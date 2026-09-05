"""Operator-facing product surface for managed Backup / Restore."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from aiohttp import web

from monitorbox_backup_restore_b2_vault import BackupVault, BackupVaultError

LOG = logging.getLogger(__name__)
MAX_IMPORT_BYTES = 8 * 1024 * 1024 * 1024
ADMIN_API_PREFIX = "/api/v2/config/backup-restore"

_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MonitorBox Backup & Restore</title><style>
:root{color-scheme:dark;--bg:#07111f;--panel:#101b2b;--panel2:#142238;--line:#293b55;--text:#eef5ff;--muted:#98a9c0;--accent:#7da6ff;--good:#65d28a;--bad:#f47878}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,sans-serif}button,input{font:inherit}.top{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:10px;padding:14px 18px;background:#07111fee;border-bottom:1px solid var(--line);backdrop-filter:blur(16px)}.top h1{font-size:19px;margin:0}.spacer{flex:1}.button{border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:var(--panel2);color:var(--text);font-weight:650;text-decoration:none;cursor:pointer}.button.primary{background:var(--accent);color:#07111f;border-color:transparent}.button.danger{border-color:#713f47;color:#ffd0d4}.auth{border:1px solid #28583b;border-radius:999px;padding:5px 9px;color:#acf1c0;background:#0b2418;font-size:12px;font-weight:650}.shell{max-width:1060px;margin:0 auto;padding:22px}.card{background:var(--panel);border:1px solid var(--line);border-radius:15px;padding:16px;margin-bottom:16px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.status{border:1px solid var(--line);border-radius:10px;padding:11px;white-space:pre-wrap}.status.good{border-color:#28583b;color:#acf1c0}.status.bad{border-color:#713f47;color:#ffc8cc}.backup{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;border-top:1px solid var(--line);padding:13px 0}.backup:first-child{border-top:0}.backup strong{display:block}.actions,.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.actions{justify-content:flex-end}.actions .button{padding:7px 9px}.field{display:flex;flex-direction:column;gap:6px;color:var(--muted);min-width:140px;flex:1}.field input{border:1px solid var(--line);border-radius:9px;padding:9px;background:#081321;color:var(--text);width:100%}.toggle{display:flex;gap:8px;align-items:center;color:var(--text);font-weight:650}.toggle input{width:auto}.login{max-width:430px;margin:10vh auto}.hidden{display:none!important}input[type=file]{max-width:100%}.kind{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 7px;margin-left:7px;font-size:11px;text-transform:uppercase;color:var(--muted)}@media(max-width:720px){.grid{grid-template-columns:1fr}.shell{padding:14px}.top{flex-wrap:wrap}.backup{grid-template-columns:1fr}.actions{justify-content:flex-start}}
</style></head><body>
<header class="top"><a class="button" href="/">← Dashboard</a><a class="button" href="/settings">Configuration</a><h1>Backup &amp; Restore</h1><span class="spacer"></span><span id="authState" class="auth hidden">Admin authenticated</span><button id="refresh" class="button">Refresh</button></header>
<div id="login" class="login card hidden"><h2>Administrator login</h2><p class="muted">Backup and restore operations use the protected MonitorBox write plane.</p><label class="field">Password<input id="password" type="password" autocomplete="current-password"></label><div class="row" style="margin-top:12px"><button id="loginButton" class="button primary">Log in</button></div><div id="loginStatus" class="status" style="margin-top:12px">Not authenticated.</div></div>
<main id="app" class="shell hidden">
<section class="card"><h2>Appliance backups</h2><p>Whole-appliance backups preserve canonical configuration, protected credentials, history/state, Module Management authority, retained package artifacts and module-owned durable state. The saved-backup vault itself is excluded from every archive.</p><div class="row"><button id="create" class="button primary">Save on MonitorBox</button><button id="createDownload" class="button">Save &amp; Download</button><input id="importFile" type="file" accept=".zip,application/zip"><button id="import" class="button">Import</button></div><div id="backupState" class="status" style="margin-top:12px">Ready.</div><div id="backups" style="margin-top:8px"></div></section>
<section class="card"><h2>Automatic full backups</h2><p class="muted">Scheduled backups are full appliance ZIP archives. Retention applies only to scheduled backups; manual backups are never silently aged out. This release supports the local vault and one filesystem destination, including a NAS mounted into the MonitorBox runtime. Cloud destinations are not advertised.</p><div class="row"><label class="toggle"><input id="scheduleEnabled" type="checkbox">Enable schedule</label><label class="field">Interval (hours)<input id="intervalHours" type="number" min="1" max="168" step="1"></label><label class="field">Keep scheduled backups<input id="retentionCount" type="number" min="1" max="100" step="1"></label><label class="field">Scheduled storage cap (GiB)<input id="retentionGib" type="number" min="1" max="1024" step="1"></label></div><label class="field" style="margin-top:10px">Optional filesystem / mounted-NAS destination<input id="destinationPath" type="text" autocomplete="off" placeholder="/backups/monitorbox"></label><div class="row" style="margin-top:12px"><button id="savePolicy" class="button primary">Save policy</button><button id="runNow" class="button">Run scheduled backup now</button></div><div id="scheduleState" class="status" style="margin-top:12px">Loading policy…</div></section>
<section class="card"><h2>Configuration snapshots</h2><p class="muted">Retained canonical revisions are lightweight configuration/history snapshots. They are intentionally separate from full appliance backups and do not replace a whole-appliance recovery archive.</p><div class="row"><button id="configExport" class="button">Download config recovery bundle</button><input id="bundle" type="file"><button id="configRestore" class="button danger">Validate &amp; restore config</button></div><div id="configState" class="status" style="margin-top:12px">No configuration restore requested.</div></section>
<div class="grid"><section class="card"><h2>Config doctor</h2><div id="doctor" class="status">Not run yet.</div></section><section class="card"><h2>Retained revisions</h2><div id="revisions" class="muted">Loading…</div></section></div>
<section class="card"><h2>Offline disaster recovery</h2><p class="muted">Whole-appliance restore replaces the persistent MonitorBox root and therefore remains an offline Core operation. Stop controller/agent processes, validate the ZIP archive, restore it to a clean compatible deployment, then restart and verify the installation fingerprint. This Core path remains available even if the Backup/Restore module or normal UI is disabled or broken.</p></section>
</main><script>
const $=id=>document.getElementById(id);let csrf=null,currentPolicy=null;const API='/api/v2/config/backup-restore';
function showAuthenticated(){ $('authState').classList.remove('hidden');$('login').classList.add('hidden');$('app').classList.remove('hidden') }
async function jsonApi(url,options={}){options.headers={...(options.headers||{})};if(csrf&&options.method&&options.method!=='GET')options.headers['X-MonitorBox-CSRF']=csrf;if(options.body&&typeof options.body==='string'&&!options.headers['Content-Type'])options.headers['Content-Type']='application/json';const r=await fetch(url,options);const text=await r.text();let data={};try{data=text?JSON.parse(text):{}}catch{data={error:text}}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);return data}
async function authenticate(){try{const status=await jsonApi('/api/v2/config/status');if(status.authenticated){csrf=(await jsonApi('/api/v2/config/session')).csrf_token;showAuthenticated();await refresh();return}$('authState').classList.add('hidden');$('login').classList.remove('hidden');$('app').classList.add('hidden')}catch(e){$('loginStatus').textContent=e.message}}
$('loginButton').onclick=async()=>{try{const body=await jsonApi('/api/v2/config/auth/login',{method:'POST',body:JSON.stringify({password:$('password').value})});csrf=body.csrf_token;showAuthenticated();await refresh()}catch(e){$('loginStatus').textContent=e.message}};
function fmtBytes(n){if(!Number.isFinite(n))return 'unknown size';const u=['B','KiB','MiB','GiB','TiB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n.toFixed(i?1:0)} ${u[i]}`}
function renderBackups(items){const root=$('backups');root.replaceChildren();if(!items.length){root.className='muted';root.textContent='No saved appliance backups yet.';return}root.className='';for(const item of items){const row=document.createElement('div');row.className='backup';const info=document.createElement('div');const title=document.createElement('strong');title.textContent=item.label;const kind=document.createElement('span');kind.className='kind';kind.textContent=item.kind||'manual';title.append(kind);const sub=document.createElement('div');sub.className='muted';sub.textContent=`${item.backup_id} · ${fmtBytes(item.bytes)} · ${item.created_at}`;info.append(title,sub);const actions=document.createElement('div');actions.className='actions';for(const [label,fn,danger] of [['Inspect',()=>inspectBackup(item),false],['Download',()=>downloadBackup(item),false],['Send',()=>sendBackup(item),false],['Rename',()=>renameBackup(item),false],['Copy',()=>copyBackup(item),false],['Delete',()=>deleteBackup(item),true]]){const b=document.createElement('button');b.className='button'+(danger?' danger':'');b.textContent=label;b.onclick=fn;actions.append(b)}row.append(info,actions);root.append(row)}}
function renderPolicy(policy,schedule){currentPolicy=policy;$('scheduleEnabled').checked=Boolean(policy.enabled);$('intervalHours').value=policy.interval_hours;$('retentionCount').value=policy.retention_count;$('retentionGib').value=Math.max(1,Math.round(Number(policy.retention_bytes)/(1024**3)));$('destinationPath').value=policy.destination_path||'';const s=schedule.status||{};const parts=[policy.enabled?`Enabled every ${policy.interval_hours}h`:'Schedule disabled',`keep ${policy.retention_count}`,`cap ${fmtBytes(policy.retention_bytes)}`];if(policy.destination_path)parts.push(`destination ${policy.destination_path}`);if(s.last_success)parts.push(`last success ${s.last_success}`);if(s.last_backup_id)parts.push(`backup ${s.last_backup_id}`);if(s.last_error)parts.push(s.last_error);$('scheduleState').className='status '+(s.last_error?'bad':'good');$('scheduleState').textContent=parts.join(' · ')}
async function refresh(){try{const [vault,doctor,revisions,policy,schedule]=await Promise.all([jsonApi(`${API}/backups`),jsonApi('/api/v2/config/doctor'),jsonApi('/api/v2/config/revisions'),jsonApi(`${API}/policy`),jsonApi(`${API}/schedule`)]);renderBackups(vault.backups||[]);renderPolicy(policy.policy,schedule);$('doctor').className='status '+(doctor.status==='healthy'?'good':'');$('doctor').textContent=`${String(doctor.status).toUpperCase()} · ${doctor.errors} error(s), ${doctor.warnings} warning(s)`;const rr=$('revisions');rr.replaceChildren();if(!(revisions.revisions||[]).length){rr.textContent='No retained revisions yet.'}else{for(const item of revisions.revisions){const div=document.createElement('div');div.textContent=item.valid?`Revision ${item.revision} · ${item.name}`:`Invalid · ${item.name}`;rr.append(div)}}}catch(e){$('backupState').className='status bad';$('backupState').textContent=e.message}}
async function createBackup(download){const label=prompt('Backup label (optional):','')||'';const state=$('backupState');try{state.className='status';state.textContent='Building and validating appliance backup…';const record=await jsonApi(`${API}/backups`,{method:'POST',body:JSON.stringify({label})});state.className='status good';state.textContent=`Saved ${record.label} (${record.backup_id}).`;await refresh();if(download)downloadBackup(record)}catch(e){state.className='status bad';state.textContent=e.message}}
$('create').onclick=()=>createBackup(false);$('createDownload').onclick=()=>createBackup(true);
function downloadBackup(item){window.location=`${API}/backups/${encodeURIComponent(item.backup_id)}/download`}
async function inspectBackup(item){try{const d=await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}`);alert(`${d.label}\nType ${d.kind}\nCore ${d.core_version||'?'} build ${d.core_build||'?'}\nRevision ${d.canonical_revision}\n${d.file_count} files · ${fmtBytes(d.payload_bytes)}\n${d.installation_fingerprint}`)}catch(e){alert(e.message)}}
async function sendBackup(item){try{const d=await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/destination`,{method:'POST'});$('backupState').className='status good';$('backupState').textContent=`Published ${item.label} to ${d.locator}.`}catch(e){$('backupState').className='status bad';$('backupState').textContent=e.message}}
async function renameBackup(item){const label=prompt('New backup label:',item.label);if(label===null)return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/rename`,{method:'POST',body:JSON.stringify({label})});await refresh()}catch(e){alert(e.message)}}
async function copyBackup(item){const label=prompt('Label for copied backup:',`Copy of ${item.label}`);if(label===null)return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}/copy`,{method:'POST',body:JSON.stringify({label})});await refresh()}catch(e){alert(e.message)}}
async function deleteBackup(item){if(!confirm(`Delete saved appliance backup “${item.label}”? This does not affect the active MonitorBox installation.`))return;try{await jsonApi(`${API}/backups/${encodeURIComponent(item.backup_id)}`,{method:'DELETE'});await refresh()}catch(e){alert(e.message)}}
$('import').onclick=async()=>{const file=$('importFile').files[0],state=$('backupState');if(!file){state.textContent='Choose a ZIP appliance backup first.';return}const label=prompt('Imported backup label:',file.name)||file.name;try{state.className='status';state.textContent='Uploading and validating appliance backup…';const r=await fetch(`${API}/import?label=${encodeURIComponent(label)}`,{method:'POST',headers:{'X-MonitorBox-CSRF':csrf,'Content-Type':'application/zip'},body:file});const text=await r.text();let data={};try{data=JSON.parse(text)}catch{}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);state.className='status good';state.textContent=`Imported ${data.label} (${data.backup_id}).`;await refresh()}catch(e){state.className='status bad';state.textContent=e.message}};
$('savePolicy').onclick=async()=>{const state=$('scheduleState');try{const gib=Number($('retentionGib').value);if(!Number.isInteger(gib)||gib<1||gib>1024)throw new Error('Scheduled storage cap must be an integer from 1 to 1024 GiB.');const destination=$('destinationPath').value.trim();const payload={enabled:$('scheduleEnabled').checked,interval_hours:Number($('intervalHours').value),retention_count:Number($('retentionCount').value),retention_bytes:gib*1024**3,destination_type:destination?'filesystem':null,destination_path:destination||null};await jsonApi(`${API}/policy`,{method:'PUT',body:JSON.stringify(payload)});state.className='status good';state.textContent='Backup policy saved.';await refresh()}catch(e){state.className='status bad';state.textContent=e.message}};
$('runNow').onclick=async()=>{const state=$('scheduleState');try{state.className='status';state.textContent='Building scheduled appliance backup…';const result=await jsonApi(`${API}/schedule/run`,{method:'POST'});state.className='status '+(result.destination_error?'bad':'good');state.textContent=result.destination_error?`Saved ${result.backup.label} locally; ${result.destination_error}.`:`Saved ${result.backup.label}.`;await refresh()}catch(e){state.className='status bad';state.textContent=e.message}};
$('configExport').onclick=async()=>{try{const r=await fetch('/api/v2/config/recovery/export',{method:'POST',headers:{'X-MonitorBox-CSRF':csrf}});if(!r.ok)throw new Error(await r.text()||`HTTP ${r.status}`);const blob=await r.blob(),name=r.headers.get('X-MonitorBox-Filename')||'monitorbox-recovery.mbx';const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}catch(e){$('configState').className='status bad';$('configState').textContent=e.message}};
$('configRestore').onclick=async()=>{const file=$('bundle').files[0],state=$('configState');if(!file){state.textContent='Choose a config recovery bundle first.';return}if(!confirm(`Restore ${file.name}? Canonical authority changes only after complete validation.`))return;try{state.className='status';state.textContent='Uploading and validating configuration recovery bundle…';const r=await fetch('/api/v2/config/recovery/restore',{method:'POST',headers:{'X-MonitorBox-CSRF':csrf,'Content-Type':'application/octet-stream'},body:file});const text=await r.text();let data={};try{data=JSON.parse(text)}catch{}if(!r.ok)throw new Error(data.error||text||`HTTP ${r.status}`);state.className='status good';state.textContent=`Restored source revision ${data.source_revision} as revision ${data.applied_revision}; restart scheduled.`}catch(e){state.className='status bad';state.textContent=e.message}};
$('refresh').onclick=refresh;authenticate();
</script></body></html>'''


class BackupRestoreApplication:
    def __init__(self, platform) -> None:
        self.platform = platform
        self.vault = BackupVault(platform.root)

    def install_page(self, app: web.Application) -> None:
        @web.middleware
        async def recovery_product_page(request: web.Request, handler):
            if request.method == "GET" and request.path == "/settings/recovery":
                return await self.page(request)
            return await handler(request)

        app.middlewares.append(recovery_product_page)
        app.router.add_get("/backup-restore", self.page)

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

    async def import_backup(self, request: web.Request) -> web.Response:
        session = self.platform.auth.require(request, csrf=True)
        self.vault.ensure()
        fd, raw = tempfile.mkstemp(prefix=".import-", suffix=".zip", dir=self.vault.path)
        temp = Path(raw)
        total = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.content.iter_chunked(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_IMPORT_BYTES:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=MAX_IMPORT_BYTES,
                            actual_size=total,
                        )
                    handle.write(chunk)
                if total == 0:
                    raise web.HTTPBadRequest(text="appliance backup payload is empty")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                record = await asyncio.to_thread(
                    self.vault.import_file,
                    temp,
                    label=request.query.get("label"),
                )
            except BackupVaultError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            LOG.info(
                "appliance backup imported actor=%s backup_id=%s bytes=%d",
                session.actor,
                record.backup_id,
                record.bytes,
            )
            return web.json_response(record.public(), status=201, headers={"Cache-Control": "no-store"})
        finally:
            temp.unlink(missing_ok=True)

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
