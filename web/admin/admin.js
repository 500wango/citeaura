const root = document.getElementById('admin-root');
const toastRoot = document.getElementById('admin-toast');

const NAV = [
  ['overview', 'Overview', 'layout-dashboard'],
  ['countries', 'Countries', 'globe'],
  ['users', 'Users', 'radar'],
  ['tenants', 'Workspaces', 'scan-search'],
  ['subscriptions', 'Subscriptions', 'package-check'],
  ['jobs', 'Jobs', 'list-checks'],
  ['audit', 'Admin audit', 'settings-2'],
  ['account', 'Account', 'settings-2'],
];

const state = {
  admin: null,
  view: location.hash.replace(/^#\/?/, '') || 'overview',
  days: 30,
  country: '',
  query: '',
  page: 1,
  countries: [],
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function qs(params = {}) {
  const values = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) values.set(key, value);
  });
  const encoded = values.toString();
  return encoded ? `?${encoded}` : '';
}

async function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  if (options.body && typeof options.body === 'object') {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== 'GET') headers['X-CiteAura-Admin'] = 'console';
  const response = await fetch(`/api/v1/admin${path}`, { credentials: 'include', ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'request_failed');
    error.status = response.status;
    throw error;
  }
  return data;
}

function toast(message, isError = false) {
  toastRoot.textContent = message;
  toastRoot.className = `admin-toast is-visible${isError ? ' is-error' : ''}`;
  window.setTimeout(() => { toastRoot.className = 'admin-toast'; }, 3000);
}

function money(cents) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format((Number(cents) || 0) / 100);
}

function number(value) {
  return new Intl.NumberFormat('en-US').format(Number(value) || 0);
}

function percent(value) {
  return value === null || value === undefined ? 'Not mature' : `${Number(value).toFixed(1)}%`;
}

function dateTime(value) {
  if (!value) return 'Unknown';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
}

function countryName(code) {
  if (!code) return 'Unknown';
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) || code;
  } catch (_) {
    return code;
  }
}

function statusClass(value) {
  if (['active', 'done', 'succeeded', 'ready'].includes(value)) return 'status-good';
  if (['past_due', 'queued', 'running', 'trialing', 'incomplete'].includes(value)) return 'status-warn';
  if (['failed', 'unpaid', 'disabled'].includes(value)) return 'status-bad';
  return 'status-muted';
}

function tag(value) {
  return `<span class="tag ${statusClass(value)}">${escapeHtml(value || 'unknown')}</span>`;
}

function canOperate() {
  return ['ops', 'superadmin'].includes(state.admin?.role);
}

function showLogin(message = '') {
  root.className = '';
  root.innerHTML = `
    <main class="admin-login">
      <section class="admin-login-panel">
        <a class="admin-brand" href="/">
          <img src="/site-assets/brand/mark.svg" alt="">
          <strong>CiteAura</strong><span>Platform operations</span>
        </a>
        <h1>Administrator sign in</h1>
        <p class="admin-login-copy">Use your platform administrator credentials.</p>
        <form id="admin-login-form" class="admin-login-form">
          <div class="admin-field"><label for="admin-email">Email</label><input class="input" id="admin-email" type="email" autocomplete="username" required></div>
          <div class="admin-field"><label for="admin-password">Password</label><input class="input" id="admin-password" type="password" autocomplete="current-password" required></div>
          <div id="admin-login-error" class="admin-form-error">${escapeHtml(message)}</div>
          <button class="btn btn-primary btn-lg btn-block" type="submit">Sign in</button>
        </form>
      </section>
      <section class="admin-login-context" aria-hidden="true"><h2>Revenue, conversion, customer geography, and platform health in one operating view.</h2></section>
    </main>`;
  document.getElementById('admin-login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    try {
      await api('/auth/login', {
        method: 'POST',
        body: {
          email: document.getElementById('admin-email').value,
          password: document.getElementById('admin-password').value,
        },
      });
      state.admin = (await api('/me')).admin;
      renderShell();
      await renderView();
    } catch (error) {
      document.getElementById('admin-login-error').textContent = error.message === 'invalid_admin_credentials' ? 'Email or password is incorrect.' : 'Unable to sign in.';
    } finally {
      button.disabled = false;
    }
  });
}

