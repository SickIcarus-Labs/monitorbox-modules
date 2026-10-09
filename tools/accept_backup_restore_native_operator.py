"""Unreleased native operator HTTP admission/auth/progress contract tests.

These tests are not approval for a signed module release: existing build 6
routes and periodic scheduler remain untouched. Only a future build can
activate this module through the signed first-party module host.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "tools"))
sys.path.insert(0,str(ROOT / "sources/backup-restore/1.0.3-build4"))
# Existing test fixture supplies the legacy v2 manager stub without mutating
# the installed signed Core code, just as vault acceptance does.
import accept_backup_restore_native_vault  # noqa:F401,E402
from backup_restore_native_operator import NativeBackupOperator, PREFIX  # noqa:E402
from backup_restore_native_workflow import NativeBackupWorkflowError  # noqa:E402


class FakeAuth:
    def require(self, request, csrf=False):
        if request.headers.get("X-Test-Session") != "admin":
            raise web.HTTPUnauthorized(text="admin authentication required")
        if csrf and request.headers.get("X-MonitorBox-CSRF") != "test-csrf":
            raise web.HTTPForbidden(text="CSRF required")
        return SimpleNamespace(actor="test-admin")


class FakeJob:
    def __init__(self, *, kind, phase="accepted"):
        self.kind = kind
        self.phase = phase
        self.request_id = "a" * 32
        self.planned_backup_id = "20261009T200000Z-aaaaaaaa"

    def public(self):
        return {
            "request_id":self.request_id, "phase":self.phase,
            "kind":self.kind, "backup_id":(
                self.planned_backup_id if self.phase == "committed" else None
            ),
        }


class FakeWorkflow:
    def __init__(self):
        self.job=None
        self.calls=[]
        self.unresolved=False

    def request(self, *,kind,include_previous):
        self.calls.append(("request",kind,include_previous))
        if self.unresolved:
            self.job=FakeJob(kind=kind,phase="requested")
            raise NativeBackupWorkflowError("snapshot may have started")
        self.job=FakeJob(kind=kind)
        return self.job

    def inspect(self):
        self.calls.append(("inspect",))
        return self.job

    def advance(self):
        self.calls.append(("advance",))
        return self.job


class OperatorHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workflow=FakeWorkflow()
        self.auth=FakeAuth()
        self.operator=NativeBackupOperator(
            SimpleNamespace(auth=self.auth),workflow=self.workflow,
        )
        self.app=web.Application()
        self.operator.install(self.app)
        self.client=TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    @staticmethod
    def authorized(*, csrf=True):
        headers={"X-Test-Session":"admin"}
        if csrf:
            headers["X-MonitorBox-CSRF"]="test-csrf"
        return headers

    async def test_manual_submit_accepted_pending_not_a_saved_zip(self):
        result=await self.client.post(
            PREFIX+"/native/backups",data="{}",
            headers=self.authorized(),
        )
        self.assertEqual(result.status,202)
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        data=await result.json()
        self.assertEqual(data["phase"],"accepted")
        self.assertIsNone(data["backup_id"])
        self.assertFalse(data["committed"])
        self.assertEqual(data["status_url"],PREFIX+"/native/status")
        self.assertIn(("request","manual",True),self.workflow.calls)

    async def test_requested_scheduled_run_is_not_claimed_as_automatic_schedule(self):
        result=await self.client.post(
            PREFIX+"/native/schedule/run",data="{}",
            headers=self.authorized(),
        )
        self.assertEqual(result.status,202)
        self.assertEqual((await result.json())["phase"],"accepted")
        self.assertIn(("request","scheduled",True),self.workflow.calls)

    async def test_unauthorized_and_missing_csrf_never_invoke_backup(self):
        for address in ("native/backups","native/schedule/run"):
            r=await self.client.post(PREFIX+"/"+address,data="{}")
            self.assertEqual(r.status,401)
            r=await self.client.post(
                PREFIX+"/"+address,data="{}",
                headers=self.authorized(csrf=False),
            )
            self.assertEqual(r.status,403)
        self.assertFalse(any(row[0]=="request" for row in self.workflow.calls))

    async def test_browser_cannot_supply_opaque_job_id_generation_or_path(self):
        response=await self.client.post(
            PREFIX+"/native/backups",
            json={"generation":"x"*32,"path":"/etc","job_id":"a"*32},
            headers=self.authorized(),
        )
        self.assertEqual(response.status,400)
        self.assertFalse(any(row[0]=="request" for row in self.workflow.calls))

    async def test_status_is_authenticated_read_only_and_never_transfers_zip(self):
        self.workflow.job=FakeJob(kind="manual",phase="accepted")
        response=await self.client.get(PREFIX+"/native/status")
        self.assertEqual(response.status,401)
        response=await self.client.get(
            PREFIX+"/native/status",
            headers=self.authorized(csrf=False),
        )
        self.assertEqual(response.status,200)
        state=await response.json()
        self.assertTrue(state["active"])
        self.assertEqual(state["job"]["phase"],"accepted")
        self.assertIsNone(state["job"]["backup_id"])
        self.assertFalse(any(row[0]=="request" for row in self.workflow.calls))

    async def test_after_core_restart_pending_intent_is_visible_to_status(self):
        self.workflow.unresolved=True
        response=await self.client.post(
            PREFIX+"/native/backups",data="{}",
            headers=self.authorized(),
        )
        self.assertEqual(response.status,503)
        status=await self.client.get(
            PREFIX+"/native/status",headers=self.authorized(),
        )
        self.assertEqual(status.status,200)
        item=(await status.json())["job"]
        self.assertEqual(item["phase"],"requested")
        self.assertIsNone(item["backup_id"])

    async def test_background_progress_polls_persisted_state_not_request_memory(self):
        # The background loop starts independently of any HTTP request and
        # picks up the recovered journal's accepted work after a Core restart.
        self.workflow.job=FakeJob(kind="scheduled",phase="accepted")
        await asyncio.sleep(0.1)
        self.assertIn(("advance",),self.workflow.calls)

    async def test_report_committed_only_when_durable_journal_says_committed(self):
        self.workflow.job=FakeJob(kind="manual",phase="committed")
        response=await self.client.get(
            PREFIX+"/native/status",headers=self.authorized(),
        )
        payload=await response.json()
        self.assertFalse(payload["active"])
        self.assertEqual(payload["job"]["phase"],"committed")
        self.assertEqual(payload["job"]["backup_id"],self.workflow.job.planned_backup_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
