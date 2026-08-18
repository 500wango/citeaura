/**
 * CiteAura API 
 *  /api/v1/ ， Cookie 、401  Refresh 。
 */

let onAuthFailureCallback = null;

export function onAuthFailure(callback) {
  onAuthFailureCallback = callback;
}

let refreshPromise = null;

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CiteAura-Session': 'cookie', Accept: 'application/json' },
    })
      .then((response) => response.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

function responseField(data, key, fallback) {
  return data && Object.prototype.hasOwnProperty.call(data, key) ? data[key] : fallback;
}

function fieldRequest(promise, key, fallback) {
  return promise.then((data) => responseField(data, key, fallback));
}

async function retryLoginTransport(operation) {
  try {
    return await operation();
  } catch (error) {
    if (!error || error.error !== 'network_error') throw error;
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    return operation();
  }
}

async function request(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : endpoint.startsWith('/') ? endpoint : `/api/v1/${endpoint}`;
  const authRetried = options._authRetried === true;
  const requestOptions = { ...options };
  delete requestOptions._authRetried;
  const headers = {
    Accept: 'application/json',
    'X-CiteAura-Session': 'cookie',
    ...(requestOptions.headers || {}),
  };

  if (requestOptions.body && !(requestOptions.body instanceof FormData) && typeof requestOptions.body === 'object') {
    headers['Content-Type'] = 'application/json';
    requestOptions.body = JSON.stringify(requestOptions.body);
  }

  const fetchOptions = {
    credentials: 'include',
    ...requestOptions,
    headers,
  };

  let res;
  try {
    res = await fetch(url, fetchOptions);
  } catch (netErr) {
    const errorObj = { error: 'network_error', detail: netErr.message, status: 0 };
    throw errorObj;
  }

  //  401 
  if (res.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/refresh') && !url.includes('/auth/register')) {
    if (!authRetried && await refreshSession()) {
      return request(endpoint, { ...options, _authRetried: true });
    }
    if (onAuthFailureCallback) onAuthFailureCallback();
    throw { status: 401, error: 'session_expired', detail: 'Session expired' };
  }

  if (res.status === 204) {
    return null;
  }

  const contentType = res.headers.get('content-type') || '';
  let data;
  if (contentType.includes('application/json')) {
    data = await res.json().catch(() => ({}));
  } else {
    data = await res.text();
  }

  if (!res.ok) {
    const errorKey = (data && data.error) || (data && data.detail) || 'request_failed';
    const detail = (data && data.detail) || (typeof data === 'string' ? data : '');
    throw {
      status: res.status,
      error: typeof errorKey === 'string' ? errorKey : 'request_failed',
      detail: typeof detail === 'string' ? detail : JSON.stringify(detail),
      data,
    };
  }

  return data;
}

/* ==========================================================================
   Auth 
   ========================================================================== */
export const auth = {
  register: (body) => request('/api/v1/auth/register', { method: 'POST', body }),
  login: (body) => retryLoginTransport(() => request('/api/v1/auth/login', { method: 'POST', body })),
  refresh: () => request('/api/v1/auth/refresh', { method: 'POST' }),
  logout: () => request('/api/v1/auth/logout', { method: 'POST' }),
  getMe: () => request('/api/v1/me'),
  forgotPassword: (body) => request('/api/v1/auth/password/forgot', { method: 'POST', body }),
  resetPassword: (body) => request('/api/v1/auth/password/reset', { method: 'POST', body }),
  switchTenant: (body) => request('/api/v1/auth/switch-tenant', { method: 'POST', body }),
  getInvitationPreview: (token) => request(`/api/v1/team/invitations/preview/${encodeURIComponent(token)}`),
  acceptInvitation: (body) => request('/api/v1/team/invitations/accept', { method: 'POST', body }),
};

/* ==========================================================================
   Projects 
   ========================================================================== */
export const projects = {
  list: () => request('/api/v1/projects'),
  create: (body) => request('/api/v1/projects', { method: 'POST', body }),
  preflight: (body) => request('/api/v1/projects/preflight', { method: 'POST', body }),
  get: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}`).then((data) => ({
    ...data,
    ...(data.project || {}),
    name: (data.brand && data.brand.name) || (data.project && data.project.slug),
  })),
  delete: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getStatus: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/status`),
  getActions: () => request('/api/v1/projects/actions'),
  triggerAction: (id, action, body = {}) =>
    request(`/api/v1/projects/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`, { method: 'POST', body }),

  getJobs: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/jobs`), 'jobs', []),
  getJob: (id, jobId, offset) =>
    fieldRequest(
      request(`/api/v1/projects/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}${offset !== undefined && offset !== null ? `?offset=${offset}` : ''}`),
      'job',
      null,
    ),
  retryJob: (id, jobId) => request(`/api/v1/projects/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' }),

  getSchedule: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/schedule`), 'schedule', {}),
  updateSchedule: (id, body) => fieldRequest(
    request(`/api/v1/projects/${encodeURIComponent(id)}/schedule`, {
      method: 'POST',
      body: {
        interval_days: body.enabled === false ? 0 : body.interval_days,
        alert_on_regression: body.alert_on_regression,
      },
    }),
    'schedule',
    {},
  ),

  getFunding: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-funding`),
  updateFunding: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-funding`, { method: 'PUT', body }),

  getBudget: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-budget`),
  updateBudget: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-budget`, { method: 'PUT', body }),

  estimateSample: (id, body = {}) => request(`/api/v1/projects/${encodeURIComponent(id)}/sample/estimate`, { method: 'POST', body }),
  triggerSample: (id, body = {}) => request(`/api/v1/projects/${encodeURIComponent(id)}/sample`, { method: 'POST', body }),

  getReport: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/report`).then((data) => (
    data && data.report ? { ...data.report, report_quality: data.report_quality, date: data.date,
      sample_artifact: data.sample_artifact } : null
  )),
  getEngines: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/engines`),
  getFraming: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/framing`), 'framing', null),
  getSamples: (id, date) => request(`/api/v1/projects/${encodeURIComponent(id)}/samples/${encodeURIComponent(date)}`),

  getTickets: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`), 'tickets', []),
  getPlaybook: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/playbook`),
  createTicket: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`, { method: 'POST', body }),
  patchTicketsBulk: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`, { method: 'PATCH', body }),
  getTicketTimeline: (id, tid) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets/${encodeURIComponent(tid)}/timeline`),
  patchTicket: (id, tid, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets/${encodeURIComponent(tid)}`, { method: 'PATCH', body }),

  triggerVerify: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/verify`, { method: 'POST' }),
  getVerifyHistory: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/verify/history`), 'history', []),

  triggerDeliver: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/deliver`, { method: 'POST' }),
  getDeliveries: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/deliveries`).then((data) => {
    if (data && Array.isArray(data.packages)) return data.packages;
    return (responseField(data, 'deliveries', []) || []).map((item) => (
      typeof item === 'string' ? { date: item, readiness: 'unknown', asset_summary: {} } : item
    ));
  }),
  getDeliveryDownloadUrl: (id, date) => `/api/v1/projects/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(date)}`,
  sendDeliveryPack: (id, date, body = {}) =>
    request(`/api/v1/projects/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(date)}/send`, {
      method: 'POST',
      body,
    }),
};