function renderShell() {
  root.className = '';
  root.innerHTML = `
    <div class="admin-shell">
      <aside class="admin-sidebar">
        <a class="admin-brand" href="/admin/"><img src="/site-assets/brand/mark.svg" alt=""><strong>CiteAura</strong><span>Operations</span></a>
        <nav class="admin-nav" aria-label="Platform operations">
          ${NAV.map(([id, label, icon]) => `<button type="button" class="admin-nav-button${state.view === id ? ' is-active' : ''}" data-view="${id}"><img src="/site-assets/icons/${icon}.svg" alt=""><span>${label}</span></button>`).join('')}
        </nav>
        <div class="admin-account">
          <div class="admin-account-email">${escapeHtml(state.admin.email)}</div>
          <div class="admin-account-role">${escapeHtml(state.admin.role)}</div>
          <button class="admin-logout" id="admin-logout" type="button"><img src="/site-assets/icons/log-out.svg" alt="">Sign out</button>
        </div>
      </aside>
      <main class="admin-main">
        <header class="admin-header">
          <div class="admin-title"><h1 id="admin-page-title">Overview</h1><p id="admin-page-desc">Platform operating metrics</p></div>
          <div class="admin-filters" id="admin-global-filters">
            <select class="input admin-filter" id="admin-days" aria-label="Time range">
              ${[7, 30, 90, 365].map((days) => `<option value="${days}"${days === state.days ? ' selected' : ''}>Last ${days} days</option>`).join('')}
            </select>
            <select class="input admin-filter" id="admin-country" aria-label="Acquisition country"><option value="">All countries</option></select>
          </div>
        </header>
        <div class="admin-content" id="admin-content"><div class="admin-loading">Loading...</div></div>
      </main>
    </div>`;
  root.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', () => {
    state.view = button.dataset.view;
    state.page = 1;
    state.query = '';
    location.hash = `/${state.view}`;
    renderShell();
    renderView();
  }));
  document.getElementById('admin-days').addEventListener('change', (event) => {
    state.days = Number(event.target.value);
    renderView();
  });
  document.getElementById('admin-country').addEventListener('change', (event) => {
    state.country = event.target.value;
    state.page = 1;
    renderView();
  });
  document.getElementById('admin-logout').addEventListener('click', async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    state.admin = null;
    showLogin();
  });
  populateCountryFilter();
}

function populateCountryFilter() {
  const select = document.getElementById('admin-country');
  if (!select) return;
  const options = state.countries.filter(Boolean).sort().map((code) => `<option value="${code}"${state.country === code ? ' selected' : ''}>${escapeHtml(countryName(code))}</option>`).join('');
  select.innerHTML = `<option value="">All countries</option>${options}`;
  select.value = state.country;
}

function setHeader(title, description, showGlobal = true) {
  document.getElementById('admin-page-title').textContent = title;
  document.getElementById('admin-page-desc').textContent = description;
  document.getElementById('admin-global-filters').style.display = showGlobal ? '' : 'none';
}

function kpi(label, value, sub = '') {
  return `<div class="kpi"><div class="kpi-label">${escapeHtml(label)}</div><strong class="kpi-value">${escapeHtml(value)}</strong><div class="kpi-sub">${escapeHtml(sub)}</div></div>`;
}

