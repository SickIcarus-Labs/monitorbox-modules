"""Operator-facing Backup / Restore build-3 product surface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from monitorbox.v2.appliance_backup import ApplianceBackupError, ApplianceBackupManager
from monitorbox.v2.appliance_restore_handoff import ApplianceRestoreHandoff
from monitorbox_backup_restore_b3_vault import BackupVault, BackupVaultError

LOG = logging.getLogger(__name__)
MAX_RESTORE_BYTES = 8 * 1024 * 1024 * 1024
RESTORE_CANDIDATE_TTL_SECONDS = 15 * 60
ADMIN_API_PREFIX = "/api/v2/config/backup-restore"

_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MonitorBox Backup & Restore</title><style>
:root{color-scheme:dark;--bg:#07111f;--panel:#101b2b;--panel2:#142238;--line:#293b55;--text:#eef5ff;--muted:#98a9c0;--accent:#7da6ff;--good:#65d28a;--bad:#f47878;--warn:#efbd66}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,sans-serif}button,input{font:inherit}.top{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:10px;padding:14px 18px;background:#07111fee;border-bottom:1px solid var(--line);backdrop-filter:blur(16px)}.top h1{font-size:19px;margin:0}.spacer{flex:1}.button{border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:var(--panel2);color:var(--text);font-weight:650;text-decoration:none;cursor:pointer}.button.primary{background:var(--accent);color:#07111f;border-color:transparent}.button.danger{border-color:#713f47;color:#ffd0d4}.button:disabled{opacity:.45}.auth{border:1px solid #28583b;border-radius:999px;padding:5px 9px;color:#acf1c0;background:#0b2418;font-size:12px;font-weight:650}.shell{max-width:1060px;margin:0 auto;padding:22px}.card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:16px;margin-bottom:16px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.status{border:1px solid var(--line);border-radius:10px;padding:11px;white-space:pre-wrap}.status.good{border-color:#28583b;color:#acf1c0}.status.warn{border-color:#6b5728;color:#f6d799}.status.bad{border-color:#713f47;color:#ffc8cc}.backup{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;border-top:1px solid var(--line);padding:13px 0}.backup:first-child{border-top:0}.backup strong{display:block}.actions,.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.actions{justify-content:flex-end}.actions .button{padding:7px 9px}.field{display:flex;flex-direction:column;gap:6px;color:var(--muted);min-width:140px;flex:1}.field input{border:1px solid var(--line);border-radius:9px;padding:9px;background:#081321;color:var(--text);width:100%}.toggle{display:flex;gap:8px;align-items:center;color:var(--text);font-weight:650}.toggle input{width:auto}.login{max-width:430px;margin:10vh auto}.hidden{display:none!important}input[type=file]{max-width:100%}.kind{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 7px;margin-left:7px;font-size:11px;text-transform:uppercase;color:var(--muted)}dialog{max-width:620px;width:calc(100% - 32px);border:1px solid var(--line);border-radius:15px;padding:18px;background:var(--panel);color:var(--text);box-shadow:0 24px 80px #000a}dialog::backdrop{background:#000a;backdrop-filter:blur(3px)}.warning{border:1px solid #6b5728;border-radius:10px;padding:11px;color:#f6d799;background:#241b0b}.preview{border:1px solid var(--line);border-radius:10px;padding:11px;white-space:pre-wrap;background:#081321}@media(max-width:720px){.grid{grid-template-columns:1fr}.shell{padding:14px}.top{flex-wrap:wrap}.backup{grid-template-columns:1fr}.actions{justify-content:flex-start}}
</style></head><body>
<header class="top"><a class="button" href="/">← Dashboard</a><a class="button" href="/settings">Configuration</a><h1>Backup &amp; Restore</h1><span class="spacer"></span><span id="authState" class="auth hidden">Admin authenticated</span><button id="refresh" class="button">Refresh</button></header>
<div id="login" class="login card hidden"><h2>Administrator login</h2><p class="muted">Backup and restore operations use the protected MonitorBox write plane.</p><label class="field">Password<input id="password" type="password" autocomplete="current-password"></label><div class="row" style="margin-top:12px"><button id="loginButton" class="button primary">Log in</button></div><div id="loginStatus" class="status" style="margin-top:12px">Not authenticated.</div></div>
<main id="app" class="shell hidden">
<section class="card"><h2>Appliance backups</h2><p>Whole-appliance backups preserve canonical configuration, protected credentials, history/state, Module Management authority, retained package artifacts and module-owned durable state. The saved-backup vault itself is outside archive authority.</p><div class="row"><button id="create" class="button primary">Save on MonitorBox</button><button id="createDownload" class="button">Save &amp; Download</button><input id="restoreFile" type="file" accept=".zip,application/zip"><button id="restoreFromFile" class="button danger">Restore from file…</button></div><div id="backupState" class="status" style="margin-top:12px">Ready.</div><div id="backups" style="margin-top:8px"></div></section>
<section class="card"><h2>Automatic full backups</h2><p class="muted">Scheduled backups are full appliance ZIP archives. Retention applies only to scheduled backups; manual backups are never silently aged out. This release supports the local vault and one filesystem destination, including a NAS mounted into the MonitorBox runtime. Cloud destinations are not advertised.</p><div class="row"><label class="toggle"><input id="scheduleEnabled" type="checkbox">Enable schedule</label><label class="field">Interval (hours)<input id="intervalHours" type="number" min="1" max="168" step="1"></label><label class="field">Keep scheduled backups<input id="retentionCount" type="number" min="1" max="100" step="1"></label><label class="field">Scheduled storage cap (GiB)<input id="retentionGib" type="number" min="1" max="1024" step="1"></label></div><label class="field" style="margin-top:10px">Optional filesystem / mounted-NAS destination<input id="destinationPath" type="text" autocomplete="off" placeholder="/backups/monitorbox"></label><div class="row" style="margin-top:12px"><button id="savePolicy" class="button primary">Save policy</button><button id="runNow" class="button">Run scheduled backup now</button></div><div id="scheduleState" class="status" style="margin-top:12px">Loading policy…</div></section>
<section class="card"><h2>Configuration snapshots</h2><p class="muted">Retained canonical revisions are lightweight configuration/history snapshots. They are separate from full appliance backups and do not replace whole-appliance recovery.</p><div class="row"><button id="configExport" class="button">Download config recovery bundle</button><input id="bundle" type="file"><button id="configRestore" class="button danger">Validate &amp; restore config</button></div><div id="configState" class="status" style="margin-top:12px">No configuration restore requested.</div></section>
<div class="grid"><section class="card"><h2>Config doctor</h2><div id="doctor" class="status">Not run yet.</div></section><section class="card"><h2>Retained revisions</h2><div id="revisions" class="muted">Loading…</div></section></div>
<section class="card"><h2>Break-glass recovery</h2><p class="muted">The normal Restore actions validate and hand off to Core's quiesced recovery substrate. Core's offline appliance-backup CLI remains available independently if this module or the normal UI is unavailable.</p></section>
</main>
<dialog id="restoreDialog"><h2>Restore MonitorBox?</h2><div id="restorePreview" class="preview"></div><p class="warning"><strong>This replaces active MonitorBox authority.</strong><br>The controller and site-local agent will quiesce, the selected backup will be activated, and MonitorBox will restart. Monitoring will be temporarily unavailable.</p><div class="row" style="justify-content:flex-end"><button id="cancelRestore" class="button">Cancel</button><button id="confirmRestore" class="button danger">Restore &amp; restart</button></div></dialog>
<script>
const $=id=>document.getElementById(id);let csrf=null,currentPolicy=null,restoreToken=null;const API='/api/v2/config/backup-restore';
function showAuthenticated(){$('authState').classList.remove('hidden');$('login').classList.add('hidden');$('app').classList.remove('hidden')}
async function jsonApi(url,options={}){options.headers={...(options.headers||{})};if(csrf&&options.method&&options.method!=='GET')options.headers['X-MonitorBox-CSRF']=csrf;if(options.body&&typeof options.body==='string'&&!options.headers['Content-Type'])options.headers['Content-Type']='application/json';const r=await fetch(url,options);const text=await r.text();let data={};try{data=text?JSON.parse(text):{}}catch{data={error:text}}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);return data}
async function authenticate(){try{const status=await jsonApi('/api/v2/config/status');if(status.authenticated){csrf=(await jsonApi('/api/v2/config/session')).csrf_token;showAuthenticated();await refresh();return}$('authState').classList.add('hidden');$('login').classList.remove('hidden');$('app').classList.add('hidden')}catch(e){$('loginStatus').textContent=e.message}}
$('loginButton').onclick=async()=>{try{const body=await jsonApi('/api/v2/config/auth/login',{method:'POST',body:JSON.stringify({password:$('password').value})});csrf=body.csrf_token;showAuthenticated();await refresh()}catch(e){$('loginStatus').textContent=e.message}};
function fmtBytes(n){if(!Number.isFinite(n))return 'unknown size';const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n.toFixed(i?1:0)} ${u[i]}`}
function renderBackups(items){const root=$('backups');root.replaceChildren();if(!items.length){root.className='muted';root.textContent='No saved appliance backups yet.';return}root.className='';for(const item of items){const row=document.createElement('div');row.className='backup';const info=document.createElement('div');const title=document.createElement('strong');title.textContent=item.label;const kind=document.createElement('span');kind.className='kind';kind.textContent=item.kind||'manual';title.append(kind);const sub=document.createElement('div');sub.className='muted';sub.textContent=`${item.backup_id} · ${fmtBytes(item.bytes)} · ${item.created_at}`;info.append(title,sub);const actions=document.createElement('div');actions.className='actions';for(const [label,fn,danger] of [['Restore',()=>previewVaultRestore(item),true],['Inspect',()=>inspectBackup(item),false],['Download',()=>downloadBackup(item),false],['Send',()=>sendBackup(item),false],['Rename',()=>renameBackup(item),false],['Copy',()=>copyBackup(item),false],['Delete',()=>deleteBackup(item),true]]){const b=document.createElement('button');b.className='button'+(danger?' danger':'');b.textContent=label;b.onclick=fn;actions.append(b)}row.append(info,actions);root.append(row)}}
function renderPolicy(policy,schedule){currentPolicy=policy;$('scheduleEnabled').checked=Boolean(policy.enabled);$('intervalHours').value=policy.interval_hours;$('retentionCount').value=policy.retention_count;$('retentionGib').value=Math.max(1,Math.round(Number(policy.retention_bytes)/(1024**3)));$('destinationPath').value=policy.destination_path||'';const s=schedule.status||{};const parts=[policy.enabled?`Enabled every ${policy.interval_hours}h`:'Schedule disabled',`keep ${policy.retention_count}`,`cap ${fmtBytes(policy.retention_bytes)}`];if(policy.destination_path)parts.push(`destination ${policy.destination_path}`);if(s.last_success)parts.push(`last success ${s.last_success}`);if(s.last_backup_id)parts.push(`backup ${s.last_backup_id}`);if(s.last_error)parts.push(s.last_error);$('scheduleState').className='status '+(s.last_error?'bad':'good');$('scheduleState').textContent=parts.join(' · ')}
async function refresh(){try{const [vault,doctor,revisions,policy,schedule,restore]=await Promise.all([jsonApi(`${API}/backups`),jsonApi('/api/v2/config/doctor'),jsonApi('/api/v2/config/revisions'),jsonApi(`${API}/policy`),jsonApi(`${API}/schedule`),jsonApi(`${API}/restore/status`)]);renderBackups(vault.backups||[]);renderPolicy(policy.policy,schedule);$('doctor').className='status '+(doctor.status==='healthy'?'good':'');$('doctor').textContent=`${String(doctor.status).toUpperCase()} · ${doctor.errors} error(s), ${doctor.warnings} warning(s)`;const rr=$('revisions');rr.replaceChildren();if(!(revisions.revisions||[]).length){rr.textContent='No retained revisions yet.'}else{for(const item of revisions.revisions){const div=document.createElement('div');div.textContent=item.valid?`Revision ${item.revision} · ${item.name}`:`Invalid · ${item.name}`;rr.append(div)}}if(restore.last_result){const r=restore.last_result;$('backupState').className='status '+(r.success?'good':'bad');$('backupState').textContent=r.success?`Last appliance restore completed successfully · revision ${r.canonical_revision}.`:`Last appliance restore failed safely · ${r.error||'prior authority preserved'}.`}}catch(e){$('backupState').className='status bad';$('backupState').textContent=e.message}}
async function createBackup(download){const label=prompt('Backup label (optional):','')||'';const state=$('backupState');try{state.className='status';state.textContent='Building and validating appliance backup…';const record=await jsonApi(`${API}/backups`,{method:'POST',body:JSON.stringify({label})});state.className='status good';state.textContent=`Saved ${record.label} (${record.backup_id}).`;await refresh();if(download)downloadBackup(record)}catch(e){state.className='status bad';state.textContent=e.message}}
$('create').onclick=()=>createBackup(false);$('createDownload').onclick=()=>createBackup(true);$('refresh').onclick=refresh;
function downloadBackup(item){window.location=`${API}/backups/${encodeURIComponent(item.backup_id)}/download`}
async function inspectBackup(item){try{const d=await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}`);alert(`${d.label}\nType ${d.kind}\nCore ${d.core_version||'?'} build ${d.core_build||'?'}\nRevision ${d.canonical_revision}\n${d.file_count} files · ${fmtBytes(d.payload_bytes)}\n${d.installation_fingerprint}`)}catch(e){alert(e.message)}}
async function sendBackup(item){try{const d=await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/destination`,{method:'POST'});$('backupState').className='status good';$('backupState').textContent=`Published ${item.label} to ${d.locator}.`}catch(e){$('backupState').className='status bad';$('backupState').textContent=e.message}}
async function renameBackup(item){const label=prompt('New backup label:',item.label);if(label===null)return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/rename`,{method:'POST',body:JSON.stringify({label})});await refresh()}catch(e){alert(e.message)}}
async function copyBackup(item){const label=prompt('Label for copied backup:',`Copy of ${item.label}`);if(label===null)return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/copy`,{method:'POST',body:JSON.stringify({label})});await refresh()}catch(e){alert(e.message)}}
async function deleteBackup(item){if(!confirm(`Delete saved appliance backup “${item.label}”? This does not affect the active MonitorBox installation.`))return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}`,{method:'DELETE'});await refresh()}catch(e){alert(e.message)}}
function showRestorePreview(d){restoreToken=d.restore_token;const lines=[d.source_label,`Core ${d.core_version||'?'} build ${d.core_build||'?'}`,`Canonical revision ${d.canonical_revision}`,`Installation ${d.installation_id||'?'}`,`${d.file_count} files · ${fmtBytes(d.payload_bytes)}`,d.installation_fingerprint||''];$('restorePreview').textContent=lines.join('\n');$('restoreDialog').showModal()}
async function previewVaultRestore(item){const state=$('backupState');try{state.className='status';state.textContent=`Validating ${item.label} for restore…`;const d=await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/restore/preview`,{method:'POST'});showRestorePreview(d);state.textContent='Restore preview ready.'}catch(e){state.className='status bad';state.textContent=e.message}}
$('restoreFromFile').onclick=async()=>{const file=$('restoreFile').files[0],state=$('backupState');if(!file){state.className='status warn';state.textContent='Choose a MonitorBox appliance .zip backup first.';return}try{state.className='status';state.textContent=`Uploading and validating ${file.name} for restore…`;const r=await fetch(`${API}/restore/file/preview`,{method:'POST',headers:{'X-MonitorBox-CSRF':csrf,'Content-Type':'application/zip','X-MonitorBox-Filename':file.name},body:file});const text=await r.text();let data={};try{data=text?JSON.parse(text):{}}catch{}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);showRestorePreview(data);state.textContent='Restore preview ready.'}catch(e){state.className='status bad';state.textContent=e.message}};
$('cancelRestore').onclick=()=>{$('restoreDialog').close();restoreToken=null};
$('confirmRestore').onclick=async()=>{if(!restoreToken)return;const state=$('backupState'),button=$('confirmRestore');button.disabled=true;try{const d=await jsonApi(`${API}/restore/confirm`,{method:'POST',body:JSON.stringify({restore_token:restoreToken,acknowledgement:'restore'})});$('restoreDialog').close();restoreToken=null;state.className='status warn';state.textContent=`Restore accepted (${d.request_id}). MonitorBox is quiescing and restarting…`;setTimeout(()=>location.reload(),7000)}catch(e){state.className='status bad';state.textContent=e.message}finally{button.disabled=false}};
$('savePolicy').onclick=async()=>{const state=$('scheduleState');try{const gib=Number($('retentionGib').value);if(!Number.isInteger(gib)||gib<1||gib>1024)throw new Error('Scheduled storage cap must be an integer from 1 to 1024 GiB.');const destination=$('destinationPath').value.trim();const payload={enabled:$('scheduleEnabled').checked,interval_hours:Number($('intervalHours').value),retention_count:Number($('retentionCount').value),retention_bytes:gib*1024**3,destination_type:destination?'filesystem':null,destination_path:destination||null};const d=await jsonApi(`${API}/policy`,{method:'PUT',body:JSON.stringify({policy:payload})});renderPolicy(d.policy,{status:{}});await refresh()}catch(e){state.className='status bad';state.textContent=e.message}};
$('runNow').onclick=async()=>{const state=$('scheduleState');try{state.className='status';state.textContent='Building scheduled full backup now…';await jsonApi(`${API}/schedule/run`,{method:'POST',body:'{}'});await refresh()}catch(e){state.className='status bad';state.textContent=e.message}};
$('configExport').onclick=async()=>{const state=$('configState');try{const r=await fetch('/api/v2/config/recovery/export',{method:'POST',headers:{'X-MonitorBox-CSRF':csrf}});if(!r.ok)throw new Error(await r.text()||`HTTP ${r.status}`);const blob=await r.blob(),name=r.headers.get('X-MonitorBox-Filename')||'monitorbox-recovery.mbx';const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);state.className='status good';state.textContent=`Downloaded ${name}.`}catch(e){state.className='status bad';state.textContent=e.message}};
$('configRestore').onclick=async()=>{const file=$('bundle').files[0],state=$('configState');if(!file){state.textContent='Choose a configuration recovery bundle first.';return}if(!confirm(`Restore configuration from ${file.name}?`))return;try{const r=await fetch('/api/v2/config/recovery/restore',{method:'POST',headers:{'X-MonitorBox-CSRF':csrf,'Content-Type':'application/octet-stream'},body:file});const text=await r.text();let data={};try{data=JSON.parse(text)}catch{}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);state.className='status good';state.textContent=`Restored source revision ${data.source_revision} as ${data.applied_revision}; controller restart scheduled.`}catch(e){state.className='status bad';state.textContent=e.message}};
authenticate();
</script></body></html>'''


class BackupRestoreApplication:
    def __init__(self, platform) -> None:
        self.platform = platform
        self.vault = BackupVault(platform.root)
        self.manager = ApplianceBackupManager(platform.root)
        self.handoff = ApplianceRestoreHandoff(platform.root)
        self.restore_root = Path(platform.root) / "backups" / "backup-restore-candidates"
        self._restore_candidates: dict[str, dict[str, Any]] = {}

    def install_page(self, app: web.Application) -> None:
        @web.middleware
        async def recovery_product_page(request: web.Request, handler):
            if request.method == "GET" and request.path == "/settings/recovery":
                return await self.page(request)
            return await handler(request)

        app.middlewares.append(recovery_product_page)
        app.router.add_get("/backup-restore", self.page)
        app.on_cleanup.append(self.cleanup)

    async def cleanup(self, _app: web.Application) -> None:
        for token in list(self._restore_candidates):
            self._discard_candidate(token)
        if self.restore_root.exists() and not self.restore_root.is_symlink():
            try:
                self.restore_root.rmdir()
            except OSError:
                pass

    async def page(self, _: web.Request) -> web.Response:
        return web.Response(
            text=_PAGE,
            content_type="text/html",
            charset="utf-8",
            headers={"Cache-Control": "no-store"},
        )

    async def list_backups(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        records = await asyncio.to_thread(self.vault.list)
        return web.json_response(
            {"backups": [item.public() for item in records]},
            headers={"Cache-Control": "no-store"},
        )

    async def create_backup(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        payload = await self._json(request)
        try:
            record = await asyncio.to_thread(
                self.vault.create,
                label=payload.get("label"),
                kind="manual",
            )
        except BackupVaultError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        LOG.info(
            "appliance backup created actor=%s backup_id=%s bytes=%d",
            session.actor,
            record.backup_id,
            record.bytes,
        )
        return web.json_response(record.public(), status=201, headers={"Cache-Control": "no-store"})

    async def inspect_backup(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        try:
            result = await asyncio.to_thread(self.vault.inspect, request.match_info["backup_id"])
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def download_backup(self, request: web.Request) -> web.StreamResponse:
        self.platform.auth.require(request)
        try:
            path = await asyncio.to_thread(self.vault.archive_path, request.match_info["backup_id"])
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        response = web.FileResponse(path)
        response.content_type = "application/zip"
        response.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def rename_backup(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        payload = await self._json(request)
        try:
            record = await asyncio.to_thread(
                self.vault.rename,
                request.match_info["backup_id"],
                label=payload.get("label", ""),
            )
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        LOG.info("saved backup renamed actor=%s backup_id=%s", session.actor, record.backup_id)
        return web.json_response(record.public(), headers={"Cache-Control": "no-store"})

    async def copy_backup(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        payload = await self._json(request)
        try:
            record = await asyncio.to_thread(
                self.vault.copy,
                request.match_info["backup_id"],
                label=payload.get("label"),
            )
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        LOG.info("saved backup copied actor=%s backup_id=%s", session.actor, record.backup_id)
        return web.json_response(record.public(), status=201, headers={"Cache-Control": "no-store"})

    async def delete_backup(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        backup_id = request.match_info["backup_id"]
        try:
            await asyncio.to_thread(self.vault.delete, backup_id)
        except BackupVaultError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        LOG.info("saved backup deleted actor=%s backup_id=%s", session.actor, backup_id)
        return web.json_response(
            {"deleted": True, "backup_id": backup_id},
            headers={"Cache-Control": "no-store"},
        )

    def _prune_candidates(self) -> None:
        cutoff = time.time() - RESTORE_CANDIDATE_TTL_SECONDS
        for token, candidate in list(self._restore_candidates.items()):
            if float(candidate.get("created_at", 0)) < cutoff:
                self._discard_candidate(token)

    def _discard_candidate(self, token: str) -> None:
        candidate = self._restore_candidates.pop(token, None)
        if candidate and candidate.get("transient"):
            Path(candidate["path"]).unlink(missing_ok=True)

    def _candidate(self, token: str) -> dict[str, Any]:
        self._prune_candidates()
        candidate = self._restore_candidates.get(str(token))
        if candidate is None:
            raise web.HTTPGone(text="restore preview expired; validate the backup again")
        path = Path(candidate["path"])
        if path.is_symlink() or not path.is_file():
            self._discard_candidate(str(token))
            raise web.HTTPGone(text="restore candidate is no longer available")
        return candidate

    def _preview(self, path: Path, *, source_label: str, transient: bool) -> dict[str, Any]:
        inspection = self.manager.inspect(path)
        manifest = inspection.manifest
        core = manifest.get("core") if isinstance(manifest.get("core"), dict) else {}
        token = secrets.token_hex(16)
        self._restore_candidates[token] = {
            "path": str(path),
            "transient": transient,
            "created_at": time.time(),
            "source_label": source_label,
        }
        return {
            "restore_token": token,
            "source_label": source_label,
            "core_version": core.get("version"),
            "core_build": core.get("build"),
            "installation_id": manifest.get("installation_id"),
            "canonical_revision": manifest.get("canonical_revision"),
            "installation_fingerprint": manifest.get("installation_fingerprint"),
            "file_count": inspection.file_count,
            "payload_bytes": inspection.total_bytes,
        }

    async def preview_vault_restore(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        try:
            record = await asyncio.to_thread(
                self.vault.get, request.match_info["backup_id"], verify=True
            )
            path = await asyncio.to_thread(self.vault.archive_path, record.backup_id)
            preview = await asyncio.to_thread(
                self._preview,
                path,
                source_label=record.label,
                transient=False,
            )
        except (BackupVaultError, ApplianceBackupError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        return web.json_response(preview, headers={"Cache-Control": "no-store"})

    async def preview_file_restore(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request, csrf=True)
        self._prune_candidates()
        if self.restore_root.is_symlink():
            raise web.HTTPConflict(text="restore staging directory may not be a symlink")
        self.restore_root.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix=".restore-upload-", suffix=".zip", dir=self.restore_root)
        temp = Path(raw)
        total = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.content.iter_chunked(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_RESTORE_BYTES:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=MAX_RESTORE_BYTES,
                            actual_size=total,
                        )
                    handle.write(chunk)
                if total == 0:
                    raise web.HTTPBadRequest(text="appliance backup payload is empty")
                handle.flush()
                os.fsync(handle.fileno())
            label = request.headers.get("X-MonitorBox-Filename", "Uploaded appliance backup")
            try:
                preview = await asyncio.to_thread(
                    self._preview,
                    temp,
                    source_label=label,
                    transient=True,
                )
            except (ApplianceBackupError, OSError) as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            return web.json_response(preview, status=201, headers={"Cache-Control": "no-store"})
        except Exception:
            if not any(Path(item.get("path", "")) == temp for item in self._restore_candidates.values()):
                temp.unlink(missing_ok=True)
            raise

    async def confirm_restore(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        if self.platform.request_restart is None:
            raise web.HTTPServiceUnavailable(text="controller restart handoff is unavailable")
        payload = await self._json(request)
        if payload.get("acknowledgement") != "restore":
            raise web.HTTPBadRequest(text="explicit restore acknowledgement is required")
        token = str(payload.get("restore_token", ""))
        candidate = self._candidate(token)
        path = Path(candidate["path"])
        try:
            # Validate again immediately before Core takes durable ownership.
            await asyncio.to_thread(self.manager.inspect, path)
            status = await asyncio.to_thread(self.handoff.prepare, path)
        except ApplianceBackupError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        self._discard_candidate(token)
        LOG.warning(
            "appliance restore accepted actor=%s request_id=%s source=%s",
            session.actor,
            status.request_id,
            candidate.get("source_label"),
        )
        asyncio.get_running_loop().call_later(0.5, self.platform.request_restart)
        return web.json_response(
            {
                "accepted": True,
                "request_id": status.request_id,
                "phase": status.phase,
            },
            status=202,
            headers={"Cache-Control": "no-store"},
        )

    async def restore_status(self, request: web.Request) -> web.Response:
        self.platform.auth.require(request)
        pending = await asyncio.to_thread(self.handoff.pending)
        last_result = await asyncio.to_thread(self.handoff.last_result)
        return web.json_response(
            {
                "pending": pending.public() if pending is not None else None,
                "last_result": last_result,
            },
            headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    async def _json(request: web.Request) -> dict:
        try:
            text = await request.text()
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise web.HTTPBadRequest(text="request body must be a JSON object") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="request body must be a JSON object")
        return payload
