import { LiquidGlass } from '../vendor/liquid-glass/src/index.js';

const selector = '.topbar-inner, .rail-btn.active, .ops-scenes, .app-card[data-key], .folder-card, .center-section, .ov, .file-filters, .file-table-panel, #view-services .tbl, .widget';

// Preload nearby surfaces; the renderer batches them into passes on one canvas.
export function visibleRainTargets(nodes, width, height) {
  return [...nodes].filter(node => {
    const r = node.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.bottom > -160 && r.right > 0 && r.top < height + 160 && r.left < width;
  });
}

export function mountRain(wallpaperUrl = '/api/ui/wallpaper?theme=rain') {
  const root = document.documentElement;
  const transparency = matchMedia('(prefers-reduced-transparency: reduce)');
  const contrast = matchMedia('(prefers-contrast: more), (forced-colors: active)');
  let image = new Image(); image.id = 'rainWallpaper'; image.alt = '';
  image.setAttribute('aria-hidden', 'true'); image.src = wallpaperUrl;
  const mist = document.createElement('div'); mist.id = 'rainMist'; mist.setAttribute('aria-hidden', 'true');
  const host = document.createElement('div'); host.id = 'rainGlass'; host.setAttribute('aria-hidden', 'true');
  const drops = document.createElement('div'); drops.id = 'rainDrops'; drops.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < 12; i++) {
    const drop = document.createElement('i');
    drop.style.setProperty('--drop-x', ((i * 37 + 13) % 100) + '%');
    drop.style.setProperty('--drop-delay', (-i * 3.7) + 's');
    drop.style.setProperty('--drop-duration', (19 + i % 5 * 4) + 's');
    drops.append(drop);
  }
  document.body.prepend(image, mist, drops, host);
  const destroyMotion = mountRainMotion();
  let stopped = false, surface = null, targets = [], scheduled = 0, appearanceKey = '';
  const topbar = document.querySelector('.topbar-inner'), drawer = document.querySelector('#opsTagsDrawer');
  const opticalHeight = () => topbar.getBoundingClientRect().height - (drawer?.getBoundingClientRect().height || 0);
  const number = (style, name) => parseFloat(style.getPropertyValue('--rain-' + name));

  function clearSurface() {
    surface?.destroy(); surface = null;
    targets.forEach(node => node.removeAttribute('data-rain-surface')); targets = [];
  }
  function refresh() {
    if (stopped) return;
    if (transparency.matches || contrast.matches) { clearSurface(); return; }
    if (!image.complete || !image.naturalWidth) return;
    const next = visibleRainTargets(document.querySelectorAll(selector), innerWidth, innerHeight);
    // An empty target list means "render the host" to LiquidGlass; our host fills the viewport.
    if (!next.length) { clearSurface(); return; }
    const style = getComputedStyle(root);
    const mistOn = root.dataset.rainMist !== 'off';
    const shortSides = next.map(node => Math.min(node.offsetWidth, node === topbar ? opticalHeight() : node.offsetHeight));
    // Bound the sampling distance in pixels even for a full-height log panel.
    const edgeReach = Math.min(.14, 24 / Math.max(1, ...shortSides));
    const key = [image.src, mistOn, root.dataset.theme, edgeReach].join('|');
    if (surface && key === appearanceKey && next.length === targets.length && next.every((node, i) => node === targets[i])) {
      return; // The renderer already tracks scrolling and element geometry.
    }
    const options = {
      // The connected image already supplies its CSS opacity to the backdrop painter.
      backdrop: [{ color: '#0b2029' }, { source: image, anchor: 'viewport', fit: 'cover' },
        { color: mistOn ? 'rgba(164, 194, 204, .12)' : 'transparent' }],
      targets: next.map((element, i) => {
        const panel = element.matches('.center-section, .ov, .file-filters, .file-table-panel, .tbl, .widget');
        const shortSide = () => Math.max(1, Math.min(element.offsetWidth, element.offsetHeight));
        return { element, frost: Math.min(number(style, 'frost'), 3 / Math.max(1, shortSides[i])),
          ...(element === topbar ? { opticalHeight } : {}),
          // Keep utility-panel rims thin as their content or viewport grows.
          ...(panel ? { refraction: number(style, 'panel-refraction'),
            edgeReach: () => Math.min(edgeReach, number(style, 'panel-capture') / shortSide()),
            edgeWidth: () => Math.min(.18, 2 * number(style, 'panel-edge') / shortSide()) } : {}) };
      }),
      tint: number(style, 'tint'), tintTone: 'dark',
      material: { refraction: number(style, 'refraction'), dispersion: .8, backdropBlur: mistOn ? 4 : 1.5,
        edgeReach, edgeWidth: .18, echo: .06, rim: .45, reflection: .3, highlight: .4, lightAngle: 125 },
      maxDpr: 1.25, live: false, bleed: 0, fallback: 'none',
      onRender(current) {
        targets.forEach(node => node.setAttribute('data-rain-surface', current.mode));
      },
    };
    targets.filter(node => !next.includes(node)).forEach(node => node.removeAttribute('data-rain-surface'));
    targets = next;
    try {
      if (surface) surface.update(key === appearanceKey ? { targets: options.targets } : options);
      else surface = new LiquidGlass(host, options);
      appearanceKey = key;
    } catch (error) { clearSurface(); console.warn('雨境玻璃已回退到 CSS 材质', error); }
  }
  function queueRefresh() {
    if (!stopped && !scheduled) scheduled = requestAnimationFrame(() => { scheduled = 0; refresh(); });
  }
  const observer = new MutationObserver(records => {
    // Filters reuse cards by changing class/hidden. Resolve visibility in this
    // mutation batch so the glass loop draws the new targets on the next paint.
    if (records.some(r => r.type === 'attributes'
      || [...r.addedNodes, ...r.removedNodes].some(n => n.nodeType === 1))) refresh();
  });
  observer.observe(document.querySelector('.main'), {
    childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden'],
  });
  const viewObserver = new MutationObserver(queueRefresh);
  viewObserver.observe(root, { attributes: true, attributeFilter: ['data-view', 'data-card-size'] });
  window.addEventListener('scroll', refresh, { capture: true, passive: true });
  window.addEventListener('resize', queueRefresh, { passive: true });
  contrast.addEventListener('change', queueRefresh);
  const visibility = () => {
    drops.hidden = document.hidden;
    if (!document.hidden) queueRefresh();
  };
  document.addEventListener('visibilitychange', visibility);
  image.decode().then(queueRefresh).catch(error => console.warn('雨景壁纸读取失败', error));
  return {
    refresh: queueRefresh,
    async setWallpaper(src) {
      const next = new Image(); next.id = 'rainWallpaper'; next.alt = '';
      next.setAttribute('aria-hidden', 'true'); next.src = src;
      await next.decode();
      if (stopped) return;
      image.replaceWith(next); image = next; queueRefresh();
    },
    destroy() {
      stopped = true; cancelAnimationFrame(scheduled);
      destroyMotion();
      observer.disconnect(); viewObserver.disconnect();
      window.removeEventListener('scroll', refresh, true);
      window.removeEventListener('resize', queueRefresh);
      contrast.removeEventListener('change', queueRefresh);
      document.removeEventListener('visibilitychange', visibility);
      clearSurface(); image.remove(); mist.remove(); drops.remove(); host.remove();
    },
  };
}