async function renderOverview() {
  setHeader('Overview', 'Customer conversion, USD revenue, and operating health');
  const data = await api(`/overview${qs({ days: state.days, country: state.country })}`);
  const maxFunnel = Math.max(data.funnel.visitors, data.funnel.signups, data.customers.activated, data.customers.paid_current, 1);
  const steps = [
    ['Unique visitors', data.funnel.visitors],
    ['Registered workspaces', data.funnel.signups],
    ['Activated', data.customers.activated],
    ['Current paid', data.customers.paid_current],
  ];
  document.getElementById('admin-content').innerHTML = `
    <section class="admin-section"><div class="kpis admin-kpis">
      ${kpi('Registered', number(data.customers.registered), `Last ${state.days} days`)}
      ${kpi('Activation', percent(data.customers.activation_rate), `${number(data.customers.activated)} workspaces`)}
      ${kpi('Current paid', number(data.customers.paid_current), `${number(data.customers.trialing)} trialing`)}
      ${kpi('Trial conversion', percent(data.funnel.trial_to_paid_rate), `${number(data.funnel.converted_trials)} of ${number(data.funnel.matured_trials)}`)}
      ${kpi('MRR', money(data.revenue.mrr_usd_cents), 'USD monthly recurring')}
      ${kpi('ARR', money(data.revenue.arr_usd_cents), 'USD annualized')}
    </div></section>
    <section class="admin-section admin-panels">
      <div class="admin-panel"><div class="admin-panel-head"><h3>Acquisition funnel</h3><span class="tag tag-outline">${escapeHtml(data.range.country || 'All countries')}</span></div><div class="admin-funnel">
        ${steps.map(([label, value]) => `<div class="admin-funnel-row"><span>${label}</span><span class="admin-funnel-track"><span class="admin-funnel-fill" style="width:${Math.max(1, value * 100 / maxFunnel)}%"></span></span><strong class="admin-funnel-value">${number(value)}</strong></div>`).join('')}
      </div></div>
      <div class="admin-panel"><div class="admin-panel-head"><h3>Revenue and reliability</h3></div><div class="admin-health">
        <div class="admin-health-row"><span>Gross USD payments</span><strong>${money(data.revenue.payments_usd_cents)}</strong></div>
        <div class="admin-health-row"><span>USD refunds</span><strong>${money(data.revenue.refunds_usd_cents)}</strong></div>
        <div class="admin-health-row"><span>Net USD payments</span><strong>${money(data.revenue.net_payments_usd_cents)}</strong></div>
        <div class="admin-health-row"><span>Checkout conversion</span><strong>${percent(data.funnel.checkout_conversion_rate)}</strong></div>
        <div class="admin-health-row"><span>Past due subscriptions</span><strong>${number(data.revenue.past_due)}</strong></div>
        <div class="admin-health-row"><span>Canceling subscriptions</span><strong>${number(data.revenue.canceling)}</strong></div>
        <div class="admin-health-row"><span>Job failure rate</span><strong>${percent(data.operations.job_failure_rate)}</strong></div>
        <div class="admin-health-row"><span>Country unknown rate</span><strong>${percent(data.customers.unknown_country_rate)}</strong></div>
      </div></div>
    </section>`;
}

async function renderCountries() {
  setHeader('Countries', 'Acquisition geography and trial conversion by signup location');
  const data = await api(`/countries${qs({ days: state.days })}`);
  state.countries = [...new Set(data.countries.map((item) => item.country_code).filter(Boolean))];
  populateCountryFilter();
  const rows = data.countries.filter((item) => !state.country || item.country_code === state.country);
  document.getElementById('admin-content').innerHTML = tableSection('Country performance', `${rows.length} acquisition markets`, ['Country', 'Registered', 'Activated', 'Activation', 'Current paid', 'Trial conversion', 'MRR'], rows.map((item) => `
    <tr><td><div class="primary">${escapeHtml(countryName(item.country_code))}</div><div class="secondary mono">${escapeHtml(item.country_code || 'UNKNOWN')}</div></td><td class="mono">${number(item.registered)}</td><td class="mono">${number(item.activated)}</td><td class="mono">${percent(item.activation_rate)}</td><td class="mono">${number(item.paid_current)}</td><td class="mono">${percent(item.trial_to_paid_rate)}</td><td class="mono">${money(item.mrr_usd_cents)}</td></tr>`));
}

function tableSection(title, description, headers, rows, toolbar = '') {
  return `<section class="admin-section"><div class="admin-section-head"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>${toolbar}</div><div class="admin-table-wrap">${rows.length ? `<table class="table admin-table"><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>` : '<div class="admin-empty">No records match this view.</div>'}</div></section>`;
}

