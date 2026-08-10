(function () {
  var param = new URLSearchParams(location.search).get('theme');
  var saved = null;
  try { saved = localStorage.getItem('utheme'); } catch (e) {}
  var choice = param || saved;
  var dark = choice ? choice === 'dark' : (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
