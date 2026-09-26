#!/usr/bin/env python3
"""UI52 WIP browser: real generated v5 cards and visible member/editor parity."""
from __future__ import annotations
import asyncio
from copy import deepcopy
from pathlib import Path
from playwright.async_api import async_playwright
import accept_ui_build51_browser as base
import accept_ui_build50_browser as previous
import build_first_party_ui_build52 as candidate

ROOT=Path(__file__).resolve().parent.parent
PREFIX=candidate.TARGET_IMPORT_PACKAGE+"/assets/"
base.ASSETS={k.removeprefix(PREFIX):v for k,v in
  candidate._package_files(ROOT).items() if k.startswith(PREFIX)}

async def scenario(browser,fixture,url,width,height):
  fixture.session=False;fixture.revision=10;fixture.hash="fixture-10"
  fixture.saved.clear();fixture.body_log.clear()
  fixture.entry=previous.legacy()
  fixture.site=previous.real_site()
  # A remote site is not a Broad Leaf Network child.
  fixture.site["objects"][14]["kind"]="remote_site" # last of 13 edges
  fixture.sites[0]=fixture.site
  context=await browser.new_context(viewport={"width":width,"height":height})
  errors=[]
  editor=await context.new_page()
  editor.on("pageerror",lambda e:errors.append(str(e)))
  await editor.goto(url+"/settings/cards")
  await editor.locator("#password").fill("test-secret")
  await editor.locator("#loginButton").click()
  await editor.locator("#selected .layout-row").first.wait_for(timeout=15000)
  assert await editor.locator("#regenerate").count()==1
  # An installed UI upgrade cannot rewrite v4. Reset is user-triggered,
  # authenticated, and draft-only until Validate→Preview→Apply.
  editor.once("dialog",lambda d:asyncio.create_task(d.accept()))
  await editor.locator("#regenerate").click()
  assert fixture.entry==previous.legacy()
  await editor.locator("#validate").click()
  await editor.locator("#apply").click()
  await editor.locator("#preview").wait_for(state="hidden",timeout=15000)
  assert fixture.revision==11
  saved=deepcopy(fixture.entry)
  assert saved["schema_version"]==5
  cards={row["id"]:row for row in saved["data"]["sites"]["home"]["cards"]}
  assert len(cards["family:network"]["presentation"]["member_ids"])==12
  assert len(cards["family:power"]["presentation"]["member_ids"])==2
  assert len(cards["family:cameras"]["presentation"]["member_ids"])==8
  assert cards["family:internet"]["presentation"]["native_sections"]==["diagnosis"]
  home=await context.new_page()
  home.on("pageerror",lambda e:errors.append(str(e)))
  await home.goto(url+"/")
  await home.wait_for_function("()=>MonitorBoxCardLayout?.state().loaded===true",
    timeout=15000)
  assert await home.locator(
    '[data-object="network"] [data-mb-member]').count()==12
  assert await home.locator(
    '[data-object="power"] [data-mb-member]').count()==2
  assert await home.locator(
    '[data-object="cameras"] [data-mb-member]').count()==8
  diagnosis=await home.locator(
    '[data-mb-site="home"] [data-object="internet"] .mb-native-diagnosis').count()
  assert diagnosis==1,("Internet diagnosis missing",
    await home.locator("#core-grid").inner_html(),
    cards["family:internet"])
  # Each checked Network member is rendered, despite every legacy device
  # reporting front_page=false. The last remote_site is not selectable.
  await editor.locator('#selected .layout-row').filter(
    has=editor.get_by_text("Network",exact=True)).get_by_text("Edit contents").click()
  selected=editor.locator('#contentMembers input:checked')
  assert await selected.count()==12
  assert await editor.locator(
    '#contentMembers input[data-member-id="edge12"]').count()==0
  await editor.locator('#contentMembers input[data-member-id="edge0"]').uncheck()
  await editor.locator("#saveContents").click()
  await editor.locator("#validate").click()
  await editor.locator("#apply").click()
  await editor.locator("#preview").wait_for(state="hidden",timeout=15000)
  assert fixture.revision==12
  await home.reload()
  await home.wait_for_function("()=>MonitorBoxCardLayout?.state().loaded===true")
  assert await home.locator(
    '[data-object="network"] [data-mb-member]').count()==11
  assert await home.locator(
    '[data-object="network"] [data-mb-member="edge0"]').count()==0
  await editor.locator("#arrange").click()
  frame=editor.frame_locator("#mb-arrange-actual-homepage")
  await frame.locator(".mb-arrange-frame-card").first.wait_for(timeout=15000)
  assert await frame.locator(".mb-arrange-menu-button").count()==0
  assert await frame.locator(
    '[data-object="network"] [data-mb-member]').count()==11
  # Both browser surfaces run the same actual native renderer.
  actual=await home.locator(
    '.mb-masonry-site[data-mb-site="home"] .mb-card-column > .mb-card-shell').evaluate_all(
      "(nodes)=>Object.fromEntries(nodes.map(n=>[n.dataset.object,n.innerText]))")
  preview=await frame.locator(
    '.mb-masonry-site[data-mb-site="home"] .mb-arrange-frame-card .mb-card-shell').evaluate_all(
      "(nodes)=>Object.fromEntries(nodes.map(n=>[n.dataset.object,n.innerText]))")
  assert actual==preview,(actual,preview)
  assert not errors,errors
  await context.close()
  print(f"UI52 {width}x{height}: exact Reset v5, 12 network members, 2 UPS, 8 cameras, native diagnosis, direct checkbox effect, Arrange parity PASS")

async def main():
  fixture,runner,url=await base.serve()
  try:
    async with async_playwright() as p:
      browser=await p.chromium.launch(headless=True)
      try:
        for size in [(1366,1000),(820,1100),(500,900)]:
          await scenario(browser,fixture,url,*size)
      finally: await browser.close()
  finally: await runner.cleanup()
if __name__=="__main__":asyncio.run(main())
