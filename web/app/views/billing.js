/**
 *  (Billing & Plans)
 */

import { billing } from '../api.js';
import { t, tError } from '../i18n.js';
import { toast } from '../components/toast.js';
import { escapeHtml } from '../safe-html.js';

const PLAN_NAMES = { starter: 'Starter', pro: 'Pro', agency: 'Agency' };

const INTENT_PLAN_KEY = 'citeaura_intent_plan';
const SUBSCRIBABLE = new Set(['starter', 'pro', 'agency']);

function formatUsd(amount) {
  if (amount === null || amount === undefined) return t('landing.plan_ent_price', {}, 'Custom');
  return '$' + String(amount);
}

function planByCode(plans, code) {
  return (plans || []).find((item) => item.code === code) || null;
}

function planSummary(plan, interval, fallbackMonthly, fallbackAnnual) {
  if (!plan) return interval === 'annual' ? fallbackAnnual : fallbackMonthly;
  if (interval === 'annual') {
    const yearly = plan.prices?.annual?.usd;
    const months = plan.prices?.annual?.months || 12;
    if (typeof yearly === 'number' && months > 0) {
      return `About $${Math.round(yearly / months)} / month billed annually`;
    }
  }
  return fallbackMonthly;
}

function formatTrialEnds(value) {
  if (!value) return '';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch (e) {
    return '';
  }
}

function readIntentPlan(params) {
  const fromRoute = String(params?.plan || '').toLowerCase();
  if (SUBSCRIBABLE.has(fromRoute) || fromRoute === 'enterprise') return fromRoute;
  try {
    const stored = String(sessionStorage.getItem(INTENT_PLAN_KEY) || '').toLowerCase();
    if (SUBSCRIBABLE.has(stored) || stored === 'enterprise') return stored;
  } catch (e) {}
  return '';
}

function clearIntentPlan() {
  try {
    sessionStorage.removeItem(INTENT_PLAN_KEY);
  } catch (e) {}
}

