'use strict';

(() => {
  const MARKER = 'mb-configuration-peer-nav';
  const PEERS = Object.freeze([
    ['configuration', 'Configuration', '/settings'],
    ['appliance', 'Appliance', '/settings/appliance'],
    ['quick-add', 'Quick Add', '/settings/quick-add'],
    ['monitoring', 'Monitoring', '/settings/discover'],
    ['policies', 'Policies', '/settings/configuration/policies'],
    ['dashboard', 'Dashboard', '/settings/dashboard'],
    ['recovery', 'Recovery', '/settings/recovery'],
  ]);

  const LEGACY_APPLIANCE_LINKS = new Set([
    '/settings/quick-add',
    '/settings',
    '/settings/policy',
    '/settings/dashboard',
    '/settings/recovery',
  ]);

  function activePeer(pathname) {
    if (pathname === '/settings') return 'configuration';
    if (pathname.startsWith('/settings/appliance')) return 'appliance';
    if (pathname.startsWith('/settings/quick-add')) return 'quick-add';
    if (pathname.startsWith('/settings/discover')) return 'monitoring';
    if (
      pathname.startsWith('/settings/configuration/policies') ||
      pathname.startsWith('/settings/policy')
    ) return 'policies';
    if (pathname.startsWith('/settings/dashboard')) return 'dashboard';
    if (pathname.startsWith('/settings/recovery')) return 'recovery';
    return 'configuration';
  }

  function stripLegacyAppliancePeers() {
    if (!location.pathname.startsWith('/settings/appliance')) return;
    const headers = [...document.querySelectorAll('header.top')];
    for (const header of headers) {
      for (const link of [...header.querySelectorAll('a[href]')]) {
        const href = link.getAttribute('href');
        if (LEGACY_APPLIANCE_LINKS.has(href)) link.remove();
      }
    }
  }

  function buildNav() {
    const nav = document.createElement('nav');
    nav.id = MARKER;
    nav.className = 'mb-configuration-peer-nav';
    nav.setAttribute('aria-label', 'Configuration sections');

    const active = activePeer(location.pathname);
    for (const [key, label, href] of PEERS) {
      const link = document.createElement('a');
      link.className = 'mb-configuration-peer-link';
      link.href = href;
      link.textContent = label;
      if (key === active) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
      nav.append(link);
    }
    return nav;
  }

  function install() {
    if (!location.pathname.startsWith('/settings')) return true;
    stripLegacyAppliancePeers();

    if (document.getElementById(MARKER)) return true;

    const nav = buildNav();
    const shell = document.getElementById('mb-app-shell');
    if (shell?.parentNode) {
      shell.insertAdjacentElement('afterend', nav);
      return true;
    }

    const firstHeader = document.querySelector('header');
    if (firstHeader?.parentNode) {
      firstHeader.insertAdjacentElement('afterend', nav);
      return true;
    }

    if (document.body) {
      document.body.prepend(nav);
      return true;
    }
    return false;
  }

  function boot() {
    if (install()) return;
    const observer = new MutationObserver(() => {
      if (!install()) return;
      observer.disconnect();
    });
    observer.observe(document.documentElement, {childList: true, subtree: true});
  }

  globalThis.MonitorBoxConfigurationPeerNavigation = Object.freeze({
    install,
    peers: PEERS,
    activePeer,
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, {once: true});
  } else {
    boot();
  }
})();
