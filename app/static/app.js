const state = {
  currentUser: null, users: [], securityStatus: null,
  hosts: [], repos: [], jobs: [], schedules: [], runs: [], mounts: [], system: {}, settings: null, backups: [], runStorage: null, notifications: null, notificationDeliveries: [],
  liveRunId: null, liveTimer: null, refreshTimer: null,
  archiveData: null, archiveRequestId: 0, archiveSelection: new Set(), activeBrowser: null, browserPath: '', browserSelection: new Set(),
  openJobActions: new Set(), backgroundRefresh: false,
  runFilter: 'all', runSearch: '', jobSearch: '', jobStatus: 'all',
  repositoryStatusDetails: '', dashboard: null,
  actionRuns: new Map(), activeRuns: [], refreshQueue: Promise.resolve(), syncResetTimer: null,
  syncDisplay: {message: 'Aktuell', kind: 'idle', persistent: false}, helpLanguage: '',
  sorts: {},
};

const SORT_DEFAULTS = {
  dashboardJobs: 'name-asc', jobs: 'name-asc', repositories: 'name-asc', hosts: 'name-asc',
};

const SYSTEM_VIEWS = new Set(['notifications', 'users', 'backups', 'settings', 'diagnostics']);

function sortPreferenceStorageKey() {
  const user = state.currentUser?.id || state.currentUser?.username || 'anonymous';
  return `bbm-sort-preferences-${user}`;
}

function loadSortPreferences() {
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(sortPreferenceStorageKey()) || '{}'); } catch { stored = {}; }
  state.sorts = {...SORT_DEFAULTS, ...(stored && typeof stored === 'object' ? stored : {})};
  const controls = {
    '#dashboard-job-sort': 'dashboardJobs', '#job-sort': 'jobs',
    '#repo-sort': 'repositories', '#host-sort': 'hosts',
  };
  for (const [selector, key] of Object.entries(controls)) {
    const control = $(selector);
    if (control && [...control.options].some((option) => option.value === state.sorts[key])) control.value = state.sorts[key];
  }
}

function saveSortPreference(key, value) {
  state.sorts[key] = value;
  try { localStorage.setItem(sortPreferenceStorageKey(), JSON.stringify(state.sorts)); } catch { /* optional browser storage */ }
}

function compareText(left, right) {
  return String(left ?? '').localeCompare(String(right ?? ''), currentLocale(), {numeric: true, sensitivity: 'base'});
}

function stableSort(items, compare) {
  return [...items].sort((left, right) => compare(left, right) || Number(left.id || 0) - Number(right.id || 0));
}

function sortedDashboardJobs(items) {
  const mode = state.sorts.dashboardJobs || SORT_DEFAULTS.dashboardJobs;
  const timestamp = (job) => serverDate(job.last_run?.created_at)?.getTime() || 0;
  const backupSize = (job) => Number((job.last_successful_backup || job.last_run)?.backup_deduplicated_size_bytes ?? -1);
  const comparators = {
    'name-asc': (a, b) => compareText(a.name, b.name), 'name-desc': (a, b) => compareText(b.name, a.name),
    'host-asc': (a, b) => compareText(a.host_name, b.host_name), 'repository-asc': (a, b) => compareText(a.repository_name, b.repository_name),
    'status-active': (a, b) => Number(b.enabled) - Number(a.enabled) || compareText(a.name, b.name),
    'last-newest': (a, b) => timestamp(b) - timestamp(a), 'last-oldest': (a, b) => timestamp(a) - timestamp(b),
    'size-desc': (a, b) => backupSize(b) - backupSize(a) || compareText(a.name, b.name),
  };
  return stableSort(items, comparators[mode] || comparators['name-asc']);
}

function sortedJobs(items) {
  const mode = state.sorts.jobs || SORT_DEFAULTS.jobs;
  const hostName = (job) => state.hosts.find((item) => item.id === job.host_id)?.name || '';
  const repoName = (job) => state.repos.find((item) => item.id === job.repository_id)?.name || '';
  const comparators = {
    'name-asc': (a, b) => compareText(a.name, b.name), 'name-desc': (a, b) => compareText(b.name, a.name),
    'host-asc': (a, b) => compareText(hostName(a), hostName(b)), 'repository-asc': (a, b) => compareText(repoName(a), repoName(b)),
    'status-active': (a, b) => Number(b.enabled) - Number(a.enabled) || compareText(a.name, b.name),
    'schedule-asc': (a, b) => compareText((a.schedule_names || []).join(', '), (b.schedule_names || []).join(', ')),
  };
  return stableSort(items, comparators[mode] || comparators['name-asc']);
}

function sortedRepositories(items) {
  const mode = state.sorts.repositories || SORT_DEFAULTS.repositories;
  const jobCount = (repo) => state.jobs.filter((job) => job.repository_id === repo.id).length;
  const ready = (repo) => Number(Boolean(repo.initialized && (!repo.managed || repo.repository_present)));
  const size = (repo) => Number(repo.deduplicated_size_bytes ?? repo.size_bytes ?? -1);
  const comparators = {
    'name-asc': (a, b) => compareText(a.name, b.name), 'name-desc': (a, b) => compareText(b.name, a.name),
    'status-ready': (a, b) => ready(b) - ready(a) || compareText(a.name, b.name),
    'type-managed': (a, b) => Number(b.managed) - Number(a.managed) || compareText(a.name, b.name),
    'jobs-desc': (a, b) => jobCount(b) - jobCount(a) || compareText(a.name, b.name),
    'size-desc': (a, b) => size(b) - size(a) || compareText(a.name, b.name),
  };
  return stableSort(items, comparators[mode] || comparators['name-asc']);
}

function sortedHosts(items) {
  const mode = state.sorts.hosts || SORT_DEFAULTS.hosts;
  const comparators = {
    'name-asc': (a, b) => compareText(a.name, b.name), 'name-desc': (a, b) => compareText(b.name, a.name),
    'status-active': (a, b) => Number(b.enabled) - Number(a.enabled) || compareText(a.name, b.name),
    'address-asc': (a, b) => compareText(`${a.address}:${a.port}`, `${b.address}:${b.port}`),
    'borg-desc': (a, b) => compareText(b.borg_version || '', a.borg_version || ''),
  };
  return stableSort(items, comparators[mode] || comparators['name-asc']);
}

const RELOAD_SESSION_KEY = 'bbm-session-reload-v1';
function reloadSessionToken() {
  try { return sessionStorage.getItem(RELOAD_SESSION_KEY) || ''; } catch { return ''; }
}
function storeReloadSessionToken(value) {
  try {
    if (value) sessionStorage.setItem(RELOAD_SESSION_KEY, String(value));
    else sessionStorage.removeItem(RELOAD_SESSION_KEY);
  } catch { /* sessionStorage kann durch Browserrichtlinien gesperrt sein. */ }
}
function reloadAuthorizationHeaders() {
  const token = reloadSessionToken();
  return token ? {'Authorization': `BBM-Reload ${token}`} : {};
}

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[char]));
const lines = (value) => value.split('\n').map((item) => item.trim()).filter(Boolean);

function bbmAction(name, ...args) {
  return `data-bbm-action="${esc(name)}" data-bbm-args="${esc(JSON.stringify(args))}"`;
}

const DISPLAY_TIME_ZONE = 'Europe/Berlin';
let dateFormatter = createDateFormatter();
function currentLanguage() { return window.BBMI18n?.language?.() || 'de'; }
function currentLocale() { return currentLanguage() === 'en' ? 'en-GB' : 'de-DE'; }
function createDateFormatter() {
  return new Intl.DateTimeFormat(currentLocale(), {
    timeZone: DISPLAY_TIME_ZONE, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}
function translateMessage(value) { return window.BBMI18n?.translateMessage?.(value) || value; }

function serverDate(value) {
  if (!value) return null;
  const text = String(value);
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : text + 'Z';
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value) {
  const date = serverDate(value);
  return date ? dateFormatter.format(date) : '–';
}

function archiveTimestampFromName(name) {
  const base = String(name || '').replace(/\.checkpoint(?:\.\d+)?$/i, '');
  const match = base.match(/(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?|\d{4}-\d{2}-\d{2}[T_ -]\d{2}[-:]\d{2}(?:[-:]\d{2}(?:\.\d+)?)?)$/);
  if (!match) return null;
  let value = match[1];
  if (!value.includes('T')) value = value.slice(0, 10) + 'T' + value.slice(11);
  const timezone = value.match(/(Z|[+-]\d{2}:?\d{2})$/)?.[1] || '';
  let body = timezone ? value.slice(0, -timezone.length) : value;
  const [datePart, timePart = ''] = body.split('T');
  body = `${datePart}T${timePart.replace(/-/g, ':')}${timezone}`;
  const parsed = serverDate(body);
  return parsed ? parsed.getTime() : null;
}

function archiveDeviceFromName(name) {
  const base = String(name || '').replace(/\.checkpoint(?:\.\d+)?$/i, '');
  const timestamp = base.match(/(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?|\d{4}-\d{2}-\d{2}[T_ -]\d{2}[-:]\d{2}(?:[-:]\d{2}(?:\.\d+)?)?)$/);
  if (!timestamp) return '';
  let device = base.slice(0, timestamp.index).replace(/[-_. ]+$/, '');
  device = device
    .replace(/^bbm-job-\d+-[0-9a-f]{8,64}-/i, '')
    .replace(/^bbm-job-\d+-/i, '')
    .replace(/^bbm-\d+-/i, '')
    .replace(/^[-_. ]+|[-_. ]+$/g, '');
  return device;
}

function archiveDevice(archive) {
  return String(archive?.device_name || archive?.archive_device || archiveDeviceFromName(archive?.name) || '');
}

function sortArchivesNewestFirst(archives) {
  return [...archives].sort((left, right) => {
    const leftDate = serverDate(left.start)?.getTime() ?? archiveTimestampFromName(left.name) ?? Number.NEGATIVE_INFINITY;
    const rightDate = serverDate(right.start)?.getTime() ?? archiveTimestampFromName(right.name) ?? Number.NEGATIVE_INFINITY;
    if (leftDate !== rightDate) return rightDate - leftDate;
    return String(right.name || '').localeCompare(String(left.name || ''), currentLocale(), {numeric: true, sensitivity: 'base'});
  });
}

function formatDuration(seconds) {
  if (seconds == null) return '–';
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes} min ${rest} s`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}


const WEEKDAY_LABELS = {mon: 'Mo', tue: 'Di', wed: 'Mi', thu: 'Do', fri: 'Fr', sat: 'Sa', sun: 'So'};

function splitSchedules(value) {
  return String(value || '').split(/[;\n]+/).map((item) => item.trim().replace(/\s+/g, ' ')).filter(Boolean);
}

function scheduleSummary(value) {
  const expressions = splitSchedules(value);
  if (!expressions.length) return 'manuell';
  const parsed = expressions.map((expression) => expression.split(' '));
  if (parsed.some((parts) => parts.length !== 5)) return expressions.join(' · ');
  const times = parsed.map(([minute, hour]) => `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`).join(', ');
  const [, , day, month, weekday] = parsed[0];
  if (!parsed.every((parts) => parts[2] === day && parts[3] === month && parts[4] === weekday)) return expressions.join(' · ');
  if (day === '*' && month === '*' && weekday === '*') return `täglich · ${times}`;
  if (day === '*' && month === '*' && ['1-5', 'mon-fri'].includes(weekday)) return `Mo–Fr · ${times}`;
  if (day === '*' && month === '*' && ['0,6', '6,0', 'sat,sun', 'sun,sat'].includes(weekday)) return `Wochenende · ${times}`;
  if (day === '*' && month === '*' && weekday !== '*') return `${weekday.split(',').map((item) => WEEKDAY_LABELS[item] || item).join(', ')} · ${times}`;
  if (month === '*' && weekday === '*' && /^\d+$/.test(day)) return `monatlich am ${day}. · ${times}`;
  return expressions.join(' · ');
}

function addScheduleTime(value = '02:00') {
  const container = $('#schedule-times');
  const row = document.createElement('div');
  row.className = 'schedule-time-row';
  row.innerHTML = `<input type="time" value="${esc(value)}" step="60" required><button type="button" class="danger ghost">Entfernen</button>`;
  row.querySelector('input').oninput = updateSchedulePreview;
  row.querySelector('button').onclick = () => {
    row.remove();
    if (!container.children.length) addScheduleTime('02:00');
    updateSchedulePreview();
  };
  container.append(row);
}

function scheduleTimes() {
  return $$('#schedule-times input[type=time]').map((input) => input.value).filter(Boolean);
}

function selectedScheduleWeekdays() {
  return $$('#schedule-weekdays input:checked').map((input) => input.value);
}

function buildScheduleExpressions() {
  const mode = $('#schedule-mode').value;
  if (mode === 'custom') return splitSchedules($('#schedule-custom').value);
  const times = scheduleTimes();
  if (!times.length) throw new Error('Mindestens eine Uhrzeit auswählen');
  let day = '*'; let weekday = '*';
  if (mode === 'weekdays') weekday = 'mon-fri';
  else if (mode === 'weekends') weekday = 'sat,sun';
  else if (mode === 'selected') {
    const selected = selectedScheduleWeekdays();
    if (!selected.length) throw new Error('Mindestens einen Wochentag auswählen');
    weekday = selected.join(',');
  } else if (mode === 'monthly') day = String(Math.max(1, Math.min(28, +$('#schedule-day').value || 1)));
  return times.map((value) => {
    const [hour, minute] = value.split(':').map(Number);
    return `${minute} ${hour} ${day} * ${weekday}`;
  });
}

function updateSchedulePreview() {
  const mode = $('#schedule-mode').value;
  $('#schedule-times').classList.toggle('hidden', mode === 'custom');
  $('#add-schedule-time').classList.toggle('hidden', mode === 'custom');
  $('#schedule-weekdays').classList.toggle('hidden', mode !== 'selected');
  $('#schedule-month-day').classList.toggle('hidden', mode !== 'monthly');
  $('#schedule-custom-field').classList.toggle('hidden', mode !== 'custom');
  $$('#schedule-times input').forEach((input) => { input.disabled = mode === 'custom'; input.required = mode !== 'custom'; });
  $('#schedule-custom').disabled = mode !== 'custom'; $('#schedule-custom').required = mode === 'custom';
  try {
    const expressions = buildScheduleExpressions();
    $('#schedule-form').elements.expressions.value = expressions.join(';');
    $('#schedule-preview').textContent = `${scheduleSummary(expressions.join(';'))} · Europe/Berlin · ${expressions.length} Ausführungszeit${expressions.length === 1 ? '' : 'en'}`;
    $('#schedule-preview').classList.remove('error');
  } catch (error) {
    $('#schedule-form').elements.expressions.value = '';
    $('#schedule-preview').textContent = error.message;
    $('#schedule-preview').classList.add('error');
  }
}

function setScheduleEditor(value) {
  const expressions = splitSchedules(value);
  const modeSelect = $('#schedule-mode');
  $('#schedule-times').innerHTML = '';
  $$('#schedule-weekdays input').forEach((input) => { input.checked = false; });
  $('#schedule-custom').value = '';
  $('#schedule-day').value = '1';
  if (!expressions.length) {
    modeSelect.value = 'daily';
    addScheduleTime('02:00');
    updateSchedulePreview();
    return;
  }
  const parsed = expressions.map((expression) => expression.split(' '));
  const simple = parsed.every((parts) => parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1]));
  let mode = 'custom';
  if (simple) {
    const day = parsed[0][2], month = parsed[0][3], weekday = parsed[0][4];
    const sameRule = parsed.every((parts) => parts[2] === day && parts[3] === month && parts[4] === weekday);
    if (sameRule && month === '*') {
      if (day === '*' && weekday === '*') mode = 'daily';
      else if (day === '*' && ['1-5', 'mon-fri'].includes(weekday)) mode = 'weekdays';
      else if (day === '*' && ['0,6', '6,0', 'sat,sun', 'sun,sat'].includes(weekday)) mode = 'weekends';
      else if (day === '*' && weekday !== '*') mode = 'selected';
      else if (/^\d+$/.test(day) && weekday === '*') mode = 'monthly';
    }
  }
  modeSelect.value = mode;
  if (mode === 'custom') {
    $('#schedule-custom').value = expressions.join('\n');
    addScheduleTime('02:00');
  } else {
    parsed.forEach(([minute, hour]) => addScheduleTime(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`));
    if (mode === 'selected') parsed[0][4].split(',').forEach((day) => {
      const input = $(`#schedule-weekdays input[value="${day}"]`); if (input) input.checked = true;
    });
    if (mode === 'monthly') $('#schedule-day').value = parsed[0][2];
  }
  updateSchedulePreview();
}

function applyUserPermissions() {
  const admin = state.currentUser?.role === 'admin';
  $$('[data-admin-only]').forEach((element) => element.classList.toggle('hidden', !admin));
  $$('[data-admin-only-block]').forEach((element) => element.classList.toggle('hidden', !admin));
  $('#current-user').textContent = state.currentUser ? `${state.currentUser.username} · ${admin ? 'Administrator' : 'Benutzer'}` : '';
  if (!admin && ['hosts', 'repositories', 'archives', 'restore', 'notifications', 'users', 'backups', 'settings', 'diagnostics'].includes(hashView())) {
    history.replaceState(null, '', '#dashboard');
    goToView('dashboard', false);
  }
}