function pagination(data) {
  const { page, per_page: perPage, total } = data.pagination;
  const pages = Math.max(1, Math.ceil(total / perPage));
  if (pages <= 1) return '';
  return `<div class="admin-pagination"><span>Page ${number(page)} of ${number(pages)}</span><div><button class="btn btn-secondary btn-sm" type="button" data-page="${page - 1}"${page <= 1 ? ' disabled' : ''}>Previous</button><button class="btn btn-secondary btn-sm" type="button" data-page="${page + 1}"${page >= pages ? ' disabled' : ''}>Next</button></div></div>`;
}

function bindPagination() {
  document.querySelectorAll('[data-page]').forEach((button) => button.addEventListener('click', () => {
    state.page = Number(button.dataset.page);
    renderView();
  }));
}

function toolbar(placeholder) {
  return `<form class="admin-toolbar" id="admin-search-form"><input class="input admin-search" id="admin-search" type="search" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(placeholder)}"><button class="btn btn-secondary btn-sm" type="submit">Search</button></form>`;
}

function bindSearch() {
  document.getElementById('admin-search-form')?.addEventListener('submit', (event) => {
    event.preventDefault();
    state.query = document.getElementById('admin-search').value.trim();
    state.page = 1;
    renderView();
  });
}

async function renderUsers() {
  setHeader('Users', 'Registered people, membership context, and signup geography');
  const data = await api(`/users${qs({ q: state.query, country: state.country, page: state.page })}`);
  const rows = data.items.map((item) => {
    const workspaces = item.workspaces.map((workspace) => `${workspace.name} (${workspace.role})`).join(', ') || 'No workspace';
    const action = canOperate() ? `<button class="btn btn-ghost btn-sm" data-user-id="${item.id}" data-current-status="${item.status}">${item.status === 'active' ? 'Disable' : 'Restore'}</button>` : '';
    return `<tr><td><div class="primary">${escapeHtml(item.email)}</div><div class="secondary">${escapeHtml(item.registration_kind.replace('_', ' '))}</div></td><td>${tag(item.status)}</td><td>${item.is_paid ? tag('paid') : tag('not paid')}</td><td><div class="primary">${escapeHtml(countryName(item.country_code))}</div><div class="secondary mono">${escapeHtml(item.country_code || 'UNKNOWN')}</div></td><td><div>${escapeHtml(workspaces)}</div></td><td class="mono">${escapeHtml(dateTime(item.last_login_at))}</td><td class="mono">${escapeHtml(dateTime(item.created_at))}</td><td>${action}</td></tr>`;
  });
  document.getElementById('admin-content').innerHTML = tableSection('Registered users', `${number(data.pagination.total)} total users`, ['User', 'Status', 'Billing', 'Signup country', 'Workspaces', 'Last login', 'Registered', ''], rows, toolbar('Search email'));
  document.getElementById('admin-content').insertAdjacentHTML('beforeend', pagination(data));
  bindSearch();
  bindPagination();
  bindStatusActions('user');
}

async function renderTenants() {
  setHeader('Workspaces', 'Customer accounts, activation, plans, and operating status');
  const data = await api(`/tenants${qs({ q: state.query, country: state.country, page: state.page })}`);
  const rows = data.items.map((item) => {
    const action = canOperate() ? `<button class="btn btn-ghost btn-sm" data-tenant-id="${item.id}" data-current-status="${item.status}">${item.status === 'active' ? 'Disable' : 'Restore'}</button>` : '';
    return `<tr><td><div class="primary">${escapeHtml(item.name)}</div><div class="secondary">${escapeHtml(item.owner_email || 'No owner')}</div></td><td>${tag(item.status)}</td><td>${tag(item.plan)}</td><td><div>${escapeHtml(countryName(item.country_code))}</div><div class="secondary mono">${escapeHtml(item.country_code || 'UNKNOWN')}</div></td><td class="mono">${number(item.members)}</td><td class="mono">${number(item.projects)}</td><td>${item.activated ? tag('active') : tag('not activated')}</td><td class="mono">${money(item.mrr_usd_cents)}</td><td>${action}</td></tr>`;
  });
  document.getElementById('admin-content').innerHTML = tableSection('Customer workspaces', `${number(data.pagination.total)} total workspaces`, ['Workspace', 'Status', 'Plan', 'Acquisition country', 'Members', 'Projects', 'Activation', 'MRR', ''], rows, toolbar('Search workspace or owner'));
  document.getElementById('admin-content').insertAdjacentHTML('beforeend', pagination(data));
  bindSearch();
  bindPagination();
  bindStatusActions('tenant');
}

