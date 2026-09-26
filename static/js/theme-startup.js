// Parser-blocking: apply local display preferences before any stylesheet or body paints.
(() => {
  const root = document.documentElement;
  let theme, mist;
  try {
    theme = localStorage.getItem('console-theme');
    mist = localStorage.getItem('console-rain-mist');
  } catch { /* Browser storage can be disabled; the system preference still works. */ }
  root.dataset.theme = theme === 'dark' || theme === 'light'
    ? theme : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  root.dataset.rainMist = mist === 'off' ? 'off' : 'on';
})();
