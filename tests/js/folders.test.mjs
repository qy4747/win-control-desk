import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const tick = () => new Promise(setImmediate);
function harness() {
  function element() {
    const classes = new Set();
    return { value: '', textContent: '', children: [], dataset: {}, handlers: {},
      classList: { add: v => classes.add(v), remove: v => classes.delete(v), contains: v => classes.has(v) },
      append(...nodes) { this.children.push(...nodes); }, prepend(...nodes) { this.children.unshift(...nodes); },
      replaceChildren(...nodes) { this.children = nodes; }, setAttribute() {}, focus() {},
      addEventListener(name, handler) { this.handlers[name] = handler; } };
  }
  const nodes = new Map(), gets = [], picks = [], posts = [], confirmations = [];
  const $ = key => { if (!nodes.has(key)) nodes.set(key, element()); return nodes.get(key); };
  const context = vm.createContext({ $, AbortSignal, Event: class {}, icon: element, iconBtn: element, el: element,
    toast() {}, escapeHtml: text => text, act: p => p,
    openLayer: layer => layer.classList.add('open'), closeLayer: layer => layer.classList.remove('open'),
    openConfirm: data => confirmations.push(data), document: { dispatchEvent() {}, querySelectorAll: () => [] },
    fetch: () => new Promise((resolve, reject) => gets.push({ resolve, reject })),
    post: async (path, data) => { posts.push({ path, data }); return { ok: true }; },
    postWithTimeout: () => new Promise(resolve => picks.push(resolve)) });
  const source = readFileSync(new URL('../../static/js/folders.js', import.meta.url), 'utf8');
  vm.runInContext(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, '') + `
    this.api = { loadFileConfig, fileConfig, openFolderDialog, closeFolderDialog, reorder };
    initFolders();
  `, context);
  const respond = (index, folders) => gets[index].resolve({ ok: true, json: async () => ({ ok: true, folders, settings: {} }) });
  return { $, gets, picks, posts, confirmations, respond, ...context.api };
}
const initial = [{ id: 'a', name: 'A', path: 'A', group: '' }, { id: 'b', name: 'B', path: 'B', group: '' }];

test('save, remove and reorder fetch a new snapshot after an older read finishes', async () => {
  for (const action of ['save', 'remove', 'reorder']) {
    const h = harness();
    const seed = h.loadFileConfig(); h.respond(0, initial); await seed;
    const oldRead = h.loadFileConfig();
    let mutation, expected;
    if (action === 'save') {
      h.openFolderDialog(initial[0]); h.$('#folderName').value = 'Updated';
      expected = [{ ...initial[0], name: 'Updated' }, initial[1]];
      mutation = h.$('#folderForm').handlers.submit({ preventDefault() {} });
    } else if (action === 'reorder') {
      expected = [initial[1], initial[0]]; mutation = h.reorder('a', 'b');
    } else {
      const walk = node => [node, ...node.children.flatMap(walk)];
      walk(h.$('#folderList')).find(node => node.textContent === '移除收藏').handlers.click();
      expected = [initial[1]]; mutation = h.confirmations[0].onOk();
    }
    await tick(); assert.equal(h.posts.length, 1); assert.equal(h.gets.length, 2);
    h.respond(1, initial); await oldRead; await tick();
    assert.equal(h.gets.length, 3, action + ' must fetch after the write');
    h.respond(2, expected); await mutation;
    assert.deepEqual(h.fileConfig().folders, expected);
  }
});

test('picker results belong to one open draft and expire on close or save', async () => {
  for (const action of ['unchanged', 'close', 'reopen', 'save']) {
    const h = harness(); h.openFolderDialog(initial[0]);
    const pick = h.$('#folderPick').handlers.click({ currentTarget: h.$('#folderPick') });
    let save;
    if (action === 'close' || action === 'reopen') h.closeFolderDialog();
    if (action === 'reopen') h.openFolderDialog(initial[1]);
    if (action === 'save') save = h.$('#folderForm').handlers.submit({ preventDefault() {} });
    h.picks[0]({ path: 'picked-for-A' }); await pick;
    assert.equal(h.$('#folderPath').value, action === 'unchanged' ? 'picked-for-A' : action === 'reopen' ? 'B' : 'A');
    if (save) { await tick(); h.respond(0, initial); await save; }
    assert.equal(h.$('#folderName').value, action === 'reopen' ? 'B' : 'A');
  }
});
