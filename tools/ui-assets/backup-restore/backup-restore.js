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
    report("Download, save or restore portable configuration JSON.");
    await Promise.all([refreshSaved(), refreshSchedule()]);
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

  function selectRestoreDocument(document) {
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
           " module selections. Existing configuration will be replaced.");
  }

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
      selectRestoreDocument(JSON.parse(await file.text()));
    } catch (error) {
      report("Restore file rejected: " + (error.message || String(error)));
    }
  });

  el("restoreButton").addEventListener("click", async () => {
    if (!candidate || !csrf || busy) return;
    if (!window.confirm("Replace this appliance\'s configuration with the selected JSON?")) return;
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
      const match = disposition.match(/filename="([^"]+\.json)"/i);
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

  // Saved backups contain provider credentials; never render their contents.
  // Restoring a saved record uses Core's existing signed restore endpoint.
  const savedApi = "/api/v2/config/backup-restore/json/saved";
  const scheduleApi = "/api/v2/config/backup-restore/json";

  async function protectedRequest(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      ...options
    });
    if (!response.ok) {
      const message = (await response.text()).trim();
      throw new Error(message || ("HTTP " + response.status));
    }
    return response;
  }

  function savedAction(label, callback) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mb-br-button";
    button.textContent = label;
    button.addEventListener("click", callback);
    return button;
  }

  async function refreshSaved() {
    const root = el("savedRecords");
    try {
      const response = await protectedRequest(savedApi);
      const result = await response.json();
      const backups = Array.isArray(result.backups) ? result.backups : [];
      root.replaceChildren();
      if (!backups.length) {
        root.textContent = "No saved configuration JSON backups.";
        return;
      }
      for (const entry of backups) {
        if (!entry || typeof entry.id !== "string" || typeof entry.filename !== "string") continue;
        const row = document.createElement("div");
        row.className = "mb-br-saved-row";
        const description = document.createElement("div");
        description.className = "mb-br-saved-label";
        const name = document.createElement("strong");
        name.textContent = entry.filename;
        const detail = document.createElement("small");
        detail.textContent = (entry.kind === "scheduled" ? "Scheduled" : "Manual") +
          " · " + (entry.created_local || "Time unavailable") +
          " · " + Math.ceil((Number(entry.bytes) || 0) / 1024) + " KiB";
        description.append(name, detail);
        const actions = document.createElement("div");
        actions.className = "mb-br-row";
        const resource = savedApi + "/" + encodeURIComponent(entry.id);
        actions.append(savedAction("Download", () => window.location.assign(resource)));
        actions.append(savedAction("Restore", async () => {
          try {
            const response = await protectedRequest(resource);
            const bytes = await response.blob();
            if (!bytes.size || bytes.size > sizeLimit + 8192) {
              throw new Error("Saved JSON size is invalid.");
            }
            el("file").value = "";
            selectRestoreDocument(JSON.parse(await bytes.text()));
            el("restoreButton").focus();
          } catch (error) { report("Saved restore unavailable: " + (error.message || String(error))); }
        }));
        actions.append(savedAction("Delete", async () => {
          if (!window.confirm("Delete saved configuration backup " + entry.filename + "?")) return;
          try {
            await protectedRequest(resource, {
              method: "DELETE", headers: {"X-MonitorBox-CSRF": csrf}
            });
            await refreshSaved();
          } catch (error) { report("Delete failed: " + (error.message || String(error))); }
        }));
        row.append(description, actions);
        root.append(row);
      }
    } catch (error) {
      root.textContent = "Saved JSON backups unavailable: " + (error.message || String(error));
    }
  }

  el("saveLocalJson").addEventListener("click", async () => {
    const button = el("saveLocalJson");
    if (!csrf || button.disabled) return;
    button.disabled = true;
    const output = el("downloadState");
    output.textContent = "Saving verified configuration JSON to MonitorBox…";
    try {
      const response = await protectedRequest(savedApi, {
        method: "POST", headers: {"X-MonitorBox-CSRF": csrf}
      });
      const record = await response.json();
      output.textContent = "Saved to MonitorBox: " + record.filename;
      await refreshSaved();
    } catch (error) {
      output.textContent = "Save failed: " + (error.message || String(error));
    } finally { button.disabled = false; }
  });

  async function refreshSchedule() {
    const output = el("scheduleStatus");
    try {
      const response = await protectedRequest(scheduleApi + "/policy");
      const data = await response.json();
      const policy = data.policy || {};
      el("scheduleEnabled").checked = Boolean(policy.enabled);
      el("scheduleTime").value = policy.time || "02:00";
      el("scheduleRetention").value = policy.retention_count || 7;
      el("scheduleDestination").value = policy.destination_path || "";
      const status = data.status || {};
      output.textContent = status.last_error ||
        (status.last_success ? ("Last scheduled JSON backup: " + status.last_success) :
          "Schedule ready. Times follow MonitorBox TZ.");
    } catch (error) {
      output.textContent = "Schedule unavailable: " + (error.message || String(error));
    }
  }

  el("saveSchedule").addEventListener("click", async () => {
    if (!csrf) return;
    const btn = el("saveSchedule");
    btn.disabled = true;
    try {
      const policy = {
        enabled: Boolean(el("scheduleEnabled").checked),
        time: el("scheduleTime").value,
        retention_count: Number(el("scheduleRetention").value),
        destination_path: el("scheduleDestination").value.trim(),
      };
      if (!/^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(policy.time) ||
          !Number.isInteger(policy.retention_count) ||
          policy.retention_count < 1 || policy.retention_count > 100) {
        throw new Error("Enter a valid local time and retention count (1–100).");
      }
      const reply = await protectedRequest(scheduleApi + "/policy", {
        method: "PUT",
        headers: {"Content-Type": "application/json", "X-MonitorBox-CSRF": csrf},
        body: JSON.stringify(policy)
      });
      const outcome = await reply.json();
      el("scheduleStatus").textContent = outcome.accepted
        ? "Schedule change accepted; awaiting signed generation activation. Refresh after MonitorBox restarts."
        : "Schedule change was not accepted. No change confirmed.";
    } catch (error) {
      el("scheduleStatus").textContent = "Schedule save failed: " + (error.message || String(error));
    } finally { btn.disabled = false; }
  });

  el("runScheduleNow").addEventListener("click", async () => {
    if (!csrf) return;
    const button = el("runScheduleNow");
    button.disabled = true;
    el("scheduleStatus").textContent = "Creating a verified JSON backup…";
    try {
      const reply = await protectedRequest(scheduleApi + "/run", {
        method: "POST", headers: {"X-MonitorBox-CSRF": csrf}
      });
      const result = await reply.json();
      if (!result.created) throw new Error("No JSON backup was created.");
      el("scheduleStatus").textContent = "Saved JSON backup: " + result.backup.filename +
        (result.destination_error ? " (external copy failed; local backup retained)" : "");
      await refreshSaved();
    } catch (error) {
      el("scheduleStatus").textContent = "Backup failed: " + (error.message || String(error));
    } finally { button.disabled = false; }
  });

  session().catch((error) => report(error.message || String(error)));
})();