async function renderSubscriptions() {
  setHeader('Subscriptions', 'Recurring revenue and account-level billing state', false);
  const data = await api(`/subscriptions${qs({ page: state.page })}`);
  const rows = data.items.map((item) => `<tr><td><div class="primary">${escapeHtml(item.tenant_name || `Workspace ${item.tenant_id}`)}</div><div class="secondary">${escapeHtml(countryName(item.country_code))}</div></td><td>${tag(item.plan)}</td><td>${tag(item.status)}</td><td>${escapeHtml(item.billing_interval)}</td><td class="mono">${money(item.mrr_usd_cents)}</td><td>${escapeHtml(countryName(item.billing_country_code))}</td><td>${item.cancel_at_period_end ? tag('canceling') : tag('renewing')}</td><td class="mono">${escapeHtml(dateTime(item.expires_at))}</td></tr>`);
  document.getElementById('admin-content').innerHTML = tableSection('Subscription ledger', `${number(data.pagination.total)} subscriptions, USD only`, ['Workspace', 'Plan', 'Status', 'Interval', 'MRR', 'Billing country', 'Renewal', 'Period end'], rows);
  document.getElementById('admin-content').insertAdjacentHTML('beforeend', pagination(data));
  bindPagination();
}

async function renderJobs() {
  setHeader('Jobs', 'Cross-workspace pipeline execution and failure diagnosis', false);
  const data = await api(`/jobs${qs({ q: state.query, page: state.page })}`);
  const rows = data.items.map((item) => `<tr><td class="mono">#${item.id}</td><td><div class="primary">${escapeHtml(item.tenant_name)}</div><div class="secondary">${escapeHtml(item.project_slug)}</div></td><td>${escapeHtml(item.action)}</td><td>${tag(item.status)}</td><td>${escapeHtml(item.stage)}</td><td class="mono">${number(item.progress)}%</td><td class="mono">${item.duration_seconds === null ? 'Running' : `${number(item.duration_seconds)}s`}</td><td><div class="secondary">${escapeHtml(item.error || '')}</div></td></tr>`);
  document.getElementById('admin-content').innerHTML = tableSection('Pipeline jobs', `${number(data.pagination.total)} total jobs`, ['ID', 'Workspace / project', 'Action', 'Status', 'Stage', 'Progress', 'Duration', 'Error'], rows, toolbar('Search workspace, project, or action'));
  document.getElementById('admin-content').insertAdjacentHTML('beforeend', pagination(data));
  bindSearch();
  bindPagination();
}

async function renderAudit() {
  setHeader('Admin audit', 'Immutable record of platform administrator activity', false);
  const data = await api(`/audit${qs({ page: state.page })}`);
  const rows = data.items.map((item) => `<tr><td class="mono">${escapeHtml(dateTime(item.created_at))}</td><td><div class="primary">${escapeHtml(item.admin_email || 'Removed administrator')}</div><div class="secondary mono">${escapeHtml(item.ip_address || 'Unknown IP')}</div></td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.target)}</td><td>${tag(item.outcome)}</td><td><div class="secondary">${escapeHtml(JSON.stringify(item.details))}</div></td></tr>`);
  document.getElementById('admin-content').innerHTML = tableSection('Administrator activity', `${number(data.pagination.total)} audit events`, ['Time', 'Administrator', 'Action', 'Target', 'Outcome', 'Details'], rows);
  document.getElementById('admin-content').insertAdjacentHTML('beforeend', pagination(data));
  bindPagination();
}

