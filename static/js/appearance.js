import { $, el, registeredThemes, applyUiTheme, toast } from './core.js';

const root = document.documentElement;
const reduceTransparency = matchMedia('(prefers-reduced-transparency: reduce)');
const moreContrast = matchMedia('(prefers-contrast: more)');
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
let choices, wallpaper, selection, library, surfaces = [], generation = 0;
let registryKey = '', saving = false, frame = 0, lastTime = 0;
let position = null, velocity = 0, target = 0;
let wallpaperControls, wallpaperPreview, wallpaperStatus, wallpaperInput, wallpaperChoose, wallpaperReset;
const wallpaperUrls = { apple: '/api/ui/wallpaper', rain: '/api/ui/wallpaper?theme=rain' };
let wallpaperSaving = false, wallpaperTitle, rainMistControl, rainMistInput;
let rainLibrary, rainSurface;

// Analytic critically damped spring: retarget without resetting presentation or velocity.
export function springStep(position, velocity, target, seconds) {
  const omega = 24, displacement = position - target;
  const c = velocity + omega * displacement;
  const decay = Math.exp(-omega * seconds);
  return [target + (displacement + c * seconds) * decay,
    (velocity - omega * c * seconds) * decay];
}

function stopSpring() { cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
function animateSelection(time) {
  const dt = lastTime ? Math.min((time - lastTime) / 1000, .05) : 1 / 60;
  lastTime = time;
  [position, velocity] = springStep(position, velocity, target, dt);
  selection.style.transform = `translateY(${position}px)`;
  if (Math.abs(position - target) < .05 && Math.abs(velocity) < .05) {
    position = target; selection.style.transform = `translateY(${target}px)`; stopSpring();
  } else frame = requestAnimationFrame(animateSelection);
}
function moveSelection() {
  if (!selection) return;
  const active = $('.rail-btn.active');
  if (!active) return;
  target = active.offsetTop;
  selection.style.left = active.offsetLeft + 'px';
  selection.style.width = active.offsetWidth + 'px';
  selection.style.height = active.offsetHeight + 'px';
  if (position === null || reduceMotion.matches) {
    stopSpring(); position = target; velocity = 0;
    selection.style.transform = `translateY(${target}px)`;
  } else if (!frame && position !== target) frame = requestAnimationFrame(animateSelection);
}
function destroyGlass() {
  for (const surface of surfaces) surface.destroy();
  surfaces = [];
}
async function loadWallpaper(src) {
  const image = new Image(); image.id = 'appleWallpaper'; image.alt = '';
  image.setAttribute('aria-hidden', 'true'); image.src = src;
  await image.decode();
  return image;
}
async function syncGlass() {
  const revision = ++generation;
  const apple = root.dataset.uiTheme === 'apple';
  if (root.dataset.uiTheme !== 'rain') { rainSurface?.destroy(); rainSurface = null; }
  if (!apple) {
    destroyGlass(); stopSpring(); selection?.remove(); selection = null; position = null;
    wallpaper?.remove(); wallpaper = null;
    if (root.dataset.uiTheme === 'rain') {
      try {
        const { mountRain } = await (rainLibrary ||= import('../themes/rain.js'));
        if (revision !== generation) return;
        rainSurface ||= mountRain(wallpaperUrls.rain);
        rainSurface.refresh();
      } catch (error) { console.warn('雨境已使用 CSS 材质', error); }
    }
    return;
  }
  if (!wallpaper) {
    let image;
    try { image = await loadWallpaper(wallpaperUrls.apple); }
    catch { image = await loadWallpaper('/assets/apple-architecture.png'); }
    if (revision !== generation) return;
    wallpaper = image;
    document.body.prepend(wallpaper);
  }
  if (!selection) {
    selection = el('span', 'apple-nav-selection'); selection.setAttribute('aria-hidden', 'true');
    $('.rail-nav').prepend(selection);
  }
  moveSelection();
  if (reduceTransparency.matches || moreContrast.matches) { destroyGlass(); return; }
  try {
    library ||= import('../vendor/liquid-glass/src/index.js');
    const { LiquidGlass } = await library;
    if (revision !== generation) return;
    const dark = root.dataset.theme === 'dark';
    const options = {
      backdrop: [{ color: dark ? '#101722' : '#e9edf3' },
        { source: wallpaper, anchor: 'viewport', fit: 'cover' }],
      tint: dark ? .6 : .52, tintTone: dark ? 'dark' : 'light', frost: .1,
      material: { refraction: 36, dispersion: .6, backdropBlur: 5 },
      maxDpr: 1.5, live: false, fallback: 'css', bleed: 0,
    };
    if (surfaces.length) surfaces.forEach(surface => surface.update(options));
    else {
      // Bounded contexts: chrome only; app/folder lists use CSS material.
      for (const selector of ['.rail', '.topbar', '.ops-scenes']) {
        const element = $(selector);
        if (element) {
          const drawer = $('#opsTagsDrawer');
          const opticalHeight = () => element.getBoundingClientRect().height - (drawer?.getBoundingClientRect().height || 0);
          surfaces.push(new LiquidGlass(element, { ...options, ...(selector === '.topbar' ? {
            opticalHeight,
            canvasHeight: () => Math.ceil(opticalHeight()) + (drawer?.querySelector('.ops-content').offsetHeight || 0) + 2,
          } : {}) }));
        }
      }
    }
  } catch (error) {
    destroyGlass();
    console.warn('Apple 玻璃已回退到 CSS 材质', error);
  }
}

async function saveWallpaper(file) {
  if (wallpaperSaving) return;
  const theme = root.dataset.uiTheme;
  if (!Object.hasOwn(wallpaperUrls, theme)) return;
  wallpaperSaving = true;
  wallpaperChoose.disabled = wallpaperReset.disabled = true;
  wallpaperStatus.textContent = file ? '正在更换壁纸…' : '正在恢复默认…';
  try {
    if (file) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw new Error('请选择 PNG、JPEG 或 WebP 图片');
      if (file.size > 5 * 1024 * 1024) throw new Error('图片不能超过 5 MB');
      const url = URL.createObjectURL(file);
      try { await loadWallpaper(url); }
      catch { throw new Error('图片无法读取，请选择其他图片'); }
      finally { URL.revokeObjectURL(url); }
    }
    const response = await fetch((file ? '/api/ui/wallpaper' : '/api/ui/wallpaper/reset') + '?theme=' + theme, {
      method: 'POST', headers: { 'Content-Type': file ? file.type : 'application/json' },
      body: file || '{}',
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '壁纸保存失败');
    const url = '/api/ui/wallpaper?theme=' + theme + '&v=' + Date.now();
    wallpaperUrls[theme] = url;
    if (root.dataset.uiTheme === theme) {
      if (theme === 'rain') await rainSurface?.setWallpaper(url);
      else {
        const image = await loadWallpaper(url);
        if (root.dataset.uiTheme === theme && wallpaper) { wallpaper.replaceWith(image); wallpaper = image; }
      }
      await syncGlass();
      renderAppearance();
    }
    wallpaperStatus.textContent = file ? '壁纸已更换' : '已恢复默认壁纸';
    toast((theme === 'rain' ? '雨境：' : 'Apple：') + wallpaperStatus.textContent);
  } catch (error) { wallpaperStatus.textContent = error.message; toast(error.message); }
  finally {
    wallpaperSaving = false; wallpaperInput.value = '';
    wallpaperChoose.disabled = wallpaperReset.disabled = false;
  }
}

export function renderAppearance() {
  if (!choices) return;
  const theme = root.dataset.uiTheme;
  wallpaperControls.hidden = !Object.hasOwn(wallpaperUrls, theme);
  if (!wallpaperControls.hidden) {
    const name = theme === 'rain' ? '雨境' : 'Apple';
    wallpaperTitle.textContent = name + '壁纸';
    wallpaperPreview.alt = '当前' + name + '壁纸';
    if (wallpaperPreview.getAttribute('src') !== wallpaperUrls[theme]) wallpaperPreview.src = wallpaperUrls[theme];
  }
  rainMistControl.hidden = theme !== 'rain';
  const themes = registeredThemes();
  const key = JSON.stringify(themes.map(({ id, name, desc, preview }) => [id, name, desc, preview]));
  if (key !== registryKey) {
    registryKey = key;
    choices.replaceChildren(...themes.map(theme => {
      const button = el('button', 'theme-choice'); button.type = 'button';
      button.dataset.themeId = theme.id;
      button.setAttribute('aria-label', theme.name + '：' + theme.desc);
      const sample = el('span', 'theme-preview'); sample.setAttribute('aria-hidden', 'true');
      if (theme.preview) {
        const image = el('img'); image.src = theme.preview; image.alt = ''; sample.append(image);
        sample.classList.add('theme-preview-image');
      } else for (let i = 0; i < 6; i++) sample.append(el('i'));
      const name = el('strong'); name.textContent = theme.name;
      const desc = el('small'); desc.textContent = theme.desc;
      button.append(sample, name, desc);
      return button;
    }));
  }
  for (const button of choices.children) {
    button.setAttribute('aria-pressed', String(button.dataset.themeId === root.dataset.uiTheme));
    button.disabled = saving;
  }
}
export function initAppearance() {
  choices = el('div', 'theme-choices'); choices.setAttribute('role', 'group');
  choices.setAttribute('aria-label', '皮肤主题');
  $('#settingsAppearance h3').after(choices);
  wallpaperControls = el('div', 'wallpaper-settings');
  wallpaperPreview = el('img', 'wallpaper-preview'); wallpaperPreview.alt = '当前 Apple 壁纸';
  wallpaperPreview.src = wallpaperUrls.apple;
  const wallpaperDetails = el('div');
  wallpaperTitle = el('strong'); wallpaperTitle.textContent = 'Apple 壁纸';
  const wallpaperHint = el('p'); wallpaperHint.textContent = 'PNG / JPEG / WebP，最大 5 MB。保存在本机，自动铺满背景。';
  const wallpaperActions = el('div', 'wallpaper-actions');
  wallpaperChoose = el('button', 'btn'); wallpaperChoose.type = 'button'; wallpaperChoose.textContent = '更换壁纸';
  wallpaperReset = el('button', 'btn'); wallpaperReset.type = 'button'; wallpaperReset.textContent = '恢复默认壁纸';
  wallpaperInput = el('input'); wallpaperInput.type = 'file'; wallpaperInput.hidden = true;
  wallpaperInput.accept = 'image/png,image/jpeg,image/webp';
  wallpaperStatus = el('p'); wallpaperStatus.setAttribute('role', 'status');
  rainMistControl = el('label', 'rain-mist-control');
  rainMistInput = el('input'); rainMistInput.type = 'checkbox';
  rainMistInput.checked = localStorage.getItem('console-rain-mist') !== 'off';
  root.dataset.rainMist = rainMistInput.checked ? 'on' : 'off';
  rainMistControl.append(rainMistInput, document.createTextNode('背景水汽'));
  rainMistInput.addEventListener('change', () => {
    root.dataset.rainMist = rainMistInput.checked ? 'on' : 'off';
    localStorage.setItem('console-rain-mist', root.dataset.rainMist);
    rainSurface?.refresh();
  });
  wallpaperActions.append(wallpaperChoose, wallpaperReset, wallpaperInput);
  wallpaperDetails.append(wallpaperTitle, wallpaperHint, wallpaperActions, rainMistControl, wallpaperStatus);
  wallpaperControls.append(wallpaperPreview, wallpaperDetails); choices.after(wallpaperControls);
  wallpaperChoose.addEventListener('click', () => wallpaperInput.click());
  wallpaperInput.addEventListener('change', () => { if (wallpaperInput.files[0]) saveWallpaper(wallpaperInput.files[0]); });
  wallpaperReset.addEventListener('click', () => saveWallpaper(null));
  choices.addEventListener('click', async event => {
    const button = event.target.closest('.theme-choice');
    if (!button || saving || button.dataset.themeId === root.dataset.uiTheme) return;
    saving = true; choices.setAttribute('aria-busy', 'true'); renderAppearance();
    try {
      if (await applyUiTheme(button.dataset.themeId, true)) toast('已切换为' + button.querySelector('strong').textContent + '主题');
    } finally { saving = false; choices.removeAttribute('aria-busy'); renderAppearance(); }
  });
  new MutationObserver(records => {
    if (records.some(record => record.attributeName !== 'data-view')) { syncGlass(); renderAppearance(); }
    else moveSelection();
  }).observe(root, { attributes: true, attributeFilter: ['data-ui-theme', 'data-theme', 'data-view'] });
  new ResizeObserver(moveSelection).observe($('.rail-nav'));
  for (const preference of [reduceTransparency, moreContrast]) preference.addEventListener('change', syncGlass);
  reduceMotion.addEventListener('change', () => { moveSelection(); syncGlass(); });
  window.addEventListener('pagehide', () => { ++generation; destroyGlass(); stopSpring(); rainSurface?.destroy(); rainSurface = null; });
  window.addEventListener('pageshow', syncGlass);
  syncGlass();
}
