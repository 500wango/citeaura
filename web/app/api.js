/**
 * CiteAura API 客户端
 * 封装 /api/v1/ 端点，处理 Cookie 会话、401 自动 Refresh 重试与错误规整。
 */

let onAuthFailureCallback = null;

export function onAuthFailure(callback) {
  onAuthFailureCallback = callback;
}

let isRefreshing = false;
let refreshSubscribers = [];

function subscribeTokenRefresh(cb) {
  refreshSubscribers.push(cb);
}

function onRefreshed(success) {
  refreshSubscribers.forEach((cb) => cb(success));
  refreshSubscribers = [];
}

async function request(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : endpoint.startsWith('/') ? endpoint : `/api/v1/${endpoint}`;
  const headers = {
    Accept: 'application/json',
    'X-CiteAura-Session': '1',
    ...(options.headers || {}),
  };

  if (options.body && !(options.body instanceof FormData) && typeof options.body === 'object') {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }

  const fetchOptions = {
    credentials: 'include',
    ...options,
    headers,
  };

  let res;
  try {
    res = await fetch(url, fetchOptions);
  } catch (netErr) {
    const errorObj = { error: 'network_error', detail: netErr.message, status: 0 };
    throw errorObj;
  }

  // 处理 401 刷新
  if (res.status === 401 && !url.includes('/auth/login') && !url.includes('/auth/refresh') && !url.includes('/auth/register')) {
    if (!isRefreshing) {
      isRefreshing = true;
      try {
        const refreshRes = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          credentials: 'include',
          headers: { 'X-CiteAura-Session': '1', Accept: 'application/json' },
        });
        if (refreshRes.ok) {
          isRefreshing = false;
          onRefreshed(true);
        } else {
          isRefreshing = false;
          onRefreshed(false);
          if (onAuthFailureCallback) onAuthFailureCallback();
          const errData = await refreshRes.json().catch(() => ({}));
          throw { status: 401, error: errData.error || 'unauthorized', detail: errData.detail };
        }
      } catch (err) {
        isRefreshing = false;
        onRefreshed(false);
        if (onAuthFailureCallback) onAuthFailureCallback();
        throw { status: 401, error: 'session_expired', detail: 'Session expired' };
      }
    }

    // 等待刷新结果并重试
    const retrySuccess = await new Promise((resolve) => subscribeTokenRefresh(resolve));
    if (retrySuccess) {
      return request(endpoint, options);
    } else {
      throw { status: 401, error: 'unauthorized', detail: 'Authentication required' };
    }
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
   Auth 认证
   ========================================================================== */
