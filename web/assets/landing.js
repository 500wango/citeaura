(function () {
  var root = document.documentElement;
  var themeButton = document.querySelector(".theme-toggle");
  var themeLabel = document.querySelector(".theme-label");
  var themeMeta = document.querySelector('meta[name="theme-color"]');
  var storedTheme;

  try {
    storedTheme = window.localStorage.getItem("disvorai-site-theme");
  } catch (error) {
    storedTheme = null;
  }

  if (storedTheme === "light" || storedTheme === "dark") {
    root.dataset.theme = storedTheme;
  }

  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function renderThemeControl() {
    var dark = currentTheme() === "dark";
    themeButton.setAttribute("aria-pressed", String(dark));
    themeLabel.textContent = dark ? "浅色" : "深色";
    themeButton.setAttribute("aria-label", dark ? "切换到浅色主题" : "切换到深色主题");
    themeMeta.setAttribute("content", dark ? "#121318" : "#f5f5f3");
  }

  themeButton.addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      window.localStorage.setItem("disvorai-site-theme", next);
    } catch (error) {
      // 浏览器禁止本地存储时，主题仍在当前页面生效。
    }
    renderThemeControl();
  });

  var systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  systemTheme.addEventListener("change", function () {
    if (!root.dataset.theme) renderThemeControl();
  });
  renderThemeControl();

  document.querySelectorAll("[data-billing]").forEach(function (button) {
    button.addEventListener("click", function () {
      var interval = button.dataset.billing;
      document.querySelectorAll("[data-billing]").forEach(function (item) {
        var active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      document.querySelectorAll("[data-monthly][data-annual]").forEach(function (item) {
        item.textContent = item.dataset[interval];
      });
    });
  });

  var revealItems = document.querySelectorAll(".reveal");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
    revealItems.forEach(function (item) {
      item.classList.add("is-visible");
    });
    return;
  }

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-visible");
      observer.unobserve(entry.target);
    });
  }, { rootMargin: "0px 0px -8%", threshold: 0.08 });

  revealItems.forEach(function (item) {
    observer.observe(item);
  });
}());
