// Offline source boundary check; no browser or application operations.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../../static/' + path, import.meta.url), 'utf8');
test('component styles leave paint and typography to the theme', () => {
  for (const path of ['base.css', 'ops.css', 'files.css']) {
    const css = read(path).replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(css, /(?:^|[;{])\s*(?:color|background(?:-[\w-]+)?|font(?:-[\w-]+)?|line-height|letter-spacing|text-shadow|fill|stroke(?:-[\w-]+)?|--(?:tone|metric-color|resource-color))\s*:/m, path);
  }
  const theme = read('themes/ops.css');
  assert.match(theme, /\.ops-preset-app-toggle\.is-on\s*\{[^}]*border:/);
  assert.match(theme, /@keyframes ops-package-charge/);
  assert.match(theme, /\.folder-tab\[aria-pressed="true"\]\s*\{[^}]*background:/);
  const js = read('js/launchpad.js');
  assert.doesNotMatch(js, /style\.transition\s*=\s*['"]transform /);
  assert.doesNotMatch(js, /function fallbackGlow/);
});
