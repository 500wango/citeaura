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
.billing-plan-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.billing-interval-switch{display:inline-flex;border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden}
.billing-interval-switch button{min-width:72px;border:0;border-radius:0}
.archive-row{display:grid;grid-template-columns:minmax(118px,.7fr) minmax(160px,1.5fr) minmax(86px,.6fr) auto;gap:10px;align-items:center;padding:9px 0;box-shadow:inset 0 -1px 0 var(--line);font-size:12px}
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
  .billing-section-title{padding-left:20px;scroll-margin-top:12px}
  .billing-plan-grid{grid-template-columns:1fr}
  .archive-section-title{padding-left:20px;scroll-margin-top:12px}
  .archive-row{grid-template-columns:1fr auto;gap:3px 8px}
  .archive-row-detail{grid-column:1/-1}
  .playbook-page{padding:24px 18px 56px}
  .playbook-page-head{align-items:flex-start!important;flex-direction:column}
  .playbook-stats{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .playbook-toolbar{align-items:flex-start;flex-direction:column}
}
"""


ADMIN_SHELL_STYLE = r"""
body{overflow-x:hidden}
#side{width:332px;display:flex;flex-direction:row;gap:0;padding:0;background:var(--side);overflow:visible;height:100dvh}
.global-rail{position:relative;z-index:2;width:108px;flex:none;display:flex;flex-direction:column;align-items:center;padding:12px 6px 10px;background:#131522;box-shadow:inset -1px 0 0 rgba(233,233,237,.10)}
.rail-brand{display:grid;place-items:center;width:44px;height:44px;border:0;border-radius:8px;background:transparent;cursor:pointer}
.rail-brand:hover{background:rgba(233,233,237,.07)}
.rail-brand img{display:block;width:32px;height:32px}
.rail-modules{display:flex;flex-direction:column;align-items:stretch;gap:6px;width:100%;margin-top:18px}
.rail-action{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;width:96px;min-height:50px;padding:6px 3px;border:0;border-radius:7px;background:transparent;color:var(--t600);font:500 10.5px/1.2 var(--font);letter-spacing:0;cursor:pointer}
.rail-action:hover{background:rgba(233,233,237,.06);color:var(--t400)}
.rail-action:active{transform:translateY(1px)}
.rail-action[aria-current="page"]{background:var(--a900);color:var(--a300);box-shadow:inset 3px 0 0 var(--accent)}
.rail-action .admin-icon{width:20px;height:20px}
.rail-footer{display:flex;flex-direction:column;align-items:center;gap:5px;margin-top:auto}
.rail-logout{min-height:38px}
.rail-action[data-tooltip]::after{position:absolute;left:102px;top:50%;z-index:80;max-width:180px;transform:translate(4px,-50%);padding:6px 8px;border:1px solid var(--divider);border-radius:5px;background:var(--surface);box-shadow:var(--sh-md);color:var(--text);font:12px/1.2 var(--font);white-space:nowrap;content:attr(data-tooltip);opacity:0;pointer-events:none;transition:opacity .12s,transform .12s}
.rail-action[data-tooltip]:hover::after,.rail-action[data-tooltip]:focus-visible::after{opacity:1;transform:translate(0,-50%)}
.module-panel{position:relative;z-index:1;width:224px;min-width:0;display:flex;flex-direction:column;padding:18px 12px 14px;background:var(--side);box-shadow:inset -1px 0 0 rgba(233,233,237,.10)}
.module-heading{display:flex;align-items:center;gap:8px;padding:0 7px 12px}
.module-heading strong{flex:1;min-width:0;font-size:16px;font-weight:600;letter-spacing:0}
.module-close{display:none;width:30px;height:30px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--t500);cursor:pointer}
.module-close:hover{background:rgba(233,233,237,.06);color:var(--text)}
.project-switcher-row{display:flex;flex-direction:column;gap:6px;margin:0 0 16px}
.project-switcher{display:flex;align-items:center;gap:9px;width:100%;min-height:58px;margin:0;padding:9px 10px;border:1px solid var(--divider);border-radius:7px;background:var(--deep);color:var(--text);text-align:left;cursor:pointer}
.project-switcher:hover{border-color:var(--t700);background:var(--surface)}
.project-switcher-copy{flex:1;min-width:0}
.project-switcher-label{display:block;margin-bottom:2px;color:var(--t600);font-size:10px;line-height:1.2;letter-spacing:0}
.project-switcher-name{display:block;overflow:hidden;color:var(--text);font-size:13px;line-height:1.35;text-overflow:ellipsis;white-space:nowrap}
.project-switcher .admin-icon{width:15px;height:15px;color:var(--t500)}
.project-add{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;min-height:34px;padding:7px 10px;border:1px solid var(--a700);border-radius:7px;background:var(--a900);color:var(--a300);font:500 12px/1.2 var(--font);letter-spacing:0;cursor:pointer}
.project-add:hover{border-color:var(--a500);background:var(--a800);color:var(--text)}
.project-add:active{transform:translateY(1px)}
.project-add .admin-icon{width:16px;height:16px}
.module-nav{display:flex;flex:1;min-height:0;flex-direction:column;gap:16px;overflow-y:auto;overscroll-behavior:contain;padding-right:1px}
.module-nav-group{display:flex;flex-direction:column;gap:2px}
.module-nav-label{padding:0 8px 5px;color:var(--t600);font-size:10px;font-weight:500;line-height:1.3;letter-spacing:0}
.module-link{display:flex;align-items:center;gap:8px;width:100%;min-height:34px;padding:7px 9px;border:0;border-radius:6px;background:transparent;color:var(--t400);font:500 13px/1.3 var(--font);letter-spacing:0;text-align:left;cursor:pointer}
.module-link:hover{background:rgba(233,233,237,.05);color:var(--text)}
.module-link:active{transform:translateY(1px)}
.module-link[aria-current="page"]{background:var(--a900);color:var(--text);box-shadow:inset 2px 0 0 var(--accent)}
.module-link-label{flex:1;min-width:0;overflow-wrap:anywhere}
.module-link .bdg{flex:none;color:var(--t600);font-size:10.5px}
.module-meta{margin-top:14px;padding:11px 8px 0;box-shadow:inset 0 1px 0 var(--line);color:var(--t600);font-size:10.5px;line-height:1.5}
.module-run{display:flex;align-items:center;gap:6px;margin-top:5px;padding:3px 0;border:0;background:transparent;color:var(--a300);font:500 11.5px/1.3 var(--font);cursor:pointer;text-align:left}
.module-run:hover{color:var(--text)}
.module-languages{display:flex;align-items:center;gap:3px;margin-top:10px}
.module-language{min-width:30px;padding:4px 6px;border:0;border-radius:5px;background:transparent;color:var(--t600);font:500 10.5px/1.2 var(--font);cursor:pointer}
.module-language:hover{background:rgba(233,233,237,.06);color:var(--t400)}
.module-language[aria-current="true"]{background:var(--a900);color:var(--a300)}
.admin-page{width:100%;max-width:1220px;padding:32px 44px 72px}
.admin-page-header{max-width:760px;margin-bottom:24px}
.admin-page-header h3{margin:0 0 7px;font-size:25px;font-weight:600;letter-spacing:0}
.admin-page-header p{margin:0;color:var(--t500);font-size:13px;line-height:1.55;text-wrap:pretty}
.admin-page-body>h4:first-child,.admin-page-body>.billing-section-title:first-child,.admin-page-body>.archive-section-title:first-child,.admin-page-body>.sso-section-title:first-child,.admin-page-body>.integration-section-title:first-child,.admin-page-body>.outreach-section-title:first-child{margin-top:0!important}
.admin-project-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}
.admin-config-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.admin-engine-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(150px,auto) auto;gap:10px;align-items:center;padding:9px 0;box-shadow:inset 0 -1px 0 var(--line)}
.admin-engine-row:last-child{box-shadow:none}
.admin-engine-name{min-width:0;overflow-wrap:anywhere;font-size:13px}
.admin-engine-mode{color:var(--t600);font-size:11.5px;text-align:right;white-space:nowrap}
.admin-run-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.admin-publisher-row{display:grid;grid-template-columns:minmax(170px,1fr) minmax(120px,auto) auto;gap:10px;align-items:center;padding:9px 0;box-shadow:inset 0 -1px 0 var(--line)}
.admin-publisher-row:last-child{box-shadow:none}
@media (max-width:700px){
  .admin-page{padding:24px 18px 56px}
  .admin-config-grid{grid-template-columns:1fr}
  .admin-engine-row,.admin-publisher-row{grid-template-columns:1fr auto;gap:4px 8px}
  .admin-engine-mode,.admin-publisher-state{grid-column:1/-1;text-align:left}
}
.admin-icon{display:inline-block;flex:none;width:18px;height:18px;background:currentColor;mask:var(--admin-icon) center/contain no-repeat;-webkit-mask:var(--admin-icon) center/contain no-repeat}
.icon-layout-dashboard{--admin-icon:url('/site-assets/icons/layout-dashboard.svg')}
.icon-radar{--admin-icon:url('/site-assets/icons/radar.svg')}
.icon-scan-search{--admin-icon:url('/site-assets/icons/scan-search.svg')}
.icon-list-checks{--admin-icon:url('/site-assets/icons/list-checks.svg')}
.icon-package-check{--admin-icon:url('/site-assets/icons/package-check.svg')}
.icon-settings-2{--admin-icon:url('/site-assets/icons/settings-2.svg')}
.icon-chevron-down{--admin-icon:url('/site-assets/icons/chevron-down.svg')}
.icon-log-out{--admin-icon:url('/site-assets/icons/log-out.svg')}
.icon-x{--admin-icon:url('/site-assets/icons/x.svg')}
.icon-menu{--admin-icon:url('/site-assets/icons/menu.svg')}
.icon-plus{--admin-icon:url('/site-assets/icons/plus.svg')}
#burger{width:36px;height:36px;padding:0;border-color:var(--divider);background:var(--side);box-shadow:var(--sh-sm)}
#burger .admin-icon{width:18px;height:18px}
#nav-scrim{display:none;position:fixed;inset:0;z-index:45;border:0;background:rgba(9,10,17,.58);cursor:pointer}
@media (max-width:1199px){
  .module-close{display:grid;place-items:center}
  #side{z-index:50}
  #side.open+#nav-scrim{display:block}
}
@media (min-width:900px) and (max-width:1199px){
  #side{width:108px;position:sticky;left:0;top:0}
  .module-panel{position:fixed;left:108px;top:0;height:100dvh;transform:translateX(calc(-100% - 2px));box-shadow:var(--sh-md);transition:transform .2s cubic-bezier(.16,1,.3,1)}
  #side.open .module-panel{transform:translateX(0)}
  #burger{display:none}
}
@media (max-width:899px){
  #burger{display:grid;place-items:center;top:10px;left:10px}
  #side{position:fixed;left:calc(-100vw - 20px);top:0;width:min(320px,calc(100vw - 36px));transition:left .2s cubic-bezier(.16,1,.3,1);box-shadow:var(--sh-md)}
  #side.open{left:0}
  .global-rail{width:108px}
  .module-panel{width:auto;flex:1}
  #main{margin-left:0;padding-top:52px}
  .rail-action[data-tooltip]::after{display:none}
}
@media (max-width:420px){
  #side{width:calc(100vw - 24px)}
  .module-panel{padding-inline:10px}
}
@media (prefers-reduced-motion:reduce){
  .module-panel,#side,.rail-action[data-tooltip]::after{transition:none}
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
  const resetToken = new URLSearchParams(location.search).get('reset_token') || '';
  const keyCatalog = [
    {code:'glm', labels:{zh:'智谱 GLM',en:'Zhipu AI GLM',ja:'Zhipu AI GLM'}, market:'cn', env:'ZHIPUAI_API_KEY', search:false},
    {code:'doubao', labels:{zh:'豆包（方舟 API）',en:'Doubao Ark API',ja:'Doubao（Ark API）'}, market:'cn', env:'ARK_API_KEY', search:true},
    {code:'deepseek', labels:{zh:'DeepSeek',en:'DeepSeek',ja:'DeepSeek'}, market:'cn', env:'DEEPSEEK_API_KEY', search:false},
    {code:'kimi', labels:{zh:'Kimi',en:'Kimi',ja:'Kimi'}, market:'cn', env:'MOONSHOT_API_KEY', search:false},
    {code:'minimax', labels:{zh:'MiniMax',en:'MiniMax',ja:'MiniMax'}, market:'cn', env:'MINIMAX_API_KEY', search:false},
    {code:'gemini', labels:{zh:'Gemini',en:'Gemini',ja:'Gemini'}, market:'global', env:'GEMINI_API_KEY', search:false},
    {code:'openai', labels:{zh:'OpenAI（ChatGPT）',en:'OpenAI (ChatGPT)',ja:'OpenAI（ChatGPT）'}, market:'global', env:'OPENAI_API_KEY', search:false},
    {code:'claude', labels:{zh:'Claude',en:'Claude',ja:'Claude'}, market:'global', env:'ANTHROPIC_API_KEY', search:false},
    {code:'grok', labels:{zh:'Grok',en:'Grok',ja:'Grok'}, market:'global', env:'XAI_API_KEY', search:false},
    {code:'perplexity', labels:{zh:'Perplexity',en:'Perplexity',ja:'Perplexity'}, market:'global', env:'PERPLEXITY_API_KEY', search:true},
    {code:'nano_ai', labels:{zh:'纳米 AI 搜索（360）',en:'Nano AI Search (360)',ja:'Nano AI 検索（360）'}, market:'cn', env:null, search:true, manual:true},
    {code:'baidu', labels:{zh:'百度 AI 搜索',en:'Baidu AI Search',ja:'百度 AI 検索'}, market:'cn', env:null, search:true, manual:true},
    {code:'doubao_app', labels:{zh:'豆包 App / 网页版',en:'Doubao app / web',ja:'Doubao アプリ / ウェブ'}, market:'cn', env:null, search:true, manual:true},
    {code:'chatgpt', labels:{zh:'ChatGPT 网页版（开启 Search）',en:'ChatGPT web (Search enabled)',ja:'ChatGPT ウェブ（Search 有効）'}, market:'global', env:null, search:true, manual:true},
    {code:'claude_web', labels:{zh:'Claude 网页版（开启 Web Search）',en:'Claude web (Web Search enabled)',ja:'Claude ウェブ（Web Search 有効）'}, market:'global', env:null, search:true, manual:true}
  ];
  function selectedLocale() {
    const requested = new URLSearchParams(location.search).get('lang');
    const saved = localStorage.getItem('ulang');
    const browser = (navigator.language || '').toLowerCase();
    const locale = requested || saved || (browser.indexOf('zh') === 0 ? 'zh' : browser.indexOf('ja') === 0 ? 'ja' : 'en');
    return ['zh','en','ja'].includes(locale) ? locale : 'en';
  }
  function localizedModelLabel(model, fallback) {
    const entry = typeof model === 'string' ? keyCatalog.find(function (item) { return item.code === model; }) : model;
    if (!entry) return fallback || '';
    return (entry.labels || {})[selectedLocale()] || (entry.labels || {}).en || fallback || entry.code;
  }
  window.disvoraiModelLabel = localizedModelLabel;
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

  const authStyles = `
    #disvorai-login{position:fixed;inset:0;z-index:9999;background:#161826;display:grid;place-items:center;padding:24px;overflow:auto;font:15px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e9e9ed}
    #disvorai-login *{box-sizing:border-box}
    .disvorai-auth-card{width:min(420px,100%);padding:28px;background:#232532;border:1px solid #343747;border-radius:8px;box-shadow:0 18px 60px #0008}
    .disvorai-auth-brand{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:7px}
    .disvorai-auth-brand strong{font-size:20px;font-weight:600;letter-spacing:0}
    .disvorai-auth-kicker{font-size:11px;letter-spacing:0;text-transform:uppercase;color:#858aa1}
    .disvorai-auth-copy{margin:0 0 18px;color:#b2b6ca;font-size:13px;line-height:1.55}
    .disvorai-auth-tabs{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin:0 0 18px;padding:3px;background:#1b1d2b;border:1px solid #3d4151;border-radius:6px}
    .disvorai-auth-tabs button{border:0;border-radius:4px;background:transparent;color:#9da2b7;padding:9px 8px;font:600 12.5px system-ui;cursor:pointer}
    .disvorai-auth-tabs button[aria-selected="true"]{background:#393449;color:#eeeaff;box-shadow:0 0 0 1px #6d5fb0}
    .disvorai-auth-field{display:block;margin:0 0 13px;color:#bfc3d2;font-size:12px}
    .disvorai-auth-field input{display:block;width:100%;margin-top:5px;padding:10px 11px;background:#1b1d2b;color:#e9e9ed;border:1px solid #595d6c;border-radius:6px;font:14px system-ui}
    .disvorai-auth-field input:focus{outline:2px solid #7e71c5;outline-offset:1px;border-color:#a69be6}
    .disvorai-auth-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 0 15px}
    .disvorai-auth-link{border:0;background:transparent;color:#a69be6;padding:3px 0;font:12px system-ui;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
    .disvorai-auth-submit{display:block;width:100%;padding:10px 12px;background:#9184d9;color:#161826;border:0;border-radius:6px;font:600 13px system-ui;cursor:pointer}
    .disvorai-auth-submit:hover{background:#a69be6}
    .disvorai-auth-submit:disabled{cursor:wait;opacity:.55}
    .disvorai-auth-message{min-height:20px;margin:12px 0 0;font-size:12px;line-height:1.5}
    .disvorai-auth-message[data-kind="error"]{color:#f09a9a}
    .disvorai-auth-message[data-kind="success"]{color:#9fd5b2}
    .disvorai-auth-message[data-kind="info"]{color:#b2b6ca}
    .disvorai-auth-footer{margin:16px 0 0;text-align:center;color:#747a92;font-size:11px}
    @media (max-width:480px){#disvorai-login{padding:14px}.disvorai-auth-card{padding:22px 18px}.disvorai-auth-actions{align-items:flex-start;flex-direction:column}.disvorai-auth-link{padding:0}}
  `;

  function authErrorMessage(data, statusCode, action) {
    const raw = (data && (data.error || (data.detail && data.detail.error) || data.detail)) || '';
    const messages = {
      invalid_credentials:'邮箱或密码不正确。', email_already_registered:'该邮箱已注册，请切换到登录。',
      invitation_invalid:'邀请链接无效或已失效。', invitation_already_accepted:'该邀请已被接受。', invitation_expired:'邀请链接已过期。',
      invitation_email_mismatch:'注册邮箱必须与邀请邮箱一致。', password_reset_token_invalid:'重置链接无效或已过期，请重新申请。',
      no_tenant_membership:'该账号暂未加入工作区。', rate_limited:'操作过于频繁，请稍后再试。'
    };
    if (messages[raw]) return messages[raw];
    if (Array.isArray(raw)) return raw.map(function (item) { return item.msg || item.message || ''; }).filter(Boolean).join('；') || '请检查输入。';
    if (statusCode === 429) return messages.rate_limited;
    return action === 'login' ? '登录失败，请检查邮箱和密码。' : action === 'register' ? '注册失败，请检查填写的信息。' : '操作失败，请稍后再试。';
  }

  async function authJson(url, body) {
    const result = await rawFetch(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data = await result.json().catch(function () { return {}; });
    return {result:result,data:data};
  }

  function clearAuthQuery() {
    history.replaceState({}, '', location.pathname + location.hash);
  }

  async function acceptInvitationWithToken(token, accessToken) {
    if (!token) return {access_token:accessToken};
    const accepted = await rawFetch('/api/v1/team/invitations/accept', {
      method:'POST', headers:{'Content-Type':'application/json',Authorization:'Bearer ' + accessToken},
      body:JSON.stringify({token:token})
    });
    const data = await accepted.json().catch(function () { return {}; });
    return {result:accepted,data:data,access_token:data.access_token || accessToken};
  }

  function showLogin() {
    if (loginShown || (localStorage.getItem('disvorai_access_token') && !resetToken)) return;
    loginShown = true;
    const box = document.createElement('div');
    box.id = 'disvorai-login';
    if (!document.getElementById('disvorai-auth-styles')) {
      const style = document.createElement('style');
      style.id = 'disvorai-auth-styles';
      style.textContent = authStyles;
      document.head.appendChild(style);
    }
    document.body.appendChild(box);
    let mode = resetToken ? 'reset' : 'login';
    let busy = false;
    let message = resetToken ? {kind:'info',text:'请输入新密码。'} : null;
    let savedEmail = '';

    function setMessage(kind, text) { message = text ? {kind:kind,text:text} : null; }
    function renderAuth() {
      const invitationCopy = invitationToken ? '你正在接受工作区邀请。已有账号请选择登录，新账号请选择注册。' : '登录后查看项目报告，或创建一个新的工作区。';
      const isReset = mode === 'reset', isForgot = mode === 'forgot', isRegister = mode === 'register';
      const title = isReset ? '设置新密码' : isForgot ? '找回密码' : isRegister ? '创建工作区' : '登录 DisvorAI';
      const copy = isReset ? '设置完成后，之前的登录会话将失效。' : isForgot ? '输入账号邮箱，我们会发送重置链接。' : (isRegister ? invitationCopy : (invitationToken ? invitationCopy : '登录后查看项目报告，或创建一个新的工作区。'));
      const tabs = (!isReset && !isForgot) ? `<div class="disvorai-auth-tabs" role="tablist" aria-label="认证模式">
        <button type="button" data-auth-mode="login" role="tab" aria-selected="${mode==='login'}">登录</button>
        <button type="button" data-auth-mode="register" role="tab" aria-selected="${isRegister}">注册</button></div>` : '';
      let fields = '';
      if (isReset) fields = `<label class="disvorai-auth-field">新密码<input name="password" type="password" minlength="8" autocomplete="new-password" required></label>
        <label class="disvorai-auth-field">确认新密码<input name="confirm_password" type="password" minlength="8" autocomplete="new-password" required></label>`;
      else {
        fields += '<label class="disvorai-auth-field">邮箱<input name="email" type="email" autocomplete="email" required></label>';
        if (isRegister) fields += invitationToken ? '<div class="disvorai-auth-field" style="padding:9px 10px;border:1px solid #3d4151;border-radius:6px;background:#1b1d2b;color:#9da2b7">邀请将加入已有工作区</div>' : '<label class="disvorai-auth-field">工作区名称<input name="tenant_name" type="text" minlength="2" maxlength="128" autocomplete="organization" required></label>';
        if (!isForgot) fields += `<label class="disvorai-auth-field">密码<input name="password" type="password" minlength="8" autocomplete="${isRegister?'new-password':'current-password'}" required></label>`;
        if (isRegister) fields += '<label class="disvorai-auth-field">确认密码<input name="confirm_password" type="password" minlength="8" autocomplete="new-password" required></label>';
      }
      const actions = isReset ? '<button type="button" class="disvorai-auth-link" data-auth-mode="login">返回登录</button>' : isForgot ? '<button type="button" class="disvorai-auth-link" data-auth-mode="login">返回登录</button>' : (mode==='login' ? '<button type="button" class="disvorai-auth-link" data-auth-mode="forgot">忘记密码？</button>' : '<span></span>');
      const submit = isReset ? '更新密码' : isForgot ? '发送重置链接' : isRegister ? '创建账号' : '登录';
      box.innerHTML = `<div class="disvorai-auth-card" role="dialog" aria-labelledby="disvorai-auth-title"><div class="disvorai-auth-brand"><strong id="disvorai-auth-title">${title}</strong><span class="disvorai-auth-kicker">DisvorAI</span></div>
        <p class="disvorai-auth-copy">${copy}</p>${tabs}<form novalidate>${fields}<div class="disvorai-auth-actions">${actions}</div>
        <button class="disvorai-auth-submit" type="submit" ${busy?'disabled':''}>${busy?'处理中…':submit}</button>
        <p class="disvorai-auth-message" data-kind="${message ? message.kind : 'info'}" role="${message && message.kind==='error'?'alert':'status'}"></p></form>
        <p class="disvorai-auth-footer">你的工作区数据按租户隔离保存</p></div>`;
      const messageNode = box.querySelector('.disvorai-auth-message');
      if (message) messageNode.textContent = message.text;
      box.querySelectorAll('[data-auth-mode]').forEach(function (button) {
        button.addEventListener('click', function () { if (busy) return; mode = button.getAttribute('data-auth-mode'); setMessage(null, ''); renderAuth(); });
      });
      const form = box.querySelector('form');
      form.addEventListener('submit', handleSubmit);
      const emailInput = form.querySelector('[name="email"]');
      if (emailInput) {
        emailInput.value = savedEmail;
        emailInput.addEventListener('input', function () { savedEmail = emailInput.value; });
      }
      const first = form.querySelector('input');
      if (first) setTimeout(function () { first.focus(); }, 0);
    }

    async function handleSubmit(event) {
      event.preventDefault();
      if (busy) return;
      const form = event.currentTarget;
      const value = function (name) { const field = form.elements[name]; return field ? String(field.value || '').trim() : ''; };
      const email = value('email'), password = value('password'), confirmPassword = value('confirm_password');
      savedEmail = email;
      if ((mode === 'login' || mode === 'register' || mode === 'forgot') && (!email || !email.includes('@'))) { setMessage('error', '请输入有效的邮箱地址。'); renderAuth(); return; }
      if ((mode === 'login' || mode === 'register') && password.length < 8) { setMessage('error', '密码至少需要 8 个字符。'); renderAuth(); return; }
      if ((mode === 'register' || mode === 'reset') && password !== confirmPassword) { setMessage('error', '两次输入的密码不一致。'); renderAuth(); return; }
      if (mode === 'register' && !invitationToken && value('tenant_name').length < 2) { setMessage('error', '请填写工作区名称。'); renderAuth(); return; }
      const action = mode;
      busy = true; setMessage('info', ''); renderAuth();
      try {
        if (action === 'forgot') {
          const answer = await authJson('/api/v1/auth/password/forgot', {email:email});
          busy = false; setMessage(answer.result.ok ? 'success' : 'error', answer.result.ok ? '如果邮箱已注册，重置链接会发送到你的邮箱。' : authErrorMessage(answer.data, answer.result.status, 'forgot')); renderAuth(); return;
        }
        if (action === 'reset') {
          const answer = await authJson('/api/v1/auth/password/reset', {token:resetToken,password:password});
          busy = false;
          if (!answer.result.ok) { setMessage('error', authErrorMessage(answer.data, answer.result.status, 'reset')); renderAuth(); return; }
          localStorage.removeItem('disvorai_access_token'); projectIds.clear(); clearAuthQuery(); mode = 'login'; setMessage('success', '密码已更新，请使用新密码登录。'); renderAuth(); return;
        }
        if (action === 'register') {
          const registration = {email:email,password:password,tenant_name:invitationToken ? null : value('tenant_name'),invitation_token:invitationToken || null};
          const registered = await authJson('/api/v1/auth/register', registration);
          if (!registered.result.ok) { busy = false; setMessage('error', authErrorMessage(registered.data, registered.result.status, 'register')); renderAuth(); return; }
        }
        const loggedIn = await authJson('/api/v1/auth/login', {email:email,password:password});
        if (!loggedIn.result.ok || !loggedIn.data.access_token) { busy = false; setMessage('error', authErrorMessage(loggedIn.data, loggedIn.result.status, 'login')); renderAuth(); return; }
        let accessToken = loggedIn.data.access_token;
        if (invitationToken) {
          const accepted = await acceptInvitationWithToken(invitationToken, accessToken);
          if (!accepted.result || !accepted.result.ok) { busy = false; setMessage('error', authErrorMessage(accepted.data, accepted.result && accepted.result.status, 'invite')); renderAuth(); return; }
          accessToken = accepted.access_token;
        }
        localStorage.setItem('disvorai_access_token', accessToken); projectIds.clear(); clearAuthQuery(); location.reload();
      } catch (error) {
        busy = false; setMessage('error', '网络暂时不可用，请稍后再试。'); renderAuth();
      }
    }
    renderAuth();
  }

  async function logout() {
    try { await rawFetch('/api/v1/auth/logout', {method:'POST'}); }
    finally {
      localStorage.removeItem('disvorai_access_token');
      projectIds.clear();
      configuredKeyCount = 0;
      refreshRequest = null;
      location.assign('/app');
    }
  }
  window.disvoraiLogout = logout;

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
          url:body.url, name:body.name || null, skip_llm:configuredKeyCount === 0,
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
        return Object.assign({}, k, {label:localizedModelLabel(k), ok:k.manual ? null : !!current, key_tail:current ? current.masked.slice(-4) : ''});
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
    if (url === '/api/billing') {
      if (!init.body) {
        const results = await Promise.all([
          nativeFetch('/api/v1/billing/plans', init),
          nativeFetch('/api/v1/billing/usage', init)
        ]);
        const catalog = await results[0].json().catch(function () { return {}; });
        const usage = await results[1].json().catch(function () { return {}; });
        return response(Object.assign({}, catalog, {usage:usage}), results[1].status);
      }
      const body = JSON.parse(init.body);
      return nativeFetch('/api/v1/billing/subscribe', {
        method:'POST',headers:init.headers,
        body:JSON.stringify({plan:body.plan,billing_interval:body.billing_interval})
      });
    }
    if (url === '/api/archive') {
      const id = projectIds.get(SLUG);
      if (!id) return response({error:'project_not_found'}, 404);
      const base = '/api/v1/projects/' + id + '/archives';
      if (!init.body) return nativeFetch(base, init);
      const body = JSON.parse(init.body);
      if (body.action === 'create') return nativeFetch(base, {method:'POST',headers:init.headers});
      if (body.action === 'restore') return nativeFetch(base + '/' + encodeURIComponent(body.archive_id) + '/restore', {
        method:'POST',headers:init.headers,
        body:JSON.stringify({overwrite:body.overwrite,confirmed:body.confirmed,confirmation_text:body.confirmation_text})
      });
      return response({error:'archive_action_invalid'}, 400);
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
  if (resetToken || !localStorage.getItem('disvorai_access_token')) setTimeout(showLogin, 0);
  else if (invitationToken) setTimeout(acceptPendingInvitation, 0);
})();
</script>
"""


UI_EXTENSION = r"""
<script>
const ADMIN_MODULES = [
  {id:'overview',icon:'layout-dashboard',label:{zh:'概览',en:'Overview',ja:'概要'},defaultRoute:'overview',groups:[
    {items:[{route:'overview',label:{zh:'品牌概览',en:'Brand overview',ja:'ブランド概要'}}]}
  ]},
  {id:'monitoring',icon:'radar',label:{zh:'监测',en:'Monitoring',ja:'モニタリング'},defaultRoute:'engines',groups:[
    {items:[
      {route:'engines',label:{zh:'AI 可见性',en:'AI visibility',ja:'AI 可視性'}},
      {route:'competitors',label:{zh:'竞品分析',en:'Competitor analysis',ja:'競合分析'}},
      {route:'questions',label:{zh:'追踪问题',en:'Tracked prompts',ja:'追跡プロンプト'}}
    ]}
  ]},
  {id:'diagnosis',icon:'scan-search',label:{zh:'诊断',en:'Diagnosis',ja:'診断'},defaultRoute:'siteaudit',groups:[
    {items:[
      {route:'siteaudit',label:{zh:'网站审计',en:'Website audit',ja:'サイト監査'}},
      {route:'gaps',label:{zh:'内容差距',en:'Content gaps',ja:'コンテンツギャップ'}},
      {route:'channels',label:{zh:'引用来源',en:'Citation sources',ja:'引用ソース'}},
      {route:'facts',label:{zh:'品牌事实',en:'Brand facts',ja:'ブランドファクト'}}
    ]}
  ]},
  {id:'execution',icon:'list-checks',label:{zh:'执行',en:'Execution',ja:'実行'},defaultRoute:'plan',groups:[
    {items:[
      {route:'plan',label:{zh:'行动计划',en:'Action plan',ja:'アクションプラン'}},
      {route:'workbench',label:{zh:'内容工作台',en:'Content studio',ja:'コンテンツスタジオ'}},
      {route:'assets',label:{zh:'部署资产',en:'Deployment assets',ja:'デプロイアセット'}},
      {route:'outreach',label:{zh:'外部联络',en:'Outreach',ja:'アウトリーチ'}}
    ]}
  ]},
  {id:'delivery',icon:'package-check',label:{zh:'交付',en:'Delivery',ja:'納品'},defaultRoute:'verify',groups:[
    {items:[
      {route:'verify',label:{zh:'验证',en:'Verification',ja:'検証'}},
      {route:'report',label:{zh:'报告与交付',en:'Reports and deliverables',ja:'レポートと成果物'}},
      {route:'publishing',label:{zh:'发布目的地',en:'Publishing destinations',ja:'公開先'}},
      {route:'branding',label:{zh:'白标报告',en:'White-label reports',ja:'ホワイトラベルレポート'}}
    ]}
  ]},
  {id:'management',icon:'settings-2',label:{zh:'管理',en:'Admin',ja:'管理'},defaultRoute:'project-settings',groups:[
    {label:{zh:'品牌',en:'Brand',ja:'ブランド'},items:[
      {route:'project-settings',label:{zh:'品牌管理',en:'Brand management',ja:'ブランド管理'}},
      {route:'automation',label:{zh:'运行与调度',en:'Runs and schedules',ja:'実行とスケジュール'}},
      {route:'archive',label:{zh:'项目归档',en:'Project archive',ja:'プロジェクトアーカイブ'}}
    ]},
    {label:{zh:'连接',en:'Connections',ja:'接続'},items:[
      {route:'engine-settings',label:{zh:'模型与测量',en:'Models and measurement',ja:'モデルと測定'}},
      {route:'integrations',label:{zh:'数据源',en:'Data sources',ja:'データソース'}}
    ]},
    {label:{zh:'组织',en:'Organization',ja:'組織'},items:[
      {route:'team',label:{zh:'团队与权限',en:'Team and access',ja:'チームと権限'}},
      {route:'billing',label:{zh:'套餐与账单',en:'Plans and billing',ja:'プランと請求'}},
      {route:'security',label:{zh:'企业安全',en:'Enterprise security',ja:'エンタープライズセキュリティ'}}
    ]}
  ]}
];
const ADMIN_ROUTE_ALIASES = {settings:'project-settings'};

Object.assign(UI_D.en, {
  '品牌管理':'Brand management','管理品牌清单、官网域名和竞品范围。':'Manage brands, official domains, and competitor scope.',
  '品牌':'Brand','网站审计均分':'Website audit average','添加品牌':'Add brand','编辑当前品牌':'Edit current brand',
  '运行与调度':'Runs and schedules','手动运行完整管线、执行单项任务，或设置固定复跑周期。':'Run the full pipeline, execute individual jobs, or set a recurring schedule.',
  '任务由后台队列执行，关闭页面后仍会继续。同一项目同时只运行一个任务。':'Jobs continue in the background queue after this page closes. Each project runs one job at a time.',
  '全自动引导':'Guided automation','跑完整一期':'Run full cycle','关闭':'Off','任务运行中':'Job running',
  '项目归档':'Project archive','创建项目文件快照，并在需要时恢复到本地文件系统。':'Create project snapshots and restore them to the local filesystem when needed.',
  '模型与测量':'Models and measurement','配置 AI 模型凭证、查看测量方式，并管理可选的托管用量。':'Configure AI model credentials, review measurement methods, and use managed usage when needed.',
  'AI 模型':'AI models','API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。BYOK 始终优先。':'API keys are encrypted with AES-256-GCM and injected only while jobs run. BYOK always takes priority.',
  '智谱GLM':'Zhipu AI GLM','智谱 GLM':'Zhipu AI GLM',
  '豆包(方舟API)':'Doubao Ark API','豆包（方舟 API）':'Doubao Ark API',
  'OpenAI(ChatGPT)':'OpenAI (ChatGPT)','OpenAI（ChatGPT）':'OpenAI (ChatGPT)',
  '纳米AI搜索（360）':'Nano AI Search (360)','纳米 AI 搜索（360）':'Nano AI Search (360)',
  '百度 AI 搜索':'Baidu AI Search',
  '豆包 App / 网页版（与方舟 API 结果不同，需分开采）':'Doubao app / web (measured separately from Ark API)',
  'ChatGPT 网页版（开 Search）':'ChatGPT web (Search enabled)',
  'Claude 网页版（开 Web Search）':'Claude web (Web Search enabled)',
  '已连接':'Connected','人工':'Manual','未连接':'Not connected',
  '数据源':'Data sources','连接外部搜索数据源，为诊断和成效分析补充可核验数据。':'Connect external data sources to add verifiable evidence to diagnosis and outcome analysis.',
  '管理 SMTP 连接和联络草稿。每封邮件都需要人工检查并确认发送。':'Manage SMTP connections and outreach drafts. Every email requires human review and confirmation.',
  '发布目的地':'Publishing destinations','配置发布目的地并查看发布记录。所有对外发布都由用户手动发起。':'Configure publishing destinations and review history. Every external publication is started manually.',
  '发布凭证加密保存。发布只能由用户手动触发，WeChat Official Account 和 WordPress 仅创建草稿。':'Publishing credentials are encrypted. Publishing is manual, and WeChat Official Account and WordPress only create drafts.',
  '暂无发布目的地':'No publishing destinations','最近发布':'Recent publications','成功':'Succeeded',
  '为客户报告和打印版交付物配置机构名称、Logo 和主题色。':'Configure organization details, logo, and accent color for client reports and print-ready deliverables.',
  '团队与权限':'Team and access','管理工作区成员、邀请和 owner、editor、viewer 角色。':'Manage workspace members, invitations, and owner, editor, and viewer roles.',
  '查看当前套餐和用量，并由工作区所有者管理订阅。':'Review the current plan and usage. Workspace owners manage subscriptions.',
  '企业安全':'Enterprise security','配置 OIDC 单点登录，查看安全控制状态和最近审计事件。':'Configure OIDC single sign-on and review security controls and recent audit events.'
});
Object.assign(UI_D.ja, {
  '品牌管理':'ブランド管理','管理品牌清单、官网域名和竞品范围。':'ブランド、公式サイト、競合範囲を管理します。',
  '品牌':'ブランド','网站审计均分':'サイト監査平均','添加品牌':'ブランドを追加','编辑当前品牌':'現在のブランドを編集',
  '运行与调度':'実行とスケジュール','手动运行完整管线、执行单项任务，或设置固定复跑周期。':'パイプライン全体または個別ジョブを実行し、定期実行を設定します。',
  '任务由后台队列执行，关闭页面后仍会继续。同一项目同时只运行一个任务。':'ジョブはバックグラウンドキューで継続します。プロジェクトごとに同時実行は 1 件です。',
  '全自动引导':'自動ガイド','跑完整一期':'フルサイクルを実行','关闭':'オフ','任务运行中':'ジョブ実行中',
  '数据归档':'データアーカイブ','创建项目文件快照，并在需要时恢复到本地文件系统。':'プロジェクトのスナップショットを作成し、必要に応じてローカルファイルへ復元します。',
  '模型与测量':'モデルと測定','配置 AI 模型凭证、查看测量方式，并管理可选的托管用量。':'AI モデルの認証情報、測定方式、任意のプラットフォーム利用を管理します。',
  'AI 模型':'AI モデル','API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。BYOK 始终优先。':'API キーは AES-256-GCM で暗号化され、ジョブ実行中のみ注入されます。BYOK が常に優先されます。',
  '智谱GLM':'Zhipu AI GLM','智谱 GLM':'Zhipu AI GLM',
  '豆包(方舟API)':'Doubao（Ark API）','豆包（方舟 API）':'Doubao（Ark API）',
  'OpenAI(ChatGPT)':'OpenAI（ChatGPT）','OpenAI（ChatGPT）':'OpenAI（ChatGPT）',
  '纳米AI搜索（360）':'Nano AI 検索（360）','纳米 AI 搜索（360）':'Nano AI 検索（360）',
  '百度 AI 搜索':'百度 AI 検索',
  '豆包 App / 网页版（与方舟 API 结果不同，需分开采）':'Doubao アプリ / ウェブ（Ark API とは別に測定）',
  'ChatGPT 网页版（开 Search）':'ChatGPT ウェブ（Search 有効）',
  'Claude 网页版（开 Web Search）':'Claude ウェブ（Web Search 有効）',
  '已连接':'接続済み','人工':'手動','未连接':'未接続',
  '数据源':'データソース','连接外部搜索数据源，为诊断和成效分析补充可核验数据。':'外部データソースを接続し、診断と成果分析に検証可能な証拠を追加します。',
  '管理 SMTP 连接和联络草稿。每封邮件都需要人工检查并确认发送。':'SMTP 接続と連絡下書きを管理します。すべてのメールで人による確認が必要です。',
  '发布目的地':'公開先','配置发布目的地并查看发布记录。所有对外发布都由用户手动发起。':'公開先と履歴を管理します。外部公開はすべて手動で開始します。',
  '发布凭证加密保存。发布只能由用户手动触发，WeChat Official Account 和 WordPress 仅创建草稿。':'公開認証情報は暗号化されます。公開は手動で、WeChat Official Account と WordPress は下書きのみ作成します。',
  '暂无发布目的地':'公開先はありません','最近发布':'最近の公開','成功':'成功',
  '为客户报告和打印版交付物配置机构名称、Logo 和主题色。':'顧客レポートと印刷用成果物の組織名、ロゴ、テーマ色を設定します。',
  '团队与权限':'チームと権限','管理工作区成员、邀请和 owner、editor、viewer 角色。':'ワークスペースのメンバー、招待、owner、editor、viewer ロールを管理します。',
  '查看当前套餐和用量，并由工作区所有者管理订阅。':'現在のプランと使用量を確認し、オーナーがサブスクリプションを管理します。',
  '企业安全':'エンタープライズセキュリティ','配置 OIDC 单点登录，查看安全控制状态和最近审计事件。':'OIDC シングルサインオンを設定し、セキュリティ統制と最近の監査イベントを確認します。'
});
UI_RX.en.push([
  /^同一批无提示采样共 (\d+) 条有效样本，对手出现率按问题语言对应的有效样本计算。领先并非不可复制：补齐对手常被引用的内容类型，你也能进入同类回答。竞品的引用份额与内容承接无法从外部可靠测量，因此不展示。$/,
  'Across $1 valid unprompted samples, rival presence is calculated against valid samples for each question language. A lead is replicable: publish the content types rivals are cited for to enter similar answers. Rival citation share and content readiness cannot be measured reliably from outside, so they are omitted.'
]);
UI_RX.ja.push([
  /^同一批无提示采样共 (\d+) 条有效样本，对手出现率按问题语言对应的有效样本计算。领先并非不可复制：补齐对手常被引用的内容类型，你也能进入同类回答。竞品的引用份额与内容承接无法从外部可靠测量，因此不展示。$/,
  '無指名の有効サンプル $1 件を対象に、質問言語ごとの有効サンプルで競合出現率を算出します。競合のリードは再現可能です。競合が引用されるコンテンツ形式を補えば、同種の回答に入る可能性が高まります。競合の引用シェアとコンテンツ受け皿は外部から正確に測定できないため表示しません。'
]);

function adminText(value) { return value && (value[ULANG] || value.zh) || ''; }
function adminCanonicalRoute(route) { return ADMIN_ROUTE_ALIASES[route] || route; }
function adminModuleForRoute(route) {
  const canonical=adminCanonicalRoute(route);
  return ADMIN_MODULES.find(function(module){
    return module.groups.some(function(group){return group.items.some(function(item){return item.route===canonical;});});
  }) || ADMIN_MODULES[0];
}
function closeAdminNav(){const side=$('#side');if(side)side.classList.remove('open');}
function startBrandOnboarding(){
  ST.obStep=1;ST.obSlug=null;ST.obNoSample=false;ST.obFail=false;ST.obUrl='';ST.obName='';ST.obMkt='both';
  go('onboard',{obStep:1});
}
function openAdminModule(moduleId){
  const module=ADMIN_MODULES.find(function(item){return item.id===moduleId;}) || ADMIN_MODULES[0];
  const current=adminModuleForRoute(R);
  if(current.id===module.id&&window.innerWidth<1200){const side=$('#side');if(side)side.classList.toggle('open');return;}
  if(current.id===module.id&&adminCanonicalRoute(R)===module.defaultRoute)return;
  go(module.defaultRoute);
  if(window.innerWidth<1200)setTimeout(function(){const side=$('#side');if(side)side.classList.add('open');},0);
}

function installAccountActions() {
  const button = document.querySelector('[data-admin-logout]');
  if (!button || button.dataset.bound === 'true') return;
  const labels = {zh:'退出登录',en:'Sign out',ja:'ログアウト'};
  button.id = 'disvorai-logout';
  button.setAttribute('aria-label', labels[ULANG] || labels.zh);
  button.dataset.bound = 'true';
  button.addEventListener('click', function () { button.disabled = true; window.disvoraiLogout(); });
}

renderSide = function () {
  const activeRoute=adminCanonicalRoute(R),module=adminModuleForRoute(activeRoute),brand=(D&&D.brand)||{};
  const updated=(D&&D.analytics&&D.analytics.latest_date)||'—';
  const languageLabel={zh:'语言',en:'Language',ja:'言語'}[ULANG]||'语言';
  const runLabel={zh:'跑完整一期',en:'Run full cycle',ja:'フルサイクルを実行'}[ULANG]||'跑完整一期';
  const runningLabel={zh:'任务运行中',en:'Job running',ja:'ジョブ実行中'}[ULANG]||'任务运行中';
  const updatedLabel={zh:'数据更新',en:'Data updated',ja:'データ更新'}[ULANG]||'数据更新';
  $('#side').innerHTML=`<div class="global-rail">
    <button class="rail-brand" type="button" onclick="go('overview')" aria-label="DisvorAI"><img src="/site-assets/favicon.png" width="30" height="30" alt=""></button>
    <div class="rail-modules" role="navigation" aria-label="${esc(adminText({zh:'主模块',en:'Main modules',ja:'メインモジュール'}))}">
      ${ADMIN_MODULES.map(function(item){const selected=item.id===module.id,label=adminText(item.label);return `<button class="rail-action" type="button" data-tooltip="${esc(label)}" aria-label="${esc(label)}" ${selected?'aria-current="page"':''} onclick="openAdminModule('${item.id}')"><span class="admin-icon icon-${item.icon}" aria-hidden="true"></span><span>${esc(label)}</span></button>`;}).join('')}
    </div>
    <div class="rail-footer"><button class="rail-action rail-logout" type="button" data-admin-logout data-tooltip="${esc(({zh:'退出登录',en:'Sign out',ja:'ログアウト'})[ULANG]||'退出登录')}"><span class="admin-icon icon-log-out" aria-hidden="true"></span></button></div>
  </div>
  <div class="module-panel">
    <div class="module-heading"><strong>${esc(adminText(module.label))}</strong><button class="module-close" type="button" onclick="closeAdminNav()" aria-label="${esc(({zh:'关闭导航',en:'Close navigation',ja:'ナビゲーションを閉じる'})[ULANG]||'关闭导航')}"><span class="admin-icon icon-x" aria-hidden="true"></span></button></div>
    <div class="project-switcher-row"><button class="project-switcher" type="button" onclick="switchModal()"><span class="project-switcher-copy"><span class="project-switcher-label">${esc(adminText({zh:'当前品牌',en:'Current brand',ja:'現在のブランド'}))}</span><span class="project-switcher-name" title="${esc(brand.name||'—')}">${esc(brand.name||'—')}</span></span><span class="admin-icon icon-chevron-down" aria-hidden="true"></span></button><button class="project-add" type="button" onclick="startBrandOnboarding()"><span class="admin-icon icon-plus" aria-hidden="true"></span><span>${esc(adminText({zh:'添加品牌',en:'Add brand',ja:'ブランドを追加'}))}</span></button></div>
    <nav class="module-nav" aria-label="${esc(adminText(module.label))}">
      ${module.groups.map(function(group){return `<div class="module-nav-group">${group.label?`<div class="module-nav-label">${esc(adminText(group.label))}</div>`:''}${group.items.map(function(item){const selected=item.route===activeRoute;return `<button class="module-link" type="button" ${selected?'aria-current="page"':''} onclick="go('${item.route}')"><span class="module-link-label">${esc(adminText(item.label))}</span><span class="bdg">${esc(badge(item.route))}</span></button>`;}).join('')}</div>`;}).join('')}
    </nav>
    <div class="module-meta"><div>${esc(updatedLabel)} ${esc(updated)}</div>${RUNNING?`<div style="margin-top:5px"><span class="spin"></span>${esc(runningLabel)}</div>`:`<button class="module-run" type="button" onclick="runAction('serve')">${esc(runLabel)}</button>`}
      <div class="module-languages" role="group" aria-label="${esc(languageLabel)}">${[['zh','中'],['en','EN'],['ja','日']].map(function(item){return `<button class="module-language" type="button" ${ULANG===item[0]?'aria-current="true"':''} onclick="setLang('${item[0]}')">${item[1]}</button>`;}).join('')}</div>
    </div>
  </div>`;
  installAccountActions();
};

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
  modal(`<h4 style="font-size:17px">创建外部协作任务</h4>
    <p class="muted" style="font-size:12.5px;margin:5px 0 14px">记录由外部页面负责人完成的具体更新；此类任务需要人工验证。</p>
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
      <button class="btn btn-primary" onclick="createOffsiteTicket()">创建任务</button></div>`);
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
  toast('外部协作任务已创建');
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
      count:function(){return `${summary.total||0} 个竞品，${summary.sample_confirmed||0} 个经采样确认`;}},
    en:{title:'Discovered competitors',desc:'Candidates are inferred during project setup. They are confirmed only after appearing in real sampled answers.',
      empty:'No competitor candidates yet. Run project setup again or configure competitors in Settings.',candidate:'Awaiting sample confirmation',confirmed:'Sample confirmed',configured:'Manually configured',aliases:'Aliases',
      count:function(){return `${summary.total||0} competitors, ${summary.sample_confirmed||0} sample confirmed`;}},
    ja:{title:'自動検出した競合',desc:'候補はプロジェクト初期化時に推定され、実際のサンプル回答に出現した場合のみ確認済みになります。',
      empty:'競合候補はまだありません。プロジェクト初期化を再実行するか、設定で競合を追加してください。',candidate:'サンプル確認待ち',confirmed:'サンプル確認済み',configured:'手動設定',aliases:'別名',
      count:function(){return `${summary.total||0} 件中 ${summary.sample_confirmed||0} 件をサンプル確認済み`;}}
  };
  const text=copies[ULANG]||copies.zh;
  const status={candidate:[text.candidate,'tag-accent'],sample_confirmed:[text.confirmed,'pill-good'],configured:[text.configured,'tag-outline']};
  return `<section style="margin-top:24px;padding-top:22px;box-shadow:inset 0 1px 0 var(--line)">
    <div class="row" style="align-items:flex-start"><div style="flex:1;min-width:220px"><h4 style="font-size:16px;margin:0 0 5px">${text.title}</h4>
      <p class="muted" style="font-size:12px;margin:0;max-width:720px">${text.desc}</p></div>
      <span style="font-size:11.5px;color:var(--t500)">${text.count()}</span></div>
    ${items.length?`<div style="margin-top:13px;border-top:1px solid var(--divider)">${items.map(function(item){const current=status[item.discovery_status]||status.configured;return `<div class="row" style="padding:9px 0;box-shadow:inset 0 -1px 0 var(--line);gap:8px">
        <span style="flex:1;min-width:180px;font-size:13px;overflow-wrap:anywhere">${esc(item.name)}${(item.aliases||[]).length?`<span style="display:block;font-size:10.5px;color:var(--t600);margin-top:1px">${text.aliases}: ${item.aliases.map(esc).join(' / ')}</span>`:''}</span>
        <span class="tag ${current[1]}">${current[0]}</span></div>`;}).join('')}</div>`
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
  '白标报告':'White-label reports','打印 / PDF 页眉':'Print / PDF header','机构名称':'Organization name',
  '主题色':'Accent color','页脚文字':'Footer text','启用白标':'Enable white label','选择 Logo':'Choose logo',
  '移除 Logo':'Remove logo','保存白标设置':'Save branding','Agency 套餐可用':'Available on Agency plan',
  '测量用量':'Measurement usage','托管用量':'Managed usage','本月调用':'Calls this month','本月费用':'Cost this month',
  'BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台凭证并按次计费。':'BYOK always takes priority. Managed usage is billed per call only when the matching API key is unavailable.',
  '当前套餐不可用':'Not available on the current plan','平台暂未配置可用模型':'No models are available for managed usage',
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
  ,'外部联络':'Outreach','人工确认发送':'Human-confirmed sending','邮件服务器':'Mail server','发件邮箱':'From email','发件名称':'From name',
  '保存 SMTP':'Save SMTP','联络草稿':'Outreach drafts','暂无联络草稿':'No outreach drafts','准备联络邮件':'Prepare outreach email','收件邮箱':'Recipient email',
  '生成草稿':'Create draft','编辑草稿':'Edit draft','邮件主题':'Subject','邮件正文':'Message','保存草稿':'Save draft','检查并发送':'Review and send',
  '最终发送确认':'Final send confirmation','我已核对收件人、主题和正文':'I reviewed the recipient, subject, and message','输入确认短语':'Type confirmation phrase',
  '确认并入队':'Confirm and queue','草稿已保存':'Draft saved','发送任务已创建':'Send job created','SMTP 凭证使用 AES-256-GCM 加密保存。':'SMTP credentials are encrypted with AES-256-GCM.',
  '发送前必须检查最终内容并输入与草稿匹配的确认短语。':'Before sending, review the final content and type the confirmation phrase for this draft.',
  '待编辑':'Draft','已排队':'Queued','发送中':'Sending','已发送':'Sent','发送失败':'Failed'
  ,'套餐与账单':'Plans and billing','月付':'Monthly','年付':'Annual','年付优惠':'Annual discount','每年':'per year','每月':'per month',
  '当前套餐':'Current plan','选择套餐':'Choose plan','续订套餐':'Renew plan','定制报价':'Custom pricing','年付节省':'Annual savings',
  '前往付款':'Continue to payment','Stripe 尚未配置，当前不能发起真实付款。':'Stripe is not configured, so live payments are unavailable.',
  '支付会话无效':'Invalid checkout session','已生效':'Active','试用中':'Trialing','付款逾期':'Past due','已取消':'Canceled','未付款':'Unpaid','待付款':'Incomplete',
  '订阅已更新':'Subscription updated','套餐信息加载失败':'Failed to load plan information','到期时间':'Expires','无限采样':'Unlimited sampling'
  ,'对象存储归档':'Object storage archives','创建快照':'Create snapshot','归档清单':'Archive history','暂无归档':'No archives yet','可恢复':'Available','已过期':'Expired',
  '恢复快照':'Restore snapshot','允许覆盖冲突文件':'Overwrite conflicting files','输入恢复确认短语':'Type the restore confirmation phrase','确认并恢复':'Confirm and restore',
  '活动数据源':'Active source','本地文件系统':'Local filesystem','保留份数':'Retention count','归档任务已创建':'Archive job created','恢复任务已创建':'Restore job created',
  '对象存储未配置':'Object storage is not configured','归档信息加载失败':'Failed to load archive information','文件':'files'
});
Object.assign(UI_D.ja, {
  '团队成员':'チームメンバー','工作区':'ワークスペース','邀请成员':'メンバーを招待','待接受邀请':'保留中の招待',
  '复制邀请链接':'招待リンクをコピー','撤销':'取り消す','移除':'削除','你':'自分',
  '所有者':'オーナー','编辑者':'編集者','只读成员':'閲覧者','邀请链接已创建':'招待リンクを作成しました',
  '团队成员按 owner/editor/viewer 分级，邀请链接 7 天内有效。':'メンバーは owner、editor、viewer のロールで管理され、招待リンクは 7 日間有効です。',
  '白标报告':'ホワイトラベルレポート','打印 / PDF 页眉':'印刷 / PDF ヘッダー','机构名称':'組織名',
  '主题色':'アクセントカラー','页脚文字':'フッターテキスト','启用白标':'ホワイトラベルを有効化','选择 Logo':'ロゴを選択',
  '移除 Logo':'ロゴを削除','保存白标设置':'ブランド設定を保存','Agency 套餐可用':'Agency プランで利用可能',
  '测量用量':'測定使用量','托管用量':'マネージド使用量','本月调用':'今月の呼び出し','本月费用':'今月の費用',
  'BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台凭证并按次计费。':'BYOK が常に優先されます。対応する API キーがない場合のみ、マネージド使用量として従量課金します。',
  '当前套餐不可用':'現在のプランでは利用できません','平台暂未配置可用模型':'マネージド使用量で利用可能なモデルはありません',
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
  ,'外部联络':'アウトリーチ','人工确认发送':'人による確認後に送信','邮件服务器':'メールサーバー','发件邮箱':'送信元メール','发件名称':'送信者名',
  '保存 SMTP':'SMTP を保存','联络草稿':'アウトリーチ下書き','暂无联络草稿':'アウトリーチ下書きはありません','准备联络邮件':'アウトリーチメールを準備','收件邮箱':'宛先メール',
  '生成草稿':'下書きを作成','编辑草稿':'下書きを編集','邮件主题':'件名','邮件正文':'本文','保存草稿':'下書きを保存','检查并发送':'確認して送信',
  '最终发送确认':'最終送信確認','我已核对收件人、主题和正文':'宛先、件名、本文を確認しました','输入确认短语':'確認フレーズを入力',
  '确认并入队':'確認してキューへ','草稿已保存':'下書きを保存しました','发送任务已创建':'送信ジョブを作成しました','SMTP 凭证使用 AES-256-GCM 加密保存。':'SMTP 認証情報は AES-256-GCM で暗号化保存されます。',
  '发送前必须检查最终内容并输入与草稿匹配的确认短语。':'送信前に最終内容を確認し、この下書き用の確認フレーズを入力してください。',
  '待编辑':'下書き','已排队':'キュー済み','发送中':'送信中','已发送':'送信済み','发送失败':'送信失敗'
  ,'套餐与账单':'プランと請求','月付':'月払い','年付':'年払い','年付优惠':'年払い割引','每年':'年間','每月':'月間',
  '当前套餐':'現在のプラン','选择套餐':'プランを選択','续订套餐':'プランを更新','定制报价':'個別見積もり','年付节省':'年間割引',
  '前往付款':'支払いへ進む','Stripe 尚未配置，当前不能发起真实付款。':'Stripe が設定されていないため、実際の支払いは利用できません。',
  '支付会话无效':'無効な決済セッション','已生效':'有効','试用中':'トライアル中','付款逾期':'支払い遅延','已取消':'キャンセル済み','未付款':'未払い','待付款':'支払い待ち',
  '订阅已更新':'サブスクリプションを更新しました','套餐信息加载失败':'プラン情報を読み込めませんでした','到期时间':'有効期限','无限采样':'無制限サンプリング'
  ,'对象存储归档':'オブジェクトストレージアーカイブ','创建快照':'スナップショットを作成','归档清单':'アーカイブ履歴','暂无归档':'アーカイブはありません','可恢复':'復元可能','已过期':'期限切れ',
  '恢复快照':'スナップショットを復元','允许覆盖冲突文件':'競合ファイルを上書き','输入恢复确认短语':'復元確認フレーズを入力','确认并恢复':'確認して復元',
  '活动数据源':'アクティブソース','本地文件系统':'ローカルファイルシステム','保留份数':'保持数','归档任务已创建':'アーカイブジョブを作成しました','恢复任务已创建':'復元ジョブを作成しました',
  '对象存储未配置':'オブジェクトストレージが設定されていません','归档信息加载失败':'アーカイブ情報を読み込めませんでした','文件':'ファイル'
});

Object.assign(UI_D.en, {
  '创建外部协作任务':'Create external collaboration task',
  '记录由外部页面负责人完成的具体更新；此类任务需要人工验证。':'Track a requested change owned by an external page manager. These tasks require manual verification.',
  '外部页面 URL':'External page URL','希望对方完成什么':'Requested update','影响问题':'Affected prompts',
  '例如：补充品牌定义、官网链接和可核验的数据来源':'For example: add a brand definition, official website link, and verifiable sources.',
  '问题库为空，请先完成项目分析。':'No prompts are available yet. Complete project analysis first.',
  '创建任务':'Create task','外部协作任务已创建':'External collaboration task created',
  'AI 模型':'AI models','模型与测量':'Models and measurement',
  'API · 模型内知识':'API · Model knowledge','API · 联网检索':'API · Web-grounded retrieval','人工 · 产品端核验':'Manual · Product-surface check',
  '项目归档':'Project archive','数据源':'Data sources','外部联络':'Outreach','外部联络加载失败':'Failed to load outreach settings',
  '测量用量':'Measurement usage','托管用量':'Managed usage','不可用':'Unavailable','启用':'Enable',
  '启用托管用量后，缺少 BYOK 的模型将按页面所示单价逐次收费。确认启用？':'Enable managed usage? Models without BYOK will be billed per call at the displayed price.',
  '托管用量已启用':'Managed usage enabled','托管用量已关闭':'Managed usage disabled',
  '白标报告':'White-label reports','暂无发布目的地':'No publishing destinations',
  '发布凭证加密保存。发布只能由用户手动触发，WeChat Official Account 和 WordPress 仅创建草稿。':'Publishing credentials are encrypted. Publishing is manual, and WeChat Official Account and WordPress create drafts only.',
  '发布目的地':'Publishing destinations','配置发布目的地并查看发布记录。所有对外发布都由用户手动发起。':'Configure publishing destinations and review history. Every external publication is started manually.'
});
Object.assign(UI_D.ja, {
  '创建外部协作任务':'外部連携タスクを作成',
  '记录由外部页面负责人完成的具体更新；此类任务需要人工验证。':'外部ページ管理者が担当する更新を記録します。このタスクは手動検証が必要です。',
  '外部页面 URL':'外部ページ URL','希望对方完成什么':'依頼する更新','影响问题':'影響するプロンプト',
  '例如：补充品牌定义、官网链接和可核验的数据来源':'例：ブランド定義、公式サイトへのリンク、検証可能な情報源を追加。',
  '问题库为空，请先完成项目分析。':'プロンプトはまだありません。先にプロジェクト分析を完了してください。',
  '创建任务':'タスクを作成','外部协作任务已创建':'外部連携タスクを作成しました',
  'AI 模型':'AI モデル','模型与测量':'モデルと測定',
  'API · 模型内知识':'API · モデル知識','API · 联网检索':'API · Web グラウンデッド検索','人工 · 产品端核验':'手動 · プロダクト画面確認',
  '项目归档':'プロジェクトアーカイブ','数据源':'データソース','外部联络':'アウトリーチ','外部联络加载失败':'アウトリーチ設定を読み込めませんでした',
  '测量用量':'測定使用量','托管用量':'マネージド使用量','不可用':'利用不可','启用':'有効化',
  '启用托管用量后，缺少 BYOK 的模型将按页面所示单价逐次收费。确认启用？':'マネージド使用量を有効にしますか。BYOK がないモデルは表示価格で 1 回ごとに課金されます。',
  '托管用量已启用':'マネージド使用量を有効にしました','托管用量已关闭':'マネージド使用量を無効にしました',
  '白标报告':'ホワイトラベルレポート','暂无发布目的地':'公開先はありません',
  '发布凭证加密保存。发布只能由用户手动触发，WeChat Official Account 和 WordPress 仅创建草稿。':'公開認証情報は暗号化されます。公開は手動で、WeChat Official Account と WordPress は下書きのみ作成します。',
  '发布目的地':'公開先','配置发布目的地并查看发布记录。所有对外发布都由用户手动发起。':'公開先と履歴を管理します。外部公開はすべて手動で開始します。'
});

let TEAM_STATE = null;
let BRANDING_STATE = null;
let SSO_STATE = null;
let AUDIT_STATE = null;
let INTEGRATION_STATE = null;
let OUTREACH_STATE = null;
let BILLING_STATE = null;
let BILLING_INTERVAL = 'monthly';
let ARCHIVE_STATE = null;
let FUNDING_STATE = null;
const billingStatusLabel = {active:'已生效',trialing:'试用中',past_due:'付款逾期',canceled:'已取消',unpaid:'未付款',incomplete:'待付款'};
const teamRoleLabel = {owner:'所有者',editor:'编辑者',viewer:'只读成员'};

function billingPanel() {
  const state=BILLING_STATE||{},plans=state.plans||[],usage=state.usage||{};
  if(state.error||state.detail||usage.error||usage.detail)return `<h4 class="billing-section-title" style="font-size:16px;margin:28px 0 10px">套餐与账单</h4>
    <div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">套餐信息加载失败</div>`;
  const subscription=usage.subscription||{},payment=state.payment||{},owner=TEAM_STATE&&TEAM_STATE.current_role==='owner';
  const expires=subscription.expires_at?String(subscription.expires_at).replace('T',' ').slice(0,10):'';
  return `<h4 class="billing-section-title" style="font-size:16px;margin:28px 0 10px">套餐与账单</h4>
    <div class="card elev" style="padding:18px;gap:14px">
      <div class="row" style="align-items:flex-start;gap:12px;flex-wrap:wrap"><div style="flex:1;min-width:170px"><div style="font-size:15px;font-weight:500">${esc(String(usage.plan||'trial').toUpperCase())}</div>
        ${expires?`<div style="font-size:11.5px;color:var(--t600);margin-top:3px">到期时间 ${esc(expires)} · ${esc(billingStatusLabel[subscription.status]||subscription.status||'已生效')}</div>`:''}</div>
        <div class="billing-interval-switch"><button class="btn ${BILLING_INTERVAL==='monthly'?'btn-primary':'btn-ghost'}" onclick="setBillingInterval('monthly')">月付</button><button class="btn ${BILLING_INTERVAL==='annual'?'btn-primary':'btn-ghost'}" onclick="setBillingInterval('annual')">年付</button></div></div>
      ${payment.configured?'':`<div style="padding:9px 11px;border:1px solid var(--line);font-size:12px;color:var(--t500)">Stripe 尚未配置，当前不能发起真实付款。</div>`}
      <div class="billing-plan-grid">${plans.map(function(plan){const price=(plan.prices||{})[BILLING_INTERVAL]||{},current=usage.plan===plan.code,currentInterval=current&&subscription.billing_interval===BILLING_INTERVAL,custom=price.cny==null;return `<div style="display:flex;flex-direction:column;min-width:0;min-height:188px;padding:14px;border:1px solid ${current?'var(--a700)':'var(--line)'};border-radius:var(--r-md);background:var(--bg)">
          <div class="row"><strong style="font-size:14px">${esc(plan.name)}</strong>${current?'<span class="tag tag-accent">当前套餐</span>':''}</div>
          <div style="font-size:22px;margin-top:13px">${custom?'定制报价':'¥'+Number(price.cny).toLocaleString()}${custom?'':`<span style="font-size:11px;color:var(--t600)"> / ${BILLING_INTERVAL==='annual'?'每年':'每月'}</span>`}</div>
          ${BILLING_INTERVAL==='annual'&&!custom?`<div style="font-size:11.5px;color:var(--good);margin-top:4px">年付优惠 ${Number(plan.annual_discount_percent||0).toFixed(2)}% · 年付节省 ¥${Number(plan.annual_savings_cny||0).toLocaleString()}</div>`:'<div style="height:21px"></div>'}
          <div style="font-size:11.5px;color:var(--t600);margin-top:9px">${plan.projects==null?'Enterprise SLA':esc(String(plan.projects))+' projects'} · 无限采样</div>
          ${!custom&&owner?`<button class="btn ${currentInterval?'btn-secondary':'btn-primary'}" ${currentInterval||!payment.configured?'disabled':''} style="margin-top:auto;width:100%" onclick="subscribeBilling('${esc(plan.code)}')">${currentInterval?'当前套餐':'前往付款'}</button>`:''}
        </div>`;}).join('')}</div>
    </div>`;
}

