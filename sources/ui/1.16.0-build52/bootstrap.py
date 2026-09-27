"""UI52 module-owned clean first-bootstrap card snapshot.

No v1 default selections, site labels, front_page hints, or previous layout are
consulted. This module runs ONLY inside Core's revisioned preference initializer;
ordinary dashboard HTTP reads never commit configuration.

JS/Python parity is a REQUIRED release gate: tools/accept_ui_build52_bootstrap.py
executes the SAME inputs through this module and card-generation.js.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

FAMILIES = ("internet", "network", "cameras", "power")
RESERVED = frozenset(("monitor", "monitorbox"))
OBJECT_KINDS = {"host": "hosts", "network_device": "network",
                "remote_site": "network", "ups": "power", "camera": "cameras",
                "service": "services"}
GROUPS = ("hosts", "network", "power", "cameras", "internet", "services", "other")


def _valid_token(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 160


def _numeric(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _key(*parts: str) -> str:
    return json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))


def _normalized(value: Any) -> str:
    return re.sub(r"[\s._-]", "", str(value)).lower()


def _observed(component: Mapping, needle: str) -> float | None:
    normalized = _normalized(needle)
    for name, value in (component.get("metrics") or {}).items():
        if _normalized(name) == normalized and _numeric(value):
            return value
    return None


def _derived(component: Mapping, metric: str) -> float | None:
    if metric == "@derived.cpu_used_percent":
        idle = _observed(component, "cpu_idle_percent")
        return None if idle is None or not 0 <= idle <= 100 else 100 - idle
    if metric == "@derived.memory_used_percent":
        total = _observed(component, "memory_total_kib")
        free = _observed(component, "memory_available_kib")
        return None if total is None or free is None or not 0 <= free <= total or total <= 0 else (
            total - free
        ) / total * 100
    return None


def _title(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").replace(".", " · ").strip() or "Unnamed metric"


def _catalog(site: Mapping, live: list[Mapping]) -> list[dict]:
    """Emit the same source/item metadata used by card-item-registry.js.

    Only the metric and LIVE subset is required for automatic selections.
    A check's health is rendered natively by canonical Core state.
    """
    result = []
    site_id = site.get("id")
    matching = [
        row for row in live if row.get("site_id") == site_id
        and all(_valid_token(row.get(k)) for k in ("object_id", "check_id", "id"))
        and row.get("kind") in ("gauge", "counter_pair")
    ]
    for obj in site.get("objects") or []:
        if not isinstance(obj, Mapping) or not _valid_token(obj.get("id")) or (
            obj.get("kind") == "appliance" or obj.get("retired") is True
        ):
            continue
        source_id = obj["id"]
        items = []
        for component in obj.get("components") or []:
            if not isinstance(component, Mapping) or not _valid_token(component.get("id")):
                continue
            cid = component["id"]
            metrics = component.get("metrics") or {}
            if not isinstance(metrics, Mapping):
                continue
            units = component.get("metric_units") or (
                component.get("metadata") or {}
            ).get("metric_units") or {}
            for metric, number in metrics.items():
                if not _valid_token(metric) or not _numeric(number):
                    continue
                unit = units.get(metric) if isinstance(units.get(metric), str) else (
                    "%" if re.search(r"(?:^|[._\s])percent$", metric, re.I) else
                    "KiB" if re.search(r"(?:^|[._\s])kib$", metric, re.I) else
                    "B" if re.search(r"(?:^|[._\s])bytes$", metric, re.I) else None
                )
                items.append(dict(key=_key("object",source_id,"metric",cid,metric),
                    type="metric",sourceKind="object",sourceId=source_id,
                    componentId=cid,metricKey=metric,label=_title(metric),unit=unit,
                    value=number))
            for derived_id, label in (
                ("@derived.cpu_used_percent", "CPU utilization"),
                ("@derived.memory_used_percent", "Memory utilization"),
            ):
                value = _derived(component, derived_id)
                if value is not None:
                    items.append(dict(key=_key("object",source_id,"metric",cid,derived_id),
                        type="metric",sourceKind="object",sourceId=source_id,
                        componentId=cid,metricKey=derived_id,label=label,unit="%",
                        value=value))
        for row in matching:
            if row["object_id"] != source_id:
                continue
            label = str(row.get("label") or row["id"])
            label += " · throughput" if row["kind"] == "counter_pair" else " · live"
            items.append(dict(key=_key("object",source_id,"live",row["check_id"],row["id"]),
                type="live",sourceKind="object",sourceId=source_id,
                componentId=row["check_id"],metricKey=row["id"],label=label,
                unit=row.get("unit") if isinstance(row.get("unit"),str) else None,
                liveKind=row["kind"],trafficSubject=str(row.get("traffic_subject") or "")))
        result.extend(items)
    return result


def _host(obj: Mapping) -> bool:
    if obj.get("retired") is True or str(obj.get("id")) in RESERVED or (
        obj.get("explicit_front_page") is False
    ):
        return False
    if obj.get("system_role") == "site_gateway" and obj.get("kind") in (
        "host", "network_device"
    ):
        return True
    return obj.get("kind") == "host" and obj.get("homepage_origin") == "operator"


def _members(site: Mapping, family: str, card: Mapping) -> list[str]:
    objects = [
        row for row in site.get("objects") or []
        if isinstance(row, Mapping) and row.get("retired") is not True
    ]
    if family == "network":
        eligible = [o for o in objects if o.get("kind") == "network_device"]
    elif family == "cameras":
        eligible = [o for o in objects if o.get("kind") == "camera"]
    elif family == "power":
        eligible = [o for o in objects if o.get("kind") == "ups"]
    else:
        declared = {str(v) for v in card.get("member_object_ids") or []}
        eligible = [o for o in objects if str(o.get("id")) in declared]
    # JS localeCompare ignores casing for the ordinary public labels tested
    # here; the deterministic tie breaker is stable object ID.
    eligible.sort(key=lambda o:(str(o.get("label") or o.get("id")).casefold(),str(o.get("id"))))
    return [str(o["id"]) for o in eligible]


def _sections(family: str) -> list[str]:
    if family == "internet":
        return ["diagnosis"]
    if family == "cameras":
        return ["camera_counts","members"]
    if family in ("network","power"):
        return ["members"]
    return ["status","members"]


def _choose(rows: list[dict], predicate) -> dict | None:
    return next((item for item in rows if predicate(item)), None)


def _host_items(obj: Mapping, catalog: list[dict]) -> list[dict]:
    candidates=sorted((x for x in catalog if x["sourceId"]==obj["id"]
        and x["type"]=="live"),key=lambda x:x["key"])
    state=sorted((x for x in catalog if x["sourceId"]==obj["id"]
        and x["type"]=="metric"),key=lambda x:x["key"])
    def label(item):
        return re.sub(r"[_./-]+"," ",str(item["label"])+" "+str(item["metricKey"])).lower()
    def percent(item):
        return str(item["unit"]).lower() in ("%","percent")
    def generic_cpu(item):
        return (bool(re.search(r"\bcpu\b",label(item))) and
                not re.search(r"\b(user|system|idle)\b",label(item)))
    cpu=_choose(candidates,lambda x:percent(x) and generic_cpu(x) and
        bool(re.search(r"usage|utilization|used|total",label(x)))) or (
        _choose(candidates,lambda x:percent(x) and generic_cpu(x)))
    mem=_choose(candidates,lambda x:bool(re.search(r"\b(memory|ram|mem)\b",label(x))) and
        bool(re.search(r"\b(used|usage|utilization)\b",label(x))) and
        x["unit"] in ("B","bytes","GiB","MiB","KiB")) or (
        _choose(candidates,lambda x:percent(x) and
        bool(re.search(r"\b(memory|ram|mem)\b",label(x))) and
        bool(re.search(r"\b(used|usage|utilization)\b",label(x)))))
    network=_choose(candidates,lambda x:x["liveKind"]=="counter_pair" or
        (bool(re.search(r"ethernet|nic|network|throughput",label(x))) and
        x["unit"]=="bit/s"))
    def named(item):
        return re.sub(r"[_./-]+"," ",str(item["metricKey"])).lower()
    def measured(item):
        return _numeric(item.get("value")) or item["metricKey"].startswith("@derived.")
    st_cpu=_choose(state,lambda x:x["metricKey"]=="@derived.cpu_used_percent" and measured(x)) or (
        _choose(state,lambda x:bool(re.search(r"\bcpu\b.*(used|usage|utilization)",named(x)))
                and x["unit"]=="%" and measured(x)))
    st_mem=_choose(state,lambda x:bool(re.search(r"\b(memory|ram|mem)\b.*(used|usage)",named(x)))
        and x["unit"] in ("B","bytes","GiB","MiB","KiB") and measured(x)) or (
        _choose(state,lambda x:x["metricKey"]=="@derived.memory_used_percent" and measured(x))) or (
        _choose(state,lambda x:bool(re.search(r"\b(memory|ram|mem)\b.*(used|usage)",named(x)))
            and x["unit"]=="%" and measured(x)))
    st_storage=_choose(state,lambda x:bool(re.search(
        r"(disk|storage|filesystem|fs|pool|volume).*(used|free|available)",named(x))) and measured(x))
    st_net=_choose(state,lambda x:bool(re.search(
        r"\b(eth|ethernet|nic|network|interface|link)\b.*(used|usage|utilization)",named(x)))
        and x["unit"]=="%" and measured(x))
    selection=[cpu or st_cpu,mem or st_mem,st_storage,network or st_net]
    seen=set()
    result=[]
    for row in selection:
        if row and row["key"] not in seen:
            result.append({"key":row["key"],"mode":"value"})
            seen.add(row["key"])
    return result[:4]


def generate(site: Mapping, live_series: list[Mapping] | None = None) -> list[dict]:
    """Return v5 cards from current canonical public site evidence only."""
    if not isinstance(site, Mapping) or not isinstance(site.get("objects"),list) or (
        not isinstance(site.get("cards"),list)
    ):
        raise RuntimeError("UI52 bootstrap requires a complete live public site projection")
    catalog=_catalog(site,live_series or [])
    output=[]
    seen=set()
    for obj in site["objects"]:
        if not isinstance(obj, Mapping) or not _valid_token(obj.get("id")) or (
            not _host(obj)
        ):
            continue
        identifier="host:"+obj["id"]
        if identifier in seen:
            continue
        seen.add(identifier)
        output.append({"id":identifier,"visible":True,"presentation":{
            "schema_version":3,"native_sections":["status"],
            "member_ids":[],"items":_host_items(obj,catalog),
        }})
    families={}
    for card in site["cards"]:
        if not isinstance(card,Mapping) or card.get("kind")!="dashboard_card" or (
            not card.get("family") or card.get("family")=="services"
        ):
            continue
        family=card["family"]
        families.setdefault(family,card)
    ordered=[f for f in FAMILIES if f in families]
    ordered.extend(sorted(f for f in families if f not in FAMILIES))
    for family in ordered:
        card=families[family]
        items=[]
        if family=="internet":
            wan=[x for x in catalog if x["type"]=="live" and
                x["liveKind"]=="counter_pair" and x["trafficSubject"]=="wan"]
            if len(wan)==1:
                items=[{"key":wan[0]["key"],"mode":"value"}]
        output.append({"id":"family:"+family,"visible":True,"presentation":{
            "schema_version":3,"native_sections":_sections(family),
            "member_ids":_members(site,family,card),"items":items,
        }})
    if len(output)>128:
        raise RuntimeError("UI52 clean bootstrap exceeds 128 cards for site "+str(site.get("id")))
    return output


def first_ready_pending(entry: Mapping) -> bool:
    """Opaque module-owned opt-in; never replace an edited/restored layout."""
    if not isinstance(entry,Mapping) or entry.get("schema_version") != 5:
        return False
    data=entry.get("data")
    if not isinstance(data,Mapping) or data.get("bootstrap_pending") is not True:
        return False
    sites=data.get("sites")
    return isinstance(sites,Mapping) and bool(sites) and all(
        isinstance(row,Mapping) and row.get("mode")=="auto" and
        row.get("arranged") is not True and
        all(isinstance(card,Mapping) and not
            str(card.get("id","")).startswith("custom:")
            for card in row.get("cards",[]))
        for row in sites.values()
    )


def _fresh(app: Any, document: Mapping, *, pending: bool) -> dict:
    source=app.get("monitorbox.public_state_snapshot")
    if not callable(source):
        raise RuntimeError("UI52 bootstrap cannot initialize without canonical public state")
    snapshot=source()
    if not isinstance(snapshot,Mapping) or not isinstance(snapshot.get("sites"),list):
        raise RuntimeError("UI52 bootstrap cannot initialize incomplete public state")
    by_id={s["id"]:s for s in snapshot["sites"] if isinstance(s,Mapping) and
        isinstance(s.get("id"),str)}
    configured=[s["id"] for s in document.get("sites") or [] if isinstance(s,Mapping)
        and isinstance(s.get("id"),str)]
    if len(configured)!=len(set(configured)) or any(site not in by_id for site in configured):
        raise RuntimeError("UI52 bootstrap declared sites differ from public authority")
    live_source=app.get("monitorbox.live_series_snapshot")
    if not callable(live_source):
        # A pre-Core-#410 runtime cannot promise first-ready convergence.
        raise RuntimeError("UI52 requires Core's first-ready LIVE catalogue contract")
    live=live_source()
    if not isinstance(live,list):
        raise RuntimeError("Core first-ready LIVE catalogue returned invalid data")
    data={"sites":{
        site_id:{"mode":"auto","cards":generate(by_id[site_id],live)}
        for site_id in configured
    }}
    if pending and not live:
        data["bootstrap_pending"]=True
    return {"schema_version":5,"data":data}


def automatic_layout_snapshot(app: Any, document: Mapping, current: dict | None) -> dict:
    """Capture provisional first-launch preferences through Core's revisioned API.

    No current saved layout is ever rewritten by startup or module upgrade.
    Core alone may invoke finalize_first_ready once if the pending preference,
    the full revision/hash and the operator's restored-history pins are intact.
    """
    if current is not None:
        return current
    return _fresh(app,document,pending=True)


def finalize_first_ready(app: Any, document: Mapping, current: dict) -> dict:
    """One bounded first-ready *or no-producer timeout* conversion to final v5.

    Core verifies this entry is still the exact provisional first-launch
    preference before invoking us, and performs the atomic canonical CAS.
    The ordinary Reset button directly uses the JS generator and never waits.
    """
    if not first_ready_pending(current):
        return current
    return _fresh(app,document,pending=False)
