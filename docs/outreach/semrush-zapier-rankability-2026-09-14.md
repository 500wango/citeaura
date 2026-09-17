# Editorial outreach drafts — 2026-09-14

Policy: brand / product / naked URL anchors only. Offer original method + limits, not a guest post package.
Do not claim CiteAura is already in their roundups.

Assets to attach (all live):

- Measurement method: https://citeaura.com/blog/measure-if-chatgpt-mentions-your-brand
- Why ChatGPT skips a brand: https://citeaura.com/blog/why-chatgpt-does-not-mention-my-brand
- GPTBot robots teardown: https://citeaura.com/blog/gptbot-blocked-by-robots-txt
- Methodology: https://citeaura.com/methodology
- Sample report: https://citeaura.com/sample-report

Send from a real person mailbox (support@citeaura.com or founder). One email per site. No follow-up blast inside 10 days.

---

## 1. Semrush

To: the editorial / updates contact on
https://www.semrush.com/blog/best-ai-visibility-tools/
Subject: Reproducible mention_rate method for your AI visibility roundup

Hi,

Your AI visibility tools roundup is one of the pages practitioners actually use when they compare mention dashboards.

We published the measurement procedure we use at CiteAura (https://citeaura.com/): freeze a prompt cohort, label each sample as API-parametric / API-web-grounded / manual product surface, detect mentions with a documented regex, then report mention_rate with a Wilson interval instead of a single snapshot.

Write-up: https://citeaura.com/blog/measure-if-chatgpt-mentions-your-brand

If you update the roundup, two things we can contribute without a ranking claim:

1. The sampling-mode table (most tools collapse these into one “visibility %”).
2. A short note on robots.txt / Cloudflare managed robots prepend silently Disallowing GPTBot — we documented the live check at https://citeaura.com/blog/gptbot-blocked-by-robots-txt

Happy to send the cohort JSON shape and the limitations paragraph you can quote. CiteAura is a new GEO product; treat this as a method citation, not a vendor slot unless you independently test it.

Best,
[Name]
CiteAura
https://citeaura.com/
support@citeaura.com

---

## 2. Zapier

To: writer listed on
https://zapier.com/blog/best-ai-visibility-tool/
Subject: A workflow-shaped way to measure ChatGPT brand mentions

Hi,

Your AI visibility tool guide is aimed at teams who want a workflow, not another enterprise dashboard.

CiteAura (https://citeaura.com/) is built as audit → tickets → verify. The public method we use to measure ChatGPT brand mentions is here:

https://citeaura.com/blog/measure-if-chatgpt-mentions-your-brand

What is actually copyable into a Zapier-style article:

- Three sampling modes that must not be averaged together
- A mention_rate formula with a confidence interval
- A “why the model skipped the brand” bucket list (crawl / JS extractability / WAF / thin facts): https://citeaura.com/blog/why-chatgpt-does-not-mention-my-brand

We are not asking to replace a listed tool. If you add a “how we scored visibility” sidebar, this is the procedure. I can also walk through the free public audit (no model key) on a domain you pick.

Best,
[Name]
CiteAura
https://citeaura.com/
support@citeaura.com

---

## 3. Rankability

To: author / updates on
https://www.rankability.com/blog/best-ai-search-visibility-tracking-tools/
Subject: Citation vs mention, plus a robots.txt failure mode your comparison can use

Hi,

Your AI search visibility tracking comparison is one of the few that already separates “mentioned” from “cited.”

We ran into a failure mode that is easy to miss in tool reviews: Cloudflare’s managed robots.txt prepends `Disallow: /` for GPTBot / ClaudeBot / Google-Extended in front of the origin file. The origin can say Allow; the live file still blocks training crawlers. Write-up with curl -A checks:

https://citeaura.com/blog/gptbot-blocked-by-robots-txt

Related measurement piece (mention_rate, cohort, three sampling modes):

https://citeaura.com/blog/measure-if-chatgpt-mentions-your-brand

CiteAura (https://citeaura.com/) is a GEO diagnostic loop with tickets and verification, not a prompt scraper. If you keep a “what the tool actually measures” column, we can give you the labeled sampling contract and the evidence boundary — no ranking guarantees.

Best,
[Name]
CiteAura
https://citeaura.com/
support@citeaura.com