function setBillingInterval(value){BILLING_INTERVAL=value==='annual'?'annual':'monthly';render();}

async function subscribeBilling(plan){
  const selected=(BILLING_STATE.plans||[]).find(function(item){return item.code===plan;});
  const price=selected&&selected.prices&&selected.prices[BILLING_INTERVAL];
  if(!price||price.cny==null)return;
  if(!confirm(`确认订阅 ${selected.name}，${BILLING_INTERVAL==='annual'?'年付':'月付'} ¥${Number(price.cny).toLocaleString()}？`))return;
  const result=await post('/api/billing',{plan:plan,billing_interval:BILLING_INTERVAL});
  if(result.error||result.detail){toast('订阅失败：'+(result.error||result.detail),'err');return}
  if(!result.checkout_url){toast('支付会话无效','err');return}
  window.location.assign(result.checkout_url);
}

function archiveSize(value){const size=Number(value||0);if(size<1024)return size+' B';if(size<1048576)return (size/1024).toFixed(1)+' KB';if(size<1073741824)return (size/1048576).toFixed(1)+' MB';return (size/1073741824).toFixed(1)+' GB';}

function archivePanel(){
  const state=ARCHIVE_STATE||{};
  if(state.error||state.detail)return `<h4 class="archive-section-title" style="font-size:16px;margin:28px 0 10px">对象存储归档</h4><div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">归档信息加载失败</div>`;
  const storage=state.storage||{},archives=state.archives||[];
  return `<h4 class="archive-section-title" style="font-size:16px;margin:28px 0 10px">对象存储归档</h4>
    <div class="card elev" style="padding:18px;gap:13px"><div class="row" style="align-items:flex-start;gap:12px;flex-wrap:wrap"><div style="flex:1;min-width:190px"><div style="font-size:15px;font-weight:500">${storage.configured?esc(storage.bucket):'对象存储未配置'}</div>
      <div style="font-size:11.5px;color:var(--t600);margin-top:3px">活动数据源 · 本地文件系统${storage.configured?' · 保留份数 '+esc(storage.retention_count):''}</div></div>
      ${state.can_manage&&storage.configured?'<button class="btn btn-primary" style="font-size:12px" onclick="createProjectArchive()">创建快照</button>':''}</div>
      <div style="padding-top:11px;box-shadow:inset 0 1px 0 var(--line)"><div class="row"><div style="flex:1;font-size:12px;color:var(--t500)">归档清单</div><span class="tag tag-outline">${archives.length}</span></div>
        ${archives.length?archives.map(function(item){const available=item.status==='available';return `<div class="archive-row"><span style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace">${esc(item.id)}</span><span class="archive-row-detail" style="color:var(--t600);overflow-wrap:anywhere">${esc(String(item.created_at||'').replace('T',' ').slice(0,19))} · ${archiveSize(item.size_bytes)} · ${esc(item.file_count)} 文件</span><span class="tag ${available?'pill-good':'tag-outline'}">${available?'可恢复':'已过期'}</span>${available&&state.can_manage?`<button class="btn btn-ghost" style="font-size:12px" onclick="restoreArchiveModal('${esc(item.id)}')">恢复快照</button>`:'<span></span>'}</div>`;}).join(''):'<div style="padding:12px 0 4px;font-size:12px;color:var(--t600)">暂无归档</div>'}</div>
    </div>`;
}

async function createProjectArchive(){
  if(!confirm('确认创建当前项目的对象存储快照？'))return;
  const result=await post('/api/archive',{action:'create'});
  if(!result.job_id){toast('归档失败：'+(result.error||result.detail||'archive_failed'),'err');return}
  ARCHIVE_STATE=null;RUNNING=result.job_id;LASTJOB=result.job_id;LOGOFF=0;renderSide();pollJob();toast('归档任务已创建');
}

function restoreArchiveModal(archiveId){
  const phrase='RESTORE '+archiveId;
  modal(`<h4 style="font-size:17px">恢复快照</h4><div style="font-size:12px;color:var(--t600);margin-top:9px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere">${esc(archiveId)}</div>
    <label class="row" style="gap:7px;margin-top:14px;font-size:12.5px"><input id="archive-overwrite" type="checkbox">允许覆盖冲突文件</label>
    <label style="display:block;font-size:12px;color:var(--t500);margin-top:12px">输入恢复确认短语 <code>${esc(phrase)}</code><input id="archive-confirm-text" class="input" autocomplete="off" style="margin-top:5px"></label>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn btn-secondary" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="queueArchiveRestore('${esc(archiveId)}')">确认并恢复</button></div>`);
}

