export function savedLanguage() {
  try {
    return localStorage.getItem('aipick.locale') === 'zh-CN' ? 'zh-CN' : 'en';
  } catch {
    return 'en';
  }
}

export function rememberLanguage(locale) {
  try {
    localStorage.setItem('aipick.locale', locale);
  } catch {
    // Switching remains usable when browser storage is unavailable.
  }
}

export function setupNoteLanguage() {
  const picker = document.querySelector('#language');
  if (!picker) return;
  // An explicit note URL takes precedence over a preference saved on another page.
  picker.value = document.documentElement.lang;
  rememberLanguage(picker.value);
  picker.addEventListener('change', () => {
    const target = picker.value === 'zh-CN' ? picker.dataset.localeZh : picker.dataset.localeEn;
    if (!target) return;
    rememberLanguage(picker.value);
    window.location.assign(target);
  });
}
