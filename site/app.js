(() => {
  const picker = document.getElementById("language");
  const catalogs = {};
  const docRoot =
    "https://github.com/runchengxie/ai-stock-picker/blob/main/docs/";
  let request = 0;

  async function catalog(locale) {
    if (!catalogs[locale]) {
      const response = await fetch(`./locales/${locale}.json`);
      if (!response.ok) throw new Error("Locale unavailable");
      catalogs[locale] = await response.json();
    }
    return catalogs[locale];
  }

  async function setLanguage(locale) {
    const id = ++request;
    const english = await catalog("en");
    let selected = english;
    let applied = locale;
    if (locale !== "en") {
      try {
        selected = await catalog(locale);
      } catch {
        applied = "en";
      }
    }
    if (id !== request) return;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.dataset.i18n;
      element.textContent =
        selected[key] ?? english[key] ?? element.textContent;
    });
    document.title = selected["page.title"] ?? english["page.title"];
    document.querySelector('meta[name="description"]').content =
      selected["page.description"] ?? english["page.description"];
    document.documentElement.lang = applied;
    document.querySelectorAll("[data-doc]").forEach((link) => {
      link.href = `${docRoot}${applied === "zh-CN" ? "zh-CN/" : ""}${link.dataset.doc}`;
    });
    picker.value = applied;
    try {
      localStorage.setItem("aipick.locale", applied);
    } catch {
      // The page also works when browser storage is disabled.
    }
  }

  let initial = "en";
  try {
    if (localStorage.getItem("aipick.locale") === "zh-CN") initial = "zh-CN";
  } catch {
    // English remains the default.
  }
  setLanguage(initial)
    .then(() => {
      picker.disabled = false;
    })
    .catch(() => {
      // Keep the complete server-rendered English page if catalogs cannot load.
      picker.disabled = true;
    });
  picker.addEventListener("change", () => {
    setLanguage(picker.value).catch(() => {
      picker.value = document.documentElement.lang;
    });
  });
})();
