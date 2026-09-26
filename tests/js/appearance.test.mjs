import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/appearance.js', import.meta.url), 'utf8');
test('navigation spring preserves velocity on reversal and settles at every frame rate', () => {
  const context = vm.createContext({});
  vm.runInContext(source.slice(source.indexOf('export function springStep'), source.indexOf('function stopSpring')).replace('export ', ''), context);
  const step = context.springStep;
  for (const fps of [30, 60, 144]) {
    let p = 0, v = 0;
    for (let i = 0; i < fps; i++) [p, v] = step(p, v, 200, 1 / fps);
    assert.ok(Math.abs(p - 200) < .001);
    assert.ok(Math.abs(v) < .001);
  }
  const [p, v] = step(0, 0, 200, .08);
  assert.ok(v > 0);
  const [reversed, velocity] = step(p, v, 0, .001);
  assert.ok(reversed > p, 'reversal retains existing momentum rather than teleporting');
  assert.ok(velocity < v, 'spring immediately decelerates toward the new target');
  const once = step(p, v, 0, .1), half = step(...step(p, v, 0, .05), 0, .05);
  assert.ok(Math.abs(once[0] - half[0]) < 1e-8);
});

test('glass lifecycle stays bounded, updates tone, respects accessibility and cancels a stale import', async () => {
  const root = { dataset: { uiTheme: 'apple', theme: 'light' } };
  const preferences = new Map();
  let created = 0, destroyed = 0, updated = 0, glassOptions;
  const node = () => ({ style: {}, setAttribute() {}, remove() {}, prepend() {}, async decode() {} });
  const nodes = Object.fromEntries(['.rail', '.topbar', '.ops-scenes', '.rail-nav'].map(s => [s, node()]));
  nodes['.rail-btn.active'] = { offsetTop: 20, offsetLeft: 10, offsetWidth: 100, offsetHeight: 50 };
  class Glass {
    constructor(host, options) { created++; glassOptions = options; }
    update(options) { updated++; glassOptions = options; }
    destroy() { destroyed++; }
  }
  const context = vm.createContext({ document: { documentElement: root, body: node() },
    matchMedia: query => { const pref = { matches: false }; preferences.set(query, pref); return pref; },
    $: s => nodes[s], el: node, Image: function () { return node(); },
    cancelAnimationFrame() {}, requestAnimationFrame() { return 1; }, console, Glass });
  vm.runInContext(source.replace(/^import .*;\n/, '').replaceAll('export function', 'function') + '\nthis.sync = syncGlass;', context);
  vm.runInContext('library = Promise.resolve({ LiquidGlass: Glass });', context);
  await context.sync();
  assert.equal(created, 3);
  root.dataset.theme = 'dark'; await context.sync();
  assert.equal(created, 3); assert.equal(updated, 3);
  assert.equal(glassOptions.backdrop[1].opacity, undefined, 'Apple wallpaper opacity must be read once from CSS');
  preferences.get('(prefers-reduced-transparency: reduce)').matches = true;
  await context.sync(); assert.equal(destroyed, 3);
  preferences.get('(prefers-reduced-transparency: reduce)').matches = false;
  await context.sync(); assert.equal(created, 6);
  root.dataset.uiTheme = 'ops'; await context.sync(); assert.equal(destroyed, 6);
  let finishImport;
  context.delayed = new Promise(resolve => { finishImport = resolve; });
  vm.runInContext('library = delayed;', context);
  root.dataset.uiTheme = 'apple'; const pending = context.sync();
  root.dataset.uiTheme = 'ops'; await context.sync();
  finishImport({ LiquidGlass: Glass }); await pending;
  assert.equal(created, 6, 'leaving Apple while loading must not attach orphan canvases');
  let rainCreated = 0, rainDestroyed = 0, rainRefreshed = 0;
  context.rainModule = Promise.resolve({ mountRain() {
    rainCreated++;
    return { refresh() { rainRefreshed++; }, destroy() { rainDestroyed++; } };
  } });
  vm.runInContext('rainLibrary = rainModule;', context);
  root.dataset.uiTheme = 'rain'; await context.sync(); await context.sync();
  assert.equal(rainCreated, 1); assert.equal(rainRefreshed, 2);
  root.dataset.uiTheme = 'ops'; await context.sync();
  assert.equal(rainDestroyed, 1);
  let finishRain;
  context.pendingRain = new Promise(resolve => { finishRain = resolve; });
  vm.runInContext('rainLibrary = pendingRain;', context);
  root.dataset.uiTheme = 'rain'; const rainPending = context.sync();
  root.dataset.uiTheme = 'ops'; await context.sync();
  finishRain(await context.rainModule); await rainPending;
  assert.equal(rainCreated, 1, 'leaving Rain while importing must not mount its resources');
});

