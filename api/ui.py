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
  const nativeFetch = window.fetch.bind(window);
  const projectIds = new Map();
  let loginShown = false;
  let configuredKeyCount = 0;
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
      return nativeFetch('/api/v1/projects/' + id, init);
    }
    const configMatch = url.match(/^\/api\/config\/([^?]+)/);
    if (configMatch) {
      const id = projectIds.get(decodeURIComponent(configMatch[1]));
      if (!id) return response({error:'project_not_found'}, 404);
      return nativeFetch('/api/v1/projects/' + id + '/config', init.body
        ? {method:'PATCH',headers:init.headers,body:init.body} : init);
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
    if (publishMatch && !init.body) return response({publishers:[],records:[]});
    if (publishMatch || url.startsWith('/api/publishcfg/')) return response({ok:false,error:'publishing_not_available_in_mvp'}, 400);
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
      for (const env of Object.keys(updates)) {
        const code = envToCode[env];
        if (!code) return response({ok:false,error:'unsupported_key'}, 400);
        const value = String(updates[env] || '').trim();
        const r = value
          ? await nativeFetch('/api/v1/settings/keys', {method:'PUT', headers:Object.assign({}, init.headers, {'Content-Type':'application/json'}), body:JSON.stringify({engine_code:code,key_value:value})})
          : await nativeFetch('/api/v1/settings/keys/' + code, {method:'DELETE', headers:init.headers});
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
      return nativeFetch('/api/v1/projects/' + id + '/tickets/' + encodeURIComponent(body.id), {method:'PATCH',headers:init.headers,body:JSON.stringify({status:body.status,note:body.note || ''})});
    }
    return response({error:'legacy_ui_endpoint_not_supported'}, 404);
  };
  if (!localStorage.getItem('disvorai_access_token')) setTimeout(showLogin, 0);
})();
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
    html = html.replace("<body>", "<body>" + FETCH_ADAPTER, 1)
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
