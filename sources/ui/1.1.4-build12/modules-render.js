  function semanticRelease(artifact) {
    return artifact && artifact.version ? `v${artifact.version}` : "—";
  }

  function exactRelease(artifact) {
    if (!artifact || !artifact.version) return "—";
    return `${semanticRelease(artifact)} · build ${text(artifact.build)}`;
  }

  function runtimeApiLabel(requirement) {
    const value = text(requirement, "");
    const match = /^>=(\d+)\s+<(\d+)$/.exec(value);
    if (match && Number(match[2]) === Number(match[1]) + 1) return match[1];
    return value || "—";
  }

  function supportFingerprint(module) {
    const artifact = module && (module.installed || module.available);
    if (!artifact || !artifact.version) return "—";
    return `${module.module_id}=${artifact.version}+${text(artifact.build)}`;
  }

  function candidateStatus(module) {
    const candidate = module && module.available;
    if (!candidate) return "No cached candidate";
    if (candidate.compatible === false) {
      return `Blocked${candidate.reason ? ` · ${candidate.reason}` : ""}`;
    }
    return candidate.compatible === true ? "Compatible" : "Compatibility unknown";
  }

  function updatePresentation(module) {
    const installed = module && module.installed;
    const candidate = module && module.available;
    if (!installed) return candidate ? `Install ${exactRelease(candidate)}` : "No cached candidate";
    if (!candidate) return "Current · no cached candidate";
    if (candidate.compatible === false) {
      return `Blocked ${exactRelease(candidate)}${candidate.reason ? ` · ${candidate.reason}` : ""}`;
    }
    if (!candidate.update_available) return "Current";
    if (String(installed.version) === String(candidate.version)) {
      return `Packaging/rebuild · ${semanticRelease(candidate)} · build ${text(installed.build)} → build ${text(candidate.build)}`;
    }
    return `${semanticRelease(installed)} → ${semanticRelease(candidate)}`;
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
      const primaryArtifact = module.installed || module.available;
      const release = document.createElement("strong");
      release.className = "modules-release-primary";
      release.textContent = semanticRelease(primaryArtifact);
      const id = document.createElement("div");
      id.className = "modules-meta modules-release-secondary";
      id.textContent = primaryArtifact
        ? `${module.module_id} · build ${text(primaryArtifact.build)}`
        : module.module_id;
      title.append(name, release, id);

      if (module.installed && module.available) {
        const candidate = document.createElement("div");
        candidate.className = "modules-meta modules-release-candidate";
        if (module.available.compatible === false) {
          candidate.textContent = `Candidate ${exactRelease(module.available)} · blocked`;
        } else if (module.available.update_available) {
          candidate.textContent = `Latest ${exactRelease(module.available)}`;
        } else {
          candidate.textContent = `Latest ${exactRelease(module.available)} · current`;
        }
        title.append(candidate);
      }

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
      if (module.available && module.available.compatible === false) {
        badges.append(badge("candidate blocked", "blocked"));
      } else if (module.available && module.available.update_available) {
        badges.append(badge("update available", "update"));
      }
      header.append(title, badges);

      const installed = module.installed;
      const available = module.available;
      const previous = module.previous;
      const grid = document.createElement("dl");
      grid.className = "modules-grid";
      grid.append(
        detail("Version", installed ? semanticRelease(installed) : "Not installed"),
        detail("Build", installed ? installed.build : null),
        detail("Module API", installed ? runtimeApiLabel(installed.requires_runtime_api) : null),
        detail("Requires Core", installed ? installed.requires_core : null),
        detail("Support identity", supportFingerprint(module)),
        detail("Installed source", installed ? installed.source_repository_id : null),
        detail("Installed digest", installed ? installed.digest_sha256 : null),
        detail("Latest version", available ? semanticRelease(available) : "No cached candidate"),
        detail("Latest build", available ? available.build : null),
        detail("Candidate status", candidateStatus(module)),
        detail("Update path", updatePresentation(module)),
        detail("Available source", available ? available.repository_id : null),
        detail("Available signing key", available ? available.signature_identity : null),
        detail("Previous release", previous ? exactRelease(previous) : null),
        detail("Active artifact", installed ? installed.artifact_identity : null),
        detail("Previous artifact", previous ? previous.artifact_identity : null)
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