test('rain preloads nearby cards without a visible sixteen-surface cutoff', () => {
  const rain = readFileSync(new URL('../../static/themes/rain.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(rain.slice(rain.indexOf('export function visibleRainTargets'), rain.indexOf('export function mountRain')).replace('export ', ''), context);
  const node = (left, top, width = 100, height = 100) => ({ getBoundingClientRect: () => ({ left, top, width, height, right: left + width, bottom: top + height }) });
  const visible = Array.from({ length: 20 }, () => node(10, 10));
  const nodes = [node(0, 0, 0, 0), node(0, -400), node(900, 10), node(10, 800), ...visible];
  const result = context.visibleRainTargets(nodes, 800, 600);
  assert.equal(result.length, 20);
  assert.ok(result.every((item, i) => item === visible[i]));
  assert.equal(context.visibleRainTargets([node(0, -120), node(0, 700)], 800, 600).length, 2);
});

test('rain keeps shared lighting stable and bounds optics on tall panels', async () => {
  const rain = readFileSync(new URL('../../static/themes/rain.js', import.meta.url), 'utf8');
  const frames = [], listeners = new Map(), observers = [];
  const node = (width = 974, height = 1277, panel = false) => ({ offsetWidth: width, offsetHeight: height, matches: () => panel,
    style: { setProperty() {} }, setAttribute() {}, removeAttribute() {}, remove() {}, append() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, right: width, bottom: height, width, height }) });
  let nodes = [node(974, 1277, true), node(220, 180)], created = 0, destroyed = 0, updated = 0, refreshed = 0, options;
  class Glass {
    constructor(host, value) { created++; options = value; }
    update(value) { updated++; options = value; }
    refresh() { refreshed++; }
    destroy() { destroyed++; }
  }
  const context = vm.createContext({ LiquidGlass: Glass, innerWidth: 1280, innerHeight: 900,
    Image: function () { return { ...node(), complete: true, naturalWidth: 1672, decode: async () => {} }; },
    document: { documentElement: { dataset: { rainMist: 'on', theme: 'light' } }, body: { prepend() {} },
      createElement: () => node(), querySelectorAll: () => nodes, querySelector: () => node(),
      addEventListener() {}, removeEventListener() {} },
    window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    getComputedStyle: () => ({ getPropertyValue: key => ({ '--rain-wallpaper-opacity': '1', '--rain-tint': '.24', '--rain-frost': '.012', '--rain-refraction': '78',
      '--rain-panel-refraction': '28', '--rain-panel-capture': '8', '--rain-panel-edge': '14' })[key] }),
    MutationObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(target, options) { this.options = options; }
      disconnect() {}
    },
    requestAnimationFrame: fn => { frames.push(fn); return frames.length; }, cancelAnimationFrame() {}, console });
  vm.runInContext(rain.replace(/^import .*;\n/, '').replaceAll('export function', 'function'), context);
  const mounted = context.mountRain(); await Promise.resolve(); frames.shift()();
  assert.equal(created, 1);
  assert.equal(options.backdrop[1].opacity, undefined, 'connected wallpaper opacity comes from CSS only');
  assert.ok(options.material.edgeReach * 974 <= 24);
  assert.ok(options.targets[0].frost * 974 <= 3);
  const dom = readFileSync(new URL('../../static/vendor/liquid-glass/src/dom.js', import.meta.url), 'utf8');
  vm.runInContext(dom.slice(dom.indexOf('const SURFACE_KEYS'), dom.indexOf('export class LiquidGlass')), context);
  for (const [width, height] of [[974, 1277], [1600, 2300], [800, 80]]) {
    nodes[0].offsetWidth = width; nodes[0].offsetHeight = height;
    const optics = context.surfaceProps(options.targets[0]);
    const short = Math.min(width, height);
    assert.equal(optics.refraction, 28);
    assert.ok(optics.edgeReach * short <= 8 + 1e-9, 'panel sampling stays bounded after resize');
    assert.ok(optics.edgeWidth * short / 2 <= 14 + 1e-9, 'long panels cannot grow a thick capture band');
  }
  nodes[0].offsetWidth = 974; nodes[0].offsetHeight = 1277;
  for (const key of ['refraction', 'edgeReach', 'edgeWidth']) {
    assert.equal(options.targets[1][key], undefined, 'home cards keep the shared material');
  }
  const material = JSON.stringify(options.material);
  listeners.get('pointermove')?.({ clientX: 900, clientY: 700 });
  assert.equal(JSON.stringify(options.material), material, 'moving toward a selection must not relight every surface');
  mounted.refresh(); frames.shift()();
  assert.equal(updated, 0, 'unchanged surfaces must not reinitialize the canvas buffer');
  assert.equal(refreshed, 0, 'native scroll tracking must not be duplicated');
  nodes = [node()]; listeners.get('scroll')();
  assert.equal(updated, 1, 'scroll updates the visible targets without an extra animation frame');
  assert.equal(options.backdrop, undefined, 'scroll must not restart wallpaper sampling');
  assert.equal(options.material, undefined, 'scroll must not reset the optical material');
  assert.deepEqual(Array.from(observers[0].options.attributeFilter), ['class', 'hidden']);
  for (const attributeName of ['class', 'hidden']) {
    nodes = [node()];
    observers[0].callback([{ type: 'attributes', attributeName }]);
    assert.equal(options.targets[0].element, nodes[0], 'newly revealed cards must join glass before the next paint');
    assert.equal(options.backdrop, undefined, 'filter changes must reuse the wallpaper texture');
    assert.equal(frames.length, 0, 'visibility updates must not wait an extra animation frame');
  }
  const beforeText = updated;
  observers[0].callback([{ type: 'childList', addedNodes: [{ nodeType: 3 }], removedNodes: [] }]);
  assert.equal(updated, beforeText, 'text polling must not rebuild the glass target list');
  nodes = []; mounted.refresh(); frames.shift()();
  assert.equal(destroyed, 1, 'an empty group must never render the full viewport host');
  mounted.destroy();
});

