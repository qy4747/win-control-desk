import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('card flip switches faces, restores focus, and respects reduced motion', async () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const theme = readFileSync(new URL('../../static/themes/ops.css', import.meta.url), 'utf8');
  const values = new Map([...theme.matchAll(/(--card-flip-[\w-]+):\s*([^;]+);/g)].map(([, name, value]) => [name, value]));
  for (const reduced of [false, true]) for (const toggleVisible of [false, true]) {
    let animations = 0, toggleFocus = 0, cardFocus = 0;
    const frames = [], effects = [];
    const toggle = { focus() { toggleFocus++; }, setAttribute() {}, getClientRects: () => toggleVisible ? [{}] : [] };
    const menu = { open: false, querySelector: () => toggle };
    const animate = (keyframes, options) => {
      animations++; frames.push({ keyframes, options });
      const effect = { startTime: animations * 1000, finished: Promise.resolve(), canceled: false, cancel() { this.canceled = true; } };
      effects.push(effect); return effect;
    };
    const front = { inert: false, animate, classList: { contains: () => false } };
    const card = { children: [front, menu], focus() { cardFocus++; },
      _r: { name: { textContent: 'Sample' } },
      _ops: { menu, front, body: { animate } } };
    const context = vm.createContext({ matchMedia: () => ({ matches: reduced }), document: { querySelectorAll: () => [] },
      getComputedStyle: () => ({ getPropertyValue: name => values.get(name) || '' }) });
    vm.runInContext(source.slice(source.indexOf('async function flipCard('), source.indexOf('export function updateCardExtras(')) + '\nthis.flip = flipCard;', context);
    await context.flip(card, true);
    assert.equal(menu.open, true);
    assert.equal(front.inert, true);
    assert.equal(toggleFocus, toggleVisible ? 1 : 0);
    assert.equal(cardFocus, toggleVisible ? 0 : 1);
    assert.equal(toggle.textContent, '返回');
    await context.flip(card, false);
    assert.equal(menu.open, false);
    assert.equal(front.inert, false);
    assert.equal(toggleFocus, toggleVisible ? 2 : 0);
    assert.equal(cardFocus, toggleVisible ? 0 : 2);
    assert.equal(toggle.textContent, '翻面');
    assert.equal(animations, reduced ? 0 : 4);
    if (!reduced) {
      assert.equal(frames[0].keyframes[1].transform, values.get('--card-flip-right'));
      assert.equal(frames[2].keyframes[1].transform, values.get('--card-flip-left'));
      assert.equal(frames[0].options.duration, Number(values.get('--card-flip-out-ms')));
      assert.equal(frames[1].options.duration, Number(values.get('--card-flip-in-ms')));
    }
    assert.equal(card._ops.flipping, false);
    // Reuse the same card, including late phase handoffs, without resetting the incoming clock.
    for (let cycle = 0; cycle < 3; cycle++) {
      await context.flip(card, true);
      await context.flip(card, false);
      assert.equal(menu.open, false);
      assert.equal(front.inert, false);
      assert.equal(card._ops.flipping, false);
    }
    for (let i = 0; i < effects.length; i += 2) {
      assert.equal(effects[i + 1].startTime, effects[i].startTime + Number(values.get('--card-flip-out-ms')));
      assert.equal(frames[i + 1].options.fill, 'both');
      assert.ok(effects[i].canceled && effects[i + 1].canceled);
    }
  }
});
