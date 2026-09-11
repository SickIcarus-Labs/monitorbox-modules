'use strict';

(()=>{
  const UI_GENERATION = '1.1.14-26';
  const SHELL_CACHE_KEY = 'monitorbox.shell.cache.v1';
  const NAV_ITEMS = Object.freeze([
    ['/', 'Dashboard'],
    ['/settings', 'Configure'],
    ['/settings#connections', 'Connections'],
    ['/settings/discover', 'Discoveries'],
    ['/settings/dashboard', 'Dashboard / Graphs'],
    ['/modules', 'Modules'],
    ['/settings/policy', 'Actions & policy'],
    ['/settings/appliance', 'Appliance'],
    ['/settings/recovery', 'Backup & Restore'],
  ]);

  const KNOWN_PAGES = Object.freeze([
    [/^\/$/, {title:'Dashboard'}],
    [/^\/modules(?:\/|$)/, {title:'Modules'}],
    [/^\/settings\/quick-add(?:\/|$)/, {title:'Add monitoring', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/discover(?:\/|$)/, {title:'Discoveries', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/advanced(?:\/|$)/, {title:'Advanced Configuration', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/dashboard(?:\/|$)/, {title:'Dashboard / Graphs', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/policy(?:\/|$)/, {title:'Actions & policy', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/appliance(?:\/|$)/, {title:'Appliance', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings\/recovery(?:\/|$)/, {title:'Backup & Restore', upHref:'/settings', upLabel:'Configuration'}],
    [/^\/settings(?:\/|$)/, {title:'Configuration', upHref:'/', upLabel:'Dashboard'}],
    [/^\/setup(?:\/|$)/, {title:'Guided Setup', upHref:'/', upLabel:'Dashboard'}],
  ]);

  const HEALTH = new Set(['healthy', 'degraded', 'critical', 'unknown']);

  function cleanTitle(value) {
    return String(value || '')
      .replace(/\s+[·|\-]\s+MonitorBox.*$/i, '')
      .replace(/^MonitorBox\s+[·|\-]\s+/i, '')
      .trim();
  }

  function fallbackTitle() {
    const heading = document.querySelector('main h1, main h2, .workspace h1, .workspace h2');
    if (heading && heading.textContent.trim()) return heading.textContent.trim();
    return cleanTitle(document.title) || 'MonitorBox';
  }

  function pageMeta() {
    const body = document.body;
    const explicit = {
      title: body.dataset.mbPageTitle || '',
      upHref: body.dataset.mbUpHref || '',
      upLabel: body.dataset.mbUpLabel || '',
    };
    const known = KNOWN_PAGES.find(([pattern]) => pattern.test(location.pathname));
    const defaults = known ? known[1] : {};
    return {
      title: explicit.title || defaults.title || fallbackTitle(),
      upHref: explicit.upHref || defaults.upHref || '',
      upLabel: explicit.upLabel || defaults.upLabel || '',
    };
  }

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function findLegacyTopbar() {
    return document.querySelector(':scope > .v22-topbar, :scope > .modules-topbar, body > header.top');
  }

  function pageActionsFromLegacy() {
    const legacy = findLegacyTopbar();
    if (!legacy) {
      document.getElementById('v22-menu')?.remove();
      document.getElementById('settingsV22Menu')?.remove();
      return null;
    }

    const actionStrip = make('div', 'mb-page-actions');
    actionStrip.setAttribute('aria-label', 'Page actions');

    // Debug is a global diagnostic capability and is adopted into the shared shell.
    // Only actual Dashboard/page-local actions belong in the page action strip.
    const dashboardActionIds = ['reload', 'v22-discoveries', 'check-all'];
    for (const id of dashboardActionIds) {
      const node = legacy.querySelector(`#${id}`);
      if (node) actionStrip.append(node);
    }

    const legacyGlobalIds = new Set([
      'settingsV22MenuButton',
      'settingsProductHome',
      'settingsBackToMonitoring',
      'settingsV22Spacer',
      'settingsSiteHome',
    ]);

    if (legacy.matches('header.top')) {
      const children = [...legacy.children];
      for (const child of children) {
        if (legacyGlobalIds.has(child.id)) continue;
        if (child.matches('h1')) continue;
        if (child.matches('a[href="/"], a[href="/settings"]')) continue;
        if (child.classList.contains('spacer') && !actionStrip.childElementCount) continue;
        actionStrip.append(child);
      }
    }

    legacy.remove();
    document.getElementById('v22-menu')?.remove();
    document.getElementById('settingsV22Menu')?.remove();

    if (!actionStrip.childElementCount) return null;
    const firstContent = document.querySelector('main, body > .shell, body > #app, body > .login, body > section, body > div');
    if (firstContent) firstContent.before(actionStrip);
    else document.body.append(actionStrip);
    return actionStrip;
  }

  function createShell(meta, debugControl) {
    const shell = make('header', 'mb-app-shell mb-health-unknown');
    shell.id = 'mb-app-shell';
    shell.dataset.health = 'unknown';
    shell.dataset.uiGeneration = UI_GENERATION;

    const menuButton = make('button', 'mb-shell-menu', '☰');
    menuButton.type = 'button';
    menuButton.setAttribute('aria-label', 'Open MonitorBox menu');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-controls', 'mb-shell-nav');

    const home = make('a', 'mb-shell-home');
    home.href = '/';
    home.setAttribute('aria-label', 'MonitorBox Home');
    home.title = 'MonitorBox Home';
    const glyph = make('span', 'mb-shell-glyph');
    glyph.setAttribute('aria-hidden', 'true');
    home.append(glyph);

    const hierarchy = make('div', 'mb-shell-hierarchy');
    const product = make('span', 'mb-shell-product', 'MonitorBox');
    const title = make('strong', 'mb-shell-title', meta.title);
    hierarchy.append(product, title);
    if (meta.upHref && location.pathname !== '/') {
      const up = make('a', 'mb-shell-up', `← ${meta.upLabel || 'Up'}`);
      up.href = meta.upHref;
      up.setAttribute('aria-label', `Up to ${meta.upLabel || 'parent page'}`);
      hierarchy.prepend(up);
    }

    if (debugControl) {
      debugControl.className = 'mb-shell-debug';
      debugControl.textContent = 'Debug';
      debugControl.title = 'Open MonitorBox live diagnostics';
      debugControl.setAttribute('aria-label', 'Open MonitorBox live diagnostics');
    }

    const runtime = make('div', 'mb-shell-runtime');
    const bodyIdentity = String(document.body?.dataset?.monitorboxBuild || '').trim();
    const core = make('span', 'mb-shell-core', bodyIdentity || 'Core …');
    core.id = 'mb-shell-core';
    const site = make('span', 'mb-shell-site', 'Site · Loading');
    site.id = 'mb-shell-site';
    runtime.append(core, site);

    const nav = make('nav', 'mb-shell-nav');
    nav.id = 'mb-shell-nav';
    nav.hidden = true;
    nav.setAttribute('aria-label', 'MonitorBox');
    for (const [href, label] of NAV_ITEMS) {
      const link = make('a', '', label);
      link.href = href;
      nav.append(link);
    }

    menuButton.addEventListener('click', event => {
      event.stopPropagation();
      nav.hidden = !nav.hidden;
      menuButton.setAttribute('aria-expanded', String(!nav.hidden));
    });
    nav.addEventListener('click', event => event.stopPropagation());
    const close = () => {
      nav.hidden = true;
      menuButton.setAttribute('aria-expanded', 'false');
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });

    shell.append(menuButton, home, hierarchy);
    if (debugControl) shell.append(debugControl);
    shell.append(runtime, nav);
    return shell;
  }

  function buildLabel(identity) {
    if (!identity || typeof identity !== 'object') return 'Core identity unavailable';
    const version = String(identity.version || '').trim();
    const build = String(identity.build ?? '').trim();
    const channel = String(identity.channel || '').trim();
    const bits = [];
    if (version) bits.push(`v${version.replace(/^v/i, '')}`);
    if (build) bits.push(`build ${build}`);
    if (channel) bits.push(channel);
    return bits.length ? bits.join(' · ') : 'Core identity unavailable';
  }

  function normalizedHealth(value) {
    const state = String(value || '').toLowerCase();
    return HEALTH.has(state) ? state : 'unknown';
  }

  function siteSummary(state) {
    const sites = Array.isArray(state?.sites) ? state.sites : [];
    if (!sites.length) return {name:'Site', health:'unknown'};
    const ranked = {critical:3, degraded:2, unknown:1, healthy:0};
    let selected = sites[0];
    for (const site of sites.slice(1)) {
      const current = normalizedHealth(selected?.state);
      const candidate = normalizedHealth(site?.state);
      if ((ranked[candidate] ?? 1) > (ranked[current] ?? 1)) selected = site;
    }
    return {
      name: selected?.label || selected?.name || selected?.id || (sites.length > 1 ? `${sites.length} sites` : 'Site'),
      health: normalizedHealth(selected?.state),
      count: sites.length,
    };
  }

  function applySite(shell, summary) {
    if (!summary) return;
    const site = shell.querySelector('#mb-shell-site');
    const health = normalizedHealth(summary.health);
    const name = summary.name || 'Site';
    site.textContent = `${name} · ${health[0].toUpperCase()}${health.slice(1)}`;
    if (summary.count > 1) site.title = `${summary.count} sites · worst current site health shown`;
    shell.dataset.health = health;
    shell.classList.remove(...[...HEALTH].map(value => `mb-health-${value}`));
    shell.classList.add(`mb-health-${health}`);
  }

  function readShellCache() {
    try {
      const raw = sessionStorage.getItem(SHELL_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function writeShellCache(update) {
    try {
      const current = readShellCache() || {};
      sessionStorage.setItem(SHELL_CACHE_KEY, JSON.stringify({...current, ...update}));
    } catch (_) {}
  }

  function applyCachedShell(shell) {
    const cached = readShellCache();
    if (!cached) return;
    if (cached.build && Date.now() - Number(cached.build_at || 0) < 3600000) {
      shell.querySelector('#mb-shell-core').textContent = cached.build;
    }
    if (cached.site && Date.now() - Number(cached.site_at || 0) < 30000) {
      applySite(shell, cached.site);
    }
  }

  async function hydrate(shell) {
    const core = shell.querySelector('#mb-shell-core');
    const site = shell.querySelector('#mb-shell-site');
    const [buildResult, stateResult] = await Promise.allSettled([
      fetch('/api/v2/build', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {
        if (!response.ok) throw new Error(`build ${response.status}`);
        return response.json();
      }),
      fetch('/api/v2/state', {headers:{Accept:'application/json'}, cache:'no-store'}).then(response => {
        if (!response.ok) throw new Error(`state ${response.status}`);
        return response.json();
      }),
    ]);

    if (buildResult.status === 'fulfilled') {
      const label = buildLabel(buildResult.value);
      core.textContent = label;
      writeShellCache({build:label, build_at:Date.now()});
    }

    if (stateResult.status === 'fulfilled') {
      const summary = siteSummary(stateResult.value);
      applySite(shell, summary);
      writeShellCache({site:summary, site_at:Date.now()});
    } else if (!readShellCache()?.site) {
      site.textContent = 'Site · Unknown';
    }
  }

  function scheduleHydration(shell) {
    applyCachedShell(shell);
    const run = () => void hydrate(shell);
    const idle = () => {
      if ('requestIdleCallback' in window) window.requestIdleCallback(run, {timeout:750});
      else setTimeout(run, 0);
    };
    if (document.readyState === 'complete') idle();
    else window.addEventListener('load', idle, {once:true});
  }

  function installBrandMetadata() {
    const head = document.head;
    if (!head) return;
    if (!head.querySelector('link[rel="icon"][data-monitorbox-brand]')) {
      const icon = document.createElement('link');
      icon.rel = 'icon';
      icon.type = 'image/svg+xml';
      icon.href = `/static/monitorbox-mark.svg?v=${UI_GENERATION}`;
      icon.dataset.monitorboxBrand = '1';
      head.append(icon);
    }
    if (!head.querySelector('link[rel="manifest"][data-monitorbox-brand]')) {
      const manifest = document.createElement('link');
      manifest.rel = 'manifest';
      manifest.href = `/static/monitorbox.webmanifest?v=${UI_GENERATION}`;
      manifest.dataset.monitorboxBrand = '1';
      head.append(manifest);
    }
    let theme = head.querySelector('meta[name="theme-color"]');
    if (!theme) {
      theme = document.createElement('meta');
      theme.name = 'theme-color';
      head.append(theme);
    }
    theme.content = '#07111f';
  }

  function rememberGeneration() {
    try { sessionStorage.setItem('monitorbox.ui.generation', UI_GENERATION); } catch (_) {}
  }

  function mount() {
    if (!document.body || document.getElementById('mb-app-shell')) return;
    installBrandMetadata();
    const meta = pageMeta();

    // Preserve the exact legacy Debug node so global-debug.js keeps its already-bound
    // listeners/state while the shared shell takes ownership of its presentation.
    const debugControl = document.getElementById('debug-toggle');
    if (debugControl) debugControl.remove();
    pageActionsFromLegacy();

    const shell = createShell(meta, debugControl);
    document.body.prepend(shell);
    document.body.classList.add('mb-shell-mounted');
    document.body.dataset.mbUiGeneration = UI_GENERATION;
    rememberGeneration();
    scheduleHydration(shell);
  }

  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    try {
      const active = sessionStorage.getItem('monitorbox.ui.generation');
      if (active && active !== UI_GENERATION) location.reload();
    } catch (_) {}
  });

  globalThis.MonitorBoxShell = Object.freeze({mount, pageMeta, buildLabel, siteSummary, uiGeneration:UI_GENERATION});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
})();