async function queueArchiveRestore(archiveId){
  const text=(($('#archive-confirm-text')||{}).value||'');if(text!=='RESTORE '+archiveId){toast('请输入完整恢复确认短语','err');return}
  const result=await post('/api/archive',{action:'restore',archive_id:archiveId,overwrite:!!($('#archive-overwrite')||{}).checked,confirmed:true,confirmation_text:text});
  if(!result.job_id){toast('恢复失败：'+(result.error||result.detail||'archive_restore_failed'),'err');return}
  ARCHIVE_STATE=null;closeModal();RUNNING=result.job_id;LASTJOB=result.job_id;LOGOFF=0;renderSide();pollJob();toast('恢复任务已创建');
}

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
  if(state.error||state.detail)return `<h4 class="outreach-section-title" style="font-size:16px;margin:28px 0 10px">外部联络</h4>
    <div class="card elev" style="padding:18px;font-size:13px;color:var(--t500)">外部联络加载失败</div>`;
  const port=Number(smtp.port||587),mode=smtp.security_mode||'starttls';
  return `<h4 class="outreach-section-title" style="font-size:16px;margin:28px 0 4px">外部联络</h4><p class="muted settings-section-subtitle" style="font-size:12px;margin:0 0 10px">人工确认发送</p>
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

function formatCny(value) {
  return 'CNY ' + Number(value || 0).toFixed(2);
}

function perCallLabel() {
  return {zh:'每次',en:'per call',ja:'1 回あたり'}[ULANG] || 'per call';
}

function samplingFundingPanel(state) {
  state = state || {};
  if (state.error) return `<h4 style="font-size:16px;margin:28px 0 10px">测量用量</h4>
    <div class="card elev" style="padding:18px"><div class="row"><span style="flex:1;font-size:13px;color:var(--t500)">费用信息加载失败</span>
      <button class="btn btn-secondary" style="font-size:12px" onclick="render()">刷新</button></div></div>`;
  const pool = state.pool_engines || [], usage = state.usage || {};
  const effective = Object.fromEntries((state.effective_engines || []).map(function (item) { return [item.engine_code,item.source]; }));
  const canEnable = !!state.eligible && pool.length > 0;
  const sourceLabel = {byok:'BYOK',platform_pool:'托管用量',unavailable:'不可用'};
  return `<h4 style="font-size:16px;margin:28px 0 10px">测量用量</h4>
    <div class="card elev" style="padding:18px;gap:12px">
      <div class="row" style="align-items:flex-start"><div style="flex:1;min-width:220px">
        <div style="font-size:15px;font-weight:500">托管用量</div>
        <div style="font-size:11.5px;color:var(--t600);margin-top:3px;line-height:1.55">BYOK 始终优先。仅在缺少对应 API Key 时，才使用平台凭证并按次计费。</div></div>
        <label class="row" style="gap:7px;font-size:12.5px;white-space:nowrap"><input id="platform-pool-enabled" type="checkbox"
          ${state.platform_pool_enabled?'checked':''} ${state.can_edit&&canEnable?'':'disabled'} onchange="setPlatformPool(this.checked)">启用</label></div>
      ${!state.eligible?`<div style="font-size:12px;color:var(--t500)">当前套餐不可用 (${esc(String(state.plan || 'trial').toUpperCase())})</div>`:''}
      ${state.eligible&&!state.can_edit?'<div style="font-size:12px;color:var(--t500)">仅所有者可更改</div>':''}
      ${state.eligible&&!pool.length?'<div style="font-size:12px;color:var(--t500)">平台暂未配置可用模型</div>':''}
      ${pool.length?`<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px">
        ${pool.map(function (item) { const source = effective[item.engine_code] || 'unavailable'; return `<div style="padding:10px 11px;border:1px solid var(--line);border-radius:var(--r-md);min-width:0">
          <div class="row" style="gap:6px"><span style="flex:1;font-size:13px;overflow-wrap:anywhere">${esc(window.disvoraiModelLabel(item.engine_code, item.engine_name || item.engine_code))}</span>
            <span class="tag ${source==='platform_pool'?'tag-accent':'tag-outline'}">${esc(sourceLabel[source] || source)}</span></div>
          <div style="font-size:11.5px;color:var(--t600);margin-top:5px">${esc(item.sampling_mode)} · ${formatCny(Number(item.unit_price_cny_fen || 0)/100)} ${perCallLabel()}</div></div>`; }).join('')}</div>`:''}
      <div class="row" style="gap:24px;padding-top:10px;box-shadow:inset 0 1px 0 var(--line)">
        <div><div style="font-size:10.5px;color:var(--t600)">本月调用</div><div style="font-size:17px;margin-top:2px">${Number(usage.calls || 0).toLocaleString()}</div></div>
        <div><div style="font-size:10.5px;color:var(--t600)">本月费用</div><div style="font-size:17px;margin-top:2px">${formatCny(usage.cost_cny)}</div></div>
        <div style="font-size:11.5px;color:var(--t600);margin-left:auto">${esc(usage.month || '')}</div></div>
    </div>`;
}

async function setPlatformPool(enabled) {
  const input = $('#platform-pool-enabled');
  if (enabled && !confirm('启用托管用量后，缺少 BYOK 的模型将按页面所示单价逐次收费。确认启用？')) {
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
  toast(enabled?'托管用量已启用':'托管用量已关闭');
  FUNDING_STATE=null;
  render();
}

function deliveryBrandingPanel() {
  const state = BRANDING_STATE || {}, value = state.branding || {};
  if (!state.available) return `<h4 style="font-size:16px;margin:28px 0 10px">白标报告</h4>
    <div class="card elev" style="padding:18px"><div class="row"><div style="flex:1">
      <div style="font-size:14px;font-weight:500">打印 / PDF 页眉</div>
      <div style="font-size:12px;color:var(--t600);margin-top:3px">Agency 套餐可用</div></div>
      <span class="tag tag-outline">${esc(String(state.plan || 'trial').toUpperCase())}</span></div></div>`;
  const editable = !!state.can_edit, logo = value.logo_data_url || '';
  return `<h4 style="font-size:16px;margin:28px 0 10px">白标报告</h4>
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

