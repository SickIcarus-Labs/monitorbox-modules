  function moduleRemovalImpactLines(review) {
    const impact = review?.impact || {};
    const connections = Array.isArray(impact.connections) ? impact.connections : [];
    const resources = [...new Set(connections.flatMap(item =>
      Array.isArray(item?.exposed_object_ids) ? item.exposed_object_ids.map(String) : []
    ))];
    const checks = [...new Set(connections.flatMap(item =>
      Array.isArray(item?.check_ids) ? item.check_ids.map(String) : []
    ))];
    const lines = [
      `${connections.length} Connection${connections.length === 1 ? "" : "s"}`,
      `${resources.length} affected Resource${resources.length === 1 ? "" : "s"}`,
      `${checks.length} affected Check${checks.length === 1 ? "" : "s"}`,
      `${Number(impact.credential_values_to_purge || 0)} now-unreferenced credential value${Number(impact.credential_values_to_purge || 0) === 1 ? "" : "s"} to purge`,
    ];
    return {lines, connections, resources, checks};
  }

  function confirmReviewedModuleRemoval(module, review) {
    return new Promise(resolve => {
      const impact = moduleRemovalImpactLines(review);
      const dialog = document.createElement("dialog");
      dialog.className = "modules-removal-review";
      const title = document.createElement("h2");
      title.textContent = `Remove ${module.display_name || module.module_id}?`;
      const warning = document.createElement("p");
      warning.textContent = "This module is referenced by canonical monitoring configuration. Removal will retire that authority before uninstalling the module.";
      const summary = document.createElement("ul");
      for (const line of impact.lines) {
        const item = document.createElement("li");
        item.textContent = line;
        summary.append(item);
      }
      if (impact.connections.length) {
        const heading = document.createElement("h3");
        heading.textContent = "Connections";
        dialog.append(title, warning, summary, heading);
        const list = document.createElement("ul");
        for (const connection of impact.connections) {
          const item = document.createElement("li");
          const label = String(connection?.label || connection?.connection_id || connection?.ref || "Connection");
          const members = Number(connection?.member_count || 0);
          item.textContent = `${label} — ${members} provider/check member${members === 1 ? "" : "s"}`;
          list.append(item);
        }
        dialog.append(list);
      } else {
        dialog.append(title, warning, summary);
      }
      if (impact.resources.length) {
        const resources = document.createElement("p");
        resources.className = "modules-removal-resources";
        resources.textContent = `Affected Resources: ${impact.resources.join(", ")}`;
        dialog.append(resources);
      }
      if (impact.checks.length) {
        const checks = document.createElement("p");
        checks.className = "modules-removal-resources";
        checks.textContent = `Affected Checks: ${impact.checks.join(", ")}`;
        dialog.append(checks);
      }
      const label = document.createElement("label");
      label.textContent = "Current administrator password";
      const input = document.createElement("input");
      input.type = "password";
      input.autocomplete = "current-password";
      input.required = true;
      label.append(input);
      const actions = document.createElement("div");
      actions.className = "modules-removal-actions";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "button secondary";
      cancel.textContent = "Cancel";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button";
      remove.textContent = "Remove module and canonical monitoring";
      actions.append(cancel, remove);
      dialog.append(label, actions);
      document.body.append(dialog);

      const finish = value => {
        if (dialog.open) dialog.close();
        dialog.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => finish(null));
      dialog.addEventListener("cancel", event => {
        event.preventDefault();
        finish(null);
      });
      remove.addEventListener("click", () => {
        const value = input.value;
        if (!value) {
          input.focus();
          return;
        }
        finish(value);
      });
      dialog.showModal();
      input.focus();
    });
  }

  async function moduleRemoveRequest(moduleId) {
    const response = await fetch(`/api/v2/config/modules/${moduleId}/remove`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json", [CSRF_HEADER]: csrfToken },
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (response.ok) return payload;
    if (
      response.status === 409 &&
      payload &&
      typeof payload === "object" &&
      payload.review_required === true &&
      typeof payload.plan_id === "string"
    ) return payload;
    const message = typeof payload === "string"
      ? payload
      : payload?.error || `${response.status} ${response.statusText}`;
    throw new Error(message || "Module removal failed");
  }

  async function mutateModule(module, action) {
    if (!authenticated || !csrfToken || busy) return;
    if ((action === "remove" || action === "rollback") && !window.confirm(
      `${action === "remove" ? "Remove" : "Roll back"} ${module.display_name || module.module_id}?`
    )) return;

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus(`${action} ${module.display_name || module.module_id}…`);
    try {
      const moduleId = encodeURIComponent(module.module_id);
      let payload;
      if (action === "remove") {
        payload = await moduleRemoveRequest(moduleId);
        if (payload?.review_required === true) {
          const adminPassword = await confirmReviewedModuleRemoval(module, payload);
          if (adminPassword === null) {
            setStatus("Module removal cancelled.");
            return;
          }
          payload = await jsonRequest(`/api/v2/config/modules/${moduleId}/remove/apply`, {
            method: "POST",
            headers: { [CSRF_HEADER]: csrfToken, "Content-Type": "application/json" },
            body: JSON.stringify({ plan_id: payload.plan_id, admin_password: adminPassword }),
          });
        }
      } else {
        payload = await jsonRequest(`/api/v2/config/modules/${moduleId}/${action}`, {
          method: "POST",
          headers: { [CSRF_HEADER]: csrfToken },
        });
      }
      setStatus(
        payload.runtime_reconcile === "restart_scheduled"
          ? "Module authority committed. MonitorBox restart scheduled."
          : "Module authority committed. Runtime restart is required."
      );
      if (payload.runtime_reconcile !== "restart_scheduled") await loadModel();
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }
