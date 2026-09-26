import { el } from './core.js';

// Keep the original tag buttons: resizing never creates a second filter state.
export function initTagDrawer(host, select) {
  const strip = el('div', 'ops-tags-visible');
  const more = el('button', 'btn ops-tags-more'); more.type = 'button'; more.hidden = true;
  more.setAttribute('aria-expanded', 'false'); more.setAttribute('aria-controls', 'opsTagsDrawer');
  const count = el('span', 'ops-tags-count'); count.setAttribute('aria-hidden', 'true');
  more.append('更多', count); host.append(strip, more);

  const topbar = host.closest('.topbar-inner'), row = el('div', 'ops-topbar-row');
  row.append(...topbar.childNodes); topbar.append(row);
  const drawer = el('section', 'ops-tags-drawer'); drawer.id = 'opsTagsDrawer';
  drawer.inert = true; drawer.setAttribute('aria-hidden', 'true'); drawer.setAttribute('aria-label', '更多标签');
  const closeButton = el('button', 'btn ops-tags-close');
  closeButton.type = 'button'; closeButton.textContent = '关闭'; closeButton.setAttribute('aria-label', '关闭标签抽屉');
  const reveal = el('div', 'ops-tags-reveal'), body = el('div', 'ops-content'), overflow = el('div', 'ops-tags-overflow');
  overflow.setAttribute('role', 'group'); overflow.setAttribute('aria-label', '更多筛选标签');
  body.append(overflow, closeButton); reveal.append(body); drawer.append(reveal); topbar.append(drawer);

  let buttons = [], signature = '', selected = '', frame = 0;
  const isOpen = () => drawer.classList.contains('open');
  function close(event) {
    if (event) drawer.dataset.instant = String(event.type === 'keydown' || event.detail === 0);
    if (drawer.contains(document.activeElement)) more.focus({ preventScroll: true });
    drawer.classList.remove('open'); drawer.inert = true; drawer.setAttribute('aria-hidden', 'true');
    more.setAttribute('aria-expanded', 'false');
  }
  more.addEventListener('click', event => {
    if (isOpen()) { close(event); return; }
    drawer.dataset.instant = String(event.detail === 0);
    drawer.inert = false; drawer.setAttribute('aria-hidden', 'false'); drawer.classList.add('open');
    more.setAttribute('aria-expanded', 'true');
    if (event.detail === 0) (overflow.querySelector('[aria-pressed="true"]') || overflow.firstElementChild || closeButton).focus({ preventScroll: true });
  });
  closeButton.addEventListener('click', close);
  document.addEventListener('click', event => { if (isOpen() && !topbar.contains(event.target)) close(event); });
  topbar.addEventListener('keydown', event => {
    if (event.key === 'Escape' && isOpen()) { event.preventDefault(); event.stopPropagation(); close(event); }
  });

  function syncSelection() {
    for (const b of buttons) b.setAttribute('aria-pressed', String(b.dataset.category === selected));
    const hiddenSelected = [...overflow.children].some(b => b.dataset.category === selected);
    more.classList.toggle('has-selection', hiddenSelected);
    more.setAttribute('aria-label', `更多标签，${overflow.children.length} 个${hiddenSelected ? '，当前：' + selected : ''}`);
  }
  function layout() {
    frame = 0;
    if (!host.clientWidth) { if (isOpen()) close(); return; }
    body.style.maxHeight = `calc(100dvh - ${row.getBoundingClientRect().bottom}px - 12px)`;
    const focused = document.activeElement;
    strip.append(...buttons); more.hidden = false;
    count.textContent = String(buttons.length);
    const gap = parseFloat(getComputedStyle(strip).columnGap) || 0;
    const style = getComputedStyle(strip);
    const inset = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
    const widths = buttons.map(b => b.getBoundingClientRect().width);
    const total = widths.reduce((sum, width) => sum + width, 0) + Math.max(0, buttons.length - 1) * gap;
    let limit = host.clientWidth - inset;
    if (total > limit) limit -= more.getBoundingClientRect().width + (parseFloat(getComputedStyle(host).columnGap) || 0);
    let used = 0, visible = 0;
    for (const width of widths) {
      const next = used + (visible ? gap : 0) + width;
      if (next > limit) break;
      used = next; visible++;
    }
    overflow.append(...buttons.slice(visible));
    count.textContent = String(buttons.length - visible); more.hidden = visible === buttons.length;
    syncSelection();
    if (isOpen()) {
      if (more.hidden) { close(); buttons.find(b => b.dataset.category === selected)?.focus({ preventScroll: true }); }
      else if (buttons.includes(focused)) focused.focus({ preventScroll: true });
    } else if (buttons.includes(focused)) {
      (strip.contains(focused) ? focused : more).focus({ preventScroll: true });
    }
  }
  function queueLayout() { if (!frame) frame = requestAnimationFrame(layout); }
  const observer = new ResizeObserver(queueLayout);
  observer.observe(host); observer.observe(row);
  new MutationObserver(queueLayout).observe(document.documentElement, { attributes: true, attributeFilter: ['data-ui-theme', 'data-theme', 'data-view'] });
  document.querySelector('#themeCss').addEventListener('load', queueLayout);
  document.fonts.ready.then(queueLayout);
  return {
    render(categories, value) {
      selected = value;
      const next = JSON.stringify(categories);
      if (next !== signature) {
        signature = next; buttons.forEach(b => b.remove());
        buttons = ['', ...categories].map(name => {
          const b = el('button', 'btn ops-tag'); b.type = 'button'; b.dataset.category = name; b.textContent = name || '全部';
          b.addEventListener('click', event => { close(event); select(name); });
          return b;
        });
        layout();
      } else syncSelection();
    },
  };
}