async function renderAccount() {
  setHeader('Account', 'Update your platform administrator credentials', false);
  document.getElementById('admin-content').innerHTML = `
    <section class="admin-section admin-account-settings">
      <div class="admin-section-head"><div><h2>Change password</h2><p>Changing your password signs out this administrator session.</p></div></div>
      <form class="admin-password-form" id="admin-password-form">
        <div class="admin-field"><label for="admin-current-password">Current password</label><input class="input" id="admin-current-password" type="password" autocomplete="current-password" required></div>
        <div class="admin-field"><label for="admin-new-password">New password</label><input class="input" id="admin-new-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></div>
        <div class="admin-field"><label for="admin-confirm-password">Confirm new password</label><input class="input" id="admin-confirm-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></div>
        <div class="admin-password-actions">
          <div id="admin-password-error" class="admin-form-error" role="alert"></div>
          <button class="btn btn-primary" type="submit">Change password</button>
        </div>
      </form>
    </section>`;
  document.getElementById('admin-password-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const currentPassword = document.getElementById('admin-current-password').value;
    const newPassword = document.getElementById('admin-new-password').value;
    const confirmPassword = document.getElementById('admin-confirm-password').value;
    const errorElement = document.getElementById('admin-password-error');
    const button = event.currentTarget.querySelector('button[type="submit"]');
    errorElement.textContent = '';
    if (newPassword !== confirmPassword) {
      errorElement.textContent = 'New passwords do not match.';
      return;
    }
    button.disabled = true;
    try {
      await api('/auth/password', { method: 'POST', body: { current_password: currentPassword, new_password: newPassword } });
      state.admin = null;
      showLogin('Password changed. Sign in with your new password.');
    } catch (error) {
      const messages = {
        current_password_incorrect: 'Current password is incorrect.',
        password_unchanged: 'New password must be different from the current password.',
        password_matches_email: 'New password must not match the administrator email.',
      };
      errorElement.textContent = messages[error.message] || 'Unable to change password.';
      button.disabled = false;
    }
  });
}

function bindStatusActions(kind) {
  document.querySelectorAll(`[data-${kind}-id]`).forEach((button) => button.addEventListener('click', async () => {
    const current = button.dataset.currentStatus;
    const next = current === 'active' ? 'disabled' : 'active';
    const reason = window.prompt(`Reason to ${next === 'active' ? 'restore' : 'disable'} this ${kind}:`);
    if (!reason || reason.trim().length < 3) return;
    button.disabled = true;
    try {
      await api(`/${kind === 'user' ? 'users' : 'tenants'}/${button.dataset[`${kind}Id`]}/status`, { method: 'PATCH', body: { status: next, reason: reason.trim() } });
      toast(`${kind === 'user' ? 'User' : 'Workspace'} status updated.`);
      await renderView();
    } catch (error) {
      toast(`Update failed: ${error.message}`, true);
      button.disabled = false;
    }
  }));
}

async function renderView() {
  const content = document.getElementById('admin-content');
  if (!content) return;
  content.innerHTML = '<div class="admin-loading">Loading...</div>';
  try {
    const renderers = { overview: renderOverview, countries: renderCountries, users: renderUsers, tenants: renderTenants, subscriptions: renderSubscriptions, jobs: renderJobs, audit: renderAudit, account: renderAccount };
    await (renderers[state.view] || renderOverview)();
  } catch (error) {
    if (error.status === 401) {
      state.admin = null;
      showLogin('Your administrator session has expired.');
      return;
    }
    content.innerHTML = `<div class="admin-error">Unable to load this view: ${escapeHtml(error.message)}</div>`;
  }
}

async function boot() {
  try {
    state.admin = (await api('/me')).admin;
    const countryData = await api('/countries?days=365');
    state.countries = [...new Set(countryData.countries.map((item) => item.country_code).filter(Boolean))];
    renderShell();
    await renderView();
  } catch (_) {
    showLogin();
  }
}

window.addEventListener('hashchange', () => {
  const view = location.hash.replace(/^#\/?/, '');
  if (NAV.some(([id]) => id === view) && view !== state.view) {
    state.view = view;
    state.page = 1;
    renderShell();
    renderView();
  }
});

boot();
