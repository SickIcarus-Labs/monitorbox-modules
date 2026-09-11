  function pageActionsFromLegacy() {
    const legacy = findLegacyTopbar();
    if (!legacy) {
      document.getElementById('v22-menu')?.remove();
      document.getElementById('settingsV22Menu')?.remove();
      return null;
    }

    const actionStrip = make('div', 'mb-page-actions');
    actionStrip.setAttribute('aria-label', 'Page actions');

    const dashboardActionIds = ['reload', 'debug-toggle', 'v22-discoveries', 'check-all'];
    for (const id of dashboardActionIds) {
      const node = legacy.querySelector(`#${id}`);
      if (node) actionStrip.append(node);
    }

    // The shared application shell owns global navigation, product identity, Home/Up,
    // runtime identity, and site identity. Older settings shell nodes must be consumed,
    // never reclassified as page-local actions.
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