/* ==========================================================================
   Workspace 
   ========================================================================== */
export const workspace = {
  getConfig: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/config`),
  getQuestions: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/questions`), 'questions', []),
  patchConfig: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/config`, { method: 'PATCH', body }),
  getFacts: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/facts`),
  saveFacts: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/facts`, { method: 'PUT', body }),
  getAssets: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/assets`),
  getAsset: (id, path) => request(`/api/v1/projects/${encodeURIComponent(id)}/asset?path=${encodeURIComponent(path)}`),
  saveAsset: (id, path, text) => request(`/api/v1/projects/${encodeURIComponent(id)}/asset`, { method: 'PUT', body: { path, text } }),
  getWorkbench: (id, qid = '') => request(`/api/v1/projects/${encodeURIComponent(id)}/workbench${qid ? `?qid=${encodeURIComponent(qid)}` : ''}`),
  saveFactcheck: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/factcheck`, { method: 'PUT', body }),
  saveDistribution: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/distribution`, { method: 'PUT', body }),
  getContent: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/content`),
  saveContent: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/content`, { method: 'PUT', body }),
  getExpand: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/expand`),
  addQuestions: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/questions`, { method: 'POST', body }),
  updateQuestion: (id, questionId, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/questions/${encodeURIComponent(questionId)}`, { method: 'PATCH', body }),
  deleteQuestion: (id, questionId) => request(`/api/v1/projects/${encodeURIComponent(id)}/questions/${encodeURIComponent(questionId)}`, { method: 'DELETE' }),
  getBlueprint: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/blueprint`), 'blueprint', {}),
  getFiles: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/files`),
  importSamples: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/samples/import`, { method: 'POST', body }),
  importProductSurface: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/samples/product-surface`, { method: 'POST', body }),
};

/* ==========================================================================
   Settings API Keys
   ========================================================================== */
export const settings = {
  getKeys: () => fieldRequest(request('/api/v1/settings/keys'), 'keys', []),
  saveKey: (engineCode, keyValue) => request('/api/v1/settings/keys', { method: 'PUT', body: { engine_code: engineCode, key_value: keyValue } }),
  deleteKey: (engineCode) => request(`/api/v1/settings/keys/${encodeURIComponent(engineCode)}`, { method: 'DELETE' }),
  testKey: (engineCode, keyValue = '') => request(`/api/v1/settings/keys/${encodeURIComponent(engineCode)}/test`, { method: 'POST', body: { key_value: keyValue } }),
  getCustomProviders: () => fieldRequest(request('/api/v1/settings/keys/custom'), 'providers', []),
  testCustomProvider: (body) => request('/api/v1/settings/keys/custom/test', { method: 'POST', body }),
  saveCustomProvider: (body) => request('/api/v1/settings/keys/custom', { method: 'PUT', body }),
  deleteCustomProvider: (code) => request(`/api/v1/settings/keys/custom/${encodeURIComponent(code)}`, { method: 'DELETE' }),
};

/* ==========================================================================
   Branding 
   ========================================================================== */
export const branding = {
  get: () => request('/api/v1/settings/delivery-branding').then((data) => ({
    ...(data.branding || {}),
    available: Boolean(data.available),
    can_edit: Boolean(data.can_edit),
    plan: data.plan,
  })),
  save: (body) => request('/api/v1/settings/delivery-branding', { method: 'PUT', body }),
  delete: () => request('/api/v1/settings/delivery-branding', { method: 'DELETE' }),
};

/* ==========================================================================
   Publishing 
   ========================================================================== */
export const publishing = {
  get: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing`),
  save: (id, platform, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing/${encodeURIComponent(platform)}`, { method: 'PUT', body }),
  publish: (id, platform, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing/${encodeURIComponent(platform)}`, { method: 'POST', body }),
};