export const auth = {
  register: (body) => request('/api/v1/auth/register', { method: 'POST', body }),
  login: (body) => request('/api/v1/auth/login', { method: 'POST', body }),
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
   Projects 项目与管线
   ========================================================================== */
export const projects = {
  list: () => request('/api/v1/projects'),
  create: (body) => request('/api/v1/projects', { method: 'POST', body }),
  preflight: (body) => request('/api/v1/projects/preflight', { method: 'POST', body }),
  get: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}`),
  delete: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getStatus: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/status`),
  getActions: () => request('/api/v1/projects/actions'),
  triggerAction: (id, action, body = {}) =>
    request(`/api/v1/projects/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`, { method: 'POST', body }),

  getJobs: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/jobs`),
  getJob: (id, jobId) => request(`/api/v1/projects/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}`),
  retryJob: (id, jobId) => request(`/api/v1/projects/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' }),

  getSchedule: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/schedule`),
  updateSchedule: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/schedule`, { method: 'POST', body }),

  getFunding: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-funding`),
  updateFunding: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-funding`, { method: 'PUT', body }),

  getBudget: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-budget`),
  updateBudget: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/sampling-budget`, { method: 'PUT', body }),

  estimateSample: (id, body = {}) => request(`/api/v1/projects/${encodeURIComponent(id)}/sample/estimate`, { method: 'POST', body }),
  triggerSample: (id, body = {}) => request(`/api/v1/projects/${encodeURIComponent(id)}/sample`, { method: 'POST', body }),

  getReport: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/report`),
  getEngines: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/engines`),
  getFraming: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/framing`),
  getSamples: (id, date) => request(`/api/v1/projects/${encodeURIComponent(id)}/samples/${encodeURIComponent(date)}`),

  getTickets: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`),
  getPlaybook: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/playbook`),
  createTicket: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`, { method: 'POST', body }),
  patchTicketsBulk: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets`, { method: 'PATCH', body }),
  getTicketTimeline: (id, tid) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets/${encodeURIComponent(tid)}/timeline`),
  patchTicket: (id, tid, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/tickets/${encodeURIComponent(tid)}`, { method: 'PATCH', body }),

  triggerVerify: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/verify`, { method: 'POST' }),
  getVerifyHistory: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/verify/history`),

  triggerDeliver: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/deliver`, { method: 'POST' }),
  getDeliveries: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/deliveries`),
  getDeliveryDownloadUrl: (id, date) => `/api/v1/projects/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(date)}`,
};

/* ==========================================================================
   Workspace 工作区产物与事实库
   ========================================================================== */
export const workspace = {
  getConfig: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/config`),
  patchConfig: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/config`, { method: 'PATCH', body }),
  getFacts: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/facts`),
  saveFacts: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/facts`, { method: 'PUT', body }),
  getAssets: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/assets`),
  getAsset: (id, name) => request(`/api/v1/projects/${encodeURIComponent(id)}/asset?name=${encodeURIComponent(name)}`),
  saveAsset: (id, name, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/asset?name=${encodeURIComponent(name)}`, { method: 'PUT', body }),
  getWorkbench: (id, qid = '') => request(`/api/v1/projects/${encodeURIComponent(id)}/workbench${qid ? `?qid=${encodeURIComponent(qid)}` : ''}`),
  saveFactcheck: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/factcheck`, { method: 'PUT', body }),
  saveDistribution: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/distribution`, { method: 'PUT', body }),
  getContent: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/content`),
  saveContent: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/content`, { method: 'PUT', body }),
  getExpand: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/expand`),
  addQuestions: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/questions`, { method: 'POST', body }),
  getFiles: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/files`),
  importSamples: (id, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/samples/import`, { method: 'POST', body }),
};

/* ==========================================================================
   Settings API Keys
   ========================================================================== */
export const settings = {
  getKeys: () => request('/api/v1/settings/keys'),
  saveKey: (engineCode, keyValue) => request('/api/v1/settings/keys', { method: 'PUT', body: { engine_code: engineCode, key_value: keyValue } }),
  deleteKey: (engineCode) => request(`/api/v1/settings/keys/${encodeURIComponent(engineCode)}`, { method: 'DELETE' }),
  testKey: (engineCode, keyValue = '') => request(`/api/v1/settings/keys/${encodeURIComponent(engineCode)}/test`, { method: 'POST', body: { key_value: keyValue } }),
};

/* ==========================================================================
   Branding 白标设置
   ========================================================================== */
export const branding = {
  get: () => request('/api/v1/settings/delivery-branding'),
  save: (body) => request('/api/v1/settings/delivery-branding', { method: 'PUT', body }),
  delete: () => request('/api/v1/settings/delivery-branding', { method: 'DELETE' }),
};

/* ==========================================================================
   Publishing 发布渠道
   ========================================================================== */
export const publishing = {
  get: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing`),
  save: (id, platform, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing/${encodeURIComponent(platform)}`, { method: 'PUT', body }),
  publish: (id, platform, body) => request(`/api/v1/projects/${encodeURIComponent(id)}/publishing/${encodeURIComponent(platform)}`, { method: 'POST', body }),
};

/* ==========================================================================
   Outreach 协作外联
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
   Integrations 外部集成
   ========================================================================== */
export const integrations = {
  list: () => request('/api/v1/integrations'),
  saveSemrush: (body) => request('/api/v1/integrations/semrush', { method: 'PUT', body }),
  delete: (provider) => request(`/api/v1/integrations/${encodeURIComponent(provider)}`, { method: 'DELETE' }),
  getProjectIntegrations: (id) => request(`/api/v1/integrations/projects/${encodeURIComponent(id)}/integrations`),
  sync: (id, provider) => request(`/api/v1/integrations/projects/${encodeURIComponent(id)}/integrations/${encodeURIComponent(provider)}/sync`, { method: 'POST' }),
};

/* ==========================================================================
   Team 团队成员
   ========================================================================== */
export const team = {
  getMembers: () => request('/api/v1/team/members'),
  getInvitations: () => request('/api/v1/team/invitations'),
  createInvitation: (body) => request('/api/v1/team/invitations', { method: 'POST', body }),
  revokeInvitation: (id) => request(`/api/v1/team/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateMemberRole: (userId, role) => request(`/api/v1/team/members/${encodeURIComponent(userId)}`, { method: 'PATCH', body: { role } }),
  removeMember: (userId) => request(`/api/v1/team/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
};

/* ==========================================================================
   Billing 计费与订阅
   ========================================================================== */
export const billing = {
  getUsage: () => request('/api/v1/billing/usage'),
  getPlans: () => request('/api/v1/billing/plans'),
  getPlatformPool: () => request('/api/v1/billing/platform-pool'),
  subscribe: (body) => request('/api/v1/billing/subscribe', { method: 'POST', body }),
  cancel: () => request('/api/v1/billing/cancel', { method: 'POST' }),
};

/* ==========================================================================
   SSO & Security 企业安全
   ========================================================================== */
export const sso = {
  getConfig: () => request('/api/v1/sso/config'),
  saveConfig: (body) => request('/api/v1/sso/config', { method: 'PUT', body }),
  deleteConfig: () => request('/api/v1/sso/config', { method: 'DELETE' }),
  getAuditEvents: () => request('/api/v1/sso/audit-events'),
};

/* ==========================================================================
   Archive 备份归档
   ========================================================================== */
export const archive = {
  list: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/archives`),
  create: (id, note = '') => request(`/api/v1/projects/${encodeURIComponent(id)}/archives`, { method: 'POST', body: { note } }),
  restore: (id, archiveId, confirmationText) =>
    request(`/api/v1/projects/${encodeURIComponent(id)}/archives/${encodeURIComponent(archiveId)}/restore`, {
      method: 'POST',
      body: { confirmation_text: confirmationText },
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
  integrations,
  team,
  billing,
  sso,
  archive,
};
