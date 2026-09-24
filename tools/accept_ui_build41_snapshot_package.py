#!/usr/bin/env python3
"""UI41 reproducible package, opaque-layout admission and immutable UI40 test."""
from __future__ import annotations

import ast
import hashlib
import json
import tempfile
from pathlib import Path

import build_first_party_ui_build40 as parent
import build_first_party_ui_build41 as candidate
import stage_p1_85_ui_build40 as stage40
import stage_p3_219_ui_build41 as stage41

ROOT=Path(__file__).resolve().parent.parent


def accept() -> None:
    source=candidate._sources(ROOT)
    assert set(source)==set(candidate.SOURCE_BLOBS)
    assert candidate.UI_GENERATION=="1.5.0-41"
    assert b"homepage_origin" in source["card-layout-policy.js"]
    assert b"system_role" in source["card-layout-policy.js"]
    assert b"visible" in source["card-layout-policy.js"]
    assert b"/api/v2/config/module-preferences/" in source["card-layout-editor.js"]
    assert b"X-MonitorBox-CSRF" in source["card-layout-editor.js"]
    assert b"content_hash" in source["card-layout-editor.js"]
    assert b"card-layout-policy.js" in source["card-layout-editor.html"]

    predecessor=parent._package_files(ROOT)
    candidate_files=candidate._package_files(ROOT)
    old=parent.TARGET_IMPORT_PACKAGE+"/"
    new=candidate.TARGET_IMPORT_PACKAGE+"/"
    assert {p.removeprefix(old) for p in predecessor} | {
        "assets/"+name for name in source
    } == {p.removeprefix(new) for p in candidate_files}
    for name,content in source.items():
        assert candidate_files[new+"assets/"+name] == content

    old_init=predecessor[old+"__init__.py"]
    new_init=candidate_files[new+"__init__.py"]
    program=ast.parse(new_init.decode("utf-8"))
    installer=next(node for node in program.body if isinstance(node,ast.FunctionDef)
        and node.name=="install")
    first_two=[node.value.func.id for node in installer.body[:2]]
    assert first_two == [
        "_require_card_projection_contract","_require_opaque_preference_contract"
    ],first_two
    assert b"MODULE_PREFERENCES_CONTRACT_VERSION" in new_init
    assert b"MODULE_PREFERENCES_INITIALIZATION_CONTRACT_VERSION" in new_init
    assert b"register_preference_default" in new_init
    assert isinstance(installer.body[2],ast.Expr)
    registration=installer.body[2].value
    assert isinstance(registration,ast.Call)
    assert isinstance(registration.func,ast.Name)
    assert registration.func.id=="register_default"
    assert registration.args[1].value=="com.sickicarus.monitorbox.ui"
    automatic=ast.literal_eval(registration.args[2])
    assert automatic=={"schema_version":1,"data":{"sites":{}}}
    assert b"/settings/cards" in new_init
    assert b'"/settings/cards", dashboard_cards_page' in new_init
    assert b"ui_preferences" not in old_init

    # UI40 remains untouched apart from deterministic generation identity
    # updates. No destructive 36-39 side path may appear in this candidate.
    for item,payload in predecessor.items():
        name=item.removeprefix(old)
        if name in ("__init__.py","assets/dashboard.html"):
            continue
        expected=payload.replace(parent.UI_GENERATION.encode(),candidate.UI_GENERATION.encode())
        expected=expected.replace(old[:-1].encode(),new[:-1].encode())
        assert candidate_files[new+name]==expected,name
    assert candidate_files[new+"assets/card-projection.js"] == predecessor[old+"assets/card-projection.js"]
    homepage=candidate_files[new+"assets/dashboard.html"].decode("utf-8")
    assert homepage.count("card-projection.js")==1
    assert homepage.count("card-layout-policy.js")==1
    assert homepage.count("card-layout.js")==1
    assert homepage.index("card-projection.js")<homepage.index("card-layout-policy.js")<homepage.index("card-layout.js")

    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        first=candidate.build(ROOT,root/"build-a").read_bytes()
        second=candidate.build(ROOT,root/"build-b").read_bytes()
        assert first==second
        digest=hashlib.sha256(first).hexdigest()
        assert len(digest)==64
        catalog=root/"catalog.source.json"
        catalog.write_bytes((ROOT/"catalog.source.json").read_bytes())
        assert stage40.stage(catalog) is True
        assert stage41.stage(catalog) is True
        snapshot=catalog.read_bytes()
        assert stage41.stage(catalog) is False
        assert catalog.read_bytes()==snapshot
        modules=json.loads(snapshot)["modules"]
        assert len([m for m in modules if stage40.identity(m)==stage40.RELEASE])==1
        assert len([m for m in modules if stage41.identity(m)==stage41.RELEASE])==1
        assert stage41.ENTRY["manifest"]["requires_core"]==">=2.6.0 <3.0.0"
        print(f"UI41 immutable-parent, dual-contract and reproducible archive: PASS sha256={digest}")


if __name__=="__main__":
    accept()
