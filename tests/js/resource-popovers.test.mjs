import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('resource hover switches independent popovers and anchors to each metric', () => {
  const source = readFileSync(new URL('../../static/js/ops.js', import.meta.url), 'utf8');
  const context = vm.createContext({ clearTimeout, innerWidth: 1000, innerHeight: 800 });
  vm.runInContext('let activeMetric, metricsHideTimer;\n' + source.slice(
    source.indexOf('function placeMetricsPopover()'), source.indexOf('function scheduleMetricsHide()')), context);
  const bars = [100, 200, 300].map(left => ({
    node: { getBoundingClientRect: () => ({ left, bottom: 60 }) },
    popover: { open: false, style: {}, offsetWidth: 320, offsetHeight: 200,
      matches() { return this.open; }, showPopover() { this.open = true; }, hidePopover() { this.open = false; } }
  }));
  for (const [i, bar] of bars.entries()) {
    context.showMetricsPopover(bar);
    assert.deepEqual(bars.map(b => b.popover.open), bars.map((_, j) => i === j));
    assert.equal(bar.popover.style.left, `${100 + i * 100}px`);
    assert.equal(bar.popover.style.top, '72px');
  }
  context.closeMetricsPopover();
  assert.ok(bars.every(b => !b.popover.open));
});
