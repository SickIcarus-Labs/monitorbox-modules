#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sources" / "unifi" / "1.0.11-build12" / "recommendation_relationship.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("recommendation_relationship_b12", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.annotate_port_recommendation_relationships


def base_ports():
    return [
        {"device_mac":"aa:aa:aa:aa:aa:aa","device_name":"Aggregation","port_idx":7,"name":"Port 7","infrastructure_role":"uplink"},
        {"device_mac":"bb:bb:bb:bb:bb:bb","device_name":"Broad Leaf","port_idx":15,"name":"SFP+ 1","infrastructure_role":"infrastructure"},
    ]


def main() -> None:
    annotate = load_helper()

    devices = [
        {"mac":"aa:aa:aa:aa:aa:aa","name":"Aggregation","port_table":[{"port_idx":7,"name":"Port 7"}]},
        {"mac":"bb:bb:bb:bb:bb:bb","name":"Broad Leaf","port_table":[{"port_idx":15,"name":"SFP+ 1"}]},
    ]
    topology = {"edges":[{"type":"wired","downlinkMac":"aa:aa:aa:aa:aa:aa","uplinkMac":"bb:bb:bb:bb:bb:bb","downlinkPortNumber":7,"uplinkPortNumber":15}]}
    ports = base_ports()
    annotate(ports, devices, topology)
    assert ports[0]["recommendation_reason"] == "Uplink to Broad Leaf · SFP+ 1"
    assert ports[1]["recommendation_reason"] == "Inter-switch link → Aggregation · Port 7"

    # Broad Leaf may fall back to the same stat/device uplink tuples already
    # accepted as infrastructure-role authority when topology yields no edge.
    fallback_devices = [
        {"mac":"aa:aa:aa:aa:aa:aa","name":"Aggregation","uplink":{"port_idx":7,"uplink_mac":"bb:bb:bb:bb:bb:bb","uplink_remote_port":15},"port_table":[{"port_idx":7,"name":"Port 7"}]},
        {"mac":"bb:bb:bb:bb:bb:bb","name":"Broad Leaf","port_table":[{"port_idx":15,"name":"SFP+ 1"}]},
    ]
    fallback = base_ports()
    annotate(fallback, fallback_devices, None)
    assert fallback[0]["recommendation_reason"] == "Uplink to Broad Leaf · SFP+ 1"
    assert fallback[1]["recommendation_reason"] == "Inter-switch link → Aggregation · Port 7"

    # No authoritative relation still fails closed.
    untouched = base_ports()
    annotate(untouched, devices, None)
    assert "recommendation_reason" not in untouched[0]
    assert "recommendation_reason" not in untouched[1]

    print("UniFi build12 recommendation relationship acceptance: PASS")


if __name__ == "__main__":
    main()
