"""Normal UI ownership of the native JSON Backup/Restore presentation.

The accepted Core JSON page remains a standalone emergency fallback.
The UI module replaces only its HTML on native /settings/restore-json, reuses
Core's authenticated JSON action script, and adds no other backup mechanism.
"""

from __future__ import annotations

from pathlib import Path

_UI_PREFIX = "monitorbox_ui_b54/"
_ASSETS = Path(__file__).resolve().parent.parent / "sources/ui/successor-backup-restore"
_FILES = ("backup-restore.html", "backup-restore.css", "backup-restore.js")


def apply_ui_backup_restore(files: dict[str, bytes | None], record: dict) -> None:
    adapter = _UI_PREFIX + "__init__.py"
    payload = files.get(adapter)
    if not isinstance(payload, bytes):
        raise ValueError("reviewed UI adapter missing")
    source = payload.decode("utf-8")

    mime_anchor = 'ASSETS = {\n'
    mime_addition = (
        'ASSETS = {\n'
        '    "backup-restore.css": "text/css",\n'
        '    "backup-restore.js": "text/javascript",\n'
    )
    if source.count(mime_anchor) != 1:
        raise ValueError("reviewed UI asset MIME registry changed")
    source = source.replace(mime_anchor, mime_addition, 1)

    # This is the innermost middleware; existing outer Settings, Debug and App
    # Shell middleware then compose the normal shared navigation and branding.
    # Never replace an HTTP error or a route whose upstream is not Core's
    # explicitly identified portable JSON fallback.
    middleware = '''
@web.middleware
async def native_json_backup_restore_ui(request: web.Request, handler):
    response = await handler(request)
    if not (
        request.method == "GET"
        and request.path == "/settings/restore-json"
        and isinstance(response, web.Response)
        and response.status == 200
        and response.content_type == "text/html"
        and response.body
    ):
        return response
    core_html = response.text
    if "<title>MonitorBox Restore JSON</title>" not in core_html:
        return response
    start = core_html.find("<script>")
    end = core_html.find("</script>", start)
    if (
        start < 0 or end < 0 or core_html.count("<script>") != 1
        or core_html.count("</script>") != 1
        or "/api/v2/config/restore-json" not in core_html
        or "/api/v2/config/portable-json" not in core_html
        or "el('saveButton').onclick" not in core_html
    ):
        # A changed Core contract never removes the usable Core fallback.
        return response
    page = _resource("backup-restore.html").read_text(encoding="utf-8")
    token = "<!-- CORE_JSON_ACTIONS -->"
    if page.count(token) != 1:
        return response
    response.text = page.replace(token, core_html[start:end + len("</script>")], 1)
    response.headers["Cache-Control"] = "no-store"
    return response


'''
    # Anchor the route's normal-UI middleware next to the reviewed initializer;
    # Core routes, auth, provider secret handling and fallback are untouched.
    install_anchor = "def install(app: web.Application) -> None:\n"
    if source.count(install_anchor) != 1:
        raise ValueError("reviewed UI install entrypoint changed")
    source = source.replace(install_anchor, middleware + install_anchor, 1)

    append_anchor = "    app.middlewares.append(v22_settings_presentation)\n"
    if source.count(append_anchor) != 1:
        raise ValueError("reviewed UI middleware order changed")
    source = source.replace(
        append_anchor,
        append_anchor + "    app.middlewares.append(native_json_backup_restore_ui)\n",
        1,
    )
    compile(source, adapter, "exec")
    files[adapter] = source.encode("utf-8")

    version = f"{record['version']}-{record['build']}".encode("ascii")
    for basename in _FILES:
        key = _UI_PREFIX + "assets/" + basename
        if key in files:
            raise ValueError("UI Backup/Restore asset unexpectedly present in predecessor")
        blob = (_ASSETS / basename).read_bytes()
        if basename == "backup-restore.html":
            tag = b"__MONITORBOX_UI_GENERATION__"
            if blob.count(tag) != 2 or blob.count(b"<!-- CORE_JSON_ACTIONS -->") != 1:
                raise ValueError("UI backup HTML insertion contract changed")
            blob = blob.replace(tag, version)
        if len(blob) < 100 or len(blob) > 32768:
            raise ValueError("UI backup asset size outside reviewed range")
        files[key] = blob
