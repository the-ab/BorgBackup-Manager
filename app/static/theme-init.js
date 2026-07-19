(() => {
  const theme = localStorage.getItem('bbm-theme');
  document.documentElement.dataset.theme = ['light', 'dark'].includes(theme) ? theme : 'light';
})();