function adminPage(title, description, body) {
  return `<div class="admin-page"><header class="admin-page-header"><h3>${esc(title)}</h3><p>${esc(description)}</p></header><div class="admin-page-body">${body}</div></div>`;
}

async function ensureTeamState() {
  if (!TEAM_STATE) TEAM_STATE=await api('/api/team');
  return TEAM_STATE;
}

function projectSettingsPanel() {
  const projects=Array.isArray(PROJECTS)?PROJECTS:[];
  return `<div class="tbl"><table class="table"><thead><tr><th>品牌</th><th style="width:210px">域名</th><th style="width:110px">网站审计均分</th><th style="width:90px">任务</th><th style="width:80px"></th></tr></thead><tbody>
    ${projects.map(function(project){return `<tr><td><span style="font-size:13.5px">${esc(project.name)}</span>${project.slug===SLUG?' <span class="tag tag-accent">当前</span>':''}</td><td style="font-size:12.5px;color:var(--t500)">${esc((project.site||'').replace('https://',''))}</td><td style="font-size:13px">${project.avg_score==null?'—':project.avg_score}</td><td style="font-size:12.5px;color:var(--t400)">${project.tasks_total||'—'}</td><td><button class="btn btn-ghost" style="font-size:12px" onclick="switchProject(${esc(JSON.stringify(project.slug))})">${project.slug===SLUG?'刷新':'进入'}</button></td></tr>`;}).join('')}
    </tbody></table></div><div class="admin-project-actions"><button class="btn btn-primary" onclick="startBrandOnboarding()">添加品牌</button><button class="btn btn-secondary" onclick="editConfig()">编辑当前品牌</button></div>`;
}

