import { workspace, projects } from '../api.js?v=3.4';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function assetStatusLabel(status) {
  return status === 'deployable' ? t('common.deployable', {}, 'Deployable') : status === 'review_required' ? t('common.review_required', {}, 'Review required') : status === 'draft' ? t('common.draft', {}, 'Draft') : t('common.unavailable', {}, 'Unavailable');
}

function campaignStatus(status) {
  if (status === 'ready_for_approval') return { label: t('assets.ready_for_approval', {}, 'Ready for approval'), className: 'pill-good' };
  if (status === 'review_required') return { label: t('assets.review_required', {}, 'Review required'), className: 'pill-warn' };
  return { label: t('assets.blocked', {}, 'Blocked'), className: 'pill-bad' };
}

function percent(value) {
  return value === null || value === undefined ? t('common.unmeasured', {}, 'Unmeasured') : `${Math.round(Number(value) * 100)}%`;
}

function renderCampaignProposals(campaigns) {
  const items = Array.isArray(campaigns?.items) ? campaigns.items : [];
  const counts = campaigns?.counts || {};
  return `
    <section class="campaign-proposals" aria-labelledby="campaign-proposals-title">
      <div class="campaign-proposals-head">
        <div>
          <h2 id="campaign-proposals-title">${t('assets.proposals_title', {}, 'Campaign Proposals')}</h2>
          <p>${t('assets.proposals_desc', {}, 'Evidence-backed interventions awaiting measurement, fact review, or human approval.')}</p>
        </div>
        <div class="campaign-proposal-counts" aria-label="Campaign proposal status counts">
          <span class="tag pill-good">${counts.ready_for_approval || 0} ready</span>
          <span class="tag pill-warn">${counts.review_required || 0} review</span>
          <span class="tag pill-bad">${counts.blocked || 0} blocked</span>
        </div>
      </div>
      ${items.length ? `<div class="campaign-proposal-list">${items.map((proposal) => {
        const status = campaignStatus(proposal.status);
        const promptEvidence = (proposal.evidence || []).find((item) => item.type === 'prompt_opportunity') || {};
        const takeoverEvidence = (proposal.evidence || []).filter((item) => item.type === 'takeover_candidate');
        const baselines = proposal.expected_impact?.cohort_baselines || [];
        const tickets = proposal.related_tickets || [];
        const linkedAssets = proposal.related_assets || [];
        const questionId = proposal.target_question?.id || '';
        const workflow = proposal.workflow || {};
        const opportunity = promptEvidence.opportunity_score === null || promptEvidence.opportunity_score === undefined
          ? 'Evidence pending'
          : `Opportunity ${promptEvidence.opportunity_score}/100`;
        return `<article class="campaign-proposal">
          <div class="campaign-proposal-main">
            <div class="campaign-proposal-title-row">
              <span class="num campaign-proposal-id">${escapeHtml(questionId)}</span>
              <span class="tag ${status.className}">${status.label}</span>
              ${takeoverEvidence.length ? `<span class="tag tag-outline">${t('assets.competitive_gap', {}, 'Competitive gap')}</span>` : ''}
            </div>
            <h3>${escapeHtml(proposal.title || 'Campaign proposal')}</h3>
            <p class="campaign-proposal-objective">${escapeHtml(proposal.objective || '')}</p>
            <div class="campaign-proposal-evidence">
              <span><strong>${escapeHtml(opportunity)}</strong></span>
              <span>Aggregate mention ${escapeHtml(percent(promptEvidence.mention_rate))} · n=${Number(promptEvidence.samples || 0)}</span>
              <span>${baselines.length} separate cohort baseline${baselines.length === 1 ? '' : 's'}</span>
              ${takeoverEvidence.slice(0, 2).map((item) => `<span>${escapeHtml(item.competitor || 'Competitor')} · ${escapeHtml(item.engine_name || '')} · ${escapeHtml(item.sampling_mode || '')}</span>`).join('')}
            </div>
          </div>
          <div class="campaign-proposal-side">
            <div>
              <span class="campaign-proposal-label">${t('assets.expected_impact', {}, 'Expected impact')}</span>
              <p>${escapeHtml(proposal.expected_impact?.statement || '')}</p>
            </div>
            <div>
              <span class="campaign-proposal-label">${t('assets.linked_work', {}, 'Linked work')}</span>
              <div class="campaign-proposal-links">
                ${tickets.slice(0, 3).map((ticket) => `<span class="tag tag-neutral">${escapeHtml(ticket.id || 'Ticket')} · ${escapeHtml(ticket.status || '')}</span>`).join('')}
                ${linkedAssets.slice(0, 3).map((asset) => `<span class="tag tag-neutral">${escapeHtml(asset.path)} · ${escapeHtml(asset.status || '')}</span>`).join('')}
                ${!tickets.length && !linkedAssets.length ? `<span class="muted">${t('assets.no_linked_work', {}, 'No linked implementation artifact yet')}</span>` : ''}
              </div>
            </div>
            <div class="campaign-proposal-links" aria-label="Campaign workflow">
              <span class="tag ${workflow.evidence?.status === 'available' ? 'pill-good' : 'pill-warn'}">Evidence ${escapeHtml(workflow.evidence?.status || 'pending')}</span>
              <span class="tag ${workflow.ticket?.status === 'linked' ? 'tag-neutral' : 'tag-dim'}">Ticket ${escapeHtml(workflow.ticket?.status || 'missing')}</span>
              <span class="tag ${workflow.asset?.status === 'linked' ? 'tag-neutral' : 'tag-dim'}">Asset ${escapeHtml(workflow.asset?.status || 'missing')}</span>
              <span class="tag ${workflow.review?.status === 'ready' ? 'pill-good' : 'pill-warn'}">Review ${escapeHtml(workflow.review?.status || 'required')}</span>
              <span class="tag tag-dim">${t('assets.verify_pending', {}, 'Verify pending')}</span>
            </div>
            <a class="btn btn-secondary btn-sm campaign-proposal-action" data-action="${escapeHtml(proposal.next_step?.action || '')}" data-question-id="${escapeHtml(questionId)}" href="${escapeHtml(proposal.next_step?.route || '#/assets')}">${escapeHtml(proposal.next_step?.label || 'Review proposal')}</a>
          </div>
        </article>`;
      }).join('')}</div>` : `<div class="campaign-proposals-empty">${t('assets.no_proposals', {}, 'No proposals yet. Collect comparable samples to turn prompt gaps into reviewable work.')}</div>`}
      <p class="campaign-proposal-policy">${t('assets.policy_note', {}, 'Impact remains a hypothesis until the same question, engine, sampling mode, and measurement policy are rerun after deployment. Publication always requires human approval.')}</p>
    </section>`;
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }
    const [assets, project] = await Promise.all([
      workspace.getAssets(projectId).catch(() => []),
      projects.get(projectId).catch(() => null),
    ]);
    const requestedQuestion = String(ctx.params?.question || '');
    const requestedAsset = assets.find((item) => {
      const filename = String(item.path || '').split('/').pop() || '';
      return filename.split('.')[0] === requestedQuestion;
    });
    const firstPath = requestedAsset?.path || assets[0]?.path || '';
    const first = firstPath
      ? await workspace.getAsset(projectId, firstPath).catch(() => ({ path: firstPath, text: '' }))
      : { path: '', text: '' };
    const campaigns = project?.insights?.campaign_proposals || {};
    const reviewRequired = assets.filter((item) => item.status === 'review_required');
    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group"><h1 class="view-title">${t('assets.title', {}, 'Campaigns & Assets')}</h1><p class="view-desc">${t('assets.library_desc', {}, 'Review evidence-backed interventions, then prepare the assets required for implementation.')}</p></div>
          <div class="view-actions">${assets.length
            ? `<button type="button" id="btn-save-asset" class="btn btn-primary btn-sm">${t('common.save', {}, 'Save Asset')}</button>`
            : `<button type="button" id="btn-generate-assets" class="btn btn-primary btn-sm">${t('assets.generate_btn', {}, 'Generate assets')}</button>`}</div>
        </div>
        ${renderCampaignProposals(campaigns)}
        ${reviewRequired.length ? `<div class="banner warn" style="margin-bottom:var(--sp-4);"><div><strong>Review required.</strong> ${reviewRequired.length} derived asset(s) cannot be published until the brand fact library and supporting evidence are approved.</div></div>` : ''}
        ${assets.length ? `<div class="card" style="gap:var(--sp-4);">
          <div class="field" style="margin:0;">
            <label for="asset-path">Asset file</label>
            <select id="asset-path" class="input">
              ${assets.map((item) => `<option value="${escapeHtml(item.path)}" ${item.path === first.path ? 'selected' : ''}>${escapeHtml(item.path)} · ${assetStatusLabel(item.status)}</option>`).join('')}
            </select>
          </div>
          <div class="field" style="margin:0;">
            <label for="asset-text">File contents</label>
            <textarea id="asset-text" class="input" rows="24">${escapeHtml(first.text || '')}</textarea>
          </div>
        </div>` : renderEmpty({ title: 'No generated assets', description: 'Generate project-specific files from the current audit and approved facts library.' })}
      </div>`;
  },

  mounted: (ctx) => {
    const projectId = ctx.activeProjectId;
    const pathSelect = document.getElementById('asset-path');
    const editor = document.getElementById('asset-text');
    pathSelect?.addEventListener('change', async () => {
      const asset = await workspace.getAsset(projectId, pathSelect.value).catch(() => null);
      if (asset) editor.value = asset.text || '';
    });
    document.getElementById('btn-generate-assets')?.addEventListener('click', async () => {
      try {
        const res = await projects.triggerAction(projectId, 'generate');
        toast.success('Asset generation queued');
        ctx.pollActiveJobs();
        if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'generate');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to generate assets'));
      }
    });
    document.querySelectorAll('[data-action="fill_question_gap"]').forEach((button) => {
      button.addEventListener('click', async (event) => {
        event.preventDefault();
        button.setAttribute('aria-busy', 'true');
        try {
          const questionId = button.dataset.questionId;
          const res = await projects.triggerSampleGaps(projectId, questionId ? { question_ids: [questionId] } : {});
          if (res?.status === 'no_gaps') {
            toast.success('No comparable samples are missing for this question');
          } else {
            toast.success('Comparable question sampling queued');
            ctx.pollActiveJobs();
            if (res?.job_id && typeof ctx.openTelemetry === 'function') ctx.openTelemetry(res.job_id, 'sample');
          }
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Failed to queue comparable sampling'));
        } finally {
          button.removeAttribute('aria-busy');
        }
      });
    });
    document.getElementById('btn-save-asset')?.addEventListener('click', async () => {
      try {
        await workspace.saveAsset(projectId, pathSelect.value, editor.value);
        toast.success('Asset saved');
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Failed to save asset'));
      }
    });
  },
};