/* ==========================================================================
   Outreach 
   ========================================================================== */
export const outreach = {
  get: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach`),
  saveSmtp: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach/smtp`, { method: 'PUT', body }),
  deleteSmtp: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach/smtp`, { method: 'DELETE' }),
  createDraft: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach/drafts`, { method: 'POST', body }),
  updateDraft: (id, draftId, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach/drafts/${encodeURIComponent(draftId)}`, { method: 'PUT', body }),
  sendDraft: (id, draftId, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/outreach/drafts/${encodeURIComponent(draftId)}/send`, { method: 'POST', body }),
};

/* ==========================================================================
   Team 
   ========================================================================== */
export const team = {
  getMembers: () => fieldRequest(request('/api/v1/team/members'), 'members', []),
  getInvitations: () => fieldRequest(request('/api/v1/team/invitations'), 'invitations', []),
  createInvitation: (body) => request('/api/v1/team/invitations', { method: 'POST', body }),
  revokeInvitation: (id) => request(`/api/v1/team/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateMemberRole: (userId, role) => request(`/api/v1/team/members/${encodeURIComponent(userId)}`, { method: 'PATCH', body: { role } }),
  removeMember: (userId) => request(`/api/v1/team/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
};

/* ==========================================================================
   Billing 
   ========================================================================== */
export const billing = {
  getUsage: () => request('/api/v1/billing/usage'),
  getPlans: () => request('/api/v1/billing/plans'),
  getPlatformPool: () => request('/api/v1/billing/platform-pool'),
  subscribe: (body) => request('/api/v1/billing/subscribe', { method: 'POST', body }),
  cancel: () => request('/api/v1/billing/cancel', { method: 'POST' }),
};

/* ==========================================================================
   SSO & Security 
   ========================================================================== */
export const sso = {
  getConfig: () => request('/api/v1/sso/config'),
  saveConfig: (body) => request('/api/v1/sso/config', { method: 'PUT', body }),
  deleteConfig: () => request('/api/v1/sso/config', { method: 'DELETE' }),
  getAuditEvents: () => fieldRequest(request('/api/v1/sso/audit-events'), 'events', []),
};

/* ==========================================================================
   Archive 
   ========================================================================== */
export const archive = {
  list: (id) => fieldRequest(request(`/api/v1/projects/${encodeURIComponent(id)}/archives`), 'archives', []),
  create: (id, note = '') => request(`/api/v1/projects/${encodeURIComponent(id)}/archives`, { method: 'POST', body: { note } }),
  restore: (id, archiveId, confirmationText) =>
    request(`/api/v1/projects/${encodeURIComponent(id)}/archives/${encodeURIComponent(archiveId)}/restore`, {
      method: 'POST',
      body: { confirmation_text: confirmationText, confirmed: true, overwrite: true },
    }),
};

export default {
  auth,
  projects,
  workspace,
  settings,
  branding,
  publishing,
  outreach,
  team,
  billing,
  sso,
  archive,
};
