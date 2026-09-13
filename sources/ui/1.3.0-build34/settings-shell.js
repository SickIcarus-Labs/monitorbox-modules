'use strict';

(() => {
  const SETTINGS_LINKS = Object.freeze([
    ['/settings', 'Configuration'],
    ['/modules', 'Modules'],
    ['/settings/recovery', 'Backup & Restore'],
  ]);

  function make(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function closeSettings(shell) {
    const button = shell.querySelector('#mb-shell-settings');
    const menu = shell.querySelector('#mb-settings-menu');
    if (!button || !menu) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
  }

  function install() {
    const shell = document.getElementById('mb-app-shell');
    if (!shell) return false;
    if (shell.dataset.settingsNavigation === '1') return true;

    // #316 replaces only #289's hamburger/global-nav affordance. Home, hierarchy,
    // runtime/site state, and the adopted Debug control stay under the same shell.
    shell.querySelector('.mb-shell-menu')?.remove();
    shell.querySelector('#mb-shell-nav')?.remove();

    const home = shell.querySelector('.mb-shell-home');
    if (home) shell.prepend(home);

    const debug = shell.querySelector('#debug-toggle');
    if (debug) {
      debug.className = 'mb-shell-debug';
      debug.textContent = 'Debug';
      debug.title = 'Debug';
      debug.setAttribute('aria-label', 'Debug');
    }

    const wrap = make('div', 'mb-shell-settings-wrap');
    const button = make('button', 'mb-shell-settings');
    button.id = 'mb-shell-settings';
    button.type = 'button';
    button.title = 'Settings';
    button.setAttribute('aria-label', 'Settings');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'mb-settings-menu');

    const menu = make('nav', 'mb-settings-menu');
    menu.id = 'mb-settings-menu';
    menu.hidden = true;
    menu.setAttribute('aria-label', 'Settings');
    for (const [href, label] of SETTINGS_LINKS) {
      const link = make('a', 'mb-settings-link', label);
      link.href = href;
      if (location.pathname === href || (href === '/settings' && location.pathname === '/settings')) {
        link.setAttribute('aria-current', 'page');
      }
      menu.append(link);
    }

    button.addEventListener('click', event => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      button.setAttribute('aria-expanded', String(!menu.hidden));
    });
    menu.addEventListener('click', event => event.stopPropagation());
    document.addEventListener('click', () => closeSettings(shell));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') closeSettings(shell);
    });

    wrap.append(button, menu);
    shell.append(wrap);
    shell.classList.add('mb-settings-shell');
    shell.dataset.settingsNavigation = '1';
    return true;
  }

  function boot() {
    if (install()) return;
    const observer = new MutationObserver(() => {
      if (!install()) return;
      observer.disconnect();
    });
    observer.observe(document.documentElement, {childList: true, subtree: true});
  }

  globalThis.MonitorBoxSettingsShell = Object.freeze({install, links: SETTINGS_LINKS});
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, {once: true});
  } else {
    boot();
  }
})();
