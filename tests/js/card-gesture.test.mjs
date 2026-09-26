import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('clicks survive small movement, but dragging and touch scrolling consume the release click', () => {
  const source = readFileSync(new URL('../../static/js/launchpad.js', import.meta.url), 'utf8');
  const listeners = new Map();
  let starts = 0;
  const context = vm.createContext({
    window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) },
    started: () => starts++, moveDrag() {}, cancelPointerDrag() {},
  });
  vm.runInContext(`let drag = null, keyboardSort = null, suppressDragClick = false;
    function beginDrag() { started(); drag = {}; }
    function endDrag() { drag = null; }
    ` + source.slice(source.indexOf('function blockDragClick('), source.indexOf("document.addEventListener('click', blockDragClick"))
    + source.slice(source.indexOf('function cardPointerDown('), source.indexOf('function beginDrag(')), context);
  function gesture(distance, pointerType = 'mouse', back = false) {
    const event = { button: 0, pointerId: 1, pointerType, clientX: 0, clientY: 0,
      target: { closest: selector => back && selector === 'details' }, currentTarget: {} };
    context.cardPointerDown(event);
    listeners.get('pointermove')({ ...event, clientX: distance });
    listeners.get('pointerup')({ ...event, clientX: distance });
    let blocked = false;
    context.blockDragClick({ detail: 1, preventDefault() { blocked = true; }, stopImmediatePropagation() {} });
    return blocked;
  }
  assert.equal(gesture(4), false);
  assert.equal(starts, 0);
  assert.equal(gesture(8), true);
  assert.equal(starts, 1);
  assert.equal(gesture(8, 'touch'), true);
  assert.equal(gesture(8, 'mouse', true), true);
  assert.equal(starts, 1); // Scrolling the back and ordinary touch scrolling never sort.
  assert.equal(gesture(0), false); // The next deliberate click works immediately.
});
