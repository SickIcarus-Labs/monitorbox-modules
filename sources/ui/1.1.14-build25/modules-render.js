  function repositoryMutationButton(repository, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary";
    button.textContent = action === "disable" ? "Disable" : "Enable";
    button.disabled = !authenticated || !csrfToken || busy;
    button.addEventListener("click", () => mutateRepository(repository, action));
    return button;
  }

  function normalizedRepositoryChannel(repository) {
    const explicit = String(repository?.channel || repository?.release_channel || "").trim().toLowerCase();
    if (explicit) return explicit === "latest" ? "stable" : explicit;
    if (!repository?.official) return "";
    const identity = String(repository.repository_id || "").trim().toLowerCase();
    const match = identity.match(/(?:^|[-_.])(dev|beta|stable|latest)$/);
    if (match) return match[1] === "latest" ? "stable" : match[1];
    return "stable";
  }

  function repositorySummaryLabel(repository) {
    const channel = normalizedRepositoryChannel(repository);
    return channel || text(repository.display_name, repository.repository_id);
  }

  function renderRepositories() {
    repositories.replaceChildren();
    const items = model && Array.isArray(model.repositories) ? model.repositories : [];
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "modules-empty";
      empty.textContent = "No module repositories are configured.";
      repositories.append(empty);
      return;
    }

    const enabled = items.filter(repository => repository.enabled);
    const healthy = !model?.repository_error && enabled.every(repository => repository.catalog_fetched_at);
    const summary = document.createElement("div");
    summary.className = "modules-repository-one-line";
    if (healthy) {
      const rank = new Map([["dev", 0], ["beta", 1], ["stable", 2]]);
      const labels = enabled
        .map(repository => ({
          label: repositorySummaryLabel(repository),
          official: Boolean(repository.official),
        }))
        .sort((left, right) => {
          const leftRank = left.official ? (rank.get(left.label) ?? 3) : 4;
          const rightRank = right.official ? (rank.get(right.label) ?? 3) : 4;
          return leftRank - rightRank || left.label.localeCompare(right.label);
        })
        .map(item => item.label);
      summary.textContent = `Repositories enabled: ${labels.join(", ") || "none"}`;
    } else {
      summary.textContent = `${enabled.length} of ${items.length} repositories enabled${model?.repository_error ? " · repository error" : ""}`;
    }
    repositories.append(summary);

    const details = document.createElement("details");
    details.className = "modules-repository-details modules-disclosure";
    const detailsSummary = document.createElement("summary");
    detailsSummary.textContent = "Repository details";
    const list = document.createElement("div");
    list.className = "modules-repository-summary";
    for (const repository of items) {
      const row = document.createElement("div");
      row.className = "modules-repository-row";
      row.dataset.repositoryId = text(repository.repository_id, "unknown");

      const identity = document.createElement("div");
      identity.className = "modules-repository-identity";
      const name = document.createElement("strong");
      name.textContent = text(repository.display_name, repository.repository_id);
      const meta = document.createElement("span");
      meta.className = "modules-meta";
      const state = repository.enabled ? "enabled" : "disabled";
      const authority = repository.official ? `official · ${repositorySummaryLabel(repository)}` : text(repository.repository_id);
      const catalog = repository.catalog_fetched_at ? "catalog ready" : "no cached catalog";
      meta.textContent = `${authority} · ${state} · ${catalog}`;
      identity.append(name, meta);

      const actions = document.createElement("div");
      actions.className = "modules-card-actions compact";
      for (const action of Array.isArray(repository.actions) ? repository.actions : []) {
        if (action === "enable" || action === "disable") {
          actions.append(repositoryMutationButton(repository, action));
        }
      }
      row.append(identity, actions);
      list.append(row);
    }
    details.append(detailsSummary, list);
    repositories.append(details);
  }

  function mutationButton(module, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = action === "remove" ? "button secondary" : "button";
    button.dataset.moduleAction = action;
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

  function repositoryForSource(source) {
    const items = model && Array.isArray(model.repositories) ? model.repositories : [];
    return items.find(repository => String(repository.repository_id) === String(source)) || null;
  }

  function sourceLabel(source) {
    if (!source) return "—";
    const repository = repositoryForSource(source);
    return repository ? repositorySummaryLabel(repository) : text(source);
  }

  function moduleSource(module, installed) {
    const record = installed ? module.installed : module.available;
    if (!record) return "—";
    const source = installed ? record.source_repository_id : record.repository_id;
    const channel = String(record.channel || record.release_channel || "").trim();
    if (channel) return channel === "latest" ? "stable" : channel;
    return sourceLabel(source);
  }

  function versionLabel(record) {
    if (!record) return "—";
    const version = text(record.version, "unknown").replace(/^v/i, "");
    return `v${version}`;
  }

  function exactVersion(record) {
    if (!record) return "—";
    return `${versionLabel(record)} · build ${text(record.build)}`;
  }

  function technicalDetails(module) {
    const detailsElement = document.createElement("details");
    detailsElement.className = "modules-technical modules-disclosure";
    const summary = document.createElement("summary");
    summary.textContent = "Advanced / Diagnostics";
    const grid = document.createElement("dl");
    grid.className = "modules-grid modules-grid-technical";
    grid.append(
      detail("Module ID", module.module_id),
      detail("Installed artifact", module.installed ? module.installed.artifact_identity : null),
      detail("Installed digest", module.installed ? module.installed.digest_sha256 : null),
      detail("Installed source", module.installed ? module.installed.source_repository_id : null),
      detail("Previous artifact", module.previous ? module.previous.artifact_identity : null),
      detail("Available source", module.available ? module.available.repository_id : null),
      detail("Available digest", module.available ? module.available.digest_sha256 : null),
      detail("Available signing identity", module.available ? module.available.signature_identity : null),
      detail("Requires Core", module.installed?.requires_core || module.available?.requires_core),
      detail("Requires Module API", module.installed?.requires_runtime_api || module.available?.requires_runtime_api)
    );
    detailsElement.append(summary, grid);
    return detailsElement;
  }

  function lifecycleBadges(module) {
    const badges = document.createElement("div");
    badges.className = "modules-badges";
    if (module.installed) {
      const state = module.installed.lifecycle_state || (module.installed.enabled === false ? "disabled" : "installed");
      badges.append(badge(state));
      if (module.installed.lifecycle_policy === "required") badges.append(badge("required", "required"));
      if (module.available && module.available.update_available) badges.append(badge("update available", "update"));
    } else {
      badges.append(badge("available"));
    }
    return badges;
  }

  function renderModuleTile(module, installed) {
    const card = document.createElement("details");
    card.className = "modules-card modules-tile modules-disclosure";
    card.dataset.moduleId = module.module_id;
    card.dataset.installed = installed ? "true" : "false";

    const summary = document.createElement("summary");
    summary.className = "modules-tile-summary";
    const identity = document.createElement("div");
    identity.className = "modules-tile-identity";
    const name = document.createElement("strong");
    name.className = "modules-tile-name";
    name.textContent = text(module.display_name, module.module_id);
    const release = document.createElement("span");
    release.className = "modules-release";
    release.textContent = installed ? exactVersion(module.installed) : exactVersion(module.available);
    const source = document.createElement("span");
    source.className = "modules-meta modules-source";
    source.textContent = moduleSource(module, installed);
    identity.append(name, release, source);
    summary.append(identity, lifecycleBadges(module));

    const body = document.createElement("div");
    body.className = "modules-tile-body";
    const description = document.createElement("p");
    description.className = "modules-description";
    description.textContent = text(module.description, "No module description is published.");
    body.append(description);

    const releaseGrid = document.createElement("dl");
    releaseGrid.className = "modules-grid modules-grid-release";
    if (installed) {
      releaseGrid.append(
        detail("Installed", exactVersion(module.installed)),
        detail("Source / channel", moduleSource(module, true)),
        detail("Lifecycle", module.installed.lifecycle_policy || "optional")
      );
      if (module.available) {
        releaseGrid.append(
          detail("Available", exactVersion(module.available)),
          detail("Available source / channel", moduleSource(module, false))
        );
      }
    } else {
      releaseGrid.append(
        detail("Available", exactVersion(module.available)),
        detail("Source / channel", moduleSource(module, false))
      );
    }
    body.append(releaseGrid);

    const actions = document.createElement("div");
    actions.className = "modules-card-actions";
    const allowed = Array.isArray(module.actions) ? module.actions : [];
    if (!allowed.length) {
      const none = document.createElement("span");
      none.className = "modules-meta";
      none.textContent = installed && module.installed?.lifecycle_policy === "required"
        ? "Required module; Core policy currently authorizes no lifecycle action."
        : "Core currently authorizes no lifecycle action.";
      actions.append(none);
    } else {
      // Core is authoritative. Render every authorized action independently; presentation
      // must never infer or suppress lifecycle actions from update/lifecycle state.
      for (const action of allowed) actions.append(mutationButton(module, action));
    }
    body.append(actions, technicalDetails(module));
    card.append(summary, body);
    return card;
  }

  function renderModuleGroup(label, items, expanded) {
    const group = document.createElement("details");
    group.className = "modules-group modules-disclosure";
    group.open = expanded;
    group.dataset.group = label.toLowerCase();
    const summary = document.createElement("summary");
    summary.className = "modules-group-summary";
    summary.textContent = `${label} Modules (${items.length})`;
    const body = document.createElement("div");
    body.className = "modules-group-body";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "modules-empty";
      empty.textContent = label === "Available"
        ? "No uninstalled compatible modules are available from the current catalogs."
        : "No modules are installed.";
      body.append(empty);
    } else {
      for (const module of items) body.append(renderModuleTile(module, label === "Installed"));
    }
    group.append(summary, body);
    return group;
  }

  function renderModules() {
    list.replaceChildren();
    const modules = model && Array.isArray(model.modules) ? model.modules : [];
    const installed = modules.filter(module => Boolean(module.installed));
    const installedIds = new Set(installed.map(module => module.module_id));
    const available = modules.filter(module => !installedIds.has(module.module_id) && Boolean(module.available));

    list.append(
      renderModuleGroup("Installed", installed, true),
      renderModuleGroup("Available", available, false)
    );

    const updates = installed.reduce(
      (count, module) => count + ((Array.isArray(module.actions) && module.actions.includes("update")) ? 1 : 0),
      0
    );
    const packageInstall = Boolean(model && model.capabilities && model.capabilities.package_install);
    updateAll.disabled = !authenticated || !csrfToken || !packageInstall || updates === 0 || busy;
    updateAll.textContent = updates > 0 ? `Update All (${updates})` : "Update All";
  }
