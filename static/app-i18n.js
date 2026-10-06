// app-i18n.js -- the page's words by key (I18N_v1, docs/plans/localization.md l10n/C, D1-D4). Loaded first; boot
// starts once i18nReady settles. Code asks tr(key, vars) with a dotted key -- `tr`, never `t`: the page names a
// hundred locals `t`, and one would hide the function (test_l10n_catalogs forbids a local `tr`). A table of names by
// id is i18nTable(prefix): TABLE[id] is the word, or undefined for an id the catalog lacks (so `TABLE[id] || id`).
// Static markup carries data-i18n (text), data-i18n-title, -aria-label, -placeholder and -alt. A key missing in the language
// falls back to English, then to the key. Catalogs: static/i18n/<lang>.json, flat keys, the same set in every language.
const I18N_LANGS = ['ko', 'en'];   // D1: first languages
const I18N_FALLBACK = 'en';
const I18N_STORE = 'chatbot.lang';

// D4: the chosen language (?lang= picks it for this browser), then the browser's, then English.
function i18nPickLang() {
  const ok = l => I18N_LANGS.includes(l) ? l : '';
  let asked = '';
  try {
    asked = ok(String(new URLSearchParams(location.search).get('lang') || '').toLowerCase());
    if (asked) localStorage.setItem(I18N_STORE, asked);
  } catch (e) {}
  let kept = '';
  try { kept = ok(localStorage.getItem(I18N_STORE) || ''); } catch (e) {}
  const nav = (typeof navigator !== 'undefined' && (navigator.languages || [navigator.language])) || [];
  const browser = nav.map(x => ok(String(x || '').toLowerCase().split('-')[0])).find(Boolean) || '';
  return asked || kept || browser || I18N_FALLBACK;
}

const I18N_LANG = i18nPickLang();
let I18N = {};

// ---- I18N helpers (page_source.i18n_prelude runs this part over the Korean catalog in page tests) ----
function tr(key, vars) {
  const s = Object.prototype.hasOwnProperty.call(I18N, key) ? I18N[key] : key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m)) : s;
}

function i18nTable(prefix) {
  return new Proxy({}, { get: (_, id) => {
    const key = prefix + '.' + String(id);
    return typeof id === 'string' && Object.prototype.hasOwnProperty.call(I18N, key) ? I18N[key] : undefined;
  } });
}

// L4: numbers and times in the page's language, never a fixed locale.
function fmtNumber(n, opts) { return new Intl.NumberFormat(I18N_LANG, opts).format(Number(n || 0)); }
function fmtTime(when) { return new Date(when).toLocaleTimeString(I18N_LANG); }
function fmtDate(when, opts) { return new Date(when).toLocaleDateString(I18N_LANG, opts); }
// ---- end I18N helpers ----

function applyI18n(root) {
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = tr(el.dataset.i18nTitle); });
  root.querySelectorAll('[data-i18n-aria-label]').forEach(el => { el.setAttribute('aria-label', tr(el.dataset.i18nAriaLabel)); });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = tr(el.dataset.i18nPlaceholder); });
  root.querySelectorAll('[data-i18n-alt]').forEach(el => { el.alt = tr(el.dataset.i18nAlt); });
}

const i18nReady = (async () => {
  const load = async lang => {
    try {
      const r = await fetch('./i18n/' + lang + '.json', { cache: 'no-cache' });   // revalidated: catalogs change often
      return r.ok ? await r.json() : {};
    } catch (e) {
      return {};
    }
  };
  const [base, mine] = await Promise.all([load(I18N_FALLBACK), I18N_LANG === I18N_FALLBACK ? {} : load(I18N_LANG)]);
  I18N = Object.assign({}, base, mine);
  document.documentElement.lang = I18N_LANG;
  applyI18n(document);
})();
