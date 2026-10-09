"""#630: Guarded Modules release-channel control for the Core3 successor UI.

These patches are applied only to the newly built successor ZIP, after its existing
lifecycle overlay. Signed predecessor ZIPs and all historical UI sources remain
byte-identical. Every edit is anchored and fails closed on upstream drift.
"""
from __future__ import annotations


class ChannelSelectorDrift(ValueError):
    pass


def _once(source: str, old: str, new: str, label: str) -> str:
    if source.count(old) != 1:
        raise ChannelSelectorDrift("UI channel-selector boundary changed: " + label)
    return source.replace(old, new, 1)


def _member(files: dict, suffix: str) -> str:
    names = [name for name, body in files.items()
             if name.endswith(suffix) and isinstance(body, bytes)]
    if len(names) != 1:
        raise ChannelSelectorDrift("Expected one successor UI member: " + suffix)
    return names[0]


def apply(files: dict) -> None:
    js_member = _member(files, "/assets/modules.js")
    text = files[js_member].decode("utf-8")

    # The previous successor bridge offered a selector in the diagnostics/status
    # strip. The channel is a repository policy, not a diagnostic capability.
    begin = "    if (scaffoldLifecycle && releaseChannels.length) {\n"
    finish = '    capabilities.dataset.state = distributionReady && !repositoryError ? "ready" : "limited";'
    if text.count(begin) != 1 or text.count(finish) != 1:
        raise ChannelSelectorDrift("Prior successor capability control is missing")
    left = text.index(begin)
    right = text.index(finish, left)
    text = text[:left] + text[right:]
    text = _once(text,
        '    const releaseChannels = Array.isArray(current.release_channels) ? current.release_channels : [];\n'
        '    const preferredChannel = typeof current.preferred_channel === "string" ? current.preferred_channel : "";\n',
        "", "obsolete capability-local channel state")

    # Replaces only the summary content when successor lifecycle authority
    # actually supplies a preference; legacy 2.x repo rendering is untouched.
    selection = """    const channelAuthority = model && model.capabilities ? model.capabilities : {};
    if (channelAuthority.scaffold_lifecycle) {
      const preferred = String(channelAuthority.preferred_channel || "").toLowerCase();
      const allowed = Array.isArray(channelAuthority.release_channels)
        ? channelAuthority.release_channels : [];
      if (["stable", "beta", "dev"].includes(preferred)) {
        summary.replaceChildren();
        const label = document.createElement("label");
        label.htmlFor = "modules-release-channel";
        label.textContent = "Repositories enabled:";
        const selector = document.createElement("select");
        selector.id = "modules-release-channel";
        selector.className = "modules-channel-select";
        selector.setAttribute("aria-label", "MonitorBox module release channel");
        const names = {stable:"Stable", beta:"Beta", dev:"Dev"};
        for (const channel of ["stable", "beta", "dev"]) {
          const option = document.createElement("option");
          option.value = channel;
          option.textContent = names[channel];
          option.disabled = !allowed.includes(channel);
          selector.append(option);
        }
        selector.value = preferred;
        selector.disabled = busy || !authenticated || !csrfToken ||
          Boolean(channelAuthority.platform_updating) || !allowed.includes(preferred);
        selector.title = !authenticated || !csrfToken
          ? "Administrator authentication required"
          : "Allowed channels are constrained by deployment policy (maximum " +
            (channelAuthority.channel_ceiling || "unknown") + ")";
        selector.addEventListener("change", () => changeReleaseChannel(selector.value));
        summary.append(label, selector);
      } else {
        summary.textContent = "Release channel authority unavailable";
      }
    }
    repositories.append(summary);
"""
    text = _once(text,
        "    repositories.append(summary);\n\n    const details = document.createElement(\"details\");",
        selection + "\n    const details = document.createElement(\"details\");",
        "repository summary control")

    start_marker = "  async function changeReleaseChannel(channel) {\n"
    end_marker = "  async function updateAllModules() {\n"
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise ChannelSelectorDrift("Prior successor channel-change handler is missing")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    handler = """  async function verifyChannelCommit(channel) {
    // A 202 is an accepted transaction, not an already active preference.
    // Supervisor may recycle Core as the signed generation is committed.
    for (let attempt = 0; attempt < 30; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        const latest = await jsonRequest(MODULES_API);
        const authority = latest && latest.capabilities ? latest.capabilities : {};
        if (authority.scaffold_lifecycle &&
            authority.preferred_channel === channel && !authority.platform_updating) {
          model = latest;
          return true;
        }
      } catch (_) {
        // A transient network failure is expected during activation; keep polling.
      }
    }
    return false;
  }

  async function changeReleaseChannel(channel) {
    const authority = model && model.capabilities ? model.capabilities : {};
    const allowed = Array.isArray(authority.release_channels)
      ? authority.release_channels : [];
    const previous = authority.preferred_channel;
    if (!authority.scaffold_lifecycle || !allowed.includes(channel)) {
      setStatus("This release channel is not permitted by scaffold policy.", true);
      renderRepositories();
      return;
    }
    if (!authenticated || !csrfToken || busy || authority.platform_updating) {
      renderRepositories();
      return;
    }
    if (channel === previous) return;

    const caution = channel === "dev"
      ? "Dev receives experimental signed releases that may be unstable."
      : channel === "beta"
        ? "Beta receives signed prerelease packages ahead of Stable."
        : "Stable uses the accepted release feed; changing back does not erase history.";
    if (!window.confirm("Switch MonitorBox to " + channel.toUpperCase() +
        "?\\n\\n" + caution +
        "\\n\\nSupervisor will verify the complete compatible package generation before changing the saved preference. Continue?")) {
      renderRepositories();
      return;
    }

    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Verifying signed " + channel + " packages and staging the compatible generation…");
    try {
      const payload = await jsonRequest(RELEASE_CHANNEL_API, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [CSRF_HEADER]: csrfToken,
        },
        body: JSON.stringify({channel}),
      });
      const scheduled = Boolean(payload.accepted)
        || payload.runtime_reconcile === "scaffold_activation_scheduled";
      if (scheduled) {
        setStatus("Channel change accepted; waiting for signed generation activation…");
        if (await verifyChannelCommit(channel)) {
          setStatus("Channel now active: " + channel + ".");
          window.dispatchEvent(new Event("monitorbox:channel-committed"));
        } else {
          setStatus("Channel activation was accepted but is not yet confirmed. Refresh to verify the active channel.", true);
          await loadModel().catch(() => {});
        }
      } else {
        await loadModel();
        const observed = model && model.capabilities ? model.capabilities.preferred_channel : "";
        setStatus(observed === channel
          ? "Channel now active: " + channel + "."
          : "Channel did not change; recheck signed distribution status.",
          observed !== channel);
        if (observed === channel) window.dispatchEvent(new Event("monitorbox:channel-committed"));
      }
    } catch (error) {
      setStatus(error.message || String(error), true);
      await loadModel().catch(() => {});
    } finally {
      busy = false;
      renderCapabilities();
      renderRepositories();
      renderModules();
    }
  }

"""
    text = text[:start] + handler + text[end:]
    files[js_member] = text.encode("utf-8")

    # The shared header's baked Core release label describes the container,
    # not the selected package feed. Read the same authoritative state as the
    # Modules page and never use that baked channel as a successor fallback.
    shell_member = _member(files, "/assets/app-shell.js")
    shell = files[shell_member].decode("utf-8")
    shell = _once(shell,
        "    const [buildResult, stateResult] = await Promise.allSettled([",
        "    const [buildResult, stateResult, channelResult] = await Promise.allSettled([",
        "app-shell hydrate result destructuring")
    shell = _once(shell,
        "      fetch('/api/v2/state', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {\n"
        "        if (!response.ok) throw new Error(" + String.fromCharCode(96) + "state \${response.status}" + String.fromCharCode(96) + ");\n"
        "        return response.json();\n"
        "      }),\n"
        "    ]);",
        "      fetch('/api/v2/state', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {\n"
        "        if (!response.ok) throw new Error(" + String.fromCharCode(96) + "state \${response.status}" + String.fromCharCode(96) + ");\n"
        "        return response.json();\n"
        "      }),\n"
        "      fetch('/api/v2/modules', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {\n"
        "        if (!response.ok) throw new Error('module authority ' + response.status);\n"
        "        return response.json();\n"
        "      }),\n"
        "    ]);",
        "app-shell authoritative channel fetch")
    shell = _once(shell,
        "      const label = buildLabel(buildResult.value);\n",
        """      const identity = {...buildResult.value};
      const release = channelResult.status === 'fulfilled'
        ? channelResult.value?.capabilities : null;
      if (release?.scaffold_lifecycle) {
        identity.channel = ['stable','beta','dev'].includes(release.preferred_channel)
          ? release.preferred_channel : '';
      } else if (channelResult.status !== 'fulfilled') {
        identity.channel = ''; // Unknown is not the baked Core release channel.
      }
      const label = buildLabel(identity);
""", "app-shell build label")
    shell = _once(shell,
        "    applyCachedShell(shell);\n    const run = () => void hydrate(shell);",
        "    applyCachedShell(shell);\n"
        "    window.addEventListener('monitorbox:channel-committed', () => void hydrate(shell));\n"
        "    const run = () => void hydrate(shell);",
        "app-shell post-commit refresh")
    files[shell_member] = shell.encode("utf-8")

    css_member = _member(files, "/assets/modules.css")
    css = files[css_member].decode("utf-8")
    css += """
.modules-repository-one-line {display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.modules-repository-one-line label {font-weight:600}
.modules-channel-select {font:inherit;min-width:92px;border:1px solid #4c688e;
  border-radius:8px;padding:5px 28px 5px 10px;background:#15243a;color:inherit}
.modules-channel-select:disabled {opacity:.65;cursor:not-allowed}
"""
    files[css_member] = css.encode("utf-8")