async function vProjectSettings() {
  if(!PROJECTS)PROJECTS=await api('/api/projects');
  if(!Array.isArray(PROJECTS))PROJECTS=[];
  return adminPage('品牌管理','管理品牌清单、官网域名和竞品范围。',projectSettingsPanel());
}

function automationPanel() {
  const config=SET_CFG&&!SET_CFG.error?SET_CFG:{},monitor=config.monitor||{},current=monitor.every_days||0;
  const actions=['crawl','audit','bootstrap','sample','sample-sheet','plan','blueprint','generate','lint','report','deliverables','verify','deliver'];
  setTimeout(function(){if(LASTJOB&&!RUNNING)showLog(LASTJOB);if(RUNNING)pollJob();},0);
  return `<div class="card elev" style="padding:18px;gap:13px"><div><div style="font-size:15px;font-weight:500">运行任务</div><div style="font-size:11.5px;color:var(--t600);margin-top:3px">任务由后台队列执行，关闭页面后仍会继续。同一项目同时只运行一个任务。</div></div>
    <div class="admin-run-actions"><button class="btn btn-primary" ${RUNNING?'disabled':''} onclick="runAction('autopilot')">全自动引导</button><button class="btn btn-primary" ${RUNNING?'disabled':''} onclick="runAction('serve')">跑完整一期</button></div>
    <div class="admin-run-actions">${actions.map(function(action){return `<button class="btn btn-secondary" style="font-size:11.5px;padding:5px 9px" ${RUNNING?'disabled':''} onclick="runAction('${action}')">${esc((ACTIONS[action]||{}).label||action)}</button>`;}).join('')}</div>
    <div class="row" style="gap:7px;align-items:center;padding-top:11px;box-shadow:inset 0 1px 0 var(--line)"><span style="font-size:12px;color:var(--t500);margin-right:3px">周期复跑</span>${[0,7,14,30].map(function(days){return `<button class="btn ${current===days?'btn-secondary':'btn-ghost'}" style="font-size:11.5px;padding:4px 9px" onclick="setMonitor(${days})">${days?'每 '+days+' 天':'关闭'}</button>`;}).join('')}${current?`<span class="muted" style="font-size:11.5px">下次 ${esc(monitor.next_run||'')}</span>`:''}</div>
    <div class="row"><div id="jobstat" style="font-size:12.5px;flex:1">${RUNNING?'<span class="spin"></span>任务运行中':''}</div></div><pre class="log" id="joblog" style="max-height:300px"></pre></div>`;
}

