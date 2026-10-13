"use strict";
(() => {
  // The UI owns presentation. Core owns sessions, portable JSON authority,
  // validation and signed Supervisor activation. No browser JSON editor.
  const el = (id) => document.getElementById(id);
  const report = (message) => { el("status").textContent = message; };
  const sizeLimit = 4 * 1024 * 1024;
  let csrf = null;
  let candidate = null;
  let busy = false;

  async function session() {
    const response = await fetch("/api/v2/config/session", {
      credentials: "same-origin", cache: "no-store"
    });
    if (response.status === 401) {
      csrf = null;
      el("login").hidden = false;
      el("restore").hidden = true;
      report("Administrator login required.");
      return;
    }
    if (!response.ok) throw new Error("Administrator session unavailable: HTTP " + response.status);
    const data = await response.json();
    if (typeof data.csrf_token !== "string" || !data.csrf_token) {
      throw new Error("Administrator session is missing its write token.");
    }
    csrf = data.csrf_token;
    el("login").hidden = true;
    el("restore").hidden = false;
    report("Download the current configuration or select a JSON file to restore.");
  }

  el("loginButton").addEventListener("click", async () => {
    try {
      const password = el("password").value;
      el("password").value = "";
      const response = await fetch("/api/v2/config/auth/login", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({password})
      });
      if (!response.ok) throw new Error("Administrator login failed.");
      await session();
    } catch (error) { report(error.message || String(error)); }
  });

  el("file").addEventListener("change", async () => {
    candidate = null;
    el("restoreButton").disabled = true;
    const file = el("file").files && el("file").files[0];
    if (!file) return;
    if (file.size < 2 || file.size > sizeLimit) {
      report("Configuration JSON must be between 2 bytes and 4 MiB.");
      return;
    }
    try {
      const document = JSON.parse(await file.text());
      if (!document || document.schemaVersion !== "monitorbox.portable/v1" ||
          !Array.isArray(document.modules)) {
        throw new Error("Not a MonitorBox portable configuration JSON.");
      }
      candidate = document;
      const channel = el("channel");
      channel.replaceChildren(new Option("Stable (default)", "stable"));
      const saved = document.release && document.release.preferredChannel;
      if (saved === "beta" || saved === "dev") {
        channel.add(new Option("Use saved " + saved.toUpperCase() + " channel", saved));
      }
      el("restoreButton").disabled = !csrf || busy;
      report("Ready to validate and restore " + document.modules.length +
             " module selections. This replaces configuration and clears telemetry history.");
    } catch (error) {
      report("Restore file rejected: " + (error.message || String(error)));
    }
  });

  el("restoreButton").addEventListener("click", async () => {
    if (!candidate || !csrf || busy) return;
    if (!window.confirm("REPLACE MonitorBox configuration and DISCARD historical telemetry?")) return;
    busy = true;
    el("restoreButton").disabled = true;
    report("Checking signed module availability and preparing configuration replacement…");
    try {
      const firstResponse = await fetch("/api/v2/config/restore-status", {
        credentials: "same-origin", cache: "no-store"
      });
      if (!firstResponse.ok) throw new Error("Cannot read signed activation status. Nothing changed.");
      const initial = await firstResponse.json();
      if (!initial.generation || initial.updating) {
        throw new Error("An activation is running or the current generation is unavailable.");
      }
      const response = await fetch("/api/v2/config/restore-json", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: {"Content-Type": "application/json", "X-MonitorBox-CSRF": csrf},
        body: JSON.stringify({config: candidate, channel: el("channel").value, reset_history: true})
      });
      if (!response.ok) throw new Error("Restore rejected: " + await response.text());
      const result = await response.json();
      if (!result.accepted) throw new Error("Signed configuration activation was not accepted.");
      report("Restore accepted. Waiting for the verified signed generation to restart…");
      for (let attempt = 0; attempt < 240; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          const reply = await fetch("/api/v2/config/restore-status", {
            credentials: "same-origin", cache: "no-store"
          });
          if (reply.status === 401) {
            report("Administrator session expired. Log in again to verify restore completion.");
            return;
          }
          if (!reply.ok) continue;
          const state = await reply.json();
          if (state.updating) continue;
          if (state.failed) throw new Error("Signed activation failed; check appliance status before retrying.");
          if (state.generation && state.generation !== initial.generation) {
            report("Signed configuration activation verified. Opening Dashboard…");
            window.location.assign("/");
            return;
          }
        } catch (error) {
          if (error.message && error.message.startsWith("Signed activation failed")) throw error;
        }
      }
      report("Restore accepted but completion could not be verified. Check appliance status before retrying.");
    } catch (error) { report(error.message || String(error)); }
    finally {
      busy = false;
      el("restoreButton").disabled = !candidate || !csrf;
    }
  });

  const download = el("downloadJson");
  const downloadStatus = el("downloadState");
  download.addEventListener("click", async () => {
    if (download.disabled) return;
    download.disabled = true;
    downloadStatus.textContent = "Preparing verified configuration JSON…";
    try {
      const response = await fetch("/api/v2/config/portable-json", {
        credentials: "same-origin", cache: "no-store",
        headers: {Accept: "application/json"}
      });
      if (!response.ok) {
        throw new Error((await response.text()).trim() || ("HTTP " + response.status));
      }
      if (!(response.headers.get("Content-Type") || "").toLowerCase().includes("application/json")) {
        throw new Error("Unexpected backup content type.");
      }
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"\\/]{1,180}\.json)"/i);
      if (!match) throw new Error("Backup filename header missing or invalid.");
      const filename = match[1];
      if (!/^monitorbox-config_[A-Za-z0-9.+-]+_[0-9]{8}-[0-9]{6}\.json$/.test(filename)) {
        throw new Error("Export filename violates the approved appliance-local naming contract.");
      }
      const blob = await response.blob();
      if (!blob.size || blob.size > sizeLimit + 8192) throw new Error("Backup file size invalid.");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.append(anchor);
      try { anchor.click(); }
      finally {
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
      downloadStatus.textContent = "Download requested: " + filename + ". Contains provider credentials.";
    } catch (error) {
      downloadStatus.textContent = "Download failed: " + (error.message || String(error));
    } finally { download.disabled = false; }
  });

  session().catch((error) => report(error.message || String(error)));
})();
