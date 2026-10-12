"use strict";
(() => {
  // This UI module owns presentation only. Core owns authentication,
  // credential-complete export, JSON validation, and signed activation.
  const button = document.getElementById("downloadJson");
  const status = document.getElementById("downloadState");
  if (!button || !status) return;
  const show = (message) => { status.textContent = message; };
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    button.disabled = true;
    show("Preparing verified configuration JSON…");
    try {
      const response = await fetch("/api/v2/config/portable-json", {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: {Accept: "application/json"},
      });
      if (!response.ok) {
        const body = (await response.text()).trim();
        throw new Error(body || ("Configuration export failed: HTTP " + response.status));
      }
      const type = response.headers.get("Content-Type") || "";
      if (!type.toLowerCase().includes("application/json")) {
        throw new Error("Configuration export returned an unexpected content type.");
      }
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"\\/]{1,180}\.json)"/i);
      const filename = match ? match[1] : "monitorbox-config.json";
      const blob = await response.blob();
      if (!blob.size || blob.size > 4 * 1024 * 1024 + 8192) {
        throw new Error("Configuration export size is invalid.");
      }
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.append(anchor);
      try { anchor.click(); } finally {
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
      show("Download requested: " + filename + ". Store it securely; it contains provider credentials.");
    } catch (error) {
      show("Download failed: " + (error && error.message ? error.message : String(error)));
    } finally {
      button.disabled = false;
    }
  });
})();
