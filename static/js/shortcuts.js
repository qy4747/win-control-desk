export const NAV = [
  ['launchpad', '启动台'], ['folders', '文件夹'], ['files', '文件搜索'],
  ['services', '服务监控'], ['logs', '日志中心'], ['settings', '设置中心'],
];
export const KEYS = { palette: 'Ctrl/⌘+K', logs: 'Ctrl/⌘+J', glance: 'Ctrl/⌘+Shift+G', help: '?' };
export function shortcut(e) {
  if (e.defaultPrevented || e.isComposing || e.keyCode === 229 || e.repeat) return null;
  const key = e.key.toLowerCase();
  if (e.ctrlKey || e.metaKey) {
    if (e.altKey || (e.metaKey && e.ctrlKey)) return null;
    if (e.shiftKey) return key === 'g' ? 'glance' : null;
    return key === 'k' ? 'palette' : key === 'j' ? 'logs' : null;
  }
  if (e.altKey && !e.shiftKey) {
    const digit = /^[1-6]$/.test(key) ? key : /^Digit[1-6]$/.test(e.code) ? e.code.at(-1) : null;
    return digit ? NAV[Number(digit) - 1][0] : null;
  }
  if (key === '?' && !e.altKey && !e.target?.isContentEditable &&
      !e.target?.closest?.('input, textarea, select, [role="textbox"]')) return 'help';
  return null;
}
