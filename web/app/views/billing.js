/**
 *  (Billing & Plans)
 */

import { billing } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

function formatUsd(amount) {
  if (amount === null || amount === undefined) return 'Custom';
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
      return 'About $' + Math.round(yearly / months) + ' / month billed annually';
    }
  }
  return fallbackMonthly;
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
    const maxProjects = usage.projects_limit || 3;
    const paymentAvailable = Boolean(plansData.payment?.enabled && plansData.payment?.configured);
    const paymentDisabled = paymentAvailable ? '' : 'disabled aria-disabled="true"';
    const paymentUnavailable = t('billing.payment_unavailable', {}, 'Payments unavailable');
    const starter = planByCode(plansData.plans, 'starter');
    const pro = planByCode(plansData.plans, 'pro');
    const agency = planByCode(plansData.plans, 'agency');

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

        <!-- Current Plan Status Card -->
        <div class="card" style="gap:var(--sp-4);">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:var(--sp-3);">
            <div style="display:flex;align-items:center;gap:var(--sp-3);">
              <span class="tag tag-accent" style="font-size:var(--fs-3);padding:var(--sp-1) var(--sp-3);text-transform:uppercase;">
                ${currentPlan}
              </span>
              <div>
                <strong>${t('billing.current_plan', {}, 'Active Plan')}</strong>
                <div style="font-size:var(--fs-2);color:var(--muted);">Active projects: ${activeProjects} / ${maxProjects}</div>
              </div>
            </div>
            <div class="seg" id="billing-interval-toggle">
              <button type="button" class="seg-opt is-active" data-int="monthly" ${paymentDisabled}>Monthly</button>
              <button type="button" class="seg-opt" data-int="annual" ${paymentDisabled}>Annual (Save ~20%)</button>
            </div>
          </div>
          ${subscription && ['active', 'trialing', 'past_due'].includes(subscription.status) ? `
            <div style="display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3);flex-wrap:wrap;">
              <span style="font-size:var(--fs-2);color:var(--muted);">${subscription.cancel_at_period_end ? 'Cancellation scheduled for the end of the current billing period.' : 'Your subscription is active.'}</span>
              ${subscription.cancel_at_period_end ? '' : '<button type="button" id="btn-cancel-subscription" class="btn btn-danger btn-sm">Cancel at Period End</button>'}
            </div>` : ''}
        </div>

        <!-- Pricing Plans Grid -->
        <div class="pricing-grid">
          <!-- Starter -->
          <article class="price-card">
            <p class="plan-name">Starter</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(starter?.prices?.monthly?.usd)}" data-a="${formatUsd(starter?.prices?.annual?.usd)}">${formatUsd(starter?.prices?.monthly?.usd || 79)}</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary" data-m="Ideal for indie makers & single brands" data-a="${planSummary(starter, 'annual', 'Ideal for indie makers & single brands', 'About $63 / month billed annually')}">Ideal for indie makers & single brands</p>
            <ul>
              <li>${starter?.projects || 3} active projects</li>
              <li>13 standard action tickets & verification runs</li>
              <li>Full reports & customer delivery packs</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="starter" ${paymentDisabled}>
              ${currentPlan === 'starter' ? 'Current Plan' : paymentAvailable ? 'Subscribe Starter' : paymentUnavailable}
            </button>
          </article>

          <!-- Pro (Featured) -->
          <article class="price-card price-card-featured">
            <p class="plan-badge">Most popular</p>
            <p class="plan-name">Pro</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(pro?.prices?.monthly?.usd)}" data-a="${formatUsd(pro?.prices?.annual?.usd)}">${formatUsd(pro?.prices?.monthly?.usd || 199)}</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary" data-m="Continuous multi-model tracking for growth brands" data-a="${planSummary(pro, 'annual', 'Continuous multi-model tracking for growth brands', 'About $159 / month billed annually')}">Continuous multi-model tracking for growth brands</p>
            <ul>
              <li>${pro?.projects || 10} active projects</li>
              <li>Unlimited BYOK sampling</li>
              <li>Matrix scheduled tracking & regression alerts</li>
            </ul>
            <button type="button" class="btn btn-primary btn-block btn-subscribe" data-plan="pro" ${paymentDisabled}>
              ${currentPlan === 'pro' ? 'Current Plan' : paymentAvailable ? 'Subscribe Pro' : paymentUnavailable}
            </button>
          </article>

          <!-- Agency -->
          <article class="price-card">
            <p class="plan-name">Agency</p>
            <p class="price">
              <strong class="price-val" data-m="${formatUsd(agency?.prices?.monthly?.usd)}" data-a="${formatUsd(agency?.prices?.annual?.usd)}">${formatUsd(agency?.prices?.monthly?.usd || 499)}</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary" data-m="Parallel client delivery for digital agencies" data-a="${planSummary(agency, 'annual', 'Parallel client delivery for digital agencies', 'About $399 / month billed annually')}">Parallel client delivery for digital agencies</p>
            <ul>
              <li>${agency?.projects || 30} active projects</li>
              <li>White-label client delivery headers (No CiteAura)</li>
              <li>Team multi-role permissions & white-label delivery branding</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="agency" ${paymentDisabled}>
              ${currentPlan === 'agency' ? 'Current Plan' : paymentAvailable ? 'Subscribe Agency' : paymentUnavailable}
            </button>
          </article>

          <!-- Enterprise -->
          <article class="price-card">
            <p class="plan-name">Enterprise</p>
            <p class="price"><strong>Custom</strong></p>
            <p class="plan-summary">Organization-scale private deployment</p>
            <ul>
              <li>Dedicated private deploy & custom SLA</li>
              <li>Enterprise OIDC SSO & audit events</li>
              <li>Custom data retention & dedicated support</li>
            </ul>
            <button type="button" class="btn btn-secondary btn-block btn-subscribe" data-plan="enterprise">
              Contact Sales
            </button>
          </article>
        </div>
      </div>
    `;
  },

  mounted: (ctx) => {
    let currentInterval = 'monthly';

    const toggle = document.getElementById('billing-interval-toggle');
    document.getElementById('btn-cancel-subscription')?.addEventListener('click', async () => {
      const button = document.getElementById('btn-cancel-subscription');
      if (!window.confirm('Schedule cancellation at the end of the current billing period?')) return;
      button.disabled = true;
      try {
        await billing.cancel();
        toast.success('Cancellation scheduled for the end of the current billing period.');
        await ctx.reloadCurrentView?.();
      } catch (err) {
        toast.error(t(err.error, {}, err.detail || 'Cancellation failed'));
        button.disabled = false;
      }
    });
    toggle?.querySelectorAll('.seg-opt').forEach((btn) => {
      btn.addEventListener('click', () => {
        currentInterval = btn.getAttribute('data-int');
        toggle.querySelectorAll('.seg-opt').forEach((b) => b.classList.remove('is-active'));
        btn.classList.add('is-active');

        document.querySelectorAll('.price-val').forEach((pv) => {
          pv.textContent = currentInterval === 'annual' ? pv.getAttribute('data-a') : pv.getAttribute('data-m');
        });
        document.querySelectorAll('.price-period').forEach((pp) => {
          pp.textContent = currentInterval === 'annual' ? pp.getAttribute('data-a') : pp.getAttribute('data-m');
        });
        document.querySelectorAll('.plan-summary').forEach((item) => {
          item.textContent = currentInterval === 'annual' ? item.getAttribute('data-a') : item.getAttribute('data-m');
        });
      });
    });

    document.querySelectorAll('.btn-subscribe').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const plan = btn.getAttribute('data-plan');
        if (plan === 'enterprise') {
          toast.info('Please contact sales@citeaura.com for enterprise plans.');
          return;
        }

        btn.disabled = true;
        try {
          const res = await billing.subscribe({ plan, billing_interval: currentInterval });
          if (res && res.checkout_url) {
            window.location.assign(res.checkout_url);
          } else {
            toast.success(`Subscribed to ${plan.toUpperCase()}!`);
            ctx.navigate('#/billing');
          }
        } catch (err) {
          toast.error(t(err.error, {}, err.detail || 'Subscription failed'));
        } finally {
          btn.disabled = false;
        }
      });
    });
  },
};