test('scrolling retains surface identities and reuses a viewport wallpaper texture', () => {
  const source = readFileSync(new URL('../../static/vendor/liquid-glass/src/dom.js', import.meta.url), 'utf8');
  let paints = 0, draws = 0, epoch = 0;
  const context = vm.createContext({ isElement: value => !!value, makeMaterialV2: value => value,
    paintElementBackdrop: () => { paints++; return true; }, layoutEpoch: () => epoch, wake() {} });
  vm.runInContext(source.replace(/^import[\s\S]*?from '[^']+';\r?\n/gm, '')
    .replaceAll('export function', 'function').replace('export class', 'class') + '\nthis.Glass = LiquidGlass;', context);
  const a = {}, b = {}, glass = Object.create(context.Glass.prototype);
  Object.assign(glass, { targetIds: new WeakMap(), nextTargetId: 0, options: { targets: [a, b], bleed: 0, live: false },
    targets: [], styles: [{}, {}, {}], viewportBackdrop: true, buffer: {}, bufferContext: {}, canvas: { style: {} },
    glass: { setBackdrop() {}, updateBackdrop() {}, setElements() {}, render() { draws++; } },
    frame: { x: 0, y: 0, width: 800, height: 600, screenWidth: 800, screenHeight: 600,
      borderLeft: 0, borderTop: 0, scrollLeft: 0, scrollTop: 0,
      targets: [{ x: 20, y: 20, width: 100, height: 100, screenWidth: 100, screenHeight: 100 },
        { x: 20, y: 140, width: 100, height: 100, screenWidth: 100, screenHeight: 100 }] } });
  glass.resolveTargets();
  const originalId = glass.buildElements(glass.frame, 0, 1, 1)[1].id;
  glass.draw();
  glass.frame.targets[0].y -= 30; glass.frame.targets[1].y -= 30; epoch++;
  glass.draw();
  assert.equal(paints, 1, 'scroll changes masks, not the fixed wallpaper texture');
  assert.equal(draws, 2, 'the moving glass still redraws');
  const sizeKey = glass.sizeKey;
  glass.observeSizes = glass.watchStyles = () => {};
  glass.update({ targets: [b] }); glass.frame.targets = [glass.frame.targets[1]];
  assert.equal(glass.buildElements(glass.frame, 0, 1, 1)[0].id, originalId);
  assert.equal(glass.sizeKey, sizeKey, 'target changes must not clear or resize the wallpaper buffer');
  glass.draw();
  glass.refresh({ backdrop: false }); glass.draw();
  assert.equal(paints, 1, 'target and resize-observer updates must not queue a delayed wallpaper repaint');
  glass.frame.screenWidth = 900; glass.draw();
  assert.equal(paints, 2, 'a changed viewport must still repaint its wallpaper');
});

