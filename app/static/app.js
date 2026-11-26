/* MYP Lesson Analyzer — клиентская часть (без сборки, без фреймворков).
   Маршрутизация через location.hash, состояние — в нескольких переменных. */
'use strict';

/* ------------------------------------------------------------------ */
/* Утилиты                                                             */
/* ------------------------------------------------------------------ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------------------------------------------ */
/* Языки интерфейса                                                    */
/* Ключ перевода — русская строка как есть. Словари en / kk лежат в     */
/* /static/i18n.js; если перевода нет, показывается русский текст.      */
/* Смена языка перезагружает страницу — так все подписи, включая        */
/* созданные при загрузке скрипта, сразу на нужном языке.               */
/* ------------------------------------------------------------------ */

/* i18n-skip-start */
const UI_LANGS = { ru: 'Русский', kk: 'Қазақша', en: 'English' };

function detectLang() {
  let saved = null;
  try { saved = localStorage.getItem('uiLang'); } catch { /* */ }
  if (saved && UI_LANGS[saved]) return saved;
  const nav = (navigator.language || '').toLowerCase();
  if (nav.startsWith('kk')) return 'kk';
  if (nav.startsWith('en')) return 'en';
  return 'ru';
}
const LANG = detectLang();
document.documentElement.lang = LANG;

function t(key, vars) {
  let s = (LANG !== 'ru' && window.I18N?.[LANG]?.[key]) || key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m));
  return s;
}

function setUiLang(lang, { save = true } = {}) {
  try { localStorage.setItem('uiLang', lang); } catch { /* */ }
  const done = () => location.reload();
  if (save && state.user) api('POST', '/api/auth/preferences', { ui_language: lang }).finally(done);
  else done();
}

function langSwitcher(cls = '') {
  return `<div class="lang-switch ${cls}" role="group" aria-label="Language">${Object.entries({ ru: 'RU', kk: 'KZ', en: 'EN' })
    .map(([k, v]) => `<button type="button" data-lang="${k}" aria-pressed="${k === LANG}" title="${UI_LANGS[k]}">${v}</button>`).join('')}</div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lang]');
  if (!b) return;
  if (b.dataset.lang !== LANG) return setUiLang(b.dataset.lang);
  // Язык уже выбран автоматически — запоминаем его как явный выбор.
  try { localStorage.setItem('uiLang', LANG); } catch { /* */ }
  if (state.user) api('POST', '/api/auth/preferences', { ui_language: LANG }).catch(() => {});
});

const MONTHS_BY_LANG = {
  ru: ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
  kk: ['қаң', 'ақп', 'нау', 'сәу', 'мам', 'мау', 'шіл', 'там', 'қыр', 'қаз', 'қар', 'жел'],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
};
const MONTHS = MONTHS_BY_LANG[LANG];

/* Формы множественного числа. Аргументы уже переведены через t():
   en — «one» при n = 1, иначе «many»; kk — существительное после числа
   не меняется, всегда «one». */
function plural(n, one, few, many) {
  if (LANG === 'en') return n === 1 ? one : many;
  if (LANG === 'kk') return one;
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

/* Название предметной группы на языке интерфейса */
function subjectLabel(s) {
  if (!s) return '';
  if (LANG === 'kk') return s.label_kk || s.label;
  if (LANG === 'en') return s.label;
  return s.label_ru || s.label;
}
function observabilityNote(s) {
  return (LANG === 'en' ? s.audio_observability_note_en : s.audio_observability_note) || s.audio_observability_note || '';
}
/* i18n-skip-end */

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(method, url, body) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* пустой ответ */ }
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith('/api/auth/')) {
      state.user = null;
      go('/login');
    }
    throw new ApiError(res.status, errorText(data, res.status));
  }
  return data;
}

function errorText(data, status) {
  if (data && typeof data.detail === 'string') return t(data.detail);
  if (data && data.detail && typeof data.detail.message === 'string') return t(data.detail.message);
  if (data && Array.isArray(data.detail)) return t('Проверьте заполнение формы.');
  if (status === 413) return t('Файл слишком большой.');
  return t('Не удалось выполнить запрос. Проверьте соединение и попробуйте ещё раз.');
}

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function confirmDialog({ title, text, confirm = t('Подтвердить'), danger = false }) {
  return new Promise(resolve => {
    const d = document.createElement('dialog');
    d.innerHTML = `
      <div class="d-body"><h2>${esc(title)}</h2><p class="muted">${esc(text)}</p></div>
      <div class="d-actions">
        <button class="btn" value="cancel" data-act="no">${t('Отмена')}</button>
        <button class="btn ${danger ? 'danger' : 'primary'}" data-act="yes">${esc(confirm)}</button>
      </div>`;
    document.body.appendChild(d);
    d.addEventListener('close', () => { d.remove(); resolve(d.returnValue === 'yes'); });
    d.addEventListener('click', e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act) d.close(act);
    });
    d.showModal();
  });
}

function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return '—';
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h} ${t('ч')} ${m} ${t('мин')}`;
  if (sec < 60) return `${sec} ${t('с')}`;
  return s && m < 10 ? `${m} ${t('мин')} ${s} ${t('с')}` : `${m} ${t('мин')}`;
}

