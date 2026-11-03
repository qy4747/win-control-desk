import test from 'node:test';
import assert from 'node:assert/strict';
import { shortcut, NAV } from '../../static/js/shortcuts.js';

test('exact chords only, including Option+digit on a non-US layout', () => {
  NAV.forEach(([view], i) => assert.equal(shortcut({ altKey: true, key: String(i+1) }), view));
  assert.equal(shortcut({ altKey: true, key: '¡', code: 'Digit1' }), 'launchpad');
  for (const mod of ['ctrlKey', 'metaKey']) {
    assert.equal(shortcut({ [mod]: true, key: 'k' }), 'palette');
    assert.equal(shortcut({ [mod]: true, key: 'J' }), 'logs');
    assert.equal(shortcut({ [mod]: true, shiftKey: true, key: 'G' }), 'glance');
    assert.equal(shortcut({ [mod]: true, altKey: true, key: 'g' }), null);
  }
  assert.equal(shortcut({ key: 'g', shiftKey: true }), null);
  assert.equal(shortcut({ key: '1', altKey: true, shiftKey: true }), null);
});
test('typing, IME composition, handled events and auto-repeat never launch single-key help', () => {
  assert.equal(shortcut({ key: '?', shiftKey: true }), 'help');
  for (const extra of [{ target: { closest: () => true } }, { target: { isContentEditable: true } },
    { isComposing: true }, { keyCode: 229 }, { repeat: true }, { defaultPrevented: true }, { altKey: true }])
    assert.equal(shortcut({ key: '?', ...extra }), null);
  assert.equal(shortcut({ key: 'k', ctrlKey: true, isComposing: true }), null);
});