test('shared glass clips nested scroll regions without reshaping lenses or clipping the header', () => {
  const dom = readFileSync(new URL('../../static/vendor/liquid-glass/src/dom.js', import.meta.url), 'utf8');
  const context = vm.createContext({ getComputedStyle: node => node.style });
  vm.runInContext(dom.replace(/^import[\s\S]*?from '[^']+';\r?\n/gm, '')
    .replaceAll('export function', 'function').replace('export class', 'class') + '\nthis.Glass = LiquidGlass;', context);
  const parent = (left, top, width, height, overflowX, overflowY, parentElement = null) => ({
    parentElement, style: { overflowX, overflowY }, offsetWidth: width, offsetHeight: height,
    clientLeft: 0, clientTop: 0, clientWidth: width, clientHeight: height,
    getBoundingClientRect: () => ({ left, top, width, height }),
  });
  const main = parent(184, 68, 1096, 652, 'hidden', 'auto');
  const nested = parent(208, 20, 400, 400, 'visible', 'hidden', main);
  const clip = context.ancestorClip(nested, new Map());
  assert.deepEqual({ ...clip }, { left: 184, top: 68, right: 1280, bottom: 420 });
  const header = {}, partial = {}, outside = {}, glass = Object.create(context.Glass.prototype);
  Object.assign(glass, { options: {}, styles: [{}, {}, {}, {}], targets: [header, partial, outside].map(element => ({ element })),
    targetIds: new WeakMap([[header, 'header'], [partial, 'partial'], [outside, 'outside']]) });
  const box = (y, clip) => ({ x: 208, y, width: 212, height: 212, screenWidth: 212, screenHeight: 212, clip });
  const frame = { x: 0, y: 0, targets: [box(0, null), box(-40, clip), box(-166, clip)] };
  const surfaces = glass.buildElements(frame, 0, 1, 1);
  assert.equal(surfaces.length, 2, 'fully clipped cards must not reach the renderer');
  assert.equal(surfaces[0].clipRect, undefined, 'header is not clipped to the main scroll area');
  assert.deepEqual(Array.from(surfaces[1].clipRect), [184, 68, 1280, 420]);
  assert.equal(surfaces[1].y, -40);
  assert.equal(surfaces[1].height, 212, 'partial clipping must preserve the original lens dimensions');
});

