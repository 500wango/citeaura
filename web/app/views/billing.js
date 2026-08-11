/**
 *  (Billing & Plans)
 */

import { billing } from '../api.js';
import { t } from '../i18n.js';
import { toast } from '../components/toast.js';

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
    const activeProjects = usage.projects_active || 0;
    const maxProjects = usage.projects_limit || 3;
    const paymentAvailable = Boolean(plansData.payment?.enabled && plansData.payment?.configured);
    const paymentDisabled = paymentAvailable ? '' : 'disabled aria-disabled="true"';
    const paymentUnavailable = t('billing.payment_unavailable', {}, 'Payments unavailable');

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
        </div>

        <!-- Pricing Plans Grid -->
        <div class="pricing-grid">
          <!-- Starter -->
          <article class="price-card">
            <p class="plan-name">Starter</p>
            <p class="price">
              <strong class="price-val" data-m="$79" data-a="$759">$79</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary">Ideal for indie makers & single brands</p>
            <ul>
              <li>3 active projects</li>
              <li>13 standard action tickets & auto-verification</li>
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
              <strong class="price-val" data-m="$199" data-a="$1,910">$199</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary">Continuous multi-model tracking for growth brands</p>
            <ul>
              <li>10 active projects</li>
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
              <strong class="price-val" data-m="$499" data-a="$4,790">$499</strong>
              <span class="price-period" data-m="/ month" data-a="/ year">/ month</span>
            </p>
            <p class="plan-summary">Parallel client delivery for digital agencies</p>
            <ul>
              <li>30 active projects</li>
              <li>White-label client delivery headers (No CiteAura)</li>
              <li>Team multi-role permissions & priority execution queue</li>
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
