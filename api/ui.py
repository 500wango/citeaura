"""现有 engine UI 的 SaaS 适配和静态文件服务。"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from api.adapters import engine as engine_adapter
from api.auth.deps import get_current_user
from api.db import get_db
from api.models import Project, Tenant, User


router = APIRouter(tags=["ui"])
UI_PATH = Path(__file__).resolve().parents[1] / "engine" / "scripts" / "ui.html"

SETTINGS_RESPONSIVE_STYLE = r"""
.playbook-page{padding:32px 44px 72px;max-width:1280px}
.playbook-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:0 0 12px}
.playbook-view-switch{flex:none}
.playbook-view-button{border:0;background:transparent;color:var(--t500);font:500 12.5px/1 var(--font);padding:7px 12px;cursor:pointer}
.playbook-view-button+.playbook-view-button{border-left:1px solid var(--divider)}
.playbook-view-button:hover{background:rgba(233,233,237,.07);color:var(--text)}
.playbook-view-button:active{transform:translateY(1px)}
.playbook-view-button.on{background:var(--a900);color:var(--a300)}
.playbook-matrix-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain;padding-bottom:4px}
.playbook-matrix{display:grid;grid-template-columns:104px repeat(3,minmax(218px,1fr));min-width:790px;border-top:1px solid var(--divider);border-left:1px solid var(--divider);background:var(--side)}
.playbook-matrix>div{min-width:0;border-right:1px solid var(--divider);border-bottom:1px solid var(--divider)}
.playbook-axis{display:flex;flex-direction:column;justify-content:center;min-height:58px;padding:9px 11px;background:var(--deep)}
.playbook-axis strong{font-size:12px;font-weight:500;color:var(--text)}
.playbook-axis span{font-size:10.5px;color:var(--t600);margin-top:1px}
.playbook-cell{min-height:132px;padding:8px;background:var(--bg)}
.playbook-task{display:block;width:100%;padding:9px 10px;text-align:left;color:var(--text);background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);cursor:pointer;font:inherit}
.playbook-task+.playbook-task{margin-top:7px}
.playbook-task:hover{border-color:var(--a700);background:var(--a900)}
.playbook-task:active{transform:translateY(1px)}
.playbook-task.is-complete{opacity:.52}
.playbook-task-top{display:flex;align-items:center;gap:6px;color:var(--t600);font-size:10.5px}
.playbook-task-top span:first-child{flex:1;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.playbook-task-title{display:block;margin-top:3px;font-size:12.5px;line-height:1.4;overflow-wrap:anywhere}
.playbook-task-meta{display:block;margin-top:5px;font-size:10.5px;color:var(--t500);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.playbook-empty{display:grid;place-items:center;min-height:116px;padding:18px;color:var(--t600);font-size:12px;text-align:center}
.playbook-unclassified{margin-top:12px;padding:11px 12px;border:1px solid var(--divider);border-radius:var(--r-md)}
.playbook-unclassified-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:7px;margin-top:8px}
.playbook-unclassified-list .playbook-task{margin-top:0}
.sso-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.sso-audit-row{display:grid;grid-template-columns:minmax(128px,.7fr) minmax(180px,1fr) minmax(160px,1.4fr) auto;gap:10px;align-items:center;padding:8px 0;box-shadow:inset 0 -1px 0 var(--line);font-size:12px}
.integration-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
@media (max-width:700px){
  .settings-core-grid{grid-template-columns:1fr!important}
  .sso-form-grid{grid-template-columns:1fr}
  .sso-audit-row{grid-template-columns:1fr auto;gap:3px 8px}
  .sso-audit-target{grid-column:1/-1}
  .sso-section-title{padding-left:20px;scroll-margin-top:12px}
  .integration-section-title{padding-left:20px;scroll-margin-top:12px}
  .outreach-section-title{padding-left:20px;scroll-margin-top:12px}
  .settings-section-subtitle{padding-left:20px}
  .outreach-smtp-grid,.outreach-identity-grid{grid-template-columns:1fr!important}
  .integration-grid{grid-template-columns:1fr}
  .playbook-page{padding:24px 18px 56px}
  .playbook-page-head{align-items:flex-start!important;flex-direction:column}
  .playbook-stats{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .playbook-toolbar{align-items:flex-start;flex-direction:column}
}
"""


FETCH_ADAPTER = r"""
<script>
(function () {
  const rawFetch = window.fetch.bind(window);
  const projectIds = new Map();
  let loginShown = false;
  let configuredKeyCount = 0;
  let refreshRequest = null;
  const invitationToken = new URLSearchParams(location.search).get('invite') || '';
  const keyCatalog = [
    {code:'glm', label:'智谱GLM', market:'cn', env:'ZHIPUAI_API_KEY', search:false},
    {code:'doubao', label:'豆包(方舟API)', market:'cn', env:'ARK_API_KEY', search:true},
    {code:'deepseek', label:'DeepSeek', market:'cn', env:'DEEPSEEK_API_KEY', search:false},
    {code:'kimi', label:'Kimi', market:'cn', env:'MOONSHOT_API_KEY', search:false},
    {code:'minimax', label:'MiniMax', market:'cn', env:'MINIMAX_API_KEY', search:false},
    {code:'gemini', label:'Gemini', market:'global', env:'GEMINI_API_KEY', search:false},
    {code:'openai', label:'OpenAI(ChatGPT)', market:'global', env:'OPENAI_API_KEY', search:false},
    {code:'claude', label:'Claude', market:'global', env:'ANTHROPIC_API_KEY', search:false},
    {code:'grok', label:'Grok', market:'global', env:'XAI_API_KEY', search:false},
    {code:'perplexity', label:'Perplexity', market:'global', env:'PERPLEXITY_API_KEY', search:true},
    {code:'nano_ai', label:'纳米AI搜索（360）', market:'cn', env:null, search:true, manual:true},
    {code:'baidu', label:'百度 AI 搜索', market:'cn', env:null, search:true, manual:true},
    {code:'doubao_app', label:'豆包 App / 网页版', market:'cn', env:null, search:true, manual:true},
    {code:'chatgpt', label:'ChatGPT 网页版（开 Search）', market:'global', env:null, search:true, manual:true},
    {code:'claude_web', label:'Claude 网页版（开 Web Search）', market:'global', env:null, search:true, manual:true}
  ];
  const envToCode = Object.fromEntries(keyCatalog.filter(function (k) { return k.env; }).map(function (k) { return [k.env, k.code]; }));
  const publisherEnvToCode = {
    GITHUB_TOKEN:'github',
    WP_USER:'wordpress',
    WP_APP_PASSWORD:'wordpress',
    WECHAT_APPID:'wechat_draft',
    WECHAT_APPSECRET:'wechat_draft',
    PUBLISH_WEBHOOK_URL:'webhook'
  };

  async function refreshAccessToken() {
    if (!refreshRequest) {
      refreshRequest = (async function () {
        const result = await rawFetch('/api/v1/auth/refresh', {method:'POST'});
        if (!result.ok) return null;
        const data = await result.json();
        if (!data.access_token) return null;
        localStorage.setItem('disvorai_access_token', data.access_token);
        return data.access_token;
      })();
    }
    try { return await refreshRequest; }
    finally { refreshRequest = null; }
  }

  async function nativeFetch(input, init) {
    const result = await rawFetch(input, init);
    const url = typeof input === 'string' ? input : input.url;
    if (result.status !== 401 || url.startsWith('/api/v1/auth/')) return result;
    const token = await refreshAccessToken();
    if (!token) {
      localStorage.removeItem('disvorai_access_token');
      showLogin();
      return result;
    }
    const retry = Object.assign({}, init || {});
    retry.headers = Object.assign({}, retry.headers || {}, {Authorization:'Bearer ' + token});
    return rawFetch(input, retry);
  }

  function response(data, status) {
    return new Response(JSON.stringify(data), {
      status: status || 200,
      headers: {'Content-Type': 'application/json'}
    });
  }

  function legacyJob(job) {
    if (!job) return null;
    const labels = {bootstrap:'Bootstrap',sample:'Sample',verify:'Verify',deliver:'Deliver',cycle:'Cycle'};
    return Object.assign({}, job, {
      status:job.status === 'queued' ? 'running' : job.status,
      label:labels[job.action] || job.action || 'Job'
    });
  }

  async function projects() {
    if (projectIds.size) return;
    const token = localStorage.getItem('disvorai_access_token');
    const r = await nativeFetch('/api/v1/projects', {headers: {Authorization: 'Bearer ' + token}});
    if (!r.ok) return;
    const data = await r.json();
    (data.projects || []).forEach(function (p) { projectIds.set(p.slug, p.id); });
  }

  function showLogin() {
    if (loginShown || localStorage.getItem('disvorai_access_token')) return;
    loginShown = true;
    const box = document.createElement('div');
    box.id = 'disvorai-login';
    box.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#161826;display:grid;place-items:center;font:15px system-ui;color:#e9e9ed';
    box.innerHTML = '<form style="width:min(360px,calc(100% - 40px));padding:28px;background:#232532;border-radius:8px;box-shadow:0 6px 18px #0008">' +
      '<h2 style="margin:0 0 8px;color:#e9e9ed">DisvorAI</h2><p style="color:#b2b6ca;margin:0 0 18px">' + (invitationToken ? 'Accept workspace invitation' : 'Sign in or create your workspace') + '</p>' +
      '<label>Email<input name="email" type="email" required style="display:block;width:100%;margin:5px 0 12px;padding:9px;background:#1b1d2b;color:#e9e9ed;border:1px solid #595d6c;border-radius:6px"></label>' +
      '<label>Password<input name="password" type="password" minlength="8" required style="display:block;width:100%;margin:5px 0 16px;padding:9px;background:#1b1d2b;color:#e9e9ed;border:1px solid #595d6c;border-radius:6px"></label>' +
      '<button style="width:100%;padding:9px;background:#9184d9;color:#161826;border:0;border-radius:6px;cursor:pointer">Continue</button>' +
      '<p data-error style="color:#e88;margin:12px 0 0"></p></form>';
    document.body.appendChild(box);
    box.querySelector('form').addEventListener('submit', async function (event) {
      event.preventDefault();
      const email = this.email.value, password = this.password.value;
      const options = {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email:email,password:password})};
      let r = await nativeFetch('/api/v1/auth/login', options);
      if (!r.ok) {
        const registration = {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
          email:email,password:password,invitation_token:invitationToken || null
        })};
        await nativeFetch('/api/v1/auth/register', registration);
        r = await nativeFetch('/api/v1/auth/login', options);
      }
      if (!r.ok) { this.querySelector('[data-error]').textContent = 'Unable to sign in with these credentials.'; return; }
      let data = await r.json();
      if (invitationToken) {
        const accepted = await nativeFetch('/api/v1/team/invitations/accept', {
          method:'POST', headers:{'Content-Type':'application/json',Authorization:'Bearer ' + data.access_token},
          body:JSON.stringify({token:invitationToken})
        });
        if (!accepted.ok) { this.querySelector('[data-error]').textContent = 'Unable to accept this invitation.'; return; }
        data = await accepted.json();
      }
      localStorage.setItem('disvorai_access_token', data.access_token);
      if (invitationToken) history.replaceState({}, '', location.pathname + location.hash);
      location.reload();
    });
  }

  window.fetch = async function (input, init) {
    let url = typeof input === 'string' ? input : input.url;
    const token = localStorage.getItem('disvorai_access_token');
    if (url.startsWith('/files/')) {
      if (!token) { showLogin(); return response({error:'authentication_required'}, 401); }
      init = init || {};
      init.headers = Object.assign({}, init.headers || {}, {Authorization:'Bearer ' + token});
      return nativeFetch(input, init);
    }
    if (!url.startsWith('/api/') || url.startsWith('/api/v1/')) return nativeFetch(input, init);
    if (!token) { showLogin(); return response({error:'authentication_required'}, 401); }
    init = init || {};
    init.headers = Object.assign({}, init.headers || {}, {Authorization:'Bearer ' + token});
    await projects();
    const match = url.match(/^\/api\/p\/([^?]+)/);
    if (match) {
      const id = projectIds.get(decodeURIComponent(match[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      const r = await nativeFetch('/api/v1/projects/' + id, init), data = await r.json();
      if (r.ok) {
        const er = await nativeFetch('/api/v1/projects/' + id + '/engines', init);
        if (er.ok) {
          const engineData = await er.json();
          data.analytics = data.analytics || {};
          data.analytics.engines = engineData.engines || [];
        }
        const framingResponse = await nativeFetch('/api/v1/projects/' + id + '/framing', init);
        if (framingResponse.ok) {
          const framingData = await framingResponse.json();
          data.framing = framingData.framing || {};
        } else {
          data.framing = {status:'error'};
        }
      }
      return response(data, r.status);
    }
    const configMatch = url.match(/^\/api\/config\/([^?]+)/);
    if (configMatch) {
      const id = projectIds.get(decodeURIComponent(configMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      if (init.body) {
        const updates = JSON.parse(init.body);
        if (Object.keys(updates).length === 1 && Object.prototype.hasOwnProperty.call(updates, 'monitor')) {
          const interval = Number((updates.monitor || {}).every_days || 0);
          const r = await nativeFetch('/api/v1/projects/' + id + '/schedule', {
            method:'POST', headers:init.headers, body:JSON.stringify({interval_days:interval})
          });
          const data = await r.json().catch(function () { return {}; });
          return response({ok:r.ok,schedule:data.schedule,error:data.error || data.detail}, r.status);
        }
        delete updates.monitor;
        return nativeFetch('/api/v1/projects/' + id + '/config', {
          method:'PATCH', headers:init.headers, body:JSON.stringify(updates)
        });
      }
      const configResponse = await nativeFetch('/api/v1/projects/' + id + '/config', init);
      const config = await configResponse.json().catch(function () { return {}; });
      if (!configResponse.ok) return response(config, configResponse.status);
      const scheduleResponse = await nativeFetch('/api/v1/projects/' + id + '/schedule', init);
      if (scheduleResponse.ok) {
        const scheduleData = await scheduleResponse.json();
        const schedule = scheduleData.schedule || {};
        config.monitor = schedule.enabled ? {
          every_days:schedule.interval_days,
          next_run:(schedule.next_run_at || '').slice(0, 10)
        } : {};
      }
      return response(config, configResponse.status);
    }
    const factsMatch = url.match(/^\/api\/facts\/([^?]+)/);
    if (factsMatch) {
      const id = projectIds.get(decodeURIComponent(factsMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/facts', init.body
        ? {method:'PUT',headers:init.headers,body:init.body} : init);
    }
    const assetsMatch = url.match(/^\/api\/assets\/([^?]+)/);
    if (assetsMatch) {
      const id = projectIds.get(decodeURIComponent(assetsMatch[1]));
      return id ? nativeFetch('/api/v1/projects/' + id + '/assets', init) : response({error:'project_not_found'}, 404);
    }
    const assetMatch = url.match(/^\/api\/asset\/([^?]+)/);
    if (assetMatch) {
      const id = projectIds.get(decodeURIComponent(assetMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      if (init.body) return nativeFetch('/api/v1/projects/' + id + '/asset', {method:'PUT',headers:init.headers,body:init.body});
      const path = new URL(url, location.origin).searchParams.get('path') || '';
      return nativeFetch('/api/v1/projects/' + id + '/asset?path=' + encodeURIComponent(path), init);
    }
    const workbenchMatch = url.match(/^\/api\/workbench\/([^?]+)/);
    if (workbenchMatch) {
      const id = projectIds.get(decodeURIComponent(workbenchMatch[1]));
      const qid = new URL(url, location.origin).searchParams.get('qid') || '';
      return id ? nativeFetch('/api/v1/projects/' + id + '/workbench?qid=' + encodeURIComponent(qid), init)
        : response({error:'project_not_found'}, 404);
    }
    if (url === '/api/precheck' && init.body) {
      return nativeFetch('/api/v1/workspace/precheck', init);
    }
    const factcheckMatch = url.match(/^\/api\/factcheck\/([^?]+)/);
    if (factcheckMatch) {
      const id = projectIds.get(decodeURIComponent(factcheckMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/factcheck', init.body
        ? {method:'PUT',headers:init.headers,body:init.body} : init);
    }
    const distributionMatch = url.match(/^\/api\/distribution\/([^?]+)/);
    if (distributionMatch && init.body) {
      const id = projectIds.get(decodeURIComponent(distributionMatch[1]));
      return id ? nativeFetch('/api/v1/projects/' + id + '/distribution', {method:'PUT',headers:init.headers,body:init.body})
        : response({error:'project_not_found'}, 404);
    }
    const contentMatch = url.match(/^\/api\/content\/([^?]+)/);
    if (contentMatch) {
      const id = projectIds.get(decodeURIComponent(contentMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      if (init.body) return nativeFetch('/api/v1/projects/' + id + '/content', {method:'PUT',headers:init.headers,body:init.body});
      const path = new URL(url, location.origin).searchParams.get('path');
      return nativeFetch('/api/v1/projects/' + id + '/content' + (path ? '?path=' + encodeURIComponent(path) : ''), init);
    }
    const expandMatch = url.match(/^\/api\/expand\/([^?]+)/);
    if (expandMatch) {
      const id = projectIds.get(decodeURIComponent(expandMatch[1]));
      return id ? nativeFetch('/api/v1/projects/' + id + '/expand', init) : response({error:'project_not_found'}, 404);
    }
    if (url === '/api/questions-add' && init.body) {
      const body = JSON.parse(init.body), id = projectIds.get(body.slug);
      return id ? nativeFetch('/api/v1/projects/' + id + '/questions', {
        method:'POST',headers:init.headers,body:JSON.stringify({items:body.items || []})
      }) : response({error:'project_not_found'}, 404);
    }
    if (url === '/api/team' && !init.body) {
      const membersResponse = await nativeFetch('/api/v1/team/members', init);
      const members = await membersResponse.json().catch(function () { return {}; });
      if (!membersResponse.ok) return response(members, membersResponse.status);
      const meResponse = await nativeFetch('/api/v1/me', init);
      const me = meResponse.ok ? await meResponse.json() : {};
      let invitations = [];
      if (members.current_role === 'owner') {
        const invitationsResponse = await nativeFetch('/api/v1/team/invitations', init);
        if (invitationsResponse.ok) invitations = (await invitationsResponse.json()).invitations || [];
      }
      return response(Object.assign({}, members, {invitations:invitations,workspaces:me.workspaces || []}), 200);
    }
    if (url === '/api/team/invite' && init.body) {
      return nativeFetch('/api/v1/team/invitations', {
        method:'POST', headers:init.headers, body:init.body
      });
    }
    if (url === '/api/team/member' && init.body) {
      const body = JSON.parse(init.body), target = '/api/v1/team/members/' + encodeURIComponent(body.user_id);
      return nativeFetch(target, {
        method:body.remove ? 'DELETE' : 'PATCH', headers:init.headers,
        body:body.remove ? undefined : JSON.stringify({role:body.role})
      });
    }
    if (url === '/api/team/revoke' && init.body) {
      const body = JSON.parse(init.body);
      return nativeFetch('/api/v1/team/invitations/' + encodeURIComponent(body.invitation_id), {
        method:'DELETE', headers:init.headers
      });
    }
    if (url === '/api/team/switch' && init.body) {
      return nativeFetch('/api/v1/auth/switch-tenant', {
        method:'POST', headers:init.headers, body:init.body
      });
    }
    const publishMatch = url.match(/^\/api\/publish\/([^?]+)/);
    if (publishMatch) {
      const id = projectIds.get(decodeURIComponent(publishMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      if (!init.body) return nativeFetch('/api/v1/projects/' + id + '/publishing', init);
      const body = JSON.parse(init.body), platform = String(body.platform || '');
      return nativeFetch('/api/v1/projects/' + id + '/publishing/' + encodeURIComponent(platform), {
        method:'POST', headers:init.headers, body:JSON.stringify({
          path:body.path, title:body.title || '', confirmed:true
        })
      });
    }
    const publishConfigMatch = url.match(/^\/api\/publishcfg\/([^?]+)/);
    if (publishConfigMatch && init.body) {
      const id = projectIds.get(decodeURIComponent(publishConfigMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      const body = JSON.parse(init.body), platform = String(body.platform || '');
      return nativeFetch('/api/v1/projects/' + id + '/publishing/' + encodeURIComponent(platform), {
        method:'PUT', headers:init.headers, body:JSON.stringify({config:body.cfg || {}})
      });
    }
    if (url === '/api/projects') {
      const r = await nativeFetch('/api/v1/projects', init);
      if (r.status === 401) { localStorage.removeItem('disvorai_access_token'); showLogin(); }
      const data = await r.json();
      return response((data.projects || []).map(function (p) {
        return Object.assign({}, p, {name:p.name || p.slug,site:p.site || p.url});
      }), r.status);
    }
    if (url === '/api/actions') {
      const r = await nativeFetch('/api/v1/projects/actions', init), data = await r.json();
      return response(data.actions || {}, r.status);
    }
    if (url === '/api/init' && init.body) {
      const body = JSON.parse(init.body);
      const r = await nativeFetch('/api/v1/projects', {
        method:'POST', headers:Object.assign({}, init.headers, {'Content-Type':'application/json'}),
        body:JSON.stringify({
          url:body.url, name:body.name || null, market:body.market || 'both', skip_llm:configuredKeyCount === 0,
          no_sample:configuredKeyCount === 0 || !!document.querySelector('#ob-nosample')?.checked
        })
      });
      const data = await r.json();
      if (r.ok && data.slug) projectIds.set(data.slug, data.project_id);
      return response(r.ok ? {ok:true,slug:data.slug,job:{id:data.job_id,status:'queued',label:'Bootstrap'}} : {ok:false,error:data.error || data.detail}, r.status);
    }
    if (url.startsWith('/api/files/')) {
      const id = projectIds.get(decodeURIComponent(url.slice('/api/files/'.length)));
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/files', init);
    }
    if (url.startsWith('/api/jobs?')) {
      const slug = new URL(url, location.origin).searchParams.get('slug');
      const id = projectIds.get(slug);
      if (!id) return response({jobs:[],running:null});
      const r = await nativeFetch('/api/v1/projects/' + id + '/jobs', init);
      const data = await r.json();
      const jobs = data.jobs || [], active = jobs.find(function (j) { return j.status === 'queued' || j.status === 'running'; });
      return response({jobs:jobs.map(legacyJob),running:active ? active.id : null}, r.status);
    }
    const jobMatch = url.match(/^\/api\/job\/([^?]+)/);
    if (jobMatch) {
      const jobId = jobMatch[1];
      for (const id of projectIds.values()) {
        const requested = Math.max(0, Number(new URL(url, location.origin).searchParams.get('offset') || 0) || 0);
        const r = await nativeFetch('/api/v1/projects/' + id + '/jobs/' + jobId + '?offset=' + requested, init);
        if (r.status !== 404) {
          const data = await r.json();
          return response({job:legacyJob(data.job),log:data.job.log || '',offset:data.job.log_offset || requested}, r.status);
        }
      }
      return response({error:'job_not_found'}, 404);
    }
    if (url === '/api/keys' && !init.body) {
      const r = await nativeFetch('/api/v1/settings/keys', init), data = await r.json();
      const configured = new Map((data.keys || []).map(function (k) { return [k.engine_code, k]; }));
      configuredKeyCount = configured.size;
      return response(keyCatalog.map(function (k) {
        const current = configured.get(k.code);
        return Object.assign({}, k, {ok:k.manual ? null : !!current, key_tail:current ? current.masked.slice(-4) : ''});
      }), r.status);
    }
    if (url === '/api/keys' && init.body) {
      const updates = JSON.parse(init.body).updates || {};
      const publisherUpdates = {};
      for (const env of Object.keys(updates)) {
        const code = envToCode[env];
        if (!code) {
          const platform = publisherEnvToCode[env];
          if (!platform) return response({ok:false,error:'unsupported_key'}, 400);
          publisherUpdates[platform] = publisherUpdates[platform] || {};
          publisherUpdates[platform][env] = String(updates[env] || '').trim() || null;
          continue;
        }
        const value = String(updates[env] || '').trim();
        const r = value
          ? await nativeFetch('/api/v1/settings/keys', {method:'PUT', headers:Object.assign({}, init.headers, {'Content-Type':'application/json'}), body:JSON.stringify({engine_code:code,key_value:value})})
          : await nativeFetch('/api/v1/settings/keys/' + code, {method:'DELETE', headers:init.headers});
        if (!r.ok) { const data = await r.json().catch(function () { return {}; }); return response({ok:false,error:data.error || data.detail}, r.status); }
      }
      const id = projectIds.get(SLUG);
      for (const platform of Object.keys(publisherUpdates)) {
        if (!id) return response({ok:false,error:'project_not_found'}, 404);
        const r = await nativeFetch('/api/v1/projects/' + id + '/publishing/' + encodeURIComponent(platform), {
          method:'PUT', headers:Object.assign({}, init.headers, {'Content-Type':'application/json'}),
          body:JSON.stringify({credentials:publisherUpdates[platform]})
        });
        if (!r.ok) { const data = await r.json().catch(function () { return {}; }); return response({ok:false,error:data.error || data.detail}, r.status); }
      }
      return response({ok:true});
    }
    if (url === '/api/run' && init.body) {
      const body = JSON.parse(init.body), id = projectIds.get(body.slug), params = body.params || {};
      let action = body.action;
      if (!id) return response({error:'project_not_found'}, 404);
      if (action === 'autopilot') {
        const r = await nativeFetch('/api/v1/projects/' + id + '/jobs', {headers:init.headers}), data = await r.json();
        const job = (data.jobs || []).find(function (j) {
          return (j.action === 'bootstrap' || j.action === 'autopilot') && (j.status === 'queued' || j.status === 'running');
        });
        if (job) return response({ok:true,job:legacyJob(job)});
      }
      const payload = {method:'POST',headers:Object.assign({},init.headers,{'Content-Type':'application/json'}),body:JSON.stringify({params:params})};
      const r = await nativeFetch('/api/v1/projects/' + id + '/actions/' + encodeURIComponent(action), payload), data = await r.json();
      return response({ok:r.ok,job:r.ok ? {id:data.job_id,status:'queued',label:action} : null,error:data.error}, r.status);
    }
    if (url === '/api/task' && init.body) {
      const body = JSON.parse(init.body), id = projectIds.get(body.slug);
      if (!id) return response({error:'project_not_found'}, 404);
      const r = await nativeFetch('/api/v1/projects/' + id + '/tickets/' + encodeURIComponent(body.id), {method:'PATCH',headers:init.headers,body:JSON.stringify({status:body.status,note:body.note || ''})});
      const data = await r.json();
      return response({ok:r.ok,task:data.ticket,error:data.error || data.detail}, r.status);
    }
    if (url === '/api/task-create' && init.body) {
      const body = JSON.parse(init.body), id = projectIds.get(body.slug);
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/tickets', {
        method:'POST', headers:init.headers, body:JSON.stringify({
          url:body.url, ask_text:body.ask_text, influenced_questions:body.influenced_questions || []
        })
      });
    }
    const deliveryZipMatch = url.match(/^\/api\/delivery-zip\/([^/?]+)\/(\d{4}-\d{2}-\d{2})$/);
    if (deliveryZipMatch) {
      const id = projectIds.get(decodeURIComponent(deliveryZipMatch[1]));
      return id ? nativeFetch('/api/v1/projects/' + id + '/deliveries/' + deliveryZipMatch[2], init)
        : response({error:'project_not_found'}, 404);
    }
    if (url === '/api/sample-import' && init.body) {
      const body = JSON.parse(init.body), id = projectIds.get(body.slug);
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/samples/import', {
        method:'POST', headers:init.headers, body:JSON.stringify({file:body.file,text:body.text})
      });
    }
    if (url === '/api/delivery-branding') {
      return nativeFetch('/api/v1/settings/delivery-branding', {
        method:init.body ? 'PUT' : 'GET', headers:init.headers, body:init.body
      });
    }
    if (url === '/api/sampling-funding') {
      const id = projectIds.get(SLUG);
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/sampling-funding', {
        method:init.body ? 'PUT' : 'GET', headers:init.headers, body:init.body
      });
    }
    if (url === '/api/integrations') {
      const id = projectIds.get(SLUG);
      if (!init.body) {
        const target = id ? '/api/v1/projects/' + id + '/integrations' : '/api/v1/integrations';
        return nativeFetch(target, init);
      }
      const body = JSON.parse(init.body);
      if (body.action === 'save_semrush') {
        return nativeFetch('/api/v1/integrations/semrush', {
          method:'PUT', headers:init.headers,
          body:JSON.stringify({api_key:body.api_key,database:body.database})
        });
      }
      if (body.action === 'disconnect') {
        return nativeFetch('/api/v1/integrations/' + encodeURIComponent(body.provider), {
          method:'DELETE', headers:init.headers
        });
      }
      if (body.action === 'sync' && id) {
        return nativeFetch('/api/v1/projects/' + id + '/integrations/' + encodeURIComponent(body.provider) + '/sync', {
          method:'POST', headers:init.headers
        });
      }
      return response({error:'integration_action_invalid'}, 400);
    }
    if (url === '/api/outreach') {
      const id = projectIds.get(SLUG);
      if (!id) return response({error:'project_not_found'}, 404);
      if (!init.body) return nativeFetch('/api/v1/projects/' + id + '/outreach', init);
      const body = JSON.parse(init.body), base = '/api/v1/projects/' + id + '/outreach';
      if (body.action === 'save_smtp') return nativeFetch(base + '/smtp', {
        method:'PUT',headers:init.headers,body:JSON.stringify(body.smtp)
      });
      if (body.action === 'delete_smtp') return nativeFetch(base + '/smtp', {method:'DELETE',headers:init.headers});
      if (body.action === 'create_draft') return nativeFetch(base + '/drafts', {
        method:'POST',headers:init.headers,body:JSON.stringify({ticket_id:body.ticket_id,recipient_email:body.recipient_email})
      });
      if (body.action === 'update_draft') return nativeFetch(base + '/drafts/' + encodeURIComponent(body.draft_id), {
        method:'PUT',headers:init.headers,body:JSON.stringify(body.draft)
      });
      if (body.action === 'send') return nativeFetch(base + '/drafts/' + encodeURIComponent(body.draft_id) + '/send', {
        method:'POST',headers:init.headers,body:JSON.stringify({revision:body.revision,confirmed:body.confirmed,confirmation_text:body.confirmation_text})
      });
      return response({error:'outreach_action_invalid'}, 400);
    }
    return response({error:'legacy_ui_endpoint_not_supported'}, 404);
  };
  async function acceptPendingInvitation() {
    const token = localStorage.getItem('disvorai_access_token');
    if (!invitationToken || !token) return;
    const result = await nativeFetch('/api/v1/team/invitations/accept', {
      method:'POST', headers:{'Content-Type':'application/json',Authorization:'Bearer ' + token},
      body:JSON.stringify({token:invitationToken})
    });
    if (result.ok) {
      const data = await result.json();
      localStorage.setItem('disvorai_access_token', data.access_token);
      history.replaceState({}, '', location.pathname + location.hash);
      location.reload();
      return;
    }
    localStorage.removeItem('disvorai_access_token');
    showLogin();
  }
  if (!localStorage.getItem('disvorai_access_token')) setTimeout(showLogin, 0);
  else if (invitationToken) setTimeout(acceptPendingInvitation, 0);
})();
</script>
"""


UI_EXTENSION = r"""
<script>
async function downloadDelivery(date) {
  const result = await fetch('/api/delivery-zip/' + encodeURIComponent(SLUG) + '/' + encodeURIComponent(date));
  if (!result.ok) {
    const data = await result.json().catch(function () { return {}; });
    const detail = data.error || (data.detail && data.detail.error) || data.detail || 'delivery_download_failed';
    toast('下载失败：' + detail, 'err');
    return;
  }
  const href = URL.createObjectURL(await result.blob());
  const link = document.createElement('a');
  link.href = href;
  link.download = SLUG + '-delivery-' + date + '.zip';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

function offsiteTicketModal() {
  const questions = (D.questions || []).filter(function (question) { return !question.brand_probe; });
  modal(`<h4 style="font-size:17px">创建 Offsite 工单</h4>
    <p class="muted" style="font-size:12.5px;margin:5px 0 14px">记录需要外部页面负责人完成的具体更新；此类工单由人工验收。</p>
    <label style="display:block;font-size:12px;color:var(--t500);margin-bottom:12px">外部页面 URL
      <input id="offsite-url" class="input" type="url" placeholder="https://example.com/page" style="margin-top:5px" required></label>
    <label style="display:block;font-size:12px;color:var(--t500);margin-bottom:12px">希望对方完成什么
      <textarea id="offsite-ask" class="input" rows="4" maxlength="5000" placeholder="例如：补充品牌定义、官网链接和可核验的数据来源" style="margin-top:5px" required></textarea></label>
    <div style="font-size:12px;color:var(--t500);margin-bottom:5px">影响问题</div>
    <div style="max-height:210px;overflow:auto;border:1px solid var(--line);border-radius:var(--r-md);padding:5px 10px">
      ${questions.map(function (question) { return `<label class="row" style="gap:8px;padding:7px 0;box-shadow:inset 0 -1px 0 var(--line);font-size:12.5px;cursor:pointer">
        <input data-offsite-question type="checkbox" value="${esc(question.id)}" style="width:auto">
        <span style="flex:1">${esc(question.text)}</span><span class="muted" style="font-size:10.5px">${esc(question.id)}</span></label>`; }).join('') || '<div class="muted" style="font-size:12px;padding:8px 0">问题库为空，请先完成项目分析。</div>'}
    </div>
    <div class="row" style="justify-content:flex-end;margin-top:14px">
      <button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="createOffsiteTicket()">创建工单</button></div>`);
}

async function createOffsiteTicket() {
  const url = ($('#offsite-url') || {}).value || '';
  const askText = ($('#offsite-ask') || {}).value || '';
  const influencedQuestions = Array.from(document.querySelectorAll('[data-offsite-question]:checked')).map(function (input) { return input.value; });
  if (!url.trim() || !askText.trim() || !influencedQuestions.length) {
    toast('请填写 URL、更新诉求并选择至少一个影响问题', 'err');
    return;
  }
  const result = await post('/api/task-create', {
    slug:SLUG, url:url.trim(), ask_text:askText.trim(), influenced_questions:influencedQuestions
  });
  if (result.error) { toast('创建失败：' + result.error, 'err'); return; }
  closeModal();
  toast('Offsite 工单已创建');
  await load(SLUG, true);
}

Object.assign(UI_D.en, {
  'AI 如何描述你':'How AI describes you',
  '基于品牌被实际提及的回答短语，词频按样本去重。':'Based on phrases from answers that actually mention the brand. Counts are deduplicated per sample.',
  '暂无采样，完成一期采样后这里会显示品牌印象。':'No samples yet. Run a sampling cycle to see brand framing.',
  '本期回答没有主动提及品牌，暂无可提取的描述。':'The brand was not mentioned this round, so no framing can be extracted.',
  '本期提到了品牌，但没有匹配到明确的描述关系。':'The brand was mentioned, but no explicit descriptive phrasing was found.',
  '品牌印象加载失败，请刷新后重试。':'Brand framing failed to load. Refresh and try again.',
  '原文证据':'Source evidence'
});
Object.assign(UI_D.ja, {
  'AI 如何描述你':'AI によるブランドの説明',
  '基于品牌被实际提及的回答短语，词频按样本去重。':'ブランドが実際に言及された回答の表現を使用し、頻度はサンプル単位で重複排除します。',
  '暂无采样，完成一期采样后这里会显示品牌印象。':'サンプルはまだありません。サンプリング後にブランド表現が表示されます。',
  '本期回答没有主动提及品牌，暂无可提取的描述。':'今回はブランドへの言及がなく、抽出できる表現はありません。',
  '本期提到了品牌，但没有匹配到明确的描述关系。':'ブランドへの言及はありましたが、明確な説明表現は見つかりませんでした。',
  '品牌印象加载失败，请刷新后重试。':'ブランド表現を読み込めませんでした。更新して再試行してください。',
  '原文证据':'原文の根拠'
});

function framingPanel() {
  const framing = D.framing || {}, terms = framing.terms || [];
  const empty = {
    no_samples:'暂无采样，完成一期采样后这里会显示品牌印象。',
    brand_not_mentioned:'本期回答没有主动提及品牌，暂无可提取的描述。',
    no_descriptors:'本期提到了品牌，但没有匹配到明确的描述关系。',
    error:'品牌印象加载失败，请刷新后重试。'
  }[framing.status] || '暂无采样，完成一期采样后这里会显示品牌印象。';
  const maximum = Math.max(1, ...terms.map(function (item) { return item.count || 0; }));
  return `<section style="margin-top:24px;padding-top:22px;box-shadow:inset 0 1px 0 var(--line)">
    <h4 style="font-size:16px;margin:0 0 5px">AI 如何描述你</h4>
    <p class="muted" style="font-size:12px;margin:0 0 14px">基于品牌被实际提及的回答短语，词频按样本去重。${framing.date?` 数据 ${esc(framing.date)}，${framing.mentioned_samples||0} 条提及样本。`:''}</p>
    ${terms.length?`<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-height:88px">
      ${terms.map(function (item, index) {
        const size = 13 + Math.round(8 * (item.count || 0) / maximum);
        return `<button class="btn btn-ghost" style="max-width:100%;padding:6px 9px;font-size:${size}px;overflow-wrap:anywhere" onclick="showFramingEvidence(${index})">
          ${esc(item.term)} <span class="muted" style="font-size:10px">${item.count}</span></button>`;
      }).join('')}</div>`:`<div style="padding:16px;border:1px solid var(--line);border-radius:var(--r-md);font-size:12.5px;color:var(--t500)">${empty}</div>`}
  </section>`;
}

function showFramingEvidence(index) {
  const item = (((D.framing || {}).terms) || [])[index];
  if (!item) return;
  modal(`<h4 style="font-size:17px">${esc(item.term)}</h4>
    <p class="muted" style="font-size:12px;margin:5px 0 12px">${item.count} 条样本，${(item.engines || []).map(esc).join(' / ')}</p>
    <div style="font-size:12px;color:var(--t500);margin-bottom:5px">原文证据</div>
    ${(item.evidence || []).map(function (evidence) { return `<div style="padding:11px 0;box-shadow:inset 0 -1px 0 var(--line)">
      <div class="row" style="gap:6px;margin-bottom:5px"><span class="tag tag-outline">${esc(evidence.platform_name)}</span><span class="tag tag-neutral">${esc(evidence.sampling_mode)}</span></div>
      <div style="font-size:12px;color:var(--t500);margin-bottom:4px">${esc(evidence.question || '')}</div>
      <div style="font-size:13px;line-height:1.65;color:var(--t300)">${esc(evidence.excerpt || '')}</div></div>`; }).join('')}
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
}

function competitorDiscoveryPanel() {
  const state=D.competitor_discovery||{},items=state.items||[],summary=state.summary||{};
  const copies={
    zh:{title:'自动发现竞品',desc:'候选由项目初始化自动推导；只有在真实采样回答中出现后，才标记为采样已确认。',
      empty:'尚未发现竞品候选。重新运行项目初始化，或在设置中手动配置竞品。',candidate:'待采样确认',confirmed:'采样已确认',configured:'手动配置',aliases:'别名',
      count:function(){return `${summary.total||0} 个竞品，${summary.sample_confirmed||0} 个经采样确认`;},markets:{cn:'国内',global:'海外',both:'通用'}},
    en:{title:'Discovered competitors',desc:'Candidates are inferred during project setup. They are confirmed only after appearing in real sampled answers.',
      empty:'No competitor candidates yet. Run project setup again or configure competitors in Settings.',candidate:'Awaiting sample confirmation',confirmed:'Sample confirmed',configured:'Manually configured',aliases:'Aliases',
      count:function(){return `${summary.total||0} competitors, ${summary.sample_confirmed||0} sample confirmed`;},markets:{cn:'CN',global:'Global',both:'Both'}},
    ja:{title:'自動検出した競合',desc:'候補はプロジェクト初期化時に推定され、実際のサンプル回答に出現した場合のみ確認済みになります。',
      empty:'競合候補はまだありません。プロジェクト初期化を再実行するか、設定で競合を追加してください。',candidate:'サンプル確認待ち',confirmed:'サンプル確認済み',configured:'手動設定',aliases:'別名',
      count:function(){return `${summary.total||0} 件中 ${summary.sample_confirmed||0} 件をサンプル確認済み`;},markets:{cn:'中国',global:'海外',both:'共通'}}
  };
  const text=copies[ULANG]||copies.zh;
  const status={candidate:[text.candidate,'tag-accent'],sample_confirmed:[text.confirmed,'pill-good'],configured:[text.configured,'tag-outline']};
  return `<section style="margin-top:24px;padding-top:22px;box-shadow:inset 0 1px 0 var(--line)">
    <div class="row" style="align-items:flex-start"><div style="flex:1;min-width:220px"><h4 style="font-size:16px;margin:0 0 5px">${text.title}</h4>
      <p class="muted" style="font-size:12px;margin:0;max-width:720px">${text.desc}</p></div>
      <span style="font-size:11.5px;color:var(--t500)">${text.count()}</span></div>
    ${items.length?`<div style="margin-top:13px;border-top:1px solid var(--divider)">${items.map(function(item){const current=status[item.discovery_status]||status.configured;return `<div class="row" style="padding:9px 0;box-shadow:inset 0 -1px 0 var(--line);gap:8px">
        <span style="flex:1;min-width:180px;font-size:13px;overflow-wrap:anywhere">${esc(item.name)}${(item.aliases||[]).length?`<span style="display:block;font-size:10.5px;color:var(--t600);margin-top:1px">${text.aliases}: ${item.aliases.map(esc).join(' / ')}</span>`:''}</span>
        <span class="tag tag-dim">${esc(text.markets[item.market]||item.market||text.markets.both)}</span><span class="tag ${current[1]}">${current[0]}</span></div>`;}).join('')}</div>`
      :`<div style="margin-top:13px;padding:14px;border:1px solid var(--line);border-radius:var(--r-md);font-size:12.5px;color:var(--t500)">${text.empty}</div>`}
  </section>`;
}

const engineCompetitorsView = vCompetitors;
vCompetitors = function () {
  let html = engineCompetitorsView();
  const sampleNs=((D.analytics||{}).competitors||{}).sample_ns||{};
  if (!(Number(sampleNs.cn||0)+Number(sampleNs.global||0))) {
    const pendingTitle={zh:'竞品候选等待采样',en:'Competitor candidates await sampling',ja:'競合候補はサンプリング待ち'}[ULANG];
    html=html.replace(/<h3 style="margin-bottom:6px">[^<]*<\/h3>/,`<h3 style="margin-bottom:6px">${pendingTitle}</h3>`);
  }
  const anchor = '<div class="tabs" style="margin-top:18px">';
  return html.replace(anchor, competitorDiscoveryPanel() + framingPanel() + anchor);
};
VIEWS.competitors = vCompetitors;

Object.assign(UI_D.en, {
  '团队成员':'Team members','工作区':'Workspace','邀请成员':'Invite member','待接受邀请':'Pending invitations',
  '复制邀请链接':'Copy invitation link','撤销':'Revoke','移除':'Remove','你':'You',
  '所有者':'Owner','编辑者':'Editor','只读成员':'Viewer','邀请链接已创建':'Invitation link created',
  '团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'Team members use owner, editor, and viewer roles. Invitation links expire after 7 days.',
  '白标交付':'White-label delivery','打印 / PDF 页眉':'Print / PDF header','机构名称':'Organization name',
  '主题色':'Accent color','页脚文字':'Footer text','启用白标':'Enable white label','选择 Logo':'Choose logo',
  '移除 Logo':'Remove logo','保存白标设置':'Save branding','Agency 套餐可用':'Available on Agency plan',
  '采样费用':'Sampling costs','平台代付':'Platform-funded sampling','本月调用':'Calls this month','本月费用':'Cost this month',
  'BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台 Key 并按次计费。':'BYOK always takes priority. Platform keys are used and billed per call only when the matching API key is missing.',
  '当前套餐不可用':'Not available on the current plan','平台暂未配置可用引擎':'No platform-funded engines are currently available',
  '仅所有者可更改':'Only owners can change this setting','费用信息加载失败':'Failed to load cost information',
  '企业登录与审计':'Enterprise sign-in and audit','OIDC 单点登录':'OIDC single sign-on','身份提供商名称':'Identity provider name',
  '签发者地址':'Issuer URL','客户端 ID':'Client ID','客户端密钥':'Client secret','允许的邮箱域名':'Allowed email domains',
  '新成员默认角色':'Default role for new members','启用单点登录':'Enable single sign-on','保存企业登录设置':'Save enterprise sign-in',
  '单点登录地址':'Single sign-on URL','复制登录地址':'Copy sign-in URL','已复制登录地址':'Sign-in URL copied',
  '控制措施已就绪，未获得 SOC 2 认证。':'Technical controls are ready; DisvorAI is not SOC 2 certified.',
  '包含加密密钥、OIDC PKCE、租户权限、变更审计和浏览器安全策略。':'Includes encrypted secrets, OIDC PKCE, tenant authorization, change auditing, and browser security policies.',
  'Enterprise 套餐可用':'Available on Enterprise plan','最近审计事件':'Recent audit events','暂无审计事件':'No audit events yet',
  '保留已保存密钥':'Keep the saved secret','每行或逗号分隔':'One per line or comma-separated','企业登录设置已保存':'Enterprise sign-in settings saved',
  '企业登录设置加载失败':'Failed to load enterprise sign-in settings','仅所有者可查看审计事件':'Only owners can view audit events'
  ,'搜索数据源':'Search data sources','自然搜索与站点表现':'Organic search and site performance','连接状态':'Connection status','已连接':'Connected','未连接':'Not connected',
  '区域数据库':'Regional database','保存 Semrush':'Save Semrush','断开连接':'Disconnect','同步数据':'Sync data','连接 Search Console':'Connect Search Console',
  '最近同步':'Last synced','关键词':'Keywords','前 10 关键词':'Top 10 keywords','搜索量':'Search volume','流量成本':'Traffic cost',
  '点击':'Clicks','展示':'Impressions','点击率':'CTR','平均排名':'Average position','尚未同步':'Not synced yet',
  'Search Console OAuth 未配置':'Search Console OAuth is not configured','仅所有者可管理连接':'Only owners can manage connections',
  '数据源连接已更新':'Data source connection updated','同步任务已创建':'Sync job created','外部搜索数据加载失败':'Failed to load external search data'
  ,'外链联络':'Outreach','人工确认发送':'Human-confirmed sending','邮件服务器':'Mail server','发件邮箱':'From email','发件名称':'From name',
  '保存 SMTP':'Save SMTP','联络草稿':'Outreach drafts','暂无联络草稿':'No outreach drafts','准备联络邮件':'Prepare outreach email','收件邮箱':'Recipient email',
  '生成草稿':'Create draft','编辑草稿':'Edit draft','邮件主题':'Subject','邮件正文':'Message','保存草稿':'Save draft','检查并发送':'Review and send',
  '最终发送确认':'Final send confirmation','我已核对收件人、主题和正文':'I reviewed the recipient, subject, and message','输入确认短语':'Type confirmation phrase',
  '确认并入队':'Confirm and queue','草稿已保存':'Draft saved','发送任务已创建':'Send job created','SMTP 凭证使用 AES-256-GCM 加密保存。':'SMTP credentials are encrypted with AES-256-GCM.',
  '发送前必须检查最终内容并输入与草稿匹配的确认短语。':'Before sending, review the final content and type the confirmation phrase for this draft.',
  '待编辑':'Draft','已排队':'Queued','发送中':'Sending','已发送':'Sent','发送失败':'Failed'
});
Object.assign(UI_D.ja, {
  '团队成员':'チームメンバー','工作区':'ワークスペース','邀请成员':'メンバーを招待','待接受邀请':'保留中の招待',
  '复制邀请链接':'招待リンクをコピー','撤销':'取り消す','移除':'削除','你':'自分',
  '所有者':'オーナー','编辑者':'編集者','只读成员':'閲覧者','邀请链接已创建':'招待リンクを作成しました',
  '团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'メンバーは owner、editor、viewer のロールで管理され、招待リンクは 7 日間有効です。',
  '白标交付':'ホワイトラベル納品','打印 / PDF 页眉':'印刷 / PDF ヘッダー','机构名称':'組織名',
  '主题色':'アクセントカラー','页脚文字':'フッターテキスト','启用白标':'ホワイトラベルを有効化','选择 Logo':'ロゴを選択',
  '移除 Logo':'ロゴを削除','保存白标设置':'ブランド設定を保存','Agency 套餐可用':'Agency プランで利用可能',
  '采样费用':'サンプリング費用','平台代付':'プラットフォーム負担','本月调用':'今月の呼び出し','本月费用':'今月の費用',
  'BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台 Key 并按次计费。':'BYOK が常に優先されます。対応する API キーがない場合のみ、プラットフォームキーを使用して従量課金します。',
  '当前套餐不可用':'現在のプランでは利用できません','平台暂未配置可用引擎':'利用可能なプラットフォームエンジンはまだありません',
  '仅所有者可更改':'オーナーのみ変更できます','费用信息加载失败':'費用情報を読み込めませんでした',
  '企业登录与审计':'エンタープライズログインと監査','OIDC 单点登录':'OIDC シングルサインオン','身份提供商名称':'ID プロバイダー名',
  '签发者地址':'Issuer URL','客户端 ID':'クライアント ID','客户端密钥':'クライアントシークレット','允许的邮箱域名':'許可するメールドメイン',
  '新成员默认角色':'新規メンバーの既定ロール','启用单点登录':'シングルサインオンを有効化','保存企业登录设置':'エンタープライズログイン設定を保存',
  '单点登录地址':'シングルサインオン URL','复制登录地址':'ログイン URL をコピー','已复制登录地址':'ログイン URL をコピーしました',
  '控制措施已就绪，未获得 SOC 2 认证。':'技術的統制は準備済みですが、DisvorAI は SOC 2 認証を取得していません。',
  '包含加密密钥、OIDC PKCE、租户权限、变更审计和浏览器安全策略。':'暗号化シークレット、OIDC PKCE、テナント認可、変更監査、ブラウザーセキュリティポリシーを含みます。',
  'Enterprise 套餐可用':'Enterprise プランで利用可能','最近审计事件':'最近の監査イベント','暂无审计事件':'監査イベントはまだありません',
  '保留已保存密钥':'保存済みシークレットを維持','每行或逗号分隔':'改行またはカンマで区切る','企业登录设置已保存':'エンタープライズログイン設定を保存しました',
  '企业登录设置加载失败':'エンタープライズログイン設定を読み込めませんでした','仅所有者可查看审计事件':'監査イベントはオーナーのみ閲覧できます'
  ,'搜索数据源':'検索データソース','自然搜索与站点表现':'オーガニック検索とサイト実績','连接状态':'接続状態','已连接':'接続済み','未连接':'未接続',
  '区域数据库':'地域データベース','保存 Semrush':'Semrush を保存','断开连接':'接続解除','同步数据':'データを同期','连接 Search Console':'Search Console に接続',
  '最近同步':'最終同期','关键词':'キーワード','前 10 关键词':'上位 10 キーワード','搜索量':'検索ボリューム','流量成本':'トラフィックコスト',
  '点击':'クリック','展示':'表示回数','点击率':'CTR','平均排名':'平均掲載順位','尚未同步':'未同期',
  'Search Console OAuth 未配置':'Search Console OAuth が設定されていません','仅所有者可管理连接':'接続管理はオーナーのみ可能です',
  '数据源连接已更新':'データソース接続を更新しました','同步任务已创建':'同期ジョブを作成しました','外部搜索数据加载失败':'外部検索データを読み込めませんでした'
  ,'外链联络':'アウトリーチ','人工确认发送':'人による確認後に送信','邮件服务器':'メールサーバー','发件邮箱':'送信元メール','发件名称':'送信者名',
  '保存 SMTP':'SMTP を保存','联络草稿':'アウトリーチ下書き','暂无联络草稿':'アウトリーチ下書きはありません','准备联络邮件':'アウトリーチメールを準備','收件邮箱':'宛先メール',
  '生成草稿':'下書きを作成','编辑草稿':'下書きを編集','邮件主题':'件名','邮件正文':'本文','保存草稿':'下書きを保存','检查并发送':'確認して送信',
  '最终发送确认':'最終送信確認','我已核对收件人、主题和正文':'宛先、件名、本文を確認しました','输入确认短语':'確認フレーズを入力',
  '确认并入队':'確認してキューへ','草稿已保存':'下書きを保存しました','发送任务已创建':'送信ジョブを作成しました','SMTP 凭证使用 AES-256-GCM 加密保存。':'SMTP 認証情報は AES-256-GCM で暗号化保存されます。',
  '发送前必须检查最终内容并输入与草稿匹配的确认短语。':'送信前に最終内容を確認し、この下書き用の確認フレーズを入力してください。',
  '待编辑':'下書き','已排队':'キュー済み','发送中':'送信中','已发送':'送信済み','发送失败':'送信失敗'
});

let TEAM_STATE = null;
let BRANDING_STATE = null;
let SSO_STATE = null;
let AUDIT_STATE = null;
let INTEGRATION_STATE = null;
let OUTREACH_STATE = null;
const teamRoleLabel = {owner:'所有者',editor:'编辑者',viewer:'只读成员'};

function ssoPanel() {
  const state=SSO_STATE||{};
  if (state.error || state.detail) return `<h4 class="sso-section-title" style="font-size:16px;margin:28px 0 10px">企业登录与审计</h4>
    <div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">企业登录设置加载失败</div>`;
  const editable=!!state.can_edit, configured=!!state.configured;
  if (!state.available) return `<h4 class="sso-section-title" style="font-size:16px;margin:28px 0 10px">企业登录与审计</h4>
    <div class="card elev" style="padding:18px"><div class="row"><div style="flex:1;min-width:220px">
      <div style="font-size:14px;font-weight:500">OIDC 单点登录</div><div style="font-size:12px;color:var(--t600);margin-top:3px">Enterprise 套餐可用</div></div>
      <span class="tag tag-outline">${esc(String(state.plan||'trial').toUpperCase())}</span></div>
      <div style="font-size:12px;color:var(--t500);padding-top:12px;box-shadow:inset 0 1px 0 var(--line)">控制措施已就绪，未获得 SOC 2 认证。</div></div>`;
  const loginUrl=state.login_url?new URL(state.login_url,location.origin).href:'';
  const events=(AUDIT_STATE||{}).events||[];
  return `<h4 class="sso-section-title" style="font-size:16px;margin:28px 0 10px">企业登录与审计</h4>
    <div class="card elev" style="padding:18px;gap:14px">
      <div class="row" style="align-items:flex-start"><div style="flex:1;min-width:220px"><div style="font-size:15px;font-weight:500">OIDC 单点登录</div>
        <div style="font-size:11.5px;color:var(--t600);margin-top:3px;line-height:1.55">控制措施已就绪，未获得 SOC 2 认证。</div></div>
        <span class="tag tag-accent">CONTROLS READY</span></div>
      <div style="font-size:11.5px;color:var(--t500);line-height:1.6">包含加密密钥、OIDC PKCE、租户权限、变更审计和浏览器安全策略。</div>
      <div class="sso-form-grid">
        <label style="display:block;font-size:12px;color:var(--t500)">身份提供商名称<input id="sso-provider-name" class="input" maxlength="128" value="${esc(state.provider_name||'')}" ${editable?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">签发者地址<input id="sso-issuer-url" class="input" type="url" maxlength="2048" value="${esc(state.issuer_url||'')}" placeholder="https://identity.example.com" ${editable?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">客户端 ID<input id="sso-client-id" class="input" maxlength="512" value="${esc(state.client_id||'')}" ${editable?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">客户端密钥<input id="sso-client-secret" class="input" type="password" maxlength="4096" placeholder="${state.client_secret_configured?'保留已保存密钥':''}" ${editable?'':'disabled'} autocomplete="new-password" style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">允许的邮箱域名<textarea id="sso-allowed-domains" class="input" rows="2" maxlength="1600" placeholder="每行或逗号分隔" ${editable?'':'disabled'} style="margin-top:5px">${esc((state.allowed_domains||[]).join('\n'))}</textarea></label>
        <label style="display:block;font-size:12px;color:var(--t500)">新成员默认角色<select id="sso-default-role" class="input" ${editable?'':'disabled'} style="margin-top:5px">
          <option value="viewer" ${(state.default_role||'viewer')==='viewer'?'selected':''}>${teamRoleLabel.viewer}</option><option value="editor" ${state.default_role==='editor'?'selected':''}>${teamRoleLabel.editor}</option></select></label>
      </div>
      <div class="row" style="gap:10px;flex-wrap:wrap"><label class="row" style="gap:7px;font-size:12.5px"><input id="sso-enabled" type="checkbox" ${state.enabled?'checked':''} ${editable?'':'disabled'}>启用单点登录</label>
        ${!editable?'<span style="font-size:12px;color:var(--t600)">仅所有者可更改</span>':''}
        ${editable?'<button class="btn btn-primary" style="font-size:12px;margin-left:auto" onclick="saveSsoConfiguration()">保存企业登录设置</button>':''}</div>
      ${loginUrl?`<div style="padding-top:12px;box-shadow:inset 0 1px 0 var(--line)"><div style="font-size:11.5px;color:var(--t600);margin-bottom:5px">单点登录地址</div>
        <div class="row" style="gap:8px"><input id="sso-login-url" class="input" readonly value="${esc(loginUrl)}"><button class="btn btn-secondary" style="font-size:12px;white-space:nowrap" onclick="copySsoLoginUrl()">复制登录地址</button></div></div>`:''}
      ${editable?`<div style="padding-top:12px;box-shadow:inset 0 1px 0 var(--line)"><div class="row"><div style="flex:1;font-size:13px;font-weight:500">最近审计事件</div><span class="tag tag-outline">${esc((AUDIT_STATE||{}).soc2_status||'controls_ready_not_certified')}</span></div>
        <div style="margin-top:7px">${events.length?events.slice(0,10).map(function(event){return `<div class="sso-audit-row"><span>${esc(String(event.created_at||'').replace('T',' ').slice(0,19))}</span><span>${esc(event.action||'')}</span><span class="sso-audit-target" style="color:var(--t500);overflow-wrap:anywhere">${esc(event.target||'')}</span><span class="tag ${event.outcome==='succeeded'?'pill-good':'tag-outline'}">${esc(event.outcome||'')}</span></div>`;}).join(''):'<div style="padding:10px 0;font-size:12px;color:var(--t600)">暂无审计事件</div>'}</div></div>`
        :'<div style="font-size:12px;color:var(--t600)">仅所有者可查看审计事件</div>'}
    </div>`;
}

async function saveSsoConfiguration() {
  const secret=(($('#sso-client-secret')||{}).value||'').trim();
  const payload={
    provider_name:(($('#sso-provider-name')||{}).value||'').trim(),issuer_url:(($('#sso-issuer-url')||{}).value||'').trim(),
    client_id:(($('#sso-client-id')||{}).value||'').trim(),client_secret:secret||null,
    allowed_domains:(($('#sso-allowed-domains')||{}).value||'').split(/[\n,]/).map(function(value){return value.trim();}).filter(Boolean),
    default_role:(($('#sso-default-role')||{}).value||'viewer'),enabled:!!($('#sso-enabled')||{}).checked
  };
  const response=await fetch('/api/v1/sso/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json().catch(function(){return {};});
  if (!response.ok) { toast('保存失败：'+(result.error||result.detail||'invalid_sso_configuration'),'err'); return; }
  SSO_STATE=result;AUDIT_STATE=await api('/api/v1/sso/audit-events');toast('企业登录设置已保存');render();
}

async function copySsoLoginUrl() {
  const input=$('#sso-login-url');if(!input)return;await navigator.clipboard.writeText(input.value);toast('已复制登录地址');
}

function integrationMetric(label, value) {
  return `<div><div style="font-size:10.5px;color:var(--t600)">${label}</div><div style="font-size:16px;margin-top:2px;overflow-wrap:anywhere">${esc(value==null?'—':String(value))}</div></div>`;
}

function integrationPanel() {
  const state=INTEGRATION_STATE||{},providers=state.providers||{},latest=state.latest||{};
  if (state.error || state.detail) return `<h4 class="integration-section-title" style="font-size:16px;margin:28px 0 10px">搜索数据源</h4>
    <div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">外部搜索数据加载失败</div>`;
  const semrush=providers.semrush||{},semrushData=latest.semrush||{},semrushMetrics=semrushData.metrics||{};
  const search=providers.search_console||{},searchData=latest.search_console||{},searchMetrics=searchData.metrics||{};
  const editable=!!state.can_edit,canSync=TEAM_STATE&&TEAM_STATE.current_role!=='viewer'&&!!state.project_id;
  const database=semrush.database||'us',databases=['us','uk','de','fr','jp','au','ca'];
  if(!databases.includes(database))databases.unshift(database);
  return `<h4 class="integration-section-title" style="font-size:16px;margin:28px 0 4px">搜索数据源</h4><p class="muted settings-section-subtitle" style="font-size:12px;margin:0 0 10px">自然搜索与站点表现</p>
    <div class="integration-grid">
      <div class="card elev" style="padding:18px;gap:13px"><div class="row"><div style="flex:1;font-size:15px;font-weight:500">Semrush</div><span class="tag ${semrush.configured?'pill-good':'tag-outline'}">${semrush.configured?'已连接':'未连接'}</span></div>
        <div class="row" style="align-items:flex-end;gap:10px;flex-wrap:wrap"><label style="display:block;flex:1;min-width:180px;font-size:12px;color:var(--t500)">API Key
          <input id="semrush-api-key" class="input" type="password" maxlength="4096" placeholder="${esc(semrush.masked||'')}" ${editable?'':'disabled'} autocomplete="new-password" style="margin-top:5px"></label>
          <label style="display:block;width:120px;font-size:12px;color:var(--t500)">区域数据库<select id="semrush-database" class="input" ${editable?'':'disabled'} style="margin-top:5px">${databases.map(function(item){return `<option value="${item}" ${item===database?'selected':''}>${item.toUpperCase()}</option>`;}).join('')}</select></label></div>
        <div class="row" style="gap:7px;flex-wrap:wrap">${editable?'<button class="btn btn-secondary" style="font-size:12px" onclick="saveSemrushIntegration()">保存 Semrush</button>':''}
          ${editable&&semrush.configured?'<button class="btn btn-ghost" style="font-size:12px" onclick="disconnectIntegration(\'semrush\')">断开连接</button>':''}
          ${canSync&&semrush.configured?'<button class="btn btn-primary" style="font-size:12px;margin-left:auto" onclick="syncIntegration(\'semrush\')">同步数据</button>':''}</div>
        ${!editable?'<div style="font-size:11.5px;color:var(--t600)">仅所有者可管理连接</div>':''}
        <div style="padding-top:11px;box-shadow:inset 0 1px 0 var(--line)"><div style="font-size:11px;color:var(--t600);margin-bottom:8px">${semrushData.synced_at?'最近同步 '+esc(semrushData.synced_at.replace('T',' ').slice(0,19)):'尚未同步'}</div>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">${integrationMetric('关键词',semrushMetrics.keywords_returned)}${integrationMetric('前 10 关键词',semrushMetrics.top_10_keywords)}${integrationMetric('搜索量',semrushMetrics.search_volume)}${integrationMetric('流量成本',semrushMetrics.traffic_cost)}</div></div>
      </div>
      <div class="card elev" style="padding:18px;gap:13px"><div class="row"><div style="flex:1;font-size:15px;font-weight:500">Google Search Console</div><span class="tag ${search.configured?'pill-good':'tag-outline'}">${search.configured?'已连接':'未连接'}</span></div>
        <div style="font-size:12px;color:var(--t500);overflow-wrap:anywhere">${esc(state.search_console_property||'')}</div>
        <div class="row" style="gap:7px;flex-wrap:wrap">${editable&&search.oauth_available?`<a class="btn btn-secondary" style="font-size:12px" href="${esc(state.search_console_authorize_url||'#')}">连接 Search Console</a>`:''}
          ${editable&&search.configured?'<button class="btn btn-ghost" style="font-size:12px" onclick="disconnectIntegration(\'search_console\')">断开连接</button>':''}
          ${canSync&&search.configured?'<button class="btn btn-primary" style="font-size:12px;margin-left:auto" onclick="syncIntegration(\'search_console\')">同步数据</button>':''}</div>
        ${editable&&!search.oauth_available?'<div style="font-size:11.5px;color:var(--t600)">Search Console OAuth 未配置</div>':''}
        ${!editable?'<div style="font-size:11.5px;color:var(--t600)">仅所有者可管理连接</div>':''}
        <div style="padding-top:11px;box-shadow:inset 0 1px 0 var(--line)"><div style="font-size:11px;color:var(--t600);margin-bottom:8px">${searchData.synced_at?'最近同步 '+esc(searchData.synced_at.replace('T',' ').slice(0,19)):'尚未同步'}</div>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">${integrationMetric('点击',searchMetrics.clicks)}${integrationMetric('展示',searchMetrics.impressions)}${integrationMetric('点击率',searchMetrics.ctr==null?null:(Number(searchMetrics.ctr)*100).toFixed(2)+'%')}${integrationMetric('平均排名',searchMetrics.average_position)}</div></div>
      </div>
    </div>`;
}

async function saveSemrushIntegration() {
  const key=(($('#semrush-api-key')||{}).value||'').trim();
  if(!key){toast('请输入 Semrush API Key','err');return}
  const result=await post('/api/integrations',{action:'save_semrush',api_key:key,database:(($('#semrush-database')||{}).value||'us')});
  if(result.error||result.detail){toast('保存失败：'+(result.error||result.detail),'err');return}
  INTEGRATION_STATE=null;toast('数据源连接已更新');render();
}

async function disconnectIntegration(provider) {
  if(!confirm('确认断开此数据源？历史同步快照将保留。'))return;
  const result=await post('/api/integrations',{action:'disconnect',provider:provider});
  if(result.error||result.detail){toast('断开失败：'+(result.error||result.detail),'err');return}
  INTEGRATION_STATE=null;toast('数据源连接已更新');render();
}

async function syncIntegration(provider) {
  const result=await post('/api/integrations',{action:'sync',provider:provider});
  if(!result.job_id){toast('同步失败：'+(result.error||result.detail||'integration_sync_failed'),'err');return}
  INTEGRATION_STATE=null;RUNNING=result.job_id;LASTJOB=result.job_id;LOGOFF=0;renderSide();pollJob();toast('同步任务已创建');
}

const outreachStatusLabel={draft:'待编辑',queued:'已排队',sending:'发送中',sent:'已发送',failed:'发送失败'};

function outreachPanel() {
  const state=OUTREACH_STATE||{},smtp=state.smtp||{},drafts=state.drafts||[],owner=!!state.can_edit;
  if(state.error||state.detail)return `<h4 class="outreach-section-title" style="font-size:16px;margin:28px 0 10px">外链联络</h4>
    <div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">外链联络加载失败</div>`;
  const port=Number(smtp.port||587),mode=smtp.security_mode||'starttls';
  return `<h4 class="outreach-section-title" style="font-size:16px;margin:28px 0 4px">外链联络</h4><p class="muted settings-section-subtitle" style="font-size:12px;margin:0 0 10px">人工确认发送</p>
    <div class="card elev" style="padding:18px;gap:12px"><div class="row"><div style="flex:1;font-size:15px;font-weight:500">SMTP</div><span class="tag ${smtp.configured?'pill-good':'tag-outline'}">${smtp.configured?'已连接':'未连接'}</span></div>
      <div style="font-size:11.5px;color:var(--t600)">SMTP 凭证使用 AES-256-GCM 加密保存。</div>
      <div class="outreach-smtp-grid" style="display:grid;grid-template-columns:minmax(180px,1fr) 90px 120px;gap:10px">
        <label style="display:block;font-size:12px;color:var(--t500)">邮件服务器<input id="outreach-smtp-host" class="input" value="${esc(smtp.host||'')}" ${owner?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">Port<select id="outreach-smtp-port" class="input" ${owner?'':'disabled'} style="margin-top:5px">${[25,465,587,2525].map(function(value){return `<option value="${value}" ${value===port?'selected':''}>${value}</option>`;}).join('')}</select></label>
        <label style="display:block;font-size:12px;color:var(--t500)">Security<select id="outreach-smtp-security" class="input" ${owner?'':'disabled'} style="margin-top:5px"><option value="starttls" ${mode==='starttls'?'selected':''}>STARTTLS</option><option value="ssl" ${mode==='ssl'?'selected':''}>SSL/TLS</option></select></label>
      </div>
      <div class="outreach-identity-grid" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px">
        <label style="display:block;font-size:12px;color:var(--t500)">Username<input id="outreach-smtp-username" class="input" value="${esc(smtp.username||'')}" ${owner?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">Password<input id="outreach-smtp-password" class="input" type="password" placeholder="${smtp.password_configured?'保留已保存密钥':''}" ${owner?'':'disabled'} autocomplete="new-password" style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">发件邮箱<input id="outreach-from-email" class="input" type="email" value="${esc(smtp.from_email||'')}" ${owner?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;font-size:12px;color:var(--t500)">发件名称<input id="outreach-from-name" class="input" value="${esc(smtp.from_name||'')}" ${owner?'':'disabled'} style="margin-top:5px"></label>
      </div>
      ${owner?`<div class="row" style="gap:8px;justify-content:flex-end">${smtp.configured?'<button class="btn btn-ghost" style="font-size:12px" onclick="deleteOutreachSmtp()">断开连接</button>':''}<button class="btn btn-secondary" style="font-size:12px" onclick="saveOutreachSmtp()">保存 SMTP</button></div>`:''}
    </div>
    <div class="card elev" style="padding:18px;gap:8px;margin-top:12px"><div class="row"><div style="flex:1;font-size:15px;font-weight:500">联络草稿</div><span class="tag tag-outline">${drafts.length}</span></div>
      <div style="font-size:11.5px;color:var(--t600)">发送前必须检查最终内容并输入与草稿匹配的确认短语。</div>
      ${drafts.length?drafts.map(function(draft){return `<div class="row" style="gap:8px;padding:9px 0;box-shadow:inset 0 -1px 0 var(--line)"><div style="flex:1;min-width:160px"><div style="font-size:13px;overflow-wrap:anywhere">${esc(draft.subject)}</div><div style="font-size:11px;color:var(--t600);margin-top:2px;overflow-wrap:anywhere">${esc(draft.recipient_email)} · ${esc(draft.id)}</div></div><span class="tag ${draft.status==='sent'?'pill-good':'tag-outline'}">${esc(outreachStatusLabel[draft.status]||draft.status)}</span>${['draft','failed'].includes(draft.status)&&TEAM_STATE&&TEAM_STATE.current_role!=='viewer'?`<button class="btn btn-ghost" style="font-size:12px" onclick="outreachEditModal('${esc(draft.id)}')">编辑草稿</button>`:''}</div>`;}).join(''):'<div style="padding:10px 0;font-size:12px;color:var(--t600)">暂无联络草稿</div>'}
    </div>`;
}

async function saveOutreachSmtp() {
  const smtp={host:(($('#outreach-smtp-host')||{}).value||'').trim(),port:Number((($('#outreach-smtp-port')||{}).value||587)),security_mode:(($('#outreach-smtp-security')||{}).value||'starttls'),username:(($('#outreach-smtp-username')||{}).value||'').trim(),password:(($('#outreach-smtp-password')||{}).value||'').trim()||null,from_email:(($('#outreach-from-email')||{}).value||'').trim(),from_name:(($('#outreach-from-name')||{}).value||'').trim()};
  const result=await post('/api/outreach',{action:'save_smtp',smtp:smtp});if(result.error||result.detail){toast('保存失败：'+(result.error||result.detail),'err');return}OUTREACH_STATE=result;toast('SMTP 已保存');render();
}

async function deleteOutreachSmtp(){if(!confirm('确认断开 SMTP？'))return;const result=await post('/api/outreach',{action:'delete_smtp'});if(result.error){toast('断开失败：'+result.error,'err');return}OUTREACH_STATE=result;render();}

function outreachRecipientModal(ticketId){modal(`<h4 style="font-size:17px">准备联络邮件</h4><label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">收件邮箱<input id="outreach-recipient" class="input" type="email" autocomplete="email" style="margin-top:5px"></label><div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="createOutreachDraft('${esc(ticketId)}')">生成草稿</button></div>`);}

async function createOutreachDraft(ticketId){const email=(($('#outreach-recipient')||{}).value||'').trim();if(!email){toast('请输入收件邮箱','err');return}const result=await post('/api/outreach',{action:'create_draft',ticket_id:ticketId,recipient_email:email});if(!result.draft){toast('生成失败：'+(result.error||result.detail||'outreach_draft_failed'),'err');return}OUTREACH_STATE=OUTREACH_STATE||{drafts:[]};OUTREACH_STATE.drafts=OUTREACH_STATE.drafts||[];OUTREACH_STATE.drafts.unshift(result.draft);outreachEditModal(result.draft);}

function outreachEditModal(value){const draft=typeof value==='string'?((OUTREACH_STATE||{}).drafts||[]).find(function(item){return item.id===value;}):value;if(!draft)return;modal(`<h4 style="font-size:17px">编辑草稿</h4><input id="outreach-draft-revision" type="hidden" value="${draft.revision}"><label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">收件邮箱<input id="outreach-draft-recipient" class="input" type="email" value="${esc(draft.recipient_email)}" style="margin-top:5px"></label><label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">邮件主题<input id="outreach-draft-subject" class="input" maxlength="300" value="${esc(draft.subject)}" style="margin-top:5px"></label><label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">邮件正文<textarea id="outreach-draft-body" class="input" rows="10" maxlength="20000" style="margin-top:5px">${esc(draft.body)}</textarea></label><div class="row" style="justify-content:flex-end;margin-top:14px;flex-wrap:wrap"><button class="btn btn-secondary" onclick="saveOutreachDraft('${esc(draft.id)}',false)">保存草稿</button><button class="btn btn-primary" onclick="saveOutreachDraft('${esc(draft.id)}',true)">检查并发送</button></div>`);}

async function saveOutreachDraft(draftId,review){const payload={revision:Number((($('#outreach-draft-revision')||{}).value||0)),recipient_email:(($('#outreach-draft-recipient')||{}).value||'').trim(),subject:(($('#outreach-draft-subject')||{}).value||'').trim(),body:(($('#outreach-draft-body')||{}).value||'').trim()};const result=await post('/api/outreach',{action:'update_draft',draft_id:draftId,draft:payload});if(!result.draft){toast('保存失败：'+(result.error||result.detail||'outreach_update_failed'),'err');return}if(OUTREACH_STATE){const index=(OUTREACH_STATE.drafts||[]).findIndex(function(item){return item.id===draftId;});if(index>=0)OUTREACH_STATE.drafts[index]=result.draft;}toast('草稿已保存');if(review)outreachSendReview(result.draft);else{closeModal();render();}}

function outreachSendReview(draft){const phrase='SEND '+draft.id;modal(`<h4 style="font-size:17px">最终发送确认</h4><div style="font-size:12px;color:var(--t600);margin-top:10px">收件邮箱</div><div style="font-size:13px;overflow-wrap:anywhere">${esc(draft.recipient_email)}</div><div style="font-size:12px;color:var(--t600);margin-top:10px">邮件主题</div><div style="font-size:13px;overflow-wrap:anywhere">${esc(draft.subject)}</div><div style="font-size:12px;color:var(--t600);margin-top:10px">邮件正文</div><div style="max-height:220px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:10px;margin-top:4px;border:1px solid var(--line);font-size:12.5px;line-height:1.6">${esc(draft.body)}</div><label class="row" style="gap:7px;margin-top:12px;font-size:12.5px"><input id="outreach-confirm-check" type="checkbox">我已核对收件人、主题和正文</label><label style="display:block;font-size:12px;color:var(--t500);margin-top:10px">输入确认短语 <code>${esc(phrase)}</code><input id="outreach-confirm-text" class="input" autocomplete="off" style="margin-top:5px"></label><div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-secondary" onclick="outreachEditModal('${esc(draft.id)}')">返回编辑</button><button class="btn btn-primary" onclick="queueOutreachSend('${esc(draft.id)}',${draft.revision})">确认并入队</button></div>`);}

async function queueOutreachSend(draftId,revision){const confirmed=!!($('#outreach-confirm-check')||{}).checked,text=(($('#outreach-confirm-text')||{}).value||'');if(!confirmed||text!=='SEND '+draftId){toast('请勾选确认并输入完整确认短语','err');return}const result=await post('/api/outreach',{action:'send',draft_id:draftId,revision:revision,confirmed:true,confirmation_text:text});if(!result.job_id){toast('发送失败：'+(result.error||result.detail||'outreach_send_failed'),'err');return}OUTREACH_STATE=null;closeModal();RUNNING=result.job_id;LASTJOB=result.job_id;LOGOFF=0;renderSide();pollJob();toast('发送任务已创建');}

function samplingFundingPanel(state) {
  state = state || {};
  if (state.error) return `<h4 style="font-size:16px;margin:28px 0 10px">采样费用</h4>
    <div class="card elev" style="padding:18px"><div class="row"><span style="flex:1;font-size:13px;color:var(--t500)">费用信息加载失败</span>
      <button class="btn btn-secondary" style="font-size:12px" onclick="render()">刷新</button></div></div>`;
  const pool = state.pool_engines || [], usage = state.usage || {};
  const effective = Object.fromEntries((state.effective_engines || []).map(function (item) { return [item.engine_code,item.source]; }));
  const canEnable = !!state.eligible && pool.length > 0;
  const sourceLabel = {byok:'BYOK',platform_pool:'平台代付',unavailable:'不可用'};
  return `<h4 style="font-size:16px;margin:28px 0 10px">采样费用</h4>
    <div class="card elev" style="padding:18px;gap:12px">
      <div class="row" style="align-items:flex-start"><div style="flex:1;min-width:220px">
        <div style="font-size:15px;font-weight:500">平台代付</div>
        <div style="font-size:11.5px;color:var(--t600);margin-top:3px;line-height:1.55">BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台 Key 并按次计费。</div></div>
        <label class="row" style="gap:7px;font-size:12.5px;white-space:nowrap"><input id="platform-pool-enabled" type="checkbox"
          ${state.platform_pool_enabled?'checked':''} ${state.can_edit&&canEnable?'':'disabled'} onchange="setPlatformPool(this.checked)">启用</label></div>
      ${!state.eligible?`<div style="font-size:12px;color:var(--t500)">当前套餐不可用 (${esc(String(state.plan || 'trial').toUpperCase())})</div>`:''}
      ${state.eligible&&!state.can_edit?'<div style="font-size:12px;color:var(--t500)">仅所有者可更改</div>':''}
      ${state.eligible&&!pool.length?'<div style="font-size:12px;color:var(--t500)">平台暂未配置可用引擎</div>':''}
      ${pool.length?`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px">
        ${pool.map(function (item) { const source = effective[item.engine_code] || 'unavailable'; return `<div style="padding:10px 11px;border:1px solid var(--line);border-radius:var(--r-md);min-width:0">
          <div class="row" style="gap:6px"><span style="flex:1;font-size:13px;overflow-wrap:anywhere">${esc(item.engine_name || item.engine_code)}</span>
            <span class="tag ${source==='platform_pool'?'tag-accent':'tag-outline'}">${esc(sourceLabel[source] || source)}</span></div>
          <div style="font-size:11.5px;color:var(--t600);margin-top:5px">${esc(item.sampling_mode)} · ¥${(Number(item.unit_price_cny_fen || 0)/100).toFixed(2)} / 次</div></div>`; }).join('')}</div>`:''}
      <div class="row" style="gap:24px;padding-top:10px;box-shadow:inset 0 1px 0 var(--line)">
        <div><div style="font-size:10.5px;color:var(--t600)">本月调用</div><div style="font-size:17px;margin-top:2px">${Number(usage.calls || 0).toLocaleString()}</div></div>
        <div><div style="font-size:10.5px;color:var(--t600)">本月费用</div><div style="font-size:17px;margin-top:2px">¥${esc(usage.cost_cny || '0.00')}</div></div>
        <div style="font-size:11.5px;color:var(--t600);margin-left:auto">${esc(usage.month || '')}</div></div>
    </div>`;
}

async function setPlatformPool(enabled) {
  const input = $('#platform-pool-enabled');
  if (enabled && !confirm('启用平台代付后，缺少 BYOK 的引擎将按页面所示单价逐次收费。确认启用？')) {
    if (input) input.checked=false;
    return;
  }
  if (input) input.disabled=true;
  const result = await post('/api/sampling-funding',{platform_pool_enabled:enabled});
  if (result.error || result.detail) {
    if (input) { input.checked=!enabled; input.disabled=false; }
    toast('更新失败：'+(result.error || result.detail || 'sampling_funding_update_failed'),'err');
    return;
  }
  toast(enabled?'平台代付已启用':'平台代付已关闭');
  render();
}

function deliveryBrandingPanel() {
  const state = BRANDING_STATE || {}, value = state.branding || {};
  if (!state.available) return `<h4 style="font-size:16px;margin:28px 0 10px">白标交付</h4>
    <div class="card elev" style="padding:18px"><div class="row"><div style="flex:1">
      <div style="font-size:14px;font-weight:500">打印 / PDF 页眉</div>
      <div style="font-size:12px;color:var(--t600);margin-top:3px">Agency 套餐可用</div></div>
      <span class="tag tag-outline">${esc(String(state.plan || 'trial').toUpperCase())}</span></div></div>`;
  const editable = !!state.can_edit, logo = value.logo_data_url || '';
  return `<h4 style="font-size:16px;margin:28px 0 10px">白标交付</h4>
    <div class="card elev" style="padding:18px;gap:14px">
      <div class="row"><div style="flex:1"><div style="font-size:14px;font-weight:500">打印 / PDF 页眉</div></div>
        <label class="row" style="gap:7px;font-size:12.5px"><input id="delivery-branding-enabled" type="checkbox" ${value.enabled?'checked':''} ${editable?'':'disabled'}>启用白标</label></div>
      <div class="row" style="align-items:stretch;gap:14px;flex-wrap:wrap">
        <label style="display:block;flex:1;min-width:220px;font-size:12px;color:var(--t500)">机构名称
          <input id="delivery-branding-name" class="input" maxlength="120" value="${esc(value.company_name || '')}" ${editable?'':'disabled'} style="margin-top:5px"></label>
        <label style="display:block;width:130px;font-size:12px;color:var(--t500)">主题色
          <input id="delivery-branding-color" class="input" type="color" value="${esc(value.accent_color || '#1F4E79')}" ${editable?'':'disabled'} style="margin-top:5px;height:38px;padding:3px"></label>
      </div>
      <label style="display:block;font-size:12px;color:var(--t500)">页脚文字
        <input id="delivery-branding-footer" class="input" maxlength="240" value="${esc(value.footer_text || '')}" ${editable?'':'disabled'} style="margin-top:5px"></label>
      <div class="row" style="gap:12px;flex-wrap:wrap">
        <div id="delivery-branding-logo-preview" style="display:grid;place-items:center;width:180px;height:54px;border:1px solid var(--line);background:var(--bg);overflow:hidden">
          ${logo?`<img src="${esc(logo)}" alt="" style="display:block;max-width:168px;max-height:42px;object-fit:contain">`:'<span class="muted" style="font-size:12px">Logo</span>'}</div>
        ${editable?`<label class="btn btn-secondary" style="font-size:12px;cursor:pointer">选择 Logo
          <input type="file" accept="image/png,image/jpeg,image/webp" onchange="setDeliveryBrandingLogo(this)" style="display:none"></label>
          <button class="btn btn-ghost" style="font-size:12px" onclick="clearDeliveryBrandingLogo()">移除 Logo</button>`:''}
        ${editable?'<button class="btn btn-primary" style="font-size:12px;margin-left:auto" onclick="saveDeliveryBranding()">保存白标设置</button>':''}
      </div>
    </div>`;
}

function setDeliveryBrandingLogo(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 524288) {
    toast('Logo 必须是 512KB 内的 PNG、JPEG 或 WebP','err');input.value='';return;
  }
  const reader = new FileReader();
  reader.onload = function () {
    BRANDING_STATE.branding.logo_data_url = String(reader.result || '');
    const preview = $('#delivery-branding-logo-preview');
    if (preview) preview.innerHTML = `<img src="${esc(BRANDING_STATE.branding.logo_data_url)}" alt="" style="display:block;max-width:168px;max-height:42px;object-fit:contain">`;
  };
  reader.readAsDataURL(file);
}

function clearDeliveryBrandingLogo() {
  if (!BRANDING_STATE || !BRANDING_STATE.branding) return;
  BRANDING_STATE.branding.logo_data_url = '';
  const preview = $('#delivery-branding-logo-preview');
  if (preview) preview.innerHTML = '<span class="muted" style="font-size:12px">Logo</span>';
}

async function saveDeliveryBranding() {
  const payload = {
    enabled:!!($('#delivery-branding-enabled') || {}).checked,
    company_name:(($('#delivery-branding-name') || {}).value || '').trim(),
    logo_data_url:((BRANDING_STATE.branding || {}).logo_data_url || ''),
    accent_color:(($('#delivery-branding-color') || {}).value || '#1F4E79'),
    footer_text:(($('#delivery-branding-footer') || {}).value || '').trim()
  };
  const result = await post('/api/delivery-branding',payload);
  if (result.error || result.detail) { toast('保存失败：'+(result.error || 'invalid_delivery_branding'),'err'); return; }
  BRANDING_STATE=result;toast('白标设置已保存');render();
}

function teamPanel() {
  const state = TEAM_STATE || {}, members = state.members || [], invitations = state.invitations || [];
  const owner = state.current_role === 'owner';
  const pending = invitations.filter(function (item) { return item.status === 'pending'; });
  return `<div class="card elev" style="padding:18px;gap:10px;margin-top:14px">
    <div class="row"><div style="flex:1"><div style="font-size:15px;font-weight:500">团队成员</div>
      <div style="font-size:11.5px;color:var(--t600)">${esc((state.tenant || {}).name || '')}</div></div>
      ${owner?'<button class="btn btn-primary" style="font-size:12px" onclick="teamInviteModal()">邀请成员</button>':''}</div>
    ${(state.workspaces || []).length > 1?`<label class="row" style="font-size:12px;color:var(--t500);gap:8px">工作区
      <select class="input" style="width:auto;min-width:180px" onchange="switchTeamWorkspace(this.value)">
        ${(state.workspaces || []).map(function (workspace) { return `<option value="${workspace.id}" ${workspace.id===(state.tenant || {}).id?'selected':''}>${esc(workspace.name)} · ${esc(teamRoleLabel[workspace.role] || workspace.role)}</option>`; }).join('')}
      </select></label>`:''}
    <div>${members.map(function (member) { return `<div class="row" style="padding:7px 0;box-shadow:inset 0 -1px 0 var(--line);gap:8px">
      <span style="flex:1;font-size:13px;overflow-wrap:anywhere">${esc(member.email)}${member.is_current_user?' <span class="tag tag-neutral">你</span>':''}</span>
      ${owner?`<select class="input" style="width:110px;padding:4px 7px;font-size:12px" onchange="updateTeamMember(${member.user_id},this.value)">
        ${['owner','editor','viewer'].map(function (role) { return `<option value="${role}" ${member.role===role?'selected':''}>${teamRoleLabel[role]}</option>`; }).join('')}</select>
        ${member.is_current_user?'':`<button class="btn btn-ghost" style="font-size:12px;padding:3px 7px" onclick="removeTeamMember(${member.user_id})">移除</button>`}`
        :`<span class="tag tag-outline">${esc(teamRoleLabel[member.role] || member.role)}</span>`}</div>`; }).join('')}</div>
    ${owner&&pending.length?`<div style="font-size:12px;color:var(--t500);margin-top:4px">待接受邀请</div>
      ${pending.map(function (invitation) { return `<div class="row" style="padding:5px 0;gap:8px;font-size:12.5px">
        <span style="flex:1;overflow-wrap:anywhere">${esc(invitation.email)}</span><span class="tag tag-outline">${esc(teamRoleLabel[invitation.role] || invitation.role)}</span>
        <button class="btn btn-ghost" style="font-size:12px;padding:3px 7px" onclick="revokeTeamInvitation(${invitation.id})">撤销</button></div>`; }).join('')}`:''}
  </div>`;
}

function teamInviteModal() {
  modal(`<h4 style="font-size:17px">邀请成员</h4>
    <label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">Email
      <input id="team-invite-email" class="input" type="email" autocomplete="email" style="margin-top:5px"></label>
    <label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">角色
      <select id="team-invite-role" class="input" style="margin-top:5px"><option value="editor">编辑者</option><option value="viewer">只读成员</option><option value="owner">所有者</option></select></label>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-secondary" onclick="closeModal()">取消</button>
      <button class="btn btn-primary" onclick="inviteTeamMember()">创建邀请</button></div>`);
}

async function inviteTeamMember() {
  const email = (($('#team-invite-email') || {}).value || '').trim();
  const role = (($('#team-invite-role') || {}).value || 'viewer');
  if (!email) { toast('请输入成员邮箱','err'); return; }
  const result = await post('/api/team/invite',{email:email,role:role});
  if (result.error) { toast('邀请失败：'+result.error,'err'); return; }
  TEAM_STATE = null;
  const inviteUrl = new URL(result.invite_url || '/', location.origin).href;
  modal(`<h4 style="font-size:17px">邀请链接已创建</h4>
    <input id="team-invite-link" class="input" readonly value="${esc(inviteUrl)}" style="margin-top:12px">
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-secondary" onclick="closeModal();render()">关闭</button>
      <button class="btn btn-primary" onclick="copyTeamInvite()">复制邀请链接</button></div>`);
}

async function copyTeamInvite() {
  const input = $('#team-invite-link');
  if (!input) return;
  await navigator.clipboard.writeText(input.value);
  toast('已复制');
}

async function updateTeamMember(userId, role) {
  const result = await post('/api/team/member',{user_id:userId,role:role});
  if (result.error) { toast('更新失败：'+result.error,'err'); TEAM_STATE=null; render(); return; }
  TEAM_STATE=null;toast('角色已更新');render();
}

async function removeTeamMember(userId) {
  if (!confirm('确认移除这名成员？')) return;
  const result = await post('/api/team/member',{user_id:userId,remove:true});
  if (result.error) { toast('移除失败：'+result.error,'err'); return; }
  TEAM_STATE=null;render();
}

async function revokeTeamInvitation(invitationId) {
  if (!confirm('确认撤销这条邀请？')) return;
  const result = await post('/api/team/revoke',{invitation_id:invitationId});
  if (result.error) { toast('撤销失败：'+result.error,'err'); return; }
  TEAM_STATE=null;render();
}

async function switchTeamWorkspace(tenantId) {
  const result = await post('/api/team/switch',{tenant_id:Number(tenantId)});
  if (!result.access_token) { toast('切换失败：'+(result.error || ''),'err'); return; }
  localStorage.setItem('disvorai_access_token', result.access_token);
  location.reload();
}

const engineSettingsView = VIEWS.settings;
vSettings = async function () {
  if (!TEAM_STATE) TEAM_STATE = await api('/api/team');
  if (!BRANDING_STATE) BRANDING_STATE = await api('/api/delivery-branding');
  if (!SSO_STATE) SSO_STATE = await api('/api/v1/sso/config');
  if (SSO_STATE.can_edit && !AUDIT_STATE) AUDIT_STATE = await api('/api/v1/sso/audit-events');
  if (!INTEGRATION_STATE) INTEGRATION_STATE = await api('/api/integrations');
  if (!OUTREACH_STATE) OUTREACH_STATE = await api('/api/outreach');
  const funding = await api('/api/sampling-funding');
  const html = await engineSettingsView();
  const index = html.lastIndexOf('</div>');
  const panels = samplingFundingPanel(funding) + deliveryBrandingPanel() + teamPanel() + integrationPanel() + outreachPanel() + ssoPanel();
  return index < 0 ? html + panels : html.slice(0,index) + panels + html.slice(index);
};
VIEWS.settings = vSettings;

const engineEditKey = editKey;
editKey = function (index) {
  if (!TEAM_STATE || TEAM_STATE.current_role !== 'owner') { toast('仅所有者可配置 API Key','err'); return; }
  engineEditKey(index);
};
const engineEditPublisher = editPub;
editPub = function (index) {
  if (!TEAM_STATE || TEAM_STATE.current_role !== 'owner') { toast('仅所有者可配置发布渠道','err'); return; }
  engineEditPublisher(index);
};

const engineTaskModal = taskModal;
taskModal = function (id) {
  const ticket = (D.tasks || []).find(function (item) { return item.id === id; });
  if (!ticket || ticket.kind !== 'offsite') { engineTaskModal(id); return; }
  const acceptance = ticket.acceptance || {};
  const questions = ticket.influenced_question_texts || ticket.influenced_questions || [];
  modal(`<h4 style="font-size:17px">${esc(ticket.id)} · ${esc(ticket.title)}</h4>
    <div class="row" style="gap:6px;margin-top:6px"><span class="tag tag-neutral">${esc(ticket.priority)}</span>
      <span class="tag tag-outline">Offsite · 人工</span>
      <span style="font-size:11.5px;color:var(--t600)">负责：${esc(ticket.owner)} · 工作量 ${esc(ticket.effort)} · ${mktLabel(ticket.market)}</span></div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">目标页面</div>
    <a href="${esc(ticket.url)}" target="_blank" rel="noopener noreferrer" style="font-size:13px;color:var(--a300);overflow-wrap:anywhere">${esc(ticket.url)}</a>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">为什么做</div>
    <div style="font-size:13px;line-height:1.6;color:var(--t400)">${esc(ticket.why)}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">具体怎么干</div>
    <div style="font-size:13px;line-height:1.6">${esc(ticket.action)}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">影响问题（${questions.length}）</div>
    <div style="max-height:120px;overflow:auto;font-size:12px;color:var(--t400);line-height:1.7">${questions.map(function (question) { return '<div>' + esc(question) + '</div>'; }).join('')}</div>
    <div style="font-size:12px;color:var(--t600);margin:12px 0 3px">怎么算做完（人工验收）</div>
    <div style="font-size:13px;line-height:1.6">${esc(acceptance.desc || '')}</div>
    <div class="row" style="justify-content:flex-end;margin-top:14px">${TEAM_STATE&&TEAM_STATE.current_role!=='viewer'?`<button class="btn btn-secondary" onclick="outreachRecipientModal('${esc(ticket.id)}')">准备联络邮件</button>`:''}<button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
};

Object.assign(UI_D.en, {
  '矩阵':'Matrix','列表':'List','行动计划视图':'Action plan view','影响优先级':'Impact priority','工作量':'Effort',
  '影响优先级 × 工作量':'Impact priority × effort','全部任务':'All tasks',
  '高影响':'High impact','中影响':'Medium impact','低影响':'Lower impact','低工作量':'Low effort','中工作量':'Medium effort','高工作量':'High effort',
  '暂无行动任务':'No action items yet','未分类任务':'Unclassified tasks','待开始':'To do','进行中':'In progress','受阻':'Blocked','已完成':'Done','不处理':'Won\'t fix'
});
Object.assign(UI_D.ja, {
  '矩阵':'マトリクス','列表':'リスト','行动计划视图':'アクションプラン表示','影响优先级':'インパクト優先度','工作量':'工数',
  '影响优先级 × 工作量':'インパクト優先度 × 工数','全部任务':'すべてのタスク',
  '高影响':'高インパクト','中影响':'中インパクト','低影响':'低インパクト','低工作量':'低工数','中工作量':'中工数','高工作量':'高工数',
  '暂无行动任务':'アクション項目はまだありません','未分类任务':'未分類タスク','待开始':'未着手','进行中':'進行中','受阻':'ブロック中','已完成':'完了','不处理':'対応しない'
});

const enginePlanView = vPlan;
const playbookPriorityOrder = {P0:0,P1:1,P2:2};
const playbookEffortOrder = {S:0,M:1,L:2};
const playbookStatusLabel = {todo:'待开始',doing:'进行中',blocked:'受阻',done:'已完成',wontfix:'不处理'};

function sortedPlaybookTasks(tasks) {
  return (Array.isArray(tasks) ? tasks : []).map(function (task,index) { return {task:task,index:index}; })
    .filter(function (item) { return item.task && typeof item.task === 'object'; })
    .sort(function (left,right) {
      const a=left.task,b=right.task;
      return (['done','wontfix'].includes(a.status)?1:0)-(['done','wontfix'].includes(b.status)?1:0)
        || (playbookPriorityOrder[a.priority]??99)-(playbookPriorityOrder[b.priority]??99)
        || (playbookEffortOrder[a.effort]??99)-(playbookEffortOrder[b.effort]??99)
        || left.index-right.index;
    }).map(function (item) { return item.task; });
}

function playbookTaskButton(task) {
  const complete=['done','wontfix'].includes(task.status);
  return `<button class="playbook-task ${complete?'is-complete':''}" onclick="taskModal(${esc(JSON.stringify(task.id))})" title="${esc(task.title || task.id)}">
    <span class="playbook-task-top"><span>${esc(task.id || '')}</span><span>${esc(playbookStatusLabel[task.status] || task.status || '')}</span></span>
    <span class="playbook-task-title">${esc(task.title || '')}</span>
    <span class="playbook-task-meta">${esc(task.owner || '未分配')} · ${esc(task.package || '')}</span></button>`;
}

function playbookMatrix(tasks) {
  const sorted=sortedPlaybookTasks(tasks), priorities=[['P0','高影响'],['P1','中影响'],['P2','低影响']], efforts=[['S','低工作量'],['M','中工作量'],['L','高工作量']];
  const known=sorted.filter(function (task) { return playbookPriorityOrder[task.priority]!==undefined && playbookEffortOrder[task.effort]!==undefined; });
  const unknown=sorted.filter(function (task) { return !known.includes(task); });
  if (!sorted.length) return '<div class="playbook-empty">暂无行动任务</div>';
  let cells=`<div class="playbook-axis"><strong>影响优先级</strong><span>工作量</span></div>`;
  efforts.forEach(function (effort) { cells+=`<div class="playbook-axis"><strong>${effort[0]}</strong><span>${effort[1]}</span></div>`; });
  priorities.forEach(function (priority) {
    cells+=`<div class="playbook-axis"><strong>${priority[0]}</strong><span>${priority[1]}</span></div>`;
    efforts.forEach(function (effort) {
      const items=known.filter(function (task) { return task.priority===priority[0] && task.effort===effort[0]; });
      cells+=`<div class="playbook-cell">${items.map(playbookTaskButton).join('') || '<div class="playbook-empty">0</div>'}</div>`;
    });
  });
  return `<div class="playbook-matrix-scroll" tabindex="0"><div class="playbook-matrix">${cells}</div></div>
    ${unknown.length?`<div class="playbook-unclassified"><div style="font-size:12px;color:var(--t500)">未分类任务</div>
      <div class="playbook-unclassified-list">${unknown.map(playbookTaskButton).join('')}</div></div>`:''}`;
}

function setPlaybookView(view) {
  ST.planView=view==='list'?'list':'matrix';
  render();
}

vPlan = function () {
  ST.planView=ST.planView==='list'?'list':'matrix';
  let html=enginePlanView()
    .replace('<div style="padding:32px 44px 72px;max-width:1280px">','<div class="playbook-page">')
    .replace('<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px">','<div class="playbook-page-head" style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px">')
    .replace('<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 18px">','<div class="playbook-stats" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0 18px">');
  const tableStart=html.indexOf('<div class="tbl">'), pageEnd=html.lastIndexOf('\n  </div>');
  if (tableStart<0 || pageEnd<tableStart) return html;
  const list=html.slice(tableStart,pageEnd);
  const labels={zh:'行动计划视图',en:'Action plan view',ja:'アクションプラン表示'};
  const toolbar=`<div class="playbook-toolbar"><div style="font-size:12px;color:var(--t500)">${ST.planView==='matrix'?'影响优先级 × 工作量':'全部任务'}</div>
    <div class="seg playbook-view-switch" role="group" aria-label="${labels[ULANG] || labels.zh}">
      <button class="playbook-view-button ${ST.planView==='matrix'?'on':''}" aria-pressed="${ST.planView==='matrix'}" onclick="setPlaybookView('matrix')">矩阵</button>
      <button class="playbook-view-button ${ST.planView==='list'?'on':''}" aria-pressed="${ST.planView==='list'}" onclick="setPlaybookView('list')">列表</button></div></div>`;
  return html.slice(0,tableStart)+toolbar+(ST.planView==='matrix'?playbookMatrix(D.tasks):list)+html.slice(pageEnd);
};
VIEWS.plan = vPlan;
</script>
"""


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def serve_ui():
    """返回经过品牌和 SaaS API 适配的 engine 单页 UI。"""
    html = UI_PATH.read_text("utf-8")
    html = html.replace("GeoLook", "DisvorAI").replace("geolook", "disvorai")
    html = html.replace(
        'Geo<span style="color:var(--accent)">Look</span>',
        'Disvor<span style="color:var(--accent)">AI</span>',
    )
    html = html.replace("</style>", SETTINGS_RESPONSIVE_STYLE + "</style>", 1)
    html = html.replace(
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:26px">',
        '<div class="settings-core-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:26px">',
        1,
    )
    html = html.replace(
        '点「配置」填 Key 和模型，写入项目根目录 .env，立即生效。无 API 的引擎走人工采样表。',
        'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。无公开 API 的引擎走人工采样表。',
    )
    html = html.replace(
        '把成稿从「内容工作台」发到你自己的渠道。凭证写 .env；',
        '把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；',
    )
    html = html.replace(
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。无公开 API 的引擎走人工采样表。':'Click Configure to set keys & models (written to local .env, effective immediately). Engines without APIs use manual sheets.'",
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。无公开 API 的引擎走人工采样表。':'API keys are encrypted with AES-256-GCM and injected only while a job runs. Engines without public APIs use manual sample sheets.'",
    )
    html = html.replace(
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。无公开 API 的引擎走人工采样表。':'「設定」で Key とモデルを入力するとローカル .env に書き込まれ即時反映。API なしのエンジンは手動採取表で。'",
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。无公开 API 的引擎走人工采样表。':'API キーは AES-256-GCM で暗号化保存し、ジョブ実行中のみ注入します。公開 API のないエンジンは手動採取表を使用します。'",
    )
    html = html.replace("确定从 .env 删除 ${esc(k.env)}？", "确定删除 ${esc(k.label)} 的 API Key？")
    html = html.replace("toast(r.ok?'已写入 .env'", "toast(r.ok?'Key 已加密保存'")
    html = html.replace(
        '团队与权限：单机自托管版，无账号体系；服务只绑定 127.0.0.1。多人使用需自行加反向代理与认证。',
        '团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。',
    )
    html = html.replace(
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'Teams & auth: single-machine self-hosted, no account system; the server binds to 127.0.0.1 only. For multi-user, add your own reverse proxy with auth.'",
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'Team members use owner, editor, and viewer roles. Invitation links expire after 7 days.'",
    )
    html = html.replace(
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'チームと権限：単一マシンのセルフホスト版でアカウント機能なし。サービスは 127.0.0.1 のみにバインド。複数人利用はリバースプロキシと認証を追加。'",
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'メンバーは owner、editor、viewer のロールで管理され、招待リンクは 7 日間有効です。'",
    )
    html = html.replace(
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'チームと権限：単機セルフホスト版でアカウント機構なし。サーバーは 127.0.0.1 のみにバインド。複数人利用はリバースプロキシ+認証を自前で。'",
        "'团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'メンバーは owner、editor、viewer のロールで管理され、招待リンクは 7 日間有効です。'",
    )
    html = html.replace(
        '后台子进程执行，关掉页面也会跑完。同一项目同时只跑一个。',
        '后台任务队列执行，关掉页面也会跑完。同一项目同时只跑一个。',
    )
    html = html.replace(
        "'后台任务队列执行，关掉页面也会跑完。同一项目同时只跑一个。':'Jobs run as background subprocesses. One at a time per project.'",
        "'后台任务队列执行，关掉页面也会跑完。同一项目同时只跑一个。':'Jobs run in the background queue and continue after this page closes. One job runs per project at a time.'",
    )
    html = html.replace(
        "'后台任务队列执行，关掉页面也会跑完。同一项目同时只跑一个。':'バックグラウンドのサブプロセスで実行され、ページを閉じても完走。同一プロジェクトは同時 1 件のみ。'",
        "'后台任务队列执行，关掉页面也会跑完。同一项目同时只跑一个。':'ジョブはバックグラウンドキューで実行され、このページを閉じても継続します。プロジェクトごとに同時実行は 1 件です。'",
    )
    html = html.replace("'保存':'Save'", "'保存':'Save','下载 ZIP':'Download ZIP'", 1)
    html = html.replace("'保存':'保存'", "'保存':'保存','下载 ZIP':'ZIP をダウンロード'", 1)
    html = html.replace(
        '<td style="font-size:13px;color:var(--t600)">0</td>\n        <td><span class="tag tag-dim">未采样</span></td>',
        '<td style="font-size:13px;color:var(--t600)">—</td>\n        <td><span class="tag tag-dim">未测</span></td>',
    )
    html = html.replace(
        "${mktLabel(x.market)} · ${x.searched?'联网':'参数化知识'}",
        "${mktLabel(x.market)} · ${esc(x.sampling_mode || (x.searched?'API·联网':'API·参数化'))}",
    )
    html = html.replace(
        "${mktLabel(k.market)} · ${k.ok===false?'缺 API Key':'仅人工采样'}",
        "${mktLabel(k.market)} · ${k.ok===false?(k.search?'API·联网 · 缺 Key':'API·参数化 · 缺 Key'):'人工·网页端'}",
    )
    html = html.replace(
        '''    {who:'给客户',name:'交付包',desc:'诊断报告、优化方案、工单表（CSV）、验收表、资产目录与说明。',
     act:(D.deliveries||[]).length?`<a class="btn btn-primary" style="font-size:12px" target="_blank" href="/files/${SLUG}/delivery/${D.deliveries[0]}/index.html">打开</a>`
        :`<button class="btn btn-secondary" style="font-size:12px" onclick="runAction('deliver')">生成</button>`},
''',
        '''    {who:'给客户',name:'交付包',desc:'诊断报告、优化方案、工单表（CSV）、验收表、资产目录与说明。',
     act:(D.deliveries||[]).length?`<a class="btn btn-secondary" style="font-size:12px" target="_blank" href="/files/${SLUG}/delivery/${D.deliveries[0]}/index.html">打开</a>
          <button class="btn btn-primary" style="font-size:12px" onclick="downloadDelivery('${D.deliveries[0]}')">下载 ZIP</button>`
        :`<button class="btn btn-secondary" style="font-size:12px" onclick="runAction('deliver')">生成</button>`},
''',
        1,
    )
    html = html.replace(
        '''        ${(D.deliveries||[]).map(d=>`<div style="font-size:13px"><a target="_blank" href="/files/${SLUG}/delivery/${d}/index.html">${d}</a>
          <a class="muted" style="font-size:11.5px;margin-left:8px" href="/files/${SLUG}/delivery/${d}/03-工单表.csv">任务 CSV</a></div>`).join('')||'<span class="muted" style="font-size:12.5px">暂无</span>'}
''',
        '''        ${(D.deliveries||[]).map(d=>`<div class="row" style="font-size:13px;gap:8px"><a target="_blank" href="/files/${SLUG}/delivery/${d}/index.html">${d}</a>
          <a class="muted" style="font-size:11.5px" href="/files/${SLUG}/delivery/${d}/03-工单表.csv">任务 CSV</a>
          <button class="btn btn-ghost" style="font-size:11.5px;padding:2px 6px" onclick="downloadDelivery('${d}')">下载 ZIP</button></div>`).join('')||'<span class="muted" style="font-size:12.5px">暂无</span>'}
''',
        1,
    )
    html = html.replace(
        '''    <h4 style="font-size:16px;margin:30px 0 8px">自动交付</h4>
    <p class="muted" style="font-size:12.5px">本产品不内置定时器。要每周自动跑并发送，用 Claude 的 schedule 能力挂
      <code>geo.py serve --slug ${esc(SLUG)}</code>，跑完把 deliverables/ 发给收件人。</p>
''',
        "",
        1,
    )
    html = html.replace(
        "'本产品不内置定时器。要每周自动跑并发送，用 Claude 的 schedule 能力挂':'No built-in timer. For a weekly auto-run with delivery, schedule it via Claude with',\n",
        "",
    )
    html = html.replace(
        "'本产品不内置定时器。要每周自动跑并发送，用 Claude 的 schedule 能力挂':'タイマーは非内蔵。週次自動実行と送信は Claude の schedule 機能で',\n",
        "",
    )
    html = html.replace(
        "'把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；':'Publish finals from the Workbench to your own channels. Credentials live in .env; '",
        "'把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；':'Publish finals from the Workbench to your own channels. Credentials are encrypted with AES-256-GCM; '",
    )
    html = html.replace(
        "'把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；':'完成稿をワークベンチから自分のチャネルへ公開。認証情報は .env に。'",
        "'把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；':'完成稿をワークベンチから自分のチャネルへ公開。認証情報は AES-256-GCM で暗号化保存します。'",
    )
    html = html.replace("到期后看板运行时自动跑完整一期", "由后台调度自动跑完整一期")
    html = html.replace(
        '''      <div class="field"><label>官网域名 *</label><input id="ob-url" class="input" placeholder="https://example.com" value="${esc(ST.obUrl||'')}"></div>
      <div class="field"><label>品牌名称（留空自动从网页识别）</label><input id="ob-name" class="input" value="${esc(ST.obName||'')}"></div>
      <div class="field"><label>目标市场</label><div class="seg">
        ${[['cn','国内引擎'],['global','海外引擎'],['both','两者都要']].map(([m,l])=>`<label class="seg-opt"><input type="radio" name="obm" value="${m}" ${(ST.obMkt||'both')===m?'checked':''}>${l}</label>`).join('')}</div></div>
      <label class="row" style="gap:6px;font-size:13px"><input type="checkbox" id="ob-nosample" style="width:auto" ${ST.obNoSample?'checked':''}> 首期跳过采样（省时间，可稍后补）</label>
''',
        '''      <div class="field"><label>官网域名 *</label><input id="ob-url" class="input" placeholder="https://example.com" value="${esc(ST.obUrl||'')}"></div>
      <details style="padding-top:2px"><summary style="font-size:12.5px;color:var(--t500);cursor:pointer">高级设置</summary>
        <div class="field"><label>品牌名称（留空自动从网页识别）</label><input id="ob-name" class="input" value="${esc(ST.obName||'')}"></div>
        <div class="field"><label>目标市场</label><div class="seg">
          ${[['cn','国内引擎'],['global','海外引擎'],['both','两者都要']].map(([m,l])=>`<label class="seg-opt"><input type="radio" name="obm" value="${m}" ${(ST.obMkt||'both')===m?'checked':''}>${l}</label>`).join('')}</div></div>
        <label class="row" style="gap:6px;font-size:13px"><input type="checkbox" id="ob-nosample" style="width:auto" ${ST.obNoSample?'checked':''}> 首期跳过采样（省时间，可稍后补）</label>
      </details>
''',
        1,
    )
    html = html.replace(
        "${RUNNING?`<button class=\"btn btn-secondary\" style=\"font-size:12px\" onclick=\"stopJob()\">停止任务</button>`:''}",
        "",
    )
    html = html.replace(
        '<button class="btn btn-primary" onclick="runAction(\'verify\')">自动验收</button>',
        '<button class="btn btn-secondary" onclick="offsiteTicketModal()">创建 Offsite 工单</button>'
        '<button class="btn btn-primary" onclick="runAction(\'verify\')">自动验收</button>',
        1,
    )
    html = html.replace("<body>", "<body>" + FETCH_ADAPTER, 1)
    html = html.replace("</body>", UI_EXTENSION + "</body>", 1)
    return HTMLResponse(html)


@router.get("/files/{path:path}")
def serve_project_file(path: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """为 UI 提供当前租户项目交付文件，禁止跨租户和路径穿越。"""
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or ".." in path or "\\" in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_file_path"})
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    project = db.query(Project).filter(Project.tenant_id == tenant.id, Project.slug == parts[0]).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "file_not_found"})
    tenant_directory = engine_adapter.tenant_slug(tenant.name)
    root = (engine_adapter.WORK_ROOT / tenant_directory / project.slug).resolve()
    target = (root / parts[1]).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_file_path"}) from None
    if not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "file_not_found"})
    return FileResponse(target)