function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function parseTs(ts) {
  if (typeof ts === 'number') return ts;
  const parts = String(ts || '').trim().split(':').map(Number);
  if (!parts.length || parts.some(isNaN)) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

function fmtDate(value) {
  if (!value) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return value;
  return `${+m[3]} ${MONTHS[+m[2] - 1]} ${m[1]}`;
}
function fmtTimestamp(unix) {
  if (!unix) return '';
  const d = new Date(unix * 1000);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function initials(name, email) {
  const src = (name || email || '?').trim();
  const parts = src.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || '?';
}
function toRoman(n) { return ['', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii'][n] || String(n); }
function fmtSize(bytes) {
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1).replace('.', ',') + t(' МБ');
  return Math.max(1, Math.round(bytes / 1024)) + t(' КБ');
}

/* ------------------------------------------------------------------ */
/* Иконки (линейные, 24×24)                                            */
/* ------------------------------------------------------------------ */

const ICON_PATHS = {
  list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  users: '<path d="M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20"/><circle cx="10" cy="8" r="3.5"/><path d="M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35M15.5 4.6a3.5 3.5 0 0 1 0 6.8"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  slides: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  print: '<path d="M7 9V3h10v6M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="7"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  alert: '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4M12 17h.01"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  chart: '<path d="M4 4v16h16"/><path d="m8 14 3.5-4 3 2.5L19 7"/>',
  chat: '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`;
}

/* ------------------------------------------------------------------ */
/* Словари отображения                                                 */
/* ------------------------------------------------------------------ */

const CATEGORY = {
  recall: { label: t('Воспроизведение'), hint: t('вспомнить факт или определение') },
  understanding: { label: t('Понимание'), hint: t('объяснить своими словами') },
  application: { label: t('Применение'), hint: t('перенести правило на новую ситуацию') },
  analysis: { label: t('Анализ'), hint: t('сравнить, найти причины, оценить доводы') },
};
const CATEGORY_ORDER = ['recall', 'understanding', 'application', 'analysis'];

const LEVEL = {
  level_1: { short: t('Уровень 1'), label: t('Учитель спрашивает — ученик отвечает'), cls: 'l1' },
  level_2: { short: t('Уровень 2'), label: t('Учитель ставит вопрос — ученики исследуют'), cls: 'l2' },
  level_4: { short: t('Уровень 4'), label: t('Ученики формулируют вопрос, исследуют и рефлексируют'), cls: 'l4' },
};
const LEVEL_COLOR = { level_1: 'var(--level-1)', level_2: 'var(--level-2)', level_4: 'var(--level-4)' };

const ALIGN = {
  'Strong': { label: t('Реализовано'), cls: 'good' },
  'Partial': { label: t('Частично'), cls: 'warn' },
  'Not observed': { label: t('Не наблюдалось'), cls: '' },
};

const FIELD_LABELS = {
  key_concept: 'Key concept',
  related_concept: 'Related concepts',
  global_context: 'Global context',
  statement_of_inquiry: 'Statement of inquiry',
  inquiry_questions: 'Inquiry questions',
  learning_objectives: 'Learning objectives',
  atl_skills: 'ATL skills',
  learner_profile: 'Learner profile',
  assessment_criteria: 'Assessment criteria',
  learning_experiences: 'Learning experiences',
};

const STATUS = {
  queued: { label: t('В очереди'), cls: 'info run' },
  running: { label: t('Обработка'), cls: 'info run' },
  done: { label: t('Готов'), cls: 'good' },
  error: { label: t('Ошибка'), cls: 'bad' },
};
const ROLE_LABEL = { teacher: t('Учитель'), observer: t('Методист'), admin: t('Администратор') };
const canViewAll = u => u && (u.role === 'admin' || u.role === 'observer');
const LESSON_LANGUAGES = { '': t('Не указан'), ru: t('Русский'), kk: t('Қазақша'), en: 'English', mixed: t('Смешанный') };
const REPORT_LANGUAGES = { ru: t('Русский'), kk: t('Қазақша'), en: 'English' };

const statusBadge = s => `<span class="badge ${STATUS[s]?.cls || ''}">${STATUS[s]?.label || esc(s)}</span>`;

/* ------------------------------------------------------------------ */
/* Состояние и маршрутизация                                           */
/* ------------------------------------------------------------------ */

const state = {
  user: null,
  options: null,
  lessonsScope: localGet('lessonsScope') || 'mine',
};
let pollTimer = null;
let navCleanup = [];

function localGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localSet(k, v) { try { localStorage.setItem(k, v); } catch { /* приватный режим */ } }
function localDel(k) { try { localStorage.removeItem(k); } catch { /* */ } }

function go(path) {
  if (location.hash !== '#' + path) location.hash = path;
  else route();
}

const ROUTES = [
  [/^\/login$/, viewLogin, { public: true }],
  [/^\/$/, viewLessons],
  [/^\/new$/, viewNewLesson],
  [/^\/record$/, viewRecord],
  [/^\/progress$/, viewProgress],
  [/^\/notifications$/, viewNotifications],
  [/^\/lessons\/([a-f0-9]+)$/, viewLesson],
  [/^\/users$/, viewUsers, { admin: true }],
  [/^\/account$/, viewAccount],
];

async function route() {
  clearInterval(pollTimer); pollTimer = null;
  navCleanup.forEach(fn => fn()); navCleanup = [];
  hideTip();

  const [path, qs] = (location.hash.replace(/^#/, '') || '/').split('?');
  state.query = new URLSearchParams(qs || '');
  for (const [re, view, opts = {}] of ROUTES) {
    const m = re.exec(path);
    if (!m) continue;
    if (!opts.public && !state.user) return go('/login');
    if (opts.public && state.user) return go('/');
    if (opts.admin && state.user.role !== 'admin') return go('/');
    window.scrollTo(0, 0);
    try {
      await view(...m.slice(1));
    } catch (err) {
      if (err.status === 401) return;
      renderShell('', `<div class="page"><div class="panel empty"><h2>${t('Не удалось загрузить страницу')}</h2><p>${esc(err.message)}</p><a class="btn" href="#/">${t('К списку уроков')}</a></div></div>`);
    }
    return;
  }
  go('/');
}

/* ------------------------------------------------------------------ */
/* Каркас приложения                                                   */
/* ------------------------------------------------------------------ */

function renderShell(active, content) {
  const u = state.user;
  const nav = (href, key, ic, label) =>
    `<a href="#${href}" ${active === key ? 'aria-current="page"' : ''}>${icon(ic)}<span>${label}</span></a>`;
  $('#app').className = '';
  $('#app').innerHTML = `
    <div class="shell" id="shell">
      <aside class="sidebar" aria-label="${t('Навигация')}">
        <div class="brand">
          <div class="brand-mark">MYP</div>
          <div><div class="brand-name">Lesson Analyzer</div><div class="brand-sub">${t('Анализ уроков IB MYP')}</div></div>
        </div>
        <nav class="nav">
          ${nav('/', 'lessons', 'list', t('Уроки'))}
          ${nav('/new', 'new', 'plus', t('Новый анализ'))}
          ${nav('/record', 'record', 'mic', t('Записать урок'))}
          ${nav('/progress', 'progress', 'chart', t('Динамика'))}
          <a href="#/notifications" ${active === 'notifications' ? 'aria-current="page"' : ''}>${icon('bell')}<span>${t('Уведомления')}</span><span class="nav-badge" id="unreadBadge" ${state.unread ? '' : 'hidden'}>${state.unread || ''}</span></a>
          <a href="#/record" class="rec-indicator" id="recIndicator" hidden><span class="rec-dot recording"></span>${t('Идёт запись')} <span class="mono" id="recIndicatorTime">00:00</span></a>
          ${u.role === 'admin' ? `<div class="nav-section">${t('Администрирование')}</div>${nav('/users', 'users', 'users', t('Пользователи'))}` : ''}
        </nav>
        <div class="sidebar-foot">
          <div class="user-chip">
            <div class="avatar">${esc(initials(u.name, u.email))}</div>
            <div style="min-width:0">
              <div class="name">${esc(u.name || u.email)}</div>
              <div class="role">${ROLE_LABEL[u.role] || ''}</div>
            </div>
          </div>
          ${langSwitcher('in-sidebar')}
          <div class="foot-links">
            <a href="#/account" ${active === 'account' ? 'aria-current="page"' : ''}>${t('Профиль')}</a>
            <button type="button" id="logoutBtn">${t('Выйти')}</button>
          </div>
        </div>
      </aside>
      <div class="scrim" id="scrim"></div>
      <div class="main">
        <header class="topbar">
          <button class="btn ghost icon-btn" id="menuBtn" aria-label="${t('Открыть меню')}">${icon('menu')}</button>
          <div class="brand-mark">MYP</div>
          <div class="brand-name">Lesson Analyzer</div>
          <a href="#/notifications" class="top-bell" id="topBell" aria-label="${t('Уведомления')}" ${state.unread ? '' : 'hidden'}>${icon('bell')}<span class="nav-badge" id="unreadBadgeTop">${state.unread || ''}</span></a>
          <a href="#/record" class="rec-indicator top" id="recIndicatorTop" hidden><span class="rec-dot recording"></span><span class="mono" id="recIndicatorTopTime">00:00</span></a>
        </header>
        <main id="view">${content}</main>
      </div>
    </div>`;
  const shell = $('#shell');
  $('#menuBtn').onclick = () => shell.classList.add('nav-open');
  $('#scrim').onclick = () => shell.classList.remove('nav-open');
  $$('.nav a, .foot-links a').forEach(a => a.addEventListener('click', () => shell.classList.remove('nav-open')));
  updateRecIndicator();
  $('#logoutBtn').onclick = async () => {
    if (recorder.active && ['recording', 'paused', 'interrupted', 'uploading'].includes(recorder.active.state)) {
      return toast(t('Сначала завершите запись урока.'), 'bad');
    }
    await api('POST', '/api/auth/logout').catch(() => {});
    state.user = null;
    go('/login');
  };
}

/* ------------------------------------------------------------------ */
/* Подсказки на графиках                                               */
/* ------------------------------------------------------------------ */

function showTip(target, x, y) {
  const tip = $('#tooltip');
  tip.innerHTML = target.dataset.tip;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let left = x + 14, top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tip.style.left = Math.max(8, left) + 'px';
  tip.style.top = Math.max(8, top) + 'px';
}
function hideTip() { const tip = $('#tooltip'); if (tip) tip.hidden = true; }
document.addEventListener('mousemove', e => {
  const el = e.target.closest?.('[data-tip]');
  if (el) showTip(el, e.clientX, e.clientY); else hideTip();
});
document.addEventListener('focusin', e => {
  const el = e.target.closest?.('[data-tip]');
  if (el) { const r = el.getBoundingClientRect(); showTip(el, r.left + r.width / 2, r.bottom); }
});
document.addEventListener('focusout', hideTip);
document.addEventListener('scroll', hideTip, true);

/* ------------------------------------------------------------------ */
/* Вход                                                                */
/* ------------------------------------------------------------------ */

async function viewLogin() {
  const me = await api('GET', '/api/auth/me').catch(() => ({}));
  $('#app').className = '';
  $('#app').innerHTML = `
    <div class="auth-wrap">
      <div class="auth-card">
        <div class="brand">
          <div class="brand-mark">MYP</div>
          <div><div class="brand-name">Lesson Analyzer</div><div class="brand-sub">${t('Анализ уроков IB MYP')}</div></div>
        </div>
        <form class="panel" id="loginForm" novalidate>
          <h1>${t('Вход')}</h1>
          <p class="muted" style="margin-bottom:18px">${t('Используйте учётную запись, выданную администратором.')}</p>
          ${me.needs_setup ? `<div class="callout warn" style="margin-bottom:16px">${icon('alert')}<div>${t('Учётных записей пока нет. Задайте переменные окружения ADMIN_EMAIL и ADMIN_PASSWORD на сервере и перезапустите его.')}</div></div>` : ''}
          <div class="stack">
            <div class="field"><label for="email">Email</label><input class="input" id="email" name="email" type="email" autocomplete="username" required></div>
            <div class="field"><label for="password">${t('Пароль')}</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required></div>
            <div class="form-error" id="loginError" role="alert"></div>
            <button class="btn primary lg" style="width:100%" type="submit">${t('Войти')}</button>
          </div>
        </form>
        <p class="auth-foot">${t('Забыли пароль? Обратитесь к администратору.')}</p>
        <div style="display:flex;justify-content:center;margin-top:14px">${langSwitcher()}</div>
      </div>
    </div>`;
  $('#email').focus();
  $('#loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type=submit]');
    const errEl = $('#loginError');
    errEl.textContent = '';
    const email = $('#email').value.trim(), password = $('#password').value;
    if (!email || !password) { errEl.textContent = t('Введите email и пароль.'); return; }
    btn.disabled = true;
    try {
      const data = await api('POST', '/api/auth/login', { email, password });
      state.user = data.user;
      let local = null;
      try { local = localStorage.getItem('uiLang'); } catch { /* */ }
      if (local && local !== data.user.ui_language) api('POST', '/api/auth/preferences', { ui_language: local }).catch(() => {});
      else if (!local && data.user.ui_language !== LANG) return setUiLang(data.user.ui_language, { save: false });
      const me = await api('GET', '/api/auth/me').catch(() => ({}));
      state.unread = me.unread || 0; state.emailAvailable = !!me.email_available;
      go('/');
    } catch (err) {
      errEl.textContent = err.message;
      btn.disabled = false;
    }
  });
}

/* ------------------------------------------------------------------ */
/* Список уроков                                                       */
/* ------------------------------------------------------------------ */

async function viewLessons() {
  const isAdmin = canViewAll(state.user);
  const scope = isAdmin ? state.lessonsScope : 'mine';
  renderShell('lessons', `
    <div class="page">
      <div class="page-head">
        <div><h1>${t('Уроки')}</h1><p class="lede">${t('История проанализированных уроков. Откройте урок, чтобы посмотреть отчёт.')}</p></div>
        <div class="head-actions"><a class="btn primary" href="#/new">${icon('plus')}${t('Новый анализ')}</a></div>
      </div>
      <div id="lessonsBody"><div class="panel panel-pad stack"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:70%"></div></div></div>
    </div>`);

  const { lessons } = await api('GET', `/api/lessons?scope=${scope}`);
  const body = $('#lessonsBody');

  if (!lessons.length && scope === 'mine') {
    body.innerHTML = `
      <div class="panel empty">
        <h2>${t('Пока нет ни одного урока')}</h2>
        <p>${t('Загрузите аудиозапись урока и план — через несколько минут здесь появится отчёт: время речи, вопросы учителя, уровни inquiry и соответствие плану.')}</p>
        <a class="btn primary" href="#/new">${icon('plus')}${t('Проанализировать урок')}</a>
        ${isAdmin ? `<p style="margin-top:18px"><button class="btn ghost sm" id="seeAll">${t('Показать уроки всех учителей')}</button></p>` : ''}
      </div>`;
    $('#seeAll')?.addEventListener('click', () => { state.lessonsScope = 'all'; localSet('lessonsScope', 'all'); viewLessons(); });
    return;
  }

  const subjects = [...new Set(lessons.map(l => l.subject).filter(Boolean))].sort();
  body.innerHTML = `
    <div class="toolbar">
      <input class="input" id="q" type="search" placeholder="${t('Поиск по теме, учителю, предмету')}" aria-label="${t('Поиск')}">
      <select class="select" id="fSubject" aria-label="${t('Предмет')}"><option value="">${t('Все предметы')}</option>${subjects.map(s => `<option>${esc(s)}</option>`).join('')}</select>
      <select class="select" id="fStatus" aria-label="${t('Статус')}"><option value="">${t('Все статусы')}</option>${Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select>
      ${isAdmin ? `<div class="seg" role="group" aria-label="${t('Чьи уроки')}" style="margin-left:auto">
        <button type="button" data-scope="mine" aria-pressed="${scope === 'mine'}">${t('Мои')}</button>
        <button type="button" data-scope="all" aria-pressed="${scope === 'all'}">${t('Все учителя')}</button></div>` : ''}
    </div>
    <div class="panel lessons-table"><div class="table-wrap"><table class="data">
      <thead><tr>
        <th>${t('Дата')}</th><th>${t('Урок')}</th><th>${t('Учитель')}</th><th class="num">${t('Длительность')}</th>
        <th class="num">${t('Речь учителя')}</th><th class="num">${t('Вопросы')}</th><th>${t('Статус')}</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table></div></div>
    <div class="lesson-cards" id="cards"></div>
    <p class="subtle" id="noMatch" style="display:none;padding:24px 4px">${t('Ничего не найдено. Измените условия поиска.')}</p>`;

  $$('[data-scope]').forEach(b => b.addEventListener('click', () => {
    state.lessonsScope = b.dataset.scope; localSet('lessonsScope', b.dataset.scope); viewLessons();
  }));

  const title = l => l.lesson_title || l.subject || t('Урок без названия');
  const sub = l => [l.subject && l.lesson_title ? l.subject : '', l.grade].filter(Boolean).join(' · ');
  const date = l => fmtDate(l.lesson_date) || fmtTimestamp(l.created_at);
  const qText = s => s ? `${s.question_count}${s.higher_order_pct != null ? ` <span class="subtle">· ${s.higher_order_pct}% ${t('выс.')}</span>` : ''}` : '—';
  const progress = l => (l.status === 'running' && l.step_total) ? `<div class="cell-sub">${t('Этап {n} из {total}', { n: l.step, total: l.step_total })}</div>` : '';

  function render() {
    const q = $('#q').value.trim().toLowerCase();
    const fs = $('#fSubject').value, fst = $('#fStatus').value;
    const list = lessons.filter(l =>
      (!fs || l.subject === fs) && (!fst || l.status === fst) &&
      (!q || [l.lesson_title, l.subject, l.teacher_name, l.grade, l.owner_name].join(' ').toLowerCase().includes(q)));
    $('#noMatch').style.display = list.length ? 'none' : 'block';
    $('#rows').innerHTML = list.map(l => {
      const s = l.summary;
      return `<tr class="clickable" data-id="${l.id}" tabindex="0">
        <td class="nowrap">${esc(date(l))}</td>
        <td><div class="cell-title">${esc(title(l))}${l.comment_count ? ` <span class="tag" title="${t('Комментарии')}" style="vertical-align:1px">${l.comment_count} ${plural(l.comment_count, t('коммент.'), t('коммент.'), t('коммент.'))}</span>` : ''}</div>${sub(l) ? `<div class="cell-sub">${esc(sub(l))}</div>` : ''}</td>
        <td>${esc(l.teacher_name || l.owner_name || '')}${scope === 'all' && l.owner_name && l.owner_name !== l.teacher_name ? `<div class="cell-sub">${t('загрузил(а)')}: ${esc(l.owner_name)}</div>` : ''}</td>
        <td class="num">${s ? fmtDuration(s.duration_seconds) : '—'}</td>
        <td class="num">${s && s.teacher_pct != null ? Math.round(s.teacher_pct) + '%' : '—'}</td>
        <td class="num">${qText(s)}</td>
        <td>${statusBadge(l.status)}${progress(l)}</td>
      </tr>`;
    }).join('');
    $('#cards').innerHTML = list.map(l => {
      const s = l.summary;
      return `<a class="panel lesson-card" href="#/lessons/${l.id}">
        <div class="row"><div><div class="cell-title">${esc(title(l))}</div><div class="cell-sub">${esc([date(l), sub(l), l.teacher_name].filter(Boolean).join(' · '))}</div></div>${statusBadge(l.status)}</div>
        ${s ? `<div class="stats"><span>${fmtDuration(s.duration_seconds)}</span><span>${t('Учитель')} ${Math.round(s.teacher_pct ?? 0)}%</span><span>${t('Вопросов')} ${s.question_count}</span></div>` : ''}
      </a>`;
    }).join('');
  }
  render();
  ['input', 'change'].forEach(ev => ['#q', '#fSubject', '#fStatus'].forEach(id => $(id).addEventListener(ev, render)));
  $('#rows').addEventListener('click', e => { const tr = e.target.closest('tr[data-id]'); if (tr) go('/lessons/' + tr.dataset.id); });
  $('#rows').addEventListener('keydown', e => { const tr = e.target.closest('tr[data-id]'); if (tr && e.key === 'Enter') go('/lessons/' + tr.dataset.id); });

  // Автообновление, пока есть уроки в обработке.
  if (lessons.some(l => l.status === 'queued' || l.status === 'running')) {
    pollTimer = setInterval(async () => {
      const fresh = await api('GET', `/api/lessons?scope=${scope}`).catch(() => null);
      if (!fresh) return;
      lessons.splice(0, lessons.length, ...fresh.lessons);
      render();
      if (!lessons.some(l => l.status === 'queued' || l.status === 'running')) clearInterval(pollTimer);
    }, 5000);
  }
}

/* ------------------------------------------------------------------ */
/* Новый анализ                                                        */
/* ------------------------------------------------------------------ */

async function loadOptions() {
  if (!state.options) state.options = await api('GET', '/api/form-options');
  return state.options;
}

const DRAFT_KEY = 'lessonDraft';
const DRAFT_FIELDS = ['lesson_title', 'subject', 'grade', 'subject_key', 'lesson_language', 'report_language', 'key_concept', 'global_context',
  'statement_of_inquiry', 'inquiry_questions', 'learning_objectives', 'atl_skills_detail', 'learning_experiences'];

function dropzone({ name, title, sub, accept, iconName, required }) {
  return `<label class="dropzone" data-dz="${name}">
    <input type="file" name="${name}" accept="${accept}" ${required ? 'required' : ''}>
    <span class="dz-icon">${icon(iconName)}</span>
    <span style="min-width:0"><span class="dz-title">${title}</span><br><span class="dz-sub">${sub}</span></span>
  </label>`;
}

function chipGroup(group, items) {
  return `<div class="chips">${items.map(it => {
    const v = typeof it === 'string' ? it : it.value, l = typeof it === 'string' ? it : it.label;
    return `<label class="chip-check"><input type="checkbox" data-group="${group}" value="${esc(v)}"><span>${esc(l)}</span></label>`;
  }).join('')}</div>`;
}

async function viewNewLesson() {
  const o = await loadOptions();
  const subjectOptions = Object.entries(o.subjects).map(([k, v]) => `<option value="${esc(k)}">${esc(LANG === 'en' ? v.label : `${subjectLabel(v)} · ${v.label}`)}</option>`).join('');
  const sel = (name, items) => `<select class="select" id="${name}" name="${name}"><option value="">${t('Не выбрано')}</option>${items.map(v => `<option>${esc(v)}</option>`).join('')}</select>`;

  renderShell('new', `
    <div class="page narrow">
      <div class="page-head">
        <div><h1>${t('Новый анализ урока')}</h1>
        <p class="lede">${t('Загрузите запись и заполните план урока. Обработка занимает 5–15 минут; страницу можно закрыть — отчёт появится в списке уроков.')}</p></div>
      </div>
      <form id="lessonForm" novalidate>
        <section class="form-section">
          <div class="form-section-head"><span class="step-no">01</span><h2>${t('Запись урока')}</h2>
            <p>${t('Обязательна запись с микрофона учителя. Вторая запись из центра класса заметно повышает точность разделения реплик.')}</p></div>
          <div class="stack">
            <div id="recSlot" hidden></div>
            ${dropzone({ name: 'teacher_track', title: t('Запись учителя'), sub: t('Петличный микрофон или телефон у учителя · mp3, m4a, wav, ogg · или <a href="#/record">запишите урок на сайте</a>'), accept: 'audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.flac', iconName: 'mic', required: true })}
            <div id="recOffer"></div>
            ${dropzone({ name: 'classroom_track', title: t('Запись класса <span class="opt">— по желанию</span>'), sub: t('Телефон в центре класса'), accept: 'audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.flac', iconName: 'mic' })}
            ${dropzone({ name: 'pptx', title: t('Презентация <span class="opt">— по желанию</span>'), sub: t('Файл .pptx, используется для привязки слайдов к ходу урока'), accept: '.pptx', iconName: 'slides' })}
            <div class="callout" id="singleTrackNote">${icon('info')}<div>${t('Если загружена только запись учителя, роли «учитель / ученик» определяются по смыслу речи. Это менее точно, чем при двух записях, — в отчёте будет соответствующая пометка.')}</div></div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section-head"><span class="step-no">02</span><h2>${t('Об уроке')}</h2>
            <p>${t('Эти данные попадут в заголовок отчёта и помогут найти урок в истории.')}</p></div>
          <div class="form-grid">
            <div class="field span-2"><label for="lesson_title">${t('Тема урока')}</label><input class="input" id="lesson_title" name="lesson_title" placeholder="${t('Например: Фотосинтез и дыхание клетки')}"></div>
            <div class="field"><label for="subject_key">${t('Предметная группа MYP')}</label><select class="select" id="subject_key" name="subject_key">${subjectOptions}</select></div>
            <div class="field"><label for="subject">${t('Предмет')}</label><input class="input" id="subject" name="subject" placeholder="Biology, English B…"></div>
            <div class="field"><label for="grade">${t('Класс')} <span class="opt">/ MYP year</span></label><input class="input" id="grade" name="grade" placeholder="MYP 3, 8A…"></div>
            <div class="field"><label for="lesson_date">${t('Дата урока')}</label><input class="input" id="lesson_date" name="lesson_date" type="date" value="${todayIso()}"></div>
            <div class="field span-2"><label for="teacher_name">${t('Учитель')}</label><input class="input" id="teacher_name" name="teacher_name" value="${esc(state.user.name)}"></div>
            <div class="field"><label for="lesson_language">${t('Язык урока')}</label><select class="select" id="lesson_language" name="lesson_language">${Object.entries(LESSON_LANGUAGES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
              <span class="help">${t('Помогает точнее распознать речь.')}</span></div>
            <div class="field"><label for="report_language">${t('Язык выводов и рекомендаций')}</label><select class="select" id="report_language" name="report_language">${Object.entries(REPORT_LANGUAGES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
              <span class="help">${t('Цитаты из урока остаются на языке оригинала.')}</span></div>
            <div class="span-2" id="observabilityWarn"></div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section-head"><span class="step-no">03</span><h2>${t('План урока')}</h2>
            <p>${t('Из unit planner. С этими полями отчёт сравнит запланированное с тем, что реально прозвучало на уроке. Можно заполнить частично.')}</p></div>
          <div class="form-grid">
            ${plannerBox()}
            <div class="field"><label for="key_concept">Key concept</label>${sel('key_concept', o.key_concepts)}<span class="help" id="kcHint"></span></div>
            <div class="field"><label for="global_context">Global context</label>${sel('global_context', o.global_contexts)}</div>
            <div class="field span-2"><span class="label">Related concepts</span><div id="relatedConcepts"></div></div>
            <div class="field span-2"><label for="statement_of_inquiry">Statement of inquiry</label><textarea class="textarea" id="statement_of_inquiry" name="statement_of_inquiry" rows="2"></textarea></div>
            <div class="field span-2"><label for="inquiry_questions">Inquiry questions</label><textarea class="textarea" id="inquiry_questions" name="inquiry_questions" rows="3" placeholder="Factual: …&#10;Conceptual: …&#10;Debatable: …"></textarea></div>
            <div class="field span-2"><label for="learning_objectives">Learning objectives</label><textarea class="textarea" id="learning_objectives" name="learning_objectives" rows="2"></textarea></div>
            <div class="field span-2"><span class="label">Assessment criteria</span><div id="assessmentCriteria"></div></div>
            <div class="field span-2"><span class="label">ATL skills</span>
              ${chipGroup('atl', Object.values(o.atl_skill_clusters).map(c => c.label))}
              <input class="input" name="atl_skills_detail" style="margin-top:8px" placeholder="${t('Уточнение, например: critical thinking — сравнение доказательств')}">
            </div>
            <div class="field span-2"><span class="label">Learner profile</span>${chipGroup('learner', o.learner_profile_attributes)}</div>
            <div class="field span-2"><label for="learning_experiences">Learning experiences</label><textarea class="textarea" id="learning_experiences" name="learning_experiences" rows="3" placeholder="${t('Что делают ученики на уроке: эксперимент в группах, обсуждение, презентация…')}"></textarea></div>
          </div>
        </section>

        <div class="submit-bar">
          <div class="upload-state" id="uploadState"></div>
          <button type="button" class="btn ghost" id="clearDraft">${t('Очистить форму')}</button>
          <button type="submit" class="btn primary lg" id="submitBtn">${t('Начать анализ')}</button>
        </div>
      </form>
    </div>`);

  const form = $('#lessonForm');

  function refreshSubject() {
    const subj = o.subjects[$('#subject_key').value];
    if (!subj) return;
    const groups = subj.related_concept_groups;
    if (groups) {
      $('#relatedConcepts').innerHTML = `<div class="seg" role="group" aria-label="${t('Дисциплина')}" id="rcGroups" style="margin-bottom:8px">
          <button type="button" data-rcg="" aria-pressed="true">${t('Все')}</button>
          ${Object.keys(groups).map(g => `<button type="button" data-rcg="${esc(g)}" aria-pressed="false">${esc(g)}</button>`).join('')}
        </div>${chipGroup('related', subj.related_concepts)}`;
      $('#rcGroups').addEventListener('click', e => {
        const b = e.target.closest('[data-rcg]'); if (!b) return;
        $$('#rcGroups [data-rcg]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
        const allowed = b.dataset.rcg ? new Set(groups[b.dataset.rcg]) : null;
        $$('#relatedConcepts .chip-check').forEach(ch => {
          const inp = $('input', ch);
          ch.hidden = !!allowed && !allowed.has(inp.value) && !inp.checked;
        });
      });
    } else if (subj.related_concepts.length) {
      $('#relatedConcepts').innerHTML = chipGroup('related', subj.related_concepts);
    } else {
      $('#relatedConcepts').innerHTML = `<p class="help">${esc(subj.related_concepts_note || t('Для этого предмета список не задан.'))}</p>`;
    }
    $('#assessmentCriteria').innerHTML = `<div class="chips">${subj.assessment_criteria.map(c => {
      const tip = `<b>${esc(c.code)} · ${esc(c.label)}</b>${(c.strands || []).map((st, i) => `<br>${toRoman(i + 1)}. ${esc(st)}`).join('')}${c.audio === 'none' ? t('<br><br>По аудиозаписи не наблюдается.') : ''}`;
      return `<label class="chip-check" data-tip="${esc(tip)}"><input type="checkbox" data-group="criteria" value="${esc(`Criterion ${c.code}: ${c.label}`)}"><span>${esc(c.code)} · ${esc(c.label)}${c.audio === 'none' ? t('&nbsp;<span class="subtle" aria-label="не наблюдается по аудио">○</span>') : ''}</span></label>`;
    }).join('')}</div><span class="help">${t('Наведите на критерий, чтобы увидеть strands; ○ — по аудио не наблюдается. Если ни один не выбран, анализ пройдёт по всем критериям предмета.')}</span>`;
    const kc = subj.key_concepts_emphasized || [];
    $('#kcHint').textContent = kc.length ? `${t('Ключевые для предмета')}: ${kc.join(', ')}` : '';
    const note = observabilityNote(subj);
    $('#observabilityWarn').innerHTML = note ? `<div class="callout warn">${icon('alert')}<div>${esc(note.trim())}</div></div>` : '';
  }

  // Черновик формы: текстовые поля и отметки сохраняются в браузере,
  // чтобы случайное закрытие вкладки не стирало заполненный план.
  function saveDraft() {
    const d = {};
    DRAFT_FIELDS.forEach(n => { d[n] = form.elements[n]?.value ?? ''; });
    d.checks = $$('input[data-group]:checked').map(i => i.dataset.group + '|' + i.value);
    localSet(DRAFT_KEY, JSON.stringify(d));
  }
  function loadDraft() {
    let d; try { d = JSON.parse(localGet(DRAFT_KEY) || 'null'); } catch { d = null; }
    if (!d) return;
    if (d.subject_key && o.subjects[d.subject_key]) form.elements.subject_key.value = d.subject_key;
    refreshSubject();
    DRAFT_FIELDS.forEach(n => { if (n !== 'subject_key' && d[n] != null && form.elements[n]) form.elements[n].value = d[n]; });
    (d.checks || []).forEach(k => {
      const [g, ...rest] = k.split('|'); const v = rest.join('|');
      $$(`input[data-group="${g}"]`).find(i => i.value === v)?.click();
    });
  }

  $('#subject_key').addEventListener('change', () => { refreshSubject(); saveDraft(); });
  refreshSubject();
  loadDraft();
  form.addEventListener('input', saveDraft);
  form.addEventListener('change', e => { if (e.target.dataset.group) saveDraft(); });

  $('#clearDraft').addEventListener('click', async () => {
    if (!await confirmDialog({ title: t('Очистить форму?'), text: t('Все заполненные поля и выбранные файлы будут сброшены.'), confirm: t('Очистить') })) return;
    localDel(DRAFT_KEY);
    viewNewLesson();
  });

  // Файловые поля
  $$('.dropzone').forEach(dz => {
    const input = $('input', dz);
    const title = $('.dz-title', dz).innerHTML, sub = $('.dz-sub', dz).innerHTML;
    const update = () => {
      const f = input.files[0];
      dz.classList.toggle('has-file', !!f);
      $('.dz-title', dz).innerHTML = f ? esc(f.name) : title;
      $('.dz-sub', dz).innerHTML = f ? `${fmtSize(f.size)} · ${t('нажмите, чтобы заменить')}` : sub;
      $('.dz-clear', dz)?.remove();
      if (f) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'btn ghost sm dz-clear'; b.textContent = t('Убрать');
        b.onclick = e => { e.preventDefault(); input.value = ''; update(); };
        dz.appendChild(b);
      }
      if (input.name === 'classroom_track') $('#singleTrackNote').style.display = f ? 'none' : '';
    };
    input.addEventListener('change', update);
    ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove('drag')));
    dz.addEventListener('drop', e => {
      e.preventDefault();
      if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; update(); }
    });
  });

  bindPlanner(form, o, refreshSubject, saveDraft);

  // Запись, сделанная на сайте, вместо файла учителя
  let recordingId = null;
  function useRecording(rec) {
    recordingId = rec.id;
    $('#recSlot').hidden = false;
    $('#recSlot').innerHTML = `<div class="dropzone has-file" style="cursor:default">
      <span class="dz-icon">${icon('mic')}</span>
      <span style="min-width:0"><span class="dz-title">${t('Запись с сайта')} · ${fmtDuration(rec.duration_seconds)}</span><br><span class="dz-sub">${t('Сделана')} ${esc(fmtTimestamp(rec.created_at))}</span></span>
      <button type="button" class="btn ghost sm dz-clear" id="recUnset">${t('Загрузить файл вместо неё')}</button></div>`;
    $('[data-dz="teacher_track"]').hidden = true;
    $('#recOffer').innerHTML = '';
    $('#recUnset').onclick = () => { recordingId = null; $('#recSlot').hidden = true; $('[data-dz="teacher_track"]').hidden = false; offerRecordings(); };
  }
  async function offerRecordings() {
    const list = (await api('GET', '/api/recordings').catch(() => ({ recordings: [] }))).recordings.filter(r => r.status === 'ready');
    if (!list.length || recordingId) { $('#recOffer').innerHTML = ''; return; }
    const r0 = list[0];
    $('#recOffer').innerHTML = `<div class="callout info">${icon('mic')}<div style="flex:1">${t('Есть готовая запись с сайта от {date} ({duration}).', { date: esc(fmtTimestamp(r0.created_at)), duration: fmtDuration(r0.duration_seconds) })}
      <button type="button" class="btn sm" id="recUse" style="margin-left:6px">${t('Использовать')}</button></div></div>`;
    $('#recUse').onclick = () => useRecording(r0);
  }
  const recParam = state.query?.get('rec');
  if (recParam) {
    api('GET', `/api/recordings/${recParam}`).then(d => {
      if (d.recording.status === 'ready') useRecording(d.recording);
      else { toast(t('Эта запись ещё не готова или уже использована.'), 'bad'); offerRecordings(); }
    }).catch(() => offerRecordings());
  } else offerRecordings();

  form.addEventListener('submit', e => {
    e.preventDefault();
    const teacher = form.elements.teacher_track.files[0];
    if (!teacher && !recordingId) {
      toast(t('Добавьте запись учителя — без неё анализ невозможен.'), 'bad');
      $('[data-dz="teacher_track"]').scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    const fd = new FormData(form);
    const checked = g => $$(`input[data-group="${g}"]:checked`).map(i => i.value);
    fd.set('related_concept', checked('related').join('; '));
    fd.set('assessment_criteria', checked('criteria').join('; '));
    fd.set('learner_profile', checked('learner').join(', '));
    const atl = checked('atl').join(', ');
    const atlDetail = String(fd.get('atl_skills_detail') || '').trim();
    fd.set('atl_skills', atlDetail ? (atl ? `${atl} — ${atlDetail}` : atlDetail) : atl);
    fd.delete('atl_skills_detail');
    for (const k of ['teacher_track', 'classroom_track', 'pptx']) {
      const f = fd.get(k); if (f && f.size === 0) fd.delete(k);
    }
    if (recordingId && !teacher) { fd.delete('teacher_track'); fd.set('recording_id', recordingId); }

    const btn = $('#submitBtn'), st = $('#uploadState');
    btn.disabled = true;
    st.innerHTML = `${t('Загрузка файлов…')} <span id="pct">0%</span><div class="progress"><i id="bar"></i></div>`;

    // XHR, а не fetch: нужен прогресс загрузки больших аудиофайлов.
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/lessons');
    xhr.upload.onprogress = ev => {
      if (!ev.lengthComputable) return;
      const p = Math.round(100 * ev.loaded / ev.total);
      $('#pct') && ($('#pct').textContent = p + '%');
      $('#bar') && ($('#bar').style.width = p + '%');
      if (p >= 100) st.firstChild.textContent = t('Файлы загружены, запускаем анализ… ');
    };
    xhr.onload = () => {
      let data = null; try { data = JSON.parse(xhr.responseText); } catch { /* */ }
      if (xhr.status >= 200 && xhr.status < 300 && data?.id) {
        localDel(DRAFT_KEY);
        toast(t('Анализ запущен. Можно закрыть страницу — отчёт сохранится.'));
        go('/lessons/' + data.id);
      } else {
        if (xhr.status === 401) { state.user = null; return go('/login'); }
        st.innerHTML = `<span style="color:var(--bad)">${esc(errorText(data, xhr.status))}</span>`;
        btn.disabled = false;
      }
    };
    xhr.onerror = () => {
      st.innerHTML = `<span style="color:var(--bad)">${t('Соединение прервалось во время загрузки. Проверьте интернет и попробуйте ещё раз.')}</span>`;
      btn.disabled = false;
    };
    xhr.send(fd);
  });
}

/* ------------------------------------------------------------------ */
/* Урок: обработка и отчёт                                             */
/* ------------------------------------------------------------------ */

const STEP_NAMES = [
  t('Синхронизация аудиодорожек'), t('Расшифровка речи'), t('Разметка реплик учителя и учеников'),
  t('Анализ вопросов учителя'), t('Определение уровней inquiry'), t('Сравнение плана и урока'),
  t('Анализ критериев оценивания'), t('Формулирование выводов'), t('Подготовка отчёта'),
];

async function viewLesson(id) {
  await loadOptions().catch(() => {});
  const { lesson } = await api('GET', `/api/lessons/${id}`);
  api('POST', '/api/notifications/read', { lesson_id: id }).then(r => setUnread(r.unread)).catch(() => {});
  const title = lesson.lesson_title || lesson.subject || t('Урок без названия');
  const subjDef = state.options?.subjects?.[lesson.subject_key];
  const subjLabel = subjDef ? subjectLabel(subjDef) : '';
  const meta = [
    lesson.teacher_name,
    fmtDate(lesson.lesson_date),
    lesson.subject && lesson.lesson_title ? lesson.subject : '',
    lesson.grade,
    subjLabel,
  ].filter(Boolean);
  const done = lesson.status === 'done';

  renderShell('lessons', `
    <div class="page">
      <div class="page-head">
        <div style="min-width:0">
          <div class="crumbs"><a href="#/">${t('Уроки')}</a> / ${statusBadge(lesson.status)}</div>
          <h1>${esc(title)}</h1>
          <div class="meta-line">${meta.map(m => `<span>${esc(m)}</span>`).join('<span class="subtle">·</span>')}</div>
        </div>
        <div class="head-actions">
          ${done ? `<a class="btn" href="/api/lessons/${id}/report.docx">${icon('download')}Word</a>
                    <button class="btn" id="printBtn">${icon('print')}${t('Печать')} / PDF</button>` : ''}
          ${lesson.can_delete && (lesson.status === 'done' || lesson.status === 'error') ? `<button class="btn ghost icon-btn" id="deleteBtn" aria-label="${t('Удалить урок')}" data-tip="${t('Удалить урок')}">${icon('trash')}</button>` : ''}
        </div>
      </div>
      <div id="lessonBody"></div>
    </div>`);

  $('#printBtn')?.addEventListener('click', () => window.print());
  $('#deleteBtn')?.addEventListener('click', async () => {
    const ok = await confirmDialog({ title: t('Удалить урок?'), text: t('Отчёт, расшифровка и все данные урока будут удалены без возможности восстановления.'), confirm: t('Удалить'), danger: true });
    if (!ok) return;
    try { await api('DELETE', `/api/lessons/${id}`); toast(t('Урок удалён.')); go('/'); }
    catch (err) { toast(err.message, 'bad'); }
  });

  if (done) renderReport(lesson);
  else renderProcessing(lesson);
}

function renderProcessing(lesson) {
  const body = $('#lessonBody');
  const isErr = lesson.status === 'error';
  const current = lesson.step || 0;
  const log = (lesson.progress_log || []).map(e => e.msg).join('\n');

  body.innerHTML = `
    <div class="grid-2" style="grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)">
      <div class="panel">
        <div class="panel-head"><h2>${isErr ? t('Обработка остановлена') : lesson.status === 'queued' ? t('Урок в очереди') : t('Идёт анализ')}</h2></div>
        <div class="panel-body">
          ${isErr ? `<div class="callout bad" style="margin-bottom:14px">${icon('alert')}<div>${esc(t(lesson.error_public || 'Произошла ошибка.'))}</div></div>` : ''}
          <ol class="steps">
            ${STEP_NAMES.map((n, i) => {
              const idx = i + 1;
              const cls = idx < current ? 'done' : idx === current ? (isErr ? 'failed' : 'active') : '';
              return `<li class="${cls}"><span class="mark">${cls === 'done' ? icon('check') : cls === 'failed' ? icon('x') : ''}</span>${esc(n)}</li>`;
            }).join('')}
          </ol>
          ${isErr && lesson.can_retry ? `<div style="margin-top:14px;display:flex;gap:8px"><button class="btn primary" id="retryBtn">${icon('refresh')}${t('Повторить анализ')}</button></div>
                     <p class="subtle" style="font-size:12.5px;margin-top:8px">${t('Повторный запуск продолжит с последнего завершённого этапа — расшифровка не будет оплачена повторно.')}</p>` : ''}
        </div>
      </div>
      <div class="stack">
        ${!isErr ? `<div class="callout info">${icon('info')}<div>${t('Эту страницу можно закрыть: анализ выполняется на сервере, а готовый отчёт появится в списке уроков. Обычно это занимает 5–15 минут в зависимости от длины записи.')}</div></div>` : ''}
        <div class="panel panel-pad">
          <details class="disclosure"><summary>${t('Технический журнал')}</summary><pre class="log">${esc(log || t('Пока пусто.'))}</pre></details>
          ${lesson.error_detail ? `<details class="disclosure" style="margin-top:10px"><summary>${t('Подробности ошибки (видны администратору)')}</summary><pre class="log">${esc(lesson.error_detail)}</pre></details>` : ''}
        </div>
      </div>
    </div>`;

  $('#retryBtn')?.addEventListener('click', async () => {
    try { await api('POST', `/api/lessons/${lesson.id}/retry`); viewLesson(lesson.id); }
    catch (err) { toast(err.message, 'bad'); }
  });

  if (!isErr) {
    pollTimer = setInterval(async () => {
      const data = await api('GET', `/api/lessons/${lesson.id}`).catch(() => null);
      if (!data) return;
      const l = data.lesson;
      if (l.status !== lesson.status || l.step !== lesson.step) {
        clearInterval(pollTimer);
        if (l.status === 'done') { toast(t('Отчёт готов.')); viewLesson(l.id); }
        else if (l.status === 'error') viewLesson(l.id);
        else { lesson = l; renderProcessing(l); }
      }
    }, 3000);
  }
}

function renderReport(lesson) {
  const r = lesson.results || {};
  const tt = r.talk_time || {};
  const s = r.summary || {};
  const questions = r.questions || [];
  const episodes = r.inquiry_episodes || [];
  const rows = r.alignment_rows || [];
  const refl = r.reflection || {};
  const utts = r.utterances || [];
  const duration = tt.total_duration_seconds || (utts.length ? utts[utts.length - 1].end : 0);
  const ac = s.alignment_counts || {};
  const alignTotal = rows.length;

  const tabs = [
    ['summary', t('Сводка')],
    ['plan', t('План и факт'), alignTotal],
    ...((r.criteria_rows || []).length ? [['criteria', t('Критерии'), r.criteria_rows.length]] : []),
    ['questions', t('Вопросы'), questions.length],
    ['inquiry', 'Inquiry', episodes.length],
    ['transcript', t('Расшифровка'), utts.length],
    ['discussion', t('Обсуждение'), 0],
    ['method', t('Методология')],
  ];

  $('#lessonBody').innerHTML = `
    <p class="draft-note">${icon('info')}${t('Черновик, подготовленный ИИ. Проверьте выводы перед обсуждением с учителем или коучем.')}</p>

    <div class="kpis">
      <div class="panel kpi"><div class="k-label">${t('Длительность записи')}</div><div class="k-value">${fmtDuration(duration)}</div>
        <div class="k-note">${tt.teacher_utterance_count ?? 0} ${t('реплик учителя')} · ${tt.student_utterance_count ?? 0} ${t('учеников')}</div></div>
      <div class="panel kpi"><div class="k-label">${t('Речь учителя')}</div><div class="k-value">${tt.teacher_pct != null ? Math.round(tt.teacher_pct) : '—'}<small>%</small></div>
        <div class="k-note">${t('от общего времени урока')}</div></div>
      <div class="panel kpi"><div class="k-label">${t('Вопросы учителя')}</div><div class="k-value">${questions.length}</div>
        <div class="k-note">${s.higher_order_pct != null ? `${s.higher_order_pct}% — ${t('применение и анализ')}` : t('вопросов не найдено')}</div></div>
      <div class="panel kpi"><div class="k-label">${t('Соответствие плану')}</div><div class="k-value">${ac['Strong'] || 0}<small>/ ${alignTotal}</small></div>
        <div class="k-note">${t('реализовано полностью')}${ac['Partial'] ? ` · ${ac['Partial']} ${t('частично')}` : ''}</div></div>
    </div>

    <div class="tabs" role="tablist">
      ${tabs.map(([k, l, c], i) => `<button role="tab" id="tab-${k}" aria-controls="panel-${k}" aria-selected="${i === 0}" data-tab="${k}">${l}${c != null ? `<span class="count">${c}</span>` : ''}</button>`).join('')}
    </div>

    <div class="tab-panel" id="panel-summary" role="tabpanel" data-print-title="${t('Сводка')}">${summaryPanel(r, tt, duration)}</div>
    <div class="tab-panel" id="panel-plan" role="tabpanel" hidden data-print-title="${t('План и факт')}">${planPanel(rows, r.planned || lesson.planned || {})}</div>
    <div class="tab-panel" id="panel-criteria" role="tabpanel" hidden data-print-title="${t('Критерии оценивания')}">${criteriaPanel(r.criteria_rows || [])}</div>
    <div class="tab-panel" id="panel-questions" role="tabpanel" hidden data-print-title="${t('Вопросы учителя')}">${questionsPanel(questions)}</div>
    <div class="tab-panel" id="panel-inquiry" role="tabpanel" hidden data-print-title="${t('Уровни inquiry')}">${inquiryPanel(episodes, duration)}</div>
    <div class="tab-panel transcript-panel" id="panel-transcript" role="tabpanel" hidden>${transcriptPanel(utts, r.single_track_mode)}</div>
    <div class="tab-panel" id="panel-discussion" role="tabpanel" hidden data-print-title="${t('Обсуждение')}">${discussionPanel()}</div>
    <div class="tab-panel" id="panel-method" role="tabpanel" hidden data-print-title="${t('Методология')}"><div class="panel panel-pad prose"><p>${esc(r.methodology_notes || '')}</p></div></div>
  `;

  const showTab = key => {
    if (!$('#tab-' + key)) return;
    $$('.tabs [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === key)));
    $$('.tab-panel').forEach(p => { p.hidden = p.id !== 'panel-' + key; });
  };
  $('.tabs').addEventListener('click', e => { const b = e.target.closest('[data-tab]'); if (b) showTab(b.dataset.tab); });
  $('.tabs').addEventListener('keydown', e => {
    if (!['ArrowRight', 'ArrowLeft'].includes(e.key)) return;
    const btns = $$('.tabs [role=tab]'); const i = btns.indexOf(document.activeElement);
    const n = btns[(i + (e.key === 'ArrowRight' ? 1 : -1) + btns.length) % btns.length];
    n.focus(); showTab(n.dataset.tab);
  });

  // Переход по таймкоду к месту в расшифровке
  $('#lessonBody').addEventListener('click', e => {
    const b = e.target.closest('[data-jump]');
    if (!b) return;
    const tsec = parseTs(b.dataset.jump);
    if (tsec == null) return;
    showTab('transcript');
    resetTranscriptFilters();
    const items = $$('.transcript .u');
    let target = items[0];
    for (const el of items) { if (+el.dataset.start <= tsec + 0.5) target = el; else break; }
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.classList.add('flash');
      setTimeout(() => target.classList.remove('flash'), 1600);
    }
  });

  bindQuestionFilter();
  bindTranscript(utts);
  bindDiscussion(lesson.id, n => { const c = $('#tab-discussion .count'); if (c) c.textContent = n; }, key => showTab(key));
  if (state.query?.get('tab')) showTab(state.query.get('tab'));
}

function summaryPanel(r, tt, duration) {
  const refl = r.reflection || {};
  const total = duration || 1;
  const teacher = tt.teacher_seconds || 0;
  const student = tt.student_speech_seconds || 0;
  const silence = tt.silence_attributed_to_student_seconds ?? Math.max(0, total - teacher - student);
  const pct = v => Math.round(100 * v / total);
  const seg = (v, color, label, cls = '') => v > 0 ? `<div class="${cls}" style="flex:${v};background:${color}" tabindex="0" data-tip="<b>${label}</b><br>${fmtDuration(v)} · ${pct(v)}%"></div>` : '';
  const list = items => items?.length ? `<ol class="points">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ol>` : t('<p class="subtle">Нет данных.</p>');

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>${t('Кто говорит на уроке')}</h2><span class="hint">${t('доля от')} ${fmtDuration(total)}</span></div>
      <div class="panel-body">
        <div class="bar-stack" role="img" aria-label="${t('Учитель')} ${pct(teacher)}%, ${t('ученики')} ${pct(student)}%, ${t('без речи')} ${pct(silence)}%">
          ${seg(teacher, 'var(--series-1)', t('Учитель'))}
          ${seg(student, 'var(--series-2)', t('Ученики'))}
          ${seg(silence, '', t('Без речи'), 'fill-none')}
        </div>
        <div class="legend">
          <span><i class="sw" style="background:var(--series-1)"></i>${t('Учитель')} <b>${pct(teacher)}%</b></span>
          <span><i class="sw" style="background:var(--series-2)"></i>${t('Ученики')} <b>${pct(student)}%</b></span>
          <span><i class="sw sw-none"></i>${t('Без речи — самостоятельная или групповая работа')} <b>${pct(silence)}%</b></span>
        </div>
        ${r.single_track_mode ? `<p class="subtle" style="font-size:12.5px;margin-top:10px">${t('Только запись учителя: роли определены по смыслу речи, точность ниже.')}</p>` : ''}
      </div>
    </div>

    <div class="grid-2">
      <div class="panel panel-pad">
        <div class="col-head"><span class="dot" style="background:var(--good)"></span><h2 class="section-title">${t('Сильные стороны')}</h2></div>
        ${list(refl.strengths)}
      </div>
      <div class="panel panel-pad">
        <div class="col-head"><span class="dot" style="background:var(--warn)"></span><h2 class="section-title">${t('Зоны роста')}</h2></div>
        ${list(refl.areas_for_development)}
      </div>
    </div>

    ${refl.suggested_next_lesson_strategy ? `<div class="next-step"><div class="label">${t('Рекомендация на следующий урок')}</div><p>${esc(refl.suggested_next_lesson_strategy)}</p></div>` : ''}

    ${r.intended_vs_enacted_summary ? `<div class="panel"><div class="panel-head"><h2>${t('Заявленный подход и реальная практика')}</h2></div><div class="panel-body prose"><p>${esc(r.intended_vs_enacted_summary)}</p></div></div>` : ''}
  </div>`;
}

function planPanel(rows, planned) {
  if (!rows.length) return `<div class="panel empty"><h2>${t('Сравнение с планом не выполнено')}</h2><p>${t('План урока не был заполнен или модель не вернула результат.')}</p></div>`;
  return `<div class="panel"><div class="table-wrap"><table class="data align-table">
    <thead><tr><th>${t('Пункт плана')}</th><th>${t('Запланировано')}</th><th>${t('Что наблюдалось на уроке')}</th><th>${t('Оценка')}</th></tr></thead>
    <tbody>${rows.map(row => {
      const a = ALIGN[row.alignment] || { label: row.alignment || '—', cls: '' };
      const plannedText = row.planned || planned[row.field] || '';
      return `<tr>
        <td>${esc(FIELD_LABELS[row.field] || row.field)}</td>
        <td data-l="${t('Запланировано')}">${plannedText ? esc(plannedText) : t('<span class="subtle">не указано</span>')}</td>
        <td data-l="${t('Наблюдалось')}">${row.observed_evidence ? esc(row.observed_evidence) : t('<span class="subtle">свидетельств не найдено</span>')}</td>
        <td data-l="${t('Оценка')}"><span class="badge ${a.cls}">${esc(a.label)}</span></td>
      </tr>`;
    }).join('')}</tbody>
  </table></div></div>`;
}

const OPPORTUNITY = {
  'Strong': { label: t('Ученики работали'), cls: 'good' },
  'Partial': { label: t('Затронуто'), cls: 'warn' },
  'Not observed': { label: t('Не наблюдалось'), cls: '' },
  'Not observable': { label: t('Не видно по аудио'), cls: 'plain' },
};

function criteriaPanel(rows) {
  if (!rows.length) return '';
  const byCrit = {};
  rows.forEach(r => { (byCrit[r.criterion] ||= { label: r.criterion_label, audio: r.audio, rows: [] }).rows.push(r); });
  const counts = {};
  rows.forEach(r => { counts[r.opportunity] = (counts[r.opportunity] || 0) + 1; });
  return `<div class="stack">
    <div class="callout">${icon('info')}<div>${t('Это не оценка по рубрике — для неё нужны работы учеников. Здесь показано, давал ли урок ученикам возможность проявить каждый strand выбранных критериев. Формулировки strands — по гайду для MYP year 5.')}</div></div>
    <div class="legend" style="margin-top:0">${Object.entries(OPPORTUNITY).map(([k, v]) => `<span><span class="badge ${v.cls}">${v.label}</span> <b>${counts[k] || 0}</b></span>`).join('')}</div>
    ${Object.entries(byCrit).map(([code, c]) => `
      <div class="panel">
        <div class="panel-head"><h2>Criterion ${esc(code)} · ${esc(c.label)}</h2>
          <span class="hint">${c.audio === 'none' ? t('по аудио не наблюдается') : c.audio === 'partial' ? t('по аудио — частично') : ''}</span></div>
        <div class="panel-body"><ul class="item-list">
          ${c.rows.map(r => {
            const o = OPPORTUNITY[r.opportunity] || { label: r.opportunity, cls: '' };
            return `<li>
              ${r.timestamp ? `<button class="ts" data-jump="${esc(r.timestamp)}" data-tip="${t('Показать в расшифровке')}">${esc(r.timestamp)}</button>` : `<span class="ts static">${esc(r.strand_id)}</span>`}
              <div>
                <div class="item-meta" style="margin-top:0"><span class="badge ${o.cls}">${esc(o.label)}</span>${r.timestamp ? `<span class="subtle mono">${esc(r.strand_id)}</span>` : ''}</div>
                <div class="quote" style="margin-top:6px">${esc(r.strand)}</div>
                ${r.evidence ? `<div class="why">${esc(r.evidence)}</div>` : ''}
                ${r.suggestion ? `<div class="why"><b style="font-weight:500;color:var(--text)">${t('Идея')}:</b> ${esc(r.suggestion)}</div>` : ''}
              </div>
            </li>`;
          }).join('')}
        </ul></div>
      </div>`).join('')}
  </div>`;
}

function questionsPanel(questions) {
  if (!questions.length) return `<div class="panel empty"><h2>${t('Вопросы не найдены')}</h2><p>${t('В репликах учителя не обнаружено вопросов, обращённых к ученикам.')}</p></div>`;
  const counts = {};
  questions.forEach(q => { counts[q.category] = (counts[q.category] || 0) + 1; });
  const cats = [...CATEGORY_ORDER.filter(c => counts[c]), ...Object.keys(counts).filter(c => !CATEGORY_ORDER.includes(c))];
  const max = Math.max(...Object.values(counts));
  const n = questions.length;

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>${t('Типы вопросов')}</h2><span class="hint">${n} ${plural(n, t('вопрос'), t('вопроса'), t('вопросов'))}</span></div>
      <div class="panel-body">
        <div class="hbars">
          ${CATEGORY_ORDER.concat(cats.filter(c => !CATEGORY_ORDER.includes(c))).map(c => {
            const v = counts[c] || 0;
            const info = CATEGORY[c] || { label: c, hint: '' };
            return `<div class="hb-label">${esc(info.label)} <span class="subtle" style="font-size:12px">— ${esc(info.hint)}</span></div>
              <div class="hb-track"><div class="hb-fill" style="width:${max ? 100 * v / max : 0}%" tabindex="0" data-tip="<b>${esc(info.label)}</b><br>${t('{v} из {n}', { v, n })} · ${Math.round(100 * v / n)}%"></div></div>
              <div class="hb-val">${v} · ${Math.round(100 * v / n)}%</div>`;
          }).join('')}
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>${t('Все вопросы')}</h2></div>
      <div class="panel-body">
        <div class="toolbar no-print" id="qFilter">
          <div class="seg" role="group" aria-label="${t('Фильтр по типу')}">
            <button type="button" data-cat="" aria-pressed="true">${t('Все')}</button>
            ${cats.map(c => `<button type="button" data-cat="${esc(c)}" aria-pressed="false">${esc(CATEGORY[c]?.label || c)}</button>`).join('')}
          </div>
        </div>
        <ul class="item-list" id="qList">
          ${questions.map(q => `<li data-cat="${esc(q.category)}">
            <button class="ts" data-jump="${esc(q.timestamp)}" data-tip="${t('Показать в расшифровке')}">${esc(q.timestamp || '—')}</button>
            <div><div class="quote">${esc(q.quote)}</div>
              <div class="item-meta"><span class="tag">${esc(CATEGORY[q.category]?.label || q.category)}</span></div>
              ${q.rationale ? `<div class="why">${esc(q.rationale)}</div>` : ''}</div>
          </li>`).join('')}
        </ul>
      </div>
    </div>
  </div>`;
}

function bindQuestionFilter() {
  const f = $('#qFilter'); if (!f) return;
  f.addEventListener('click', e => {
    const b = e.target.closest('[data-cat]'); if (!b) return;
    $$('[data-cat]', f).forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    $$('#qList > li').forEach(li => { li.hidden = !!b.dataset.cat && li.dataset.cat !== b.dataset.cat; });
  });
}

function inquiryPanel(episodes, duration) {
  if (!episodes.length) return `<div class="panel empty"><h2>${t('Эпизоды не выделены')}</h2><p>${t('Модель не смогла разделить урок на эпизоды.')}</p></div>`;
  const parsed = episodes.map(ep => ({ ...ep, s: parseTs(ep.start_timestamp) ?? 0, e: parseTs(ep.end_timestamp) }));
  const end = Math.max(duration || 0, ...parsed.map(p => p.e || 0)) || 1;
  const byLevel = {};
  parsed.forEach(p => { const d = Math.max(0, (p.e ?? p.s) - p.s); byLevel[p.level] = (byLevel[p.level] || 0) + d; });
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => fmtClock(f * end));

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>${t('Ход урока по уровням inquiry')}</h2><span class="hint">${t('наведите на отрезок, чтобы увидеть эпизод')}</span></div>
      <div class="panel-body">
        <div class="timeline" role="img" aria-label="${t('Шкала эпизодов урока по уровням inquiry')}">
          ${parsed.map(p => {
            const left = 100 * p.s / end, width = Math.max(0.6, 100 * ((p.e ?? p.s) - p.s) / end);
            const lv = LEVEL[p.level] || { short: p.level, label: '' };
            return `<div class="seg-ep" style="left:${left}%;width:${width}%;background:${LEVEL_COLOR[p.level] || 'var(--series-none)'}" tabindex="0"
              data-jump="${esc(p.start_timestamp)}" data-tip="<b>${esc(p.start_timestamp)}–${esc(p.end_timestamp)} · ${esc(lv.short)}</b><br>${esc((p.rationale || '').slice(0, 180))}"></div>`;
          }).join('')}
        </div>
        <div class="time-axis">${ticks.map((tk, i) => `<span style="left:${i * 25}%">${tk}</span>`).join('')}</div>
        <div class="legend">
          ${Object.entries(LEVEL).map(([k, v]) => `<span><i class="sw" style="background:${LEVEL_COLOR[k]}"></i>${v.short} — ${v.label} <b>${byLevel[k] ? Math.round(100 * byLevel[k] / end) + '%' : '0%'}</b></span>`).join('')}
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>${t('Эпизоды')}</h2></div>
      <div class="panel-body"><ul class="item-list">
        ${parsed.map(p => `<li>
          <button class="ts" data-jump="${esc(p.start_timestamp)}">${esc(p.start_timestamp)}<br><span class="subtle">${esc(p.end_timestamp || '')}</span></button>
          <div><div class="item-meta" style="margin-top:0"><span class="badge plain" style="background:var(--accent-soft);color:var(--text)">${esc(LEVEL[p.level]?.short || p.level)}</span><span class="subtle" style="font-size:12.5px">${esc(LEVEL[p.level]?.label || '')}</span></div>
            <div class="why" style="color:var(--text);margin-top:8px">${esc(p.rationale || '')}</div>
            ${p.evidence_quote ? `<div class="why">«${esc(p.evidence_quote)}»</div>` : ''}</div>
        </li>`).join('')}
      </ul></div>
    </div>
  </div>`;
}

function transcriptPanel(utts, singleTrack) {
  if (!utts.length) return `<div class="panel empty"><h2>${t('Расшифровка недоступна')}</h2></div>`;
  return `<div class="panel">
    <div class="panel-body">
      <div class="toolbar">
        <input class="input" id="tSearch" type="search" placeholder="${t('Поиск по расшифровке')}" aria-label="${t('Поиск по расшифровке')}">
        <div class="seg" role="group" aria-label="${t('Кто говорит')}" id="tWho">
          <button type="button" data-who="" aria-pressed="true">${t('Все')}</button>
          <button type="button" data-who="Teacher" aria-pressed="false">${t('Учитель')}</button>
          <button type="button" data-who="Student" aria-pressed="false">${t('Ученики')}</button>
        </div>
        <span class="subtle" id="tCount" style="font-size:12.5px;margin-left:auto"></span>
      </div>
      ${singleTrack ? `<p class="subtle" style="font-size:12.5px;margin-bottom:10px">${t('Роли определены по смыслу речи и могут быть неточны.')}</p>` : ''}
      <div class="transcript" id="transcript"></div>
    </div>
  </div>`;
}

let resetTranscriptFilters = () => {};
function bindTranscript(utts) {
  const box = $('#transcript'); if (!box) return;
  let who = '';
  const search = $('#tSearch');
  const render = () => {
    const q = search.value.trim().toLowerCase();
    let shown = 0;
    box.innerHTML = utts.map(u => {
      if (who && u.speaker !== who) return '';
      if (q && !u.text.toLowerCase().includes(q)) return '';
      shown++;
      let text = esc(u.text);
      if (q) {
        const re = new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
        text = text.replace(re, m => `<mark>${m}</mark>`);
      }
      return `<div class="u ${u.speaker === 'Student' ? 'student' : ''}" data-start="${u.start}">
        <span class="ts static">${fmtClock(u.start)}</span>
        <span class="who">${u.speaker === 'Student' ? t('Ученик') : t('Учитель')}</span>
        <span class="text">${text}</span></div>`;
    }).join('') || t('<p class="subtle" style="padding:12px 8px">Ничего не найдено.</p>');
    $('#tCount').textContent = `${shown} ${plural(shown, t('реплика'), t('реплики'), t('реплик'))}`;
  };
  let debounce;
  search.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(render, 150); });
  $('#tWho').addEventListener('click', e => {
    const b = e.target.closest('[data-who]'); if (!b) return;
    who = b.dataset.who;
    $$('[data-who]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    render();
  });
  resetTranscriptFilters = () => {
    if (!who && !search.value) return;
    who = ''; search.value = '';
    $$('[data-who]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.who === '')));
    render();
  };
  render();
}

/* ------------------------------------------------------------------ */
/* Пользователи (администратор)                                        */
/* ------------------------------------------------------------------ */

function genPassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const arr = new Uint32Array(12); crypto.getRandomValues(arr);
  return [...arr].map(n => chars[n % chars.length]).join('');
}

async function viewUsers() {
  renderShell('users', `
    <div class="page">
      <div class="page-head">
        <div><h1>${t('Пользователи')}</h1><p class="lede">${t('Учётные записи учителей, методистов и администраторов. Самостоятельной регистрации нет — доступ выдаётся здесь.')}</p></div>
        <div class="head-actions"><button class="btn primary" id="addUser">${icon('plus')}${t('Добавить пользователя')}</button></div>
      </div>
      <div id="usersBody"></div>
    </div>`);

  async function load() {
    const { users } = await api('GET', '/api/users');
    $('#usersBody').innerHTML = `<div class="panel"><div class="table-wrap"><table class="data">
      <thead><tr><th>${t('Пользователь')}</th><th>${t('Роль')}</th><th class="num">${t('Уроков')}</th><th>${t('Статус')}</th><th></th></tr></thead>
      <tbody>${users.map(u => `<tr>
        <td><div class="cell-title">${esc(u.name || '—')}</div><div class="cell-sub">${esc(u.email)}</div></td>
        <td>${u.id === state.user.id ? ROLE_LABEL[u.role] : `<select class="select" data-role-select="${u.id}" aria-label="${t('Роль')}" style="width:auto;height:30px">${Object.entries(ROLE_LABEL).map(([k, v]) => `<option value="${k}" ${k === u.role ? 'selected' : ''}>${v}</option>`).join('')}</select>`}</td>
        <td class="num">${u.lesson_count}</td>
        <td>${u.is_active ? t('<span class="badge good">Активен</span>') : t('<span class="badge">Отключён</span>')}</td>
        <td class="num nowrap">
          <button class="btn sm ghost" data-act="pw" data-id="${u.id}">${t('Сменить пароль')}</button>
          ${u.id !== state.user.id ? `<button class="btn sm ghost" data-act="toggle" data-id="${u.id}" data-active="${u.is_active}">${u.is_active ? t('Отключить') : t('Включить')}</button>` : ''}
        </td>
      </tr>`).join('')}</tbody></table></div></div>`;
  }
  await load();

  $('#usersBody').addEventListener('click', async e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const id = +b.dataset.id;
    try {
      if (b.dataset.act === 'toggle') {
        const active = b.dataset.active === '1';
        if (active && !await confirmDialog({ title: t('Отключить пользователя?'), text: t('Он не сможет войти. Его уроки сохранятся.'), confirm: t('Отключить'), danger: true })) return;
        await api('PATCH', `/api/users/${id}`, { is_active: !active });
      } else if (b.dataset.act === 'pw') {
        const pw = await passwordDialog();
        if (!pw) return;
        await api('PATCH', `/api/users/${id}`, { password: pw });
        toast(t('Пароль изменён. Передайте его пользователю.'));
      }
      await load();
    } catch (err) { toast(err.message, 'bad'); }
  });

  $('#usersBody').addEventListener('change', async e => {
    const sel = e.target.closest('[data-role-select]'); if (!sel) return;
    try { await api('PATCH', `/api/users/${sel.dataset.roleSelect}`, { role: sel.value }); toast(t('Роль изменена.')); }
    catch (err) { toast(err.message, 'bad'); }
    await load();
  });

  $('#addUser').addEventListener('click', () => {
    const d = document.createElement('dialog');
    const pw = genPassword();
    d.innerHTML = `<form method="dialog" id="uForm">
      <div class="d-body stack">
        <h2>${t('Новый пользователь')}</h2>
        <div class="field"><label for="uName">${t('Имя и фамилия')}</label><input class="input" id="uName" required></div>
        <div class="field"><label for="uEmail">Email</label><input class="input" id="uEmail" type="email" required></div>
        <div class="field"><label for="uRole">${t('Роль')}</label><select class="select" id="uRole">${Object.entries(ROLE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
          <span class="help">${t('Методист видит уроки и динамику всех учителей и может комментировать отчёты.')}</span></div>
        <div class="field"><label for="uPw">${t('Временный пароль')}</label><input class="input mono" id="uPw" value="${pw}" required minlength="8">
          <span class="help">${t('Передайте его пользователю — он сможет сменить пароль в профиле.')}</span></div>
        <div class="form-error" id="uErr"></div>
      </div>
      <div class="d-actions"><button type="button" class="btn" data-close>${t('Отмена')}</button><button class="btn primary" type="submit">${t('Создать')}</button></div>
    </form>`;
    document.body.appendChild(d);
    d.addEventListener('close', () => d.remove());
    $('[data-close]', d).onclick = () => d.close();
    $('#uForm', d).addEventListener('submit', async e => {
      e.preventDefault();
      try {
        await api('POST', '/api/users', { name: $('#uName', d).value, email: $('#uEmail', d).value, role: $('#uRole', d).value, password: $('#uPw', d).value });
        const email = $('#uEmail', d).value, pass = $('#uPw', d).value;
        d.close();
        toast(`${t('Пользователь создан')}: ${email}`);
        navigator.clipboard?.writeText(`${t('Адрес')}: ${location.origin}\nEmail: ${email}\n${t('Пароль')}: ${pass}`).then(() => toast(t('Данные для входа скопированы в буфер обмена.'))).catch(() => {});
        await load();
      } catch (err) { $('#uErr', d).textContent = err.message; }
    });
    d.showModal();
    $('#uName', d).focus();
  });
}

function passwordDialog() {
  return new Promise(resolve => {
    const d = document.createElement('dialog');
    d.innerHTML = `<form method="dialog">
      <div class="d-body stack"><h2>${t('Новый пароль')}</h2>
        <div class="field"><label for="npw">${t('Пароль (не короче 8 символов)')}</label><input class="input mono" id="npw" value="${genPassword()}" minlength="8" required></div></div>
      <div class="d-actions"><button type="button" class="btn" data-close>${t('Отмена')}</button><button class="btn primary" type="submit">${t('Сохранить')}</button></div></form>`;
    document.body.appendChild(d);
    let result = null;
    $('[data-close]', d).onclick = () => d.close();
    $('form', d).addEventListener('submit', e => { e.preventDefault(); result = $('#npw', d).value; d.close(); });
    d.addEventListener('close', () => { d.remove(); resolve(result); });
    d.showModal();
  });
}

/* ------------------------------------------------------------------ */
/* Профиль                                                             */
/* ------------------------------------------------------------------ */

async function viewAccount() {
  const u = state.user;
  renderShell('account', `
    <div class="page narrow">
      <div class="page-head"><div><h1>${t('Профиль')}</h1><p class="lede">${esc(u.email)}</p></div></div>
      <div class="stack">
        <form class="panel panel-pad stack" id="nameForm">
          <h2 class="section-title">${t('Имя')}</h2>
          <div class="field"><label for="pName">${t('Отображается в отчётах по умолчанию')}</label><input class="input" id="pName" value="${esc(u.name)}"></div>
          <div><button class="btn" type="submit">${t('Сохранить')}</button></div>
        </form>
        <div class="panel panel-pad stack">
          <h2 class="section-title">${t('Язык интерфейса')}</h2>
          <div>${langSwitcher()}</div>
          <h2 class="section-title" style="margin-top:8px">${t('Уведомления')}</h2>
          <label class="check-row"><input type="checkbox" id="emailNotif" ${u.email_notifications ? 'checked' : ''} ${state.emailAvailable ? '' : 'disabled'}>
            <span>${t('Присылать письма о новых комментариях и готовых отчётах')}</span></label>
          ${state.emailAvailable ? '' : `<p class="help">${t('Отправка писем не настроена на сервере — уведомления приходят только на сайте.')}</p>`}
          ${u.role === 'admin' ? `<div><button type="button" class="btn" id="testEmail">${t('Отправить тестовое письмо себе')}</button>
            <p class="help" id="testEmailRes" style="margin-top:6px"></p></div>` : ''}
        </div>
        <form class="panel panel-pad stack" id="pwForm">
          <h2 class="section-title">${t('Смена пароля')}</h2>
          <div class="field"><label for="cur">${t('Текущий пароль')}</label><input class="input" id="cur" type="password" autocomplete="current-password" required></div>
          <div class="field"><label for="new1">${t('Новый пароль')}</label><input class="input" id="new1" type="password" autocomplete="new-password" minlength="8" required><span class="help">${t('Не короче 8 символов.')}</span></div>
          <div class="form-error" id="pwErr"></div>
          <div><button class="btn" type="submit">${t('Сменить пароль')}</button></div>
        </form>
      </div>
    </div>`);
  $('#nameForm').addEventListener('submit', async e => {
    e.preventDefault();
    try { await api('POST', '/api/auth/profile', { name: $('#pName').value }); state.user.name = $('#pName').value.trim(); toast(t('Сохранено.')); viewAccount(); }
    catch (err) { toast(err.message, 'bad'); }
  });
  $('#testEmail')?.addEventListener('click', async e => {
    const btn = e.currentTarget, res = $('#testEmailRes');
    btn.disabled = true; res.style.color = ''; res.textContent = t('Отправляем…');
    try {
      const r = await api('POST', '/api/admin/test-email');
      res.textContent = t('Письмо отправлено на {email}. Проверьте почту, в том числе папку «Спам».', { email: r.to });
    } catch (err) { res.style.color = 'var(--bad)'; res.textContent = err.message; }
    btn.disabled = false;
  });
  $('#emailNotif').addEventListener('change', async e => {
    try { await api('POST', '/api/auth/preferences', { email_notifications: e.target.checked }); state.user.email_notifications = e.target.checked; toast(t('Сохранено.')); }
    catch (err) { toast(err.message, 'bad'); }
  });
  $('#pwForm').addEventListener('submit', async e => {
    e.preventDefault();
    $('#pwErr').textContent = '';
    try {
      await api('POST', '/api/auth/password', { current_password: $('#cur').value, new_password: $('#new1').value });
      e.target.reset(); toast(t('Пароль изменён.'));
    } catch (err) { $('#pwErr').textContent = err.message; }
  });
}

/* ------------------------------------------------------------------ */
/* Запуск                                                              */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* Запись урока на сайте                                               */
/* ------------------------------------------------------------------ */

const REC_TIMESLICE_MS = 10000;

function pickRecorderMime() {
  if (typeof MediaRecorder === 'undefined') return null;
  for (const m of ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm']) {
    try { if (MediaRecorder.isTypeSupported(m)) return m; } catch { /* */ }
  }
  return '';
}

/* Очередь отправки кусков: строго по порядку, с повторами при обрыве связи.
   Все куски остаются в памяти до завершения записи — если сервер сообщит,
   что какого-то не хватает, он будет отправлен ещё раз. */
class ChunkUploader {
  constructor(recId, onChange) {
    this.recId = recId; this.onChange = onChange;
    this.queue = []; this.all = new Map();
    this.sentBytes = 0; this.busy = false; this.failing = false; this.lastError = '';
  }
  push(seg, seq, blob) {
    this.all.set(`${seg}:${seq}`, blob);
    this.queue.push({ seg, seq, blob });
    this.pump();
  }
  requeue(missing) {
    for (const [seg, seq] of missing) {
      const blob = this.all.get(`${seg}:${seq}`);
      if (blob) this.queue.push({ seg, seq, blob });
    }
    this.pump();
  }
  get pending() { return this.queue.length; }
  async pump() {
    if (this.busy) return;
    this.busy = true;
    let delay = 2000;
    while (this.queue.length) {
      const item = this.queue[0];
      try {
        const res = await fetch(`/api/recordings/${this.recId}/chunks/${item.seg}/${item.seq}`, {
          method: 'PUT', body: item.blob, credentials: 'same-origin',
          headers: { 'Content-Type': 'application/octet-stream' },
        });
        if (res.status === 401) { this.lastError = t('Сессия истекла — войдите снова в другой вкладке, запись продолжится.'); throw new Error('401'); }
        if (res.status === 409) { this.queue.shift(); continue; } // запись уже завершена
        if (!res.ok) throw new Error('HTTP ' + res.status);
        this.queue.shift();
        this.sentBytes += item.blob.size;
        this.failing = false; this.lastError = ''; delay = 2000;
      } catch {
        this.failing = true;
        if (!this.lastError) this.lastError = t('Нет связи с сервером. Запись продолжается, куски будут отправлены, когда связь восстановится.');
        this.onChange?.();
        await new Promise(r => setTimeout(r, delay));
        delay = Math.min(delay * 2, 30000);
        continue;
      }
      this.onChange?.();
    }
    this.busy = false;
    this.onChange?.();
  }
  async flush(timeoutMs = 120000) {
    const t0 = Date.now();
    while (this.queue.length || this.busy) {
      if (Date.now() - t0 > timeoutMs) return false;
      await new Promise(r => setTimeout(r, 300));
    }
    return true;
  }
}

/* Один активный рекордер на всё приложение: запись не прерывается при
   переходе между страницами сайта. */
const recorder = {
  active: null,        // { id, mime, segment, seqBySeg, lastSeq, uploader, ... }
  listeners: new Set(),
  notify() { this.listeners.forEach(fn => { try { fn(); } catch { /* */ } }); updateRecIndicator(); },
};

function recElapsedMs(r) {
  if (!r) return 0;
  return r.accumulatedMs + (r.runningSince ? Date.now() - r.runningSince : 0);
}

async function acquireWakeLock(r) {
  try {
    if ('wakeLock' in navigator && document.visibilityState === 'visible') {
      r.wakeLock = await navigator.wakeLock.request('screen');
      r.wakeLock.addEventListener?.('release', () => { r.wakeLock = null; });
    }
  } catch { r.wakeLock = null; }
}

const AUDIO_CONSTRAINTS = {
  audio: {
    // Шумоподавление и эхоподавление выключены: они «съедают» тихие
    // реплики учеников. Автоусиление оставлено — помогает с дальними голосами.
    echoCancellation: false, noiseSuppression: false, autoGainControl: true, channelCount: 1,
  },
};

async function startSegment(r) {
  const stream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS);
  const opts = { audioBitsPerSecond: 48000 };
  if (r.mime) opts.mimeType = r.mime;
  const mr = new MediaRecorder(stream, opts);
  const seg = r.segment;
  r.seqBySeg[seg] = r.seqBySeg[seg] ?? 0;
  r.stream = stream; r.mr = mr;

  mr.ondataavailable = e => {
    if (!e.data || !e.data.size) return;
    const seq = r.seqBySeg[seg]++;
    r.lastSeq[seg] = seq;
    r.uploader.push(seg, seq, e.data);
    recorder.notify();
  };
  mr.onstop = () => {
    stream.getTracks().forEach(t => t.stop());
    if (r.mr === mr) r.mr = null;
    if (!r.stopping) segmentInterrupted(r);
  };
  stream.getAudioTracks()[0]?.addEventListener('ended', () => {
    if (mr.state !== 'inactive') { try { mr.stop(); } catch { /* */ } }
  });
  setupMeter(r, stream);
  mr.start(REC_TIMESLICE_MS);
  r.runningSince = Date.now();
  r.state = 'recording';
  acquireWakeLock(r);
  recorder.notify();
}

function segmentInterrupted(r) {
  if (r.runningSince) { r.accumulatedMs += Date.now() - r.runningSince; r.runningSince = null; }
  r.state = 'interrupted';
  r.interruptedAt = Date.now();
  recorder.notify();
  tryResumeSegment(r);
}

async function tryResumeSegment(r) {
  if (recorder.active !== r || r.state !== 'interrupted' || r.stopping) return;
  if (document.visibilityState !== 'visible') return; // продолжим, когда страница снова откроется
  r.segment += 1;
  try {
    await startSegment(r);
    const gap = Math.max(1, Math.round((Date.now() - r.interruptedAt) / 1000));
    r.gaps.push({ at: recElapsedMs(r), seconds: gap });
    toast(t('Запись прерывалась на {duration} и продолжена.', { duration: fmtDuration(gap) }));
  } catch {
    r.segment -= 1;
    r.state = 'interrupted';
    recorder.notify();
  }
}

document.addEventListener('visibilitychange', () => {
  const r = recorder.active;
  if (!r || document.visibilityState !== 'visible') return;
  if (r.state === 'interrupted') tryResumeSegment(r);
  if (r.state === 'recording') {
    // iOS при блокировке иногда «глушит» дорожку, не останавливая MediaRecorder.
    // Такой сегмент завершаем и начинаем новый.
    const track = r.stream?.getAudioTracks()[0];
    if (track && (track.readyState === 'ended' || track.muted) && r.mr && r.mr.state !== 'inactive') {
      try { r.mr.stop(); } catch { /* */ }
      return;
    }
    if (!r.wakeLock) acquireWakeLock(r);
  }
});

window.addEventListener('beforeunload', e => {
  const r = recorder.active;
  if (r && (r.state === 'recording' || r.state === 'paused' || r.uploader.pending)) {
    e.preventDefault(); e.returnValue = '';
  }
});

function setupMeter(r, stream) {
  try {
    r.audioCtx?.close?.();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    r.audioCtx = ctx; r.analyser = an; r.meterBuf = new Uint8Array(an.fftSize);
  } catch { r.analyser = null; }
}

function meterLevel(r) {
  if (!r?.analyser) return 0;
  r.analyser.getByteTimeDomainData(r.meterBuf);
  let sum = 0;
  for (const v of r.meterBuf) { const x = (v - 128) / 128; sum += x * x; }
  return Math.min(1, Math.sqrt(sum / r.meterBuf.length) * 4);
}

async function startRecording(existing) {
  const mime = existing ? existing.mime : pickRecorderMime();
  if (mime === null || !navigator.mediaDevices?.getUserMedia) {
    toast(t('Этот браузер не поддерживает запись звука. Используйте Chrome или Safari последней версии.'), 'bad');
    return;
  }
  let id = existing?.id;
  if (!id) id = (await api('POST', '/api/recordings', { mime })).id;
  const r = {
    id, mime, state: 'starting', stopping: false,
    segment: 0, seqBySeg: {}, lastSeq: {}, gaps: [],
    accumulatedMs: 0, runningSince: null, startedAt: Date.now(),
  };
  if (existing) {
    // Продолжение записи после перезагрузки страницы: новый сегмент после уже полученных.
    const segs = existing.segments || {};
    for (const [k, v] of Object.entries(segs)) { r.lastSeq[k] = v.max_seq; r.seqBySeg[k] = v.max_seq + 1; }
    r.segment = Object.keys(segs).length ? Math.max(...Object.keys(segs).map(Number)) + 1 : 0;
    r.resumed = true;
  }
  r.uploader = new ChunkUploader(id, () => recorder.notify());
  recorder.active = r;
  try {
    await startSegment(r);
  } catch (err) {
    recorder.active = null;
    if (!existing) api('DELETE', `/api/recordings/${id}`).catch(() => {});
    const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
    toast(denied ? t('Нет доступа к микрофону. Разрешите его в настройках браузера для этого сайта.') : t('Не удалось включить микрофон.'), 'bad');
    recorder.notify();
  }
}

function pauseRecording() {
  const r = recorder.active;
  if (!r?.mr || r.mr.state !== 'recording') return;
  r.mr.pause();
  r.accumulatedMs += Date.now() - r.runningSince; r.runningSince = null;
  r.state = 'paused';
  recorder.notify();
}
function resumeRecording() {
  const r = recorder.active;
  if (!r?.mr || r.mr.state !== 'paused') return;
  r.mr.resume();
  r.runningSince = Date.now();
  r.state = 'recording';
  recorder.notify();
}

async function stopRecording() {
  const r = recorder.active;
  if (!r) return;
  r.stopping = true;
  if (r.runningSince) { r.accumulatedMs += Date.now() - r.runningSince; r.runningSince = null; }
  r.state = 'uploading';
  recorder.notify();
  if (r.mr && r.mr.state !== 'inactive') {
    await new Promise(res => { r.mr.addEventListener('stop', res, { once: true }); r.mr.stop(); });
  }
  r.stream?.getTracks().forEach(t => t.stop());
  r.audioCtx?.close?.();
  try { await r.wakeLock?.release(); } catch { /* */ }
  exitPocketMode();
  await finishUpload(r);
}

async function finishUpload(r) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const ok = await r.uploader.flush(180000);
    if (!ok) { r.state = 'upload-stuck'; recorder.notify(); return; }
    const res = await fetch(`/api/recordings/${r.id}/finish`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments: r.lastSeq }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) { r.state = 'finalizing'; recorder.notify(); return pollFinalize(r); }
    if (res.status === 409 && data.detail?.missing) { r.uploader.requeue(data.detail.missing); continue; }
    r.state = 'error'; r.error = errorText(data, res.status); recorder.notify(); return;
  }
  r.state = 'error'; r.error = t('Не все части записи удалось отправить.'); recorder.notify();
}

async function pollFinalize(r) {
  for (;;) {
    await new Promise(res => setTimeout(res, 2000));
    const data = await api('GET', `/api/recordings/${r.id}`).catch(() => null);
    const rec = data?.recording;
    if (!rec) continue;
    if (rec.status === 'ready') { r.state = 'ready'; r.duration = rec.duration_seconds; recorder.notify(); return; }
    if (rec.status === 'error') { r.state = 'error'; r.error = rec.error || t('Не удалось обработать запись.'); recorder.notify(); return; }
  }
}

/* Карманный режим: чёрный экран (на OLED почти не расходует батарею),
   экран при этом не гаснет — Wake Lock держит его включённым. */
function enterPocketMode() {
  const r = recorder.active;
  if (!r) return;
  let ov = $('#pocket');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'pocket';
    ov.innerHTML = `<div class="pocket-inner"><div class="pocket-dot"></div><div class="pocket-time" id="pocketTime">00:00</div><div class="pocket-hint">${t('Двойное касание — выйти')}</div></div>`;
    document.body.appendChild(ov);
    let last = 0;
    const exit = () => exitPocketMode();
    ov.addEventListener('dblclick', exit);
    ov.addEventListener('touchend', e => { const now = Date.now(); if (now - last < 400) { e.preventDefault(); exit(); } last = now; });
  }
  ov.hidden = false;
  document.documentElement.requestFullscreen?.().catch(() => {});
  acquireWakeLock(r);
}
function exitPocketMode() {
  const ov = $('#pocket');
  if (ov) ov.hidden = true;
  if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
}

function updateRecIndicator() {
  const r = recorder.active;
  const live = r && ['recording', 'paused', 'interrupted', 'uploading', 'finalizing'].includes(r.state);
  for (const [elId, timeId] of [['#recIndicator', '#recIndicatorTime'], ['#recIndicatorTop', '#recIndicatorTopTime']]) {
    const el = $(elId);
    if (!el) continue;
    el.hidden = !live;
    if (live) $(timeId).textContent = fmtClock(recElapsedMs(r) / 1000);
  }
  const pt = $('#pocketTime');
  if (pt && r) pt.textContent = fmtClock(recElapsedMs(r) / 1000);
}
setInterval(updateRecIndicator, 1000);

/* ---------- Страница записи ---------- */

const REC_STATE_TEXT = {
  starting: t('Включаем микрофон…'),
  recording: t('Идёт запись'),
  paused: t('Пауза'),
  interrupted: t('Запись прервалась — продолжится, как только страница снова будет открыта'),
  uploading: t('Отправляем последние части…'),
  finalizing: t('Собираем запись на сервере…'),
  ready: t('Запись готова'),
  error: t('Ошибка'),
  'upload-stuck': t('Не удаётся отправить запись'),
};

async function viewRecord() {
  renderShell('record', `<div class="page narrow" id="recPage"></div>`);
  const page = $('#recPage');
  let saved = [];
  let raf = 0;

  async function loadSaved() {
    saved = (await api('GET', '/api/recordings').catch(() => ({ recordings: [] }))).recordings;
    const r = recorder.active;
    if (r) saved = saved.filter(x => x.id !== r.id);
  }

  function savedList() {
    if (!saved.length) return '';
    const row = rec => {
      const when = fmtTimestamp(rec.created_at);
      let info = '', actions = '';
      if (rec.status === 'ready') {
        info = `${t('Готова')} · ${fmtDuration(rec.duration_seconds)}`;
        actions = `<a class="btn sm primary" href="#/new?rec=${rec.id}">${t('К анализу')}</a><a class="btn sm" href="/api/recordings/${rec.id}/audio">${t('Скачать')} mp3</a>`;
      } else if (rec.status === 'recording') {
        info = `${t('Не завершена')} · ${t('получено')} ${fmtSize(rec.bytes_received)}`;
        actions = `<button class="btn sm primary" data-act="continue" data-id="${rec.id}">${t('Продолжить запись')}</button><button class="btn sm" data-act="finish" data-id="${rec.id}">${t('Завершить')}</button>`;
      } else if (rec.status === 'finalizing') {
        info = t('Собирается на сервере…');
      } else if (rec.status === 'error') {
        info = `<span style="color:var(--bad)">${esc(rec.error || t('Ошибка обработки'))}</span>`;
      }
      return `<li class="saved-rec"><div><div class="cell-title">${t('Запись от')} ${esc(when)}</div><div class="cell-sub">${info}</div></div>
        <div class="saved-actions">${actions}${rec.status !== 'finalizing' ? `<button class="btn sm ghost" data-act="delete" data-id="${rec.id}" aria-label="${t('Удалить запись')}">${icon('trash')}</button>` : ''}</div></li>`;
    };
    return `<div class="panel"><div class="panel-head"><h2>${t('Сохранённые записи')}</h2></div><div class="panel-body"><ul class="saved-list">${saved.map(row).join('')}</ul></div></div>`;
  }

  function idleView() {
    const unsupported = pickRecorderMime() === null || !navigator.mediaDevices?.getUserMedia;
    return `
      <div class="page-head"><div><h1>${t('Запись урока')}</h1>
        <p class="lede">${t('Телефон или ноутбук записывает урок как диктофон, а запись по частям сразу сохраняется на сервере — даже если связь пропадёт или вкладка закроется, записанное не потеряется.')}</p></div></div>
      <div class="stack">
        <div class="panel rec-panel">
          ${unsupported ? `<div class="callout bad">${icon('alert')}<div>${t('Этот браузер не поддерживает запись звука. Откройте сайт в Chrome (Android, компьютер) или Safari (iPhone, iPad).')}</div></div>` : `
          <button class="rec-big" id="recStart" type="button" aria-label="${t('Начать запись')}"><span></span></button>
          <div class="rec-caption">${t('Начать запись')}</div>`}
        </div>
        <div class="panel panel-pad">
          <h2 class="section-title" style="margin-bottom:10px">${t('Как записать лучше')}</h2>
          <ol class="points">
            <li>${t('Положите телефон в нагрудный карман или держите рядом с собой — главное, чтобы был слышен учитель. Чехол и ткань не должны закрывать микрофон.')}</li>
            <li>${t('После старта нажмите <b>«Карманный режим»</b>: экран станет чёрным и не будет гаснуть. Батарея почти не расходуется.')}</li>
            <li><b>${t('Не блокируйте телефон кнопкой питания.')}</b> ${t('На iPhone это останавливает запись; на Android — может остановить. Если это всё же случилось, откройте страницу снова — запись продолжится, а пауза будет отмечена.')}</li>
            <li>${t('Подключите зарядку, если урок длиннее 60 минут, и отключите режим энергосбережения.')}</li>
          </ol>
        </div>
        ${savedList()}
      </div>`;
  }

  function liveView(r) {
    const s = r.state;
    const live = s === 'recording' || s === 'paused' || s === 'interrupted' || s === 'starting';
    const up = r.uploader;
    const pendingTxt = up.pending ? `${t('в очереди')}: ${up.pending} ${plural(up.pending, t('часть'), t('части'), t('частей'))}` : t('всё отправлено');
    return `
      <div class="page-head"><div><h1>${t('Запись урока')}</h1>
        <p class="lede">${r.resumed ? t('Продолжение ранее начатой записи.') : t('Запись сохраняется на сервере каждые 10 секунд.')}</p></div></div>
      <div class="stack">
        <div class="panel rec-panel ${s === 'recording' ? 'is-live' : ''}">
          <div class="rec-state"><span class="rec-dot ${s}"></span>${esc(REC_STATE_TEXT[s] || s)}</div>
          <div class="rec-time" id="recTime">${fmtClock(recElapsedMs(r) / 1000)}</div>
          ${live ? `<div class="meter" aria-hidden="true"><i id="meterBar"></i></div>` : ''}
          <div class="rec-sync ${up.failing ? 'bad' : ''}" id="recSync">${up.failing ? esc(up.lastError) : `${t('На сервере')}: ${fmtSize(up.sentBytes)} · ${pendingTxt}`}</div>
          ${r.gaps.length ? `<div class="rec-sync">${t('Перерывы в записи')}: ${r.gaps.map(g => `${fmtClock(g.at / 1000)} (${fmtDuration(g.seconds)})`).join(', ')}</div>` : ''}
          ${live ? `<div class="rec-actions">
            <button class="btn lg" id="pocketBtn" type="button">${t('Карманный режим')}</button>
            ${s === 'paused' ? `<button class="btn lg" id="resumeBtn" type="button">${t('Продолжить')}</button>` : `<button class="btn lg" id="pauseBtn" type="button" ${s !== 'recording' ? 'disabled' : ''}>${t('Пауза')}</button>`}
            <button class="btn lg primary" id="stopBtn" type="button">${t('Завершить')}</button>
          </div>` : ''}
          ${s === 'uploading' || s === 'finalizing' ? `<div class="progress" style="margin:16px auto 0;width:240px"><i style="width:100%;animation:pulse 1.2s infinite"></i></div>` : ''}
          ${s === 'ready' ? `<div class="rec-actions">
            <a class="btn lg primary" href="#/new?rec=${r.id}">${t('Перейти к анализу')}</a>
            <a class="btn lg" href="/api/recordings/${r.id}/audio">${t('Скачать')} mp3</a>
          </div><p class="subtle" style="margin-top:10px;font-size:13px">${t('Длительность')}: ${fmtDuration(r.duration)}. ${t('Запись сохранится в списке, пока вы не запустите анализ или не удалите её.')}</p>` : ''}
          ${s === 'error' || s === 'upload-stuck' ? `<div class="callout bad" style="margin-top:16px;text-align:left">${icon('alert')}<div>${esc(r.error || t('Часть записи не удалось отправить на сервер. Не закрывайте страницу и проверьте интернет — отправка продолжится автоматически.'))}</div></div>
            <div class="rec-actions"><button class="btn" id="retryFinish" type="button">${t('Повторить отправку')}</button><button class="btn ghost" id="newRec" type="button">${t('Новая запись')}</button></div>` : ''}
          ${s === 'ready' ? `<div class="rec-actions"><button class="btn ghost" id="newRec" type="button">${t('Новая запись')}</button></div>` : ''}
        </div>
        ${s === 'interrupted' ? `<div class="callout warn">${icon('alert')}<div>${t('Микрофон был отключён (экран заблокировали или его заняло другое приложение). Запись возобновится автоматически, пока эта страница открыта.')}</div></div>` : ''}
        ${savedList()}
      </div>`;
  }

  function render() {
    const r = recorder.active;
    page.innerHTML = r ? liveView(r) : idleView();
    bind();
  }

  function tick() {
    const r = recorder.active;
    if (r) {
      const tEl = $('#recTime'); if (tEl) tEl.textContent = fmtClock(recElapsedMs(r) / 1000);
      const m = $('#meterBar'); if (m) m.style.width = (r.state === 'recording' ? Math.round(meterLevel(r) * 100) : 0) + '%';
    }
    raf = requestAnimationFrame(tick);
  }

  function bind() {
    $('#recStart')?.addEventListener('click', () => startRecording());
    $('#pocketBtn')?.addEventListener('click', enterPocketMode);
    $('#pauseBtn')?.addEventListener('click', pauseRecording);
    $('#resumeBtn')?.addEventListener('click', resumeRecording);
    $('#stopBtn')?.addEventListener('click', async () => {
      if (!await confirmDialog({ title: t('Завершить запись?'), text: t('Запись будет собрана в один файл. Продолжить её после этого нельзя.'), confirm: t('Завершить') })) return;
      stopRecording();
    });
    $('#retryFinish')?.addEventListener('click', () => { const r = recorder.active; if (r) { r.state = 'uploading'; recorder.notify(); finishUpload(r); } });
    $('#newRec')?.addEventListener('click', async () => { recorder.active = null; await loadSaved(); render(); });
    $$('[data-act]', page).forEach(b => b.addEventListener('click', async () => {
      const id = b.dataset.id;
      const rec = saved.find(x => x.id === id);
      try {
        if (b.dataset.act === 'delete') {
          if (!await confirmDialog({ title: t('Удалить запись?'), text: t('Аудио будет удалено с сервера без возможности восстановления.'), confirm: t('Удалить'), danger: true })) return;
          await api('DELETE', `/api/recordings/${id}`);
        } else if (b.dataset.act === 'continue') {
          if (recorder.active) return toast(t('Сначала завершите текущую запись.'), 'bad');
          await startRecording(rec);
        } else if (b.dataset.act === 'finish') {
          const segments = Object.fromEntries(Object.entries(rec.segments || {}).map(([k, v]) => [k, v.max_seq]));
          await api('POST', `/api/recordings/${id}/finish`, { segments });
          toast(t('Запись собирается — это займёт до минуты.'));
        }
      } catch (err) { toast(err.message, 'bad'); }
      await loadSaved(); render();
    }));
  }

  await loadSaved();
  render();
  let lastState = recorder.active?.state;
  const onChange = () => {
    const r = recorder.active;
    if (!r) return;
    if (r.state !== lastState) { lastState = r.state; render(); return; }
    const sync = $('#recSync');
    if (sync) {
      const up = r.uploader;
      sync.className = 'rec-sync' + (up.failing ? ' bad' : '');
      sync.textContent = up.failing ? up.lastError : `${t('На сервере')}: ${fmtSize(up.sentBytes)} · ${up.pending ? `${t('в очереди')}: ${up.pending} ${plural(up.pending, t('часть'), t('части'), t('частей'))}` : t('всё отправлено')}`;
    }
  };
  recorder.listeners.add(onChange);
  raf = requestAnimationFrame(tick);
  navCleanup.push(() => { recorder.listeners.delete(onChange); cancelAnimationFrame(raf); });
}

/* ------------------------------------------------------------------ */
/* Автозаполнение плана из unit planner                                */
/* ------------------------------------------------------------------ */

function plannerBox() {
  return `<div class="span-2 planner-box" id="plannerBox">
    <div class="planner-row">
      <div style="min-width:0"><div class="cell-title">${t('Заполнить из unit planner')}</div>
        <div class="cell-sub">${t('Прикрепите Word или PDF — поля ниже заполнятся автоматически. Проверьте их перед запуском.')}</div></div>
      <div class="planner-actions">
        <label class="btn" for="plannerFile">${icon('file')}${t('Выбрать файл')}</label>
        <input type="file" id="plannerFile" accept=".docx,.pdf,.txt,.md" hidden>
        <button type="button" class="btn ghost" id="plannerPasteToggle">${t('Вставить текст')}</button>
      </div>
    </div>
    <div id="plannerPaste" hidden style="margin-top:12px">
      <textarea class="textarea" id="plannerText" rows="6" placeholder="${t('Вставьте сюда текст unit planner или плана урока')}"></textarea>
      <div style="margin-top:8px"><button type="button" class="btn" id="plannerTextGo">${t('Заполнить')}</button></div>
    </div>
    <div id="plannerStatus" class="cell-sub" style="margin-top:8px" hidden></div>
  </div>`;
}

function bindPlanner(form, o, refreshSubject, saveDraft) {
  const status = $('#plannerStatus');
  const setStatus = (html, cls = '') => { status.hidden = !html; status.innerHTML = html; status.style.color = cls === 'bad' ? 'var(--bad)' : ''; };

  async function run(fd) {
    fd.set('subject_key', form.elements.subject_key.value);
    setStatus(t('<span class="spinner"></span> Читаем документ… обычно 10–30 секунд.'));
    $$('#plannerBox button, #plannerBox label.btn').forEach(b => b.setAttribute('disabled', ''));
    try {
      const res = await fetch('/api/planner/extract', { method: 'POST', body: fd, credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorText(data, res.status));
      const n = applyPlannerFields(form, o, data.fields, refreshSubject);
      saveDraft();
      setStatus(n ? t('Заполнено полей: {n}. Проверьте их и при необходимости поправьте.', { n }) : t('В документе не нашлось полей плана.'));
      if (n) toast(t('План заполнен из документа.'));
    } catch (err) {
      setStatus(esc(err.message), 'bad');
    } finally {
      $$('#plannerBox button, #plannerBox label.btn').forEach(b => b.removeAttribute('disabled'));
      $('#plannerFile').value = '';
    }
  }

  $('#plannerFile').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.set('file', f); run(fd);
  });
  $('#plannerPasteToggle').addEventListener('click', () => { const p = $('#plannerPaste'); p.hidden = !p.hidden; if (!p.hidden) $('#plannerText').focus(); });
  $('#plannerTextGo').addEventListener('click', () => {
    const txt = $('#plannerText').value.trim();
    if (!txt) return setStatus(t('Вставьте текст плана.'), 'bad');
    const fd = new FormData(); fd.set('text', txt); run(fd);
  });
}

function applyPlannerFields(form, o, f, refreshSubject) {
  let n = 0;
  const flash = el => { el.classList.add('autofilled'); setTimeout(() => el.classList.remove('autofilled'), 2500); };
  const setVal = (name, v, onlyIfEmpty = false) => {
    const el = form.elements[name];
    if (!el || !v) return;
    if (onlyIfEmpty && el.value.trim()) return;
    el.value = v; flash(el); n++;
  };
  if (f.subject_key && o.subjects[f.subject_key] && form.elements.subject_key.value !== f.subject_key) {
    form.elements.subject_key.value = f.subject_key;
    refreshSubject();
    flash(form.elements.subject_key); n++;
  }
  setVal('lesson_title', f.lesson_title, true);
  setVal('subject', f.subject, true);
  setVal('grade', f.grade, true);
  setVal('key_concept', f.key_concept);
  setVal('global_context', f.global_context);
  setVal('statement_of_inquiry', f.statement_of_inquiry);
  setVal('inquiry_questions', f.inquiry_questions);
  setVal('learning_objectives', f.learning_objectives);
  setVal('learning_experiences', f.learning_experiences);
  setVal('atl_skills_detail', f.atl_detail);

  const subj = o.subjects[form.elements.subject_key.value];
  const checkGroup = (group, values) => {
    if (!values?.length) return;
    const set = new Set(values);
    $$(`input[data-group="${group}"]`).forEach(i => { i.checked = set.has(i.value); });
    n++;
  };
  checkGroup('related', f.related_concepts);
  checkGroup('learner', f.learner_profile);
  checkGroup('atl', f.atl_clusters);
  if (subj && f.assessment_criteria?.length) {
    checkGroup('criteria', subj.assessment_criteria.filter(c => f.assessment_criteria.includes(c.code)).map(c => `Criterion ${c.code}: ${c.label}`));
  }
  return n;
}

/* ------------------------------------------------------------------ */
/* Динамика по учителю                                                 */
/* ------------------------------------------------------------------ */

const PROGRESS_METRICS = [
  { key: 'teacher_pct', label: t('Речь учителя'), hint: t('доля времени урока; чем ниже, тем больше места ученикам'), better: 'down' },
  { key: 'student_speech_pct', label: t('Речь учеников'), hint: t('доля времени, когда говорят ученики'), better: 'up' },
  { key: 'higher_order_pct', label: t('Вопросы на применение и анализ'), hint: t('доля среди всех вопросов учителя'), better: 'up' },
  { key: 'inquiry_high_pct', label: t('Inquiry уровня 2 и выше'), hint: t('доля времени, когда исследуют ученики'), better: 'up' },
  { key: 'plan_strong_pct', label: t('Реализация плана'), hint: t('пункты плана: «реализовано» = 1, «частично» = 0,5'), better: 'up' },
  { key: 'criteria_strong_pct', label: t('Strands, где работали ученики'), hint: t('среди наблюдаемых по аудио'), better: 'up' },
];

function lessonShortDate(l) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(l.lesson_date || '');
  if (m) return `${+m[3]} ${MONTHS[+m[2] - 1]}`;
  const d = new Date(l.created_at * 1000);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

function lineChart(points, metric) {
  // points: [{ y, label, id, title }] — уже без null
  const W = 320, H = 132, padL = 26, padR = 8, padT = 8, padB = 22;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = points.length;
  const x = i => padL + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
  const y = v => padT + ih - (ih * Math.max(0, Math.min(100, v))) / 100;
  const grid = [0, 50, 100].map(v => `<line x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${padL - 6}" y="${y(v) + 4}" class="ytick">${v}</text>`).join('');
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(' ');
  // Подписи по оси X: первая, последняя и не больше двух между ними — чтобы не наезжали.
  const tickIdx = new Set(n <= 4 ? points.map((_, i) => i) : [0, Math.round((n - 1) / 3), Math.round((2 * (n - 1)) / 3), n - 1]);
  const xt = points.map((p, i) => tickIdx.has(i) ? `<text x="${x(i)}" y="${H - 6}" class="xtick" text-anchor="${n === 1 ? 'middle' : i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${esc(p.label)}</text>` : '').join('');
  const dots = points.map((p, i) => `
    <a href="#/lessons/${p.id}" class="pt" data-tip="<b>${esc(p.title)}</b><br>${esc(p.label)} · ${esc(metric.label)}: ${Math.round(p.y)}%">
      <circle cx="${x(i)}" cy="${y(p.y)}" r="12" class="hit"/>
      <circle cx="${x(i)}" cy="${y(p.y)}" r="4.5" class="dot"/>
    </a>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" class="linechart" role="img" aria-label="${esc(metric.label)} ${t('по урокам')}">
    ${grid}${n > 1 ? `<path d="${path}" class="line"/>` : ''}${dots}${xt}</svg>`;
}

function metricCard(metric, lessons) {
  const pts = lessons
    .map(l => ({ y: l.metrics[metric.key], label: lessonShortDate(l), id: l.id, title: l.lesson_title || l.subject || t('Урок') }))
    .filter(p => p.y != null);
  if (!pts.length) {
    return `<div class="panel metric-card"><div class="mc-head"><div><div class="k-label">${esc(metric.label)}</div><div class="k-note">${esc(metric.hint)}</div></div></div>
      <p class="subtle" style="padding:24px 0;font-size:13px">${t('Нет данных по этому показателю.')}</p></div>`;
  }
  const last = pts[pts.length - 1].y;
  let delta = '';
  if (pts.length > 1) {
    const prev = pts.slice(0, -1);
    const avg = prev.reduce((a, p) => a + p.y, 0) / prev.length;
    const d = Math.round(last - avg);
    if (d === 0) delta = `<span class="delta">${t('на уровне среднего за прошлые уроки')}</span>`;
    else {
      const good = (d > 0) === (metric.better === 'up');
      delta = `<span class="delta ${good ? 'good' : 'bad'}">${d > 0 ? '▲' : '▼'} ${Math.abs(d)} ${t('п.п. к среднему за прошлые уроки')}${good ? '' : ''}</span>`;
    }
  }
  return `<div class="panel metric-card">
    <div class="mc-head">
      <div><div class="k-label">${esc(metric.label)}</div><div class="k-note">${esc(metric.hint)}</div></div>
      <div class="mc-value">${Math.round(last)}<small>%</small></div>
    </div>
    ${delta}
    ${lineChart(pts, metric)}
  </div>`;
}

async function viewProgress() {
  const canAll = canViewAll(state.user);
  let userId = canAll ? (state.query?.get('user') || state.progressUser || '') : '';
  let subjectFilter = '';
  renderShell('progress', `<div class="page" id="progPage"><div class="panel panel-pad stack"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div></div></div>`);

  async function load() {
    const data = await api('GET', '/api/progress' + (userId ? `?user_id=${encodeURIComponent(userId)}` : ''));
    const teacher = data.teacher;
    if (!userId && !data.lessons.length && data.teachers?.some(x => x.done_count)) {
      userId = String(data.teachers.find(x => x.done_count).id);
      return load();
    }
    const subjects = [...new Set(data.lessons.map(l => l.subject).filter(Boolean))].sort();
    const lessons = data.lessons.filter(l => !subjectFilter || l.subject === subjectFilter);
    const teacherSel = data.teachers ? `<select class="select" id="pTeacher" aria-label="${t('Учитель')}">
        ${data.teachers.map(x => `<option value="${x.id}" ${x.id === teacher.id ? 'selected' : ''}>${esc(x.name || x.email)} · ${x.done_count} ${plural(x.done_count, t('урок'), t('урока'), t('уроков'))}</option>`).join('')}
      </select>` : '';
    const subjSel = subjects.length > 1 ? `<select class="select" id="pSubject" aria-label="${t('Предмет')}"><option value="">${t('Все предметы')}</option>${subjects.map(s => `<option ${s === subjectFilter ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>` : '';

    let body;
    if (!lessons.length) {
      body = `<div class="panel empty"><h2>${t('Пока нет готовых уроков')}</h2><p>${t('Динамика появится, когда будет проанализирован хотя бы один урок.')}</p>${teacher.id === state.user.id ? `<a class="btn primary" href="#/new">${icon('plus')}${t('Проанализировать урок')}</a>` : ''}</div>`;
    } else {
      body = `
        ${lessons.length < 3 ? `<div class="callout" style="margin-bottom:16px">${icon('info')}<div>${t('Готовых уроков: {n}. Тенденция станет заметна после 3–4 уроков.', { n: lessons.length })}</div></div>` : ''}
        <div class="metric-grid">${PROGRESS_METRICS.map(m => metricCard(m, lessons)).join('')}</div>
        <div class="panel" style="margin-top:16px">
          <div class="panel-head"><h2>${t('Все уроки')}</h2><span class="hint">${t('точки на графиках кликабельны')}</span></div>
          <div class="table-wrap" style="margin-top:10px"><table class="data">
            <thead><tr><th>${t('Дата')}</th><th>${t('Урок')}</th><th class="num">${t('Учитель')}</th><th class="num">${t('Ученики')}</th><th class="num">${t('Вопросы')}</th><th class="num">${t('Выс. порядка')}</th><th class="num">Inquiry 2+</th><th class="num">${t('План')}</th></tr></thead>
            <tbody>${lessons.slice().reverse().map(l => {
              const m = l.metrics, f = v => v == null ? '—' : Math.round(v) + '%';
              return `<tr class="clickable" data-id="${l.id}" tabindex="0">
                <td class="nowrap">${esc(fmtDate(l.lesson_date) || fmtTimestamp(l.created_at))}</td>
                <td><div class="cell-title">${esc(l.lesson_title || l.subject || t('Урок'))}</div><div class="cell-sub">${esc([l.lesson_title ? l.subject : '', l.grade].filter(Boolean).join(' · '))}</div></td>
                <td class="num">${f(m.teacher_pct)}</td><td class="num">${f(m.student_speech_pct)}</td>
                <td class="num">${m.question_count ?? '—'}</td><td class="num">${f(m.higher_order_pct)}</td>
                <td class="num">${f(m.inquiry_high_pct)}</td><td class="num">${f(m.plan_strong_pct)}</td>
              </tr>`;
            }).join('')}</tbody></table></div>
        </div>`;
    }

    $('#progPage').innerHTML = `
      <div class="page-head">
        <div><h1>${t('Динамика')}</h1><p class="lede">${teacher.id === state.user.id ? t('Как меняются ваши уроки') : `${t('Уроки')}: ${esc(teacher.name || teacher.email)}`} — ${t('по ключевым показателям анализа.')}</p></div>
      </div>
      ${teacherSel || subjSel ? `<div class="toolbar">${teacherSel}${subjSel}</div>` : ''}
      ${body}`;

    $('#pTeacher')?.addEventListener('change', e => { userId = e.target.value; state.progressUser = userId; subjectFilter = ''; load(); });
    $('#pSubject')?.addEventListener('change', e => { subjectFilter = e.target.value; load(); });
    $$('#progPage tr[data-id]').forEach(tr => {
      tr.addEventListener('click', () => go('/lessons/' + tr.dataset.id));
      tr.addEventListener('keydown', e => { if (e.key === 'Enter') go('/lessons/' + tr.dataset.id); });
    });
  }
  await load();
}

/* ------------------------------------------------------------------ */
/* Обсуждение урока                                                    */
/* ------------------------------------------------------------------ */

const COMMENT_SECTIONS = {
  general: t('Урок в целом'), summary: t('Сводка'), plan: t('План и факт'), criteria: t('Критерии'),
  questions: t('Вопросы'), inquiry: 'Inquiry', transcript: t('Расшифровка'),
};

function discussionPanel() {
  return `<div class="stack">
    <div class="panel"><div class="panel-body" id="commentsList"><div class="skeleton" style="width:60%"></div></div></div>
    <form class="panel panel-pad stack no-print" id="commentForm">
      <div class="field"><label for="cBody">${t('Комментарий')}</label>
        <textarea class="textarea" id="cBody" rows="3" maxlength="5000" placeholder="${state.user.role === 'teacher' ? t('Ваша рефлексия или ответ методисту') : t('Наблюдение, вопрос учителю или рекомендация')}"></textarea></div>
      <div class="comment-form-row">
        <select class="select" id="cSection" aria-label="${t('Раздел отчёта')}" style="width:auto">${Object.entries(COMMENT_SECTIONS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
        <span class="subtle hide-sm" style="font-size:12.5px;margin-left:auto">Ctrl+Enter — ${t('отправить')}</span>
        <button class="btn primary" type="submit">${t('Отправить')}</button>
      </div>
    </form>
  </div>`;
}

async function bindDiscussion(lessonId, onCount, showTab) {
  const list = $('#commentsList');
  if (!list) return;
  async function load() {
    const { comments } = await api('GET', `/api/lessons/${lessonId}/comments`);
    onCount(comments.length);
    list.innerHTML = comments.length ? `<ul class="comments">${comments.map(c => `
      <li>
        <div class="avatar">${esc(initials(c.author_name, c.author_email))}</div>
        <div style="min-width:0;flex:1">
          <div class="c-meta"><b>${esc(c.author_name || c.author_email)}</b><span class="subtle">${ROLE_LABEL[c.author_role] || ''} · ${esc(fmtTimestamp(c.created_at))}</span>
            ${c.section !== 'general' ? `<button type="button" class="tag tag-link" data-goto="${esc(c.section)}">${esc(COMMENT_SECTIONS[c.section] || c.section)}</button>` : ''}
            ${(c.user_id === state.user.id || state.user.role === 'admin') ? `<button type="button" class="btn ghost sm c-del no-print" data-del="${c.id}" aria-label="${t('Удалить комментарий')}">${icon('trash')}</button>` : ''}
          </div>
          <div class="c-body">${esc(c.body)}</div>
        </div>
      </li>`).join('')}</ul>`
      : `<p class="subtle" style="padding:6px 0">${t('Комментариев пока нет.')} ${state.user.role === 'teacher' ? t('Здесь можно записать свою рефлексию по уроку или ответить методисту.') : t('Оставьте наблюдение или вопрос учителю — он увидит его в отчёте.')}</p>`;
  }
  list.addEventListener('click', async e => {
    const g = e.target.closest('[data-goto]');
    if (g) return showTab(g.dataset.goto);
    const d = e.target.closest('[data-del]');
    if (!d) return;
    if (!await confirmDialog({ title: t('Удалить комментарий?'), text: t('Комментарий будет удалён для всех.'), confirm: t('Удалить'), danger: true })) return;
    try { await api('DELETE', `/api/comments/${d.dataset.del}`); await load(); } catch (err) { toast(err.message, 'bad'); }
  });
  const form = $('#commentForm');
  const submit = async () => {
    const body = $('#cBody').value.trim();
    if (!body) return;
    const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    try {
      await api('POST', `/api/lessons/${lessonId}/comments`, { body, section: $('#cSection').value });
      $('#cBody').value = '';
      await load();
    } catch (err) { toast(err.message, 'bad'); }
    btn.disabled = false;
  };
  form.addEventListener('submit', e => { e.preventDefault(); submit(); });
  $('#cBody').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  try { await load(); } catch { list.innerHTML = t('<p class="subtle">Не удалось загрузить комментарии.</p>'); }
}

/* ------------------------------------------------------------------ */
/* Уведомления                                                         */
/* ------------------------------------------------------------------ */

function setUnread(n) {
  state.unread = n || 0;
  for (const id of ['#unreadBadge', '#unreadBadgeTop']) {
    const b = $(id); if (!b) continue;
    b.textContent = state.unread > 99 ? '99+' : String(state.unread);
    b.hidden = !state.unread;
  }
  const bell = $('#topBell'); if (bell) bell.hidden = !state.unread;
  document.title = (state.unread ? `(${state.unread}) ` : '') + 'MYP Lesson Analyzer';
}

function notificationText(n) {
  const d = n.data || {};
  if (n.kind === 'comment') return t(t('{actor} оставил(а) комментарий к уроку «{lesson}»'), { actor: d.actor_name, lesson: d.lesson_title });
  if (n.kind === 'lesson_done') return t(t('Отчёт по уроку «{lesson}» готов'), { lesson: d.lesson_title });
  if (n.kind === 'lesson_error') return t(t('Анализ урока «{lesson}» остановился с ошибкой'), { lesson: d.lesson_title });
  return n.kind;
}

async function viewNotifications() {
  renderShell('notifications', `<div class="page narrow" id="notifPage"></div>`);
  async function load() {
    const { notifications, unread } = await api('GET', '/api/notifications');
    setUnread(unread);
    $('#notifPage').innerHTML = `
      <div class="page-head">
        <div><h1>${t('Уведомления')}</h1><p class="lede">${t('Новые комментарии к урокам и готовность отчётов.')}</p></div>
        ${unread ? `<div class="head-actions"><button class="btn" id="readAll">${icon('check')}${t('Отметить все прочитанными')}</button></div>` : ''}
      </div>
      ${notifications.length ? `<div class="panel"><ul class="notif-list">${notifications.map(n => `
        <li class="${n.read_at ? '' : 'unread'}">
          <a href="#/lessons/${esc(n.lesson_id)}${n.kind === 'comment' ? '?tab=discussion' : ''}" data-nid="${n.id}">
            <span class="n-icon ${n.kind}">${icon(n.kind === 'comment' ? 'chat' : n.kind === 'lesson_error' ? 'alert' : 'check')}</span>
            <span style="min-width:0;flex:1">
              <span class="n-text">${esc(notificationText(n))}</span>
              ${n.data?.excerpt ? `<span class="n-excerpt">${esc(n.data.excerpt)}</span>` : ''}
              <span class="n-time">${esc(fmtTimestamp(n.created_at))}</span>
            </span>
            ${n.read_at ? '' : t('<span class="n-dot" aria-label="Не прочитано"></span>')}
          </a>
        </li>`).join('')}</ul></div>`
      : `<div class="panel empty"><h2>${t('Уведомлений нет')}</h2><p>${t('Здесь появятся комментарии методиста и сообщения о готовых отчётах.')}</p></div>`}`;
    $('#readAll')?.addEventListener('click', async () => {
      const r = await api('POST', '/api/notifications/read', { all: true }); setUnread(r.unread); load();
    });
    $$('[data-nid]').forEach(a => a.addEventListener('click', () => {
      api('POST', '/api/notifications/read', { ids: [+a.dataset.nid] }).then(r => setUnread(r.unread)).catch(() => {});
    }));
  }
  await load();
}

setInterval(async () => {
  if (!state.user || document.visibilityState !== 'visible') return;
  try {
    const r = await fetch('/api/notifications/unread', { credentials: 'same-origin' });
    if (!r.ok) return;
    const { unread } = await r.json();
    if (unread > (state.unread || 0)) toast(t(t('Новое уведомление')));
    setUnread(unread);
  } catch { /* нет сети — проверим позже */ }
}, 60000);

/* ------------------------------------------------------------------ */

(async function boot() {
  try {
    const me = await api('GET', '/api/auth/me');
    state.user = me.user;
    state.unread = me.unread || 0;
    state.emailAvailable = !!me.email_available;
  } catch { state.user = null; }
  if (state.user) {
    // Язык: выбор на этом устройстве важнее; на новом устройстве берём сохранённый в профиле.
    let local = null;
    try { local = localStorage.getItem('uiLang'); } catch { /* */ }
    if (local && local !== state.user.ui_language) api('POST', '/api/auth/preferences', { ui_language: local }).catch(() => {});
    else if (!local && state.user.ui_language && state.user.ui_language !== LANG) return setUiLang(state.user.ui_language, { save: false });
  }
  setUnread(state.unread);
  if (state.user) loadOptions().catch(() => {});
  window.addEventListener('hashchange', route);
  route();
})();
