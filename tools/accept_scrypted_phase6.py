#!/usr/bin/env python3
"""Deterministic Phase-6C / #246 acceptance for Scrypted startup hydration."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Request:
    check_id: str
    options: dict = field(default_factory=dict)


@dataclass
class Result:
    state: str


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def load_policy(root: Path):
    path = root / "sources/scrypted/2.1.3-build4/startup_schedule.py"
    spec = importlib.util.spec_from_file_location("phase6_scrypted_startup", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def core_jitter(check_id: str, maximum: float) -> float:
    import hashlib

    value = int.from_bytes(
        hashlib.sha256(check_id.encode()).digest()[:8], "big"
    ) / (2**64 - 1)
    return value * maximum


def request(check_id: str, operation: str, jitter: float) -> Request:
    return Request(
        check_id=check_id,
        options={
            "operation": operation,
            "camera_id": check_id.rsplit("_", 1)[0],
            "scheduler_jitter_seconds": jitter,
        },
    )


def assert_legacy_jitter_converges(policy_module) -> None:
    clock = Clock()
    policy = policy_module.ScryptedStartupSchedule(clock=clock)
    windows = {"camera_state": 30.0, "snapshot": 90.0, "stream": 240.0}
    reduced: list[float] = []
    for camera in range(8):
        for operation, maximum in windows.items():
            check_id = f"camera{camera}_{operation}"
            req = request(check_id, operation, maximum)
            original = core_jitter(check_id, maximum)
            value = policy.reduce_delay(req, phase="initial", delay_seconds=original)
            assert 0 <= value <= policy_module.STARTUP_JITTER_CAP_SECONDS
            expected = core_jitter(check_id, policy_module.STARTUP_JITTER_CAP_SECONDS)
            assert abs(value - expected) < 1e-9, (check_id, value, expected)
            reduced.append(round(value, 6))

    # Provider policy preserves deterministic phasing rather than turning the cap
    # into a synchronized startup burst.
    assert len(set(reduced)) > 8
    assert max(reduced) <= policy_module.STARTUP_JITTER_CAP_SECONDS


def assert_fresh_adoption_is_bounded(policy_module) -> None:
    clock = Clock()
    policy = policy_module.ScryptedStartupSchedule(clock=clock)
    values = []
    for camera in range(8):
        check_id = f"fresh{camera}_snapshot"
        req = request(check_id, "snapshot", policy_module.STARTUP_JITTER_CAP_SECONDS)
        base = core_jitter(check_id, policy_module.STARTUP_JITTER_CAP_SECONDS)
        value = policy.reduce_delay(req, phase="initial", delay_seconds=base)
        assert value == base
        assert value <= policy_module.STARTUP_JITTER_CAP_SECONDS
        values.append(round(value, 6))
    assert len(set(values)) > 1


def assert_unknown_retries_then_truth_restores_cadence(policy_module) -> None:
    clock = Clock()
    policy = policy_module.ScryptedStartupSchedule(clock=clock)
    req = request("patio_stream", "stream", 240.0)

    # No current-boot evidence: Unknown remains acquisition state and receives one
    # deterministic short retry through the shared scheduler.
    policy.observe(req, Result("unknown"))
    retry = policy.reduce_delay(req, phase="interval", delay_seconds=300.0)
    assert policy_module.STARTUP_RETRY_MIN_SECONDS <= retry <= policy_module.STARTUP_RETRY_MAX_SECONDS
    assert not policy.hydrated(req.check_id)

    # A real failed observation is still trustworthy evidence. The policy records
    # hydration but never rewrites the result, so the UI remains truthfully red and
    # the next schedule immediately returns to configured steady-state cadence.
    failed = Result("failed")
    policy.observe(req, failed)
    assert failed.state == "failed"
    assert policy.hydrated(req.check_id)
    assert policy.reduce_delay(req, phase="interval", delay_seconds=300.0) == 300.0


def assert_late_provider_and_window_bound(policy_module) -> None:
    clock = Clock()
    policy = policy_module.ScryptedStartupSchedule(clock=clock)
    req = request("garage_snapshot", "snapshot", 90.0)

    clock.now = 50.0
    policy.observe(req, Result("unknown"))
    retry = policy.reduce_delay(req, phase="interval", delay_seconds=120.0)
    assert 5.0 <= retry <= 10.0

    # Provider becomes usable late in startup; the next provider execution supplies
    # trustworthy evidence and releases the temporary cadence automatically.
    clock.now = 58.0
    policy.observe(req, Result("healthy"))
    assert policy.hydrated(req.check_id)
    assert policy.reduce_delay(req, phase="interval", delay_seconds=120.0) == 120.0

    # A provider that never becomes observable does not get an unmanaged retry loop.
    policy.reset()
    policy.observe(req, Result("unknown"))
    clock.now += policy_module.STARTUP_ACQUISITION_WINDOW_SECONDS + 0.1
    assert policy.reduce_delay(req, phase="interval", delay_seconds=120.0) == 120.0


def assert_non_child_operations_unchanged(policy_module) -> None:
    clock = Clock()
    policy = policy_module.ScryptedStartupSchedule(clock=clock)
    req = Request(
        check_id="scrypted_inventory",
        options={"operation": "inventory", "scheduler_jitter_seconds": 240.0},
    )
    assert policy.reduce_delay(req, phase="initial", delay_seconds=200.0) == 200.0
    assert policy.reduce_delay(req, phase="interval", delay_seconds=60.0) == 60.0
    policy.observe(req, Result("healthy"))
    assert not policy.hydrated(req.check_id)


def assert_builder_contract(root: Path, policy_module) -> None:
    builder = (root / "tools/build_first_party_scrypted_213.py").read_text(encoding="utf-8")
    assert 'MODULE_VERSION = "2.1.3"' in builder
    assert "MODULE_BUILD = 4" in builder
    assert 'IMPORT_PACKAGE = "monitorbox_scrypted_v213_b4"' in builder
    assert "previous._configure()" in builder
    assert "result = await self._execute_provider(request, context)" in builder
    assert "self._startup_schedule.observe(request, result)" in builder
    assert "async def reduce_schedule_delay(" in builder
    assert '"scheduler_jitter_seconds": STARTUP_JITTER_CAP_SECONDS' in builder
    assert policy_module.STARTUP_JITTER_CAP_SECONDS == 15.0
    assert policy_module.STARTUP_ACQUISITION_WINDOW_SECONDS == 60.0


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    policy_module = load_policy(root)
    assert_legacy_jitter_converges(policy_module)
    assert_fresh_adoption_is_bounded(policy_module)
    assert_unknown_retries_then_truth_restores_cadence(policy_module)
    assert_late_provider_and_window_bound(policy_module)
    assert_non_child_operations_unchanged(policy_module)
    assert_builder_contract(root, policy_module)
    print(
        "Scrypted Phase-6C acceptance: PASS "
        "(legacy/fresh startup bounded; deterministic phasing; Unknown retries bounded; "
        "truthful Failed evidence restores steady-state cadence)"
    )


if __name__ == "__main__":
    main()
