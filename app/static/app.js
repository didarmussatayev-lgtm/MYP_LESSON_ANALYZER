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
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && Array.isArray(data.detail)) return 'Проверьте заполнение формы.';
  if (status === 413) return 'Файл слишком большой.';
  return 'Не удалось выполнить запрос. Проверьте соединение и попробуйте ещё раз.';
}

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function confirmDialog({ title, text, confirm = 'Подтвердить', danger = false }) {
  return new Promise(resolve => {
    const d = document.createElement('dialog');
    d.innerHTML = `
      <div class="d-body"><h2>${esc(title)}</h2><p class="muted">${esc(text)}</p></div>
      <div class="d-actions">
        <button class="btn" value="cancel" data-act="no">Отмена</button>
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
  if (h) return `${h} ч ${m} мин`;
  return s && m < 10 ? `${m} мин ${s} с` : `${m} мин`;
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

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
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
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}
function fmtSize(bytes) {
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1).replace('.', ',') + ' МБ';
  return Math.max(1, Math.round(bytes / 1024)) + ' КБ';
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
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ''}</svg>`;
}

/* ------------------------------------------------------------------ */
/* Словари отображения                                                 */
/* ------------------------------------------------------------------ */

const CATEGORY = {
  recall: { label: 'Воспроизведение', hint: 'вспомнить факт или определение' },
  understanding: { label: 'Понимание', hint: 'объяснить своими словами' },
  application: { label: 'Применение', hint: 'перенести правило на новую ситуацию' },
  analysis: { label: 'Анализ', hint: 'сравнить, найти причины, оценить доводы' },
};
const CATEGORY_ORDER = ['recall', 'understanding', 'application', 'analysis'];

const LEVEL = {
  level_1: { short: 'Уровень 1', label: 'Учитель спрашивает — ученик отвечает', cls: 'l1' },
  level_2: { short: 'Уровень 2', label: 'Учитель ставит вопрос — ученики исследуют', cls: 'l2' },
  level_4: { short: 'Уровень 4', label: 'Ученики формулируют вопрос, исследуют и рефлексируют', cls: 'l4' },
};
const LEVEL_COLOR = { level_1: 'var(--level-1)', level_2: 'var(--level-2)', level_4: 'var(--level-4)' };

const ALIGN = {
  'Strong': { label: 'Реализовано', cls: 'good' },
  'Partial': { label: 'Частично', cls: 'warn' },
  'Not observed': { label: 'Не наблюдалось', cls: '' },
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
  queued: { label: 'В очереди', cls: 'info run' },
  running: { label: 'Обработка', cls: 'info run' },
  done: { label: 'Готов', cls: 'good' },
  error: { label: 'Ошибка', cls: 'bad' },
};
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
  [/^\/lessons\/([a-f0-9]+)$/, viewLesson],
  [/^\/users$/, viewUsers, { admin: true }],
  [/^\/account$/, viewAccount],
];

async function route() {
  clearInterval(pollTimer); pollTimer = null;
  navCleanup.forEach(fn => fn()); navCleanup = [];
  hideTip();

  const path = location.hash.replace(/^#/, '') || '/';
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
      renderShell('', `<div class="page"><div class="panel empty"><h2>Не удалось загрузить страницу</h2><p>${esc(err.message)}</p><a class="btn" href="#/">К списку уроков</a></div></div>`);
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
      <aside class="sidebar" aria-label="Навигация">
        <div class="brand">
          <div class="brand-mark">MYP</div>
          <div><div class="brand-name">Lesson Analyzer</div><div class="brand-sub">Анализ уроков IB MYP</div></div>
        </div>
        <nav class="nav">
          ${nav('/', 'lessons', 'list', 'Уроки')}
          ${nav('/new', 'new', 'plus', 'Новый анализ')}
          ${u.role === 'admin' ? `<div class="nav-section">Администрирование</div>${nav('/users', 'users', 'users', 'Пользователи')}` : ''}
        </nav>
        <div class="sidebar-foot">
          <div class="user-chip">
            <div class="avatar">${esc(initials(u.name, u.email))}</div>
            <div style="min-width:0">
              <div class="name">${esc(u.name || u.email)}</div>
              <div class="role">${u.role === 'admin' ? 'Администратор' : 'Учитель'}</div>
            </div>
          </div>
          <div class="foot-links">
            <a href="#/account" ${active === 'account' ? 'aria-current="page"' : ''}>Профиль</a>
            <button type="button" id="logoutBtn">Выйти</button>
          </div>
        </div>
      </aside>
      <div class="scrim" id="scrim"></div>
      <div class="main">
        <header class="topbar">
          <button class="btn ghost icon-btn" id="menuBtn" aria-label="Открыть меню">${icon('menu')}</button>
          <div class="brand-mark">MYP</div>
          <div class="brand-name">Lesson Analyzer</div>
        </header>
        <main id="view">${content}</main>
      </div>
    </div>`;
  const shell = $('#shell');
  $('#menuBtn').onclick = () => shell.classList.add('nav-open');
  $('#scrim').onclick = () => shell.classList.remove('nav-open');
  $$('.nav a, .foot-links a').forEach(a => a.addEventListener('click', () => shell.classList.remove('nav-open')));
  $('#logoutBtn').onclick = async () => {
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
function hideTip() { const t = $('#tooltip'); if (t) t.hidden = true; }
document.addEventListener('mousemove', e => {
  const t = e.target.closest?.('[data-tip]');
  if (t) showTip(t, e.clientX, e.clientY); else hideTip();
});
document.addEventListener('focusin', e => {
  const t = e.target.closest?.('[data-tip]');
  if (t) { const r = t.getBoundingClientRect(); showTip(t, r.left + r.width / 2, r.bottom); }
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
          <div><div class="brand-name">Lesson Analyzer</div><div class="brand-sub">Анализ уроков IB MYP</div></div>
        </div>
        <form class="panel" id="loginForm" novalidate>
          <h1>Вход</h1>
          <p class="muted" style="margin-bottom:18px">Используйте учётную запись, выданную администратором.</p>
          ${me.needs_setup ? `<div class="callout warn" style="margin-bottom:16px">${icon('alert')}<div>Учётных записей пока нет. Задайте переменные окружения ADMIN_EMAIL и ADMIN_PASSWORD на сервере и перезапустите его.</div></div>` : ''}
          <div class="stack">
            <div class="field"><label for="email">Email</label><input class="input" id="email" name="email" type="email" autocomplete="username" required></div>
            <div class="field"><label for="password">Пароль</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required></div>
            <div class="form-error" id="loginError" role="alert"></div>
            <button class="btn primary lg" style="width:100%" type="submit">Войти</button>
          </div>
        </form>
        <p class="auth-foot">Забыли пароль? Обратитесь к администратору.</p>
      </div>
    </div>`;
  $('#email').focus();
  $('#loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type=submit]');
    const errEl = $('#loginError');
    errEl.textContent = '';
    const email = $('#email').value.trim(), password = $('#password').value;
    if (!email || !password) { errEl.textContent = 'Введите email и пароль.'; return; }
    btn.disabled = true;
    try {
      const data = await api('POST', '/api/auth/login', { email, password });
      state.user = data.user;
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
  const isAdmin = state.user.role === 'admin';
  const scope = isAdmin ? state.lessonsScope : 'mine';
  renderShell('lessons', `
    <div class="page">
      <div class="page-head">
        <div><h1>Уроки</h1><p class="lede">История проанализированных уроков. Откройте урок, чтобы посмотреть отчёт.</p></div>
        <div class="head-actions"><a class="btn primary" href="#/new">${icon('plus')}Новый анализ</a></div>
      </div>
      <div id="lessonsBody"><div class="panel panel-pad stack"><div class="skeleton" style="width:40%"></div><div class="skeleton"></div><div class="skeleton" style="width:70%"></div></div></div>
    </div>`);

  const { lessons } = await api('GET', `/api/lessons?scope=${scope}`);
  const body = $('#lessonsBody');

  if (!lessons.length && scope === 'mine') {
    body.innerHTML = `
      <div class="panel empty">
        <h2>Пока нет ни одного урока</h2>
        <p>Загрузите аудиозапись урока и план — через несколько минут здесь появится отчёт: время речи, вопросы учителя, уровни inquiry и соответствие плану.</p>
        <a class="btn primary" href="#/new">${icon('plus')}Проанализировать урок</a>
        ${isAdmin ? `<p style="margin-top:18px"><button class="btn ghost sm" id="seeAll">Показать уроки всех учителей</button></p>` : ''}
      </div>`;
    $('#seeAll')?.addEventListener('click', () => { state.lessonsScope = 'all'; localSet('lessonsScope', 'all'); viewLessons(); });
    return;
  }

  const subjects = [...new Set(lessons.map(l => l.subject).filter(Boolean))].sort();
  body.innerHTML = `
    <div class="toolbar">
      <input class="input" id="q" type="search" placeholder="Поиск по теме, учителю, предмету" aria-label="Поиск">
      <select class="select" id="fSubject" aria-label="Предмет"><option value="">Все предметы</option>${subjects.map(s => `<option>${esc(s)}</option>`).join('')}</select>
      <select class="select" id="fStatus" aria-label="Статус"><option value="">Все статусы</option>${Object.entries(STATUS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select>
      ${isAdmin ? `<div class="seg" role="group" aria-label="Чьи уроки" style="margin-left:auto">
        <button type="button" data-scope="mine" aria-pressed="${scope === 'mine'}">Мои</button>
        <button type="button" data-scope="all" aria-pressed="${scope === 'all'}">Все учителя</button></div>` : ''}
    </div>
    <div class="panel lessons-table"><div class="table-wrap"><table class="data">
      <thead><tr>
        <th>Дата</th><th>Урок</th><th>Учитель</th><th class="num">Длительность</th>
        <th class="num">Речь учителя</th><th class="num">Вопросы</th><th>Статус</th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table></div></div>
    <div class="lesson-cards" id="cards"></div>
    <p class="subtle" id="noMatch" style="display:none;padding:24px 4px">Ничего не найдено. Измените условия поиска.</p>`;

  $$('[data-scope]').forEach(b => b.addEventListener('click', () => {
    state.lessonsScope = b.dataset.scope; localSet('lessonsScope', b.dataset.scope); viewLessons();
  }));

  const title = l => l.lesson_title || l.subject || 'Урок без названия';
  const sub = l => [l.subject && l.lesson_title ? l.subject : '', l.grade].filter(Boolean).join(' · ');
  const date = l => fmtDate(l.lesson_date) || fmtTimestamp(l.created_at);
  const qText = s => s ? `${s.question_count}${s.higher_order_pct != null ? ` <span class="subtle">· ${s.higher_order_pct}% выс.</span>` : ''}` : '—';
  const progress = l => (l.status === 'running' && l.step_total) ? `<div class="cell-sub">Этап ${l.step} из ${l.step_total}</div>` : '';

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
        <td><div class="cell-title">${esc(title(l))}</div>${sub(l) ? `<div class="cell-sub">${esc(sub(l))}</div>` : ''}</td>
        <td>${esc(l.teacher_name || l.owner_name || '')}${scope === 'all' && l.owner_name && l.owner_name !== l.teacher_name ? `<div class="cell-sub">загрузил(а): ${esc(l.owner_name)}</div>` : ''}</td>
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
        ${s ? `<div class="stats"><span>${fmtDuration(s.duration_seconds)}</span><span>Учитель ${Math.round(s.teacher_pct ?? 0)}%</span><span>Вопросов ${s.question_count}</span></div>` : ''}
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
const DRAFT_FIELDS = ['lesson_title', 'subject', 'grade', 'subject_key', 'key_concept', 'global_context',
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
  const subjectOptions = Object.entries(o.subjects).map(([k, v]) => `<option value="${esc(k)}">${esc(v.label)}</option>`).join('');
  const sel = (name, items) => `<select class="select" id="${name}" name="${name}"><option value="">Не выбрано</option>${items.map(v => `<option>${esc(v)}</option>`).join('')}</select>`;

  renderShell('new', `
    <div class="page narrow">
      <div class="page-head">
        <div><h1>Новый анализ урока</h1>
        <p class="lede">Загрузите запись и заполните план урока. Обработка занимает 5–15 минут; страницу можно закрыть — отчёт появится в списке уроков.</p></div>
      </div>
      <form id="lessonForm" novalidate>
        <section class="form-section">
          <div class="form-section-head"><span class="step-no">01</span><h2>Запись урока</h2>
            <p>Обязательна запись с микрофона учителя. Вторая запись из центра класса заметно повышает точность разделения реплик.</p></div>
          <div class="stack">
            ${dropzone({ name: 'teacher_track', title: 'Запись учителя', sub: 'Петличный микрофон или телефон у учителя · mp3, m4a, wav, ogg', accept: 'audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.flac', iconName: 'mic', required: true })}
            ${dropzone({ name: 'classroom_track', title: 'Запись класса <span class="opt">— по желанию</span>', sub: 'Телефон в центре класса', accept: 'audio/*,.m4a,.mp3,.wav,.ogg,.webm,.aac,.flac', iconName: 'mic' })}
            ${dropzone({ name: 'pptx', title: 'Презентация <span class="opt">— по желанию</span>', sub: 'Файл .pptx, используется для привязки слайдов к ходу урока', accept: '.pptx', iconName: 'slides' })}
            <div class="callout" id="singleTrackNote">${icon('info')}<div>Если загружена только запись учителя, роли «учитель / ученик» определяются по смыслу речи. Это менее точно, чем при двух записях, — в отчёте будет соответствующая пометка.</div></div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section-head"><span class="step-no">02</span><h2>Об уроке</h2>
            <p>Эти данные попадут в заголовок отчёта и помогут найти урок в истории.</p></div>
          <div class="form-grid">
            <div class="field span-2"><label for="lesson_title">Тема урока</label><input class="input" id="lesson_title" name="lesson_title" placeholder="Например: Фотосинтез и дыхание клетки"></div>
            <div class="field"><label for="subject_key">Предметная группа MYP</label><select class="select" id="subject_key" name="subject_key">${subjectOptions}</select></div>
            <div class="field"><label for="subject">Предмет</label><input class="input" id="subject" name="subject" placeholder="Biology, English B…"></div>
            <div class="field"><label for="grade">Класс <span class="opt">/ MYP year</span></label><input class="input" id="grade" name="grade" placeholder="MYP 3, 8A…"></div>
            <div class="field"><label for="lesson_date">Дата урока</label><input class="input" id="lesson_date" name="lesson_date" type="date" value="${todayIso()}"></div>
            <div class="field span-2"><label for="teacher_name">Учитель</label><input class="input" id="teacher_name" name="teacher_name" value="${esc(state.user.name)}"></div>
            <div class="span-2" id="observabilityWarn"></div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section-head"><span class="step-no">03</span><h2>План урока</h2>
            <p>Из unit planner. С этими полями отчёт сравнит запланированное с тем, что реально прозвучало на уроке. Можно заполнить частично.</p></div>
          <div class="form-grid">
            <div class="field"><label for="key_concept">Key concept</label>${sel('key_concept', o.key_concepts)}</div>
            <div class="field"><label for="global_context">Global context</label>${sel('global_context', o.global_contexts)}</div>
            <div class="field span-2"><span class="label">Related concepts</span><div id="relatedConcepts"></div></div>
            <div class="field span-2"><label for="statement_of_inquiry">Statement of inquiry</label><textarea class="textarea" id="statement_of_inquiry" name="statement_of_inquiry" rows="2"></textarea></div>
            <div class="field span-2"><label for="inquiry_questions">Inquiry questions</label><textarea class="textarea" id="inquiry_questions" name="inquiry_questions" rows="3" placeholder="Factual: …&#10;Conceptual: …&#10;Debatable: …"></textarea></div>
            <div class="field span-2"><label for="learning_objectives">Learning objectives</label><textarea class="textarea" id="learning_objectives" name="learning_objectives" rows="2"></textarea></div>
            <div class="field span-2"><span class="label">Assessment criteria</span><div id="assessmentCriteria"></div></div>
            <div class="field span-2"><span class="label">ATL skills</span>
              ${chipGroup('atl', Object.values(o.atl_skill_clusters).map(c => c.label))}
              <input class="input" name="atl_skills_detail" style="margin-top:8px" placeholder="Уточнение, например: critical thinking — сравнение доказательств">
            </div>
            <div class="field span-2"><span class="label">Learner profile</span>${chipGroup('learner', o.learner_profile_attributes)}</div>
            <div class="field span-2"><label for="learning_experiences">Learning experiences</label><textarea class="textarea" id="learning_experiences" name="learning_experiences" rows="3" placeholder="Что делают ученики на уроке: эксперимент в группах, обсуждение, презентация…"></textarea></div>
          </div>
        </section>

        <div class="submit-bar">
          <div class="upload-state" id="uploadState"></div>
          <button type="button" class="btn ghost" id="clearDraft">Очистить форму</button>
          <button type="submit" class="btn primary lg" id="submitBtn">Начать анализ</button>
        </div>
      </form>
    </div>`);

  const form = $('#lessonForm');

  function refreshSubject() {
    const subj = o.subjects[$('#subject_key').value];
    if (!subj) return;
    $('#relatedConcepts').innerHTML = chipGroup('related', subj.related_concepts);
    $('#assessmentCriteria').innerHTML = chipGroup('criteria',
      subj.assessment_criteria.map(c => ({ value: `Criterion ${c.code}: ${c.label}`, label: `${c.code} · ${c.label}` })));
    const note = subj.audio_observability_note;
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
    if (!await confirmDialog({ title: 'Очистить форму?', text: 'Все заполненные поля и выбранные файлы будут сброшены.', confirm: 'Очистить' })) return;
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
      $('.dz-sub', dz).innerHTML = f ? `${fmtSize(f.size)} · нажмите, чтобы заменить` : sub;
      $('.dz-clear', dz)?.remove();
      if (f) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'btn ghost sm dz-clear'; b.textContent = 'Убрать';
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

  form.addEventListener('submit', e => {
    e.preventDefault();
    const teacher = form.elements.teacher_track.files[0];
    if (!teacher) {
      toast('Добавьте запись учителя — без неё анализ невозможен.', 'bad');
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
    for (const k of ['classroom_track', 'pptx']) {
      const f = fd.get(k); if (f && f.size === 0) fd.delete(k);
    }

    const btn = $('#submitBtn'), st = $('#uploadState');
    btn.disabled = true;
    st.innerHTML = `Загрузка файлов… <span id="pct">0%</span><div class="progress"><i id="bar"></i></div>`;

    // XHR, а не fetch: нужен прогресс загрузки больших аудиофайлов.
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/lessons');
    xhr.upload.onprogress = ev => {
      if (!ev.lengthComputable) return;
      const p = Math.round(100 * ev.loaded / ev.total);
      $('#pct') && ($('#pct').textContent = p + '%');
      $('#bar') && ($('#bar').style.width = p + '%');
      if (p >= 100) st.firstChild.textContent = 'Файлы загружены, запускаем анализ… ';
    };
    xhr.onload = () => {
      let data = null; try { data = JSON.parse(xhr.responseText); } catch { /* */ }
      if (xhr.status >= 200 && xhr.status < 300 && data?.id) {
        localDel(DRAFT_KEY);
        toast('Анализ запущен. Можно закрыть страницу — отчёт сохранится.');
        go('/lessons/' + data.id);
      } else {
        if (xhr.status === 401) { state.user = null; return go('/login'); }
        st.innerHTML = `<span style="color:var(--bad)">${esc(errorText(data, xhr.status))}</span>`;
        btn.disabled = false;
      }
    };
    xhr.onerror = () => {
      st.innerHTML = `<span style="color:var(--bad)">Соединение прервалось во время загрузки. Проверьте интернет и попробуйте ещё раз.</span>`;
      btn.disabled = false;
    };
    xhr.send(fd);
  });
}

/* ------------------------------------------------------------------ */
/* Урок: обработка и отчёт                                             */
/* ------------------------------------------------------------------ */

const STEP_NAMES = [
  'Синхронизация аудиодорожек', 'Расшифровка речи', 'Разметка реплик учителя и учеников',
  'Анализ вопросов учителя', 'Определение уровней inquiry', 'Сравнение плана и урока',
  'Формулирование выводов', 'Подготовка отчёта',
];

async function viewLesson(id) {
  await loadOptions().catch(() => {});
  const { lesson } = await api('GET', `/api/lessons/${id}`);
  const title = lesson.lesson_title || lesson.subject || 'Урок без названия';
  const subjLabel = state.options?.subjects?.[lesson.subject_key]?.label;
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
          <div class="crumbs"><a href="#/">Уроки</a> / ${statusBadge(lesson.status)}</div>
          <h1>${esc(title)}</h1>
          <div class="meta-line">${meta.map(m => `<span>${esc(m)}</span>`).join('<span class="subtle">·</span>')}</div>
        </div>
        <div class="head-actions">
          ${done ? `<a class="btn" href="/api/lessons/${id}/report.docx">${icon('download')}Word</a>
                    <button class="btn" id="printBtn">${icon('print')}Печать / PDF</button>` : ''}
          ${lesson.status === 'done' || lesson.status === 'error' ? `<button class="btn ghost icon-btn" id="deleteBtn" aria-label="Удалить урок" data-tip="Удалить урок">${icon('trash')}</button>` : ''}
        </div>
      </div>
      <div id="lessonBody"></div>
    </div>`);

  $('#printBtn')?.addEventListener('click', () => window.print());
  $('#deleteBtn')?.addEventListener('click', async () => {
    const ok = await confirmDialog({ title: 'Удалить урок?', text: 'Отчёт, расшифровка и все данные урока будут удалены без возможности восстановления.', confirm: 'Удалить', danger: true });
    if (!ok) return;
    try { await api('DELETE', `/api/lessons/${id}`); toast('Урок удалён.'); go('/'); }
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
        <div class="panel-head"><h2>${isErr ? 'Обработка остановлена' : lesson.status === 'queued' ? 'Урок в очереди' : 'Идёт анализ'}</h2></div>
        <div class="panel-body">
          ${isErr ? `<div class="callout bad" style="margin-bottom:14px">${icon('alert')}<div>${esc(lesson.error_public || 'Произошла ошибка.')}</div></div>` : ''}
          <ol class="steps">
            ${STEP_NAMES.map((n, i) => {
              const idx = i + 1;
              const cls = idx < current ? 'done' : idx === current ? (isErr ? 'failed' : 'active') : '';
              return `<li class="${cls}"><span class="mark">${cls === 'done' ? icon('check') : cls === 'failed' ? icon('x') : ''}</span>${esc(n)}</li>`;
            }).join('')}
          </ol>
          ${isErr ? `<div style="margin-top:14px;display:flex;gap:8px"><button class="btn primary" id="retryBtn">${icon('refresh')}Повторить анализ</button></div>
                     <p class="subtle" style="font-size:12.5px;margin-top:8px">Повторный запуск продолжит с последнего завершённого этапа — расшифровка не будет оплачена повторно.</p>` : ''}
        </div>
      </div>
      <div class="stack">
        ${!isErr ? `<div class="callout info">${icon('info')}<div>Эту страницу можно закрыть: анализ выполняется на сервере, а готовый отчёт появится в списке уроков. Обычно это занимает 5–15 минут в зависимости от длины записи.</div></div>` : ''}
        <div class="panel panel-pad">
          <details class="disclosure"><summary>Технический журнал</summary><pre class="log">${esc(log || 'Пока пусто.')}</pre></details>
          ${lesson.error_detail ? `<details class="disclosure" style="margin-top:10px"><summary>Подробности ошибки (видны администратору)</summary><pre class="log">${esc(lesson.error_detail)}</pre></details>` : ''}
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
        if (l.status === 'done') { toast('Отчёт готов.'); viewLesson(l.id); }
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
    ['summary', 'Сводка'],
    ['plan', 'План и факт', alignTotal],
    ['questions', 'Вопросы', questions.length],
    ['inquiry', 'Inquiry', episodes.length],
    ['transcript', 'Расшифровка', utts.length],
    ['method', 'Методология'],
  ];

  $('#lessonBody').innerHTML = `
    <p class="draft-note">${icon('info')}Черновик, подготовленный ИИ. Проверьте выводы перед обсуждением с учителем или коучем.</p>

    <div class="kpis">
      <div class="panel kpi"><div class="k-label">Длительность записи</div><div class="k-value">${fmtDuration(duration)}</div>
        <div class="k-note">${tt.teacher_utterance_count ?? 0} реплик учителя · ${tt.student_utterance_count ?? 0} учеников</div></div>
      <div class="panel kpi"><div class="k-label">Речь учителя</div><div class="k-value">${tt.teacher_pct != null ? Math.round(tt.teacher_pct) : '—'}<small>%</small></div>
        <div class="k-note">от общего времени урока</div></div>
      <div class="panel kpi"><div class="k-label">Вопросы учителя</div><div class="k-value">${questions.length}</div>
        <div class="k-note">${s.higher_order_pct != null ? `${s.higher_order_pct}% — применение и анализ` : 'вопросов не найдено'}</div></div>
      <div class="panel kpi"><div class="k-label">Соответствие плану</div><div class="k-value">${ac['Strong'] || 0}<small>/ ${alignTotal}</small></div>
        <div class="k-note">реализовано полностью${ac['Partial'] ? ` · ${ac['Partial']} частично` : ''}</div></div>
    </div>

    <div class="tabs" role="tablist">
      ${tabs.map(([k, l, c], i) => `<button role="tab" id="tab-${k}" aria-controls="panel-${k}" aria-selected="${i === 0}" data-tab="${k}">${l}${c != null ? `<span class="count">${c}</span>` : ''}</button>`).join('')}
    </div>

    <div class="tab-panel" id="panel-summary" role="tabpanel" data-print-title="Сводка">${summaryPanel(r, tt, duration)}</div>
    <div class="tab-panel" id="panel-plan" role="tabpanel" hidden data-print-title="План и факт">${planPanel(rows, r.planned || lesson.planned || {})}</div>
    <div class="tab-panel" id="panel-questions" role="tabpanel" hidden data-print-title="Вопросы учителя">${questionsPanel(questions)}</div>
    <div class="tab-panel" id="panel-inquiry" role="tabpanel" hidden data-print-title="Уровни inquiry">${inquiryPanel(episodes, duration)}</div>
    <div class="tab-panel transcript-panel" id="panel-transcript" role="tabpanel" hidden>${transcriptPanel(utts, r.single_track_mode)}</div>
    <div class="tab-panel" id="panel-method" role="tabpanel" hidden data-print-title="Методология"><div class="panel panel-pad prose"><p>${esc(r.methodology_notes || '')}</p></div></div>
  `;

  const showTab = key => {
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
    const t = parseTs(b.dataset.jump);
    if (t == null) return;
    showTab('transcript');
    resetTranscriptFilters();
    const items = $$('.transcript .u');
    let target = items[0];
    for (const el of items) { if (+el.dataset.start <= t + 0.5) target = el; else break; }
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.classList.add('flash');
      setTimeout(() => target.classList.remove('flash'), 1600);
    }
  });

  bindQuestionFilter();
  bindTranscript(utts);
}

function summaryPanel(r, tt, duration) {
  const refl = r.reflection || {};
  const total = duration || 1;
  const teacher = tt.teacher_seconds || 0;
  const student = tt.student_speech_seconds || 0;
  const silence = tt.silence_attributed_to_student_seconds ?? Math.max(0, total - teacher - student);
  const pct = v => Math.round(100 * v / total);
  const seg = (v, color, label, cls = '') => v > 0 ? `<div class="${cls}" style="flex:${v};background:${color}" tabindex="0" data-tip="<b>${label}</b><br>${fmtDuration(v)} · ${pct(v)}%"></div>` : '';
  const list = items => items?.length ? `<ol class="points">${items.map(x => `<li>${esc(x)}</li>`).join('')}</ol>` : '<p class="subtle">Нет данных.</p>';

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>Кто говорит на уроке</h2><span class="hint">доля от ${fmtDuration(total)}</span></div>
      <div class="panel-body">
        <div class="bar-stack" role="img" aria-label="Учитель ${pct(teacher)}%, ученики ${pct(student)}%, без речи ${pct(silence)}%">
          ${seg(teacher, 'var(--series-1)', 'Учитель')}
          ${seg(student, 'var(--series-2)', 'Ученики')}
          ${seg(silence, '', 'Без речи', 'fill-none')}
        </div>
        <div class="legend">
          <span><i class="sw" style="background:var(--series-1)"></i>Учитель <b>${pct(teacher)}%</b></span>
          <span><i class="sw" style="background:var(--series-2)"></i>Ученики <b>${pct(student)}%</b></span>
          <span><i class="sw sw-none"></i>Без речи — самостоятельная или групповая работа <b>${pct(silence)}%</b></span>
        </div>
        ${r.single_track_mode ? `<p class="subtle" style="font-size:12.5px;margin-top:10px">Только запись учителя: роли определены по смыслу речи, точность ниже.</p>` : ''}
      </div>
    </div>

    <div class="grid-2">
      <div class="panel panel-pad">
        <div class="col-head"><span class="dot" style="background:var(--good)"></span><h2 class="section-title">Сильные стороны</h2></div>
        ${list(refl.strengths)}
      </div>
      <div class="panel panel-pad">
        <div class="col-head"><span class="dot" style="background:var(--warn)"></span><h2 class="section-title">Зоны роста</h2></div>
        ${list(refl.areas_for_development)}
      </div>
    </div>

    ${refl.suggested_next_lesson_strategy ? `<div class="next-step"><div class="label">Рекомендация на следующий урок</div><p>${esc(refl.suggested_next_lesson_strategy)}</p></div>` : ''}

    ${r.intended_vs_enacted_summary ? `<div class="panel"><div class="panel-head"><h2>Заявленный подход и реальная практика</h2></div><div class="panel-body prose"><p>${esc(r.intended_vs_enacted_summary)}</p></div></div>` : ''}
  </div>`;
}

function planPanel(rows, planned) {
  if (!rows.length) return `<div class="panel empty"><h2>Сравнение с планом не выполнено</h2><p>План урока не был заполнен или модель не вернула результат.</p></div>`;
  return `<div class="panel"><div class="table-wrap"><table class="data align-table">
    <thead><tr><th>Пункт плана</th><th>Запланировано</th><th>Что наблюдалось на уроке</th><th>Оценка</th></tr></thead>
    <tbody>${rows.map(row => {
      const a = ALIGN[row.alignment] || { label: row.alignment || '—', cls: '' };
      const plannedText = row.planned || planned[row.field] || '';
      return `<tr>
        <td>${esc(FIELD_LABELS[row.field] || row.field)}</td>
        <td data-l="Запланировано">${plannedText ? esc(plannedText) : '<span class="subtle">не указано</span>'}</td>
        <td data-l="Наблюдалось">${row.observed_evidence ? esc(row.observed_evidence) : '<span class="subtle">свидетельств не найдено</span>'}</td>
        <td data-l="Оценка"><span class="badge ${a.cls}">${esc(a.label)}</span></td>
      </tr>`;
    }).join('')}</tbody>
  </table></div></div>`;
}

function questionsPanel(questions) {
  if (!questions.length) return `<div class="panel empty"><h2>Вопросы не найдены</h2><p>В репликах учителя не обнаружено вопросов, обращённых к ученикам.</p></div>`;
  const counts = {};
  questions.forEach(q => { counts[q.category] = (counts[q.category] || 0) + 1; });
  const cats = [...CATEGORY_ORDER.filter(c => counts[c]), ...Object.keys(counts).filter(c => !CATEGORY_ORDER.includes(c))];
  const max = Math.max(...Object.values(counts));
  const n = questions.length;

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>Типы вопросов</h2><span class="hint">${n} ${plural(n, 'вопрос', 'вопроса', 'вопросов')}</span></div>
      <div class="panel-body">
        <div class="hbars">
          ${CATEGORY_ORDER.concat(cats.filter(c => !CATEGORY_ORDER.includes(c))).map(c => {
            const v = counts[c] || 0;
            const info = CATEGORY[c] || { label: c, hint: '' };
            return `<div class="hb-label">${esc(info.label)} <span class="subtle" style="font-size:12px">— ${esc(info.hint)}</span></div>
              <div class="hb-track"><div class="hb-fill" style="width:${max ? 100 * v / max : 0}%" tabindex="0" data-tip="<b>${esc(info.label)}</b><br>${v} из ${n} · ${Math.round(100 * v / n)}%"></div></div>
              <div class="hb-val">${v} · ${Math.round(100 * v / n)}%</div>`;
          }).join('')}
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Все вопросы</h2></div>
      <div class="panel-body">
        <div class="toolbar no-print" id="qFilter">
          <div class="seg" role="group" aria-label="Фильтр по типу">
            <button type="button" data-cat="" aria-pressed="true">Все</button>
            ${cats.map(c => `<button type="button" data-cat="${esc(c)}" aria-pressed="false">${esc(CATEGORY[c]?.label || c)}</button>`).join('')}
          </div>
        </div>
        <ul class="item-list" id="qList">
          ${questions.map(q => `<li data-cat="${esc(q.category)}">
            <button class="ts" data-jump="${esc(q.timestamp)}" data-tip="Показать в расшифровке">${esc(q.timestamp || '—')}</button>
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
  if (!episodes.length) return `<div class="panel empty"><h2>Эпизоды не выделены</h2><p>Модель не смогла разделить урок на эпизоды.</p></div>`;
  const parsed = episodes.map(ep => ({ ...ep, s: parseTs(ep.start_timestamp) ?? 0, e: parseTs(ep.end_timestamp) }));
  const end = Math.max(duration || 0, ...parsed.map(p => p.e || 0)) || 1;
  const byLevel = {};
  parsed.forEach(p => { const d = Math.max(0, (p.e ?? p.s) - p.s); byLevel[p.level] = (byLevel[p.level] || 0) + d; });
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => fmtClock(f * end));

  return `<div class="stack">
    <div class="panel">
      <div class="panel-head"><h2>Ход урока по уровням inquiry</h2><span class="hint">наведите на отрезок, чтобы увидеть эпизод</span></div>
      <div class="panel-body">
        <div class="timeline" role="img" aria-label="Шкала эпизодов урока по уровням inquiry">
          ${parsed.map(p => {
            const left = 100 * p.s / end, width = Math.max(0.6, 100 * ((p.e ?? p.s) - p.s) / end);
            const lv = LEVEL[p.level] || { short: p.level, label: '' };
            return `<div class="seg-ep" style="left:${left}%;width:${width}%;background:${LEVEL_COLOR[p.level] || 'var(--series-none)'}" tabindex="0"
              data-jump="${esc(p.start_timestamp)}" data-tip="<b>${esc(p.start_timestamp)}–${esc(p.end_timestamp)} · ${esc(lv.short)}</b><br>${esc((p.rationale || '').slice(0, 180))}"></div>`;
          }).join('')}
        </div>
        <div class="time-axis">${ticks.map((t, i) => `<span style="left:${i * 25}%">${t}</span>`).join('')}</div>
        <div class="legend">
          ${Object.entries(LEVEL).map(([k, v]) => `<span><i class="sw" style="background:${LEVEL_COLOR[k]}"></i>${v.short} — ${v.label} <b>${byLevel[k] ? Math.round(100 * byLevel[k] / end) + '%' : '0%'}</b></span>`).join('')}
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Эпизоды</h2></div>
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
  if (!utts.length) return `<div class="panel empty"><h2>Расшифровка недоступна</h2></div>`;
  return `<div class="panel">
    <div class="panel-body">
      <div class="toolbar">
        <input class="input" id="tSearch" type="search" placeholder="Поиск по расшифровке" aria-label="Поиск по расшифровке">
        <div class="seg" role="group" aria-label="Кто говорит" id="tWho">
          <button type="button" data-who="" aria-pressed="true">Все</button>
          <button type="button" data-who="Teacher" aria-pressed="false">Учитель</button>
          <button type="button" data-who="Student" aria-pressed="false">Ученики</button>
        </div>
        <span class="subtle" id="tCount" style="font-size:12.5px;margin-left:auto"></span>
      </div>
      ${singleTrack ? `<p class="subtle" style="font-size:12.5px;margin-bottom:10px">Роли определены по смыслу речи и могут быть неточны.</p>` : ''}
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
        <span class="who">${u.speaker === 'Student' ? 'Ученик' : 'Учитель'}</span>
        <span class="text">${text}</span></div>`;
    }).join('') || '<p class="subtle" style="padding:12px 8px">Ничего не найдено.</p>';
    $('#tCount').textContent = `${shown} ${plural(shown, 'реплика', 'реплики', 'реплик')}`;
  };
  let t;
  search.addEventListener('input', () => { clearTimeout(t); t = setTimeout(render, 150); });
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
        <div><h1>Пользователи</h1><p class="lede">Учётные записи учителей и администраторов. Самостоятельной регистрации нет — доступ выдаётся здесь.</p></div>
        <div class="head-actions"><button class="btn primary" id="addUser">${icon('plus')}Добавить пользователя</button></div>
      </div>
      <div id="usersBody"></div>
    </div>`);

  async function load() {
    const { users } = await api('GET', '/api/users');
    $('#usersBody').innerHTML = `<div class="panel"><div class="table-wrap"><table class="data">
      <thead><tr><th>Пользователь</th><th>Роль</th><th class="num">Уроков</th><th>Статус</th><th></th></tr></thead>
      <tbody>${users.map(u => `<tr>
        <td><div class="cell-title">${esc(u.name || '—')}</div><div class="cell-sub">${esc(u.email)}</div></td>
        <td>${u.role === 'admin' ? 'Администратор' : 'Учитель'}</td>
        <td class="num">${u.lesson_count}</td>
        <td>${u.is_active ? '<span class="badge good">Активен</span>' : '<span class="badge">Отключён</span>'}</td>
        <td class="num nowrap">
          <button class="btn sm ghost" data-act="pw" data-id="${u.id}">Сменить пароль</button>
          ${u.id !== state.user.id ? `<button class="btn sm ghost" data-act="role" data-id="${u.id}" data-role="${u.role}">${u.role === 'admin' ? 'Сделать учителем' : 'Сделать админом'}</button>
          <button class="btn sm ghost" data-act="toggle" data-id="${u.id}" data-active="${u.is_active}">${u.is_active ? 'Отключить' : 'Включить'}</button>` : ''}
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
        if (active && !await confirmDialog({ title: 'Отключить пользователя?', text: 'Он не сможет войти. Его уроки сохранятся.', confirm: 'Отключить', danger: true })) return;
        await api('PATCH', `/api/users/${id}`, { is_active: !active });
      } else if (b.dataset.act === 'role') {
        await api('PATCH', `/api/users/${id}`, { role: b.dataset.role === 'admin' ? 'teacher' : 'admin' });
      } else if (b.dataset.act === 'pw') {
        const pw = await passwordDialog();
        if (!pw) return;
        await api('PATCH', `/api/users/${id}`, { password: pw });
        toast('Пароль изменён. Передайте его пользователю.');
      }
      await load();
    } catch (err) { toast(err.message, 'bad'); }
  });

  $('#addUser').addEventListener('click', () => {
    const d = document.createElement('dialog');
    const pw = genPassword();
    d.innerHTML = `<form method="dialog" id="uForm">
      <div class="d-body stack">
        <h2>Новый пользователь</h2>
        <div class="field"><label for="uName">Имя и фамилия</label><input class="input" id="uName" required></div>
        <div class="field"><label for="uEmail">Email</label><input class="input" id="uEmail" type="email" required></div>
        <div class="field"><label for="uRole">Роль</label><select class="select" id="uRole"><option value="teacher">Учитель</option><option value="admin">Администратор</option></select></div>
        <div class="field"><label for="uPw">Временный пароль</label><input class="input mono" id="uPw" value="${pw}" required minlength="8">
          <span class="help">Передайте его пользователю — он сможет сменить пароль в профиле.</span></div>
        <div class="form-error" id="uErr"></div>
      </div>
      <div class="d-actions"><button type="button" class="btn" data-close>Отмена</button><button class="btn primary" type="submit">Создать</button></div>
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
        toast(`Пользователь создан: ${email}`);
        navigator.clipboard?.writeText(`Адрес: ${location.origin}\nEmail: ${email}\nПароль: ${pass}`).then(() => toast('Данные для входа скопированы в буфер обмена.')).catch(() => {});
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
      <div class="d-body stack"><h2>Новый пароль</h2>
        <div class="field"><label for="npw">Пароль (не короче 8 символов)</label><input class="input mono" id="npw" value="${genPassword()}" minlength="8" required></div></div>
      <div class="d-actions"><button type="button" class="btn" data-close>Отмена</button><button class="btn primary" type="submit">Сохранить</button></div></form>`;
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
      <div class="page-head"><div><h1>Профиль</h1><p class="lede">${esc(u.email)}</p></div></div>
      <div class="stack">
        <form class="panel panel-pad stack" id="nameForm">
          <h2 class="section-title">Имя</h2>
          <div class="field"><label for="pName">Отображается в отчётах по умолчанию</label><input class="input" id="pName" value="${esc(u.name)}"></div>
          <div><button class="btn" type="submit">Сохранить</button></div>
        </form>
        <form class="panel panel-pad stack" id="pwForm">
          <h2 class="section-title">Смена пароля</h2>
          <div class="field"><label for="cur">Текущий пароль</label><input class="input" id="cur" type="password" autocomplete="current-password" required></div>
          <div class="field"><label for="new1">Новый пароль</label><input class="input" id="new1" type="password" autocomplete="new-password" minlength="8" required><span class="help">Не короче 8 символов.</span></div>
          <div class="form-error" id="pwErr"></div>
          <div><button class="btn" type="submit">Сменить пароль</button></div>
        </form>
      </div>
    </div>`);
  $('#nameForm').addEventListener('submit', async e => {
    e.preventDefault();
    try { await api('POST', '/api/auth/profile', { name: $('#pName').value }); state.user.name = $('#pName').value.trim(); toast('Сохранено.'); viewAccount(); }
    catch (err) { toast(err.message, 'bad'); }
  });
  $('#pwForm').addEventListener('submit', async e => {
    e.preventDefault();
    $('#pwErr').textContent = '';
    try {
      await api('POST', '/api/auth/password', { current_password: $('#cur').value, new_password: $('#new1').value });
      e.target.reset(); toast('Пароль изменён.');
    } catch (err) { $('#pwErr').textContent = err.message; }
  });
}

/* ------------------------------------------------------------------ */
/* Запуск                                                              */
/* ------------------------------------------------------------------ */

(async function boot() {
  try {
    const me = await api('GET', '/api/auth/me');
    state.user = me.user;
  } catch { state.user = null; }
  if (state.user) loadOptions().catch(() => {});
  window.addEventListener('hashchange', route);
  route();
})();