export default {
  render: async (ctx) => {
    let usage = {};
    let plansData = {};
    try {
      [usage, plansData] = await Promise.all([
        billing.getUsage().catch(() => ({})),
        billing.getPlans().catch(() => ({})),
      ]);
    } catch (e) {}

    const currentPlan = usage.plan || 'trial';
    const subscription = usage.subscription || null;
    const activeProjects = usage.projects_active || 0;
    const maxProjects = usage.projects_limit;
    const paymentAvailable = Boolean(plansData.payment?.enabled && plansData.payment?.configured);
    const activeSubscription = ['active', 'trialing', 'past_due'].includes(subscription?.status);
    const canUpgrade = usage.can_upgrade !== false;
    const paymentDisabled = paymentAvailable && canUpgrade ? '' : 'disabled aria-disabled="true"';
    const paymentUnavailable = t('billing.payment_unavailable', {}, 'Payments unavailable');
    const starter = planByCode(plansData.plans, 'starter');
    const pro = planByCode(plansData.plans, 'pro');
    const agency = planByCode(plansData.plans, 'agency');
    const intentPlan = readIntentPlan(ctx.params);
    const trialEndsLabel = formatTrialEnds(usage.trial_ends_at);
    const onTrial = currentPlan === 'trial';
    const trialExpired = Boolean(usage.trial_expired);
    const billingStatus = String(ctx.params?.billing || '').toLowerCase();
    const funnel = usage.activation_funnel || {};
    const funnelSteps = Array.isArray(funnel.steps) ? funnel.steps : [];
    const projectsRemaining = usage.projects_remaining;
    const sampleRemaining = usage.sample_runs_remaining;
    const poolCalls = Number(usage.platform_pool_calls || usage.platform_pool?.calls || 0);
    const poolCostFen = Number(usage.platform_pool_cost_cny_fen || usage.platform_pool?.cost_cny_fen || 0);

    const subscribeLabel = (code, label) => {
      const planName = PLAN_NAMES[code] || code;
      if (currentPlan === code) return t('billing.current_plan', {}, 'Current Plan');
      if (!paymentAvailable) return paymentUnavailable;
      if (!canUpgrade) return t('billing.plan_change_unavailable', {}, 'Plan change unavailable');
      if (activeSubscription) return t('billing.switch_to', { plan: planName }, `Switch to ${planName}`);
      return label;
    };

    return `
      <div class="app-view-container">
        <div class="view-header">
          <div class="view-title-group">
            <h1 class="view-title">${t('billing.title', {}, 'Subscription & Billing')}</h1>
            <p class="view-desc">
              ${t('billing.desc', {}, 'Transparent SaaS tiers with unlimited BYOK sampling. Upgrade to expand active projects and unlock white-label agency delivery.')}
            </p>
          </div>
        </div>

        ${billingStatus === 'success' ? `
          <div class="banner good" style="margin-bottom:var(--sp-4);">
            ${t('billing.payment_received', {}, 'Payment received. Your plan unlocks as soon as Stripe confirms the subscription.')}
          </div>` : ''}
        ${billingStatus === 'canceled' ? `
          <div class="banner warn" style="margin-bottom:var(--sp-4);">
            ${t('billing.checkout_canceled', {}, 'Checkout was canceled. You can resume any plan below — no need to wait for the trial to end.')}
          </div>` : ''}

        <!-- Current Plan Status Card -->
        <div class="card" style="gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--sp-3);">
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              <span class="tag tag-accent" style="font-size:var(--fs-3);padding:var(--sp-1) var(--sp-3);text-transform:uppercase;">
                ${currentPlan}
              </span>
              <div>
                <strong>${t('billing.current_plan', {}, 'Active Plan')}</strong>
                <div style="font-size:var(--fs-2);color:var(--muted);">${t('billing.active_projects', { active: activeProjects, max: maxProjects === null || maxProjects === undefined ? '∞' : maxProjects }, `Active projects: ${activeProjects} / ${maxProjects === null || maxProjects === undefined ? '∞' : maxProjects}`)}</div>
                ${onTrial ? `<div style="font-size:var(--fs-2);color:var(--muted);">${t('billing.trial_samples', { used: usage.sample_runs_lifetime || 0, limit: usage.sample_runs_lifetime_limit || 6, per_project: usage.sample_runs_limit_per_project || 2 }, `Trial samples: ${usage.sample_runs_lifetime || 0} / ${usage.sample_runs_lifetime_limit || 6} lifetime · ${usage.sample_runs_limit_per_project || 2} per project`)}</div>` : ''}
                ${onTrial ? `
                  <div style="font-size:var(--fs-2);color:var(--muted);margin-top:2px;">
                    ${trialExpired
                      ? t('billing.trial_ended_upgrade', {}, 'Trial ended — upgrade now to restore full access.')
                      : (trialEndsLabel
                        ? t('billing.trial_ends_notice', { date: trialEndsLabel }, `Trial ends ${trialEndsLabel}. You can upgrade to Pro or higher anytime — no need to wait.`)
                        : t('billing.trial_upgrade_anytime', {}, 'You can upgrade to Pro or higher anytime during the trial.'))}
                  </div>` : ''}
              </div>
            </div>
            <div class="seg" id="billing-interval-toggle">
              <button type="button" class="seg-opt is-active" data-int="monthly" ${paymentAvailable ? '' : 'disabled aria-disabled="true"'}>${t('landing.billing_monthly', {}, 'Monthly')}</button>
              <button type="button" class="seg-opt" data-int="annual" ${paymentAvailable ? '' : 'disabled aria-disabled="true"'}>${t('landing.billing_annual', {}, 'Annual · save ~20%')}</button>
            </div>
          </div>
          ${subscription && ['active', 'trialing', 'past_due'].includes(subscription.status) ? `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
              <span style="font-size:var(--fs-2);color:var(--muted);">${subscription.cancel_at_period_end ? t('billing.cancel_scheduled', {}, 'Cancellation scheduled for the end of the current billing period.') : t('billing.subscription_active', {}, 'Your subscription is active.')}</span>
              ${subscription.cancel_at_period_end ? '' : `<button type="button" id="btn-cancel-subscription" class="btn btn-danger btn-sm">${t('billing.cancel_period_end', {}, 'Cancel at Period End')}</button>`}
            </div>` : ''}
        </div>

        <section class="card" style="gap:var(--sp-4);" aria-labelledby="activation-funnel-title">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
            <div>
              <h2 id="activation-funnel-title" style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('billing.activation_title', {}, 'Activation progress')}</h2>
              <p style="font-size:var(--fs-2);color:var(--muted);margin:4px 0 0;">${t('billing.activation_desc', {}, 'Track the path from registration to a repeatable, evidence-backed delivery.')}</p>
            </div>
            <span class="tag ${funnel.completed_steps === funnel.total_steps && funnel.total_steps ? 'pill-good' : 'tag-accent'}">${t('billing.funnel.complete_count', { done: Number(funnel.completed_steps || 0), total: Number(funnel.total_steps || 6) }, `${Number(funnel.completed_steps || 0)} / ${Number(funnel.total_steps || 6)} complete`)}</span>
          </div>
          <div style="height:6px;background:var(--line);border-radius:999px;overflow:hidden;" role="progressbar" aria-label="${t('billing.activation_title', {}, 'Activation progress')}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(funnel.progress_percent || 0)}">
            <div style="height:100%;width:${Math.max(0, Math.min(100, Number(funnel.progress_percent || 0)))}%;background:var(--accent);border-radius:inherit;"></div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:var(--sp-2);">
            ${funnelSteps.map((step) => {
              const stepLabel = t(`billing.funnel.${step.key}`, {}, step.label || step.key);
              return `<div style="display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-2);border:1px solid var(--line);background:var(--page);border-radius:var(--r-md);"><span class="tag ${step.completed ? 'pill-good' : 'tag-dim'}" aria-label="${step.completed ? t('common.done', {}, 'Done') : t('common.next', {}, 'Next')}">${step.completed ? t('common.done', {}, 'Done') : t('common.next', {}, 'Next')}</span><span style="font-size:var(--fs-2);">${escapeHtml(stepLabel)}</span></div>`;
            }).join('')}
          </div>
          ${funnel.next_step ? `<p style="margin:0;color:var(--muted);font-size:var(--fs-2);">${t('billing.funnel.next', { step: t(`billing.funnel.${funnel.next_step}`, {}, funnel.next_step_label || funnel.next_step) }, `Next: ${funnel.next_step_label || funnel.next_step}`)}</p>` : `<p style="margin:0;color:var(--good);font-size:var(--fs-2);">${t('billing.activation_complete', {}, 'Activation path complete for this workspace.')}</p>`}
        </section>

        <section class="card" style="gap:var(--sp-3);" aria-labelledby="usage-snapshot-title">
          <div>
            <h2 id="usage-snapshot-title" style="font-size:var(--fs-4);font-weight:600;margin:0;">${t('billing.usage_title', {}, 'Usage snapshot')}</h2>
            <p style="font-size:var(--fs-2);color:var(--muted);margin:4px 0 0;">${t('billing.usage_desc', {}, 'Current limits and platform-pool consumption are shown separately from BYOK usage.')}</p>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:var(--sp-2);">
            <div style="padding:var(--sp-3);border:1px solid var(--line);border-radius:var(--r-md);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('billing.projects_remaining', {}, 'Projects remaining')}</span><strong style="font-size:var(--fs-4);">${projectsRemaining === null || projectsRemaining === undefined ? t('billing.unlimited', {}, 'Unlimited') : projectsRemaining}</strong></div>
            <div style="padding:var(--sp-3);border:1px solid var(--line);border-radius:var(--r-md);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('billing.samples_remaining', {}, 'Sample runs remaining')}</span><strong style="font-size:var(--fs-4);">${sampleRemaining === null || sampleRemaining === undefined ? t('billing.unlimited', {}, 'Unlimited') : sampleRemaining}</strong></div>
            <div style="padding:var(--sp-3);border:1px solid var(--line);border-radius:var(--r-md);"><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${t('billing.pool_calls', {}, 'Platform-pool calls')}</span><strong style="font-size:var(--fs-4);">${poolCalls}</strong><span style="display:block;color:var(--muted);font-size:var(--fs-1);">${poolCostFen ? t('billing.pool_cost_month', { cost: (poolCostFen / 100).toFixed(2) }, `¥${(poolCostFen / 100).toFixed(2)} this month`) : t('billing.pool_cost_none', {}, 'No pool cost this month')}</span></div>
          </div>
        </section>

        <!-- Pricing Plans Grid -->
        <div class="pricing-grid">
          <!-- Starter -->
          <article class="price-card ${intentPlan === 'starter' ? 'is-intent' : ''}">
            <p class="plan-name">Starter</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(starter?.prices?.monthly?.usd)}" data-a="${formatUsd(starter?.prices?.annual?.usd)}">${formatUsd(starter?.prices?.monthly?.usd || 79)}</strong>
              <span class="price-period" data-m="${t('billing.per_month', {}, '/ month')}" data-a="${t('billing.per_year', {}, '/ year')}">${t('billing.per_month', {}, '/ month')}</span>
            </p>
            <p class="plan-summary" data-m="${t('landing.plan_starter_summary', {}, 'Ideal for indie makers & single brands')}" data-a="${t('landing.plan_starter_summary_annual', {}, 'About $63 / month billed annually')}">${t('landing.plan_starter_summary', {}, 'Ideal for indie makers & single brands')}</p>
            <ul>
              <li>${t('landing.plan_starter_1', {}, '3 active projects')}</li>
              <li>${t('landing.plan_starter_2', {}, '13 standard action tickets & verification runs')}</li>
              <li>${t('landing.plan_starter_3', {}, 'Full reports & customer delivery packs')}</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="starter" ${currentPlan === 'starter' || !canUpgrade || !paymentAvailable ? 'disabled aria-disabled="true"' : ''}>
              ${subscribeLabel('starter', t('billing.subscribe_starter', {}, 'Subscribe Starter'))}
            </button>
          </article>

          <!-- Pro (Featured) -->
          <article class="price-card price-card-featured ${intentPlan === 'pro' ? 'is-intent' : ''}">
            <p class="plan-badge">${t('landing.plan_pro_badge', {}, 'Most popular')}</p>
            <p class="plan-name">Pro</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(pro?.prices?.monthly?.usd)}" data-a="${formatUsd(pro?.prices?.annual?.usd)}">${formatUsd(pro?.prices?.monthly?.usd || 199)}</strong>
              <span class="price-period" data-m="${t('billing.per_month', {}, '/ month')}" data-a="${t('billing.per_year', {}, '/ year')}">${t('billing.per_month', {}, '/ month')}</span>
            </p>
            <p class="plan-summary" data-m="${t('landing.plan_pro_summary', {}, 'Continuous multi-model tracking for growth brands')}" data-a="${t('landing.plan_pro_summary_annual', {}, 'About $159 / month billed annually')}">${t('landing.plan_pro_summary', {}, 'Continuous multi-model tracking for growth brands')}</p>
            <ul>
              <li>${t('landing.plan_pro_1', {}, '10 active projects')}</li>
              <li>${t('landing.plan_pro_2', {}, 'Unlimited BYOK sampling')}</li>
              <li>${t('landing.plan_pro_3', {}, 'Scheduled re-sampling and email alerts on mention-rate drops')}</li>
            </ul>
            <button type="button" class="btn btn-primary btn-block btn-subscribe" data-plan="pro" ${currentPlan === 'pro' || !canUpgrade || !paymentAvailable ? 'disabled aria-disabled="true"' : ''}>
              ${subscribeLabel('pro', onTrial ? t('billing.upgrade_to_pro', {}, 'Upgrade to Pro') : t('landing.plan_pro_cta', {}, 'Subscribe Pro'))}
            </button>
          </article>

          <!-- Agency -->
          <article class="price-card ${intentPlan === 'agency' ? 'is-intent' : ''}">
            <p class="plan-name">Agency</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(agency?.prices?.monthly?.usd)}" data-a="${formatUsd(agency?.prices?.annual?.usd)}">${formatUsd(agency?.prices?.monthly?.usd || 499)}</strong>
              <span class="price-period" data-m="${t('billing.per_month', {}, '/ month')}" data-a="${t('billing.per_year', {}, '/ year')}">${t('billing.per_month', {}, '/ month')}</span>
            </p>
            <p class="plan-summary" data-m="${t('landing.plan_agency_summary', {}, 'Parallel client delivery for digital agencies')}" data-a="${t('landing.plan_agency_summary_annual', {}, 'About $416 / month billed annually')}">${t('landing.plan_agency_summary', {}, 'Parallel client delivery for digital agencies')}</p>
            <ul>
              <li>${t('landing.plan_agency_1', {}, '30 active projects')}</li>
              <li>${t('landing.plan_agency_2', {}, 'One-click sendable white-label client pack')}</li>
              <li>${t('landing.plan_agency_3', {}, 'Team multi-role permissions & white-label delivery branding')}</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="agency" ${currentPlan === 'agency' || !canUpgrade || !paymentAvailable ? 'disabled aria-disabled="true"' : ''}>
              ${subscribeLabel('agency', onTrial ? t('billing.upgrade_to_agency', {}, 'Upgrade to Agency') : t('landing.plan_agency_cta', {}, 'Subscribe Agency'))}
            </button>
          </article>

          <!-- Enterprise -->
          <article class="price-card ${intentPlan === 'enterprise' ? 'is-intent' : ''}">
            <p class="plan-name">Enterprise</p>
            <p class="price"><strong>${t('landing.plan_ent_price', {}, 'Custom')}</strong></p>
            <p class="plan-summary">${t('landing.plan_ent_summary', {}, 'Organization-scale private deployment')}</p>
            <ul>
              <li>${t('landing.plan_ent_1', {}, 'Dedicated private deploy & custom SLA')}</li>
              <li>${t('landing.plan_ent_2', {}, 'Enterprise OIDC SSO & audit events')}</li>
              <li>${t('landing.plan_ent_3', {}, 'Custom data retention & dedicated support team')}</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="enterprise">
              ${t('billing.contact_sales', {}, 'Contact Sales')}
            </button>
          </article>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    let currentInterval = 'monthly';
    const intentPlan = readIntentPlan(ctx.params);
    let autoCheckoutStarted = false;

    const startCheckout = async (plan, button) => {
      if (plan === 'enterprise') {
        toast.info(t('billing.contact_sales_tip', {}, 'Please contact sales@citeaura.com for enterprise plans.'));
        clearIntentPlan();
        return;
      }
      if (!SUBSCRIBABLE.has(plan)) return;
      if (button) button.disabled = true;
      try {
        const res = await billing.subscribe({ plan, billing_interval: currentInterval });
        clearIntentPlan();
        if (res && res.checkout_url) {
          window.location.assign(res.checkout_url);
          return;
        }
        toast.success(t('billing.subscribe_success', { plan: plan.toUpperCase() }, `Subscribed to ${plan.toUpperCase()}.`));
        ctx.navigate('#/billing');
      } catch (err) {
        toast.error(tError(err));
        if (button) button.disabled = false;
      }
    };

    document.getElementById('btn-cancel-subscription')?.addEventListener('click', async () => {
      const button = document.getElementById('btn-cancel-subscription');
      if (!window.confirm(t('billing.cancel_confirm', {}, 'Schedule cancellation at the end of the current billing period?'))) return;
      button.disabled = true;
      try {
        await billing.cancel();
        toast.success(t('billing.cancel_scheduled', {}, 'Cancellation scheduled for the end of the current billing period.'));
        await ctx.reloadCurrentView?.();
      } catch (err) {
        toast.error(tError(err));
        button.disabled = false;
      }
    });

    document.querySelectorAll('.btn-subscribe').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const plan = e.currentTarget.dataset.plan;
        startCheckout(plan, e.currentTarget);
      });
    });

    const toggle = document.getElementById('billing-interval-toggle');
    toggle?.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-int]');
      if (!btn) return;
      toggle.querySelectorAll('.seg-opt').forEach((b) => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      currentInterval = btn.dataset.int;

      document.querySelectorAll('.price-card').forEach((card) => {
        const valEl = card.querySelector('.price-val');
        const periodEl = card.querySelector('.price-period');
        const summaryEl = card.querySelector('.plan-summary');
        if (!valEl) return;
        if (currentInterval === 'annual') {
          valEl.textContent = valEl.dataset.a || valEl.textContent;
          if (periodEl) periodEl.textContent = periodEl.dataset.a || t('billing.per_year', {}, '/ year');
          if (summaryEl && summaryEl.dataset.a) summaryEl.textContent = summaryEl.dataset.a;
        } else {
          valEl.textContent = valEl.dataset.m || valEl.textContent;
          if (periodEl) periodEl.textContent = periodEl.dataset.m || t('billing.per_month', {}, '/ month');
          if (summaryEl && summaryEl.dataset.m) summaryEl.textContent = summaryEl.dataset.m;
        }
      });
    });

    if (intentPlan && SUBSCRIBABLE.has(intentPlan) && !autoCheckoutStarted) {
      autoCheckoutStarted = true;
      const targetBtn = document.querySelector(`.btn-subscribe[data-plan="${intentPlan}"]`);
      if (targetBtn && !targetBtn.disabled) {
        startCheckout(intentPlan, targetBtn);
      }
    }
  },
};