// One delegated tooltip for Rain; keep existing titles and richer popovers intact.
function mountRainMotion() {
  const root = document.documentElement;
  const tip = document.createElement('div');
  tip.id = 'rainTooltip'; tip.setAttribute('popover', 'manual'); tip.setAttribute('role', 'tooltip');
  document.body.prepend(tip);
  const pointer = matchMedia('(hover: hover) and (pointer: fine)');
  const originPanels = new Set();
  let anchor = null, title = '', label = false, showTimer = 0, hideTimer = 0, warmUntil = 0, titleObserver;
  root.dataset.rainInput = 'pointer';
  const cancel = () => { if (showTimer) clearTimeout(showTimer); if (hideTimer) clearTimeout(hideTimer); showTimer = hideTimer = 0; };
  function hide() {
    cancel(); titleObserver?.disconnect();
    if (tip.isConnected && tip.matches(':popover-open')) { tip.hidePopover(); warmUntil = performance.now() + 500; }
    if (anchor) {
      if (anchor.getAttribute('title') === '') anchor.setAttribute('title', title);
      const ids = (anchor.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== tip.id);
      if (ids.length) anchor.setAttribute('aria-describedby', ids.join(' '));
      else anchor.removeAttribute('aria-describedby');
      if (label && anchor.getAttribute('aria-label') === title) anchor.removeAttribute('aria-label');
    }
    anchor = null;
  }
  function show() {
    showTimer = 0;
    if (!anchor?.isConnected || !anchor.getClientRects().length || anchor.closest('[inert]')) { hide(); return; }
    tip.textContent = title;
    const instant = root.dataset.rainInput === 'keyboard' || performance.now() < warmUntil;
    tip.dataset.instant = String(instant);
    tip.showPopover();
    const r = anchor.getBoundingClientRect(), gap = 8;
    const below = r.top < tip.offsetHeight + gap + 8;
    const left = Math.max(8, Math.min(r.left + (r.width - tip.offsetWidth) / 2, innerWidth - tip.offsetWidth - 8));
    const top = Math.max(8, Math.min(below ? r.bottom + gap : r.top - tip.offsetHeight - gap, innerHeight - tip.offsetHeight - 8));
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
    tip.style.transformOrigin = `${Math.max(8, Math.min(r.left + r.width / 2 - left, tip.offsetWidth - 8))}px ${below ? 'top' : 'bottom'}`;
    tip.dataset.side = below ? 'bottom' : 'top';
  }
  function enter(event) {
    if (event.type === 'pointerover' && (!pointer.matches || event.pointerType === 'touch')) return;
    if (event.type === 'focusin' && root.dataset.rainInput !== 'keyboard') return;
    if (tip.contains(event.target)) { cancel(); return; }
    const next = event.target.closest('button, a, summary, [role="button"]');
    if (next && next === anchor) {
      if (hideTimer) clearTimeout(hideTimer); hideTimer = 0;
      if (!showTimer && !tip.matches(':popover-open')) showTimer = setTimeout(show, 350);
      return;
    }
    hide();
    // Resource and preset buttons already own a hover panel; do not cover it.
    if (!next || next.closest('[inert]') || next.hasAttribute('aria-haspopup') || next.hasAttribute('aria-describedby')) return;
    const text = next.getAttribute('title')?.trim();
    if (!text) return;
    anchor = next; title = text;
    label = !next.getAttribute('aria-label') && !next.textContent.trim();
    if (label) next.setAttribute('aria-label', title);
    next.setAttribute('aria-describedby', tip.id); next.setAttribute('title', '');
    titleObserver = new MutationObserver(() => {
      const updated = anchor?.getAttribute('title');
      if (updated) { title = updated; tip.textContent = title; if (label) anchor.setAttribute('aria-label', title); anchor.setAttribute('title', ''); }
    });
    titleObserver.observe(next, { attributes: true, attributeFilter: ['title'] });
    if (event.type === 'focusin' || performance.now() < warmUntil) show();
    else showTimer = setTimeout(show, 350);
  }
  function leave(event) {
    if (!anchor || anchor.contains(event.relatedTarget) || tip.contains(event.relatedTarget)) return;
    cancel(); hideTimer = setTimeout(hide, 100);
  }
  function press() { root.dataset.rainInput = 'pointer'; hide(); }
  function key(event) {
    root.dataset.rainInput = 'keyboard';
    if (event.key === 'Escape') hide();
  }
  function move(event) { if (event.pointerType !== 'touch' && root.dataset.rainInput !== 'pointer') root.dataset.rainInput = 'pointer'; }
  function placeOrigin(event) {
    const panel = event.target;
    if (event.newState !== 'open' || !panel.matches('.ops-preset-popover, .ops-resource-popover')) return;
    const id = CSS.escape(panel.id);
    const trigger = document.querySelector(`[aria-controls="${id}"][aria-expanded="true"], [aria-describedby="${id}"]:is(:hover, :focus-visible)`);
    if (!trigger) return;
    const r = trigger.getBoundingClientRect(), p = panel.getBoundingClientRect();
    const above = p.top < r.top;
    panel.dataset.rainSide = above ? 'top' : 'bottom';
    originPanels.add(panel);
    panel.style.transformOrigin = `${Math.max(8, Math.min(r.left + r.width / 2 - p.left, panel.offsetWidth - 8))}px ${above ? 'bottom' : 'top'}`;
  }
  const events = { pointerover: enter, pointerout: leave, focusin: enter, focusout: leave, pointerdown: press, pointermove: move, keydown: key, scroll: hide, toggle: placeOrigin };
  for (const [name, handler] of Object.entries(events)) document.addEventListener(name, handler, true);
  window.addEventListener('resize', hide);
  return () => {
    hide(); tip.remove(); delete root.dataset.rainInput;
    originPanels.forEach(panel => { delete panel.dataset.rainSide; panel.style.transformOrigin = ''; });
    for (const [name, handler] of Object.entries(events)) document.removeEventListener(name, handler, true);
    window.removeEventListener('resize', hide);
  };
}
