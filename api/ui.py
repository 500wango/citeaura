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


FETCH_ADAPTER = r"""
<script>
(function () {
  const rawFetch = window.fetch.bind(window);
  const projectIds = new Map();
  let loginShown = false;
  let configuredKeyCount = 0;
  let refreshRequest = null;
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
      '<h2 style="margin:0 0 8px;color:#e9e9ed">DisvorAI</h2><p style="color:#b2b6ca;margin:0 0 18px">Sign in or create your workspace</p>' +
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
        await nativeFetch('/api/v1/auth/register', options);
        r = await nativeFetch('/api/v1/auth/login', options);
      }
      if (!r.ok) { this.querySelector('[data-error]').textContent = 'Unable to sign in with these credentials.'; return; }
      const data = await r.json();
      localStorage.setItem('disvorai_access_token', data.access_token);
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
    return response({error:'legacy_ui_endpoint_not_supported'}, 404);
  };
  if (!localStorage.getItem('disvorai_access_token')) setTimeout(showLogin, 0);
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

const engineCompetitorsView = vCompetitors;
vCompetitors = function () {
  const html = engineCompetitorsView();
  const anchor = '<div class="tabs" style="margin-top:18px">';
  return html.replace(anchor, framingPanel() + anchor);
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
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-primary" onclick="closeModal()">关闭</button></div>`);
};
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
        '当前工作区按租户隔离；成员邀请与角色管理暂未开放。',
    )
    html = html.replace(
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'Teams & auth: single-machine self-hosted, no account system; the server binds to 127.0.0.1 only. For multi-user, add your own reverse proxy with auth.'",
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'This workspace is tenant-isolated. Member invitations and role management are not available yet.'",
    )
    html = html.replace(
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'チームと権限：単一マシンのセルフホスト版でアカウント機能なし。サービスは 127.0.0.1 のみにバインド。複数人利用はリバースプロキシと認証を追加。'",
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'このワークスペースはテナントごとに分離されています。メンバー招待とロール管理はまだ利用できません。'",
    )
    html = html.replace(
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'チームと権限：単機セルフホスト版でアカウント機構なし。サーバーは 127.0.0.1 のみにバインド。複数人利用はリバースプロキシ+認証を自前で。'",
        "'当前工作区按租户隔离；成员邀请与角色管理暂未开放。':'このワークスペースはテナントごとに分離されています。メンバー招待とロール管理はまだ利用できません。'",
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