async function vAutomation() {
  if(!SET_CFG)SET_CFG=await api('/api/config/'+SLUG);
  return adminPage('运行与调度','手动运行完整管线、执行单项任务，或设置固定复跑周期。',automationPanel());
}

function engineKeysPanel() {
  const keys=Array.isArray(KEYS)?KEYS:[],owner=TEAM_STATE&&TEAM_STATE.current_role==='owner';
  return `<h4 style="font-size:16px;margin:0 0 10px">AI 模型</h4><div class="card elev" style="padding:18px;gap:0"><div style="font-size:11.5px;color:var(--t600);margin-bottom:8px">API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。BYOK 始终优先。</div>${keys.map(function(key,index){const mode=key.manual?'人工 · 产品端核验':(key.search?'API · 联网检索':'API · 模型内知识');return `<div class="admin-engine-row"><div class="admin-engine-name"><span class="tag ${key.ok===true?'pill-good':'tag-outline'}" style="margin-right:7px">${key.ok===true?'已连接':key.manual?'人工':'未连接'}</span>${esc(key.label)}</div><div class="admin-engine-mode">${esc(mode)}${key.ok===true&&key.key_tail?' ····'+esc(key.key_tail):''}</div>${key.env&&owner?`<button class="btn btn-ghost" style="font-size:12px" onclick="editKey(${index})">${key.ok===true?'修改':'配置'}</button>`:'<span></span>'}</div>`;}).join('')}</div>`;
}

