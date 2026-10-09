#!/usr/bin/env python3
"""UI55: appliance-wide signed release-channel selection on Modules and app header.

Rebuilds from exact immutable signed UI54; never edits a historical package.
The selector calls the authenticated Core/Supervisor lifecycle transaction.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_first_party_ui as stable
import build_first_party_ui_build54 as previous

UI_VERSION = "1.18.0"
UI_BUILD = 55
UI_GENERATION = f"{UI_VERSION}-{UI_BUILD}"
PARENT_GENERATION = previous.UI_GENERATION
PARENT_IMPORT_PACKAGE = previous.TARGET_IMPORT_PACKAGE
TARGET_IMPORT_PACKAGE = "monitorbox_ui_b55"
RELEASE55 = stable.Release(
    build=UI_BUILD,
    version=UI_VERSION,
    certified_sha="feature-630-module-release-channel-selector",
)
SIGNED_UI54_SHA256 = "c51119fc0615f8d6108d6f6d6b43745209424e0385637c6853201c8b2742fb14"


def one(source: str, before: str, after: str, label: str) -> str:
    if source.count(before) != 1:
        raise RuntimeError(f"UI55 parent {label} contract drift: {source.count(before)} matches")
    return source.replace(before, after)


CHANNEL_CONTROL = r'''
  async function changeReleaseChannel(channel) {
    const previous = model?.capabilities?.preferred_channel;
    const allowed = model?.capabilities?.release_channels || [];
    if (!authenticated || !csrfToken || busy || !allowed.includes(channel) || channel === previous) {
      renderRepositories();
      return;
    }
    const warning = channel === "stable"
      ? "Switch MonitorBox to Stable? Only compatible signed Stable packages will be eligible. A validated package generation may be activated. Switching policy does not by itself prove a prerelease downgrade."
      : "Switch MonitorBox to " + channel.toUpperCase() + "? This permits signed " + channel + " packages, potentially replacing stable components. MonitorBox will validate compatibility and may restart when a new generation activates.";
    if (!window.confirm(warning)) { renderRepositories(); return; }
    busy = true;
    renderCapabilities();
    renderRepositories();
    renderModules();
    setStatus("Validating signed " + channel + " packages and compatible generation…");
    try {
      const result = await jsonRequest(RELEASE_CHANNEL_API, {
        method: "POST",
        headers: { "Content-Type": "application/json", [CSRF_HEADER]: csrfToken },
        body: JSON.stringify({channel}),
      });
      await loadModel();
      if (result.accepted) {
        setStatus("Signed " + channel + " generation accepted for activation. Policy changes after verified activation; no Compose pull is required.");
        watchChannelActivation(channel);
      } else {
        setStatus("Release policy unchanged: " + text(result.preferred_channel, previous) + ".");
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

  function watchChannelActivation(target) {
    let attempts = 0;
    async function check() {
      attempts++;
      try {
        await loadModel();
        const policy = model?.capabilities || {};
        if (policy.preferred_channel === target && !policy.platform_updating) {
          setStatus("MonitorBox release channel: " + target + ". Active signed generation verified.");
          return;
        }
        if (!policy.platform_updating && policy.preferred_channel !== target) {
          setStatus("Channel activation was not confirmed. Still using " + text(policy.preferred_channel, "prior") + " policy; review lifecycle diagnostics.", true);
          return;
        }
      } catch (_) { /* The supervisor may restart Core during activation. */ }
      if (attempts < 45) window.setTimeout(check, 2000);
      else setStatus("Channel activation not confirmed. Reload Modules to inspect the actual policy.", true);
    }
    window.setTimeout(check, 2000);
  }

'''


SELECTOR_RENDER = r'''    const policy = model?.capabilities || {};
    const channels = ["stable", "beta", "dev"];
    const permitted = Array.isArray(policy.release_channels) ? policy.release_channels : [];
    if (policy.scaffold_lifecycle && channels.includes(policy.preferred_channel)) {
      const label = document.createElement("span");
      label.textContent = "Repositories enabled: ";
      const select = document.createElement("select");
      select.id = "modules-release-channel";
      select.className = "modules-channel-select";
      select.setAttribute("aria-label", "Module release channel");
      select.title = "Appliance module release policy; maximum channel: " + text(policy.channel_ceiling, "unknown");
      for (const channel of channels) {
        const option = document.createElement("option");
        option.value = channel;
        option.textContent = channel[0].toUpperCase() + channel.slice(1);
        option.disabled = !permitted.includes(channel);
        if (option.disabled) option.title = "Restricted by deployment policy";
        select.append(option);
      }
      select.value = policy.preferred_channel;
      select.disabled = !permitted.includes(policy.preferred_channel) || !authenticated ||
        !csrfToken || busy || Boolean(policy.platform_updating);
      select.addEventListener("change", () => changeReleaseChannel(select.value));
      summary.append(label, select);
    } else if (policy.scaffold_lifecycle) {
      summary.textContent = "Release channel policy unavailable; changes disabled.";
    } else if (healthy) {'''


def patch_modules(source: str) -> str:
    source = one(
        source,
        '  const REPOSITORIES_API = "/api/v2/config/modules/repositories";',
        '  const REPOSITORIES_API = "/api/v2/config/modules/repositories";\n'
        '  const RELEASE_CHANNEL_API = "/api/v2/config/modules/release-channel";',
        "channel API",
    )
    source = one(
        source,
        '    const items = model && Array.isArray(model.repositories) ? model.repositories : [];\n'
        '    if (!items.length) {',
        '    const items = model && Array.isArray(model.repositories) ? model.repositories : [];\n'
        '    if (!items.length && !model?.capabilities?.scaffold_lifecycle) {',
        "empty repository projection",
    )
    source = one(
        source,
        '    summary.className = "modules-repository-one-line";\n    if (healthy) {',
        '    summary.className = "modules-repository-one-line";\n' + SELECTOR_RENDER,
        "repository channel selector",
    )
    source = one(
        source,
        '  async function mutateRepository(repository, action) {',
        CHANNEL_CONTROL + '  async function mutateRepository(repository, action) {',
        "release channel mutation",
    )
    return source


def patch_app_shell(source: str) -> str:
    source = one(
        source, "const SHELL_CACHE_KEY = 'monitorbox.shell.cache.v1';",
        "const SHELL_CACHE_KEY = 'monitorbox.shell.cache.v2-channel-policy';",
        "old image-channel cache",
    )
    source = one(source, "  function buildLabel(identity) {",
                 "  function buildLabel(identity, effectiveChannel) {",
                 "header identity interface")
    source = one(
        source,
        "    const channel = String(identity.channel || '').trim();",
        "    // Container image provenance is not authoritative release policy.\n"
        "    const channel = String(effectiveChannel || '').trim();",
        "header source policy",
    )
    source = one(
        source, "    const [buildResult, stateResult] = await Promise.allSettled([",
        "    const [buildResult, stateResult, moduleResult] = await Promise.allSettled([",
        "header hydration",
    )
    source = one(
        source,
        """        return response.json();
      }),
    ]);

    if (buildResult.status === 'fulfilled') {""",
        """        return response.json();
      }),
      fetch('/api/v2/modules', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {
        if (!response.ok) throw new Error('module policy ' + response.status);
        return response.json();
      }),
    ]);

    if (buildResult.status === 'fulfilled') {""",
        "header policy API",
    )
    source = one(
        source,
        "      const label = buildLabel(buildResult.value);",
        """      const policy = moduleResult.status === 'fulfilled' ? moduleResult.value?.capabilities : null;
      const effective = policy?.scaffold_lifecycle &&
        Array.isArray(policy.release_channels) &&
        policy.release_channels.includes(policy.preferred_channel)
          ? policy.preferred_channel : null;
      const label = buildLabel(buildResult.value, effective);""",
        "header effective channel",
    )
    return source


def _package_files(root: Path) -> dict[str, bytes]:
    signed_parent = previous._package_files(root)
    if hashlib.sha256(stable._zip_bytes(signed_parent)).hexdigest() != SIGNED_UI54_SHA256:
        raise RuntimeError("UI55 signed immutable UI54 predecessor drift")
    prefix = PARENT_IMPORT_PACKAGE + "/"
    if any(not path.startswith(prefix) for path in signed_parent):
        raise RuntimeError("UI55 parent package boundary changed")
    payloads = {path[len(prefix):]: body for path, body in signed_parent.items()}
    for name, value in list(payloads.items()):
        value = value.replace(PARENT_GENERATION.encode(), UI_GENERATION.encode())
        value = value.replace(PARENT_IMPORT_PACKAGE.encode(), TARGET_IMPORT_PACKAGE.encode())
        payloads[name] = value

    init = payloads["__init__.py"].decode("utf-8")
    init = one(
        init, "Standalone managed MonitorBox UI 1.17.1 build 54.",
        "Standalone managed MonitorBox UI 1.18.0 build 55.",
        "module identity",
    )
    payloads["__init__.py"] = init.encode("utf-8")

    modules_js = payloads["assets/modules.js"].decode("utf-8")
    payloads["assets/modules.js"] = patch_modules(modules_js).encode("utf-8")
    shell_js = payloads["assets/app-shell.js"].decode("utf-8")
    payloads["assets/app-shell.js"] = patch_app_shell(shell_js).encode("utf-8")
    payloads["assets/modules.css"] += b"""
/* Signed appliance release policy: compact, accessible native selector. */
.modules-channel-select {
  appearance: auto;
  border: 1px solid rgba(134, 170, 219, .52);
  border-radius: 7px;
  background: #13243a;
  color: #e8eef7;
  font: inherit;
  padding: 4px 9px;
  margin-left: 5px;
  cursor: pointer;
}
.modules-channel-select:disabled { opacity: .6; cursor: not-allowed; }
.modules-channel-select:focus-visible { outline: 2px solid #7da6ff; outline-offset: 2px; }
"""
    if PARENT_GENERATION.encode() in payloads["assets/app-shell.js"]:
        raise RuntimeError("UI55 retained stale header generation")
    if b"identity.channel" in payloads["assets/app-shell.js"]:
        raise RuntimeError("UI55 header still follows container image release channel")
    return {
        TARGET_IMPORT_PACKAGE + "/" + name: body
        for name, body in payloads.items()
    }


def build(root: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = stable._zip_bytes(_package_files(root))
    target = output_dir / RELEASE55.filename
    target.write_bytes(payload)
    print(f"UI55 reproducible unsigned candidate: {target} sha256={hashlib.sha256(payload).hexdigest()}")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "packages")
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent, args.output_dir)
