"""v3 Backup/Restore operator page — unsigned build7 candidate, BACKUP ONLY.

No restore route is installed here. Native restore will be added only after
the separate signed authority, administrator identity/session and real
appliance acceptance gates in P0 #691 pass. The existing v2 handoff must not
be reachable on v3 through this module.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from monitorbox_backup_restore_b7_policy import (
    BackupPolicy, BackupPolicyStore, BackupPolicyError,
)
from monitorbox_backup_restore_b7_native_schedule import NativeScheduledBackup
from monitorbox_backup_restore_b7_native_workflow import NativeBackupWorkflow
from monitorbox_backup_restore_b7_native_vault import BackupVaultError

PREFIX = "/api/v2/config/backup-restore"

_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MonitorBox — Backup &amp; Restore</title><style>
:root{color-scheme:dark;--bg:#07111f;--panel:#101b2b;--border:#2a3c55;--text:#e9f1ff;--muted:#a1b2c7;--accent:#84a9fb;--warn:#e8bc70}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,sans-serif}
header{display:flex;gap:14px;align-items:center;padding:16px 22px;background:#101b2b;border-bottom:1px solid var(--border)}
h1{font-size:20px;margin:0}.shell{max-width:950px;margin:22px auto;padding:0 15px}.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px;margin:15px 0}
button,input{font:inherit}button{padding:8px 13px;border-radius:8px;border:1px solid var(--border);background:#192941;color:var(--text);cursor:pointer}
button.primary{background:var(--accent);color:#07111f;font-weight:700}button:disabled{opacity:.5;cursor:not-allowed}
input{width:100%;padding:7px;border-radius:7px;color:var(--text);background:var(--bg);border:1px solid var(--border)}
label{display:block;margin:10px 0;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.muted{color:var(--muted)}.status{padding:13px;border:1px solid var(--border);border-radius:8px;white-space:pre-wrap}
.warning{border-left:3px solid var(--warn);padding:9px 14px;background:#2a2119}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.item{border-top:1px solid var(--border);padding:12px 0}
a{color:var(--accent)}[hidden]{display:none!important}
</style></head><body>
<header><a href="/settings">← Settings</a><h1>Backup &amp; Restore</h1></header>
<main class="shell">
<section id="login" class="card" hidden><h2>Administrator sign-in</h2><label>Password<input type="password" id="password" autocomplete="current-password"></label>
<button class="primary" id="signIn">Sign in</button><div id="loginError" class="muted" role="alert"></div></section>
<div id="authenticated" hidden>
<section class="card"><h2>Signed full-appliance backups</h2><p class="muted">Backups include the Supervisor-authorized Active generation, retained signed packages and state. An accepted job is not a saved backup until verification and vault publication finish.</p>
<div class="row"><button id="create" class="primary">Create manual backup</button><button id="reload">Refresh</button></div>
<div class="status" id="job" role="status" aria-live="polite">Checking durable backup journal…</div>
<h3>Saved and verified archives</h3><div id="archives" class="muted">Loading…</div></section>
<section class="card"><h2>Automatic full backups</h2><div class="grid">
<label><input id="scheduleEnabled" type="checkbox"> Schedule enabled</label>
<label>Interval, hours<input id="intervalHours" type="number" min="1" max="168"></label>
<label>Retain scheduled backups<input id="retentionCount" type="number" min="1" max="100"></label>
<label>Scheduled storage cap, GiB<input id="retentionGib" type="number" min="1" max="1024"></label></div>
<label>Optional mounted filesystem/NAS destination (outside the appliance root)
<input id="destinationPath" placeholder="/backups/monitorbox" type="text" autocomplete="off"></label>
<div class="row"><button id="savePolicy">Save schedule policy</button><button id="runNow">Run scheduled backup now</button></div>
<div id="policyStatus" class="status" role="status">Loading schedule…</div></section>
<section class="card"><h2>Restore</h2>
<div class="warning" role="alert"><strong>Restore is intentionally unavailable in this unsigned development candidate.</strong>
The native restore transaction, password/session preservation and independent Core-down recovery tests are being completed in campaign #691.
No legacy v2 restore mechanism is invoked by this module.</div>
<button disabled aria-disabled="true">Restore from saved backup</button>
<button disabled aria-disabled="true">Restore from file</button></section>
</div></main>
<script>
const API='/api/v2/config/backup-restore';
const $=id=>document.getElementById(id);
let csrf=null,refreshBusy=false;
async function request(path,method='GET',payload=null){
 const options={method,headers:{}};if(method!=='GET'&&csrf)options.headers['X-MonitorBox-CSRF']=csrf;
 if(payload!==null){options.body=JSON.stringify(payload);options.headers['Content-Type']='application/json'}
 const r=await fetch(path,options);const raw=await r.text();let data={};
 try{data=raw?JSON.parse(raw):{}}catch{data={error:raw.slice(0,512)}}
 if(!r.ok)throw new Error(data.error||('HTTP '+r.status));
 return data;
}
async function authenticate(){
 try{const status=await request('/api/v2/config/status');
 if(!status.authenticated){$('login').hidden=false;$('authenticated').hidden=true;return}
 csrf=(await request('/api/v2/config/session')).csrf_token;
 $('login').hidden=true;$('authenticated').hidden=false;await refresh();
 }catch(error){$('login').hidden=false;$('authenticated').hidden=true;$('loginError').textContent=error.message}
}
$('signIn').onclick=async()=>{
 try{const d=await request('/api/v2/config/auth/login','POST',{password:$('password').value});csrf=d.csrf_token;
 $('password').value='';$('login').hidden=true;$('authenticated').hidden=false;await refresh();
 }catch(error){$('loginError').textContent=error.message}
};
function renderJob(data){
 const j=data.job;const view=$('job');
 view.textContent=!j?'No native backup is pending.':(
  j.phase==='committed'?'Saved and verified archive: '+j.backup_id:
  j.phase==='failed'?'Backup failed ('+(j.failure_code||'unknown')+'). No archive was saved.':
  'Backup pending — '+j.phase+'. Core may restart while Supervisor prepares the snapshot.'
 );
 const pending=Boolean(data.active);
 $('create').disabled=pending;$('runNow').disabled=pending;
}
function renderArchives(rows){
 const target=$('archives');target.replaceChildren();
 if(!rows.length){target.textContent='No verified saved native backups.';return}
 target.className='';
 for(const item of rows){
  const row=document.createElement('div');row.className='item';
  const name=document.createElement('strong');name.textContent=item.label||item.backup_id;
  const meta=document.createElement('div');meta.className='muted';
  meta.textContent=item.kind+' · '+item.backup_id+' · '+item.bytes+' bytes';
  const link=document.createElement('a');link.href=API+'/native/backups/'+encodeURIComponent(item.backup_id)+'/download';
  link.textContent='Download signed ZIP';row.append(name,meta,link);target.append(row);
 }
}
function renderPolicy(data){
 const p=data.policy;$('scheduleEnabled').checked=Boolean(p.enabled);
 $('intervalHours').value=p.interval_hours;$('retentionCount').value=p.retention_count;
 $('retentionGib').value=Math.round(p.retention_bytes/1073741824);
 $('destinationPath').value=p.destination_path||'';
 $('policyStatus').textContent=p.enabled?'Schedule active every '+p.interval_hours+'h':'Schedule disabled';
}
async function refresh(){
 if(refreshBusy||!csrf)return;refreshBusy=true;
 try{const [status,saved,policy]=await Promise.all([
  request(API+'/native/status'),request(API+'/native/backups'),request(API+'/native/policy')]);
  renderJob(status);renderArchives(saved.backups||[]);renderPolicy(policy);
 }catch(error){$('job').textContent='Backup status unavailable: '+error.message}
 finally{refreshBusy=false}
}
async function start(url){
 try{
  const accepted=await request(url,'POST',{});
  $('job').textContent='Backup accepted ('+accepted.request_id+'). Preparing signed ZIP; not saved yet.';
  await refresh();
 }catch(error){$('job').textContent='Backup request needs attention: '+error.message;await refresh()}
}
$('create').onclick=()=>start(API+'/native/backups');
$('runNow').onclick=()=>start(API+'/native/schedule/run');
$('reload').onclick=refresh;
$('savePolicy').onclick=async()=>{
 try{
  const path=$('destinationPath').value.trim();
  const policy={
   enabled:$('scheduleEnabled').checked,interval_hours:Number($('intervalHours').value),
   retention_count:Number($('retentionCount').value),
   retention_bytes:Math.round(Number($('retentionGib').value)*1073741824),
   destination_type:path?'filesystem':null,destination_path:path||null
  };
  await request(API+'/native/policy','PUT',policy);
  $('policyStatus').textContent='Schedule policy saved.';await refresh();
 }catch(error){$('policyStatus').textContent='Policy not saved: '+error.message}
};
setInterval(()=>{if(!$('authenticated').hidden)refresh()},5000);
authenticate();
</script></body></html>'''


class NativeBackupApplication:
    def __init__(self, platform: Any, workflow: NativeBackupWorkflow, scheduled: NativeScheduledBackup):
        self.platform=platform
        self.workflow=workflow
        self.scheduled=scheduled
        self.policy=BackupPolicyStore(platform.root)

    def install(self, app: web.Application) -> None:
        @web.middleware
        async def recovery_page(request: web.Request, handler):
            if request.method=="GET" and request.path=="/settings/recovery":
                return await self.page(request)
            return await handler(request)
        app.middlewares.append(recovery_page)
        app.router.add_get("/backup-restore",self.page)
        app.router.add_get(PREFIX+"/native/backups",self.list_backups)
        app.router.add_get(PREFIX+"/native/backups/{backup_id}/download",self.download_backup)
        app.router.add_get(PREFIX+"/native/policy",self.get_policy)
        app.router.add_put(PREFIX+"/native/policy",self.put_policy)

    async def page(self, request: web.Request)->web.Response:
        return web.Response(text=_PAGE,content_type="text/html",charset="utf-8",
                            headers={"Cache-Control":"no-store"})

    async def list_backups(self, request: web.Request)->web.Response:
        self.platform.auth.require(request)
        records=await asyncio.to_thread(self.workflow.vault.list)
        return web.json_response({"backups":[item.public() for item in records]},
                                 headers={"Cache-Control":"no-store"})

    async def download_backup(self, request: web.Request)->web.StreamResponse:
        self.platform.auth.require(request)
        try:
            path=await asyncio.to_thread(
                self.workflow.vault.archive_path,request.match_info["backup_id"],verify=True
            )
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text="native saved backup is not independently verified") from exc
        response=web.FileResponse(path)
        response.content_type="application/zip"
        response.headers["Content-Disposition"]=f'attachment; filename="{path.name}"'
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        return response

    async def get_policy(self, request: web.Request)->web.Response:
        self.platform.auth.require(request)
        policy=await asyncio.to_thread(self.policy.load)
        return web.json_response({"policy":policy.public()},headers={"Cache-Control":"no-store"})

    async def put_policy(self, request: web.Request)->web.Response:
        self.platform.auth.require(request,csrf=True)
        if request.content_length is not None and request.content_length>8192:
            raise web.HTTPRequestEntityTooLarge(max_size=8192,actual_size=request.content_length)
        try:
            raw=await request.json()
            if not isinstance(raw,dict) or set(raw)!={
                "enabled","interval_hours","retention_count","retention_bytes",
                "destination_type","destination_path"
            }:
                raise ValueError("policy fields invalid")
            updated=BackupPolicy.from_mapping(raw)
            saved=await asyncio.to_thread(self.policy.save,updated)
        except (ValueError,BackupPolicyError) as exc:
            raise web.HTTPBadRequest(text="native schedule policy rejected") from exc
        return web.json_response({"policy":saved.public()},headers={"Cache-Control":"no-store"})