async function vEngineSettings() {
  await ensureTeamState();
  if(!KEYS)KEYS=await api('/api/keys');
  if(!Array.isArray(KEYS))KEYS=[];
  if(!FUNDING_STATE)FUNDING_STATE=await api('/api/sampling-funding');
  return adminPage('模型与测量','配置 AI 模型凭证、查看测量方式，并管理可选的托管用量。',engineKeysPanel()+samplingFundingPanel(FUNDING_STATE));
}

async function vArchive() {
  if(!ARCHIVE_STATE)ARCHIVE_STATE=await api('/api/archive');
  return adminPage('项目归档','创建项目文件快照，并在需要时恢复到本地文件系统。',archivePanel());
}

async function vIntegrations() {
  await ensureTeamState();
  if(!INTEGRATION_STATE)INTEGRATION_STATE=await api('/api/integrations');
  return adminPage('数据源','连接外部搜索数据源，为诊断和成效分析补充可核验数据。',integrationPanel());
}

async function vOutreach() {
  await ensureTeamState();
  if(!OUTREACH_STATE)OUTREACH_STATE=await api('/api/outreach');
  return adminPage('外部联络','管理 SMTP 连接和联络草稿。每封邮件都需要人工检查并确认发送。',outreachPanel());
}

function publishingPanel() {
  const state=PUB||{},publishers=state.publishers||[],records=state.records||[],owner=TEAM_STATE&&TEAM_STATE.current_role==='owner';
  return `<div class="card elev" style="padding:18px;gap:0"><div style="font-size:11.5px;color:var(--t600);margin-bottom:8px">发布凭证加密保存。发布只能由用户手动触发，WeChat Official Account 和 WordPress 仅创建草稿。</div>${publishers.map(function(publisher,index){const ready=!publisher.missing.length;return `<div class="admin-publisher-row"><div style="min-width:0"><div style="font-size:13px">${esc(publisher.name)}</div><div style="font-size:11px;color:var(--t600);margin-top:2px;overflow-wrap:anywhere">${esc(publisher.note)}</div></div><div class="admin-publisher-state" style="font-size:11.5px;color:var(--t600)">${ready?'已就绪':'缺 '+publisher.missing.map(esc).join('、')}</div>${owner?`<button class="btn btn-ghost" style="font-size:12px" onclick="editPub(${index})">配置</button>`:'<span></span>'}</div>`;}).join('')||'<div style="padding:10px 0;font-size:12px;color:var(--t600)">暂无发布目的地</div>'}</div>${records.length?`<h4 style="font-size:16px;margin:24px 0 10px">最近发布</h4><div class="card elev" style="padding:14px 18px">${records.slice(-10).reverse().map(function(record){return `<div style="padding:6px 0;box-shadow:inset 0 -1px 0 var(--line);font-size:12.5px;color:var(--t400)">${record.ok?'成功':'失败'} · ${esc((record.at||'').slice(0,16).replace('T',' '))} · ${esc(record.platform_name)} · ${esc(record.title)} ${record.url?`<a href="${esc(record.url)}" target="_blank" rel="noopener">打开链接</a>`:esc(record.note||record.error||'')}</div>`;}).join('')}</div>`:''}`;
}

async function vPublishing() {
  await ensureTeamState();
  if(!PUB)PUB=await api('/api/publish/'+SLUG);
  return adminPage('发布目的地','配置发布目的地并查看发布记录。所有对外发布都由用户手动发起。',publishingPanel());
}

async function vBranding() {
  if(!BRANDING_STATE)BRANDING_STATE=await api('/api/delivery-branding');
  return adminPage('白标报告','为客户报告和打印版交付物配置机构名称、Logo 和主题色。',deliveryBrandingPanel());
}

async function vTeam() {
  await ensureTeamState();
  return adminPage('团队与权限','管理工作区成员、邀请和 owner、editor、viewer 角色。',teamPanel());
}

async function vBilling() {
  await ensureTeamState();
  if(!BILLING_STATE)BILLING_STATE=await api('/api/billing');
  return adminPage('套餐与账单','查看当前套餐和用量，并由工作区所有者管理订阅。',billingPanel());
}

async function vSecurity() {
  if(!SSO_STATE)SSO_STATE=await api('/api/v1/sso/config');
  if(SSO_STATE.can_edit&&!AUDIT_STATE)AUDIT_STATE=await api('/api/v1/sso/audit-events');
  return adminPage('企业安全','配置 OIDC 单点登录，查看安全控制状态和最近审计事件。',ssoPanel());
}

async function vLegacySettings() {
  R='project-settings';
  history.replaceState({r:R,engSel:ST.engSel,gapTab:ST.gapTab},'','#project-settings');
  return vProjectSettings();
}

VIEWS['project-settings']=vProjectSettings;
VIEWS.automation=vAutomation;
VIEWS.archive=vArchive;
VIEWS['engine-settings']=vEngineSettings;
VIEWS.integrations=vIntegrations;
VIEWS.outreach=vOutreach;
VIEWS.publishing=vPublishing;
VIEWS.branding=vBranding;
VIEWS.team=vTeam;
VIEWS.billing=vBilling;
VIEWS.security=vSecurity;
VIEWS.settings=vLegacySettings;

const engineSwitchProjectWithAdminState = switchProject;
switchProject = async function (slug) {
  ARCHIVE_STATE=null;
  FUNDING_STATE=null;
  INTEGRATION_STATE=null;
  OUTREACH_STATE=null;
  await engineSwitchProjectWithAdminState(slug);
};

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
      <span style="font-size:11.5px;color:var(--t600)">负责：${esc(ticket.owner)} · 工作量 ${esc(ticket.effort)}</span></div>
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


