#!/usr/bin/env python3
"""Unsigned v3 B7 assembly, native-only operator and browser contract tests.

Actual cryptographic signatures are verified by the Core/Supervisor Go
acceptance tests from the stacked PRs. All fixture ZIPs here are synthetic;
none of these tests authorizes a release, installation or v3 restore.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT=Path(__file__).resolve().parents[1]
BUILDER=ROOT/"tools/build_first_party_backup_restore_b7.py"
PACKAGE="com.sickicarus.monitorbox.backup-restore-2.0.0-build7.zip"
PREFIX="monitorbox_backup_restore_b7"
EXPECTED={
    PREFIX+suffix+".py" for suffix in (
        "", "_application", "_native_jobs","_native_archive",
        "_native_vault","_native_workflow","_native_operator",
        "_native_schedule","_vault","_policy","_destinations",
        "_restore_preflight",
    )
}
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"sources/backup-restore/1.0.3-build4"))
# Test-only Core v2 backup import stubs, preserving application admission scope.
import accept_backup_restore_native_vault  # noqa:F401,E402
from accept_backup_restore_native_vault import (  # noqa:E402
    make_native_zip, verify_test_signed_closure,
)
from accept_backup_restore_native_workflow import NativeAuthority  # noqa:E402


def build_unsigned(output:Path)->Path:
    subprocess.run([sys.executable,str(BUILDER),"--output-dir",str(output)],check=True,cwd=ROOT)
    return output/PACKAGE


def check_bundle(package:Path)->str:
    with zipfile.ZipFile(package) as archive:
        names=set(archive.namelist())
        assert names==EXPECTED,(sorted(EXPECTED-names),sorted(names-EXPECTED))
        for name in names:
            source=archive.read(name).decode("utf-8")
            compile(source,name,"exec")
            if name.endswith("_vault.py"):
                assert "from monitorbox.v2.appliance_backup" not in source
                assert "ApplianceBackupManager(" not in source
        entry=archive.read(PREFIX+".py").decode()
        app=archive.read(PREFIX+"_application.py").decode()
        for piece in (
            'MODULE_VERSION = "2.0.0"', "MODULE_BUILD = 7",
            'REQUIRES_CORE = ">=3.0.0 <4.0.0"',
            "NativeBackupWorkflow(platform)", "NativeScheduledBackup(workflow",
        ):
            assert piece in entry,piece
        for forbidden in (
            "ApplianceRestoreHandoff", "ApplianceBackupManager(platform.root)",
            "restore/confirm", "restore/file/preview",
        ):
            assert forbidden not in entry and forbidden not in app,forbidden
        tree=ast.parse(app)
        literal=next(node.value for node in tree.body if isinstance(node,ast.Assign) and any(
            isinstance(target,ast.Name) and target.id=="_PAGE" for target in node.targets))
        page=ast.literal_eval(literal)
        for required in (
            "native/status","native/backups","native/schedule/run",
            "committed","pending","Restore is intentionally unavailable",
            "Inspect ZIP signatures","native/restore/preflight-file",
            'disabled aria-disabled="true"',
        ):
            assert required in page,required
        scripts=re.findall(r"<script>(.*?)</script>",page,flags=re.DOTALL)
        assert len(scripts)==1
        return scripts[0]


class Auth:
    def require(self,request,csrf=False):
        if request.headers.get("X-Test-Session")!="admin":
            raise web.HTTPUnauthorized()
        if csrf and request.headers.get("X-MonitorBox-CSRF")!="test-csrf":
            raise web.HTTPForbidden()
        return SimpleNamespace(actor="unsigned-test-admin")


class PackageAcceptance(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=tempfile.TemporaryDirectory()
        cls.output2=tempfile.TemporaryDirectory()
        cls.archive_one=build_unsigned(Path(cls.output.name))
        cls.archive_two=build_unsigned(Path(cls.output2.name))
        assert hashlib.sha256(cls.archive_one.read_bytes()).digest()==hashlib.sha256(
            cls.archive_two.read_bytes()
        ).digest(),"B7 assembly nondeterministic"
        cls.script=check_bundle(cls.archive_one)
        cls.page=cls.archive_one
        cls.previous_sys_path=sys.path[:]
        sys.path.insert(0,str(cls.archive_one))
        import importlib
        cls.module=importlib.import_module(PREFIX)
        operator=importlib.import_module(PREFIX+"_native_operator")
        # Exercise the real packaged startup worker without waiting five
        # seconds per regression; only alter synthetic test runner cadence.
        operator.PROGRESS_INTERVAL_SECONDS=0.02

    @classmethod
    def tearDownClass(cls):
        sys.path[:]=cls.previous_sys_path
        cls.output.cleanup()
        cls.output2.cleanup()
        for key in list(sys.modules):
            if key.startswith(PREFIX):
                sys.modules.pop(key,None)

    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.synthetic=make_native_zip(self.root/"trusted.zip")
        self.native=NativeAuthority(self.synthetic)
        self.native.phase="preparing"
        self.app=web.Application()
        self.module.install(self.app,platform=SimpleNamespace(
            root=self.root,auth=Auth(),request_restart=None,
            native_full_archive=self.native,
        ))
        self.client=TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    @staticmethod
    def headers(*,csrf=True):
        h={"X-Test-Session":"admin"}
        if csrf:h["X-MonitorBox-CSRF"]="test-csrf"
        return h

    async def test_unsigned_package_compilation_determinism_and_js_syntax(self):
        assert self.archive_one.is_file()
        node=shutil.which("node")
        if node is None:
            self.skipTest("Node.js unavailable on this test runner")
        script=Path(self.temp.name)/"b7.js"
        script.write_text(self.script,encoding="utf-8")
        subprocess.run([node,"--check",str(script)],check=True)

    async def test_candidate_status_requires_admin_and_does_not_expose_native_secret(self):
        unauth=await self.client.get("/api/v2/config/backup-restore/native/status")
        self.assertEqual(unauth.status,401)
        response=await self.client.get(
            "/api/v2/config/backup-restore/native/status",headers=self.headers(csrf=False)
        )
        self.assertEqual(response.status,200)
        assert (await response.json())=={"active":False,"job":None}

    async def test_inherited_v2_writer_cannot_be_constructed_or_called(self):
        import importlib
        raw_vault=importlib.import_module(PREFIX+"_vault")
        with self.assertRaisesRegex(raw_vault.BackupVaultError,"signed Supervisor"):
            raw_vault.BackupVault(self.root)
        with self.assertRaisesRegex(raw_vault.BackupVaultError,"Supervisor snapshot"):
            raw_vault.BackupVault.create(
                object(),label="legacy-must-not-run",kind="manual"
            )

    async def test_no_restore_routes_or_legacy_handoff(self):
        for route in (
            "/api/v2/config/backup-restore/restore/confirm",
            "/api/v2/config/backup-restore/restore/file/preview",
            "/api/v2/config/backup-restore/backups/test/restore/preview",
        ):
            response=await self.client.post(route,headers=self.headers(),data=b"{}")
            self.assertEqual(response.status,404,route)
        page=await self.client.get("/backup-restore")
        self.assertEqual(page.status,200)
        html=await page.text()
        self.assertIn("Restore is intentionally unavailable",html)
        self.assertNotIn("ApplianceRestoreHandoff",html)

    async def test_manual_ui_route_returns_pending_until_signed_vault_commit(self):
        endpoint="/api/v2/config/backup-restore"
        denied=await self.client.post(endpoint+"/native/backups",data="{}")
        self.assertEqual(denied.status,401)
        rejected=await self.client.post(endpoint+"/native/backups",data="{}",
                                        headers=self.headers(csrf=False))
        self.assertEqual(rejected.status,403)
        accepted=await self.client.post(endpoint+"/native/backups",data="{}",
                                        headers=self.headers())
        self.assertEqual(accepted.status,202)
        body=await accepted.json()
        self.assertFalse(body["committed"])
        self.assertIsNone(body["backup_id"])
        status=await self.client.get(endpoint+"/native/status",headers=self.headers())
        self.assertEqual((await status.json())["job"]["phase"],"accepted")
        # HTTP receipt doesn't populate a saved ZIP, even if Core's first-party
        # worker eventually restarts after quiescence.
        listing=await self.client.get(endpoint+"/native/backups",headers=self.headers())
        self.assertEqual((await listing.json())["backups"],[])
        self.native.phase="ready"
        # The installed, versioned module's real startup task (not a tools/
        # prototype) must observe its durable job and commit signed ZIP+metadata.
        committed=None
        for _ in range(80):
            await asyncio.sleep(0.025)
            state=await self.client.get(endpoint+"/native/status",headers=self.headers())
            content=await state.json()
            if content.get("job",{}).get("phase")=="committed":
                committed=content["job"]
                break
        self.assertIsNotNone(committed,"packaged Core progress task failed to commit")
        self.assertEqual(committed["backup_id"],committed["planned_backup_id"])
        listing=await self.client.get(endpoint+"/native/backups",headers=self.headers())
        records=(await listing.json())["backups"]
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]["backup_id"],committed["backup_id"])
        download=await self.client.get(
            endpoint+"/native/backups/"+committed["backup_id"]+"/download",
            headers=self.headers(),
        )
        self.assertEqual(download.status,200)
        self.assertEqual(await download.read(),self.synthetic.read_bytes())

    async def test_installed_scheduled_route_waits_for_signed_vault_publication(self):
        endpoint="/api/v2/config/backup-restore"
        response=await self.client.post(
            endpoint+"/native/schedule/run",data="{}",headers=self.headers(),
        )
        self.assertEqual(response.status,202)
        item=await response.json()
        self.assertFalse(item["committed"])
        self.assertIsNone(item["backup_id"])
        before=await self.client.get(endpoint+"/native/backups",headers=self.headers())
        self.assertEqual((await before.json())["backups"],[])
        self.native.phase="ready"
        for _ in range(80):
            await asyncio.sleep(0.025)
            status=await self.client.get(endpoint+"/native/status",headers=self.headers())
            result=await status.json()
            if result.get("job",{}).get("phase")=="committed":
                self.assertEqual(result["job"]["kind"],"scheduled")
                break
        else:
            self.fail("signed scheduled ZIP did not become committed")
        saved=await self.client.get(endpoint+"/native/backups",headers=self.headers())
        self.assertEqual((await saved.json())["backups"][0]["kind"],"scheduled")

    async def test_pending_destination_prevents_new_manual_job(self):
        import importlib
        operator_module=importlib.import_module(PREFIX+"_native_operator")
        destination_module=importlib.import_module(PREFIX+"_destinations")
        class Existing:
            kind="scheduled"
            phase="committed"
        class FakeWorkflow:
            def __init__(self):
                self.job=Existing()
                self.calls=0
            def inspect(self):
                return self.job
            def request(self,**kwargs):
                self.calls+=1
                return SimpleNamespace(request_id="f"*32,phase="accepted")
        class FakeSchedule:
            fail=True
            def finalize_committed(self):
                if self.fail:
                    raise destination_module.BackupDestinationError("unavailable")
                return {"finalized":True}
            def run_due(self,**kwargs):
                return {"created":False}
        workflow=FakeWorkflow()
        schedule=FakeSchedule()
        app=web.Application()
        operator_module.NativeBackupOperator(
            SimpleNamespace(auth=Auth()),workflow=workflow,scheduled=schedule,
        ).install(app)
        client=TestClient(TestServer(app))
        await client.start_server()
        try:
            endpoint="/api/v2/config/backup-restore/native/backups"
            blocked=await client.post(endpoint,data="{}",headers=self.headers())
            self.assertEqual(blocked.status,409)
            self.assertEqual(workflow.calls,0)
            self.assertIsInstance(workflow.job,Existing)
            schedule.fail=False
            accepted=await client.post(endpoint,data="{}",headers=self.headers())
            self.assertEqual(accepted.status,202)
            self.assertEqual(workflow.calls,1)
        finally:
            await client.close()

    async def test_chunked_large_request_is_rejected_before_snapshot(self):
        endpoint="/api/v2/config/backup-restore/native/backups"
        async def upload():
            yield b"{}"
            yield b"x"*4096
        response=await self.client.post(
            endpoint,data=upload(),headers=self.headers(),
        )
        self.assertEqual(response.status,413)
        status=await self.client.get(
            endpoint.replace("/backups","/status"),
            headers=self.headers(),
        )
        self.assertIsNone((await status.json())["job"])
        self.assertEqual(self.native.started,0)

    async def test_uploaded_signed_zip_preflight_is_read_only_and_fails_closed(self):
        api="/api/v2/config/backup-restore/native/restore/preflight-file"
        data=self.synthetic.read_bytes()
        missing=await self.client.post(api,data=data,headers={"Content-Type":"application/zip"})
        self.assertEqual(missing.status,401)
        invalid=await self.client.post(
            api,data=data,headers={
                **self.headers(csrf=False),"Content-Type":"application/zip"
            },
        )
        self.assertEqual(invalid.status,403)
        before=len(await self._saved_list())
        signed=await self.client.post(
            api,data=data,headers={**self.headers(),"Content-Type":"application/zip"}
        )
        self.assertEqual(signed.status,200)
        response=await signed.json()
        self.assertTrue(response["verified"])
        self.assertFalse(response["restorable"])
        self.assertEqual(response["source"],"uploaded-file")
        self.assertEqual(response["format"],"monitorbox-successor-full-v1")
        self.assertEqual(response["zip_bytes"],len(data))
        self.assertEqual(response["sha256"],hashlib.sha256(data).hexdigest())
        self.assertNotIn("config",response)
        self.assertNotIn("password",response)
        self.assertNotIn("restore_token",response)
        self.assertEqual(len(await self._saved_list()),before)
        scratch=self.root/"saved-backups"/".native-restore-preflight"
        self.assertTrue(scratch.is_dir())
        self.assertEqual(list(scratch.iterdir()),[])

        corrupted=data[:len(data)//2]+bytes([data[len(data)//2]^0x80])+data[len(data)//2+1:]
        refused=await self.client.post(
            api,data=corrupted,headers={**self.headers(),"Content-Type":"application/zip"}
        )
        self.assertEqual(refused.status,422)
        self.assertEqual(list(scratch.iterdir()),[])
        self.assertEqual(len(await self._saved_list()),before)

        # Entirely self-consistent unsigned archive with no executable trust
        # must still fail the Supervisor validator, not just member hashes.
        self.native.invalid_signature=True
        independent=await self.client.post(
            api,data=data,headers={**self.headers(),"Content-Type":"application/zip"}
        )
        self.assertEqual(independent.status,422)
        self.assertEqual(list(scratch.iterdir()),[])
        self.assertEqual(len(await self._saved_list()),before)
        self.native.invalid_signature=False

    async def test_saved_vault_zip_preview_does_not_commit_or_modify_backup(self):
        endpoint="/api/v2/config/backup-restore"
        self.native.phase="ready"
        begin=await self.client.post(
            endpoint+"/native/backups",data="{}",headers=self.headers()
        )
        self.assertEqual(begin.status,202)
        committed=None
        for _ in range(80):
            await asyncio.sleep(0.025)
            state=await self.client.get(endpoint+"/native/status",headers=self.headers())
            result=await state.json()
            if result.get("job",{}).get("phase")=="committed":
                committed=result["job"]
                break
        self.assertIsNotNone(committed)
        backup=committed["backup_id"]
        existing=await self._saved_list()
        self.assertEqual(len(existing),1)

        path=endpoint+"/native/restore/preflight/"+backup
        no_auth=await self.client.post(path,data="{}")
        self.assertEqual(no_auth.status,401)
        no_csrf=await self.client.post(path,data="{}",headers=self.headers(csrf=False))
        self.assertEqual(no_csrf.status,403)
        bad_body=await self.client.post(path,data="{}",headers=self.headers())
        self.assertEqual(bad_body.status,400)
        checked=await self.client.post(path,data=b"",headers=self.headers())
        self.assertEqual(checked.status,200)
        result=await checked.json()
        self.assertEqual(result["source"],"saved-vault")
        self.assertFalse(result["restorable"])
        self.assertEqual(result["sha256"],existing[0]["sha256"])
        self.assertEqual(await self._saved_list(),existing)
        forbidden=await self.client.post(
            endpoint+"/native/restore/commit",
            data="{}",headers=self.headers()
        )
        self.assertEqual(forbidden.status,404)

    async def test_core_restart_reaps_only_stale_private_preview_not_recent_or_unowned(self):
        import importlib
        preflight=importlib.import_module(PREFIX+"_restore_preflight")
        scratch=self.root/"saved-backups"/".native-restore-preflight"
        scratch.mkdir(mode=0o700,exist_ok=True)
        stale=scratch/".inspect-abcdefgh"
        stale.mkdir(mode=0o700)
        (stale/"uploaded.zip").write_bytes(b"PRIVATE_ARCHIVE_CANNOT_PERSIST")
        os.chmod(stale/"uploaded.zip",0o600)
        recent=scratch/".inspect-ijklmnop"
        recent.mkdir(mode=0o700)
        outsider=scratch/"module-elsewhere"
        outsider.mkdir(mode=0o700)
        now=__import__("time").time()
        old=now-preflight.ABANDONED_UPLOAD_SECONDS-60
        os.utime(stale,(old,old))
        os.utime(outsider,(old,old))
        verifier=preflight.NativeRestorePreflight(
            SimpleNamespace(),SimpleNamespace(
                vault=SimpleNamespace(path=self.root/"saved-backups")
            ),
        )
        await verifier.recover_abandoned(self.app)
        self.assertFalse(stale.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(outsider.exists())

        # A stale-looking but symlinked owned stage must not be traversed
        # toward arbitrary data outside the protected vault.
        external=self.root/"unrelated-data"
        external.mkdir(mode=0o700)
        (external/"keep.txt").write_text("NOT_PART_OF_UPLOAD")
        link=scratch/".inspect-qrstuvwx"
        link.symlink_to(external,target_is_directory=True)
        with self.assertRaises(Exception):
            await verifier.recover_abandoned(self.app)
        self.assertEqual((external/"keep.txt").read_text(),"NOT_PART_OF_UPLOAD")
        link.unlink()

    async def test_chunked_oversize_signed_upload_refuses_before_verification(self):
        import importlib
        preflight=importlib.import_module(PREFIX+"_restore_preflight")
        original=preflight.MAX_UPLOAD_BYTES
        preflight.MAX_UPLOAD_BYTES=512
        try:
            async def chunks():
                yield b"x"*350
                yield b"y"*350
            reply=await self.client.post(
                "/api/v2/config/backup-restore/native/restore/preflight-file",
                data=chunks(),
                headers={**self.headers(),"Content-Type":"application/zip"},
            )
            self.assertEqual(reply.status,413)
            scratch=self.root/"saved-backups"/".native-restore-preflight"
            self.assertTrue(scratch.is_dir())
            self.assertEqual(list(scratch.iterdir()),[])
        finally:
            preflight.MAX_UPLOAD_BYTES=original

    async def _saved_list(self):
        response=await self.client.get(
            "/api/v2/config/backup-restore/native/backups",
            headers=self.headers(),
        )
        self.assertEqual(response.status,200)
        return (await response.json())["backups"]

    async def test_candidate_policy_requires_csrf_and_preserves_native_schedule(self):
        endpoint="/api/v2/config/backup-restore/native/policy"
        unauthorized=await self.client.get(endpoint)
        self.assertEqual(unauthorized.status,401)
        old=await self.client.get(endpoint,headers=self.headers(csrf=False))
        self.assertEqual((await old.json())["policy"]["enabled"],False)
        config={
            "enabled":True,"interval_hours":12,"retention_count":5,
            "retention_bytes":10737418240,"destination_type":None,
            "destination_path":None,
        }
        deny=await self.client.put(endpoint,json=config,headers=self.headers(csrf=False))
        self.assertEqual(deny.status,403)
        put=await self.client.put(endpoint,json=config,headers=self.headers())
        self.assertEqual(put.status,200)
        reread=await self.client.get(endpoint,headers=self.headers(csrf=False))
        self.assertEqual((await reread.json())["policy"]["interval_hours"],12)


def main():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(PackageAcceptance)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("unsigned v3 Backup/Restore 2.0.0 build7 candidate accepted (NO RELEASE AUTHORITY)")


if __name__=="__main__":
    main()
