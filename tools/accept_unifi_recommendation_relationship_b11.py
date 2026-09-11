#!/usr/bin/env python3
"""Acceptance for UniFi 1.0.10 build 11 recommendation relationship evidence."""
from __future__ import annotations
from pathlib import Path
import importlib.util

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/"sources"/"unifi"/"1.0.10-build11"/"recommendation_relationship.py"


def load_helper():
    spec=importlib.util.spec_from_file_location("recommendation_relationship",SOURCE)
    module=importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.annotate_port_recommendation_relationships


def main()->None:
    annotate=load_helper()
    devices=[
      {"mac":"aa:aa:aa:aa:aa:aa","name":"Aggregation"},
      {"mac":"bb:bb:bb:bb:bb:bb","name":"Broad Leaf"},
    ]
    ports=[
      {"device_mac":"aa:aa:aa:aa:aa:aa","device_name":"Aggregation","port_idx":7,"name":"Port 7","infrastructure_role":"uplink"},
      {"device_mac":"bb:bb:bb:bb:bb:bb","device_name":"Broad Leaf","port_idx":15,"name":"SFP+ 1","infrastructure_role":"infrastructure"},
      {"device_mac":"aa:aa:aa:aa:aa:aa","device_name":"Aggregation","port_idx":8,"name":"Port 8"},
    ]
    topology={"edges":[{"type":"wired","downlinkMac":"aa:aa:aa:aa:aa:aa","uplinkMac":"bb:bb:bb:bb:bb:bb","downlinkPortNumber":7,"uplinkPortNumber":15}]}
    annotate(ports,devices,topology)
    assert ports[0]["recommendation_reason"]=="Uplink to Broad Leaf · SFP+ 1"
    assert ports[0]["recommendation_relationship"]=={"kind":"uplink","peer_device":"Broad Leaf","peer_port":"SFP+ 1"}
    assert ports[1]["recommendation_reason"]=="Inter-switch link → Aggregation · Port 7"
    assert ports[2].get("recommendation_reason") is None

    # No authenticated topology means no invented relationship.
    untouched=[{"device_mac":"aa:aa:aa:aa:aa:aa","port_idx":7,"infrastructure_role":"uplink"}]
    annotate(untouched,devices,None)
    assert "recommendation_reason" not in untouched[0]
    print("UniFi build11 recommendation relationship acceptance: PASS")

if __name__=="__main__": main()
