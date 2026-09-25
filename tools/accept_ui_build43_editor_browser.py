#!/usr/bin/env python3
"""UI43 disposable iPad/desktop editor qualification on packaged managed assets.

Synthetic public projections and authenticated revision writes; this is not a
substitute for paired real-Core/managed-loader or physical iPad acceptance.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

from playwright.async_api import async_playwright

import accept_ui_build42_editor_browser as fixture_server
import build_first_party_ui_build43 as candidate

ROOT = Path(__file__).resolve().parent.parent
PREFIX = candidate.TARGET_IMPORT_PACKAGE + "/assets/"
PACKAGE = candidate._package_files(ROOT)
fixture_server.ASSETS = {
    p[len(PREFIX):]: body for p, body in PACKAGE.items() if p.startswith(PREFIX)
}
original_site = fixture_server.fixture_site


def composed_site():
    site = original_site()
    by_id = {obj["id"]: obj for obj in site["objects"]}
    by_id["arrrrr2"]["components"] = [
        {"id": "host-cpu", "label": "CPU", "state": "healthy",
         "metrics": {"cpu.usage": 41, "cpu.temp": 55},
         "metric_units": {"cpu.usage": "%"}},
        {"id": "host-ram", "label": "Memory", "state": "healthy",
         "metrics": {"memory.used_percent": 62}},
    ]
    by_id["goliath"]["components"] = [
        {"id": "pool", "label": "Storage pool", "state": "healthy",
         "metrics": {"pool.free_bytes": 123456789}},
    ]
    site["objects"] += [
        {"id": "aggregation", "label": "Aggregation", "kind": "network_device",
         "state": "healthy",
         "components": [{"id": "snmp", "label": "SNMP", "state": "healthy"}]},
        {"id": "rack-ups", "label": "Rack UPS", "kind": "ups",
         "state": "healthy",
         "components": [{"id": "nut", "label": "NUT", "state": "healthy",
                         "metrics": {"battery.charge": 85}}]},
        {"id": "driveway", "label": "Driveway", "kind": "camera",
         "state": "healthy", "components": []},
    ]
    site["cards"][0]["components"] = [
        {"id": "dns", "label": "DNS reachability", "state": "healthy",
         "metrics": {"dns.latency_ms": 25}},
    ]
    return site


fixture_server.fixture_site = composed_site
LEGACY_V2 = {
    "schema_version": 2,
    "data": {"sites": {"home": {
        "mode": "custom",
        "cards": [
            {"id": "host:arrrrr2", "visible": True},
            {"id": "family:network", "visible": True,
             "presentation": {"schema_version": 1,
                              "hidden_member_ids": ["aggregation"]}},
        ],
    }}},
}


async def select_item(page, search, source, label):
    await page.locator("#pickerSearch").fill(search)
    match = page.locator("#pickerGroups .mb-picker-source").filter(
        has=page.locator("summary", has_text=source)
    ).locator("label.member-option").filter(has_text=label)
    assert await match.count() == 1, (search, source, label, await match.count())
    await match.locator("input").check()


async def save_draft(page):
    await page.locator("#saveContents").click()
    assert await page.locator("#contents").is_hidden()
    await page.locator("#validate").click()
    await page.locator("#preview").wait_for(state="visible")
    await page.locator("#apply").click()
    await page.locator("#preview").wait_for(state="hidden")


def find_row(entry, prefix):
    cards = entry["data"]["sites"]["home"]["cards"]
    found = [row for row in cards if row["id"].startswith(prefix)]
    assert len(found) == 1, (prefix, found)
    return found[0]


async def accept():
    fixture, runner, base = await fixture_server.serve()
    fixture.entry = deepcopy(LEGACY_V2)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for width, height in ((820, 1100), (1366, 900)):
                    fixture.entry = deepcopy(LEGACY_V2)
                    fixture.site = composed_site()
                    fixture.revision = 10
                    fixture.hash = "fixture-hash-10"
                    fixture.session = False
                    fixture.saved.clear()
                    fixture.body_log.clear()
                    context = await browser.new_context(viewport={"width": width, "height": height})
                    page = await context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    response = await page.goto(base + "/settings/cards", wait_until="networkidle")
                    assert response and response.ok
                    await page.locator("#password").fill("test-secret")
                    await page.locator("#loginButton").click()
                    await page.locator("#selected .layout-row").first.wait_for()
                    names = await page.locator("#selected .layout-row strong").all_inner_texts()
                    assert names == ["Arrrrr2", "Network"], names
                    assert await page.locator("#available .available-item").count() < 12
                    assert await page.locator("#showDiscovered").count() == 0

                    # Existing host uses exactly the same source/item picker as custom cards.
                    host = page.locator("#selected .layout-row").filter(has_text="Arrrrr2")
                    await host.get_by_role("button", name="Edit contents").click()
                    await page.locator("#addContentItem").click()
                    await select_item(page, "cpu.usage", "Arrrrr2", "cpu · usage")
                    await page.locator("#donePicker").click()
                    assert await page.locator("#contentSelectedItems .mb-selected-item").count() == 1
                    await save_draft(page)
                    assert fixture.entry["schema_version"] == 3
                    host = find_row(fixture.entry, "host:arrrrr2")
                    assert host["presentation"]["items"][0]["mode"] == "value"
                    assert find_row(fixture.entry, "family:network")[
                        "presentation"]["hidden_member_ids"] == ["aggregation"]

                    # Compose mixed-source Infrastructure card without new checks or
                    # promoting 30 discovered hosts to top-level candidate cards.
                    await page.locator("#createCustom").click()
                    await page.locator("#newCardTitle").fill("Infrastructure")
                    await page.locator("#saveNewCard").click()
                    await page.locator("#contents").wait_for(state="visible")
                    await page.locator("#addContentItem").click()
                    await select_item(page, "cpu.usage", "Arrrrr2", "cpu · usage")
                    await select_item(page, "memory.used_percent", "Arrrrr2", "memory · used percent")
                    await select_item(page, "pool.free_bytes", "Goliath", "pool · free bytes")
                    await select_item(page, "Aggregation", "Aggregation", "Aggregation · status")
                    await select_item(page, "battery.charge", "Rack UPS", "battery · charge")
                    await page.locator("#donePicker").click()
                    assert await page.locator("#contentSelectedItems .mb-selected-item").count() == 5
                    await save_draft(page)
                    custom = find_row(fixture.entry, "custom:")
                    assert custom["presentation"]["title"] == "Infrastructure"
                    assert len(custom["presentation"]["items"]) == 5
                    assert fixture.entry["schema_version"] == 3
                    assert find_row(fixture.entry, "family:network")[
                        "presentation"]["hidden_member_ids"] == ["aggregation"]

                    # Restoring both retained snapshots reproduces exact item choices.
                    latest = deepcopy(fixture.entry)
                    fixture.entry = deepcopy(fixture.saved[0])
                    fixture.revision += 1
                    fixture.hash = f"fixture-hash-{fixture.revision}"
                    await page.reload(wait_until="networkidle")
                    assert await page.locator("#selected").get_by_text("Infrastructure").count() == 0
                    assert len(find_row(fixture.entry, "host:arrrrr2")[
                        "presentation"]["items"]) == 1
                    fixture.entry = deepcopy(latest)
                    fixture.revision += 1
                    fixture.hash = f"fixture-hash-{fixture.revision}"
                    await page.reload(wait_until="networkidle")
                    custom_row = page.locator("#selected .layout-row").filter(has_text="Infrastructure")
                    await custom_row.get_by_role("button", name="Edit contents").click()
                    assert await page.locator("#contentSelectedItems .mb-selected-item").count() == 5
                    await page.locator("#cancelContents").click()

                    # A previously saved provider item that vanishes remains
                    # present and explicitly unavailable, never silently healthy.
                    fixture.site["objects"] = [
                        item for item in fixture.site["objects"] if item["id"] != "rack-ups"
                    ]
                    await page.reload(wait_until="networkidle")
                    custom_row = page.locator("#selected .layout-row").filter(has_text="Infrastructure")
                    await custom_row.get_by_role("button", name="Edit contents").click()
                    assert "currently unavailable" in await page.locator(
                        "#contentSelectedItems").inner_text()
                    assert len(find_row(fixture.entry, "custom:")[
                        "presentation"]["items"]) == 5
                    assert not errors, errors
                    await context.close()
                    print(f"UI43 grouped editor, legacy-v2 migration, mixed-source custom "
                          f"composition, snapshot restoration, missing source: PASS {width}x{height}")
            finally:
                await browser.close()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(accept())
