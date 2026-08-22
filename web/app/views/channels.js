/**
 * AI 联网采样引用信源。
 */

import { projects } from '../api.js?v=3.8';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';
import { renderEmpty } from '../components/empty.js';
import { openModal } from '../components/modal.js';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function runCitationSample(ctx, button) {
  const projectId = ctx.activeProjectId;
  if (!projectId) return;
  button.disabled = true;
  try {
    const result = await projects.triggerSample(projectId);
    toast.success(t('channels.sample_queued', {}, 'Citation sampling queued across the configured model matrix.'));
    ctx.pollActiveJobs();
    if (result?.job_id && typeof ctx.openTelemetry === 'function') {
      ctx.openTelemetry(result.job_id, 'sample');
    }
  } catch (err) {
    toast.error(t(err.error, {}, err.detail || 'Sampling task failed to start'));
  } finally {
    button.disabled = false;
  }
}

export default {
  render: async (ctx) => {
    const projectId = ctx.activeProjectId;
    if (!projectId) {
      return `<div class="app-view-container">${renderEmpty({ title: t('overview.no_project_title', {}, 'No Brand Selected') })}</div>`;
    }

    const [report, externalEvidence, project] = await Promise.all([
      projects.getReport(projectId).catch(() => null),
      projects.getExternalEvidence(projectId).catch(() => []),
      projects.get(projectId).catch(() => null),
    ]);
    const channels = report?.channels || [];
    const totalMentions = channels.reduce((sum, channel) => sum + Number(channel.count || 0), 0);
    const cohort = report?.sample_artifact || report?.date || null;
    const ownHost = String(project?.url || '').replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '').toLowerCase();
    const officialSource = channels.find((channel) => String(channel.domain || '').toLowerCase().replace(/^www\./, '') === ownHost);

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('channels.title', {}, 'AI Citation Sources')}</h1>
            <p class="view-desc">
              ${t('channels.desc', {}, 'See which third-party domains the latest web-enabled AI samples used as evidence.')}
            </p>
          </div>
          <div class="view-actions">
            <a href="#/engines" class="btn btn-secondary btn-sm">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>
              <span>${t('channels.review_samples', {}, 'Review Raw Citations')}</span>
            </a>
            <a href="${projects.exportCsv(projectId)}" class="btn btn-secondary btn-sm" download>
              <span aria-hidden="true">↓</span><span>Download CSV</span>
            </a>
            <button type="button" class="btn btn-primary btn-sm btn-run-citation-sample">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>${t('channels.sample_now', {}, 'Run Citation Sampling')}</span>
            </button>
          </div>
        </div>

        <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-4);flex-wrap:wrap;padding:0 var(--sp-1);">
          <div style="display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;">
            <span class="tag tag-neutral">${t('channels.evidence_badge', {}, 'Web citation evidence')}</span>
            <span style="font-size:var(--fs-2);color:var(--muted);">
              ${t('channels.source_note', {}, 'Only source URLs returned by web-enabled model samples are counted.')}
            </span>
          </div>
          ${cohort ? `<span class="tag tag-dim num">Cohort ${escapeHtml(cohort)}</span>` : ''}
        </div>

        ${channels.length ? `
          <div class="card" style="padding:0;overflow:hidden;">
            <div style="padding:var(--sp-4);border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
              <div>
                <h2 style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('channels.top_domains', {}, 'Top Cited Domains')}</h2>
                <p style="font-size:var(--fs-1);color:var(--muted);margin:2px 0 0;">${channels.length} domains · ${totalMentions} citation mentions</p>
              </div>
            </div>
            <div class="tbl" style="overflow-x:auto;">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>${t('channels.col_domain', {}, 'Source Domain')}</th>
                    <th>${t('channels.col_engines', {}, 'Observed In')}</th>
                    <th>${t('channels.col_questions', {}, 'Question Evidence')}</th>
                    <th style="text-align:right;">${t('channels.col_citations', {}, 'Mentions')}</th>
                    <th style="text-align:right;">${t('channels.col_share', {}, 'Share')}</th>
                    <th>${t('channels.col_opportunity', {}, 'Next Action')}</th>
                  </tr>
                </thead>
                <tbody>
                  ${channels.map((channel, index) => {
                    const engines = Array.isArray(channel.engines) ? channel.engines : [];
                    const questions = Array.isArray(channel.sample_questions) ? channel.sample_questions : [];
                    const questionCount = Number(channel.question_count || questions.length);
                    const share = totalMentions ? Math.round(Number(channel.count || 0) * 1000 / totalMentions) / 10 : 0;
                    return `
                      <tr>
                        <td class="num" style="color:var(--muted);">${index + 1}</td>
                        <td><strong class="num" style="font-size:var(--fs-3);color:var(--ink);">${escapeHtml(channel.domain)}</strong></td>
                        <td>
                          <div style="display:flex;gap:4px;flex-wrap:wrap;">
                            ${engines.length ? engines.map((engine) => `<span class="tag tag-neutral">${escapeHtml(engine)}</span>`).join('') : '<span class="tag tag-dim">Unknown model</span>'}
                          </div>
                        </td>
                        <td style="max-width:340px;">
                          ${questions.length ? `
                            <div style="font-size:var(--fs-2);color:var(--ink);line-height:1.45;overflow-wrap:anywhere;">${escapeHtml(questions[0])}</div>
                            ${questionCount > 1 ? `<span style="font-size:var(--fs-1);color:var(--muted);">+${questionCount - 1} more question${questionCount === 2 ? '' : 's'}</span>` : ''}
                          ` : '<span style="color:var(--muted);">Question unavailable</span>'}
                        </td>
                        <td data-num style="font-weight:700;text-align:right;">${Number(channel.count || 0)}</td>
                        <td data-num style="text-align:right;">${share.toFixed(1)}%</td>
                        <td><a href="#/outreach" class="btn btn-ghost btn-sm">${t('channels.create_outreach', {}, 'Draft Outreach')} →</a></td>
                      </tr>
                    `;
                  }).join('')}
                </tbody>
              </table>
            </div>
          </div>
        ` : `
          <div class="card" style="padding:var(--sp-8);">
            <div class="empty">
              <strong>${t('channels.empty_title', {}, 'No citation sources captured yet')}</strong>
              <p style="max-width:58ch;margin:0 auto;color:var(--muted);">
                ${t('channels.no_citations_yet', {}, 'Run the configured model matrix. Citation domains will appear when a web-enabled model returns source URLs; parametric-only answers do not create citation evidence.')}
              </p>
              <div style="display:flex;gap:var(--sp-2);flex-wrap:wrap;justify-content:center;">
                <button type="button" class="btn btn-primary btn-sm btn-run-citation-sample">${t('channels.sample_now', {}, 'Run Citation Sampling')}</button>
                <a href="#/engine-settings" class="btn btn-secondary btn-sm">${t('engines.configure_keys', {}, 'Configure API Keys')}</a>
              </div>
            </div>
          </div>
        `}
        <section class="card" style="gap:var(--sp-3);border-left:3px solid ${officialSource ? 'var(--good)' : 'var(--warn)'};">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div><h2 style="font-size:var(--fs-4);font-weight:600;margin:0;">Official citation gap</h2><p style="font-size:var(--fs-2);color:var(--muted);margin:4px 0 0;">This compares the latest web-enabled citation cohort with your official domain. It is a source observation, not a ranking guarantee.</p></div>
            <span class="tag ${officialSource ? 'pill-good' : 'pill-warn'}">${officialSource ? `${officialSource.count || 0} mentions` : 'Not observed'}</span>
          </div>
          <div style="font-size:var(--fs-2);color:var(--muted);">Official domain: <strong style="color:var(--ink);">${escapeHtml(ownHost || 'Not recorded')}</strong>${officialSource ? ` · ${Number(officialSource.question_count || 0)} question contexts` : ' · add verified third-party evidence or review the source replay for the missing citation path.'}</div>
        </section>
        <section class="card" style="gap:var(--sp-3);">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div>
              <h2 style="font-size:var(--fs-4);font-weight:600;margin:0;">External evidence records</h2>
              <p style="font-size:var(--fs-2);color:var(--muted);margin:4px 0 0;">Record real third-party sources and the facts they support. CiteAura does not invent or auto-verify external coverage.</p>
            </div>
            <button type="button" id="btn-add-external-evidence" class="btn btn-secondary btn-sm">Add evidence record</button>
          </div>
          ${externalEvidence.length ? `<div class="tbl" style="overflow-x:auto;"><table class="table"><thead><tr><th>Source</th><th>Fact supported</th><th>Questions</th><th>Status</th></tr></thead><tbody>${externalEvidence.map((record) => `<tr><td><a href="${escapeHtml(record.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(record.url)}</a><div style="color:var(--muted);font-size:var(--fs-1);">${escapeHtml(record.source_type || '')}</div></td><td>${escapeHtml(record.fact_supported || '')}</td><td>${escapeHtml((record.question_ids || []).join(', ') || 'Not mapped')}</td><td><span class="tag tag-warn">Manual confirmation required</span></td></tr>`).join('')}</tbody></table></div>` : '<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">No external evidence has been confirmed for this project.</p>'}
        </section>
      </div>
    `;
  },

  mounted: (ctx) => {
    document.querySelectorAll('.btn-run-citation-sample').forEach((button) => {
      button.addEventListener('click', () => runCitationSample(ctx, button));
    });
    document.getElementById('btn-add-external-evidence')?.addEventListener('click', async () => {
      openModal({
        title: 'Add external evidence record',
        content: `<div class="field"><label>Source URL</label><input id="external-url" class="input" type="url" placeholder="https://example.com/source"></div><div class="field"><label>Source type</label><input id="external-type" class="input" placeholder="Review platform, directory, encyclopedia"></div><div class="field"><label>Fact supported</label><textarea id="external-fact" class="input" rows="4" placeholder="Which verified fact does this source support?"></textarea></div><div class="field"><label>Question IDs</label><input id="external-questions" class="input" placeholder="q101, q102"></div><div class="field"><label>Reviewer</label><input id="external-reviewer" class="input" placeholder="Reviewer name or email"></div>`,
        confirmText: 'Save record',
        onConfirm: async () => {
          const url = document.getElementById('external-url')?.value?.trim();
          const sourceType = document.getElementById('external-type')?.value?.trim();
          const fact = document.getElementById('external-fact')?.value?.trim();
          if (!url || !sourceType || !fact) {
            toast.error('URL, source type, and supported fact are required');
            return false;
          }
          try {
            await projects.addExternalEvidence(ctx.activeProjectId, {
              url,
              source_type: sourceType,
              fact_supported: fact,
              question_ids: (document.getElementById('external-questions')?.value || '').split(',').map((value) => value.trim()).filter(Boolean),
              reviewer: document.getElementById('external-reviewer')?.value?.trim() || '',
            });
            toast.success('Evidence record saved');
            await ctx.reloadCurrentView();
            return true;
          } catch (err) {
            toast.error(err.detail || 'Failed to save evidence record');
            return false;
          }
        },
      });
    });
  },
};