@router.get("/app", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def serve_ui():
    """返回经过品牌和 SaaS API 适配的 engine 单页 UI。"""
    html = UI_PATH.read_text("utf-8")
    html = "".join(
        line
        for line in html.splitlines(keepends=True)
        if "[/^同一批无提示采样下的对手出现率" not in line
    )
    html = html.replace(
        "const mktLabel=m=>m==='cn'?'国内':m==='global'?'海外':'通用';",
        "const mktLabel=m=>m==='cn'?'中文':m==='global'?'英文':'通用';",
    )
    html = html.replace("[['cn','国内市场'],['global','海外市场']]", "[['cn','中文问题'],['global','英文问题']]")
    html = html.replace("tbl(T.cn||[],NS.cn||0,'国内市场')", "tbl(T.cn||[],NS.cn||0,'中文问题')")
    html = html.replace("tbl(T.global||[],NS.global||0,'海外市场')", "tbl(T.global||[],NS.global||0,'英文问题')")
    html = html.replace("${mtab('cn','国内')}${mtab('global','海外')}", "${mtab('cn','中文')}${mtab('global','英文')}")
    html = html.replace(
        "'全部':'All','国内':'CN','海外':'Global','通用':'Both'",
        "'全部':'All','中文':'Chinese','英文':'English','通用':'All languages'",
    )
    html = html.replace(
        "'全部':'すべて','国内':'中国','海外':'グローバル','通用':'共通'",
        "'全部':'すべて','中文':'中国語','英文':'英語','通用':'共通'",
    )
    html = html.replace("['国内','CN'],['海外','Global']", "['中文','Chinese'],['英文','English']")
    html = html.replace("['国内','中国'],['海外','海外']", "['中文','中国語'],['英文','英語']")
    html = html.replace(
        "题量按市场定：国内 18–24 题；海外 14–20 题；双市场 = 国内 16–20 + 海外 12–16 + 通用 2。编号 q001 起为国内、q101 起为海外、q901 起为通用。",
        "题量按语言覆盖确定：中文 18–24 题；英文 14–20 题；双语覆盖 = 中文 16–20 + 英文 12–16 + 通用 2。编号 q001 起为中文、q101 起为英文、q901 起为通用。",
    )
    html = html.replace(
        "要求真实口语问法：国内题像真人在 AI 里打的字；海外题是<b>英文原生问法</b>，不是中文题翻译。",
        "要求真实口语问法：中文题像真人在 AI 里输入的内容；英文题使用<b>英文原生问法</b>，不是中文题翻译。",
    )
    html = html.replace("校验分组与市场标记", "校验分组与语言路由标记")
    html = html.replace(
        "市场路由：中文题只问国内引擎，英文题只问海外引擎，通用题两边都问；两套市场的指标分开算，分母各用各的。",
        "语言路由：中文题匹配中文回答能力，英文题匹配英文回答能力，通用题参与全部采样；不同语言问题组独立计算分母。",
    )
    html = html.replace(
        "`同一批无提示采样下的对手出现率，国内（${NS.cn||0} 条）与海外（${NS.global||0} 条）分开算、分母各用各的。对手领先是可复制的——补上它们被引用的那类内容，你就能进同一批回答。竞品的引用份额与内容承接无法从外部测量，故不列。`",
        "`同一批无提示采样共 ${Number(NS.cn||0)+Number(NS.global||0)} 条有效样本，对手出现率按问题语言对应的有效样本计算。领先并非不可复制：补齐对手常被引用的内容类型，你也能进入同类回答。竞品的引用份额与内容承接无法从外部可靠测量，因此不展示。`",
    )
    html = html.replace("严格高于同市场所有引擎", "严格高于同语言问题组所有引擎")
    html = html.replace("GeoLook", "DisvorAI").replace("geolook", "disvorai")
    html = html.replace("+ 接入新品牌", "添加品牌")
    html = html.replace("go('onboard',{obStep:1})", "startBrandOnboarding()")
    html = html.replace(
        'Geo<span style="color:var(--accent)">Look</span>',
        'Disvor<span style="color:var(--accent)">AI</span>',
    )
    html = html.replace("</style>", SETTINGS_RESPONSIVE_STYLE + ADMIN_SHELL_STYLE + "</style>", 1)
    html = html.replace(
        '<button id="burger" class="btn btn-secondary" onclick="document.getElementById(\'side\').classList.toggle(\'open\')">☰</button>',
        '<button id="burger" class="btn btn-secondary" type="button" aria-label="打开导航" '
        'onclick="document.getElementById(\'side\').classList.toggle(\'open\')">'
        '<span class="admin-icon icon-menu" aria-hidden="true"></span></button>',
        1,
    )
    html = html.replace(
        '<aside id="side"></aside>',
        '<aside id="side"></aside><button id="nav-scrim" type="button" aria-label="关闭导航" '
        'onclick="document.getElementById(\'side\').classList.remove(\'open\')"></button>',
        1,
    )
    html = html.replace(
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:26px">',
        '<div class="settings-core-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:26px">',
        1,
    )
    html = html.replace(
        '点「配置」填 Key 和模型，写入项目根目录 .env，立即生效。无 API 的引擎走人工采样表。',
        'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。参数化知识基于模型权重，不启用实时搜索或外部检索；无公开 API 的引擎走人工产品端采样表。',
    )
    html = html.replace(
        '把成稿从「内容工作台」发到你自己的渠道。凭证写 .env；',
        '把成稿从「内容工作台」发到你自己的渠道。凭证使用 AES-256-GCM 加密保存；',
    )
    html = html.replace(
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。参数化知识基于模型权重，不启用实时搜索或外部检索；无公开 API 的引擎走人工产品端采样表。':'Click Configure to set keys & models (written to local .env, effective immediately). Engines without APIs use manual sheets.'",
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。参数化知识基于模型权重，不启用实时搜索或外部检索；无公开 API 的引擎走人工产品端采样表。':'API keys are encrypted with AES-256-GCM and injected only while a job runs. Parametric knowledge uses model weights without live search or external retrieval; engines without public APIs use manual product sampling.'",
    )
    html = html.replace(
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。参数化知识基于模型权重，不启用实时搜索或外部检索；无公开 API 的引擎走人工产品端采样表。':'「設定」で Key とモデルを入力するとローカル .env に書き込まれ即時反映。API なしのエンジンは手動採取表で。'",
        "'API Key 使用 AES-256-GCM 加密保存，仅在任务运行期间注入。参数化知识基于模型权重，不启用实时搜索或外部检索；无公开 API 的引擎走人工产品端采样表。':'API キーは AES-256-GCM で暗号化保存し、ジョブ実行中のみ注入します。パラメトリック知識はリアルタイム検索や外部検索を使用せず、公開 API のないエンジンは製品画面で手動サンプリングします。'",
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
        "${esc(x.sampling_mode || (x.searched?'API · 联网检索':'API · 模型内知识'))}",
    )
    html = html.replace(
        "${mktLabel(k.market)} · ${k.ok===false?'缺 API Key':'仅人工采样'}",
        "${k.ok===false?(k.search?'API · 联网检索 · 缺 Key':'API · 模型内知识 · 缺 Key'):'人工 · 产品端核验'}",
    )
    html = html.replace(
        "${mktLabel(k.market)}${k.search?' · 联网':''}",
        "${k.manual?'人工 · 产品端核验':(k.search?'API · 联网检索':'API · 模型内知识')}",
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
        <label class="row" style="gap:6px;font-size:13px"><input type="checkbox" id="ob-nosample" style="width:auto" ${ST.obNoSample?'checked':''}> 首期跳过采样（省时间，可稍后补）</label>
      </details>
''',
        1,
    )
    html = html.replace(
        "ST.obMkt=document.querySelector('input[name=obm]:checked').value;",
        "ST.obMkt='both';",
    )
    html = html.replace(
        r'''  const mkNeed=ST.obMkt==='both'?['cn','global']:[ST.obMkt];
  const miss=mkNeed.filter(m=>!okKeys.some(k=>k.market===m));
  if(okKeys.length&&miss.length&&!confirm(`所选市场里 ${miss.map(m=>m==='cn'?'国内':'海外').join('、')} 尚无已配置的引擎 Key，该市场的自动采样会被跳过（可稍后补 Key 或用人工采样表）。\n\n仍要继续吗？`))
    {go('settings');return}
''',
        "",
        1,
    )
    html = html.replace(
        '''`<div class="muted" style="font-size:12px">已配置引擎：国内 ${okCn} 个 · 海外 ${okGl} 个（可在「设置」增改）${(ST.obMkt||'both')!=='global'&&!okCn?'——注意国内市场尚无可用 Key':''}${(ST.obMkt||'both')!=='cn'&&!okGl?'——注意海外市场尚无可用 Key':''}</div>`''',
        '''`<div class="muted" style="font-size:12px">已配置引擎：${okCn+okGl} 个（可在「设置」增改）</div>`''',
        1,
    )
    html = html.replace(
        '''    <div class="field"><label>市场</label><div class="seg">
      ${['cn','global','both'].map(m=>`<label class="seg-opt"><input type="radio" name="cmkt" value="${m}" ${cfg.market===m?'checked':''}>${({cn:'国内',global:'海外',both:'两者都要'})[m]}</label>`).join('')}</div></div>
''',
        "",
        1,
    )
    html = html.replace(
        "cfg.competitors=sp($('#c-comp').value).map(n=>old[n]||{name:n,aliases:[],market:cfg.market==='global'?'global':'cn'});",
        "cfg.competitors=sp($('#c-comp').value).map(n=>old[n]||{name:n,aliases:[],market:'both'});",
    )
    html = html.replace(
        "cfg.market=document.querySelector('input[name=cmkt]:checked').value;",
        "cfg.market='both';",
    )
    html = html.replace(
        "${RUNNING?`<button class=\"btn btn-secondary\" style=\"font-size:12px\" onclick=\"stopJob()\">停止任务</button>`:''}",
        "",
    )
    html = html.replace(
        '<button class="btn btn-primary" onclick="runAction(\'verify\')">自动验收</button>',
        '<button class="btn btn-secondary" onclick="offsiteTicketModal()">创建外部协作任务</button>'
        '<button class="btn btn-primary" onclick="runAction(\'verify\')">自动验收</button>',
        1,
    )
    html = html.replace("`go('settings')`:`go('report')`", "`go('engine-settings')`:`go('report')`")
    html = html.replace("closeModal();go('settings')\">渠道配置", "closeModal();go('publishing')\">渠道配置")
    html = html.replace("onclick=\"go('settings')\">去配置 Key", "onclick=\"go('engine-settings')\">去配置 Key")
    html = html.replace("onclick=\"go('settings')\">返回设置", "onclick=\"go('project-settings')\">返回设置")
    html = html.replace("onclick=\"go('settings')\">去设置手动跑", "onclick=\"go('automation')\">去设置手动跑")
    html = html.replace("{go('settings');return}", "{go('engine-settings');return}")
    html = html.replace("onclick=\"go('settings')\">去设置", "onclick=\"go('project-settings')\">去设置")
    html = html.replace("?'overview':'settings'", "?'overview':'project-settings'")
    html = html.replace(
        "if((R==='settings'||R==='onboard')&&RUNNING)pollJob();",
        "if((R==='settings'||R==='automation'||R==='onboard')&&RUNNING)pollJob();",
    )
    html = html.replace("<body>", "<body>" + FETCH_ADAPTER, 1)
    html = html.replace("</body>", UI_EXTENSION + "</body>", 1)
    html = html.replace("国内", "中文").replace("海外", "英文")
    html = html.replace("中文市场", "中文问题").replace("英文市场", "英文问题")
    html = html.replace("中文引擎", "中文问题").replace("英文引擎", "英文问题")
    html = html.replace("分母为本市场", "分母为该语言组")
    html = html.replace("全市场口径", "全部有效样本口径")
    html = html.replace("目标市场", "问题语言")
    html = html.replace("来源：百度下拉（中文）+ Google 补全（英文）", "来源：百度与 Google 搜索建议")
    html = html.replace(
        "拉百度下拉（中文）与 Google 补全（英文）的真实搜索词",
        "从百度与 Google 获取真实搜索建议",
    )
    html = html.replace("这是中文官网最常见的致命伤", "这是前端渲染站点常见的致命问题")
    html = html.replace("'中文':'CN'", "'中文':'Chinese'").replace("'英文':'Global'", "'英文':'English'")
    html = html.replace("'中文':'中国'", "'中文':'中国語'").replace("'英文':'英文'", "'英文':'英語'")
    html = html.replace("CN market", "Chinese questions").replace("Global market", "English questions")
    html = html.replace("CN engines", "Chinese questions").replace("Global engines", "English questions")
    html = html.replace("CN · manual only", "Chinese · manual only")
    html = html.replace("Global · manual only", "English · manual only")
    html = html.replace("CN · you", "Chinese · you").replace("Global · you", "English · you")
    html = html.replace("in this market", "for this language group")
    html = html.replace("market-wide", "across all valid samples")
    html = html.replace("the most common fatal flaw on CN sites", "a common critical issue on client-rendered sites")
    html = html.replace(
        "Sources: Baidu suggest (CN) + Google autocomplete (Global).",
        "Sources: Baidu and Google search suggestions.",
    )
    html = html.replace(
        "pull real search terms from Baidu suggest (CN) and Google autocomplete (Global)",
        "pull real search suggestions from Baidu and Google",
    )
    html = html.replace("WeChat drafts", "WeChat Official Account drafts")
    html = html.replace(
        "preview and send from the WeChat console",
        "preview and publish from the WeChat Official Account admin console",
    )
    html = html.replace(
        "WeChat / WordPress get drafts only, released after you confirm in their consoles.",
        "WeChat Official Account and WordPress create drafts only. Publish them from the respective platform consoles.",
    )
    html = html.replace("中国市場", "中国語の質問").replace("グローバル市場", "英語の質問")
    html = html.replace("中国エンジン", "中国語の質問").replace("英文エンジン", "英語の質問")
    html = html.replace("本市場", "この言語グループ").replace("全市場", "全有効サンプル")
    html = html.replace("中国 · 手動のみ", "中国語 · 手動のみ").replace("英文 · 手動のみ", "英語 · 手動のみ")
    html = html.replace(
        "百度サジェスト（中国）+ Google オートコンプリート（英文）",
        "百度と Google の検索サジェスト",
    )
    html = html.replace(
        "百度サジェスト（中国）と Google オートコンプリート（英文）から実検索語を取得",
        "百度と Google から実際の検索サジェストを取得",
    )
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
