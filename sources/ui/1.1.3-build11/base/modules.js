(() => {
  "use strict";

  const MODULES_API = "/api/v2/modules";
  const CONFIG_STATUS_API = "/api/v2/config/status";
  const CONFIG_LOGIN_API = "/api/v2/config/auth/login";
  const CONFIG_SESSION_API = "/api/v2/config/session";
  const CHECK_UPDATES_API = "/api/v2/config/modules/check-updates";
  const UPDATE_ALL_API = "/api/v2/config/modules/update-all";
  const REPOSITORIES_API = "/api/v2/config/modules/repositories";
  const CSRF_HEADER = "X-MonitorBox-CSRF";

  const list = document.getElementById("modules-list");
  const repositories = document.getElementById("modules-repositories");
  const capabilities = document.getElementById("modules-capabilities");
  const status = document.getElementById("modules-status");
  const authState = document.getElementById("modules-auth-state");
  const loginForm = document.getElementById("modules-login-form");
  const password = document.getElementById("modules-password");
  const checkUpdates = document.getElementById("modules-check-updates");
  const updateAll = document.getElementById("modules-update-all");
  const repositoryForm = document.getElementById("modules-repository-form");
  const repositoryId = document.getElementById("modules-repository-id");
  const repositoryName = document.getElementById("modules-repository-name");
  const repositoryUrl = document.getElementById("modules-repository-url");
  const repositoryKeyId = document.getElementById("modules-repository-key-id");
  const repositoryPublicKey = document.getElementById("modules-repository-public-key");
  const repositoryCredential = document.getElementById("modules-repository-credential");

  let model = null;
  let csrfToken = null;
  let authenticated = false;
  let busy = false;

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function setStatus(message, error = false) {
    status.textContent = message || "";
    status.classList.toggle("error", error);
  }

  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const message = typeof payload === "string"
        ? payload
        : payload && payload.error
          ? payload.error
          : `${response.status} ${response.statusText}`;
      throw new Error(message || `${response.status} ${response.statusText}`);
    }
    return payload;
  }

  function badge(label, className = "") {
    const item = document.createElement("span");
    item.className = `modules-badge ${className}`.trim();
    item.textContent = label;
    return item;
  }

  function detail(label, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = text(value);
    wrapper.append(term, description);
    return wrapper;
  }

  function renderCapabilities() {
    const current = model && model.capabilities ? model.capabilities : {};
    const catalogRefresh = Boolean(current.catalog_refresh);
    const packageInstall = Boolean(current.package_install);
    const repositoryError = model && model.repository_error ? String(model.repository_error) : "";

    capabilities.replaceChildren();
    const heading = document.createElement("strong");
    if (repositoryError) {
      heading.textContent = "Module distribution unavailable";
    } else {
      heading.textContent = catalogRefresh && packageInstall
        ? "Repository and package operations ready"
        : "Module distribution is partially available";
    }
    const copy = document.createElement("span");
    if (repositoryError) {
      copy.textContent = ` ${repositoryError}`;
    } else {
      copy.textContent = catalogRefresh
        ? (packageInstall
          ? " Core reports repository refresh and trusted package installation available."
          : " Repository metadata can refresh, but trusted package installation is unavailable.")
        : (packageInstall
          ? " Repository refresh unavailable; trusted packages can be applied from the current cached catalog."
          : " Repository refresh unavailable; install/update remains disabled until a trusted package provider is configured.");
    }
    capabilities.append(heading, copy);
    capabilities.dataset.state = catalogRefresh && packageInstall && !repositoryError ? "ready" : "limited";

    checkUpdates.disabled = !catalogRefresh || !authenticated || !csrfToken || busy;
    checkUpdates.title = !catalogRefresh
      ? "Repository refresh unavailable"
      : (!authenticated || !csrfToken)
        ? "Administrator authentication required"
        : "Check configured module repositories for updates";

    const repositoryMutation = Boolean(current.repository_mutation);
    for (const control of repositoryForm.elements) {
      control.disabled = !repositoryMutation || !authenticated || !csrfToken || busy;
    }
    repositoryForm.title = !repositoryMutation
      ? "Repository mutation unavailable"
      : (!authenticated || !csrfToken)
        ? "Administrator authentication required"
        : "";
  }

  function repositoryMutationButton(repository, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary";
    button.textContent = action === "disable" ? "Disable" : "Enable";
    button.disabled = !authenticated || !csrfToken || busy;
    button.addEventListener("click", () => mutateRepository(repository, action));
    return button;
  }

  function renderRepositories() {
    repositories.replaceChildren();
    const items = model && Array.isArray(model.repositories) ? model.repositories : [];
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "modules-empty";
      empty.textContent = "No module repositories are configured in canonical module authority.";
      repositories.append(empty);
      return;
    }

    for (const repository of items) {
      const card = document.createElement("article");
      card.className = "modules-repository";
      const identity = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = text(repository.display_name, repository.repository_id);
      const meta = document.createElement("div");
      meta.className = "modules-meta";
      meta.textContent = `${text(repository.repository_id)} · ${repository.enabled ? "enabled" : "disabled"}`;
      identity.append(name, meta);

      const state = document.createElement("div");
      state.className = "modules-meta";
      state.textContent = repository.catalog_fetched_at
        ? `Catalog ${repository.catalog_fetched_at}${repository.official ? " · official" : ""}`
        : `No cached catalog${repository.official ? " · official" : ""}`;
      const actions = document.createElement("div");
      actions.className = "modules-card-actions";
      const allowed = Array.isArray(repository.actions) ? repository.actions : [];
      for (const action of allowed) {
        if (action === "enable" || action === "disable") {
          actions.append(repositoryMutationButton(repository, action));
        }
      }
      card.append(identity, state, actions);
      repositories.append(card);
    }
  }

  function mutationButton(module, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = action === "remove" ? "button secondary" : "button";
    button.textContent = {
      install: "Install",
      update: "Update",
      rollback: "Roll Back",
      remove: "Remove",
    }[action] || action;
    button.disabled = !authenticated || !csrfToken || busy;
    button.addEventListener("click", () => mutateModule(module, action));
    return button;
  }

  function renderModules() {
    list.replaceChildren();
    const modules = model && Array.isArray(model.modules) ? model.modules : [];
    if (!modules.length) {
      const empty = document.createElement("div");
      empty.className = "modules-empty";
      empty.textContent = "No installed modules or cached catalog candidates are currently visible.";
      list.append(empty);
      updateAll.disabled = true;
      return;
    }

    let updates = 0;
    for (const module of modules) {
      const card = document.createElement("article");
      card.className = "modules-card";
      card.dataset.moduleId = module.module_id;

      const header = document.createElement("header");
      const title = document.createElement("div");
      const name = document.createElement("h3");
      name.textContent = text(module.display_name, module.module_id);
      const id = document.createElement("div");
      id.className = "modules-meta";
      id.textContent = module.module_id;
      title.append(name, id);

      const badges = document.createElement("div");
      badges.className = "modules-badges";
      if (module.installed) {
        badges.append(badge(module.installed.lifecycle_state || "installed"));
        if (module.installed.lifecycle_policy === "required") {
          badges.append(badge("required", "required"));
        }
      } else {
        badges.append(badge("not installed"));
      }
      if (module.available && module.available.update_available) {
        badges.append(badge("update available", "update"));
      }
      header.append(title, badges);

      const grid = document.createElement("dl");
      grid.className = "modules-grid";
      grid.append(
        detail(
          "Installed",
          module.installed
            ? `${module.installed.version} · build ${module.installed.build}`
            : "Not installed"
        ),
        detail(
          "Installed source",
          module.installed ? module.installed.source_repository_id : null
        ),
        detail(
          "Installed digest",
          module.installed ? module.installed.digest_sha256 : null
        ),
        detail(
          "Available",
          module.available
            ? `${module.available.version} · build ${module.available.build}`
            : "No cached candidate"
        ),
        detail(
          "Available source",
          module.available ? module.available.repository_id : null
        ),
        detail(
          "Available digest",
          module.available ? module.available.digest_sha256 : null
        ),
        detail(
          "Available signing key",
          module.available ? module.available.signature_identity : null
        ),
        detail(
          "Active artifact",
          module.installed ? module.installed.artifact_identity : null
        ),
        detail(
          "Previous artifact",
          module.previous ? module.previous.artifact_identity : null
        )
      );

      const actions = document.createElement("div");
      actions.className = "modules-card-actions";
      const allowed = Array.isArray(module.actions) ? module.actions : [];
      if (!allowed.length) {
        const none = document.createElement("span");
        none.className = "modules-meta";
        none.textContent = module.installed && module.installed.lifecycle_policy === "required"
          ? "Required module; ordinary remove/disable is blocked by Core policy."
          : "No lifecycle action is currently available.";
        actions.append(none);
      } else {
        for (const action of allowed) {
          actions.append(mutationButton(module, action));
          if (action === "update") updates += 1;
        }
      }

      card.append(header, grid, actions);
      list.append(card);
    }

    const packageInstall = Boolean(model.capabilities && model.capabilities.package_install);
    updateAll.disabled = !authenticated || !csrfToken || !packageInstall || updates === 0 || busy;
    updateAll.textContent = updates > 0 ? `Update All (${updates})` : "Update All";
  }

  async function loadModel() {
    model = await jsonRequest(MODULES_API);
    renderCapabilities();
    renderRepositories();
    renderModules();
  }

  async function refreshSession() {
    const config = await jsonRequest(CONFIG_STATUS_API);
    authenticated = Boolean(config.authenticated);
    csrfToken = null;
    if (authenticated) {
      const session = await jsonRequest(CONFIG_SESSION_API);
      csrfToken = session.csrf_token || null;
      authState.textContent = `Authenticated as ${text(session.actor, "admin")}. Lifecycle writes are enabled.`;
      loginForm.hidden = true;
    } else {
      authState.textContent = "Authenticate with the existing MonitorBox configuration administrator to mutate module authority.";
      loginForm.hidden = false;
    }
    renderCapabilities();
    renderRepositories();
    renderModules();
  }

  async function mutateRepository(repository, action) {
    if (!authenticated || !csrfToken || busy) return;
    if (action === "disable" && !window.confirm(
      `Disable ${repository.display_name || repository.repository_id}? Installed modules remain available, but catalog discovery will stop.`
    )) return;

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus(`${action === "disable" ? "Disabling" : "Enabling"} ${repository.display_name || repository.repository_id}…`);
    try {
      const id = encodeURIComponent(repository.repository_id);
      await jsonRequest(`${REPOSITORIES_API}/${id}/${action}`, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      await loadModel();
      setStatus(`Repository ${action === "disable" ? "disabled" : "enabled"}.`);
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
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
      const payload = await jsonRequest(`/api/v2/config/modules/${moduleId}/${action}`, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      setStatus(
        payload.runtime_reconcile === "restart_scheduled"
          ? "Module authority committed. MonitorBox restart scheduled."
          : "Module authority committed. Runtime restart is required."
      );
      if (payload.runtime_reconcile !== "restart_scheduled") {
        await loadModel();
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }

  async function updateAllModules() {
    if (!authenticated || !csrfToken || busy) return;
    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Applying compatible cached module updates independently…");
    try {
      const payload = await jsonRequest(UPDATE_ALL_API, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      const summary = `${payload.updated || 0} updated, ${payload.failed || 0} failed.`;
      setStatus(
        payload.runtime_reconcile === "restart_scheduled"
          ? `${summary} Module authority committed; MonitorBox restart scheduled.`
          : summary,
        Boolean(payload.failed)
      );
      if (payload.runtime_reconcile !== "restart_scheduled") {
        await loadModel();
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }

  repositoryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!authenticated || !csrfToken || busy) return;
    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Adding trusted module repository…");
    try {
      const credential = repositoryCredential.value.trim();
      const body = {
        repository_id: repositoryId.value.trim(),
        display_name: repositoryName.value.trim(),
        index_url: repositoryUrl.value.trim(),
        signature_identity: repositoryKeyId.value.trim(),
        public_key_base64: repositoryPublicKey.value.trim(),
      };
      if (credential) body.credential_handle = credential;
      await jsonRequest(REPOSITORIES_API, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [CSRF_HEADER]: csrfToken,
        },
        body: JSON.stringify(body),
      });
      repositoryForm.reset();
      await loadModel();
      setStatus("Repository trust added. Check for updates to verify and cache its signed catalog.");
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus("Authenticating…");
    try {
      await jsonRequest(CONFIG_LOGIN_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: password.value }),
      });
      password.value = "";
      await refreshSession();
      setStatus("Administrator session authenticated.");
    } catch (error) {
      setStatus(error.message || String(error), true);
    }
  });

  checkUpdates.addEventListener("click", async () => {
    if (!model || !model.capabilities || !model.capabilities.catalog_refresh) {
      setStatus("Repository refresh unavailable in this build; showing the current cached catalog.", true);
      return;
    }
    if (!authenticated || !csrfToken || busy) return;

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Checking configured module repositories for updates…");
    try {
      const payload = await jsonRequest(CHECK_UPDATES_API, {
        method: "POST",
        headers: { [CSRF_HEADER]: csrfToken },
      });
      await loadModel();
      const refreshed = Number(payload.refreshed || 0);
      const failed = Number(payload.failed || 0);
      setStatus(
        `Repository check complete: ${refreshed} refreshed, ${failed} failed.`,
        failed > 0
      );
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  });

  updateAll.addEventListener("click", updateAllModules);

  Promise.all([loadModel(), refreshSession()]).catch((error) => {
    setStatus(error.message || String(error), true);
  });
})();