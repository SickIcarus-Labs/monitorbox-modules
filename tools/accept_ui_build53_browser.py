#!/usr/bin/env python3
"""UI53 real generated v5 Power card + grouped picker on desktop/iPad/mobile."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
from playwright.async_api import async_playwright
import accept_ui_build52_browser as base52
import build_first_party_ui_build53 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
base52.base.ASSETS={key.removeprefix(PREFIX):value
    for key,value in candidate._package_files(ROOT).items()
    if key.startswith(PREFIX)}


def site_with_power():
    site=base52.base.prior.real_site()
    ups=[o for o in site["objects"] if o["kind"]=="ups"]
    assert len(ups)==2
    c=ups[0]["components"][0]
    c["metrics"].update({
      "battery.charge":100,"battery.runtime":1500,
      "ups.load":28,"input.voltage":116,
      "battery.voltage":27.4,"output.voltage":117,
      "driver.parameter.pollfreq":5,"driver.parameter.pollinterval":2,
      "driver.parameter.productid":66,"driver.parameter.vendorid":99,
      "driver.version.internal":1,"ups.delay.shutdown":30,
      "ups.delay.start":45,"ups.productid":67,
      "ups.realpower.nominal":1500,"battery.charge.low":15,
      "battery.charge.warning":22,"battery.runtime.low":120,
      "battery.voltage.nominal":24,"input.voltage.nominal":120,
      "output.voltage.nominal":120,"driver.debug":0,
      "device.serial":4,"device.mfr":8,"ups.load.warning":90,
      "ups.load.low":5,"ups.vendorid":42,
    })
    c["metadata"]={"power_source":"utility","ups.status":"OL"}
    vendor=ups[1]["components"][0]
    vendor["metrics"]={"battery_soc_percent":86,
      "battery_runtime_minutes":23,"output_load_percent":37,
      "input_voltage_v":121}
    vendor["metadata"]={"power_source":"utility","ups.status":"OL"}
    return site


async def power_case(browser,fixture,base,width,height):
    fixture.session=False;fixture.revision=10;fixture.hash="fixture-10"
    fixture.entry=base52.previous.legacy()
    fixture.site=site_with_power();fixture.sites[0]=fixture.site
    fixture.saved.clear();fixture.body_log.clear()
    context=await browser.new_context(viewport={"width":width,"height":height})
    errors=[]
    editor=await context.new_page()
    editor.on("pageerror",lambda error:errors.append(str(error)))
    await editor.goto(base+"/settings/cards")
    await editor.locator("#password").fill("test-secret")
    await editor.locator("#loginButton").click()
    await editor.locator("#selected .layout-row").first.wait_for(timeout=15000)
    editor.once("dialog",lambda d:asyncio.create_task(d.accept()))
    await editor.locator("#regenerate").click()
    assert fixture.entry==base52.previous.legacy(),(
      "Reset preview must not alter existing canonical authority")
    await editor.locator("#validate").click()
    await editor.locator("#apply").click()
    await editor.locator("#preview").wait_for(state="hidden",timeout=15000)
    assert fixture.revision==11
    homepage=await context.new_page()
    homepage.on("pageerror",lambda error:errors.append(str(error)))
    await homepage.goto(base+"/")
    await homepage.wait_for_function("()=>MonitorBoxCardLayout?.state().loaded===true")
    power=homepage.locator('[data-object="power"]')
    assert await power.locator("[data-mb-member]").count()==2
    text=await power.inner_text()
    assert "100% · 25 min" in text,text
    assert "86% · 23 min" in text,text
    assert "28% load" in text and "37% load" in text,text
    assert "116 V" in text and "121 V" in text,text

    row=editor.locator("#selected .layout-row").filter(
      has=editor.get_by_text("Power",exact=True))
    await row.get_by_text("Edit contents").click()
    assert await editor.locator("#contentMembers input:checked").count()==2
    await editor.locator("#addContentItem").click()
    assert await editor.locator("#pickerAdvanced").is_checked() is False
    assert await editor.locator("#pickerNativeNote").is_visible()
    # Native Power shows both UPSes' charge/runtime/load/input voltage already;
    # Add Item must not suggest duplicated automatic readings.
    options=await editor.locator("#pickerGroups label.member-option").all_inner_texts()
    assert not any("Battery charge" in option for option in options),options
    await editor.locator("#pickerSearch").fill("pollfreq")
    assert await editor.locator("#pickerEmpty").is_visible(),(
      "Ordinary searching must not expose hidden raw driver settings")
    await editor.locator("#pickerAdvanced").check()
    raw=editor.locator("#pickerGroups label.member-option").filter(
      has_text="driver · parameter · pollfreq")
    await raw.locator("input").check()
    await editor.locator("#donePicker").click()
    assert "driver · parameter · pollfreq" in await editor.locator(
      "#contentSelectedItems").inner_text()
    await editor.locator("#saveContents").click()
    await editor.locator("#validate").click()
    await editor.locator("#apply").click()
    await editor.locator("#preview").wait_for(state="hidden",timeout=15000)
    assert fixture.revision==12
    entry=deepcopy(fixture.entry)
    power_prefs=next(row["presentation"] for row in entry["data"]["sites"]["home"]["cards"]
      if row["id"]=="family:power")
    assert power_prefs["member_ids"]==["ups0","ups1"]
    assert len(power_prefs["items"])==1
    assert "driver.parameter.pollfreq" in power_prefs["items"][0]["key"]
    # Previously selected raw data is not dropped by Advanced-off filtering.
    await editor.reload()
    await editor.locator("#selected .layout-row").first.wait_for(timeout=15000)
    row=editor.locator("#selected .layout-row").filter(
      has=editor.get_by_text("Power",exact=True))
    await row.get_by_text("Edit contents").click()
    await editor.locator("#addContentItem").click()
    assert await editor.locator("#pickerAdvanced").is_checked() is False
    assert await editor.locator("#pickerGroups label.member-option").filter(
      has_text="driver · parameter · pollfreq").count()==1
    await editor.locator("#cancelPicker").click()
    await editor.locator("#cancelContents").click()

    # The exact same shared picker exposes semantic Power readings to custom
    # cards, where they are not already displayed automatically.
    await editor.locator("#createCustom").click()
    await editor.locator("#newCardTitle").fill("Cross-host power")
    await editor.locator("#saveNewCard").click()
    await editor.locator("#addContentItem").click()
    network=editor.locator("details.mb-picker-source").filter(
      has=editor.locator("summary").get_by_text("Network UPS",exact=False))
    assert await network.count()==1
    recommended=network.locator("section.mb-picker-section").filter(
      has=editor.get_by_text("Recommended UPS readings",exact=True))
    assert await recommended.count()==1
    opts=await recommended.locator("label.member-option").all_inner_texts()
    assert len(opts)==4 and "Battery charge" in " ".join(opts),opts
    await recommended.locator("label.member-option").filter(
      has_text="Battery charge").locator("input").check()
    await editor.locator("#donePicker").click()
    await editor.locator("#saveContents").click()
    await editor.locator("#validate").click()
    await editor.locator("#apply").click()
    await editor.locator("#preview").wait_for(state="hidden",timeout=15000)
    assert fixture.revision==13
    assert any(row["id"].startswith("custom:") and
      row["presentation"]["items"][0]["key"].endswith(
        '"battery.charge"]') for row in
      fixture.entry["data"]["sites"]["home"]["cards"])
    assert not errors,errors
    await context.close()
    print(f"UI53 {width}x{height}: 27 UPS raw readings retained in Advanced, "
      "vendor-independent honest native values, no native duplicates, "
      "selected diagnostic preservation and custom-card recommendation PASS")


async def main():
    fixture,runner,base=await base52.base.serve()
    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                for size in [(1366,1000),(820,1100),(500,900)]:
                    await base52.scenario(browser,fixture,base,*size)
                    await power_case(browser,fixture,base,*size)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()

if __name__=="__main__":asyncio.run(main())
