'use strict';

(() => {
  const SECTION_ATTR = 'data-contextual-configuration';
  const RESOURCE_ATTR = 'data-contextual-resource-id';
  let requestSerial = 0;
  let queued = false;

  function selectedResourceId() {
    const hash = String(location.hash || '').replace(/^#/, '');
    if (!hash) return '';
    const separator = hash.indexOf('/');
    if (separator < 0 || separator === hash.length - 1) return '';
    try {
      return decodeURIComponent(hash.slice(separator + 1));
    } catch (_) {
      return '';
    }
  }

  function validTarget(target) {
    return target &&
      typeof target === 'object' &&
      typeof target.label === 'string' && target.label &&
      typeof target.href === 'string' &&
      target.href.startsWith('/settings/configuration/editor?ref=');
  }

  function action(target, prefix, primary = false) {
    if (!validTarget(target)) return null;
    const link = document.createElement('a');
    link.className = `button ${primary ? '' : 'secondary'} contextual-config-link`.trim();
    link.href = target.href;
    link.textContent = `${prefix}${target.label}`;
    return link;
  }

  function group(label, targets, prefix) {
    const valid = Array.isArray(targets) ? targets.filter(validTarget) : [];
    if (!valid.length) return null;
    const group = document.createElement('div');
    group.className = 'contextual-config-group';
    const heading = document.createElement('span');
    heading.className = 'component-meta contextual-config-group-label';
    heading.textContent = label;
    const actions = document.createElement('div');
    actions.className = 'action-list contextual-config-actions';
    for (const target of valid) {
      const link = action(target, prefix);
      if (link) actions.append(link);
    }
    group.append(heading, actions);
    return group;
  }

  function placeSection(root, resourceId, payload) {
    if (selectedResourceId() !== resourceId || !validTarget(payload?.resource)) return;
    const existing = root.querySelector(`[${SECTION_ATTR}]`);
    if (existing) existing.remove();

    const section = document.createElement('section');
    section.className = 'detail-section contextual-configuration';
    section.setAttribute(SECTION_ATTR, 'true');
    section.setAttribute(RESOURCE_ATTR, resourceId);

    const heading = document.createElement('h3');
    heading.textContent = 'Configuration';
    const copy = document.createElement('p');
    copy.className = 'component-meta contextual-config-copy';
    copy.textContent = 'Edit this item or an explicitly related configuration object.';
    const actions = document.createElement('div');
    actions.className = 'action-list contextual-config-actions';
    const resourceAction = action(payload.resource, 'Configure ', true);
    if (resourceAction) actions.append(resourceAction);
    section.append(heading, copy, actions);

    const connections = group('Connections', payload.connections, 'Configure Connection · ');
    if (connections) section.append(connections);
    const systems = group('Hosting / dependency Systems', payload.systems, 'Configure System · ');
    if (systems) section.append(systems);

    const history = [...root.querySelectorAll(':scope > .detail-section')]
      .find(node => node.querySelector(':scope > h3')?.textContent === 'History');
    root.insertBefore(section, history || null);
  }

  async function refreshContext() {
    const root = document.querySelector('#drawer-body');
    const resourceId = selectedResourceId();
    if (!root || !resourceId) return;
    const existing = root.querySelector(`[${SECTION_ATTR}]`);
    if (existing?.getAttribute(RESOURCE_ATTR) === resourceId) return;

    const serial = ++requestSerial;
    try {
      const response = await fetch(
        `/api/v2/config/context?resource_id=${encodeURIComponent(resourceId)}`,
        {headers: {Accept: 'application/json'}, cache: 'no-store'}
      );
      if (serial !== requestSerial || response.status === 404) return;
      if (!response.ok) return;
      const payload = await response.json();
      if (serial !== requestSerial) return;
      placeSection(root, resourceId, payload);
    } catch (_) {
      // Contextual configuration is progressive enhancement. Operational detail
      // remains fully usable when the configuration seam is unavailable.
    }
  }

  function queueRefresh() {
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      refreshContext();
    });
  }

  function install() {
    const root = document.querySelector('#drawer-body');
    if (!root) return;
    new MutationObserver(queueRefresh).observe(root, {childList: true});
    window.addEventListener('hashchange', queueRefresh);
    queueRefresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, {once: true});
  } else {
    install();
  }
})();
