(() => {
  const storageKey = "aipick.theme";
  const root = document.documentElement;
  const buttonId = "theme-toggle";
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let savedTheme = null;

  try {
    savedTheme = localStorage.getItem(storageKey);
  } catch {
    // The theme still follows the system setting when storage is unavailable.
  }

  function currentTheme() {
    return savedTheme === "dark" || savedTheme === "light"
      ? savedTheme
      : media.matches
        ? "dark"
        : "light";
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#111814" : "#f7f8f2";
    const button = document.getElementById(buttonId);
    if (!button) return;
    const dark = theme === "dark";
    button.setAttribute("aria-pressed", String(dark));
    button.querySelector(".theme-icon").textContent = dark ? "☀" : "☾";
    const label = document.getElementById("theme-toggle-label");
    if (label) {
      label.dataset.i18n = dark ? "theme.switchToLight" : "theme.switchToDark";
      updateLabel(label, label.dataset.i18n);
    }
  }

  async function updateLabel(label, key) {
    const locale = root.lang === "zh-CN" ? "zh-CN" : "en";
    try {
      const response = await fetch(`./locales/${locale}.json`);
      if (!response.ok) return;
      const catalog = await response.json();
      if (
        label.isConnected &&
        label.dataset.i18n === key &&
        (root.lang === "zh-CN" ? "zh-CN" : "en") === locale
      ) {
        label.textContent = catalog[key] ?? key;
      }
    } catch {
      // The button's English label remains usable if translations cannot load.
    }
  }

  applyTheme(currentTheme());
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(currentTheme());
    document.getElementById(buttonId)?.addEventListener("click", () => {
      savedTheme = root.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(storageKey, savedTheme);
      } catch {
        // The selection applies for this page even when it cannot be persisted.
      }
      applyTheme(savedTheme);
    });
  });

  new MutationObserver(() => {
    const label = document.getElementById("theme-toggle-label");
    if (label) updateLabel(label, label.dataset.i18n);
  }).observe(root, { attributes: true, attributeFilter: ["lang"] });

  media.addEventListener("change", () => {
    if (savedTheme !== "dark" && savedTheme !== "light")
      applyTheme(currentTheme());
  });
})();
