/* Админ-панель Dialam — vanilla JS, без внешних зависимостей. */
'use strict';

/* ============================== УТИЛИТЫ ============================== */

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function toast(msg, isError) {
  const t = document.createElement('div');
  t.className = 'toast' + (isError ? ' error' : '');
  t.textContent = msg;
  $('#toast-container').appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

async function api(path, opts) {
  opts = opts || {};
  const o = { headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
  if (opts.method) o.method = opts.method;
  if (opts.body !== undefined) o.body = JSON.stringify(opts.body);
  let res;
  try {
    res = await fetch(path, o);
  } catch (e) {
    toast('Сервер недоступен', true);
    throw e;
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* пустое тело */ }
  if (res.status === 401 && path !== '/api/login' && path !== '/api/me') {
    showLogin();
    throw new Error((data && data.error) || 'Сессия истекла');
  }
  if (!res.ok) {
    const err = new Error((data && data.error) || ('Ошибка ' + res.status));
    err.payload = data;
    throw err;
  }
  return data;
}

/* ============================== СОСТОЯНИЕ ============================== */

const state = {
  sites: [],          // список сайтов (с counts)
  siteId: null,       // текущий сайт
  view: 'overview',   // текущий раздел
  branches: [],       // филиалы текущего сайта (названия городов)
  branchFilter: '',   // выбранный филиал в списках ('' — все филиалы)
};

/* Разделы, которые для dialam группируются/фильтруются по филиалам */
const BRANCH_GROUPED_TYPES = ['staff', 'vacancy', 'news'];

const VIEWS = {
  overview: { title: 'Обзор' },
  sites: { title: 'Сайты' },
  branch: { title: 'Филиалы', type: 'branch' },
  license: { title: 'Лицензии', type: 'license' },
  news: { title: 'Новости', type: 'news' },
  vacancy: { title: 'Вакансии', type: 'vacancy' },
  staff: { title: 'Сотрудники', type: 'staff' },
  service: { title: 'Услуги', type: 'service' },
  document: { title: 'Документы', type: 'document' },
  settings: { title: 'Настройки' },
};

/* Схемы полей элементов: [имя, метка, тип] */
const SCHEMAS = {
  branch: [
    ['city', 'Город', 'text'], ['address', 'Адрес', 'text'],
    ['phone', 'Телефон', 'text'], ['email', 'E-mail', 'text'],
    ['hours', 'Часы работы', 'text'], ['map_url', 'Ссылка на карту', 'text'],
    ['is_active', 'Активен', 'bool'],
  ],
  license: [
    ['number', 'Номер лицензии', 'text'], ['issued_by', 'Кем выдана', 'text'],
    ['issued_at', 'Дата выдачи', 'date'], ['file_url', 'Ссылка на файл', 'text'],
    ['note', 'Примечание', 'textarea'],
  ],
  news: [
    ['title', 'Заголовок', 'text'], ['branch', 'Филиал', 'select-branch'],
    ['date', 'Дата', 'date'],
    ['excerpt', 'Краткое описание', 'textarea'], ['body', 'Текст новости', 'textarea'],
    ['image_url', 'URL изображения', 'text'], ['published', 'Опубликовано', 'bool'],
  ],
  vacancy: [
    ['title', 'Должность', 'text'], ['branch', 'Филиал', 'select-branch'],
    ['city', 'Город', 'text'],
    ['employment', 'Занятость', 'text'], ['salary', 'Зарплата', 'text'],
    ['description', 'Обязанности', 'textarea'], ['requirements', 'Требования', 'textarea'],
    ['contact_email', 'Контактный e-mail', 'text'], ['published', 'Опубликовано', 'bool'],
  ],
  staff: [
    ['name', 'ФИО', 'text'], ['role', 'Должность', 'text'],
    ['branch', 'Филиал', 'select-branch'], ['phone', 'Телефон', 'text'],
    ['email', 'E-mail', 'text'], ['education', 'Образование', 'textarea'],
    ['accreditation', 'Аккредитация', 'text'], ['photo', 'URL фото', 'text'],
  ],
  service: [
    ['name', 'Название', 'text'], ['category', 'Категория', 'text'],
    ['description', 'Описание', 'textarea'], ['price', 'Цена', 'text'],
    ['is_active', 'Активна', 'bool'],
  ],
  document: [
    ['title', 'Название', 'text'], ['category', 'Категория', 'text'],
    ['file_url', 'Ссылка на файл', 'text'], ['published', 'Опубликован', 'bool'],
  ],
  setting: [
    ['key', 'Ключ', 'text'], ['value', 'Значение', 'textarea'],
  ],
};

/* Колонки таблиц списков: type -> функция(item) -> [[заголовок, значение], ...] */
const LIST_COLUMNS = {
  branch: i => [['Город', i.city], ['Адрес', i.address], ['Телефон', i.phone], ['Часы', i.hours], ['Статус', boolBadge(i.is_active)]],
  license: i => [['Номер', i.number], ['Кем выдана', i.issued_by], ['Дата', i.issued_at], ['Файл', i.file_url]],
  news: i => [['Заголовок', i.title], ['Филиал', i.branch], ['Дата', i.date], ['Отрывок', i.excerpt], ['Публикация', boolBadge(i.published)]],
  vacancy: i => [['Должность', i.title], ['Филиал', i.branch || i.city], ['Занятость', i.employment], ['Зарплата', i.salary], ['Публикация', boolBadge(i.published)]],
  staff: i => [['ФИО', i.name], ['Должность', i.role], ['Филиал', i.branch], ['E-mail', i.email]],
  service: i => [['Название', i.name], ['Категория', i.category], ['Цена', i.price], ['Статус', boolBadge(i.is_active)]],
  document: i => [['Название', i.title], ['Категория', i.category], ['Ссылка', i.file_url], ['Публикация', boolBadge(i.published)]],
  setting: i => [['Ключ', i.key], ['Значение', i.value]],
};

function boolBadge(v) {
  return v ? '<span class="badge on">да</span>' : '<span class="badge off">нет</span>';
}

function currentSite() {
  return state.sites.find(s => s.id === state.siteId) || null;
}

/* Группировка по филиалам включается только для бренда «Диалам+» (slug=dialam) */
function isDialam() {
  const site = currentSite();
  return !!site && site.slug === 'dialam';
}

function branchGroupingEnabled(type) {
  return isDialam() && BRANCH_GROUPED_TYPES.indexOf(type) !== -1;
}

function itemBranch(it) {
  const d = it.data || {};
  return String(d.branch || d.city || '').trim();
}

/* Филиалы текущего сайта: API /api/sites/<id>/items?type=branch */
async function loadBranches(siteId) {
  if (!siteId) { state.branches = []; return; }
  try {
    const data = await api(`/api/sites/${siteId}/items?type=branch`);
    const names = (data.items || [])
      .map(it => String((it.data && it.data.city) || '').trim())
      .filter(Boolean);
    state.branches = Array.from(new Set(names));
  } catch (e) {
    state.branches = [];
  }
}

/* ============================== ВХОД / ВЫХОД ============================== */

function showLogin() {
  $('#app').classList.add('hidden');
  $('#login-screen').classList.remove('hidden');
  const pw = $('#login-password');
  if (pw) pw.value = '';
}

async function doLogin(password) {
  await api('/api/login', { method: 'POST', body: { password } });
  await enterApp();
}

async function doLogout() {
  try { await api('/api/logout', { method: 'POST', body: {} }); } catch (e) { /* ignore */ }
  showLogin();
  toast('Вы вышли из панели');
}

async function enterApp() {
  $('#login-screen').classList.add('hidden');
  $('#app').classList.remove('hidden');
  await loadSites();
  await loadBranches(state.siteId);
  renderView();
}

/* ============================== САЙТЫ ============================== */

async function loadSites() {
  const data = await api('/api/sites');
  state.sites = data.sites;
  if (!state.siteId || !state.sites.some(s => s.id === state.siteId)) {
    state.siteId = state.sites.length ? state.sites[0].id : null;
  }
  const sel = $('#site-switcher');
  sel.innerHTML = state.sites.map(s =>
    `<option value="${s.id}"${s.id === state.siteId ? ' selected' : ''}>${esc(s.name)}${s.is_active ? '' : ' (выкл.)'}</option>`
  ).join('');
}

/* ============================== РОУТЕР ВИДОВ ============================== */

function setView(view) {
  state.view = view;
  $$('#sidebar .nav-item').forEach(b =>
    b.classList.toggle('active', b.dataset.view === view));
  renderView();
}

async function renderView() {
  const content = $('#content');
  const meta = VIEWS[state.view];
  content.innerHTML = '<div class="loading">Загрузка…</div>';
  try {
    if (state.view === 'overview') return renderOverview(content, meta);
    if (state.view === 'sites') return renderSites(content, meta);
    if (state.view === 'settings') return renderSettings(content, meta);
    return renderItemsList(content, meta);
  } catch (e) {
    content.innerHTML = `<div class="form-error">${esc(e.message || 'Ошибка загрузки')}</div>`;
  }
}

/* ============================== ОБЗОР ============================== */

async function renderOverview(content, meta) {
  const site = currentSite();
  if (!site) { content.innerHTML = '<div class="empty-hint">Нет сайтов. Создайте первый в разделе «Сайты».</div>'; return; }
  const c = site.counts || {};
  const types = [
    ['branch', 'Филиалы'], ['license', 'Лицензии'], ['news', 'Новости'],
    ['vacancy', 'Вакансии'], ['staff', 'Сотрудники'], ['service', 'Услуги'],
    ['document', 'Документы'], ['setting', 'Настройки'],
  ];
  const cards = types.map(([t, label]) =>
    `<div class="stat-card glass" data-goto="${t}">
       <div class="stat-num">${c[t] || 0}</div><div class="stat-label">${esc(label)}</div>
     </div>`).join('');
  const info = [
    ['Slug', site.slug], ['Бренд', site.brand], ['Домен', site.domain],
    ['Девиз', site.tagline], ['Юр. лицо', site.legal_name],
    ['ИНН / ОГРН', `${site.inn || '—'} / ${site.ogrn || '—'}`],
    ['Лицензия', site.license_number ? `${site.license_number} от ${site.license_date || '—'}` : '—'],
    ['Телефон', site.phone], ['E-mail', site.email], ['Адрес', site.address],
    ['Тема', site.theme], ['Активен', boolBadge(site.is_active)],
  ].filter(r => r[1] !== '' && r[1] !== undefined && r[1] !== null || ['Активен'].includes(r[0]))
   .map(r => `<dt>${esc(r[0])}</dt><dd>${r[0] === 'Активен' ? r[1] : esc(r[1] || '—')}</dd>`).join('');

  content.innerHTML = `
    <div class="page-head"><h2>Обзор · ${esc(site.name)}</h2></div>
    <div class="cards-grid">${cards}</div>
    <div class="info-card glass"><h3>Реквизиты и контакты</h3><dl>${info}</dl></div>`;
  $$('.stat-card', content).forEach(el =>
    el.addEventListener('click', () => setView(el.dataset.goto)));
}

/* ============================== СПИСКИ ЭЛЕМЕНТОВ ============================== */

async function renderItemsList(content, meta) {
  const site = currentSite();
  if (!site) { content.innerHTML = '<div class="empty-hint">Нет сайтов.</div>'; return; }
  const type = meta.type;
  const grouping = branchGroupingEnabled(type);
  if (isDialam()) await loadBranches(site.id);
  const data = await api(`/api/sites/${site.id}/items?type=${type}`);
  let items = data.items.slice();
  let pinnedDirector = null;
  if (grouping && type === 'staff') {
    pinnedDirector = items.find(it => /директор/i.test(String((it.data || {}).role || ''))) || null;
    if (pinnedDirector) {
      items = items.filter(it => it.id !== pinnedDirector.id);
    }
  }

  /* Фильтр по филиалу (для dialam: Сотрудники / Вакансии / Новости) */
  if (grouping && state.branchFilter) {
    items = items.filter(it => itemBranch(it) === state.branchFilter);
  }

  /* Панель фильтра по филиалам */
  let filterHtml = '';
  if (grouping) {
    const chips = ['', ...state.branches].map(b =>
      `<button class="btn btn-sm ${b === state.branchFilter ? 'btn-primary' : 'btn-ghost'}"
         data-branch-filter="${esc(b)}">${b ? esc(b) : 'Все филиалы'}</button>`).join('');
    filterHtml = `<div class="branch-filter glass"><span class="branch-filter-label">Филиал:</span>${chips}</div>`;
  }

  /* Колонки: при группировке колонку «Филиал» убираем — она вынесена в заголовок группы */
  let baseColsFn = LIST_COLUMNS[type];
  let colsFn = baseColsFn;
  let dropIdx = -1;
  if (grouping) {
    const probe = baseColsFn({});
    dropIdx = probe.findIndex(h => h[0] === 'Филиал');
    if (dropIdx >= 0) {
      colsFn = (i) => baseColsFn(i).filter((_, idx) => idx !== dropIdx);
    }
  }

  const rowHtml = (it) => {
    const cells = colsFn(it.data).map(([h, v]) => `<td>${v && String(v).startsWith('<span') ? v : esc(v)}</td>`).join('');
    return `<tr><td>#${it.id}</td>${cells}
      <td class="row-actions">
        <button class="btn btn-ghost btn-sm" data-edit="${it.id}">Изменить</button>
        <button class="btn btn-danger-ghost btn-sm" data-del="${it.id}">Удалить</button>
      </td></tr>`;
  };

  const heads = ['#', ...colsFn({}).map(h => h[0]), ''].map(h => `<th>${esc(h)}</th>`).join('');

  let bodyHtml = '';
  if (!items.length && !pinnedDirector) {
    const span = 2 + colsFn({}).length;
    bodyHtml = `<tr><td colspan="${span}"><div class="empty-hint">Пока пусто. Нажмите «Добавить».</div></td></tr>`;
  } else if (grouping) {
    /* Директор всегда один и закреплён сверху, вне филиальных групп */
    let pinnedHtml = '';
    if (pinnedDirector) {
      pinnedHtml = `<tr class="branch-group-head"><td colspan="${2 + colsFn({}).length}">РУКОВОДСТВО · 1</td></tr>` +
        rowHtml(pinnedDirector);
    }
    /* Группировка по филиалу: заголовок-город, под ним записи */
    const groups = new Map();
    items.forEach(it => {
      const b = itemBranch(it) || 'Без филиала';
      if (!groups.has(b)) groups.set(b, []);
      groups.get(b).push(it);
    });
    const ordered = [...groups.keys()].sort((a, b) => {
      const ia = state.branches.indexOf(a), ib = state.branches.indexOf(b);
      return (ia < 0 ? 1e9 : ia) - (ib < 0 ? 1e9 : ib);
    });
    bodyHtml = pinnedHtml + ordered.map(city =>
      `<tr class="branch-group-head"><td colspan="${2 + colsFn({}).length}">${esc(city)} · ${groups.get(city).length}</td></tr>` +
      groups.get(city).map(rowHtml).join('')
    ).join('');
  } else {
    bodyHtml = items.map(rowHtml).join('');
  }

  content.innerHTML = `
    <div class="page-head">
      <h2>${esc(meta.title)} · ${esc(site.name)}</h2>
      <button class="btn btn-primary" id="btn-add">+ Добавить</button>
    </div>
    ${filterHtml}
    <div class="table-wrap glass"><table class="list"><thead><tr>${heads}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;

  $$('[data-branch-filter]', content).forEach(b =>
    b.addEventListener('click', () => {
      state.branchFilter = b.dataset.branchFilter;
      renderView();
    }));

  $('#btn-add').addEventListener('click', () => openItemModal(type, null));
  $$('[data-edit]', content).forEach(b =>
    b.addEventListener('click', () => openItemModal(type, items.find(i => i.id == b.dataset.edit))));
  $$('[data-del]', content).forEach(b =>
    b.addEventListener('click', async () => {
      if (!confirm('Удалить запись?')) return;
      try {
        await api(`/api/items/${b.dataset.del}`, { method: 'DELETE' });
        toast('Удалено');
        renderView();
      } catch (e) { toast(e.message, true); }
    }));
}

/* ============================== МОДАЛКА ЭЛЕМЕНТА ============================== */

let modalSaveFn = null;

function openModal(title, fieldsHtml, onSave) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = fieldsHtml;
  $('#modal-error').classList.add('hidden');
  modalSaveFn = onSave;
  $('#modal-backdrop').classList.remove('hidden');
}

function closeModal() {
  $('#modal-backdrop').classList.add('hidden');
  modalSaveFn = null;
}

function fieldHtml(name, label, kind, value) {
  const v = value === undefined || value === null ? '' : value;
  if (kind === 'bool') {
    return `<label class="field-check full"><input type="checkbox" name="${esc(name)}" ${v ? 'checked' : ''}> ${esc(label)}</label>`;
  }
  if (kind === 'select-branch') {
    /* Для dialam — обязательный select с филиалами сайта.
       Для остальных брендов поле остаётся обычным (необязательным). */
    if (isDialam()) {
      const opts = ['<option value="">— выберите филиал —</option>']
        .concat(state.branches.map(b =>
          `<option value="${esc(b)}"${String(v) === b ? ' selected' : ''}>${esc(b)}</option>`));
      /* Если значение не из списка (например, свободный текст) — добавляем его */
      if (v && state.branches.indexOf(String(v)) === -1) {
        opts.push(`<option value="${esc(v)}" selected>${esc(v)} (вне списка)</option>`);
      }
      return `<label class="field"><span>${esc(label)} *</span><select class="input select" name="${esc(name)}" required>${opts.join('')}</select></label>`;
    }
    kind = 'text';
  }
  const cls = (kind === 'textarea') ? 'full' : '';
  const input = kind === 'textarea'
    ? `<textarea class="input" name="${esc(name)}">${esc(v)}</textarea>`
    : `<input class="input" type="${kind}" name="${esc(name)}" value="${esc(v)}">`;
  return `<label class="field ${cls}"><span>${esc(label)}</span>${input}</label>`;
}

function readForm(container) {
  const out = {};
  $$('input[name], textarea[name], select[name]', container).forEach(el => {
    out[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  });
  return out;
}

function buildItemForm(schema, data) {
  data = data || {};
  const fields = schema.map(([name, label, kind]) => fieldHtml(name, label, kind, data[name])).join('');
  return `<div class="form-grid">${fields}
    <label class="field full"><span>Порядок сортировки</span>
      <input class="input" type="number" name="__sort_order" value="${data.__sort_order || 0}"></label>
  </div>`;
}

function openItemModal(type, item) {
  const site = currentSite();
  const schema = SCHEMAS[type];
  const data = Object.assign({}, item ? item.data : {}, { __sort_order: item ? item.sort_order : 0 });
  /* Для новой записи в dialam подставляем текущий выбранный филиал */
  if (!item && isDialam() && state.branchFilter && BRANCH_GROUPED_TYPES.indexOf(type) !== -1) {
    data.branch = state.branchFilter;
  }
  openModal((item ? 'Изменить: ' : 'Добавить: ') + VIEWS[type].title, buildItemForm(schema, data), async (bodyEl) => {
    const form = readForm(bodyEl);
    if (isDialam() && BRANCH_GROUPED_TYPES.indexOf(type) !== -1 && !String(form.branch || '').trim()) {
      showModalError('Выберите филиал — это поле обязательно.');
      return;
    }
    const order = parseInt(form.__sort_order || '0', 10) || 0;
    delete form.__sort_order;
    const payload = { type, data: form, sort_order: order };
    try {
      if (item) {
        await api(`/api/items/${item.id}`, { method: 'PUT', body: payload });
        toast('Сохранено');
      } else {
        await api(`/api/sites/${site.id}/items`, { method: 'POST', body: payload });
        toast('Добавлено');
      }
      closeModal();
      renderView();
    } catch (e) { showModalError(e.message); }
  });
}

function showModalError(msg) {
  const el = $('#modal-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

/* ============================== САЙТЫ (раздел) ============================== */

const SITE_FORM_FIELDS = [
  ['slug', 'Slug (латиница, адрес)', 'text'], ['name', 'Название', 'text'],
  ['brand', 'Бренд', 'text'], ['domain', 'Домен', 'text'],
  ['tagline', 'Девиз / tagline', 'text'], ['description', 'Описание', 'textarea'],
  ['legal_name', 'Юридическое название', 'text'], ['inn', 'ИНН', 'text'],
  ['ogrn', 'ОГРН', 'text'], ['license_number', 'Номер лицензии', 'text'],
  ['license_issued_by', 'Лицензия: кем выдана', 'text'],
  ['license_date', 'Лицензия: дата', 'date'], ['phone', 'Телефон', 'text'],
  ['email', 'E-mail', 'text'], ['address', 'Адрес', 'textarea'],
  ['theme', 'Тема (mint/dark/…)', 'text'],
];

function siteFormHtml(site) {
  site = site || {};
  const fields = SITE_FORM_FIELDS.map(([n, l, k]) => fieldHtml(n, l, k, site[n])).join('');
  const active = `<label class="field-check full"><input type="checkbox" name="is_active" ${site.is_active !== false ? 'checked' : ''}> Сайт активен (публичный JSON доступен)</label>`;
  return `<div class="form-grid">${fields}${active}</div>`;
}

async function renderSites(content, meta) {
  const rows = state.sites.map(s => `
    <tr>
      <td>${esc(s.name)}<div class="muted" style="font-size:.8rem">${esc(s.slug)}</div></td>
      <td>${esc(s.brand)}</td>
      <td>${esc(s.domain || '—')}</td>
      <td>${boolBadge(s.is_active)}</td>
      <td class="row-actions">
        <button class="btn btn-ghost btn-sm" data-switch="${s.id}">Открыть</button>
        <button class="btn btn-ghost btn-sm" data-edit-site="${s.id}">Изменить</button>
        <button class="btn btn-danger-ghost btn-sm" data-del-site="${s.id}">Удалить</button>
      </td>
    </tr>`).join('');
  content.innerHTML = `
    <div class="page-head">
      <h2>${esc(meta.title)}</h2>
      <button class="btn btn-primary" id="btn-add-site">+ Создать сайт</button>
    </div>
    <div class="table-wrap glass"><table class="list">
      <thead><tr><th>Название</th><th>Бренд</th><th>Домен</th><th>Активен</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;

  $('#btn-add-site').addEventListener('click', () => {
    openModal('Новый сайт', siteFormHtml({ is_active: true }), async (el) => {
      const body = readForm(el);
      try {
        const s = await api('/api/sites', { method: 'POST', body });
        toast('Сайт создан');
        closeModal();
        await loadSites();
        state.siteId = s.id;
        renderView();
      } catch (e) { showModalError(e.message); }
    });
  });

  $$('[data-switch]', content).forEach(b => b.addEventListener('click', async () => {
    state.siteId = parseInt(b.dataset.switch, 10);
    $('#site-switcher').value = state.siteId;
    state.branchFilter = '';
    await loadBranches(state.siteId);
    setView('overview');
  }));
  $$('[data-edit-site]', content).forEach(b => b.addEventListener('click', () => {
    const site = state.sites.find(s => s.id == b.dataset.editSite);
    openModal('Редактировать сайт: ' + site.name, siteFormHtml(site), async (el) => {
      const body = readForm(el);
      try {
        await api(`/api/sites/${site.id}`, { method: 'PUT', body });
        toast('Сайт обновлён');
        closeModal();
        await loadSites();
        renderView();
      } catch (e) { showModalError(e.message); }
    });
  }));
  $$('[data-del-site]', content).forEach(b => b.addEventListener('click', async () => {
    const site = state.sites.find(s => s.id == b.dataset.delSite);
    if (!confirm(`Удалить сайт «${site.name}» и весь его контент?`)) return;
    try {
      await api(`/api/sites/${site.id}`, { method: 'DELETE' });
      toast('Сайт удалён');
      if (state.siteId == site.id) state.siteId = null;
      await loadSites();
      renderView();
    } catch (e) { toast(e.message, true); }
  }));
}

/* ============================== НАСТРОЙКИ ============================== */

async function renderSettings(content, meta) {
  const site = currentSite();
  if (!site) { content.innerHTML = '<div class="empty-hint">Нет сайтов.</div>'; return; }
  const data = await api(`/api/sites/${site.id}/items?type=setting`);
  const kvRows = data.items.map(it => `
    <tr>
      <td><input class="input" data-k="${it.id}" value="${esc(it.data.key)}"></td>
      <td><textarea class="input" data-v="${it.id}">${esc(it.data.value)}</textarea></td>
      <td class="row-actions"><button class="btn btn-danger-ghost btn-sm" data-del-kv="${it.id}">Удалить</button></td>
    </tr>`).join('') || `<tr><td colspan="3" class="empty-hint">Нет key/value настроек</td></tr>`;

  content.innerHTML = `
    <div class="page-head"><h2>Настройки · ${esc(site.name)}</h2></div>
    <div class="info-card glass">
      <h3>Параметры сайта</h3>
      <p class="muted">Реквизиты, контакты и тема. Открываются в модальном окне.</p>
      <button class="btn btn-primary" id="btn-edit-site">Изменить параметры сайта</button>
    </div>
    <div class="info-card glass">
      <h3>Key/Value настройки</h3>
      <p class="muted">hero_title, hero_subtitle, cta_text, legal_text, footer_note и любые новые ключи.</p>
      <div class="table-wrap"><table class="list">
        <thead><tr><th style="width:220px">Ключ</th><th>Значение</th><th style="width:90px"></th></tr></thead>
        <tbody id="kv-body">${kvRows}</tbody></table></div>
      <div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap">
        <button class="btn btn-primary" id="btn-save-kv">Сохранить значения</button>
        <button class="btn btn-ghost" id="btn-add-kv">+ Добавить настройку</button>
      </div>
    </div>`;

  $('#btn-edit-site').addEventListener('click', () => {
    openModal('Параметры сайта: ' + site.name, siteFormHtml(site), async (el) => {
      const body = readForm(el);
      try {
        await api(`/api/sites/${site.id}`, { method: 'PUT', body });
        toast('Сохранено');
        closeModal();
        await loadSites();
        renderView();
      } catch (e) { showModalError(e.message); }
    });
  });

  $('#btn-save-kv').addEventListener('click', async () => {
    const inputs = $$('#kv-body [data-k]');
    try {
      for (const inp of inputs) {
        const id = inp.dataset.k;
        const ta = $(`#kv-body [data-v="${id}"]`);
        await api(`/api/items/${id}`, { method: 'PUT', body: { data: { key: inp.value, value: ta.value } } });
      }
      toast('Настройки сохранены');
      renderView();
    } catch (e) { toast(e.message, true); }
  });

  $$('[data-del-kv]', content).forEach(b => b.addEventListener('click', async () => {
    if (!confirm('Удалить настройку?')) return;
    try { await api(`/api/items/${b.dataset.delKv}`, { method: 'DELETE' }); toast('Удалено'); renderView(); }
    catch (e) { toast(e.message, true); }
  }));

  $('#btn-add-kv').addEventListener('click', () => {
    openItemModal('setting', null);
  });
}

/* ============================== ТОПБАР ============================== */

async function exportJson(saveFile) {
  const site = currentSite();
  if (!site) return toast('Нет активного сайта', true);
  try {
    if (saveFile) {
      const r = await api(`/api/sites/${site.id}/export-file`, { method: 'POST', body: {} });
      toast('Экспорт сохранён: ' + r.path);
    } else {
      const data = await api(`/api/sites/${site.id}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = site.slug + '.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast('JSON скачан');
    }
  } catch (e) { toast(e.message, true); }
}

/* ============================== ИНИЦИАЛИЗАЦИЯ ============================== */

function init() {
  $('#login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = $('#login-btn');
    const err = $('#login-error');
    err.classList.add('hidden');
    btn.disabled = true;
    try {
      await doLogin($('#login-password').value);
      toast('Добро пожаловать');
    } catch (e) {
      err.textContent = e.message || 'Не удалось войти';
      err.classList.remove('hidden');
    } finally {
      btn.disabled = false;
    }
  });

  $('#sidebar').addEventListener('click', (ev) => {
    const b = ev.target.closest('.nav-item');
    if (b) setView(b.dataset.view);
  });

  $('#site-switcher').addEventListener('change', async (ev) => {
    state.siteId = parseInt(ev.target.value, 10);
    state.branchFilter = '';
    await loadBranches(state.siteId);
    renderView();
  });

  $('#btn-export').addEventListener('click', () => exportJson(false));
  $('#btn-site-settings').addEventListener('click', () => setView('settings'));
  $('#btn-logout').addEventListener('click', doLogout);

  $('#modal-close').addEventListener('click', closeModal);
  $('#modal-cancel').addEventListener('click', closeModal);
  $('#modal-backdrop').addEventListener('click', (ev) => {
    if (ev.target === $('#modal-backdrop')) closeModal();
  });
  $('#modal-save').addEventListener('click', () => {
    if (modalSaveFn) modalSaveFn($('#modal-body'));
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeModal();
  });

  // проверка сессии
  fetch('/api/me', { credentials: 'same-origin' })
    .then(res => {
      if (res.ok) return enterApp();
      showLogin();
    })
    .catch(() => showLogin());
}

document.addEventListener('DOMContentLoaded', init);
