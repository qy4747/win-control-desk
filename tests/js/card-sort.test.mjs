import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/launchpad.js', import.meta.url), 'utf8');

function setup(columns = 3, scroll = 0) {
  const frames = new Map(), timers = new Map();
  let serial = 0;
  const grid = {
    children: [],
    querySelectorAll() { return this.children.filter(c => c.id !== 'ph'); },
    contains(c) { return this.children.includes(c); },
    insertBefore(c, ref) {
      this.children.splice(this.children.indexOf(c), 1);
      this.children.splice(ref ? this.children.indexOf(ref) : this.children.length, 0, c);
    },
  };
  const base = { left: 200, top: 80 - scroll };
  for (const id of ['ph', 'b', 'c', 'd', 'e', 'f']) {
    grid.children.push({
      id, style: {}, isConnected: true,
      classList: { contains: () => false },
      matches: () => id !== 'ph',
      closest() { return this; },
      get offsetLeft() { return grid.children.indexOf(this) % columns * 110; },
      get offsetTop() { return Math.floor(grid.children.indexOf(this) / columns) * 110; },
      offsetWidth: 100, offsetHeight: 100,
      offsetParent: { getBoundingClientRect: () => base },
      get nextSibling() { return grid.children[grid.children.indexOf(this) + 1] || null; },
      getBoundingClientRect() { return { left: base.left + this.offsetLeft, top: base.top + this.offsetTop }; },
    });
  }
  const ph = grid.children[0], card = { style: {} };
  const context = vm.createContext({
    drag: { grid, ph, card, dx: 20, dy: 30 }, reduceMotion: false,
    // A card sliding across rows can visually cover a different layout slot.
    document: { elementFromPoint: () => grid.children.find(c => c.id === 'c') },
    requestAnimationFrame: fn => { frames.set(++serial, fn); return serial; },
    cancelAnimationFrame: id => frames.delete(id),
    setTimeout: fn => { timers.set(++serial, fn); return serial; },
    clearTimeout: id => timers.delete(id),
    getComputedStyle: () => ({ getPropertyValue: () => '200' }),
  });
  vm.runInContext(source.slice(source.indexOf('/* FLIP '), source.indexOf('function cardPointerDown('))
    + source.slice(source.indexOf('function moveDrag('), source.indexOf('function resetPointerDragCard(')), context);
  return { context, grid, ph, card, frames, timers, base };
}

test('cross-row drag targets layout slots and stays put while neighboring cards animate', () => {
  const { context, grid, ph, card } = setup();
  for (let i = 0; i < 20; i++) {
    context.moveDrag({ clientX: 390 + i % 2, clientY: 230 });
    assert.equal(grid.children.indexOf(ph), 4);
  }
  assert.equal(card.style.transform, 'translate(371px,200px)');
  context.moveDrag({ clientX: 225, clientY: 110 });
  assert.equal(grid.children.indexOf(ph), 0);
});

test('single-column dragging uses vertical slots after scrolling, ignoring gaps and hidden cards', () => {
  const { context, grid, ph } = setup(1, 150);
  grid.children[1].offsetWidth = 0;
  context.moveDrag({ clientX: 230, clientY: 60 });
  assert.equal(grid.children.indexOf(ph), 0);
  context.moveDrag({ clientX: 230, clientY: 255 }); // gap between rows
  assert.equal(grid.children.indexOf(ph), 0);
  context.moveDrag({ clientX: 230, clientY: 290 });
  assert.equal(grid.children.indexOf(ph), 3);
  context.moveDrag({ clientX: 180, clientY: 290 }); // outside grid
  assert.equal(grid.children.indexOf(ph), 3);
});

test('taking over a card cancels both pending frames and running FLIP cleanup', () => {
  for (const running of [false, true]) {
    const { context, grid, ph, frames, timers } = setup();
    const card = grid.children[1];
    context.flip(grid, () => grid.insertBefore(card, null));
    assert.equal(ph.style.transform, undefined); // stable drop target, never animated
    if (running) {
      for (const fn of frames.values()) fn();
      frames.clear();
    }
    context.stopFlip(card);
    card.style.transform = 'translate(500px,300px)';
    for (const fn of frames.values()) fn();
    for (const fn of timers.values()) fn();
    assert.equal(card.style.transform, 'translate(500px,300px)');
    assert.equal(card.style.transition, 'none');
  }
});