test('expanding chrome preserves its optical height and reuses the reserved backdrop', () => {
  const dom = readFileSync(new URL('../../static/vendor/liquid-glass/src/dom.js', import.meta.url), 'utf8');
  let paints = 0, buffers = 0, current, capacity = 160;
  const context = vm.createContext({ makeMaterialV2: value => value, layoutEpoch: () => 0,
    paintElementBackdrop: (_ctx, _layers, frame) => { paints++; assert.equal(frame.height, capacity); return true; } });
  vm.runInContext(dom.replace(/^import[\s\S]*?from '[^']+';\r?\n/gm, '')
    .replaceAll('export function', 'function').replace('export class', 'class') + '\nthis.Glass = LiquidGlass;', context);
  const glass = Object.create(context.Glass.prototype);
  Object.assign(glass, { options: { bleed: 0, live: false, opticalHeight: () => 68, canvasHeight: () => capacity },
    targets: [], styles: [{}], viewportBackdrop: true, buffer: {}, bufferContext: {}, canvas: { style: {} },
    glass: { setBackdrop() { buffers++; }, updateBackdrop() {}, setElements(elements) { current = elements[0]; }, render() {} },
    frame: { x: 184, y: 0, width: 1096, height: 68, screenWidth: 1096, screenHeight: 68,
      borderLeft: 0, borderTop: 0, scrollLeft: 0, scrollTop: 0, targets: [] } });
  for (const height of [68, 84.25, 110.5, 138, 94.75, 68]) {
    glass.frame.height = glass.frame.screenHeight = height;
    glass.draw();
    assert.equal(current.height, height, 'the outline follows the animated height, including reversals');
    assert.equal(current.opticalHeight, 68, 'the original refraction scale stays anchored');
  }
  assert.equal(buffers, 1, 'no canvas reallocation while opening or closing');
  assert.equal(paints, 1, 'no wallpaper repaint while opening or closing');
  capacity = 240; glass.draw();
  assert.equal(buffers, 2, 'new wrapped content can grow the reservation');
  glass.frame.x += 10; glass.draw();
  assert.equal(paints, 3, 'moving the whole toolbar still updates its backdrop registration');
});

test('expanding chrome samples lighting from the original region', () => {
  const v2 = readFileSync(new URL('../../static/vendor/liquid-glass/src/v2.js', import.meta.url), 'utf8');
  const context = vm.createContext({});
  vm.runInContext(v2.replace(/^import[\s\S]*?from '[^']+';\r?\n/gm, '')
    .replace(/^export \{[\s\S]*?\};?\s*$/gm, '').replaceAll('export ', '')
    + '\nthis.Glass = LiquidGlassWebGLV2;', context);
  const glass = Object.create(context.Glass.prototype);
  glass.sampleLuminance = (x, y) => Math.sin(x * 4 + y * 11) * .5 + .5;
  const closed = context.normalizeElement({ width: 1096, height: 68, opticalHeight: 68, tintTone: 'auto' }, 0);
  const open = context.normalizeElement({ ...closed, h: 138 }, 0);
  assert.deepEqual(glass.lightDirection(open, 1280, 720, 125), glass.lightDirection(closed, 1280, 720, 125));
  assert.equal(glass.tintLightForElement(open, 1280, 720), glass.tintLightForElement(closed, 1280, 720));
  assert.equal(context.normalizeElement({ width: 100, height: 142 }, 0).opticalHeight, 142);
  assert.throws(() => context.normalizeElement({ width: 100, height: 142, opticalHeight: NaN }, 0), /optical height/);
  for (const key of ['refraction', 'edgeReach', 'edgeWidth']) {
    assert.equal(context.normalizeElement({ [key]: '0.1' }, 0)[key], .1);
    assert.equal(context.normalizeElement({}, 0)[key], undefined, 'unconfigured optics inherit the material');
    for (const invalid of [NaN, Infinity, -1]) {
      assert.throws(() => context.normalizeElement({ [key]: invalid }, 0), new RegExp(key));
    }
  }
});

test('wallpaper upload stays with the selected theme when navigation changes during decode', async () => {
  const root = { dataset: { uiTheme: 'rain' } };
  const requests = [];
  let finishDecode;
  const pending = new Promise(resolve => { finishDecode = resolve; });
  const context = vm.createContext({ document: { documentElement: root }, matchMedia: () => ({}),
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    Image: function () { return { setAttribute() {}, decode: () => pending }; },
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, json: async () => ({ ok: true }) }; },
    console, toast() {} });
  vm.runInContext(source.replace(/^import .*;\n/, '').replaceAll('export function', 'function') + '\nthis.save = saveWallpaper;', context);
  vm.runInContext('wallpaperChoose = {}; wallpaperReset = {}; wallpaperStatus = {}; wallpaperInput = {};', context);
  const file = { type: 'image/png', size: 32 };
  const saving = context.save(file);
  root.dataset.uiTheme = 'ops'; finishDecode(); await saving;
  assert.equal(requests[0].url, '/api/ui/wallpaper?theme=rain');
  assert.equal(requests[0].options.body, file);
  assert.equal(vm.runInContext('wallpaperUrls.apple', context), '/api/ui/wallpaper');
  assert.match(vm.runInContext('wallpaperUrls.rain', context), /theme=rain&v=/);
});