function parseHashState() {
  const raw = location.hash.replace(/^#/, '') || 'dashboard';
  const [viewPart, query = ''] = raw.split('?', 2);
  const view = validView(viewPart) ? viewPart : 'dashboard';
  const params = new URLSearchParams(query);
  const allowed = new Set(['all', 'active', 'failed', 'success', 'warning', 'cancelled', 'queued', 'running']);
  const status = allowed.has(params.get('status')) ? params.get('status') : 'all';
  const requestedSection = params.get('section') || '';
  const section = view === 'help' && /^help-[a-z0-9-]+$/.test(requestedSection) ? requestedSection : '';
  return {view, status, section};
}

class ApiError extends Error {
  constructor(status, message, path) {
    super(message || `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = Number(status) || 0;
    this.path = path;
  }
}

async function api(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const securityHeaders = ['GET', 'HEAD', 'OPTIONS'].includes(method) ? {} : {'X-BBM-Request': '1'};
  const headers = {'Content-Type': 'application/json', ...reloadAuthorizationHeaders(), ...securityHeaders, ...options.headers};
  const response = await fetch('/api' + path, {
    ...options,
    credentials: 'same-origin',
    cache: 'no-store',
    headers,
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { detail = response.statusText; }
    const rawMessage = Array.isArray(detail) ? detail.map((item) => item.msg).join(', ') : detail;
    const message = translateMessage(rawMessage);
    const error = new ApiError(response.status, message, path);
    // Nur ein echter HTTP-401 beendet die lokale Anmeldung. Fehlermeldungen aus
    // Borg, SSH oder Diagnose dürfen auch dann nicht abmelden, wenn sie Wörter
    // wie „Session“ oder „Token“ enthalten.
    if (response.status === 401 && path !== '/auth/login') setTimeout(() => logout(false), 0);
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

let loginInProgress = false;

async function verifyBrowserSession() {
  const response = await fetch('/api/auth/status', {credentials: 'same-origin', cache: 'no-store', headers: reloadAuthorizationHeaders()});
  let body = {};
  try { body = await response.json(); } catch { /* textlose Antwort */ }
  if (!response.ok) {
    throw new ApiError(response.status, body.detail || 'Der Browser hat die Sitzung nicht übernommen.', '/auth/status');
  }
  return body;
}

function showLoginScreen(message = '') {
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
  if (message) $('#login-error').textContent = message;
}

async function submitLogin(event) {
  event.preventDefault();
  if (loginInProgress) return;
  loginInProgress = true;
  const errorBox = $('#login-error');
  const usernameInput = $('#login-username');
  const passwordInput = $('#login-password');
  errorBox.textContent = '';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-BBM-Request': '1'},
      body: JSON.stringify({username: usernameInput.value.trim(), password: passwordInput.value}),
    });
    let body = {};
    try { body = await response.json(); } catch { /* textlose Antwort */ }
    if (!response.ok) throw new Error(body.detail || 'Anmeldung abgelehnt');
    storeReloadSessionToken(body.reload_token || '');
    // Erst nachweisen, dass der Browser den HttpOnly-Cookie wirklich gespeichert
    // und bei einer zweiten Anfrage zurückgesendet hat. Dadurch kann die WebUI
    // nicht mehr scheinbar erfolgreich anmelden und erst beim Reload scheitern.
    const verifiedUser = await verifyBrowserSession();
    state.currentUser = verifiedUser;
    applyUserPreferences(false);
    passwordInput.value = '';
    $('#login').classList.add('hidden');
    $('#app').classList.remove('hidden');
    applyUserPermissions();
    goToView(hashView(), false);
    if (verifiedUser.must_change_password) { openPasswordDialog(true); return; }
    await loadAll();
  } catch (error) {
    state.currentUser = null;
    storeReloadSessionToken('');
    showLoginScreen();
    errorBox.textContent = `Anmeldung fehlgeschlagen: ${error.message}`;
    passwordInput.value = '';
    passwordInput.focus();
  } finally {
    loginInProgress = false;
  }
}

const loginForm = $('#login-form');
if (loginForm) loginForm.addEventListener('submit', submitLogin);

async function loadPublicVersion() {
  try {
    const response = await fetch('/api/ready', {credentials: 'same-origin', cache: 'no-store'});
    const body = await response.json();
    if (body.version) $('#login-version').textContent = `v${body.version}`;
  } catch { /* Statische Fallback-Version bleibt sichtbar. */ }
}
loadPublicVersion();

function toast(message, bad = false) {
  const element = $('#toast');
  element.textContent = message;
  element.style.background = bad ? '#a83d36' : '';
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), bad ? 8000 : 3200);
}

async function copyText(value, successMessage, fallbackTitle = 'Text kopieren') {
  const text = String(value || '').trim();
  if (!text) throw new Error('Kein kopierbarer Inhalt vorhanden');
  try {
    await navigator.clipboard.writeText(text);
  } catch (_clipboardError) {
    const field = document.createElement('textarea');
    field.value = text; field.setAttribute('readonly', ''); field.style.position = 'fixed'; field.style.opacity = '0';
    document.body.append(field); field.select();
    const copied = document.execCommand && document.execCommand('copy');
    field.remove();
    if (!copied) { showTextDialog(fallbackTitle, text); return false; }
  }
  toast(successMessage);
  return true;
}


function activeRunSubject(run) {
  return run.job_name || (!run.job_id ? 'Repository-Verwaltung' : `Job ${run.job_id}`);
}

function currentActiveRun() {
  const active = [...(state.activeRuns || [])];
  const running = active.filter((run) => run.status === 'running').sort((left, right) => {
    const leftTime = serverDate(left.started_at || left.created_at)?.getTime() || Number(left.id);
    const rightTime = serverDate(right.started_at || right.created_at)?.getTime() || Number(right.id);
    return rightTime - leftTime;
  });
  if (running.length) return running[0];
  return active.filter((run) => run.status === 'queued').sort((left, right) => Number(left.id) - Number(right.id))[0] || null;
}

function renderHeaderStatus() {
  const element = $('#sync-state');
  if (!element) return;
  const run = currentActiveRun();
  if (run) {
    const extra = Math.max(0, (state.activeRuns || []).length - 1);
    const status = run.status === 'running' ? 'läuft' : 'wartet';
    const subject = `#${run.id} · ${activeRunSubject(run)}`;
    const detail = `${run.action || 'Ausführung'} · ${status}${extra ? ` · +${extra}` : ''}`;
    element.className = 'sync-state pending has-tasks';
    element.innerHTML = `<span class="sync-indicator" aria-hidden="true"></span><span><b>${esc(subject)}</b><small>${esc(detail)}</small></span>`;
    element.disabled = false;
    element.title = `Live-Log von Ausführung #${run.id} öffnen`;
    element.dataset.runId = String(run.id);
    return;
  }
  delete element.dataset.runId;
  const display = state.syncDisplay || {message: 'Aktuell', kind: 'idle'};
  element.className = `sync-state ${display.kind || 'idle'}`;
  element.innerHTML = `<span class="sync-indicator" aria-hidden="true"></span><span>${esc(display.message || 'Aktuell')}</span>`;
  element.disabled = true;
  element.title = '';
}

function openCurrentActiveRun() {
  const run = currentActiveRun();
  if (run) showRun(run.id);
}

function openActiveRun(id) { showRun(id); }

function setActiveRuns(runs) {
  state.activeRuns = (runs || []).filter((run) => activeRunStatus(run.status));
  renderHeaderStatus();
}

function updateActiveRun(run) {
  const items = (state.activeRuns || []).filter((item) => Number(item.id) !== Number(run.id));
  if (activeRunStatus(run.status)) items.push(run);
  setActiveRuns(items);
}

function setSyncState(message, kind = 'idle', persistent = false) {
  clearTimeout(state.syncResetTimer);
  state.syncDisplay = {message, kind, persistent};
  renderHeaderStatus();
  if (!persistent && kind !== 'pending') {
    state.syncResetTimer = setTimeout(() => {
      state.syncDisplay = {message: 'Aktuell', kind: 'idle', persistent: false};
      renderHeaderStatus();
    }, kind === 'error' ? 8000 : 4200);
  }
}

function actionButton(explicit = null) {
  if (explicit instanceof HTMLButtonElement) return explicit;
  return document.activeElement instanceof HTMLButtonElement ? document.activeElement : null;
}

function markButtonBusy(button, label = 'Wird ausgeführt …') {
  if (!button) return () => {};
  const originalText = button.textContent;
  const originalDisabled = button.disabled;
  button.disabled = true;
  button.classList.add('action-busy');
  button.textContent = label;
  return () => {
    button.disabled = originalDisabled;
    button.classList.remove('action-busy');
    button.textContent = originalText;
  };
}

function activeRunStatus(status) {
  return ['queued', 'running'].includes(status);
}

function runImpact(jobId, actionName) {
  const job = state.jobs.find((item) => item.id === Number(jobId));
  return {
    areas: ['dashboard', 'runs', 'repositories', 'jobs'],
    repositoryId: job?.repository_id || null,
    refreshArchives: ['backup', 'prune', 'compact'].includes(actionName),
  };
}

function setRepositoryStatus(message, bad = false, details = '', pending = false) {
  const box = $('#repo-operation-status');
  if (!box) return;
  box.classList.remove('hidden', 'error-state', 'success-state', 'pending-state');
  box.classList.add(pending ? 'pending-state' : (bad ? 'error-state' : 'success-state'));
  state.repositoryStatusDetails = details || '';
  const heading = pending ? 'Repository-Aktion läuft' : (bad ? 'Repository-Aktion fehlgeschlagen' : 'Repository-Aktion erfolgreich');
  const detailsButton = details
    ? `<button type="button" class="secondary" ${bbmAction('showRepositoryStatusDetails')}>Technische Details anzeigen</button>`
    : '';
  box.innerHTML = `<b>${heading}</b><span>${esc(message)}</span>${detailsButton}`;
}

function showRepositoryStatusDetails() {
  if (state.repositoryStatusDetails) showTextDialog('Technische Repository-Details', state.repositoryStatusDetails);
}

function clearRepositoryStatus() {
  const box = $('#repo-operation-status');
  if (!box) return;
  box.classList.add('hidden');
  box.innerHTML = '';
  state.repositoryStatusDetails = '';
}

function validView(view) {
  return Boolean($(`#view-${view}`) && ($(`nav button[data-view="${view}"]`) || SYSTEM_VIEWS.has(view)));
}

function isSystemView(view) {
  return SYSTEM_VIEWS.has(view);
}

function hashView() {
  return parseHashState().view;
}

function setMobileNavigation(open) {
  const sidebar = document.querySelector('aside');
  const toggle = $('#mobile-nav-toggle');
  if (!sidebar || !toggle) return;
  sidebar.classList.toggle('mobile-open', Boolean(open));
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  toggle.textContent = open ? 'Schließen' : 'Menü';
}

function goToView(view, updateHash = true) {
  if (!validView(view)) view = 'dashboard';
  if (view === 'runs' && updateHash) state.runFilter = 'all';
  const systemView = isSystemView(view);
  const sidebarView = systemView ? 'settings' : view;
  const button = $(`nav button[data-view="${sidebarView}"]`);
  $$('nav button').forEach((item) => item.classList.toggle('active', item === button));
  $$('.view').forEach((item) => item.classList.toggle('active', item.id === 'view-' + view));
  const systemTabs = $('#system-workspace-tabs');
  if (systemTabs) systemTabs.classList.toggle('hidden', !systemView || state.currentUser?.role !== 'admin');
  $$('[data-system-view]').forEach((item) => {
    const active = systemView && item.dataset.systemView === view;
    item.classList.toggle('active', active);
    item.setAttribute('aria-selected', active ? 'true' : 'false');
    item.tabIndex = active ? 0 : -1;
  });
  $('#page-title').textContent = systemView ? 'System' : (button?.textContent || 'Übersicht');
  if (updateHash) {
    const targetHash = view === 'runs' && state.runFilter !== 'all' ? `#runs?status=${state.runFilter}` : '#' + view;
    if (location.hash !== targetHash) history.pushState(null, '', targetHash);
  }
  if (view === 'releases') loadReleaseNotes();
  if (view === 'help') loadHelpLanguage(currentLanguage());
  if (view === 'restore' && $('#restore-form').elements.job_id.value) syncRestoreArchives(false);
  if (view === 'runs') {
    syncRunFilterControls();
    if (updateHash && state.settings) loadRunsOnly();
  }
  if (window.matchMedia('(max-width: 760px)').matches) setMobileNavigation(false);
}

async function goToRuns(status = 'all') {
  state.runFilter = status;
  const targetHash = status === 'all' ? '#runs' : `#runs?status=${encodeURIComponent(status)}`;
  if (location.hash !== targetHash) history.pushState(null, '', targetHash);
  goToView('runs', false);
  await loadRunsOnly();
}

function bindHelpNavigation() {
  $$('.help-toc a').forEach((anchor) => {
    anchor.onclick = (event) => {
      event.preventDefault();
      const target = new URL(anchor.href).hash || '#help';
      if (location.hash !== target) history.pushState(null, '', target);
      const parsed = parseHashState();
      goToView('help', false);
      scrollToHelpSection(parsed.section, true);
    };
  });
}

async function loadHelpLanguage(language = currentLanguage()) {
  const normalized = language === 'en' ? 'en' : 'de';
  const container = $('#help-container');
  if (!container || state.helpLanguage === normalized) return;
  container.className = 'help-fragment-loading';
  container.textContent = normalized === 'en' ? 'Loading manual …' : 'Anleitung wird geladen …';
  try {
    const response = await fetch(`/static/help.${normalized}.html?v=1.0.47`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    container.innerHTML = await response.text();
    container.className = '';
    state.helpLanguage = normalized;
    bindHelpNavigation();
    const section = parseHashState().section;
    if (hashView() === 'help' && section) scrollToHelpSection(section);
  } catch (error) {
    container.className = 'empty error';
    container.textContent = normalized === 'en' ? `Manual could not be loaded: ${error.message}` : `Anleitung konnte nicht geladen werden: ${error.message}`;
  }
}

function scrollToHelpSection(section, smooth = false) {
  if (!section) return;
  const target = document.getElementById(section);
  if (!target || !target.closest('#view-help')) return;
  requestAnimationFrame(() => target.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: 'start'}));
}

async function handleLocationChange() {
  const parsed = parseHashState();
  state.runFilter = parsed.status;
  goToView(parsed.view, false);
  if (parsed.view === 'help') scrollToHelpSection(parsed.section);
  if (parsed.view === 'runs' && state.settings) await loadRunsOnly();
}

window.addEventListener('hashchange', handleLocationChange);
window.addEventListener('popstate', handleLocationChange);

function runStatusLabel(status) {
  return ({all: 'alle', active: 'laufend/wartend', queued: 'wartet', running: 'läuft', success: 'erfolgreich', warning: 'Warnung', failed: 'fehlgeschlagen', cancelled: 'abgebrochen'})[status] || status;
}

function runRow(run) {
  const subject = run.job_name || (!run.job_id ? 'Repository-Verwaltung' : `Job ${run.job_id}`);
  const active = ['queued', 'running'].includes(run.status);
  const admin = state.currentUser?.role === 'admin';
  const runTitle = admin
    ? `<button class="entity-link" ${bbmAction('showRun', run.id)}>#${run.id} · ${esc(subject)}</button>`
    : `<b>#${run.id} · ${esc(subject)}</b>`;
  const actions = admin
    ? `<div class="table-actions"><button class="secondary" ${bbmAction('showRun', run.id)}>${active ? 'Live-Log' : 'Details'}</button>${active ? `<button class="danger" ${bbmAction('cancelExecution', run.id)}>Stoppen</button>` : `${run.job_id ? `<button class="secondary" ${bbmAction('retryExecution', run.id)}>Wiederholen</button>` : ''}<button class="danger ghost" ${bbmAction('deleteExecution', run.id)}>Löschen</button>`}</div>`
    : '<span class="muted">Nur Ansicht</span>';
  return `<tr><td data-label="Status"><span class="badge ${esc(run.status)}">${esc(runStatusLabel(run.status))}</span></td><td data-label="Lauf">${runTitle}<small>${esc(run.action)}</small></td><td data-label="Zeit">${esc(formatDate(run.created_at))}</td><td data-label="Dauer">${esc(formatDuration(run.duration_seconds))}</td><td data-label="Hinweis">${run.diagnosis ? `<span class="table-note warning-text">${esc(run.diagnosis.title)}</span>` : '–'}</td><td data-label="Aktionen">${actions}</td></tr>`;
}

function runTable(runs) {
  if (!runs.length) return '<div class="empty">Keine passenden Ausführungen vorhanden.</div>';
  return `<div class="table-scroll"><table class="data-table runs-table"><thead><tr><th>Status</th><th>Lauf</th><th>Zeit (${DISPLAY_TIME_ZONE})</th><th>Dauer</th><th>Hinweis</th><th>Aktionen</th></tr></thead><tbody>${runs.map(runRow).join('')}</tbody></table></div>`;
}



async function loadAll(background = false) {
  if (!background) setSyncState('Alle Bereiche werden aktualisiert …', 'pending', true);
  try {
    const requestedView = hashView();
    const storageRequest = (!background || requestedView === 'settings' || !state.runStorage)
      ? api('/runs/storage') : Promise.resolve(state.runStorage);
    const admin = state.currentUser?.role === 'admin';
    const usersRequest = admin ? api('/users') : Promise.resolve([]);
    const securityRequest = admin ? api('/users/security-status') : Promise.resolve(null);
    const backupsRequest = admin ? api('/backups') : Promise.resolve([]);
    const mountsRequest = admin ? api('/mounts') : Promise.resolve([]);
    const notificationSettingsRequest = admin ? api('/notifications/settings') : Promise.resolve(null);
    const notificationDeliveriesRequest = admin ? api('/notifications/deliveries?limit=100') : Promise.resolve([]);
    const protectedStorageRequest = admin ? storageRequest : Promise.resolve(null);
    const [dashboard, hosts, repos, jobs, schedules, runs, activeRuns, system, settings, backups, mounts, runStorage, users, securityStatus, notifications, notificationDeliveries] = await Promise.all([
      api('/dashboard'), api('/hosts'), api('/repositories'), api('/jobs'), api('/schedules'), api(`/runs?status=${encodeURIComponent(state.runFilter)}`), api('/runs?status=active&limit=100'),
      api('/system'), api('/settings'), backupsRequest, mountsRequest, protectedStorageRequest, usersRequest, securityRequest, notificationSettingsRequest, notificationDeliveriesRequest,
    ]);
    state.dashboard = dashboard;
    state.hosts = hosts;
    state.repos = repos;
    state.jobs = jobs;
    state.schedules = schedules;
    state.runs = runs;
    setActiveRuns(activeRuns);
    state.system = system;
    state.settings = settings;
    state.backups = backups;
    state.mounts = mounts;
    state.runStorage = runStorage;
    state.users = users;
    state.securityStatus = securityStatus;
    state.notifications = notifications;
    state.notificationDeliveries = notificationDeliveries;
    applyUserPermissions();
    const active = hashView();
    renderDashboard(dashboard);
    if (!background || active !== 'hosts') renderHosts();
    if (!background || active !== 'repositories') renderRepos();
    if (!background || active !== 'jobs') renderJobs();
    if (!background || active !== 'schedules') renderSchedules();
    if (!background || active !== 'runs') renderRuns();
    renderSystem();
    if (!background || active !== 'settings') renderSettings();
    if (!background || active !== 'notifications') renderNotifications();
    if (!background || active !== 'backups') renderBackups();
    if (!background || active !== 'users') renderUsers();
    fillSelects(background ? active : null);
    if (!background || active !== 'archives') renderLegacyMounts();
    scheduleRefresh();
    if (!background) setSyncState('Alle Bereiche aktualisiert', 'success');
  } catch (error) {
    if (!background) setSyncState('Aktualisierung fehlgeschlagen', 'error');
    if (error instanceof ApiError && error.status === 401) return;
    toast(error.message, true);
  }
}


async function loadRunsOnly() {
  try {
    const [runs, activeRuns] = await Promise.all([
      api(`/runs?status=${encodeURIComponent(state.runFilter)}`),
      api('/runs?status=active&limit=100'),
    ]);
    state.runs = runs;
    setActiveRuns(activeRuns);
    renderRuns();
  } catch (error) { toast(error.message, true); }
}


async function performAreaRefresh(areas, message = 'Änderungen werden übernommen …') {
  const requested = new Set(areas || []);
  if (!requested.size) return;
  setSyncState(message, 'pending', true);
  const active = hashView();
  const requests = [];
  const add = (name, promise) => requests.push(promise.then((value) => [name, value]));
  if (requested.has('dashboard')) add('dashboard', api('/dashboard'));
  if (requested.has('hosts')) add('hosts', api('/hosts'));
  if (requested.has('repositories')) add('repositories', api('/repositories'));
  if (requested.has('jobs')) add('jobs', api('/jobs'));
  if (requested.has('schedules')) add('schedules', api('/schedules'));
  if (requested.has('runs')) add('runs', api(`/runs?status=${encodeURIComponent(state.runFilter)}`));
  if (['dashboard', 'runs', 'jobs', 'repositories'].some((area) => requested.has(area))) add('activeRuns', api('/runs?status=active&limit=100'));
  if (requested.has('backups') && state.currentUser?.role === 'admin') add('backups', api('/backups'));
  if (requested.has('users') && state.currentUser?.role === 'admin') add('users', api('/users'));
  if (requested.has('security') && state.currentUser?.role === 'admin') add('security', api('/users/security-status'));
  if (requested.has('runStorage') && state.currentUser?.role === 'admin') add('runStorage', api('/runs/storage'));
  if (requested.has('mounts') && state.currentUser?.role === 'admin') add('mounts', api('/mounts'));
  if (requested.has('notifications') && state.currentUser?.role === 'admin') { add('notifications', api('/notifications/settings')); add('notificationDeliveries', api('/notifications/deliveries?limit=100')); }

  const values = Object.fromEntries(await Promise.all(requests));
  if ('dashboard' in values) state.dashboard = values.dashboard;
  if ('hosts' in values) state.hosts = values.hosts;
  if ('repositories' in values) state.repos = values.repositories;
  if ('jobs' in values) state.jobs = values.jobs;
  if ('schedules' in values) state.schedules = values.schedules;
  if ('runs' in values) state.runs = values.runs;
  if ('activeRuns' in values) setActiveRuns(values.activeRuns);
  if ('backups' in values) state.backups = values.backups;
  if ('users' in values) state.users = values.users;
  if ('security' in values) state.securityStatus = values.security;
  if ('runStorage' in values) state.runStorage = values.runStorage;
  if ('mounts' in values) state.mounts = values.mounts;
  if ('notifications' in values) state.notifications = values.notifications;
  if ('notificationDeliveries' in values) state.notificationDeliveries = values.notificationDeliveries;

  if ('dashboard' in values) renderDashboard(state.dashboard);
  if ('hosts' in values) renderHosts();
  if ('repositories' in values) renderRepos();
  if ('jobs' in values) renderJobs();
  if ('schedules' in values) renderSchedules();
  if ('runs' in values) renderRuns();
  if ('backups' in values) renderBackups();
  if ('users' in values || 'security' in values) renderUsers();
  if ('runStorage' in values && active === 'settings') renderSettings();
  if ('mounts' in values) renderLegacyMounts();
  if ('notifications' in values || 'notificationDeliveries' in values) renderNotifications();
  if (['hosts', 'repositories', 'jobs'].some((area) => requested.has(area))) fillSelects(active);
  setSyncState(`Aktualisiert · ${new Date().toLocaleTimeString(currentLocale())}`, 'success');
}

function refreshAreas(areas, message) {
  state.refreshQueue = state.refreshQueue.catch(() => {}).then(() => performAreaRefresh(areas, message));
  return state.refreshQueue.catch((error) => {
    setSyncState('Aktualisierung fehlgeschlagen', 'error');
    toast(error.message, true);
    throw error;
  });
}

function watchRunCompletion(runId, context = {}) {
  const id = Number(runId);
  const tracker = state.actionRuns.get(id) || {areas: [], repositoryId: null, refreshArchives: false, timer: null};
  tracker.areas = [...new Set([...(tracker.areas || []), ...(context.areas || ['dashboard', 'runs'])])];
  tracker.repositoryId = context.repositoryId || tracker.repositoryId;
  tracker.refreshArchives = Boolean(tracker.refreshArchives || context.refreshArchives);
  state.actionRuns.set(id, tracker);
  if (!tracker.timer) { tracker.timer = -1; pollRun(id); }
}

async function pollRun(runId) {
  const tracker = state.actionRuns.get(runId);
  if (!tracker) return;
  try {
    const run = await api('/runs/' + runId);
    updateActiveRun(run);
    if (!tracker.repositoryId && run.job_id) tracker.repositoryId = state.jobs.find((job) => job.id === run.job_id)?.repository_id || null;
    if (state.liveRunId === runId && $('#log-dialog').open) renderRunDialog(run);
    if (activeRunStatus(run.status)) {
      setSyncState(`Ausführung #${runId} ${run.status === 'queued' ? 'wartet' : 'läuft'} …`, 'pending', true);
      tracker.timer = setTimeout(() => pollRun(runId), 850);
      return;
    }
    await refreshAreas(tracker.areas, `Ausführung #${runId} abgeschlossen · Ansichten werden aktualisiert …`);
    state.actionRuns.delete(runId);
    if (tracker.refreshArchives && hashView() === 'archives' && Number($('#archive-repository').value) === Number(tracker.repositoryId)) {
      await loadArchives({silent: true});
    }
    const good = ['success', 'warning'].includes(run.status);
    const label = run.status === 'success' ? 'erfolgreich abgeschlossen' : run.status === 'warning' ? 'mit Warnung abgeschlossen' : run.status === 'cancelled' ? 'abgebrochen' : 'fehlgeschlagen';
    setSyncState(`Ausführung #${runId} ${label}`, good ? 'success' : 'error');
    toast(`Ausführung #${runId} ${label}`, !good);
  } catch (error) {
    tracker.timer = setTimeout(() => pollRun(runId), 1500);
    setSyncState(`Status von Ausführung #${runId} wird erneut abgefragt …`, 'pending', true);
  }
}

function syncRunFilterControls() {
  const filter = $('#runs-filter');
  if (filter) filter.value = state.runFilter;
  const search = $('#runs-search');
  if (search && search.value !== state.runSearch) search.value = state.runSearch;
  const label = $('#runs-filter-label');
  if (label) label.textContent = state.runFilter === 'all' ? 'Alle Ausführungen' : `Filter: ${runStatusLabel(state.runFilter)}`;
}


function sourceStatsLine(job, refreshable = false) {
  const hasStats = job.source_size_bytes != null || job.source_file_count != null;
  const sourceLabel = job.source_stats_origin === 'scan' ? 'Live-Scan vor Ausschlüssen' : 'letztes Backup';
  const values = hasStats
    ? `${formatBytes(job.source_size_bytes)} · ${job.source_file_count == null ? '–' : Number(job.source_file_count).toLocaleString(currentLocale())} Dateien`
    : 'noch nicht ermittelt';
  const checked = job.source_stats_checked_at ? ` · ${formatDate(job.source_stats_checked_at)}` : '';
  const refresh = refreshable && state.currentUser?.role === 'admin'
    ? `<button type="button" class="inline-action" ${bbmAction('action', job.id, 'source-stats')}>Aktualisieren</button>`
    : '';
  return `<span class="source-stat-line"><span><b>Quellenstatistik:</b> ${values}${hasStats ? ` · ${sourceLabel}` : ''}${checked}</span>${refresh}</span>`;
}

function dashboardJobTable(jobs) {
  if (!jobs?.length) return '<div class="empty">Noch keine Backup-Jobs angelegt.</div>';
  const rows = sortedDashboardJobs(jobs).map((job) => {
    const last = job.last_run;
    const schedule = job.schedule_mode === 'scheduled' && job.schedule_names?.length
      ? job.schedule_names.join(', ') : 'Manuell';
    const admin = state.currentUser?.role === 'admin';
    const lastRun = last
      ? `${admin ? `<button class="entity-link" ${bbmAction('showRun', last.id)}>#${last.id} · ${esc(formatDate(last.created_at))} · ${esc(formatDuration(last.duration_seconds))}</button>` : `<b>#${last.id} · ${esc(formatDate(last.created_at))} · ${esc(formatDuration(last.duration_seconds))}</b>`}<small><span class="badge ${esc(last.status)}">${esc(runStatusLabel(last.status))}</span> · ${last.trigger_type === 'schedule' ? `Zeitplan: ${esc(last.schedule_name || schedule)}` : 'Manuell'}</small>`
      : '<span>noch kein Backup</span><small>–</small>';
    const sizeRun = job.last_successful_backup || last;
    const deduplicated = sizeRun?.backup_deduplicated_size_bytes;
    const original = sizeRun?.backup_original_size_bytes;
    const compressed = sizeRun?.backup_compressed_size_bytes;
    const sizeSource = sizeRun && last && sizeRun.id !== last.id ? ` · aus Lauf #${sizeRun.id}` : '';
    const size = [deduplicated, original, compressed].some((value) => value != null)
      ? `<b>${formatBytes(deduplicated)}</b><small>Dedupliziert${sizeSource} · Original ${formatBytes(original)} · Komprimiert ${formatBytes(compressed)}</small>`
      : '<span>–</span><small>keine Statistik gespeichert</small>';
    const accessBlocked = job.repository_managed && !job.repository_access_ready;
    const startTitle = !job.enabled ? 'Backup-Job ist deaktiviert' : !job.host_enabled ? 'Gerät ist deaktiviert' : accessBlocked ? 'Repository-Zugang zuerst im Backup-Job einrichten' : 'Backup jetzt manuell starten';
    const startAction = admin
      ? `<button ${bbmAction('action', job.id, 'backup')} ${job.enabled && job.host_enabled && !accessBlocked ? '' : 'disabled'} title="${esc(startTitle)}">Starten</button>`
      : '<span class="muted">Nur Ansicht</span>';
    return `<tr><td data-label="Status"><span class="badge ${job.enabled ? 'success' : 'inactive'}">${job.enabled ? 'aktiv' : 'inaktiv'}</span></td><td data-label="Job"><button class="entity-link" ${bbmAction('goToView', 'jobs')}>${esc(job.name)}</button></td><td data-label="Gerät">${esc(job.host_name)}</td><td data-label="Repository">${esc(job.repository_name)}</td><td data-label="Quellen"><span class="path-list">${job.source_paths.map((path) => `<code>${esc(path)}</code>`).join('')}</span>${sourceStatsLine(job, false)}</td><td data-label="Zeitplan">${esc(schedule)}</td><td data-label="Letzter Job">${lastRun}</td><td data-label="Größe letzte Sicherung">${size}</td><td data-label="Aktion">${startAction}</td></tr>`;
  }).join('');
  return `<div class="table-scroll dashboard-jobs-scroll"><table class="data-table dashboard-jobs-table"><thead><tr><th>Status</th><th>Job</th><th>Gerät</th><th>Repository</th><th>Quellen</th><th>Zeitplan</th><th>Letzter Job</th><th>Größe letzte Sicherung</th><th>Aktion</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderDashboard(data) {
  const labels = {jobs: 'Backup-Jobs', running: 'Laufend', waiting: 'Wartend', failed: 'Fehlgeschlagen', repositories: 'Repositories'};
  const actions = {
    jobs: ['goToView', 'jobs'], running: ['goToRuns', 'running'], waiting: ['goToRuns', 'queued'],
    failed: ['goToRuns', 'failed'], repositories: ['goToView', 'repositories'],
  };
  const metrics = [
    {key: 'jobs', label: labels.jobs, value: data.counts.jobs, action: actions.jobs},
    {key: 'running', label: labels.running, value: data.counts.running, action: actions.running},
    {key: 'waiting', label: labels.waiting, value: data.counts.waiting, action: actions.waiting},
    {key: 'failed', label: labels.failed, value: data.counts.failed, action: actions.failed},
    {key: 'repositories', label: labels.repositories, value: data.counts.repositories, detail: `Gesamtgröße ${formatBytes(data.counts.repository_size_bytes)}`, action: actions.repositories},
  ];
  $('#metrics').innerHTML = metrics.map((metric) => {
    const [handler, ...args] = metric.action;
    return `<button type="button" class="metric" ${bbmAction(handler, ...args)}><strong>${metric.value}</strong><span>${metric.label}</span>${metric.detail ? `<small>${metric.detail}</small>` : ''}</button>`;
  }).join('');
  const warnings = state.hosts.filter((host) => ['critical', 'warning', 'unsupported', 'unknown'].includes(host.borg_version_status));
  const attention = $('#attention-panel');
  attention.classList.toggle('hidden', !warnings.length && !data.counts.failed);
  const warningRows = warnings.map((host) => `<tr><td data-label="Status"><span class="badge ${esc(host.borg_version_status)}">${esc(host.borg_version || 'unbekannt')}</span></td><td data-label="Bereich"><button class="entity-link" ${bbmAction('goToView', 'hosts')}>${esc(host.name)}</button></td><td data-label="Hinweis">${host.borg_version_status === 'critical' ? 'kritische Borg-Sicherheitswarnung' : host.borg_version_status === 'warning' ? 'veraltete Borg-Version' : 'Version prüfen'}</td></tr>`).join('');
  const failedRow = data.counts.failed ? `<tr><td data-label="Status"><span class="badge failed">${data.counts.failed}</span></td><td data-label="Bereich"><button class="entity-link" ${bbmAction('goToRuns', 'failed')}>Fehlgeschlagene Ausführungen</button></td><td data-label="Hinweis">Gefilterte Protokoll- und Diagnoseansicht öffnen</td></tr>` : '';
  attention.innerHTML = (!warnings.length && !data.counts.failed) ? '' : `<div class="panel-head"><div><p class="eyebrow">Aufmerksamkeit</p><h2>Offene Hinweise</h2></div></div><div class="table-scroll compact-table"><table class="data-table"><thead><tr><th>Status</th><th>Bereich</th><th>Hinweis</th></tr></thead><tbody>${warningRows}${failedRow}</tbody></table></div>`;
  $('#dashboard-jobs').innerHTML = dashboardJobTable(data.jobs || []);
  $('#recent-runs').innerHTML = data.runs.length ? runTable(data.runs) : '<div class="empty">Noch keine Aktivitäten.</div>';
}

function renderHosts() {
  if (!state.hosts.length) { $('#host-list').innerHTML = '<div class="empty">Noch keine Geräte angelegt.</div>'; return; }
  const rows = sortedHosts(state.hosts).map((host) => {
    const assignments = state.jobs.filter((job) => job.host_id === host.id && state.repos.some((repo) => repo.id === job.repository_id && repo.managed));
    const ready = host.repository_ready && assignments.length > 0;
    const versionText = host.borg_version ? `Borg ${esc(host.borg_version)}` : 'nicht geprüft';
    const versionClass = host.borg_version_status || 'unknown';
    return `<tr><td data-label="Status"><span class="badge ${host.enabled ? 'success' : 'inactive'}">${host.enabled ? 'aktiv' : 'inaktiv'}</span></td><td data-label="Gerät"><button class="entity-link" ${bbmAction('editHost', host.id)}>${esc(host.name)}</button></td><td data-label="SSH"><code>${esc(host.username)}@${esc(host.address)}:${host.port}</code></td><td data-label="Borg"><span class="badge ${esc(versionClass)}">${versionText}</span></td><td data-label="Repository-Zugänge">${assignments.length ? `${ready ? 'eingerichtet' : 'unvollständig'} · ${assignments.length}<small>Einrichtung direkt beim Backup-Job</small>` : 'keine Zuordnung'}</td><td data-label="Aktionen"><div class="table-actions"><button class="secondary" ${bbmAction('checkHostVersion', host.id)}>Borg prüfen</button><button class="${host.enabled ? 'danger ghost' : 'secondary'}" ${bbmAction('setHostEnabled', host.id, !host.enabled)}>${host.enabled ? 'Deaktivieren' : 'Aktivieren'}</button><button class="secondary" ${bbmAction('editHost', host.id)}>Bearbeiten</button><button class="danger ghost" ${bbmAction('removeEntity', 'hosts', host.id)}>Löschen</button></div></td></tr>`;
  }).join('');
  $('#host-list').innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr><th>Status</th><th>Gerät</th><th>SSH</th><th>Borg</th><th>Repository-Zugänge</th><th>Aktionen</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}


function renderRepos() {
  if (!state.repos.length) { $('#repo-list').innerHTML = '<div class="empty">Noch keine Repositories angelegt.</div>'; return; }
  const rows = sortedRepositories(state.repos).map((repo) => {
    const jobs = state.jobs.filter((job) => job.repository_id === repo.id);
    const hosts = new Set(jobs.map((job) => job.host_id)).size;
    const keyInfo = !repo.managed && repo.external_ssh_public_key
      ? `<small>Manager-SSH-Key · ${esc(repo.external_host_fingerprint || 'Hostkey gespeichert')}</small>` : '';
    const guardInfo = repo.managed
      ? `<small>Speicher-Sperre: ${repo.storage_guard_effective_enabled ? `ab ${repo.storage_guard_effective_threshold_percent} % (${repo.storage_guard_source === 'repository' ? 'Repository' : 'global'})` : 'deaktiviert'} · Belegung über Systemdiagnose</small>`
      : '';
    const detailsButton = repo.validation_details
      ? `<button type="button" class="inline-action" ${bbmAction('showRepositoryDiagnostic', repo.id)}>Details</button>` : '';
    const errorInfo = repo.validation_error
      ? `<small class="repository-error-summary">${esc(repo.validation_error)} ${detailsButton}</small>` : '';
    const hasBorgStats = [repo.original_size_bytes, repo.compressed_size_bytes, repo.deduplicated_size_bytes].some((value) => value != null);
    const sizeRows = [
      `<span><small>Original</small><b>${formatBytes(repo.original_size_bytes)}</b></span>`,
      `<span><small>Dedupliziert</small><b>${formatBytes(repo.deduplicated_size_bytes)}</b></span>`,
      `<span><small>Komprimiert</small><b>${formatBytes(repo.compressed_size_bytes)}</b></span>`,
      repo.managed ? `<span><small>Dateisystem</small><b>${formatBytes(repo.size_bytes)}</b></span>` : '',
    ].filter(Boolean).join('');
    const sizeInfo = hasBorgStats || (repo.managed && repo.size_bytes != null)
      ? `<div class="repository-size-grid">${sizeRows}</div><small>${repo.size_checked_at ? `Stand ${esc(formatDate(repo.size_checked_at))}` : 'noch nicht aktualisiert'}</small>`
      : `<span>nicht berechnet</span><small>Borg-Statistik${repo.managed ? ' und Dateisystembelegung' : ''}</small>`;
    const repositoryMissing = Boolean(repo.managed && repo.initialized && !repo.repository_present);
    const repositoryReady = Boolean(repo.initialized && (!repo.managed || repo.repository_present));
    const sizeButton = `<button class="secondary" ${bbmAction('refreshRepoSize', repo.id)} ${repositoryReady ? '' : 'disabled'}>Größe berechnen</button>`;
    const status = repositoryMissing
      ? {className: 'warning', label: 'Repository fehlt'}
      : repo.validation_error
        ? {className: 'warning', label: 'Prüfung fehlgeschlagen'}
        : repositoryReady
          ? {className: 'success', label: 'bereit'}
          : repo.repository_present
            ? {className: 'warning', label: 'Prüfung erforderlich'}
            : {className: 'warning', label: 'nicht initialisiert'};
    const initButton = repo.managed && !repo.repository_present
      ? repositoryMissing
        ? `<button class="danger ghost" ${bbmAction('resetRepositoryState', repo.id)}>Zurücksetzen</button>`
        : `<button class="secondary" ${bbmAction('initRepository', repo.id)}>Initialisieren</button>`
      : '';
    const cacheButton = state.currentUser?.role === 'admin'
      ? `<button class="secondary" ${bbmAction('clearRepositoryCache', repo.id)} ${repo.managed && !repositoryReady ? 'disabled' : ''}>Cache löschen</button>` : '';
    const compactButton = state.currentUser?.role === 'admin'
      ? `<button class="secondary" ${bbmAction('compactRepository', repo.id)} ${repositoryReady ? '' : 'disabled'}>Compact</button>` : '';
    return `<tr>
      <td data-label="Status" class="repo-status-cell"><span class="badge ${status.className}">${status.label}</span>${errorInfo}</td>
      <td data-label="ID" class="repo-id-cell"><code title="Manager-Repository-ID">#${repo.id}</code></td>
      <td data-label="Repository"><button class="entity-link" ${bbmAction('editRepository', repo.id)}>${esc(repo.name)}</button><small>${repo.managed ? 'verwaltet' : 'extern'} · ${esc(repo.encryption_mode)}</small>${keyInfo}${guardInfo}</td>
      <td data-label="Pfad/Zugriff"><code class="repo-location">${esc(repo.location)}</code><small>direkt im Manager-Container</small></td>
      <td data-label="Nutzung">${jobs.length} Job(s)<small>${hosts} Gerät(e)</small></td>
      <td data-label="Größe" class="repo-size-cell">${sizeInfo}</td>
      <td data-label="Aktionen"><div class="table-actions repo-table-actions">${initButton}<button class="secondary" ${bbmAction('testRepository', repo.id)}>Verbindung prüfen</button>${cacheButton}${!repo.managed && repo.external_ssh_public_key ? `<button class="secondary" ${bbmAction('copyRepositoryPublicKey', repo.id)}>Public Key</button>` : ''}${sizeButton}${compactButton}<button class="secondary" ${bbmAction('openRepositoryArchives', repo.id)} ${repositoryReady ? '' : 'disabled'}>Archive</button><button class="secondary" ${bbmAction('editRepository', repo.id)}>Bearbeiten</button><button class="danger ghost" ${bbmAction('removeEntity', 'repositories', repo.id)}>Löschen</button></div></td>
    </tr>`;
  }).join('');
  $('#repo-list').innerHTML = `<div class="table-scroll repository-table-scroll"><table class="data-table repositories-table"><thead><tr><th>Status</th><th>ID</th><th>Repository</th><th>Pfad/Zugriff</th><th>Nutzung</th><th>Größe</th><th>Aktionen</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function showRepositoryDiagnostic(id) {
  const repo = state.repos.find((item) => item.id === id);
  if (!repo) return;
  showTextDialog(`Repository-Diagnose · ${repo.name}`, repo.validation_details || repo.validation_error || 'Keine technischen Details gespeichert.');
}

async function copyRepositoryPublicKey(id) {
  const repo = state.repos.find((item) => item.id === id);
  if (!repo?.external_ssh_public_key) return;
  await copyText(repo.external_ssh_public_key, 'Öffentlicher Repository-Schlüssel kopiert', `Öffentlicher Schlüssel · ${repo.name}`);
}


async function setHostEnabled(id, enabled) {
  const host = state.hosts.find((item) => item.id === Number(id));
  const activeJobs = state.jobs.filter((item) => item.host_id === Number(id) && item.enabled);
  const prompt = currentLanguage() === 'en'
    ? enabled
      ? `Really enable device “${host?.name || ''}”? Its backup jobs remain disabled and must be enabled explicitly.`
      : `Really disable device “${host?.name || ''}”? ${activeJobs.length} active backup job(s) will also be disabled automatically.`
    : enabled
      ? `Gerät „${host?.name || ''}“ wirklich aktivieren? Die zugehörigen Backup-Jobs bleiben deaktiviert und müssen gezielt aktiviert werden.`
      : `Gerät „${host?.name || ''}“ wirklich deaktivieren? ${activeJobs.length} aktive Backup-Job(s) werden automatisch ebenfalls deaktiviert.`;
  if (!host || !confirm(prompt)) return;
  const release = markButtonBusy(actionButton(), enabled ? 'Wird aktiviert …' : 'Wird deaktiviert …');
  try {
    await api(`/hosts/${id}/enabled`, {method: 'POST', body: JSON.stringify({enabled: Boolean(enabled)})});
    const message = enabled
      ? 'Gerät aktiviert; Backup-Jobs bleiben deaktiviert'
      : activeJobs.length
        ? `Gerät und ${activeJobs.length} Backup-Job(s) deaktiviert`
        : 'Gerät deaktiviert';
    toast(message);
    await refreshAreas(['hosts', 'jobs', 'schedules', 'dashboard']);
  } catch (error) { toast(error.message, true); }
  finally { release(); }
}

async function setJobEnabled(id, enabled) {
  const job = state.jobs.find((item) => item.id === Number(id));
  const verb = enabled ? 'aktivieren' : 'deaktivieren';
  const prompt = currentLanguage() === 'en'
    ? `Really ${enabled ? 'enable' : 'disable'} backup job “${job?.name || ''}”?`
    : `Backup-Job „${job?.name || ''}“ wirklich ${verb}?`;
  if (!job || !confirm(prompt)) return;
  const release = markButtonBusy(actionButton(), enabled ? 'Wird aktiviert …' : 'Wird deaktiviert …');
  try {
    await api(`/jobs/${id}/enabled`, {method: 'POST', body: JSON.stringify({enabled: Boolean(enabled)})});
    toast(`Backup-Job ${enabled ? 'aktiviert' : 'deaktiviert'}`);
    await refreshAreas(['jobs', 'schedules', 'dashboard']);
  } catch (error) { toast(error.message, true); }
  finally { release(); }
}


function renderJobs() {
  const list = $('#job-list');
  const query = state.jobSearch.trim().toLocaleLowerCase(currentLocale());
  const jobs = sortedJobs(state.jobs.filter((job) => {
    const host = state.hosts.find((item) => item.id === job.host_id);
    const repo = state.repos.find((item) => item.id === job.repository_id);
    const matchesStatus = state.jobStatus === 'all' || (state.jobStatus === 'active' ? job.enabled : !job.enabled);
    const haystack = `${job.name} ${host?.name || ''} ${repo?.name || ''} ${job.source_paths.join(' ')}`.toLocaleLowerCase(currentLocale());
    return matchesStatus && (!query || haystack.includes(query));
  }));
  $('#job-count').textContent = `${jobs.length} von ${state.jobs.length} Jobs`;
  if (!jobs.length) { list.innerHTML = '<div class="empty">Keine passenden Backup-Jobs vorhanden.</div>'; return; }
  const rows = jobs.map((job) => {
    const host = state.hosts.find((item) => item.id === job.host_id);
    const repo = state.repos.find((item) => item.id === job.repository_id);
    const open = state.openJobActions.has(job.id);
    const admin = state.currentUser?.role === 'admin';
    const jobLink = admin ? `<button class="entity-link" ${bbmAction('editJob', job.id)}>${esc(job.name)}</button>` : `<b>${esc(job.name)}</b>`;
    const manageSection = admin ? `<section class="job-action-group"><div class="job-action-heading"><h4>Verwalten</h4></div><div class="job-action-buttons"><button class="${job.enabled ? 'danger ghost' : 'secondary'}" ${bbmAction('setJobEnabled', job.id, !job.enabled)}>${job.enabled ? 'Deaktivieren' : 'Aktivieren'}</button><button ${bbmAction('editJob', job.id)}>Job bearbeiten</button><button class="danger" ${bbmAction('removeEntity', 'jobs', job.id)}>Job löschen</button></div></section>` : '';
    const relocationButton = admin ? `<button class="secondary" ${bbmAction('confirmRepositoryLocation', job.id)}>Geänderten Repository-Standort bestätigen</button>` : '';
    const accessRequired = Boolean(repo?.managed);
    const accessReady = !accessRequired || job.repository_access_ready;
    const repositoryReady = Boolean(repo?.initialized && (!repo.managed || repo.repository_present));
    const accessSection = admin && accessRequired
      ? `<section class="job-action-group"><div class="job-action-heading"><h4>Repository-Zugang</h4><span class="badge ${accessReady ? 'success' : 'warning'}">${accessReady ? 'eingerichtet' : 'fehlt'}</span></div><p class="job-action-note">Nur für dieses Gerät und Repository.</p><div class="job-action-buttons"><button class="secondary" ${bbmAction('bootstrapJob', job.id)}>${accessReady ? 'Zugang erneuern' : 'Zugang einrichten'}</button></div></section>`
      : '';
    const startDisabled = !job.enabled || !host?.enabled || !accessReady || !repositoryReady;
    const startTitle = !job.enabled
      ? 'Backup-Job ist deaktiviert'
      : !host?.enabled
        ? 'Gerät ist deaktiviert'
      : !repositoryReady
        ? 'Repository fehlt oder ist nicht initialisiert'
        : !accessReady
          ? 'Repository-Zugang zuerst einrichten'
          : 'Backup jetzt starten';
    if (!admin) {
      return `<tr><td data-label="Status"><span class="badge ${job.enabled ? 'success' : 'inactive'}">${job.enabled ? 'aktiv' : 'inaktiv'}</span>${!repositoryReady ? '<small class="warning-text">Repository fehlt oder ist nicht initialisiert</small>' : accessRequired && !accessReady ? '<small class="warning-text">Repository-Zugang fehlt</small>' : ''}</td><td data-label="Job">${jobLink}<small><code>${esc(job.archive_prefix)}*</code></small></td><td data-label="Gerät">${esc(host?.name || '?')}</td><td data-label="Repository">${esc(repo?.name || '?')}</td><td data-label="Quellen"><span class="path-list">${job.source_paths.map((path) => `<code>${esc(path)}</code>`).join('')}</span>${sourceStatsLine(job, true)}</td><td data-label="Zeitplan"><span>${esc(job.schedule_mode === 'scheduled' ? (job.schedule_names || []).join(', ') : 'Manuell')}</span><small>${esc(job.compression)}</small></td><td data-label="Aktionen"><span class="muted">Nur Ansicht</span></td></tr>`;
    }
    return `<tr><td data-label="Status"><span class="badge ${job.enabled ? 'success' : 'inactive'}">${job.enabled ? 'aktiv' : 'inaktiv'}</span>${!repositoryReady ? '<small class="warning-text">Repository fehlt oder ist nicht initialisiert</small>' : accessRequired && !accessReady ? '<small class="warning-text">Repository-Zugang fehlt</small>' : ''}</td><td data-label="Job">${jobLink}<small><code>${esc(job.archive_prefix)}*</code></small></td><td data-label="Gerät">${esc(host?.name || '?')}</td><td data-label="Repository">${esc(repo?.name || '?')}</td><td data-label="Quellen"><span class="path-list">${job.source_paths.map((path) => `<code>${esc(path)}</code>`).join('')}</span>${sourceStatsLine(job, true)}</td><td data-label="Zeitplan"><span>${esc(job.schedule_mode === 'scheduled' ? (job.schedule_names || []).join(', ') : 'Manuell')}</span><small>${esc(job.compression)}</small></td><td data-label="Aktionen"><div class="table-actions"><button ${bbmAction('action', job.id, 'backup')} ${startDisabled ? 'disabled' : ''} title="${esc(startTitle)}">Starten</button><button class="secondary" ${bbmAction('openRepositoryArchives', job.repository_id)} ${repositoryReady ? '' : 'disabled'}>Archive</button><button class="secondary" data-job-toggle="${job.id}" ${bbmAction('toggleJobActions', job.id)}>${open ? 'Weniger' : 'Mehr'}</button></div></td></tr><tr class="job-detail-row ${open ? '' : 'hidden'}" data-job-detail="${job.id}"><td colspan="7"><div class="job-more-grid"><section class="job-action-group job-action-group-wide"><div class="job-action-heading"><h4>Prüfen</h4></div><div class="job-action-buttons"><button ${bbmAction('action', job.id, 'probe')} ${accessReady && repositoryReady ? '' : 'disabled'}>Verbindung</button><button ${bbmAction('action', job.id, 'info')} ${accessReady && repositoryReady ? '' : 'disabled'}>Job-Info</button><button ${bbmAction('action', job.id, 'version')}>Borg-Version</button><button ${bbmAction('action', job.id, 'source-stats')} ${host?.enabled ? '' : 'disabled'}>Quellenstatistik</button><button ${bbmAction('action', job.id, 'check')} ${accessReady && repositoryReady ? '' : 'disabled'}>Repository</button><button ${bbmAction('action', job.id, 'verify')} ${accessReady && repositoryReady ? '' : 'disabled'}>Vollprüfung</button>${relocationButton}</div></section>${accessSection}<section class="job-action-group"><div class="job-action-heading"><h4>Speicherpflege</h4></div><div class="job-action-buttons"><button ${bbmAction('action', job.id, 'prune')} ${accessReady && repositoryReady ? '' : 'disabled'}>Aufbewahrung</button><button ${bbmAction('action', job.id, 'compact')} ${accessReady && repositoryReady ? '' : 'disabled'}>Compact</button><button ${bbmAction('openRepositoryArchives', job.repository_id)} ${repositoryReady ? '' : 'disabled'}>Archive</button></div></section>${manageSection}</div></td></tr>`;
  }).join('');
  list.innerHTML = `<div class="table-scroll"><table class="data-table jobs-table"><thead><tr><th>Status</th><th>Job</th><th>Gerät</th><th>Repository</th><th>Quellen</th><th>Zeitplan</th><th>Aktionen</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function toggleJobActions(id) {
  const open = !state.openJobActions.has(id);
  if (open) state.openJobActions.add(id); else state.openJobActions.delete(id);
  const detail = document.querySelector(`[data-job-detail="${id}"]`);
  const button = document.querySelector(`[data-job-toggle="${id}"]`);
  if (detail) detail.classList.toggle('hidden', !open);
  if (button) button.textContent = open ? 'Weniger' : 'Mehr';
}



function selectedNumberValues(select) {
  return [...select.selectedOptions].map((option) => Number(option.value)).filter((value) => Number.isInteger(value) && value > 0);
}

function toggleScheduleTarget() {
  const mode = $('#schedule-target-mode').value;
  $('#schedule-target-hosts').classList.toggle('hidden', mode !== 'hosts');
  $('#schedule-target-repository').classList.toggle('hidden', mode !== 'repository');
  $('#schedule-target-jobs').classList.toggle('hidden', mode !== 'jobs');
}

function scheduleTargetSummary(schedule) {
  if (schedule.target_mode === 'repository') {
    return `Alle Jobs in ${state.repos.find((item) => item.id === schedule.target_repository_id)?.name || 'Repository'}`;
  }
  if (schedule.target_mode === 'hosts') {
    const names = schedule.target_host_ids.map((id) => state.hosts.find((item) => item.id === id)?.name || `Gerät ${id}`);
    return names.join(', ');
  }
  const names = schedule.target_job_ids.map((id) => state.jobs.find((item) => item.id === id)?.name || `Job ${id}`);
  return names.join(', ');
}

function renderSchedules() {
  const list = $('#schedule-list');
  $('#schedule-count').textContent = `${state.schedules.length} Zeitplan${state.schedules.length === 1 ? '' : 'e'}`;
  if (!state.schedules.length) {
    list.innerHTML = '<div class="empty">Noch keine zentralen Zeitpläne angelegt. Alle Backup-Jobs werden manuell ausgeführt.</div>';
    return;
  }
  const admin = state.currentUser?.role === 'admin';
  const rows = state.schedules.map((schedule) => `<tr><td data-label="Status"><span class="badge ${schedule.enabled ? 'success' : 'inactive'}">${schedule.enabled ? 'aktiv' : 'inaktiv'}</span></td><td data-label="Zeitplan"><b>${esc(schedule.name)}</b><small>${esc(scheduleSummary(schedule.expressions))} · Europe/Berlin</small></td><td data-label="Zuordnung">${esc(scheduleTargetSummary(schedule))}</td><td data-label="Jobs"><span class="badge">${schedule.assigned_job_count}</span></td><td data-label="Parallelität">${schedule.parallel_limit ? `max. ${schedule.parallel_limit}` : 'globale Grenze'}</td><td data-label="Aktionen">${admin ? `<div class="table-actions"><button class="secondary" ${bbmAction('editSchedule', schedule.id)}>Bearbeiten</button><button class="danger ghost" ${bbmAction('deleteSchedule', schedule.id)}>Löschen</button></div>` : '–'}</td></tr>`).join('');
  list.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr><th>Status</th><th>Zeitplan</th><th>Zielgruppe</th><th>Zugeordnete Jobs</th><th>Parallelität</th><th>Aktionen</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function resetScheduleForm() {
  const form = $('#schedule-form');
  if (!form) return;
  form.reset();
  form.elements.id.value = '';
  form.elements.enabled.checked = true;
  form.elements.parallel_limit.value = '0';
  form.elements.target_mode.value = 'hosts';
  $('#schedule-form-title').textContent = 'Zentralen Zeitplan erstellen';
  $('#cancel-schedule-edit').classList.add('hidden');
  setScheduleEditor(null);
  toggleScheduleTarget();
}

function editSchedule(id) {
  const schedule = state.schedules.find((item) => item.id === id); if (!schedule) return;
  goToView('schedules');
  const form = $('#schedule-form');
  form.elements.id.value = schedule.id;
  form.elements.name.value = schedule.name;
  form.elements.target_mode.value = schedule.target_mode;
  form.elements.parallel_limit.value = String(schedule.parallel_limit || 0);
  form.elements.enabled.checked = schedule.enabled;
  [...form.elements.target_host_ids.options].forEach((option) => { option.selected = schedule.target_host_ids.includes(Number(option.value)); });
  form.elements.target_repository_id.value = schedule.target_repository_id || '';
  [...form.elements.target_job_ids.options].forEach((option) => { option.selected = schedule.target_job_ids.includes(Number(option.value)); });
  setScheduleEditor(schedule.expressions);
  toggleScheduleTarget();
  $('#schedule-form-title').textContent = 'Zeitplan bearbeiten';
  $('#cancel-schedule-edit').classList.remove('hidden');
  form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function deleteSchedule(id) {
  const schedule = state.schedules.find((item) => item.id === id);
  if (!confirm(`Zeitplan „${schedule?.name || id}“ löschen? Die betroffenen Backup-Jobs werden danach manuell ausgeführt.`)) return;
  try { await api(`/schedules/${id}`, {method: 'DELETE'}); toast('Zeitplan gelöscht'); resetScheduleForm(); await refreshAreas(['dashboard', 'schedules', 'jobs']); }
  catch (error) { toast(error.message, true); }
}

function renderRuns() {
  const query = state.runSearch.trim().toLocaleLowerCase(currentLocale());
  const filtered = state.runs.filter((run) => {
    const haystack = `${run.id} ${run.job_name || ''} ${run.action} ${run.status} ${run.diagnosis?.title || ''}`.toLocaleLowerCase(currentLocale());
    return !query || haystack.includes(query);
  });
  $('#run-list').innerHTML = runTable(filtered);
  $('#runs-count').textContent = `${filtered.length} angezeigt`;
  syncRunFilterControls();
}


function replaceOptions(select, html) {
  if (!select) return;
  const selected = select.multiple ? new Set([...select.selectedOptions].map((option) => option.value)) : new Set([select.value]);
  select.innerHTML = html;
  if (select.multiple) [...select.options].forEach((option) => { option.selected = selected.has(option.value); });
  else if ([...select.options].some((option) => selected.has(option.value))) select.value = [...selected][0];
}

function fillSelects(skipView = null) {
  const hosts = state.hosts.map((item) => `<option value="${item.id}">${esc(item.name)}</option>`).join('');
  const repos = state.repos.map((item) => `<option value="${item.id}">${esc(item.name)}</option>`).join('');
  const jobs = state.jobs.map((job) => {
    const repo = state.repos.find((item) => item.id === job.repository_id);
    const host = state.hosts.find((item) => item.id === job.host_id);
    return `<option value="${job.id}">${esc(job.name)} · ${esc(repo?.name || '?')} · ${esc(host?.name || '?')}</option>`;
  }).join('');
  if (skipView !== 'jobs') {
    $$('select[name=host_id]').forEach((select) => replaceOptions(select, hosts));
    $$('select[name=repository_id]').forEach((select) => replaceOptions(select, repos));
  }
  if (skipView !== 'schedules') {
    replaceOptions($('#schedule-form select[name=target_host_ids]'), hosts);
    replaceOptions($('#schedule-form select[name=target_repository_id]'), repos);
    replaceOptions($('#schedule-form select[name=target_job_ids]'), jobs);
  }
  if (skipView !== 'restore') $$('select[name=job_id]').forEach((select) => replaceOptions(select, jobs));
  if (skipView !== 'archives') {
    replaceOptions($('#archive-repository'), repos);
    const storedRepository = localStorage.getItem('bbm-archive-repository');
    if (storedRepository && [...$('#archive-repository').options].some((option) => option.value === storedRepository)) $('#archive-repository').value = storedRepository;
    $('#archive-consider-checkpoints').checked = localStorage.getItem('bbm-archive-checkpoints') === '1';
  }
}

function renderSystem() {
  const controllerKey = state.system.controller_public_key || 'Controller-Schlüssel fehlt – Installer erneut ausführen.';
  $('#controller-key').textContent = controllerKey;
  const settingsKey = $('#settings-controller-key');
  if (settingsKey) settingsKey.textContent = controllerKey;
  $('#version-link').textContent = 'v' + (state.system.app_version || '?');
  $('#backup-path').textContent = state.system.backup_directory || '';
}

function effectiveTheme(value) {
  return value === 'auto' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : value;
}

function applyPreferences() {
  if (!state.settings) return;
  document.body.classList.toggle('compact', state.settings.density === 'compact');
  document.documentElement.style.setProperty('--list-max-height', state.settings.list_max_height + 'px');
  applyTheme(state.currentUser?.appearance || 'auto', false);
  $('#runs-limit').value = String(state.settings.runs_list_limit);
}

function renderExcludeTemplateSelect() {
  const select = $('#job-exclude-template');
  if (!select) return;
  const current = select.value;
  const templates = state.settings?.exclude_templates || [];
  select.innerHTML = '<option value="">Keine Vorlage ausgewählt</option>' + templates.map((template, index) => `<option value="${index}">${esc(template.name)} · ${template.patterns.length} Muster</option>`).join('');
  if ([...select.options].some((option) => option.value === current)) select.value = current;
}

function appendExcludeTemplateEditor(template = {name: '', patterns: []}) {
  const container = $('#exclude-template-editor');
  const card = document.createElement('article');
  card.className = 'exclude-template-card';
  card.innerHTML = `<div class="exclude-template-head"><label>Vorlagenname<input data-template-name maxlength="80" value="${esc(template.name || '')}" placeholder="z. B. Linux-Systempfade"></label><button type="button" class="danger ghost" data-remove-template>Vorlage entfernen</button></div><label>Ausschlussmuster <span>(einer pro Zeile)</span><textarea data-template-patterns rows="7" placeholder="/proc
/sys
/dev
/run
/tmp">${esc((template.patterns || []).join('\n'))}</textarea></label>`;
  card.querySelector('[data-remove-template]').onclick = () => card.remove();
  container.append(card);
}

function renderExcludeTemplateEditor() {
  const container = $('#exclude-template-editor');
  if (!container) return;
  container.innerHTML = '';
  const templates = state.settings?.exclude_templates || [];
  templates.forEach((template) => appendExcludeTemplateEditor(template));
  if (!templates.length) container.innerHTML = '<div class="empty template-empty">Keine Ausschlussvorlage angelegt.</div>';
}

function collectExcludeTemplates() {
  const cards = $$('.exclude-template-card');
  const templates = cards.map((card) => ({
    name: card.querySelector('[data-template-name]').value.trim(),
    patterns: lines(card.querySelector('[data-template-patterns]').value),
  })).filter((template) => template.name || template.patterns.length);
  for (const template of templates) {
    if (!template.name) throw new Error('Jede Ausschlussvorlage benötigt einen Namen');
    if (!template.patterns.length) throw new Error(`Die Ausschlussvorlage „${template.name}“ enthält keine Muster`);
  }
  const names = templates.map((template) => template.name.toLocaleLowerCase(currentLocale()));
  if (new Set(names).size !== names.length) throw new Error('Namen von Ausschlussvorlagen müssen eindeutig sein');
  return templates;
}

function renderSettings() {
  if (!state.settings) return;
  const form = $('#settings-form');
  for (const name of ['density', 'dashboard_recent_runs_limit', 'runs_list_limit', 'auto_refresh_seconds', 'list_max_height', 'run_retention_days', 'run_log_max_mib', 'run_log_view_kib', 'storage_guard_threshold_percent', 'max_parallel_runs']) form.elements[name].value = state.settings[name];
  form.elements.repository_size_after_run.checked = state.settings.repository_size_after_run;
  form.elements.compact_after_prune.checked = state.settings.compact_after_prune;
  form.elements.storage_guard_enabled.checked = state.settings.storage_guard_enabled;
  const storage = state.runStorage;
  const info = $('#run-storage-info');
  if (info && storage) {
    info.innerHTML = `<b>${storage.finished_runs} abgeschlossene Protokolle</b> · Logdateien ${formatBytes(storage.log_file_bytes)} · DB-Protokollanteil ${formatBytes(storage.database_log_payload_bytes)} · SQLite-Datei ${formatBytes(storage.database_file_bytes)}<br><span>Speicherort: <code>${esc(storage.log_directory)}</code>${storage.oldest_run ? ' · ältester Lauf ' + esc(formatDate(storage.oldest_run)) : ''}</span>`;
  }
  renderExcludeTemplateEditor();
  renderExcludeTemplateSelect();
  applyPreferences();
}

function notificationChannelLabel(channel) {
  return ({email: 'E-Mail', webhook: 'Webhook', telegram: 'Telegram'})[channel] || channel;
}

function notificationEventLabel(eventType) {
  return ({
    backup_failed: 'Backup fehlgeschlagen', backup_warning: 'Backup mit Warnungen', backup_success: 'Backup erfolgreich',
    run_cancelled: 'Ausführung abgebrochen', repository_failed: 'Repository-Aktion fehlgeschlagen',
    repository_warning: 'Repository-Aktion mit Warnungen', repository_success: 'Repository-Aktion erfolgreich',
    schedule_failed: 'Zeitplanausführung fehlgeschlagen', schedule_warning: 'Zeitplanausführung mit Warnungen',
    schedule_success: 'Zeitplanausführung erfolgreich', operation_failed: 'Sonstige Aktion fehlgeschlagen',
    operation_warning: 'Sonstige Aktion mit Warnungen', operation_success: 'Sonstige Aktion erfolgreich', test: 'Testbenachrichtigung',
  })[eventType] || eventType;
}

function renderNotifications() {
  const settings = state.notifications;
  const form = $('#notification-form');
  if (!settings || !form) return;
  for (const name of ['enabled', 'include_error_excerpt', 'smtp_enabled', 'webhook_enabled', 'telegram_enabled']) {
    form.elements[name].checked = Boolean(settings[name]);
  }
  for (const name of ['instance_name', 'language', 'timeout_seconds', 'smtp_host', 'smtp_port', 'smtp_security', 'smtp_username', 'email_from', 'webhook_kind', 'telegram_chat_id']) {
    form.elements[name].value = settings[name] ?? '';
  }
  form.elements.email_recipients.value = (settings.email_recipients || []).join('\n');
  form.elements.smtp_password.value = ''; form.elements.webhook_url.value = ''; form.elements.telegram_bot_token.value = '';
  form.elements.smtp_clear_password.checked = false; form.elements.webhook_clear_url.checked = false; form.elements.telegram_clear_token.checked = false;
  const selectedEvents = new Set(settings.events || []);
  form.querySelectorAll('input[name="events"]').forEach((input) => { input.checked = selectedEvents.has(input.value); });
  $('#smtp-secret-status').textContent = settings.smtp_password_set ? 'SMTP-Passwort ist verschlüsselt gespeichert.' : 'Kein SMTP-Passwort gespeichert.';
  $('#webhook-secret-status').textContent = settings.webhook_url_set ? 'Webhook-URL ist verschlüsselt gespeichert.' : 'Keine Webhook-URL gespeichert.';
  $('#telegram-secret-status').textContent = settings.telegram_token_set ? 'Telegram-Bot-Token ist verschlüsselt gespeichert.' : 'Kein Bot-Token gespeichert.';
  const deliveries = state.notificationDeliveries || [];
  const target = $('#notification-delivery-list');
  if (!target) return;
  if (!deliveries.length) { target.innerHTML = '<div class="empty">Noch keine Benachrichtigungen versendet.</div>'; return; }
  target.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr><th>Status</th><th>Zeit</th><th>Kanal</th><th>Ereignis</th><th>Titel</th><th>Ergebnis</th></tr></thead><tbody>${deliveries.map((item) => `<tr><td data-label="Status"><span class="badge ${item.status === 'success' ? 'success' : 'failed'}">${item.status === 'success' ? 'versendet' : 'Fehler'}</span></td><td data-label="Zeit">${esc(formatDate(item.created_at))}</td><td data-label="Kanal">${esc(notificationChannelLabel(item.channel))}</td><td data-label="Ereignis">${esc(notificationEventLabel(item.event_type))}</td><td data-label="Titel">${esc(item.title)}</td><td data-label="Ergebnis" class="notification-delivery-detail">${esc(item.detail || '–')}${item.run_id ? `<small>Ausführung #${esc(item.run_id)}</small>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
}

function notificationPayload(formElement) {
  const form = new FormData(formElement);
  const payload = {
    enabled: form.get('enabled') === 'on', instance_name: String(form.get('instance_name') || '').trim(),
    language: form.get('language'), events: [...formElement.querySelectorAll('input[name="events"]:checked')].map((input) => input.value),
    include_error_excerpt: form.get('include_error_excerpt') === 'on', timeout_seconds: +form.get('timeout_seconds'),
    smtp_enabled: form.get('smtp_enabled') === 'on', smtp_host: String(form.get('smtp_host') || '').trim(), smtp_port: +form.get('smtp_port'),
    smtp_security: form.get('smtp_security'), smtp_username: String(form.get('smtp_username') || '').trim(),
    smtp_clear_password: form.get('smtp_clear_password') === 'on', email_from: String(form.get('email_from') || '').trim(),
    email_recipients: String(form.get('email_recipients') || '').split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean),
    webhook_enabled: form.get('webhook_enabled') === 'on', webhook_kind: form.get('webhook_kind'), webhook_clear_url: form.get('webhook_clear_url') === 'on',
    telegram_enabled: form.get('telegram_enabled') === 'on', telegram_clear_token: form.get('telegram_clear_token') === 'on', telegram_chat_id: String(form.get('telegram_chat_id') || '').trim(),
  };
  const smtpPassword = String(form.get('smtp_password') || ''); if (smtpPassword) payload.smtp_password = smtpPassword;
  const webhookUrl = String(form.get('webhook_url') || ''); if (webhookUrl) payload.webhook_url = webhookUrl;
  const telegramToken = String(form.get('telegram_bot_token') || ''); if (telegramToken) payload.telegram_bot_token = telegramToken;
  return payload;
}

async function testNotification(channel, button) {
  const release = markButtonBusy(button, 'Test wird gesendet …');
  try {
    state.notifications = await api('/notifications/settings', {method: 'PUT', body: JSON.stringify(notificationPayload($('#notification-form')))});
    const result = await api('/notifications/test', {method: 'POST', body: JSON.stringify({channel})});
    toast(`${notificationChannelLabel(channel)}-Test erfolgreich versendet`);
    await refreshAreas(['notifications']);
    return result;
  } catch (error) { toast(error.message, true); throw error; }
  finally { release(); }
}

function renderBackups() {
  const restoreSelect = $('#backup-restore-form')?.elements.name;
  const selected = restoreSelect?.value || '';
  if (restoreSelect) {
    restoreSelect.innerHTML = '<option value="">Backup auswählen</option>' + state.backups.map((backup) => `<option value="${esc(backup.name)}">${backup.encrypted ? '🔒 ' : ''}${esc(backup.name)}</option>`).join('');
    if ([...restoreSelect.options].some((option) => option.value === selected)) restoreSelect.value = selected;
  }
  $('#backup-list').innerHTML = state.backups.length ? state.backups.map((backup) => `<div class="entity"><div class="backup-meta"><div class="entity-title"><h3>${esc(backup.name)}</h3><span class="badge ${backup.encrypted ? 'warning' : 'success'}">${backup.encrypted ? 'verschlüsselt' : 'ZIP'}</span></div><p>Version ${esc(backup.manifest?.app_version || '?')} · ${esc(formatDate(backup.modified_at))} · ${formatBytes(backup.size_bytes)}${backup.manifest?.label ? ' · ' + esc(backup.manifest.label) : ''}</p></div><div class="actions"><button class="secondary" data-backup-restore="${esc(backup.name)}">Wiederherstellen</button><button data-backup-download="${esc(backup.name)}">Download</button><button class="danger" data-backup-delete="${esc(backup.name)}">Löschen</button></div></div>`).join('') : '<div class="empty">Noch keine Manager-Backups vorhanden.</div>';
  $$('[data-backup-restore]').forEach((button) => button.onclick = () => {
    const select = $('#backup-restore-form').elements.name;
    select.value = button.dataset.backupRestore;
    $('#backup-restore-form').scrollIntoView({behavior: 'smooth', block: 'start'});
    select.focus();
  });
  $$('[data-backup-download]').forEach((button) => button.onclick = () => downloadBackup(button.dataset.backupDownload));
  $$('[data-backup-delete]').forEach((button) => button.onclick = () => deleteBackup(button.dataset.backupDelete));
}


function renderUsers() {
  const list = $('#user-list');
  if (!list || state.currentUser?.role !== 'admin') return;
  const status = state.securityStatus;
  if (status) $('#security-status').textContent = `${status.users} Benutzer · ${status.administrators ?? state.users.filter((item) => item.role === 'admin').length} Administratoren · ${status.sessions} aktive Sitzungen · ${status.encrypted_secrets ?? 0} verschlüsselte Geheimnisse · ${status.sensitive_storage_ok ? 'Sicherheitsprüfung OK' : 'Sicherheitsprüfung erforderlich'} · ${status.secret_database || status.database}`;
  if (!state.users.length) { list.innerHTML = '<div class="empty">Keine Benutzer vorhanden.</div>'; return; }
  const administratorCount = state.users.filter((item) => item.role === 'admin').length;
  const rows = state.users.map((user) => {
    const own = user.id === state.currentUser?.id;
    const lastAdministrator = user.role === 'admin' && administratorCount <= 1;
    const accountActions = own
      ? `<span class="hint">${lastAdministrator ? 'Eigenes Konto · letzter Administrator geschützt' : 'Eigenes Passwort über die Seitenleiste ändern'}</span>`
      : `<button class="secondary" ${bbmAction('resetUserPassword', user.id)}>Passwort setzen</button>${lastAdministrator ? '<button class="danger ghost" disabled title="Der letzte Administrator kann nicht gelöscht werden">Letzter Administrator</button>' : `<button class="danger ghost" ${bbmAction('deleteUser', user.id)}>Löschen</button>`}`;
    return `<tr><td data-label="Status"><span class="badge ${user.enabled ? 'success' : 'inactive'}">${user.enabled ? 'aktiv' : 'inaktiv'}</span></td><td data-label="Benutzer"><b>${esc(user.username)}</b>${user.must_change_password ? '<small>Passwortwechsel erforderlich</small>' : ''}</td><td data-label="Rolle">${user.role === 'admin' ? 'Administrator' : 'Benutzer'}${lastAdministrator ? '<small>Letzter Administrator · geschützt</small>' : ''}</td><td data-label="Letzte Anmeldung">${esc(formatDate(user.last_login_at))}</td><td data-label="Aktionen"><div class="table-actions"><button class="secondary" ${bbmAction('editUser', user.id)}>Bearbeiten</button>${accountActions}</div></td></tr>`;
  }).join('');
  list.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr><th>Status</th><th>Benutzer</th><th>Rolle</th><th>Letzte Anmeldung</th><th>Aktionen</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function resetUserForm() {
  const form = $('#user-form'); if (!form) return;
  form.reset(); form.elements.id.value = ''; form.elements.role.value = 'user'; form.elements.role.disabled = false; form.elements.enabled.disabled = false; form.elements.must_change_password.checked = true;
  $('#user-password-fields').classList.remove('hidden'); $('#user-enabled-field').classList.add('hidden');
  form.elements.password.required = true; form.elements.password_confirm.required = true;
  $('#user-form-title').textContent = 'Benutzer anlegen'; $('#user-submit').textContent = 'Benutzer anlegen'; $('#cancel-user-edit').classList.add('hidden');
}

function editUser(id) {
  const user = state.users.find((item) => item.id === id); if (!user) return;
  const form = $('#user-form'); const own = user.id === state.currentUser?.id;
  form.elements.id.value = user.id; form.elements.username.value = user.username; form.elements.role.value = user.role; form.elements.enabled.checked = user.enabled;
  form.elements.role.disabled = own; form.elements.enabled.disabled = own;
  $('#user-password-fields').classList.add('hidden'); $('#user-enabled-field').classList.remove('hidden');
  form.elements.password.required = false; form.elements.password_confirm.required = false;
  $('#user-form-title').textContent = 'Benutzer bearbeiten'; $('#user-submit').textContent = 'Änderungen speichern'; $('#cancel-user-edit').classList.remove('hidden');
  form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function resetUserPassword(id) {
  const user = state.users.find((item) => item.id === id); if (!user) return;
  const form = $('#user-password-form'); form.reset(); form.elements.user_id.value = id;
  form.elements.must_change_password.checked = true;
  $('#user-password-dialog-user').textContent = user.username;
  $('#user-password-error').textContent = '';
  $('#user-password-dialog').showModal();
}

async function deleteUser(id) {
  const user = state.users.find((item) => item.id === id);
  const administratorCount = state.users.filter((item) => item.role === 'admin').length;
  if (user?.role === 'admin' && administratorCount <= 1) {
    toast('Der letzte Administrator kann nicht gelöscht werden', true);
    return;
  }
  if (!confirm('Benutzerkonto wirklich löschen? Alle Sitzungen dieses Kontos werden beendet.')) return;
  try { await api(`/users/${id}`, {method: 'DELETE'}); toast('Benutzer gelöscht'); await refreshAreas(['users', 'security']); }
  catch (error) { toast(error.message, true); }
}

async function rotateControllerKey() {
  const form = $('#controller-key-confirm-form');
  form.reset();
  $('#controller-key-confirm-error').textContent = '';
  $('#controller-key-dialog').showModal();
}

async function refreshRepoSize(id) {
  const repo = state.repos.find((item) => item.id === id);
  const release = markButtonBusy(actionButton(), 'Wird berechnet …');
  setRepositoryStatus(`${repo?.name || 'Repository'}: Größenberechnung läuft …`, false, '', true);
  setSyncState('Repository-Größe wird berechnet …', 'pending', true);
  try {
    const result = await api(`/repositories/${id}/refresh-size`, {method: 'POST'});
    await refreshAreas(['dashboard', 'repositories']);
    const parts = [
      `Original ${formatBytes(result.original_size_bytes)}`,
      `komprimiert ${formatBytes(result.compressed_size_bytes)}`,
      `dedupliziert ${formatBytes(result.deduplicated_size_bytes)}`,
    ];
    if (result.filesystem_size_bytes != null) parts.push(`Dateisystem ${formatBytes(result.filesystem_size_bytes)}`);
    setRepositoryStatus(`${repo?.name || 'Repository'}: ${parts.join(' · ')}.`);
  } catch (error) {
    await refreshAreas(['repositories']);
    const updated = state.repos.find((item) => item.id === id);
    setRepositoryStatus(error.message, true, updated?.validation_details || '');
    setSyncState('Größenberechnung fehlgeschlagen', 'error');
  } finally { release(); }
}

async function deleteBackup(name) {
  if (!confirm('Manager-Backup wirklich löschen?')) return;
  const release = markButtonBusy(actionButton(), 'Wird gelöscht …');
  try {
    await api('/backups/' + encodeURIComponent(name), {method: 'DELETE'});
    await refreshAreas(['backups']);
    toast('Backup gelöscht');
  } catch (error) { setSyncState('Backup konnte nicht gelöscht werden', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function downloadBackup(name) {
  try {
    const response = await fetch('/api/backups/' + encodeURIComponent(name) + '/download', {credentials: 'same-origin'});
    if (!response.ok) throw new Error('Download fehlgeschlagen');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = name; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message, true); }
}

async function loadReleaseNotes() {
  try {
    const result = await api(`/system/release-notes?language=${encodeURIComponent(currentLanguage())}`);
    $('#release-version').textContent = 'v' + result.version;
    $('#release-content').textContent = result.content || 'Keine Release Notes vorhanden.';
  } catch (error) { toast(error.message, true); }
}

function scheduleRefresh() {
  clearTimeout(state.refreshTimer);
  if (state.settings) state.refreshTimer = setTimeout(() => loadAll(true), state.settings.auto_refresh_seconds * 1000);
}

async function removeEntity(type, id) {
  const messages = {
    jobs: 'Backup-Job wirklich löschen? Vorhandene Borg-Archive und abgeschlossene Protokolle bleiben erhalten.',
    repositories: 'Repository-Eintrag wirklich entfernen? Repository-Daten werden dadurch nicht automatisch gelöscht.',
    hosts: 'Gerät wirklich entfernen?',
  };
  if (!confirm(messages[type] || 'Eintrag wirklich entfernen?')) return;
  const release = markButtonBusy(actionButton(), 'Wird gelöscht …');
  const impacts = {
    jobs: ['dashboard', 'jobs', 'hosts', 'repositories', 'schedules'],
    repositories: ['dashboard', 'repositories', 'jobs', 'schedules'],
    hosts: ['dashboard', 'hosts', 'jobs', 'schedules'],
  };
  try {
    await api(`/${type}/${id}`, {method: 'DELETE'});
    await refreshAreas(impacts[type] || ['dashboard']);
    toast('Eintrag entfernt');
  } catch (error) { setSyncState('Löschen fehlgeschlagen', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function action(id, name) {
  const release = markButtonBusy(actionButton(), 'Wird gestartet …');
  try {
    const result = await api(`/jobs/${id}/actions/${name}`, {method: 'POST'});
    const impact = runImpact(id, name);
    await refreshAreas(['dashboard', 'runs'], `Ausführung #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, impact);
    toast(`Ausführung #${result.run_id} gestartet`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState('Aktion konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function confirmRepositoryLocation(id) {
  const warning = 'Nur bestätigen, wenn dieses Repository absichtlich verschoben oder unter einer neuen URL eingebunden wurde und SSH-Fingerprint sowie Zielpfad geprüft wurden. Die Aktion wird repositoryweit eingereiht; mehrere Jobs desselben Geräts verwenden denselben Bestätigungslauf. Borg aktualisiert anschließend den Sicherheitsstatus dieses Clients. Fortfahren?';
  if (!confirm(warning)) return;
  const release = markButtonBusy(actionButton(), 'Wird bestätigt …');
  try {
    const result = await api(`/jobs/${id}/confirm-repository-location`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs'], `Standortbestätigung #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, runImpact(id, 'confirm-location'));
    toast(`Standortbestätigung #${result.run_id} eingereiht`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState('Standortbestätigung konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function checkHostVersion(id) {
  const release = markButtonBusy(actionButton(), 'Borg wird geprüft …');
  setSyncState('Borg-Version wird geprüft …', 'pending', true);
  try {
    const result = await api(`/hosts/${id}/check-version`, {method: 'POST'});
    await refreshAreas(['dashboard', 'hosts']);
    const heading = `${result.title}${result.version ? ' · Borg ' + result.version : ''}`;
    showTextDialog(heading, `${result.output || ''}\n\nBewertung: ${result.message}`.trim());
  } catch (error) { setSyncState('Borg-Prüfung fehlgeschlagen', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function bootstrapJob(id) {
  const job = state.jobs.find((item) => item.id === id);
  const release = markButtonBusy(actionButton(), 'Zugang wird eingerichtet …');
  setSyncState('Repository-Zugang für den Backup-Job wird eingerichtet …', 'pending', true);
  try {
    await api(`/jobs/${id}/bootstrap-repository`, {method: 'POST'});
    await refreshAreas(['dashboard', 'hosts', 'jobs', 'repositories']);
    setSyncState(`Repository-Zugang für „${job?.name || id}“ eingerichtet`, 'success');
    toast('Repository-Zugang eingerichtet');
  } catch (error) { setSyncState('Einrichtung fehlgeschlagen', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function resetRepositoryState(id) {
  const repo = state.repos.find((item) => item.id === id);
  if (!repo) return;
  const english = currentLanguage() === 'en';
  const warning = english
    ? `Reset the manager state for repository “${repo.name}”?\n\nThis is allowed only when the managed target directory contains no Borg config and is completely empty. No repository files are deleted. Validation, size and initialization metadata are cleared; afterwards the repository can be initialized again.`
    : `Managerstatus für Repository „${repo.name}“ zurücksetzen?\n\nDies ist nur möglich, wenn der verwaltete Zielordner keine Borg-Konfiguration enthält und vollständig leer ist. Es werden keine Repository-Dateien gelöscht. Prüf-, Größen- und Initialisierungsdaten werden zurückgesetzt; anschließend kann das Repository neu initialisiert werden.`;
  if (!confirm(warning)) return;
  const release = markButtonBusy(actionButton(), english ? 'State is being reset …' : 'Status wird zurückgesetzt …');
  try {
    const result = await api(`/repositories/${id}/reset`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs', 'repositories', 'jobs'], english ? 'Repository state was reset …' : 'Repository-Status wurde zurückgesetzt …');
    toast(english ? 'Repository state reset; initialization is available again' : 'Repository-Status zurückgesetzt; Initialisieren ist wieder verfügbar');
    if (result.run_id) showRun(result.run_id);
  } catch (error) {
    setSyncState(english ? 'Repository state could not be reset' : 'Repository-Status konnte nicht zurückgesetzt werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}


async function initRepository(id) {
  const release = markButtonBusy(actionButton(), 'Wird gestartet …');
  try {
    const result = await api(`/repositories/${id}/init`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs', 'repositories'], `Initialisierung #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories'], repositoryId: id, refreshArchives: true});
    toast(`Initialisierung #${result.run_id} gestartet`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState('Initialisierung konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function compactRepository(id) {
  const repo = state.repos.find((item) => item.id === id);
  if (!repo) return;
  const english = currentLanguage() === 'en';
  const warning = english
    ? `Run Compact directly on repository “${repo.name}”?\n\nThis operates independently of a backup job. It cannot start while another repository operation or an archive mount is active.`
    : `Compact direkt am Repository „${repo.name}“ ausführen?\n\nDie Aktion ist unabhängig von einem Backup-Job. Sie kann nicht starten, solange eine andere Repository-Aktion oder ein Archiv-Mount aktiv ist.`;
  if (!confirm(warning)) return;
  const release = markButtonBusy(actionButton(), english ? 'Compact is starting …' : 'Compact wird gestartet …');
  try {
    const result = await api(`/repositories/${id}/compact`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs'], `${english ? 'Compact execution' : 'Compact-Ausführung'} #${result.run_id} ${english ? 'was accepted' : 'wurde angenommen'} …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories'], repositoryId: id, refreshArchives: true});
    toast(`${english ? 'Compact execution' : 'Compact-Ausführung'} #${result.run_id} ${english ? 'started' : 'gestartet'}`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState(english ? 'Compact could not be started' : 'Compact konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function testRepository(id) {
  const repo = state.repos.find((item) => item.id === id);
  const english = currentLanguage() === 'en';
  const release = markButtonBusy(actionButton(), english ? 'Queueing connection test …' : 'Verbindung wird eingereiht …');
  setRepositoryStatus(
    `${repo?.name || 'Repository'}: ${english ? 'connection test is being queued' : 'Verbindungsprüfung wird eingereiht'} …`,
    false, '', true,
  );
  setSyncState(
    english ? 'Repository connection test is being queued …' : 'Repository-Verbindung wird geprüft und eingereiht …',
    'pending', true,
  );
  try {
    const result = await api(`/repositories/${id}/test`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs', 'repositories']);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories'], repositoryId: id});
    toast(english ? `Repository test #${result.run_id} queued` : `Repository-Prüfung #${result.run_id} eingereiht`);
    showRun(result.run_id);
  } catch (error) {
    await refreshAreas(['repositories']);
    const updated = state.repos.find((item) => item.id === id);
    setRepositoryStatus(error.message, true, updated?.validation_details || '');
    setSyncState(english ? 'Repository test could not be queued' : 'Repository-Prüfung konnte nicht eingereiht werden', 'error');
  } finally { release(); }
}

async function clearRepositoryCache(id) {
  const repo = state.repos.find((item) => item.id === id);
  if (!repo) return;
  const warning = [
    `Lokalen Borg-Cache für „${repo.name}“ löschen?`,
    '',
    'Dabei werden keine Archive, keine Repository-Konfiguration und keine Passphrase gelöscht.',
    'Der nächste Zugriff kann länger dauern, weil Borg den Cache neu aufbaut.',
  ].join('\n');
  if (!confirm(warning)) return;
  const release = markButtonBusy(actionButton(), 'Cache wird gelöscht …');
  setRepositoryStatus(`${repo.name}: lokaler Borg-Cache wird gelöscht …`, false, '', true);
  setSyncState('Repository-Cache wird gelöscht …', 'pending', true);
  try {
    const result = await api(`/repositories/${id}/clear-cache`, {method: 'POST'});
    await refreshAreas(['repositories']);
    const legacy = result.legacy_cache_removed ? ' Der bisherige Cache im Repository-Mount wurde ebenfalls entfernt.' : '';
    const legacyWarning = result.legacy_cache_error ? ` Alt-Cache konnte nicht entfernt werden: ${result.legacy_cache_error}` : '';
    setRepositoryStatus(`${repo.name}: lokaler Borg-Cache gelöscht.${legacy}${legacyWarning} Verbindung jetzt erneut prüfen.`, Boolean(result.legacy_cache_error));
  } catch (error) {
    setRepositoryStatus(error.message, true);
    setSyncState('Cache-Löschung fehlgeschlagen', 'error');
  } finally { release(); }
}

function setLogTab(tab) {
  $$('[data-log-tab]').forEach((button) => button.classList.toggle('active', button.dataset.logTab === tab));
  $$('.log-view').forEach((view) => view.classList.toggle('active', view.id === `log-view-${tab}`));
}

function warningCauseText(kind, reason = '') {
  const english = currentLanguage() === 'en';
  const labels = english ? {
    changed: ['Changed', 'Changed while the backup was reading it'],
    permission: ['Access denied', 'The Borg user could not read this path'],
    missing: ['Disappeared', 'The path no longer existed when Borg tried to read it'],
    io: ['I/O error', 'The filesystem reported an input/output error'],
    error: ['Read error', 'Borg reported a file access or read error'],
    other: ['Warning', reason || 'Borg reported an additional warning'],
    unknown: ['Cause not emitted', 'Borg returned warning status without a specific detail line'],
  } : {
    changed: ['Verändert', 'Während der Sicherung verändert'],
    permission: ['Zugriff verweigert', 'Der Borg-Benutzer konnte diesen Pfad nicht lesen'],
    missing: ['Nicht mehr vorhanden', 'Der Pfad war beim Lesen durch Borg nicht mehr vorhanden'],
    io: ['E/A-Fehler', 'Das Dateisystem meldete einen Ein-/Ausgabefehler'],
    error: ['Lesefehler', 'Borg meldete einen Datei-Zugriffs- oder Lesefehler'],
    other: ['Warnung', reason || 'Borg meldete einen weiteren Warnhinweis'],
    unknown: ['Ursache nicht ausgegeben', 'Borg meldete einen Warnungsstatus ohne konkrete Detailzeile'],
  };
  return labels[kind] || labels.other;
}

function renderWarningCauses(summary) {
  const box = $('#log-warning-causes');
  if (!summary || !summary.total_count) {
    box.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  const english = currentLanguage() === 'en';
  const total = Number(summary.total_count || 0);
  const unresolved = Boolean(summary.unresolved || Number(summary.unknown_count || 0));
  const intro = unresolved
    ? (english
      ? 'Borg saved the archive with warning status, but did not emit a specific warning detail:'
      : 'Borg hat das Archiv mit Warnungsstatus gespeichert, aber keine konkrete Warnungsdetailzeile ausgegeben:')
    : (english
      ? `Borg saved the archive, but detected ${total} concrete warning ${total === 1 ? 'cause' : 'causes'}:`
      : `Borg hat das Archiv gespeichert, aber ${total} konkrete Warnungsursache${total === 1 ? '' : 'n'} erkannt:`);
  const rows = (summary.items || []).map((item) => {
    const [label, fallback] = warningCauseText(item.kind, item.reason || '');
    const detail = item.kind === 'other' && item.reason ? item.reason : fallback;
    const subject = item.path
      ? `<code data-i18n-skip>${esc(item.path)}</code>`
      : `<span>${esc(detail)}</span>`;
    const detailRow = item.path ? `<small>${esc(detail)}</small>` : '';
    return `<li><span class="badge warning">${esc(label)}</span>${subject}${detailRow}</li>`;
  }).join('');
  const more = Number(summary.truncated_count || 0) > 0
    ? `<p class="warning-cause-more">${english ? `${summary.truncated_count} more warnings are available in the full live log.` : `${summary.truncated_count} weitere Warnungen stehen im vollständigen Live-Log.`}</p>`
    : '';
  box.innerHTML = `<strong>${english ? 'Warning causes' : 'Warnungsursachen'}</strong><p>${esc(intro)}</p><ul class="warning-cause-list">${rows}</ul>${more}`;
  box.classList.remove('hidden');
}

function renderRunDialog(run) {
  $('#log-dialog h2').textContent = `${run.job_name || 'Repository-Verwaltung'} · ${run.action}`;
  const readable = (run.log_output || `${run.output || ''}\n${run.error || ''}`).trim();
  $('#log-content').textContent = readable || 'Noch keine Ausgabe vorhanden …';
  $('#log-command').textContent = run.command_preview || 'Kein Befehl gespeichert.';
  $('#log-stdout').textContent = run.output || 'Keine Standardausgabe.';
  $('#log-stderr').textContent = run.error || 'Keine Fehler oder Warnungen erkannt.';
  const active = ['queued', 'running'].includes(run.status);
  $('#log-live-state').textContent = active ? `Live · ${run.status}` : `${run.status}${run.duration_seconds != null ? ' · ' + run.duration_seconds + ' s' : ''}`;
  const trigger = run.trigger_type === 'schedule' ? `Zeitplan: ${esc(run.schedule_name || 'unbekannt')}` : 'Manuell';
  const backupSize = [run.backup_original_size_bytes, run.backup_compressed_size_bytes, run.backup_deduplicated_size_bytes].some((value) => value != null)
    ? `Dedupliziert ${formatBytes(run.backup_deduplicated_size_bytes)} · Original ${formatBytes(run.backup_original_size_bytes)} · Komprimiert ${formatBytes(run.backup_compressed_size_bytes)}`
    : '–';
  $('#log-summary').innerHTML = `<div><span>Status</span><strong class="status-text ${esc(run.status)}">${esc(runStatusLabel(run.status))}</strong></div><div><span>Gestartet</span><strong>${run.started_at ? esc(formatDate(run.started_at)) : 'wartet'}</strong></div><div><span>Dauer</span><strong>${esc(formatDuration(run.duration_seconds))}</strong></div><div><span>Lauf</span><strong>#${run.id}</strong></div><div><span>Ausführung</span><strong>${trigger}</strong></div><div><span>Backup-Größe</span><strong>${backupSize}</strong></div><div><span>Dateien</span><strong>${run.backup_file_count == null ? '–' : Number(run.backup_file_count).toLocaleString(currentLocale())}</strong></div>`;
  renderWarningCauses(run.warning_summary);
  const box = $('#log-diagnosis');
  box.classList.toggle('hidden', !run.diagnosis);
  box.innerHTML = run.diagnosis ? `<strong>${esc(run.diagnosis.title)}</strong><p>${esc(run.diagnosis.detail)}</p><p><b>Empfehlung:</b> ${esc(run.diagnosis.action)}</p>` : '';
  const version = $('#log-version-warning');
  const compatibility = run.borg_compatibility;
  version.className = `diagnosis-box ${compatibility && compatibility.level !== 'ok' ? compatibility.level : 'hidden'}`;
  version.innerHTML = compatibility && compatibility.level !== 'ok' ? `<strong>${esc(compatibility.title)} · Borg ${esc(compatibility.version || '?')}</strong><p>${esc(compatibility.message)}</p>` : '';
  if (active && $('#log-view-output').classList.contains('active')) $('#log-content').scrollTop = $('#log-content').scrollHeight;
  return active;
}

function showTextDialog(title, text) {
  clearTimeout(state.liveTimer);
  state.liveRunId = null;
  $('#log-dialog h2').textContent = title;
  $('#log-live-state').textContent = '';
  $('#log-diagnosis').classList.add('hidden');
  $('#log-warning-causes').classList.add('hidden');
  $('#log-warning-causes').innerHTML = '';
  $('#log-version-warning').classList.add('hidden');
  $('#log-summary').innerHTML = '';
  $('#log-content').textContent = text;
  $('#log-command').textContent = ''; $('#log-stdout').textContent = ''; $('#log-stderr').textContent = '';
  setLogTab('output');
  $('#log-dialog').showModal();
}


async function showRun(id) {
  state.liveRunId = Number(id);
  try {
    const run = await api('/runs/' + id);
    renderRunDialog(run);
    $('#log-dialog').showModal();
    if (activeRunStatus(run.status)) watchRunCompletion(id, {areas: ['dashboard', 'runs']});
  } catch (error) { toast(error.message, true); }
}

async function cancelExecution(id) {
  const release = markButtonBusy(actionButton(), 'Abbruch läuft …');
  try {
    await api(`/runs/${id}/cancel`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs'], `Abbruch für #${id} wurde angefordert …`);
    watchRunCompletion(id, {areas: ['dashboard', 'runs', 'repositories', 'jobs']});
    toast('Abbruch angefordert');
  } catch (error) {
    setSyncState('Abbruchanforderung fehlgeschlagen', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function retryExecution(id) {
  const release = markButtonBusy(actionButton(), 'Wird gestartet …');
  try {
    const result = await api(`/runs/${id}/retry`, {method: 'POST'});
    await refreshAreas(['dashboard', 'runs'], `Wiederholung #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories', 'jobs'], refreshArchives: true});
    toast(`Wiederholung #${result.run_id} gestartet`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState('Wiederholung konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function deleteExecution(id) {
  if (!confirm(`Ausführungsprotokoll #${id} wirklich löschen?`)) return;
  try { await api(`/runs/${id}`, {method: 'DELETE'}); toast(`Protokoll #${id} gelöscht`); await refreshAreas(['dashboard', 'runs', 'runStorage']); }
  catch (error) { toast(error.message, true); }
}

async function cleanupRunHistory(mode) {
  const all = mode === 'all_finished';
  if (all && !confirm('Alle abgeschlossenen Ausführungsprotokolle und zugehörigen Logdateien wirklich löschen? Laufende Jobs bleiben erhalten.')) return;
  try {
    const result = await api('/runs/cleanup', {method: 'POST', body: JSON.stringify({mode, vacuum: true})});
    toast(`${result.removed} Protokoll(e) gelöscht`);
    await refreshAreas(['dashboard', 'runs', 'runStorage']);
  } catch (error) { toast(error.message, true); }
}

function clearPendingHostKey(message = 'Der Hostschlüssel muss vor dem Speichern bestätigt werden.') {
  const form = $('#host-form');
  form.dataset.pendingHostKey = '';
  form.dataset.pendingFingerprint = '';
  $('#host-fingerprint').textContent = message;
  $('#host-fingerprint-box').classList.remove('pending', 'confirmed', 'error');
  $('#host-fingerprint-actions').classList.add('hidden');
}

function showPendingHostKey(hostKey, fingerprint) {
  const form = $('#host-form');
  form.dataset.pendingHostKey = hostKey;
  form.dataset.pendingFingerprint = fingerprint;
  $('#host-fingerprint').innerHTML = `<b>Gefunden: ${esc(fingerprint)}</b><span>Mit der Ausgabe des Clients vergleichen und anschließend bestätigen.</span>`;
  $('#host-fingerprint-box').classList.remove('confirmed', 'error');
  $('#host-fingerprint-box').classList.add('pending');
  $('#host-fingerprint-actions').classList.remove('hidden');
}

function acceptPendingHostKey() {
  const form = $('#host-form');
  const hostKey = form.dataset.pendingHostKey || '';
  const fingerprint = form.dataset.pendingFingerprint || '';
  if (!hostKey || !fingerprint) return;
  form.elements.host_key.value = hostKey;
  form.dataset.pendingHostKey = '';
  form.dataset.pendingFingerprint = '';
  $('#host-fingerprint').innerHTML = `<b>Bestätigt: ${esc(fingerprint)}</b><span>Der geprüfte Ed25519-Hostschlüssel wird beim Speichern übernommen.</span>`;
  $('#host-fingerprint-box').classList.remove('pending', 'error');
  $('#host-fingerprint-box').classList.add('confirmed');
  $('#host-fingerprint-actions').classList.add('hidden');
  toast('SSH-Fingerprint bestätigt');
}

function resetHostForm() {
  const form = $('#host-form'); form.reset(); form.elements.id.value = ''; form.elements.port.value = '22'; form.elements.enabled.checked = true; form.elements.host_key.value = '';
  $('#host-form-title').textContent = 'Gerät hinzufügen'; $('#host-submit').textContent = 'Gerät speichern'; $('#cancel-host-edit').classList.add('hidden');
  clearPendingHostKey();
}

function editHost(id) {
  const host = state.hosts.find((item) => item.id === id); if (!host) return;
  goToView('hosts');
  const form = $('#host-form');
  for (const name of ['id', 'name', 'address', 'username', 'port', 'host_key']) form.elements[name].value = host[name] ?? '';
  form.elements.enabled.checked = host.enabled;
  $('#host-form-title').textContent = 'Gerät bearbeiten'; $('#host-submit').textContent = 'Änderungen speichern'; $('#cancel-host-edit').classList.remove('hidden');
  clearPendingHostKey(host.host_key ? 'Gespeicherter Hostschlüssel wird beibehalten.' : 'SSH-Fingerprint muss geprüft werden.');
  $('#host-fingerprint-box').classList.toggle('confirmed', Boolean(host.host_key));
  form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function resetRepositoryForm() {
  const form = $('#repo-form'); form.reset(); form.elements.id.value = ''; form.elements.import_directory.value = '';
  form.elements.managed.disabled = false; form.elements.encryption_mode.disabled = false; form.elements.generate_external_ssh_key.checked = true; form.elements.scan_external_host_key.checked = true; form.elements.external_ssh_private_key.value = ''; form.elements.external_known_hosts.value = '';
  form.elements.storage_guard_mode.value = 'inherit'; form.elements.storage_guard_threshold_percent.value = '';
  $('#repo-form-title').textContent = 'Repository hinzufügen'; $('#cancel-repo-edit').classList.add('hidden');
  $('#repo-manager-key-info').classList.add('hidden'); $('#repo-manager-key-info').innerHTML = '';
  clearRepositoryStatus();
  toggleRepositoryMode();
}

function editRepository(id) {
  const repo = state.repos.find((item) => item.id === id); if (!repo) return;
  goToView('repositories');
  const form = $('#repo-form');
  form.elements.id.value = repo.id; form.elements.import_directory.value = ''; form.elements.name.value = repo.name;
  form.elements.managed.value = String(repo.managed); form.elements.location.value = repo.managed ? '' : repo.location;
  form.elements.encryption_mode.value = repo.encryption_mode; form.elements.passphrase.value = ''; form.elements.keyfile.value = ''; form.elements.external_ssh_private_key.value = ''; form.elements.external_known_hosts.value = '';
  form.elements.generate_external_ssh_key.checked = false; form.elements.scan_external_host_key.checked = false;
  form.elements.storage_guard_mode.value = repo.storage_guard_enabled == null ? 'inherit' : (repo.storage_guard_enabled ? 'enabled' : 'disabled');
  form.elements.storage_guard_threshold_percent.value = repo.storage_guard_threshold_percent ?? '';
  form.elements.managed.disabled = true; form.elements.encryption_mode.disabled = repo.repository_present;
  const keyInfo = $('#repo-manager-key-info');
  if (!repo.managed && repo.external_ssh_public_key) {
    keyInfo.classList.remove('hidden');
    keyInfo.innerHTML = `<b>Öffentlicher Manager-Schlüssel</b><code>${esc(repo.external_ssh_public_key)}</code><small>SSH-Hostkey: ${esc(repo.external_host_fingerprint || 'gespeichert')}</small><small>Privater Schlüssel: verschlüsselt in /data/security/security.db · Schutzschlüssel: /data/security/master.key</small><button type="button" class="secondary" ${bbmAction('copyRepositoryPublicKey', repo.id)}>Public Key kopieren</button>`;
  } else { keyInfo.classList.add('hidden'); keyInfo.innerHTML = ''; }
  $('#repo-form-title').textContent = 'Repository bearbeiten'; $('#repo-submit').textContent = 'Änderungen speichern'; $('#cancel-repo-edit').classList.remove('hidden');
  toggleRepositoryMode(); form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function prepareRepositoryImport(directoryName, suggestedName) {
  resetRepositoryForm();
  goToView('repositories');
  const form = $('#repo-form');
  form.elements.import_directory.value = directoryName;
  form.elements.name.value = suggestedName || directoryName;
  form.elements.managed.value = 'true'; form.elements.managed.disabled = true;
  $('#repo-form-title').textContent = 'Vorhandenes Repository einbinden'; $('#repo-submit').textContent = 'Repository prüfen und einbinden'; $('#cancel-repo-edit').classList.remove('hidden');
  toggleRepositoryMode(); form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function discoverRepositories() {
  const box = $('#repository-discovery-list');
  box.innerHTML = '<div class="empty">Repository-Verzeichnis wird durchsucht …</div>';
  try {
    const candidates = await api('/repositories/discover');
    box.innerHTML = candidates.length ? candidates.map((item) => `<div class="entity"><div><h3>${esc(item.directory_name)}</h3><p>${esc(item.path)}</p><p>${item.repository_id ? 'Repository-ID: ' + esc(item.repository_id) : 'Borg-Konfiguration erkannt'}</p></div><div class="actions"><button data-import-directory="${esc(item.directory_name)}" data-import-name="${esc(item.suggested_name)}">Einbinden</button></div></div>`).join('') : '<div class="empty">Keine noch nicht registrierten Borg-Repositories gefunden.</div>';
    $$('[data-import-directory]').forEach((button) => button.onclick = () => prepareRepositoryImport(button.dataset.importDirectory, button.dataset.importName));
  } catch (error) { box.innerHTML = `<div class="empty error">${esc(error.message)}</div>`; }
}

function toggleRepositoryMode() {
  const form = $('#repo-form');
  const managed = form.elements.managed.value === 'true';
  const mode = form.elements.encryption_mode.value;
  const unencrypted = mode === 'none';
  const editing = Boolean(form.elements.id.value);
  const importing = Boolean(form.elements.import_directory.value);
  $('#repo-external-fields').classList.toggle('hidden', managed);
  $('#repo-storage-guard-fields').classList.toggle('hidden', !managed);
  $('#repo-storage-guard-help').classList.toggle('hidden', !managed);
  form.elements.storage_guard_mode.disabled = !managed;
  form.elements.storage_guard_threshold_percent.disabled = !managed;
  $('#repo-passphrase-field').classList.toggle('hidden', unencrypted);
  const existingRepository = state.repos.find((item) => String(item.id) === String(form.elements.id.value));
  const needsKeyfile = mode.startsWith('keyfile') && (importing || !managed) && !(editing && existingRepository?.has_keyfile);
  $('#repo-keyfile-field').classList.toggle('hidden', !mode.startsWith('keyfile') || (editing && existingRepository?.has_keyfile));
  form.elements.location.required = !managed;
  form.elements.external_ssh_private_key.disabled = managed || form.elements.generate_external_ssh_key.checked;
  form.elements.external_known_hosts.disabled = managed || form.elements.scan_external_host_key.checked;
  form.elements.passphrase.required = importing ? !unencrypted : managed && !unencrypted && !editing;
  form.elements.keyfile.required = needsKeyfile;
  form.elements.passphrase.disabled = unencrypted;
  if (unencrypted) form.elements.passphrase.value = '';
  if (importing) {
    $('#repo-form-title').textContent = 'Vorhandenes lokales Repository einbinden';
    $('#repo-submit').textContent = 'Repository prüfen und einbinden';
  } else if (editing) {
    $('#repo-form-title').textContent = 'Repository bearbeiten';
    $('#repo-submit').textContent = 'Änderungen speichern';
  } else if (managed) {
    $('#repo-form-title').textContent = 'Verwaltetes Repository erstellen';
    $('#repo-submit').textContent = 'Repository erstellen';
  } else {
    $('#repo-form-title').textContent = 'Vorhandenes externes Repository hinzufügen';
    $('#repo-submit').textContent = 'Repository hinzufügen';
  }
  const help = {
    none: 'Keine Verschlüsselung und keine Authentifizierung. Nur verwenden, wenn dies ausdrücklich gewünscht ist.',
    authenticated: 'Daten bleiben lesbar, Manipulationen werden mit SHA-256 erkannt.',
    'authenticated-blake2': 'Daten bleiben lesbar, Manipulationen werden mit BLAKE2b erkannt.',
    repokey: 'Verschlüsselter Schlüssel liegt im Repository; kompatibel mit älteren Borg-Versionen.',
    'repokey-blake2': 'Verschlüsselter Schlüssel liegt im Repository; BLAKE2b ist auf vielen Systemen schneller.',
    keyfile: 'Separater Schlüssel. Beim Import muss der vorhandene Borg-Keyfile-Inhalt angegeben werden.',
    'keyfile-blake2': 'Separater BLAKE2b-Schlüssel. Beim Import muss der vorhandene Borg-Keyfile-Inhalt angegeben werden.',
  };
  $('#encryption-help').textContent = (importing ? 'Bestehendes Repository: ' : '') + (help[mode] || '');
}

function resetJobForm() {
  const form = $('#job-form'); form.reset(); form.elements.id.value = ''; form.elements.enabled.checked = true;
  form.elements.one_file_system.checked = true; form.elements.exclude_caches.checked = true; form.elements.exclude_nodump.checked = true; form.elements.numeric_ids.checked = false; form.elements.list_files.checked = true;
  form.elements.files_cache.value = 'ctime,size,inode'; form.elements.checkpoint_interval.value = 1800;
  $('#archive-prefix-hint').textContent = 'Automatisches Präfix wird nach dem Speichern erzeugt.';
  $('#job-form-title').textContent = 'Backup-Job erstellen'; $('#job-submit').textContent = 'Job speichern'; $('#cancel-job-edit').classList.add('hidden');
  toggleCompressionMode();
}

function editJob(id) {
  const job = state.jobs.find((item) => item.id === id); if (!job) return;
  goToView('jobs');
  const form = $('#job-form'); const options = job.create_options || {};
  form.elements.id.value = job.id; form.elements.name.value = job.name; form.elements.host_id.value = job.host_id; form.elements.repository_id.value = job.repository_id;
  form.elements.source_paths.value = job.source_paths.join('\n'); form.elements.exclude_patterns.value = job.exclude_patterns.join('\n');
  form.elements.archive_template.value = job.archive_template;
  const preset = [...form.elements.compression.options].some((option) => option.value === job.compression);
  form.elements.compression.value = preset ? job.compression : 'custom'; form.elements.compression_custom.value = preset ? '' : job.compression;
  for (const key of ['last', 'hourly', 'daily', 'weekly', 'monthly', 'yearly']) form.elements[key].value = job.prune_options[key] ?? 0;
  for (const key of ['one_file_system', 'exclude_caches', 'exclude_nodump', 'numeric_ids']) form.elements[key].checked = Boolean(options[key]);
  form.elements.list_files.checked = options.list_files !== false;
  form.elements.files_cache.value = options.files_cache || 'ctime,size,inode'; form.elements.checkpoint_interval.value = options.checkpoint_interval || 1800; form.elements.enabled.checked = job.enabled;
  $('#archive-prefix-hint').textContent = 'Effektiver Archivname: ' + job.archive_prefix + job.archive_template;
  $('#job-form-title').textContent = 'Backup-Job bearbeiten'; $('#job-submit').textContent = 'Änderungen speichern'; $('#cancel-job-edit').classList.remove('hidden');
  toggleCompressionMode(); form.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function bindForm(selector, handler, impacts) {
  $(selector).addEventListener('submit', async (event) => {
    event.preventDefault();
    const release = markButtonBusy(event.submitter, 'Wird gespeichert …');
    setSyncState('Änderungen werden gespeichert …', 'pending', true);
    try {
      await handler(new FormData(event.target));
      if (selector === '#host-form') resetHostForm();
      else if (selector === '#job-form') resetJobForm();
      else if (selector === '#repo-form') resetRepositoryForm();
      else event.target.reset();
      await refreshAreas(impacts, 'Gespeicherte Änderungen werden angezeigt …');
      toast('Gespeichert');
    } catch (error) { setSyncState('Speichern fehlgeschlagen', 'error'); toast(error.message, true); }
    finally { release(); }
  });
}

bindForm('#host-form', (form) => {
  if (!form.get('host_key')) throw new Error('SSH-Fingerprint zuerst prüfen');
  const id = form.get('id');
  return api(id ? `/hosts/${id}` : '/hosts', {method: id ? 'PUT' : 'POST', body: JSON.stringify({name: form.get('name'), address: form.get('address'), username: form.get('username'), port: +form.get('port'), enabled: form.get('enabled') === 'on', host_key: form.get('host_key')})});
}, ['dashboard', 'hosts', 'jobs']);

bindForm('#repo-form', (form) => {
  const id = form.get('id');
  const importDirectory = form.get('import_directory');
  const existing = state.repos.find((item) => String(item.id) === String(id));
  const managed = existing ? existing.managed : form.get('managed') === 'true';
  const encryption = existing && $('#repo-form').elements.encryption_mode.disabled ? existing.encryption_mode : form.get('encryption_mode');
  const guardMode = managed ? form.get('storage_guard_mode') : 'inherit';
  const guardEnabled = guardMode === 'inherit' ? null : guardMode === 'enabled';
  const guardThreshold = managed && form.get('storage_guard_threshold_percent') ? +form.get('storage_guard_threshold_percent') : null;
  if (importDirectory) return api('/repositories/import', {method: 'POST', body: JSON.stringify({name: form.get('name'), directory_name: importDirectory, encryption_mode: encryption, passphrase: form.get('passphrase') || null, keyfile: form.get('keyfile') || null, storage_guard_enabled: guardEnabled, storage_guard_threshold_percent: guardThreshold})});
  return api(id ? `/repositories/${id}` : '/repositories', {method: id ? 'PUT' : 'POST', body: JSON.stringify({name: form.get('name'), managed, location: managed ? null : form.get('location'), external_ssh_private_key: managed ? null : (form.get('external_ssh_private_key') || null), external_known_hosts: managed ? null : (form.get('external_known_hosts') || null), generate_external_ssh_key: managed ? false : form.get('generate_external_ssh_key') === 'on', scan_external_host_key: managed ? false : form.get('scan_external_host_key') === 'on', encryption_mode: encryption, passphrase: form.get('passphrase') || null, keyfile: form.get('keyfile') || null, passphrase_env: null, extra_env: {}, storage_guard_enabled: managed ? guardEnabled : null, storage_guard_threshold_percent: managed ? guardThreshold : null})});
}, ['dashboard', 'repositories', 'jobs']);

bindForm('#job-form', (form) => {
  const compression = form.get('compression') === 'custom' ? form.get('compression_custom').trim() : form.get('compression');
  if (!compression) throw new Error('Kompressionsspezifikation fehlt');
  const id = form.get('id');
  const createOptions = {one_file_system: form.get('one_file_system') === 'on', exclude_caches: form.get('exclude_caches') === 'on', exclude_nodump: form.get('exclude_nodump') === 'on', numeric_ids: form.get('numeric_ids') === 'on', list_files: form.get('list_files') === 'on', files_cache: form.get('files_cache'), checkpoint_interval: +form.get('checkpoint_interval')};
  return api(id ? `/jobs/${id}` : '/jobs', {method: id ? 'PUT' : 'POST', body: JSON.stringify({name: form.get('name'), host_id: +form.get('host_id'), repository_id: +form.get('repository_id'), source_paths: lines(form.get('source_paths')), exclude_patterns: lines(form.get('exclude_patterns')), archive_template: form.get('archive_template'), compression, prune_options: Object.fromEntries(['last', 'hourly', 'daily', 'weekly', 'monthly', 'yearly'].map((key) => [key, +form.get(key)]).filter(([, value]) => value > 0)), create_options: createOptions, enabled: form.get('enabled') === 'on'})});
}, ['dashboard', 'jobs', 'hosts', 'repositories', 'schedules']);


$('#schedule-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, 'Wird gespeichert …');
  setSyncState('Zeitplan wird gespeichert …', 'pending', true);
  const form = event.target;
  try {
    const expressions = buildScheduleExpressions();
    if (!expressions.length) throw new Error('Mindestens eine Ausführungszeit festlegen');
    const mode = form.elements.target_mode.value;
    const payload = {
      name: form.elements.name.value.trim(),
      expressions: expressions.join(';'),
      target_mode: mode,
      target_host_ids: mode === 'hosts' ? selectedNumberValues(form.elements.target_host_ids) : [],
      target_repository_id: mode === 'repository' ? Number(form.elements.target_repository_id.value) || null : null,
      target_job_ids: mode === 'jobs' ? selectedNumberValues(form.elements.target_job_ids) : [],
      parallel_limit: Number(form.elements.parallel_limit.value) || 0,
      enabled: form.elements.enabled.checked,
    };
    const id = form.elements.id.value;
    await api(id ? `/schedules/${id}` : '/schedules', {method: id ? 'PUT' : 'POST', body: JSON.stringify(payload)});
    toast(id ? 'Zeitplan aktualisiert' : 'Zeitplan erstellt');
    resetScheduleForm();
    await refreshAreas(['dashboard', 'schedules', 'jobs']);
  } catch (error) { setSyncState('Zeitplan konnte nicht gespeichert werden', 'error'); toast(error.message, true); }
  finally { release(); }
};

$('#user-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, 'Wird gespeichert …');
  setSyncState('Benutzer wird gespeichert …', 'pending', true);
  const form = new FormData(event.target); const id = form.get('id');
  try {
    if (id) {
      const existing = state.users.find((item) => item.id === +id);
      await api(`/users/${id}`, {method: 'PUT', body: JSON.stringify({
        username: form.get('username'),
        role: form.get('role') || existing?.role || 'user',
        enabled: event.target.elements.enabled.disabled ? Boolean(existing?.enabled) : form.get('enabled') === 'on',
      })});
    } else {
      await api('/users', {method: 'POST', body: JSON.stringify({username: form.get('username'), role: form.get('role'), password: form.get('password'), password_confirm: form.get('password_confirm'), must_change_password: form.get('must_change_password') === 'on'})});
    }
    toast(id ? 'Benutzer aktualisiert' : 'Benutzer angelegt'); resetUserForm(); await refreshAreas(['users', 'security']);
  } catch (error) { setSyncState('Benutzer konnte nicht gespeichert werden', 'error'); toast(error.message, true); }
  finally { release(); }
};
$('#cancel-user-edit').onclick = resetUserForm;


function toggleCompressionMode() {
  const custom = $('#job-form').elements.compression.value === 'custom';
  $('#compression-custom-field').classList.toggle('hidden', !custom);
  $('#job-form').elements.compression_custom.required = custom;
}


function renderLegacyMounts() {
  const panel = $('#legacy-mount-panel');
  const mounts = state.mounts || [];
  panel.classList.toggle('hidden', mounts.length === 0);
  if (!mounts.length) {
    $('#legacy-mount-error').classList.add('hidden');
    $('#legacy-mount-error').textContent = '';
    $('#legacy-mount-list').innerHTML = '';
    return;
  }
  $('#legacy-mount-list').innerHTML = mounts.map((mount) => `<div class="entity"><div><h3>${esc(mount.archive)}</h3><p>${esc(mount.job_name || `Job ${mount.job_id}`)} · ${esc(mount.mount_path)}</p></div><div class="actions"><button class="danger" data-legacy-unmount="${mount.id}">Aushängen und entfernen</button></div></div>`).join('');
  $$('[data-legacy-unmount]').forEach((button) => button.onclick = () => unmountLegacyArchive(+button.dataset.legacyUnmount));
}

async function unmountLegacyArchive(mountId) {
  $('#legacy-mount-error').classList.add('hidden');
  $('#legacy-mount-error').textContent = '';
  try {
    await api(`/mounts/${mountId}`, {method: 'DELETE'});
    toast('Alter Archiv-Mount wurde ausgehängt');
    await refreshAreas(['mounts']);
  } catch (error) {
    $('#legacy-mount-error').textContent = error.message;
    $('#legacy-mount-error').classList.remove('hidden');
  }
}

function markArchivesStale() {
  const repositoryId = +$('#archive-repository').value;
  const considerCheckpoints = $('#archive-consider-checkpoints').checked;
  if (repositoryId) localStorage.setItem('bbm-archive-repository', String(repositoryId));
  localStorage.setItem('bbm-archive-checkpoints', considerCheckpoints ? '1' : '0');
  state.archiveData = null;
  state.archiveSelection = new Set();
  state.activeBrowser = null;
  state.browserSelection = new Set();
  $('#archive-browser-panel').classList.add('hidden');
  $('#archive-error').classList.add('hidden');
  $('#archive-error').textContent = '';
  $('#archive-summary').textContent = 'Auswahl geändert – gespeicherte Archivliste anzeigen oder Repository neu einlesen.';
  $('#archive-list').innerHTML = '<div class="empty">„Archive anzeigen“ verwendet den persistenten Zwischenspeicher; „Neu aus Repository einlesen“ erzwingt einen Borg-Scan.</div>';
  $('#archive-diff-first').innerHTML = '<option value="">Archive anzeigen</option>';
  $('#archive-diff-second').innerHTML = '<option value="">Archive anzeigen</option>';
  $('#archive-device-filter').innerHTML = '<option value="">Alle Geräte / alle Archive</option>';
  $('#archive-device-filter').disabled = true;
  $('#compare-archives').disabled = true;
  updateArchiveSelectionControls([]);
}

async function loadArchives(options = {}) {
  const repositoryId = +$('#archive-repository').value;
  if (!repositoryId) return;
  const considerCheckpoints = $('#archive-consider-checkpoints').checked;
  localStorage.setItem('bbm-archive-repository', String(repositoryId));
  localStorage.setItem('bbm-archive-checkpoints', considerCheckpoints ? '1' : '0');
  const requestId = ++state.archiveRequestId;
  const button = options.force === true ? $('#refresh-archives') : $('#load-archives');
  const otherButton = options.force === true ? $('#load-archives') : $('#refresh-archives');
  const silent = options.silent === true;
  button.disabled = true;
  otherButton.disabled = true;
  button.textContent = options.force === true ? 'Repository wird eingelesen …' : (silent ? 'Wird aktualisiert …' : 'Archive werden angezeigt …');
  $('#archive-error').classList.add('hidden');
  $('#archive-error').textContent = '';
  if (!state.archiveData) $('#archive-list').innerHTML = '<div class="empty">Archive werden geladen …</div>';
  else $('#archive-summary').textContent = 'Archivliste wird manuell aktualisiert …';
  try {
    const forceRefresh = options.force === true;
    const result = await api(`/repositories/${repositoryId}/archives?consider_checkpoints=${considerCheckpoints}&force_refresh=${forceRefresh}`);
    if (requestId !== state.archiveRequestId) return;
    state.archiveData = result;
    renderArchives();
  } catch (error) {
    if (requestId !== state.archiveRequestId) return;
    $('#archive-error').textContent = error.message;
    $('#archive-error').classList.remove('hidden');
    $('#archive-summary').textContent = state.archiveData ? 'Aktualisierung fehlgeschlagen – vorherige Liste bleibt sichtbar.' : 'Archivliste konnte nicht geladen werden.';
    if (!state.archiveData) $('#archive-list').innerHTML = '<div class="empty error">Archivliste nicht verfügbar. Die Fehlermeldung steht oberhalb der Liste.</div>';
  } finally {
    if (requestId === state.archiveRequestId) {
      button.disabled = false;
      otherButton.disabled = false;
      button.textContent = options.force === true ? 'Neu aus Repository einlesen' : 'Archive anzeigen';
    }
  }
}

function archiveSelectionDeviceLabel(items) {
  const devices = new Set(items.map((archive) => archiveDevice(archive)).filter(Boolean));
  const hasUnknown = items.some((archive) => !archiveDevice(archive));
  if (devices.size === 1 && !hasUnknown) return `${currentLanguage() === 'en' ? 'Device' : 'Gerät'}: ${[...devices][0]}`;
  if (devices.size > 1 || (devices.size && hasUnknown)) return currentLanguage() === 'en' ? 'Multiple devices' : 'Mehrere Geräte';
  return currentLanguage() === 'en' ? 'Device not uniquely identified' : 'Gerät nicht eindeutig';
}

function selectedArchiveItems(names = state.archiveSelection) {
  const selected = names instanceof Set ? names : new Set(names || []);
  return (state.archiveData?.archives || []).filter((archive) => selected.has(archive.name));
}

function updateArchiveSelectionControls(visibleArchives = []) {
  const admin = state.currentUser?.role === 'admin';
  const selectAll = $('#archive-select-visible');
  const deleteButton = $('#delete-selected-archives');
  const summary = $('#archive-selection-summary');
  const toolbar = $('#archive-selection-toolbar');
  if (!selectAll || !deleteButton || !summary || !toolbar) return;
  toolbar.classList.toggle('hidden', !admin);
  const existing = new Set((state.archiveData?.archives || []).map((archive) => archive.name));
  state.archiveSelection = new Set([...state.archiveSelection].filter((name) => existing.has(name)));
  const visibleNames = visibleArchives.map((archive) => archive.name);
  const selectedVisible = visibleNames.filter((name) => state.archiveSelection.has(name)).length;
  selectAll.disabled = !visibleNames.length;
  selectAll.checked = Boolean(visibleNames.length && selectedVisible === visibleNames.length);
  selectAll.indeterminate = Boolean(selectedVisible && selectedVisible < visibleNames.length);
  deleteButton.disabled = !state.archiveSelection.size;
  const countText = currentLanguage() === 'en'
    ? `${state.archiveSelection.size} selected`
    : `${state.archiveSelection.size} ausgewählt`;
  summary.textContent = countText;
  const selectedItems = selectedArchiveItems();
  if (selectedItems.length) summary.textContent += ` · ${archiveSelectionDeviceLabel(selectedItems)}`;
}

function renderArchives() {
  const allArchives = sortArchivesNewestFirst(state.archiveData?.archives || []);
  const repository = state.repos.find((item) => item.id === state.archiveData?.repository_id);
  const repositoryJobs = state.jobs.filter((job) => job.repository_id === state.archiveData?.repository_id);
  const mode = 'direkt im Manager-Container';
  const deviceFilter = $('#archive-device-filter');
  const counts = new Map();
  let unassigned = 0;
  allArchives.forEach((archive) => {
    const device = archiveDevice(archive);
    if (device) counts.set(device, (counts.get(device) || 0) + 1);
    else unassigned += 1;
  });
  const storageKey = `bbm-archive-device-${state.archiveData?.repository_id || 0}`;
  const previousFilter = deviceFilter.value || localStorage.getItem(storageKey) || '';
  const deviceOptions = [...counts.entries()]
    .sort((left, right) => left[0].localeCompare(right[0], currentLocale(), {numeric: true, sensitivity: 'base'}))
    .map(([device, count]) => `<option value="${esc(device)}">Gerät: ${esc(device)} (${count})</option>`)
    .join('');
  deviceFilter.innerHTML = `<option value="">Alle Geräte / alle Archive (${allArchives.length})</option>${deviceOptions}${unassigned ? `<option value="__unassigned__">Nicht eindeutig erkannt (${unassigned})</option>` : ''}`;
  deviceFilter.disabled = false;
  deviceFilter.value = [...deviceFilter.options].some((option) => option.value === previousFilter) ? previousFilter : '';
  const selectedDevice = deviceFilter.value;
  localStorage.setItem(storageKey, selectedDevice);
  const archives = allArchives.filter((archive) => {
    const device = archiveDevice(archive);
    return !selectedDevice || (selectedDevice === '__unassigned__' ? !device : device === selectedDevice);
  });
  const checkpoints = archives.filter((archive) => archive.checkpoint).length;
  const checkpointInfo = state.archiveData?.consider_checkpoints ? ` · ${checkpoints} Checkpoint(s) eingeblendet` : '';
  const repoStats = state.archiveData?.repository_statistics || {};
  const sizeSummary = repoStats.original_size != null
    ? ` · Original ${formatBytes(repoStats.original_size)} · komprimiert ${formatBytes(repoStats.compressed_size)} · dedupliziert ${formatBytes(repoStats.deduplicated_size)}`
    : '';
  const cacheSource = state.archiveData?.archive_cache_source === 'cache' ? 'Zwischenspeicher' : 'Repository';
  const cacheTime = state.archiveData?.archive_cache_updated_at ? ` vom ${formatDate(state.archiveData.archive_cache_updated_at)}` : '';
  const filterSummary = selectedDevice ? ` · Filter: ${selectedDevice === '__unassigned__' ? 'nicht eindeutig erkannt' : selectedDevice}` : '';
  const countSummary = archives.length === allArchives.length ? `${archives.length} Archiv(e)` : `${archives.length} von ${allArchives.length} Archiv(en)`;
  $('#archive-summary').textContent = `${countSummary} · neueste zuerst · ${mode}${filterSummary}${checkpointInfo}${sizeSummary} · Quelle: ${cacheSource}${cacheTime}`;
  const first = $('#archive-diff-first');
  const second = $('#archive-diff-second');
  const previousFirst = first.value;
  const previousSecond = second.value;
  const options = archives.map((archive) => `<option value="${esc(archive.name)}">${esc(archive.name)}</option>`).join('');
  first.innerHTML = options || '<option value="">Keine Archive vorhanden</option>';
  second.innerHTML = options || '<option value="">Keine Archive vorhanden</option>';
  if (archives.length >= 2) {
    first.value = archives.some((item) => item.name === previousFirst) ? previousFirst : archives[1].name;
    second.value = archives.some((item) => item.name === previousSecond) ? previousSecond : archives[0].name;
  }
  $('#compare-archives').disabled = archives.length < 2 || !repositoryJobs.length;
  const admin = state.currentUser?.role === 'admin';
  $('#archive-list').innerHTML = archives.length ? archives.map((archive) => {
    const owner = archive.job_name ? `Job: ${archive.job_name}` : 'Legacy-/fremdes Archiv';
    const resolvedDevice = archiveDevice(archive);
    const actionJobId = archive.action_job_id || archive.job_id || (repositoryJobs.length === 1 ? repositoryJobs[0].id : null);
    const requiresLegacyRestore = Boolean(archive.legacy || !archive.job_id);
    const checkpointBadge = archive.checkpoint ? '<span class="badge warning">Checkpoint · unvollständig</span>' : '';
    const restoreActions = actionJobId
      ? `<button class="secondary" data-action-job="${actionJobId}" data-archive-rename="${esc(archive.name)}">Umbenennen</button><button class="secondary" data-action-job="${actionJobId}" data-archive-restore="${esc(archive.name)}" data-archive-legacy="${requiresLegacyRestore ? '1' : '0'}" data-archive-checkpoint="${archive.checkpoint ? '1' : '0'}">Wiederherstellen</button>`
      : '<span class="hint">Für Restore/Umbenennen muss das Gerät eindeutig einem Backup-Job zugeordnet sein.</span>';
    const deleteAction = admin ? `<button class="danger" data-repository-id="${state.archiveData.repository_id}" data-archive-delete="${esc(archive.name)}">Archiv löschen</button>` : '';
    const selection = admin ? `<label class="archive-select-control" title="Archiv auswählen"><input type="checkbox" data-archive-select="${esc(archive.name)}" ${state.archiveSelection.has(archive.name) ? 'checked' : ''}/><span>Auswählen</span></label>` : '';
    const statistics = `<div class="archive-stat-grid">
      <span><small>Dauer</small><b>${formatDuration(archive.duration)}</b></span>
      <span><small>Dateien</small><b>${archive.nfiles == null ? '–' : Number(archive.nfiles).toLocaleString(currentLocale())}</b></span>
      <span><small>Original</small><b>${formatBytes(archive.original_size)}</b></span>
      <span><small>Komprimiert</small><b>${formatBytes(archive.compressed_size)}</b></span>
      <span><small>Dedupliziert</small><b>${formatBytes(archive.deduplicated_size)}</b></span>
    </div>`;
    const deviceInfo = resolvedDevice ? ` · Gerät: ${esc(resolvedDevice)}` : ' · Gerät nicht eindeutig';
    const selectedClass = state.archiveSelection.has(archive.name) ? ' archive-selected' : '';
    return `<div class="entity archive-row${selectedClass}">${selection}<div class="archive-main"><h3>${esc(archive.name)} ${checkpointBadge}</h3><p>${archive.start ? esc(formatDate(archive.start)) : 'Zeit unbekannt'} · ${esc(owner)}${deviceInfo}${archive.hostname ? ' · Borg-Hostname: ' + esc(archive.hostname) : ''}</p>${statistics}<p>${archive.id ? 'ID: ' + esc(archive.id) : ''}${archive.comment ? ' · ' + esc(archive.comment) : ''}</p></div><div class="actions"><button class="secondary" data-repository-id="${state.archiveData.repository_id}" data-archive-info="${esc(archive.name)}">Details</button><button data-repository-id="${state.archiveData.repository_id}" data-action-job="${actionJobId || ''}" data-archive-browse="${esc(archive.name)}">Inhalt durchsuchen</button>${restoreActions}${deleteAction}</div></div>`;
  }).join('') : '<div class="empty">Keine passenden Archive vorhanden.</div>';
  $$('[data-archive-info]').forEach((button) => button.onclick = () => archiveInfo(+button.dataset.repositoryId, button.dataset.archiveInfo));
  $$('[data-archive-rename]').forEach((button) => button.onclick = () => renameArchive(+button.dataset.actionJob, button.dataset.archiveRename));
  $$('[data-archive-browse]').forEach((button) => button.onclick = () => openArchiveBrowser(+button.dataset.repositoryId, button.dataset.archiveBrowse, +(button.dataset.actionJob || 0)));
  $$('[data-archive-restore]').forEach((button) => button.onclick = () => prepareRestore(+button.dataset.actionJob, button.dataset.archiveRestore, button.dataset.archiveLegacy === '1', [], button.dataset.archiveCheckpoint === '1'));
  $$('[data-archive-delete]').forEach((button) => button.onclick = () => deleteArchive(+button.dataset.repositoryId, button.dataset.archiveDelete));
  $$('[data-archive-select]').forEach((input) => input.onchange = () => {
    if (input.checked) state.archiveSelection.add(input.dataset.archiveSelect);
    else state.archiveSelection.delete(input.dataset.archiveSelect);
    input.closest('.archive-row')?.classList.toggle('archive-selected', input.checked);
    updateArchiveSelectionControls(archives);
  });
  updateArchiveSelectionControls(archives);
}

function openRepositoryArchives(repositoryId) {
  goToView('archives');
  $('#archive-repository').value = String(repositoryId);
  $('#archive-consider-checkpoints').checked = false;
  loadArchives();
}

async function archiveInfo(repositoryId, archive) {
  try {
    const cachedItem = state.archiveData?.repository_id === repositoryId
      ? (state.archiveData.archives || []).find((item) => item.name === archive)
      : null;
    const cachedHasDetails = cachedItem && [
      cachedItem.duration, cachedItem.nfiles, cachedItem.original_size,
      cachedItem.compressed_size, cachedItem.deduplicated_size, cachedItem.end,
    ].some((value) => value != null);
    const info = cachedHasDetails ? {archive: cachedItem} : await api(`/repositories/${repositoryId}/archives/${encodeURIComponent(archive)}/info`);
    const item = info.archive || {};
    const lines = [
      `Archiv: ${item.name || archive}`,
      `ID: ${item.id || '–'}`,
      `Start: ${item.start ? formatDate(item.start) : '–'}`,
      `Ende: ${item.end ? formatDate(item.end) : '–'}`,
      `Dauer: ${formatDuration(item.duration)}`,
      `Dateien: ${item.nfiles == null ? '–' : Number(item.nfiles).toLocaleString(currentLocale())}`,
      `Originalgröße: ${formatBytes(item.original_size)}`,
      `Komprimierte Größe: ${formatBytes(item.compressed_size)}`,
      `Deduplizierte Größe dieses Archivs: ${formatBytes(item.deduplicated_size)}`,
      `Hostname: ${item.hostname || '–'}`,
      `Benutzer: ${item.username || '–'}`,
      `Kommentar: ${item.comment || '–'}`,
    ];
    showTextDialog('Archivdetails', lines.join('\n'));
  } catch (error) { toast(error.message, true); }
}

async function renameArchive(jobId, archive) {
  const newName = prompt('Neuer Archivname. Das Job-Präfix muss erhalten bleiben:', archive);
  if (newName == null || newName.trim() === archive) return;
  if (!confirm(`Archiv umbenennen?\n\n${archive}\n→ ${newName.trim()}`)) return;
  const release = markButtonBusy(actionButton(), 'Wird gestartet …');
  try {
    const result = await api(`/jobs/${jobId}/archive-rename`, {method: 'POST', body: JSON.stringify({archive, new_name: newName.trim()})});
    const repositoryId = +$('#archive-repository').value;
    await refreshAreas(['dashboard', 'runs'], `Archivumbenennung #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories'], repositoryId, refreshArchives: true});
    toast(`Archivumbenennung #${result.run_id} gestartet`);
    showRun(result.run_id);
  } catch (error) { setSyncState('Archivumbenennung konnte nicht gestartet werden', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function compareArchives() {
  const repositoryId = +$('#archive-repository').value;
  const accessJob = state.jobs.find((job) => job.repository_id === repositoryId);
  const archive = $('#archive-diff-first').value;
  const secondArchive = $('#archive-diff-second').value;
  if (!accessJob) return toast('Für den Archivvergleich wird derzeit ein Backup-Job dieses Repositorys benötigt', true);
  if (!archive || !secondArchive) return toast('Zwei Archive auswählen', true);
  if (archive === secondArchive) return toast('Für den Vergleich zwei unterschiedliche Archive auswählen', true);
  const release = markButtonBusy(actionButton(), 'Vergleich wird gestartet …');
  try {
    const result = await api(`/jobs/${accessJob.id}/archive-diff`, {method: 'POST', body: JSON.stringify({
      archive,
      second_archive: secondArchive,
      paths: lines($('#archive-diff-paths').value),
      content_only: $('#archive-diff-content-only').checked,
    })});
    await refreshAreas(['dashboard', 'runs'], `Archivvergleich #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs']});
    toast(`Archivvergleich #${result.run_id} gestartet`);
    showRun(result.run_id);
  } catch (error) { setSyncState('Archivvergleich konnte nicht gestartet werden', 'error'); toast(error.message, true); }
  finally { release(); }
}

async function deleteArchives(repositoryId, archives) {
  const uniqueArchives = [...new Set((archives || []).map((name) => String(name || '').trim()).filter(Boolean))];
  if (!uniqueArchives.length) return;
  const english = currentLanguage() === 'en';
  const items = selectedArchiveItems(new Set(uniqueArchives));
  const deviceLabel = archiveSelectionDeviceLabel(items);
  const visibleNames = uniqueArchives.slice(0, 12).map((name) => `• ${name}`).join('\n');
  const more = uniqueArchives.length > 12 ? `\n• ${english ? `and ${uniqueArchives.length - 12} more` : `und ${uniqueArchives.length - 12} weitere`}` : '';
  const warning = english
    ? `Permanently delete ${uniqueArchives.length} archive(s)?\n\nAssignment: ${deviceLabel}\n\n${visibleNames}${more}\n\nThis deletion cannot be undone. All selected archives are handled in one repository operation.`
    : `${uniqueArchives.length} Archiv(e) endgültig löschen?\n\nZuordnung: ${deviceLabel}\n\n${visibleNames}${more}\n\nDiese Löschung kann nicht rückgängig gemacht werden. Alle ausgewählten Archive werden in einer gemeinsamen Repository-Aktion verarbeitet.`;
  if (!confirm(warning)) return;
  const compactAfter = confirm(english
    ? 'Run Compact once after all selected archives have been deleted?\n\nOK: release storage afterwards.\nCancel: delete only; Compact can be started later directly on the repository.'
    : 'Nach dem Löschen aller ausgewählten Archive einmal Compact ausführen?\n\nOK: Speicherplatz anschließend freigeben.\nAbbrechen: Nur löschen; Compact kann später direkt am Repository gestartet werden.');
  const release = markButtonBusy(actionButton(), english ? 'Deletion is starting …' : 'Löschung wird gestartet …');
  try {
    const result = await api(`/repositories/${repositoryId}/archive-delete`, {
      method: 'POST',
      body: JSON.stringify({archives: uniqueArchives, compact_after: compactAfter}),
    });
    uniqueArchives.forEach((name) => state.archiveSelection.delete(name));
    await refreshAreas(['dashboard', 'runs'], `${english ? 'Archive deletion' : 'Archivlöschung'} #${result.run_id} ${english ? 'was accepted' : 'wurde angenommen'} …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs', 'repositories'], repositoryId, refreshArchives: true});
    toast(`${english ? 'Archive deletion' : 'Archivlöschung'} #${result.run_id} ${english ? 'started' : 'gestartet'} · ${result.device_label || deviceLabel}`);
    showRun(result.run_id);
  } catch (error) {
    setSyncState(english ? 'Archive deletion could not be started' : 'Archivlöschung konnte nicht gestartet werden', 'error');
    toast(error.message, true);
  } finally { release(); }
}

async function deleteArchive(repositoryId, archive) {
  return deleteArchives(repositoryId, [archive]);
}

async function deleteSelectedArchives() {
  const repositoryId = Number(state.archiveData?.repository_id || $('#archive-repository').value);
  if (!repositoryId) return;
  return deleteArchives(repositoryId, [...state.archiveSelection]);
}

function openArchiveBrowser(repositoryId, archive, jobId = 0) {
  state.activeBrowser = {repository_id: repositoryId, job_id: jobId || null, archive};
  state.browserPath = '';
  state.browserSelection = new Set();
  $('#archive-browser-panel').classList.remove('hidden');
  $('#archive-browser-error').classList.add('hidden');
  $('#archive-browser-error').textContent = '';
  $('#archive-browser-meta').textContent = `${archive} · ohne FUSE-Mount`;
  $('#export-browser-selection').disabled = !jobId || !state.repos.find((repo) => repo.id === repositoryId)?.managed;
  browseArchive('');
  $('#archive-browser-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function browseArchive(path) {
  if (!state.activeBrowser) return;
  $('#archive-browser-list').innerHTML = '<div class="empty">Archivinhalt wird gelesen …</div>';
  $('#archive-browser-error').classList.add('hidden');
  $('#archive-browser-error').textContent = '';
  try {
    const {repository_id: repositoryId, archive} = state.activeBrowser;
    const result = await api(`/repositories/${repositoryId}/archives/${encodeURIComponent(archive)}/browse?path=${encodeURIComponent(path || '')}`);
    state.browserPath = result.path || '';
    const mode = 'direkt im Manager-Container';
    $('#archive-browser-meta').textContent = `${archive} · ${mode} · kein FUSE erforderlich`;
    $('#browser-path').textContent = '/' + state.browserPath;
    $('#browser-up').disabled = result.parent == null;
    $('#browser-up').dataset.parent = result.parent || '';
    const box = $('#archive-browser-list');
    const typeLabels = {directory: 'Verzeichnis', file: 'Datei', symlink: 'Verknüpfung', other: 'Sonstiges'};
    const iconFor = (entry) => entry.type === 'directory' ? '📁' : entry.type === 'symlink' ? '🔗' : entry.type === 'file' ? '📄' : '◻';
    const ownerFor = (entry) => {
      const user = entry.user || (entry.uid != null ? String(entry.uid) : '–');
      const group = entry.group || (entry.gid != null ? String(entry.gid) : '–');
      return `${user}:${group}`;
    };
    const parts = (result.path || '').split('/').filter(Boolean);
    const breadcrumb = [{label: '/', path: ''}, ...parts.map((label, index) => ({label, path: parts.slice(0, index + 1).join('/')}))];
    $('#browser-path').innerHTML = breadcrumb.map((item, index) => `${index ? '<span class="browser-breadcrumb-separator">›</span>' : ''}<button type="button" data-browse-path="${esc(item.path)}">${esc(item.label)}</button>`).join('');
    const rows = result.entries.map((entry) => {
      const name = entry.type === 'directory'
        ? `<button type="button" class="entity-link" data-browse-path="${esc(entry.path)}"><span class="browser-icon">${iconFor(entry)}</span>${esc(entry.name)}</button>`
        : `<span><span class="browser-icon">${iconFor(entry)}</span>${esc(entry.name)}</span>`;
      const target = entry.target ? `<small class="browser-target" title="${esc(entry.target)}">→ ${esc(entry.target)}</small>` : '';
      return `<tr><td data-label="Auswahl"><input aria-label="${esc(entry.name)} auswählen" type="checkbox" data-select-path="${esc(entry.path)}" ${state.browserSelection.has(entry.path) ? 'checked' : ''}></td><td data-label="Name" class="browser-name-cell">${name}${target}</td><td data-label="Größe">${entry.type === 'directory' ? '–' : formatBytes(entry.size)}</td><td data-label="Typ">${esc(typeLabels[entry.type] || entry.type)}</td><td data-label="Rechte"><code>${esc(entry.mode || '–')}</code></td><td data-label="Besitzer"><code>${esc(ownerFor(entry))}</code></td><td data-label="Geändert">${entry.mtime ? esc(formatDate(entry.mtime)) : '–'}</td></tr>`;
    }).join('');
    box.innerHTML = result.entries.length
      ? `<div class="archive-browser-shell table-scroll"><table class="data-table archive-browser-table"><thead><tr><th></th><th>Name</th><th>Größe</th><th>Typ</th><th>Rechte</th><th>Besitzer</th><th>Geändert</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty">Dieses Verzeichnis ist leer.</div>';
    const meta = $('#archive-browser-meta');
    meta.innerHTML = `${esc(archive)} · ${esc(mode)} · kein FUSE erforderlich <span class="browser-entry-count">· ${result.entries.length} Einträge</span>`;
    $$('[data-browse-path]').forEach((button) => button.onclick = () => browseArchive(button.dataset.browsePath));
    $$('[data-select-path]').forEach((checkbox) => checkbox.onchange = () => {
      if (checkbox.checked) state.browserSelection.add(checkbox.dataset.selectPath);
      else state.browserSelection.delete(checkbox.dataset.selectPath);
      renderBrowserSelection();
    });
    renderBrowserSelection();
  } catch (error) {
    $('#archive-browser-error').textContent = error.message;
    $('#archive-browser-error').classList.remove('hidden');
    $('#archive-browser-list').innerHTML = '<div class="empty error">Archivinhalt konnte nicht gelesen werden. Die Fehlermeldung bleibt oberhalb sichtbar.</div>';
  }
}


function closeArchiveBrowser() {
  state.activeBrowser = null;
  state.browserPath = '';
  state.browserSelection = new Set();
  $('#archive-browser-panel').classList.add('hidden');
}

function renderBrowserSelection() {
  const paths = [...state.browserSelection].sort();
  $('#browser-selection').innerHTML = paths.length ? paths.map((path) => `<code>${esc(path)}</code>`).join(' ') : 'Noch nichts ausgewählt.';
}

async function exportBrowserSelection() {
  if (!state.activeBrowser) return;
  const paths = [...state.browserSelection].sort();
  if (!paths.length) return toast('Zuerst mindestens eine Datei oder einen Ordner auswählen', true);
  const status = $('#archive-export-status');
  const button = $('#export-browser-selection');
  status.textContent = 'Export wird im Manager erstellt. Bei größeren Verzeichnissen kann dies dauern …';
  status.classList.remove('hidden', 'error-state');
  button.disabled = true;
  try {
    const {job_id: jobId, archive} = state.activeBrowser;
    if (!jobId) throw new Error('Für den Export wird ein Backup-Job dieses verwalteten Repositorys benötigt');
    const response = await fetch(`/api/jobs/${jobId}/archive-export`, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-BBM-Request': '1'},
      body: JSON.stringify({archive, paths}),
    });
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch { detail = response.statusText; }
      throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(', ') : detail);
    }
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/"/g, '')) : 'borg-export.tar.gz';
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    status.textContent = `${paths.length} Auswahl(en) wurden als ${filename} exportiert.`;
  } catch (error) {
    status.textContent = 'Export fehlgeschlagen: ' + error.message;
    status.classList.add('error-state');
  } finally { button.disabled = false; }
}

function toggleRestoreDestination() {
  const form = $('#restore-form');
  const mode = form.elements.restore_mode.value;
  const dryRun = form.elements.dry_run.checked;
  const targetMode = mode === 'target';
  $('#restore-target-options').classList.toggle('hidden', !targetMode);
  form.elements.target_directory.required = targetMode;
  $('#restore-overwrite-confirm').classList.toggle('hidden', targetMode || dryRun);
  if (targetMode || dryRun) form.elements.overwrite_existing.checked = false;
  $('#restore-submit').textContent = dryRun ? 'Restore testen' : 'Wiederherstellung starten';
}

function prepareRestore(jobId, archive, legacy = false, paths = [], checkpoint = false) {
  goToView('restore');
  const form = $('#restore-form');
  form.elements.job_id.value = String(jobId);
  form.elements.allow_legacy_archive.checked = Boolean(legacy);
  form.elements.consider_checkpoints.checked = Boolean(checkpoint);
  form.elements.restore_mode.value = 'original';
  form.elements.dry_run.checked = true;
  form.elements.overwrite_existing.checked = false;
  toggleRestoreDestination();
  syncRestoreArchives(true, archive).then(() => {
    form.elements.archive.value = archive;
    if (paths.length) form.elements.paths.value = paths.join('\n');
  });
}

async function syncRestoreArchives(force = false, preferredArchive = '') {
  const form = $('#restore-form');
  const jobId = +form.elements.job_id.value;
  if (!jobId) return;
  const allArchives = form.elements.allow_legacy_archive.checked;
  const considerCheckpoints = form.elements.consider_checkpoints.checked;
  const select = form.elements.archive;
  const previous = preferredArchive || select.value;
  select.innerHTML = '<option value="">Archive werden geladen …</option>';
  try {
    const result = await api(`/jobs/${jobId}/archives?all_archives=${allArchives}&consider_checkpoints=${considerCheckpoints}`);
    select.innerHTML = result.archives.length ? result.archives.map((archive) => `<option value="${esc(archive.name)}">${esc(archive.name)}${archive.checkpoint ? ' · Checkpoint (unvollständig)' : ''}${archive.job_name ? ' · ' + esc(archive.job_name) : ' · Legacy/fremd'}</option>`).join('') : '<option value="">Keine Archive vorhanden</option>';
    if (previous && [...select.options].some((option) => option.value === previous)) select.value = previous;
  } catch (error) {
    select.innerHTML = '<option value="">Archivliste nicht verfügbar</option>';
    if (force) toast(error.message, true);
  }
}

function formatBytes(value) {
  if (value == null) return '–';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']; let number = Number(value); let unit = 0;
  while (number >= 1024 && unit < units.length - 1) { number /= 1024; unit += 1; }
  return `${number.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function formatDuration(value) {
  if (value == null || Number.isNaN(Number(value))) return '–';
  let seconds = Math.max(0, Number(value));
  const hours = Math.floor(seconds / 3600); seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60); seconds -= minutes * 60;
  const parts = [];
  if (hours) parts.push(`${hours} Std.`);
  if (minutes) parts.push(`${minutes} Min.`);
  if (seconds || !parts.length) parts.push(`${seconds < 10 && parts.length ? seconds.toFixed(1) : seconds.toFixed(0)} Sek.`);
  return parts.join(' ');
}

$$('nav button').forEach((button) => button.onclick = () => goToView(button.dataset.view));
$$('[data-system-view]').forEach((button) => button.onclick = () => goToView(button.dataset.systemView));
$('#mobile-nav-toggle').onclick = () => setMobileNavigation(!document.querySelector('aside')?.classList.contains('mobile-open'));
window.addEventListener('resize', () => {
  if (!window.matchMedia('(max-width: 760px)').matches) setMobileNavigation(false);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    setMobileNavigation(false);
  }
});
$$('[data-log-tab]').forEach((button) => button.onclick = () => setLogTab(button.dataset.logTab));
$$('[data-target-view]').forEach((button) => button.onclick = () => goToView(button.dataset.targetView));
$('#apply-exclude-template').onclick = () => {
  const index = Number.parseInt($('#job-exclude-template').value, 10);
  const template = state.settings?.exclude_templates?.[index];
  if (!template) { toast('Bitte zuerst eine Ausschlussvorlage auswählen', true); return; }
  const field = $('#job-form').elements.exclude_patterns;
  const merged = [...lines(field.value)];
  for (const pattern of template.patterns) if (!merged.includes(pattern)) merged.push(pattern);
  field.value = merged.join('\n');
  toast(`Vorlage „${template.name}“ hinzugefügt`);
};
$('#add-exclude-template').onclick = () => {
  const empty = $('#exclude-template-editor .template-empty');
  if (empty) empty.remove();
  appendExcludeTemplateEditor();
  const cards = $$('.exclude-template-card');
  cards[cards.length - 1]?.querySelector('[data-template-name]')?.focus();
};
$('#job-search').oninput = (event) => { state.jobSearch = event.target.value; renderJobs(); };
$('#job-status-filter').onchange = (event) => { state.jobStatus = event.target.value; renderJobs(); };
$('#runs-filter').onchange = (event) => goToRuns(event.target.value);
$('#runs-search').oninput = (event) => { state.runSearch = event.target.value; renderRuns(); };
$('#sync-state').onclick = openCurrentActiveRun;
$('#refresh').onclick = async (event) => { const release = markButtonBusy(event.currentTarget, 'Aktualisiere …'); try { await loadAll(false); } finally { release(); } };
$('#close-dialog').onclick = () => { state.liveRunId = null; $('#log-dialog').close(); };
$('#scan-host-key').onclick = async (event) => {
  const form = $('#host-form'); const address = form.elements.address.value.trim(); const port = +form.elements.port.value;
  if (!address) return toast('Adresse zuerst eingeben', true);
  const release = markButtonBusy(event.currentTarget, 'Fingerprint wird gelesen …');
  form.elements.host_key.value = '';
  clearPendingHostKey('SSH-Fingerprint wird vom Gerät abgerufen …');
  $('#host-fingerprint-box').classList.add('pending');
  try {
    const result = await api('/hosts/scan-key', {method: 'POST', body: JSON.stringify({address, port})});
    showPendingHostKey(result.host_key, result.fingerprint);
  } catch (error) {
    clearPendingHostKey(`Prüfung fehlgeschlagen: ${error.message}`);
    $('#host-fingerprint-box').classList.add('error');
    toast(error.message, true);
  } finally { release(); }
};
$('#accept-host-key').onclick = acceptPendingHostKey;
$('#discard-host-key').onclick = () => { $('#host-form').elements.host_key.value = ''; clearPendingHostKey(); };
['address', 'port'].forEach((name) => $('#host-form').elements[name].addEventListener('input', () => { $('#host-form').elements.host_key.value = ''; clearPendingHostKey(); }));
$('#cancel-host-edit').onclick = resetHostForm;
$('#cancel-repo-edit').onclick = resetRepositoryForm;
$('#repo-form').elements.managed.onchange = toggleRepositoryMode;
$('#repo-form').elements.encryption_mode.onchange = toggleRepositoryMode;
$('#repo-form').elements.generate_external_ssh_key.onchange = toggleRepositoryMode;
$('#repo-form').elements.scan_external_host_key.onchange = toggleRepositoryMode;
$('#cancel-job-edit').onclick = resetJobForm;
$('#cancel-schedule-edit').onclick = resetScheduleForm;
$('#schedule-target-mode').onchange = toggleScheduleTarget;
$('#job-form').elements.compression.onchange = toggleCompressionMode;
$('#schedule-mode').onchange = updateSchedulePreview;
$('#add-schedule-time').onclick = () => { addScheduleTime('02:00'); updateSchedulePreview(); };
$$('#schedule-weekdays input').forEach((input) => input.onchange = updateSchedulePreview);
$('#schedule-day').oninput = updateSchedulePreview;
$('#schedule-custom').oninput = updateSchedulePreview;
$('#discover-repositories').onclick = discoverRepositories;
$('#archive-repository').onchange = markArchivesStale;
$('#archive-consider-checkpoints').onchange = markArchivesStale;
$('#archive-device-filter').onchange = () => {
  if (!state.archiveData) return;
  localStorage.setItem(`bbm-archive-device-${state.archiveData.repository_id}`, $('#archive-device-filter').value);
  renderArchives();
};
$('#load-archives').onclick = () => loadArchives();
$('#refresh-archives').onclick = () => loadArchives({force: true});
$('#archive-select-visible').onchange = (event) => {
  const selectedDevice = $('#archive-device-filter').value;
  const visibleArchives = sortArchivesNewestFirst(state.archiveData?.archives || []).filter((archive) => {
    const device = archiveDevice(archive);
    return !selectedDevice || (selectedDevice === '__unassigned__' ? !device : device === selectedDevice);
  });
  visibleArchives.forEach((archive) => {
    if (event.target.checked) state.archiveSelection.add(archive.name);
    else state.archiveSelection.delete(archive.name);
  });
  renderArchives();
};
$('#delete-selected-archives').onclick = deleteSelectedArchives;
$('#compare-archives').onclick = compareArchives;
$('#browser-up').onclick = () => browseArchive($('#browser-up').dataset.parent || '');
$('#close-archive-browser').onclick = closeArchiveBrowser;
$('#export-browser-selection').onclick = exportBrowserSelection;
$('#use-browser-selection').onclick = () => {
  if (!state.activeBrowser) return;
  const job = state.jobs.find((item) => item.id === state.activeBrowser.job_id);
  const prefixes = job?.archive_prefixes?.length ? job.archive_prefixes : (job ? [job.archive_prefix] : []);
  const legacy = !job || !prefixes.some((prefix) => state.activeBrowser.archive.startsWith(prefix));
  prepareRestore(state.activeBrowser.job_id, state.activeBrowser.archive, legacy, [...state.browserSelection]);
};
$('#restore-form').elements.job_id.onchange = () => syncRestoreArchives(true);
$('#restore-form').elements.allow_legacy_archive.onchange = () => syncRestoreArchives(true);
$('#restore-form').elements.consider_checkpoints.onchange = () => syncRestoreArchives(true);
$$('#restore-form input[name=restore_mode]').forEach((input) => input.onchange = toggleRestoreDestination);
$('#restore-form').elements.dry_run.onchange = toggleRestoreDestination;

toggleRepositoryMode();
toggleCompressionMode();
resetScheduleForm();
resetUserForm();

function resetSystemDiagnostics() {
  $('#system-diagnostics').className = 'empty';
  $('#system-diagnostics').textContent = 'Borg-Version, Repository-Speicher und Serverprotokoll bei Bedarf laden.';
  $('#load-diagnostics').textContent = 'Diagnose laden';
  $('#close-diagnostics').classList.add('hidden');
}

$('#load-diagnostics').onclick = async () => {
  const button = $('#load-diagnostics');
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Diagnose wird geladen …';
  setSyncState('Systemdiagnose wird geladen …', 'pending', true);
  try {
    const diagnostics = await api('/system/diagnostics'); const storage = diagnostics.repository_storage; const checks = diagnostics.repository_server_checks || {};
    const filesystems = diagnostics.repository_storage_filesystems || (storage ? [storage] : []);
    const filesystemRows = filesystems.map((item) => {
      const repositories = item.repositories?.length ? item.repositories.map((repo) => `${esc(repo.name)} · ${repo.guard_enabled ? `Sperre ab ${repo.guard_threshold_percent} %${repo.guard_source === 'repository' ? ' (Repository)' : ' (global)'}` : 'Sperre deaktiviert'}${repo.guard_blocked ? ' · BLOCKIERT' : ''}`).join('<br>') : `Keine direkte Repository-Zuordnung · globale Sperre ${item.guard_enabled ? 'ab ' + item.guard_threshold_percent + ' %' : 'deaktiviert'}`;
      return `<tr><td data-label="Mount"><code>${esc(item.path)}</code></td><td data-label="Belegung">${formatBytes(item.used)} / ${formatBytes(item.total)}<small>${item.percent} % · ${formatBytes(item.free)} frei</small></td><td data-label="Repositories">${repositories}</td><td data-label="Status"><span class="badge ${item.guard_blocked ? 'failed' : 'success'}">${item.guard_blocked ? 'Backups blockiert' : 'OK'}</span></td></tr>`;
    }).join('');
    $('#system-diagnostics').className = '';
    $('#system-diagnostics').innerHTML = `<p><b>Repository-Server:</b> ${esc(diagnostics.borg_version)}</p><h3>Repository-Dateisysteme</h3>${filesystemRows ? `<div class="table-scroll"><table class="data-table"><thead><tr><th>Mount</th><th>Belegung</th><th>Repositories / Sperre</th><th>Status</th></tr></thead><tbody>${filesystemRows}</tbody></table></div>` : '<p>Repository-Speicher konnte nicht ermittelt werden.</p>'}<p><b>Serverprüfungen:</b> Repository R/W/X: ${checks.repository_readable_as_borg && checks.repository_writable_as_borg && checks.repository_searchable_as_borg ? 'OK' : 'FEHLER'} · sshd lauscht: ${checks.repository_sshd_listening ? 'OK' : 'FEHLER'} · sshd-Konfiguration: ${checks.sshd_configuration_valid ? 'OK' : 'FEHLER'} · authorized_keys lesbar: ${checks.authorized_keys_readable_as_borg ? 'OK' : 'FEHLER'} · Forced Command: ${checks.all_keys_use_forced_command ? 'OK' : 'FEHLER'} · Log schreibbar: ${checks.log_writable_as_borg ? 'OK' : 'FEHLER'} · Wrapper ausführbar: ${checks.serve_wrapper_executable ? 'OK' : 'FEHLER'} · Zugänge vollständig: ${checks.repository_access_complete ? 'OK' : 'FEHLER'} (${checks.authorized_device_keys ?? 0}/${checks.repository_access_rows ?? 0}) · gemeinsam genutzte Repositories: ${checks.managed_repositories_shared_across_hosts ?? 0}</p><h3>sshd-Log</h3><pre>${esc(diagnostics.sshd_log || 'Noch keine SSH-Servermeldung protokolliert.')}</pre><h3>borg-serve-Log</h3><pre>${esc(diagnostics.borg_serve_log || 'Noch kein Start von borg serve protokolliert.')}</pre>`;
    button.textContent = 'Diagnose neu laden';
    $('#close-diagnostics').classList.remove('hidden');
    setSyncState('Systemdiagnose aktualisiert', 'success');
  } catch (error) {
    button.textContent = originalText;
    setSyncState('Systemdiagnose konnte nicht geladen werden', 'error');
    toast(error.message, true);
  } finally { button.disabled = false; }
};
$('#close-diagnostics').onclick = () => {
  resetSystemDiagnostics();
  setSyncState('Systemdiagnose geschlossen', 'success');
};

function applyTheme(appearance, persist = true) {
  const preference = ['auto', 'light', 'dark'].includes(appearance) ? appearance : 'auto';
  const theme = effectiveTheme(preference);
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('bbm-theme', theme); } catch { /* optional browser storage */ }
  $('#theme-toggle').textContent = theme === 'dark' ? 'Hell' : 'Dunkel';
  if (state.currentUser) state.currentUser.appearance = preference;
  if (persist && state.currentUser) saveUserPreferences().catch((error) => toast(error.message, true));
}

function applyUserPreferences(persistLanguage = true) {
  loadSortPreferences();
  const language = state.currentUser?.language === 'en' ? 'en' : 'de';
  window.BBMI18n?.setLanguage?.(language, persistLanguage);
  dateFormatter = createDateFormatter();
  applyTheme(state.currentUser?.appearance || 'auto', false);
  loadHelpLanguage(language);
  const form = $('#preferences-form');
  if (form) {
    form.elements.language.value = language;
    form.elements.appearance.value = state.currentUser?.appearance || 'auto';
  }
}

async function saveUserPreferences() {
  if (!state.currentUser) return;
  const result = await api('/auth/preferences', {
    method: 'PUT',
    body: JSON.stringify({language: state.currentUser.language || 'de', appearance: state.currentUser.appearance || 'auto'}),
  });
  state.currentUser.language = result.language;
  state.currentUser.appearance = result.appearance;
}

async function copyControllerKey() {
  try { await copyText(state.system.controller_public_key, 'Controller-Schlüssel kopiert', 'Controller-Schlüssel'); }
  catch (error) { toast(error.message, true); }
}
$('#copy-controller-key').onclick = copyControllerKey;
$('#settings-copy-controller-key').onclick = copyControllerKey;
$('#open-controller-key-settings').onclick = () => {
  goToView('settings');
  requestAnimationFrame(() => $('#settings-controller-key-section').scrollIntoView({behavior: 'smooth', block: 'start'}));
};
$('#rotate-controller-key').onclick = rotateControllerKey;
$('#close-controller-key-dialog').onclick = () => $('#controller-key-dialog').close();
$('#controller-key-confirm-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, 'Schlüssel wird erneuert …');
  setSyncState('Controller-Schlüssel wird erneuert …', 'pending', true);
  const confirmation = event.target.elements.confirmation.value;
  try {
    const result = await api('/system/controller-key/rotate', {method: 'POST', body: JSON.stringify({confirmation})});
    state.system.controller_public_key = result.controller_public_key;
    $('#controller-key').textContent = result.controller_public_key;
    $('#settings-controller-key').textContent = result.controller_public_key;
    $('#settings-controller-key-status').textContent = 'Schlüssel erneuert. Der neue öffentliche Schlüssel muss jetzt auf allen Geräten hinterlegt werden.';
    $('#settings-controller-key-status').classList.add('warning-text');
    $('#controller-key-dialog').close();
    setSyncState('Controller-Schlüssel erneuert', 'success');
    toast('Controller-Schlüssel erneuert');
  } catch (error) { setSyncState('Schlüsselerneuerung fehlgeschlagen', 'error'); $('#controller-key-confirm-error').textContent = error.message; }
  finally { release(); }
};
$('#theme-toggle').onclick = () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
$('#user-preferences').onclick = () => {
  const form = $('#preferences-form');
  form.elements.language.value = state.currentUser?.language || 'de';
  form.elements.appearance.value = state.currentUser?.appearance || 'auto';
  $('#preferences-error').textContent = '';
  $('#preferences-dialog').showModal();
};
$('#close-preferences-dialog').onclick = () => $('#preferences-dialog').close();
$('#preferences-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, currentLanguage() === 'en' ? 'Saving …' : 'Wird gespeichert …');
  $('#preferences-error').textContent = '';
  try {
    const form = new FormData(event.target);
    state.currentUser.language = form.get('language') === 'en' ? 'en' : 'de';
    state.currentUser.appearance = ['auto', 'light', 'dark'].includes(form.get('appearance')) ? form.get('appearance') : 'auto';
    await saveUserPreferences();
    applyUserPreferences();
    $('#preferences-dialog').close();
    setSyncState(currentLanguage() === 'en' ? 'Personal preferences saved' : 'Persönliche Einstellungen gespeichert', 'success');
  } catch (error) { $('#preferences-error').textContent = error.message; }
  finally { release(); }
};
applyTheme(document.documentElement.dataset.theme || 'light', false);
window.BBMI18n?.setLanguage?.(currentLanguage(), false);

async function logout(callServer = true) {
  clearTimeout(state.refreshTimer);
  state.currentUser = null; state.users = [];
  if (callServer) {
    try { await api('/auth/logout', {method: 'POST'}); } catch { /* Sitzung lokal trotzdem beenden. */ }
  }
  storeReloadSessionToken('');
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
  $('#login-password').value = '';
}

function openPasswordDialog(force = false) {
  const dialog = $('#password-dialog');
  $('#password-dialog-note').textContent = force
    ? 'Das temporäre Passwort muss vor der weiteren Nutzung geändert werden.'
    : 'Nach dem Wechsel ist eine erneute Anmeldung erforderlich.';
  $('#close-password-dialog').classList.toggle('hidden', force);
  dialog.dataset.force = force ? '1' : '0';
  dialog.showModal();
}

$('#close-user-password-dialog').onclick = () => $('#user-password-dialog').close();
$('#user-password-form').onsubmit = async (event) => {
  event.preventDefault(); const form = new FormData(event.target); $('#user-password-error').textContent = '';
  try {
    await api(`/users/${+form.get('user_id')}/password`, {method: 'POST', body: JSON.stringify({
      password: form.get('password'), password_confirm: form.get('password_confirm'),
      must_change_password: form.get('must_change_password') === 'on',
    })});
    $('#user-password-dialog').close(); event.target.reset();
    toast('Passwort gesetzt; bestehende Sitzungen wurden beendet'); await refreshAreas(['users', 'security']);
  } catch (error) { $('#user-password-error').textContent = error.message; }
};

$('#logout').onclick = () => logout(true);
$('#change-password').onclick = () => openPasswordDialog(false);
$('#close-password-dialog').onclick = () => $('#password-dialog').close();
$('#password-dialog').addEventListener('cancel', (event) => { if ($('#password-dialog').dataset.force === '1') event.preventDefault(); });
$('#password-form').onsubmit = async (event) => {
  event.preventDefault(); const form = new FormData(event.target); $('#password-error').textContent = '';
  try {
    await api('/auth/change-password', {method: 'POST', body: JSON.stringify({current_password: form.get('current_password'), new_password: form.get('new_password'), new_password_confirm: form.get('new_password_confirm')})});
    $('#password-dialog').close(); event.target.reset();
    await logout(false); $('#login-error').textContent = 'Passwort geändert. Bitte mit dem neuen Passwort erneut anmelden.';
  } catch (error) { $('#password-error').textContent = error.message; }
};

$('#restore-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const dryRun = form.get('dry_run') === 'on';
  const restoreMode = form.get('restore_mode');
  const paths = lines(form.get('paths'));
  const status = $('#restore-status');
  status.classList.add('hidden');
  status.classList.remove('error-state');
  if (restoreMode === 'original' && !paths.length) {
    status.textContent = 'Für die Wiederherstellung am Originalpfad muss mindestens eine Datei oder ein Ordner ausgewählt sein.';
    status.classList.remove('hidden'); status.classList.add('error-state'); return;
  }
  if (!dryRun && restoreMode === 'original' && form.get('overwrite_existing') !== 'on') {
    status.textContent = 'Bitte die mögliche Ersetzung vorhandener Dateien ausdrücklich bestätigen.';
    status.classList.remove('hidden'); status.classList.add('error-state'); return;
  }
  try {
    const payload = {
      archive: form.get('archive'), paths,
      restore_mode: restoreMode,
      target_directory: restoreMode === 'target' ? form.get('target_directory') : null,
      target_layout: form.get('target_layout'),
      dry_run: dryRun,
      overwrite_existing: form.get('overwrite_existing') === 'on',
      allow_legacy_archive: form.get('allow_legacy_archive') === 'on',
    };
    const result = await api(`/jobs/${+form.get('job_id')}/restore`, {method: 'POST', body: JSON.stringify(payload)});
    status.textContent = `${dryRun ? 'Restore-Test' : 'Wiederherstellung'} als Lauf #${result.run_id} gestartet.`;
    status.classList.remove('hidden');
    toast(`${dryRun ? 'Restore-Test' : 'Wiederherstellung'} #${result.run_id} gestartet`);
    await refreshAreas(['dashboard', 'runs'], `Lauf #${result.run_id} wurde angenommen …`);
    watchRunCompletion(result.run_id, {areas: ['dashboard', 'runs']});
    showRun(result.run_id);
  } catch (error) {
    status.textContent = 'Restore konnte nicht gestartet werden: ' + error.message;
    status.classList.remove('hidden'); status.classList.add('error-state');
  }
};

toggleRestoreDestination();

$('#backup-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, 'Backup wird erstellt …');
  setSyncState('Manager-Backup wird erstellt …', 'pending', true);
  const form = new FormData(event.target);
  const payload = {
    label: form.get('label') || '',
    encrypted: true,
    passphrase: form.get('passphrase'),
    passphrase_confirm: form.get('passphrase_confirm'),
  };
  try {
    await api('/backups', {method: 'POST', body: JSON.stringify(payload)});
    toast('Manager-Backup erstellt');
    event.target.reset();
    await refreshAreas(['backups']);
  } catch (error) { setSyncState('Manager-Backup konnte nicht erstellt werden', 'error'); toast(error.message, true); }
  finally { release(); }
};

$('#backup-upload-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const file = form.get('backup_file');
  const status = $('#backup-upload-status');
  if (!(file instanceof File) || !file.name || !file.size) {
    status.textContent = 'Bitte eine nicht leere Manager-Backup-Datei auswählen.';
    status.classList.remove('hidden'); status.classList.add('error-state');
    return;
  }
  const release = markButtonBusy(event.submitter, 'Backup wird hochgeladen …');
  status.textContent = 'Backup wird übertragen und serverseitig geprüft …';
  status.classList.remove('hidden', 'error-state');
  try {
    await api('/backups/upload', {
      method: 'POST',
      headers: {'Content-Type': 'application/octet-stream', 'X-BBM-Backup-Name': file.name},
      body: file,
    });
    status.textContent = `Backup „${file.name}“ wurde geprüft und übernommen.`;
    toast('Manager-Backup hochgeladen');
    event.target.reset();
    await refreshAreas(['backups']);
  } catch (error) {
    status.textContent = 'Backup konnte nicht hochgeladen werden: ' + error.message;
    status.classList.add('error-state');
    toast(error.message, true);
  } finally { release(); }
};


async function waitForManagerAfterRestore() {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    try {
      const response = await fetch('/api/ready', {credentials: 'same-origin', cache: 'no-store'});
      if (response.ok) { location.reload(); return; }
    } catch { /* Container startet neu. */ }
  }
  const status = $('#backup-restore-status');
  status.textContent = 'Der automatische Neustart dauert ungewöhnlich lange. Containerstatus und Logs prüfen.';
  status.classList.add('error-state');
}

$('#backup-restore-form').onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const name = form.get('name');
  const status = $('#backup-restore-status');
  if (!confirm(`Manager-Backup ${name} wirklich wiederherstellen? Die WebUI startet anschließend neu.`)) return;
  status.textContent = 'Backup wird geprüft und für die Wiederherstellung vorbereitet …';
  status.classList.remove('hidden', 'error-state');
  try {
    const result = await api(`/backups/${encodeURIComponent(name)}/restore`, {
      method: 'POST',
      body: JSON.stringify({
        passphrase: form.get('passphrase') || null,
        safety_passphrase: form.get('safety_passphrase'),
        safety_passphrase_confirm: form.get('safety_passphrase_confirm'),
        confirm: form.get('confirm') === 'on',
      }),
    });
    status.textContent = `${result.message} Sicherheitsbackup: ${result.safety_backup}`;
    clearTimeout(state.refreshTimer);
    waitForManagerAfterRestore();
  } catch (error) {
    status.textContent = 'Wiederherstellung konnte nicht gestartet werden: ' + error.message;
    status.classList.add('error-state');
  }
};
$('#cleanup-expired-runs')?.addEventListener('click', () => cleanupRunHistory('expired'));
$('#cleanup-all-runs')?.addEventListener('click', () => cleanupRunHistory('all_finished'));

$('#notification-form').onsubmit = async (event) => {
  event.preventDefault();
  const release = markButtonBusy(event.submitter, 'Konfiguration wird gespeichert …');
  const status = $('#notification-form-status');
  status.classList.add('hidden');
  try {
    state.notifications = await api('/notifications/settings', {method: 'PUT', body: JSON.stringify(notificationPayload(event.target))});
    renderNotifications();
    toast('Benachrichtigungskonfiguration gespeichert');
  } catch (error) {
    status.textContent = error.message; status.classList.remove('hidden'); toast(error.message, true);
  } finally { release(); }
};
$('#test-notification-email').onclick = (event) => testNotification('email', event.currentTarget);
$('#test-notification-webhook').onclick = (event) => testNotification('webhook', event.currentTarget);
$('#test-notification-telegram').onclick = (event) => testNotification('telegram', event.currentTarget);
$('#refresh-notification-deliveries').onclick = () => refreshAreas(['notifications']);
$('#clear-notification-deliveries').onclick = async (event) => {
  if (!confirm('Benachrichtigungsprotokoll wirklich vollständig leeren?')) return;
  const release = markButtonBusy(event.currentTarget, 'Wird gelöscht …');
  try { await api('/notifications/deliveries', {method: 'DELETE'}); await refreshAreas(['notifications']); toast('Benachrichtigungsprotokoll geleert'); }
  catch (error) { toast(error.message, true); } finally { release(); }
};

$('#settings-form').elements.density.onchange = (event) => {
  document.body.classList.toggle('compact', event.target.value === 'compact');
};
$('#settings-form').elements.list_max_height.oninput = (event) => {
  const value = Math.min(1200, Math.max(240, Number(event.target.value) || 520));
  document.documentElement.style.setProperty('--list-max-height', value + 'px');
};
$('#settings-form').onsubmit = async (event) => {
  event.preventDefault(); const release = markButtonBusy(event.submitter, 'Wird gespeichert …'); setSyncState('Einstellungen werden gespeichert …', 'pending', true); const form = new FormData(event.target);
  const payload = {appearance: state.settings.appearance || 'auto', density: form.get('density'), dashboard_recent_runs_limit: +form.get('dashboard_recent_runs_limit'), runs_list_limit: +form.get('runs_list_limit'), auto_refresh_seconds: +form.get('auto_refresh_seconds'), list_max_height: +form.get('list_max_height'), run_retention_days: +form.get('run_retention_days'), run_log_max_mib: +form.get('run_log_max_mib'), run_log_view_kib: +form.get('run_log_view_kib'), max_parallel_runs: +form.get('max_parallel_runs'), repository_size_after_run: form.get('repository_size_after_run') === 'on', compact_after_prune: form.get('compact_after_prune') === 'on', storage_guard_enabled: form.get('storage_guard_enabled') === 'on', storage_guard_threshold_percent: +form.get('storage_guard_threshold_percent'), exclude_templates: collectExcludeTemplates()};
  try { state.settings = await api('/settings', {method: 'PUT', body: JSON.stringify(payload)}); renderSettings(); scheduleRefresh(); setSyncState('Einstellungen übernommen', 'success'); toast('Einstellungen gespeichert'); }
  catch (error) { setSyncState('Einstellungen konnten nicht gespeichert werden', 'error'); toast(error.message, true); }
  finally { release(); }
};
$('#runs-limit').onchange = async (event) => {
  if (!state.settings) return; state.settings.runs_list_limit = +event.target.value;
  try { state.settings = await api('/settings', {method: 'PUT', body: JSON.stringify(state.settings)}); loadRunsOnly(); }
  catch (error) { toast(error.message, true); }
};

const SORT_CONTROL_BINDINGS = [
  ['#dashboard-job-sort', 'dashboardJobs', () => renderDashboard(state.dashboard)],
  ['#job-sort', 'jobs', renderJobs], ['#repo-sort', 'repositories', renderRepos], ['#host-sort', 'hosts', renderHosts],
];
for (const [selector, key, render] of SORT_CONTROL_BINDINGS) {
  const control = $(selector);
  if (control) control.onchange = (event) => { saveSortPreference(key, event.target.value); render(); };
}

document.addEventListener('bbm-language-changed', (event) => {
  dateFormatter = createDateFormatter();
  loadHelpLanguage(event.detail?.language || currentLanguage());
  if (state.archiveData) renderArchives();
  if (hashView() === 'releases') loadReleaseNotes();
});

const BBM_ACTION_HANDLERS = Object.freeze({
  removeEntity, action, showRun, resetRepositoryState, initRepository, compactRepository, goToView, goToRuns,
  toggleJobActions, cancelExecution, retryExecution, deleteExecution, refreshRepoSize, testRepository,
  clearRepositoryCache, editHost, checkHostVersion, setHostEnabled, editRepository, copyRepositoryPublicKey, editJob, setJobEnabled,
  bootstrapJob, confirmRepositoryLocation, editSchedule, deleteSchedule, openRepositoryArchives,
  editUser, resetUserPassword, deleteUser, showRepositoryDiagnostic, showRepositoryStatusDetails,
});

document.addEventListener('click', (event) => {
  const source = event.target instanceof Element ? event.target : null;
  const control = source?.closest('[data-bbm-action]');
  if (!control || control.disabled) return;
  const handler = BBM_ACTION_HANDLERS[control.dataset.bbmAction];
  if (typeof handler !== 'function') {
    console.error('Unbekannte BBM-Oberflächenaktion', control.dataset.bbmAction);
    return;
  }
  event.preventDefault();
  let args = [];
  try {
    args = JSON.parse(control.dataset.bbmArgs || '[]');
    if (!Array.isArray(args)) throw new TypeError('Aktionsargumente sind keine Liste');
  } catch (error) {
    console.error('Ungültige BBM-Oberflächenaktion', error);
    toast('Die Oberflächenaktion enthält ungültige Daten.', true);
    return;
  }
  try {
    const result = handler(...args);
    if (result && typeof result.catch === 'function') {
      result.catch((error) => {
        console.error('BBM-Oberflächenaktion fehlgeschlagen', error);
        toast(error?.message || 'Oberflächenaktion fehlgeschlagen', true);
      });
    }
  } catch (error) {
    console.error('BBM-Oberflächenaktion fehlgeschlagen', error);
    toast(error?.message || 'Oberflächenaktion fehlgeschlagen', true);
  }
});

Object.assign(window, {
  removeEntity, action, showRun, openActiveRun, resetRepositoryState, initRepository, compactRepository, goToView, goToRuns, toggleJobActions, cancelExecution, retryExecution, deleteExecution, cleanupRunHistory,
  refreshRepoSize, testRepository, clearRepositoryCache, downloadBackup, deleteBackup, rotateControllerKey, editHost, setHostEnabled, editRepository, editJob, setJobEnabled, editSchedule, deleteSchedule, prepareRepositoryImport,
  openRepositoryArchives, archiveInfo, renameArchive, deleteArchive, deleteSelectedArchives, openArchiveBrowser, prepareRestore, exportBrowserSelection, editUser, resetUserPassword, deleteUser,
  showRepositoryDiagnostic, showRepositoryStatusDetails,
});

state.runFilter = parseHashState().status;
goToView(hashView(), false);
scrollToHelpSection(parseHashState().section);
async function restoreBrowserSession() {
  try {
    const current = await verifyBrowserSession();
    if (loginInProgress || state.currentUser) return;
    state.currentUser = current;
    applyUserPreferences(false);
    $('#login').classList.add('hidden'); $('#app').classList.remove('hidden');
    applyUserPermissions();
    if (current.must_change_password) { openPasswordDialog(true); return; }
    await loadAll();
  } catch (error) {
    if (!loginInProgress && !state.currentUser) {
      const detail = error instanceof ApiError && error.status === 401
        ? `Sitzung konnte nicht wiederhergestellt werden: ${error.message}` : '';
      if (error instanceof ApiError && error.status === 401) storeReloadSessionToken('');
      showLoginScreen(detail);
    }
  }
}
restoreBrowserSession();
