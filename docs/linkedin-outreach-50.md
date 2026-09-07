# CiteAura LinkedIn 50 潜在客户 + 私信方案

更新时间：2026-09-04
目标：为 CiteAura (citeaura.com) 筛选 50 个 LinkedIn 精准画像，产出可直接发送的连接邀请与私信（中英双语），并沉淀为可复用 outreach 资产
底座：PRD v2.0 四类画像（GEO代理/咨询、品牌增长/SEO、内容运营、管理）× 产品承诺（填域名 3分钟出报告 + 6维体检 + 工单闭环 + 白标交付包）
方法：site:linkedin.com/in 公开索引检索，过滤 /in/ 个人主页，63 条去重后精选 50，剔除公司页/职位页/建议页，仅保留真实个人主页

---

## 文件索引

- 全量 50 人 CSV（含优先级/契合原因/破冰点）：`/tmp/citeaura_leads/citeaura_linkedin_50_leads.csv`
- 全量个性化 CSV（含连接邀请≤300ch + 首条私信 + 跟进，中英双语）：`/tmp/citeaura_leads/linkedin/citeaura_linkedin_50_personalized.csv`
- 连接邀请合集 EN/ZH：`/tmp/citeaura_leads/linkedin/all_connection_notes_EN.txt`、`/tmp/citeaura_leads/linkedin/all_connection_notes_ZH.txt`
- 邮件版邀请（代理/SaaS/DTC/中文 + 3天跟进）：`/tmp/citeaura_leads/emails/`
- 本文 Top15 超个性化（含域名+公司规模+官网状态）CSV：`/tmp/citeaura_leads/linkedin/citeaura_top15_hyper_personalized.csv`（已剔除 lovable 外包等21个不合适画像，见 audit）
- 复审报告：`docs/linkedin-outreach-50-audit.md`（29合适/21剔除，逐条verdict）
- 搜索证据（63条原始命中）：`/tmp/citeaura_leads/combined.json`

> 隐私说明：全部为 LinkedIn 公开索引的个人主页 URL，未爬取私密数据；LinkedIn 完整经历需登录后查看，此处仅用公开标题/简介校画像，不编造履历。

---

## 画像分布

| 画像 | 人数 | 典型头衔 | 为何是 CiteAura 的付费画像 |
|---|---|---|----------------|
| A GEO/SEO代理 | 21 | Founder / SEO Director / AI Marketing Agency | 最快成交：把现有 SEO 年单升级为 GEO 年单，需要白标报告 + 工单交付 |
| B SaaS 增长/市场负责人 | 15 | CMO / Head of Growth / Head of Marketing | 自用：跟踪 Perplexity/ChatGPT 提及率与引用率，证明品类心智 |
| C 出海/DTC品牌 | 12 | Founder / Co-Founder / Ecommerce Lead | 核心 PMF：出海品牌在 AI 答案里从零开始，需要零门槛基线 |
| D 内容/SEO执行层 | 2 | SEO Director / Marketing Manager | 执行：直接用可引用块/schema/llms.txt 工单 |

---

## 全量 50 人清单

| 编号 | 姓名 | 职位 | 公司 | LinkedIn | 画像 | 优先级 | 契合原因 |
|---|---|---|---|---|---|---|---|
| 1 | Kai Cromwell | Founder | eCommerce SEO Agency New Seas | https://www.linkedin.com/in/kai-cromwell | A | ★★★★★ | 专注电商SEO的Agency创始人，正从传统SEO转向GEO |
| 2 | Guy Njoukam | Founder | AIFun Lovable Agency (AEO/GEO) | https://www.linkedin.com/in/guy-njoukam-43a347193 | A | ★★★★★ | 简介直接写AEO and GEO，完美ICP |
| 3 | James Banks | Founder | Rankmax AI SEO Agency (AU) | https://au.linkedin.com/in/jamesbanksco | A | ★★★★★ | AI SEO Agency定位，澳洲市场 |
| 4 | Navneet Kaushal | Founder & CEO | PageTraffic Inc | https://in.linkedin.com/in/navneetkaushal | A | ★★★★★ | 20年老牌SEO代理创始人，客户多为出海企业 |
| 5 | Rebekah Edwards | Founder | SEO Agency + The Based Creator | https://www.linkedin.com/in/rebekahcreates | A | ★★★★☆ | 内容型SEO代理创始人 |
| 6 | Andy Chadwick | Founder | SaaS & SEO Agency (UK) | https://uk.linkedin.com/in/andy-chadwick | A | ★★★★☆ | 横跨SaaS与SEO代理 |
| 7 | Andy Ng | Director | YOYI TECH (SG) | https://sg.linkedin.com/in/andynggp | C | ★★★★☆ | 新加坡AdTech，服务大量出海品牌 |
| 8 | Arnob Sarker | AEO Expert | Freelance AEO | https://bd.linkedin.com/in/arnob-sarker-aeo-expert | A | ★★★★★ | 标题直接写AEO Expert |
| 9 | Md Mynul Hassan | AEO/GEO Specialist | AM Webzone | https://bd.linkedin.com/in/aeo-geo-seo-specialist | A | ★★★★☆ | 专注AEO/GEO细分 |
| 10 | Pete Blackshaw | Co-Founder & CEO | BrandRank.AI | https://www.linkedin.com/in/consumergeneratedmedia | B | ★★★☆☆ | GEO竞品创始人，可作生态合作 |
| 11 | Zhong Li | Co-Founder | Cross-border Ecommerce Project | https://www.linkedin.com/in/zhong-li-555656191 | C | ★★★★★ | 华人跨境电商联合创始人，核心TA |
| 12 | Tam Le | Head of Growth | Ecommerce/Logistics/SaaS (VN) | https://vn.linkedin.com/in/tamle068 | B | ★★★★★ | 越南背景管电商+物流+SaaS增长 |
| 13 | Dylan Hey | Founder | Hey Digital (SaaS Performance) | https://ee.linkedin.com/in/dylanhey | A | ★★★★★ | 只做SaaS的营销代理 |
| 14 | Johnathan Wang | Founder | The SaaS Consultants / Fractional CMO | https://www.linkedin.com/in/johnathan-wang | B | ★★★★☆ | 服务多个SaaS的Fractional CMO |
| 15 | Samantha Ngo | Head of Marketing | Strety | https://www.linkedin.com/in/hello-samantha-ngo | B | ★★★★☆ | B2B SaaS Head of Marketing |
| 16 | Bastien Dubuc | Head of Growth | resistant.ai | https://cz.linkedin.com/in/bastien-dubuc | B | ★★★★☆ | AI风控SaaS的增长负责人 |
| 17 | Devanshu L | Head of Growth | Enrich.so / InboxKit | https://www.linkedin.com/in/devanshulakhaney | B | ★★★★☆ | 多款SaaS增长负责人 |
| 18 | Sandeep Nagpal | CMO | SaaS & B2B Growth (IN) | https://in.linkedin.com/in/nagpalsandeep | B | ★★★★☆ | 印度SaaS CMO，预算敏感 |
| 19 | Archana Chopda | B2B SaaS CMO | Independent | https://in.linkedin.com/in/archanachopda | B | ★★★★☆ | 专注B2B SaaS营销体系 |
| 20 | Liviu I | Fractional CMO | Founder-led SaaS | https://www.linkedin.com/in/multiplycmo | B | ★★★★☆ | 专做创始人驱动SaaS |
| 21 | Atsushi Ikeda | Executive Leader | B2B SaaS (JP) | https://jp.linkedin.com/in/atsushi-ikeda | B | ★★★☆☆ | 日本B2B SaaS高管 |
| 22 | Tanny Nguyen | B2B SaaS Marketing Ops | Independent (CA) | https://ca.linkedin.com/in/tanny-nguyen | B | ★★★☆☆ | B2B SaaS营销运营 |
| 23 | Shining Tang | Marketing Manager | B2B SaaS | https://www.linkedin.com/in/shining-tang-61b6ba44 | D | ★★★☆☆ | B2B SaaS市场经理 |
| 24 | Thomas Fondrat | SEO Director | Resolution Media / OMD (NZ) | https://nz.linkedin.com/in/thomas-fondrat-seo | D | ★★★★☆ | 大型代理SEO总监 |
| 25 | Mark Ackermann | SEO Director | Searchable (PT) | https://pt.linkedin.com/in/mark-ackermann | D | ★★★☆☆ | SEO代理总监 |
| 26 | Frew Murdoch | Founder | Chewberri Limited (UK) | https://uk.linkedin.com/in/frew-murdoch | A | ★★★☆☆ | 小代理创始人，决策快 |
| 27 | Husnain Arbi | Founder | Aicoads (AI Marketing) | https://www.linkedin.com/in/husnainarbi | A | ★★★★☆ | AI营销代理 |
| 28 | Hussain Zahid Butt | Founder | AI Marketing Agency | https://www.linkedin.com/in/hussain-zahid-butt-2974b4258 | A | ★★★☆☆ | AI代理 |
| 29 | Simon Gould | Founder | Sydney Digital Marketing Agency | https://au.linkedin.com/in/speaktosimon | A | ★★★☆☆ | 澳洲数字营销代理 |
| 30 | Annie G | Founder | 8th Wave Marketing | https://www.linkedin.com/in/anngoth | A | ★★★☆☆ | 美国精品营销代理 |
| 31 | Tee Gallagher | Marketing Leader | Integrated Marketing | https://www.linkedin.com/in/teegallagher | B | ★★★☆☆ | 整合营销负责人 |
| 32 | Angela Diniak | Marketing Manager | Oyova | https://www.linkedin.com/in/angeladiniak | D | ★★★☆☆ | 数字代理营销经理 |
| 33 | Uzair Siddiqui | SEO Specialist | KernelTech (PK) | https://pk.linkedin.com/in/uzair-siddiqui-seo | A | ★★★☆☆ | 技术SEO |
| 34 | Zuhdi F | Digital Sales & Ecom | DTC Brand (ID) | https://id.linkedin.com/in/zuhdifathani | C | ★★★★☆ | 印尼DTC电商负责人 |
| 35 | Jaclyn Grauman | Marketing Lead | Bobbie (DTC 母婴) | https://www.linkedin.com/in/jaclyn-grauman | C | ★★★★☆ | 美国知名DTC品牌 Bobbie |
| 36 | Allan Muteti | Founder | Homestead Studio (DTC) | https://www.linkedin.com/in/allan-muteti | C | ★★★☆☆ | DTC工作室创始人 |
| 37 | Justin Perez | Founder / Head of Ecommerce | Retail & DTC | https://www.linkedin.com/in/jjustinperez | C | ★★★★☆ | 电商与零售DTC创始人 |
| 38 | Neeraj Bansal | Founder & CEO | BeSpoke AI Stylist | https://www.linkedin.com/in/neerajbansalcpa | C | ★★★☆☆ | AI+时尚DTC创始人 |
| 39 | Sandeep Kumar | Founder | ROI Minds (Performance) | https://in.linkedin.com/in/sandyroiminds | A | ★★★☆☆ | 效果类代理 |
| 40 | Alastair Steele | Director | Edelman (UK) | https://uk.linkedin.com/in/alastairsteele | B | ★★☆☆☆ | 公关集团品牌管理 |
| 41 | Anthony Lee | Founder | NextMarket LLC (Cross-border) | https://www.linkedin.com/in/borderless | C | ★★★★☆ | 美国跨境营销创始人 |
| 42 | Efua Ihenyen | Cross Border Lead | Independent | https://www.linkedin.com/in/efuaihenyen | C | ★★★☆☆ | 跨境电商负责人 |
| 43 | William Everson | Co-Founder | Aims AMS LLC | https://www.linkedin.com/in/william-bill-everson-915a0512 | C | ★★★☆☆ | 跨境物流/电商联合创始人 |
| 44 | Bradley Pudney | Founder | Shopiotic (SEO Content) | https://www.linkedin.com/in/bradley-pudney-seocontentcreator | A | ★★★☆☆ | SEO内容创作者 |
| 45 | Ravi Fuleriya | Founder | InnovatorCraft | https://in.linkedin.com/in/ravifuleriya | A | ★★★☆☆ | 印度内容/SEO服务 |
| 46 | Andres Rusic | Founder | Marketingandai | https://www.linkedin.com/in/andres-rusic-marketingaide | A | ★★★☆☆ | AI营销工具创始人 |
| 47 | Anna Torbina | Growth Product Leader | Independent (CY) | https://cy.linkedin.com/in/anna-torbina | B | ★★★☆☆ | 9年增长产品负责人 |
| 48 | Emily Deacon | Founder & Growth Partner | Earthos (ID) | https://id.linkedin.com/in/emily-deacon-earthos | A | ★★★☆☆ | 增长合伙人 |
| 49 | Masayoshi Aritomo | CEO | JUST A inc. (JP) | https://jp.linkedin.com/in/masayoshi-aritomo-56a3a9227 | C | ★★★☆☆ | 日本CEO，日本品牌出海 |
| 50 | Lin Miao | Founder | Opan Talk (Live Selling) | https://www.linkedin.com/in/ilinmiao | C | ★★★☆☆ | 直播带货代理创始人 |

---

## 全量个性化私信（50人，已按画像分话术）

> 完整版在 `/tmp/citeaura_leads/linkedin/citeaura_linkedin_50_personalized.csv`
> 连接邀请全部 ≤300字符，首条私信 600-800字符，跟进 1句

话术分层：
- A 代理：GEO转售 + 白标交付包 + BYOK约2元/项目
- B SaaS：Perplexity/ChatGPT 提及率与引用率 + 竞品差距
- C DTC/出海：不在AI答案里就不在购物车里 + 填域名3分钟零门槛

---

## Top 15 超个性化先发名单（已剔除 lovable 外包等21个不合适画像，带域名+公司规模+官网状态富化）

> 选型：复审后 29个合适中的 15个强匹配（8代理+4 SaaS增长+3出海/DTC），适合本周分3天发完（每天5封），剔除 Guy/lovable 外包、Pete竞品、BD freelancer、员工岗等
> 复审见 `docs/linkedin-outreach-50-audit.md`，富化 CSV：`/tmp/citeaura_leads/linkedin/citeaura_top15_hyper_personalized.csv`
> 超个性化定义：连接邀请里带域名与竞品/品类词，首条私信里给“已预研的3个具体工单假设”，对方回复即可直接开跑

| 优先级 | 姓名 | 公司 | 域名 | 规模 | 官网 | 超个性化连接邀请 EN (≤300ch) | 超个性化连接邀请 中文 | 超个性化首条私信 EN | 超个性化首条私信 中文 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | James Banks | Rankmax AI SEO Agency | rankmax.com.au | 11-50人 AU | ✓ 活 | Hi James, loved Rankmax's $20M+ client revenue story on rankmax.com.au. Built CiteAura for AI SEO agencies - domain-only -> 3min visibility across 10+ engines (labeled sampling) + tickets->auto-verify. Would love to connect and compare GEO delivery notes. | James你好，很喜欢Rankmax在rankmax.com.au上$20M+客户收入的案例。做了CiteAura专为AI SEO代理：填域名3分钟出多引擎可见性+工单闭环，想连接交流。 | Hi James, thanks for connecting! Saw Rankmax positions as "AI SEO Team Behind $20M+" - perfect fit for GEO. I pre-checked rankmax.com.au: great extractability but llms.txt is likely missing and homepage lacks a citable "what is Rankmax" block (common). CiteAura would generate 3 tickets: llms.txt + JSON-LD Organization + answerability snippet for "best AI SEO agency Australia". BYOK ~$0.30/run. Want me to run rankmax.com.au free and send the delivery pack? Happy to white-label it for your clients. citeaura.com/app | James你好，感谢通过！Rankmax定位AI SEO很准。我预检rankmax.com.au：可抽取性不错但可能缺llms.txt且首页缺少可引用定义块。CiteAura会出3条工单：llms.txt+组织化JSON-LD+可引用答案块。BYOK约2元/次。发我一个客户域名我免费跑份白标包给你看？ |
| 2 | Rebekah Edwards | Clara Agency | clara.agency* | 11-50人 US | * 待复核 clara.agency | Hi Rebekah, love your work at Clara (clara.agency) blending SEO with brand storytelling. Built CiteAura for content-led SEO agencies - paste domain -> 3min AI visibility + white-label pack. Would love to connect and swap GEO notes. | Rebekah你好，很喜欢你在Clara (clara.agency) 把SEO与品牌叙事结合。做了CiteAura给内容型代理：填域名3分钟出AI可见性+白标包，想连接交流。 | Hi Rebekah, thanks for connecting! Saw Clara's organic SEO focus in Nashville - GEO is the next layer. For any client domain, CiteAura outputs per-engine mention/citation + 6-dim audit + fact-conflict detection (stops AI hallucinating the brand). Want me to run a client domain free? Reply a domain and I'll send the white-label zip. Or try clara.agency as demo. citeaura.com/app | Rebekah你好，感谢通过！看到Clara做有机SEO - 下一步是GEO。对任意客户域名，CiteAura出分引擎提及/引用+6维体检+事实冲突检测。发我一个域名我免费跑份白标包给你？ |
| 3 | Andy Chadwick | Snippet Digital | snippet.digital | 11-50人 UK | ✓ 活 snippet.digital | Hi Andy, saw you run Snippet Digital + your AI playbook at andy-chadwick.com - exactly the SaaS+SEO hybrid I built CiteAura for. Domain-only -> 3min AI visibility across 10 engines. Would love to connect. | Andy你好，看到你在Snippet Digital和andy-chadwick.com做SaaS+SEO混合，正是我做CiteAura面向的客群。填域名3分钟出报告，想连接。 | Hi Andy, thanks for connecting! Saw Snippet Digital's SEO expertise + your AI focus - GEO fits both. For snippet.digital or any SaaS client, CiteAura gives 30 questions x 10 engines, aggregates mention/citation, audits llms.txt/robots/schema, then maps gaps to tickets with 16+ auto-checkers. BYOK ~$0.30/run. Want me to run snippet.digital free as demo? Reply "run: snippet.digital" and I'll send the zip. | Andy你好，感谢通过！看到Snippet Digital的SEO+AI，很适合GEO。对snippet.digital或任意SaaS客户，CiteAura自动审并转工单验收。发我域名我免费跑份demo？ |
| 4 | Dylan Hey | Hey Digital | heydigital.com* | 11-50人 EE | * 待复核 | Hi Dylan, Hey Digital's SaaS-only focus is sharp. I built CiteAura to help SaaS agencies add GEO as a retainer - paste SaaS domain -> 3min visibility + playbook. Would love to connect and show how Hey Digital could sell GEO packs. | Dylan你好，Hey Digital只做SaaS很犀利。做了CiteAura帮SaaS代理新增GEO年单：填域名3分钟出报告+Playbook，想连接给你看如何打包。 | Hi Dylan, thanks for connecting! Saw Hey Digital only serves SaaS - GEO is a natural upsell. For any SaaS client domain, CiteAura outputs: (1) per-engine mention/citation (2) 6-dim audit (3) 4-type tickets with acceptance criteria. BYOK so you keep margin. Want me to run a demo on heydigital.com or a client domain free? Reply domain and I'll send white-label zip. | Dylan你好，感谢通过！Hey Digital只做SaaS很适合卖GEO。对任意SaaS客户域名，CiteAura出分引擎提及/引用+6维体检+4类工单。发我一个域名我免费跑份白标包给你？ |
| 5 | Husnain Arbi | Aicoads (Austin) | aicoads.com | 11-50人 US | ✓ 活 aicoads.com | Hi Husnain, saw Aicoads in Austin (aicoads.com) selling AI marketing - smart. Built CiteAura for AI agencies like yours - domain -> 3min AI visibility + white-label pack. Would love to connect. | Husnain你好，看到Aicoads在Austin (aicoads.com) 做AI营销，很领先。做了CiteAura给AI代理：填域名3分钟出报告+白标包，想连接。 | Hi Husnain, thanks for connecting! Saw Aicoads' AI marketing focus in Austin - GEO is the natural next service. CiteAura: 30 questions x 10 engines, audits llms.txt/extractability, maps to tickets (fact/content/tech/off-site) with auto-verify. BYOK ~$0.30/project. Want me to run aicoads.com free as demo? Reply "run: aicoads.com" and I'll send the zip. citeaura.com/app | Husnain你好，感谢通过！Aicoads做AI营销，GEO是自然加售。CiteAura 30题×10引擎+自动验收。发我aicoads.com我免费跑份demo？ |
| 6 | Thomas Fondrat | Resolution/OMD NZ | omd.com* | 1000+人 全球 | * 大代理 需确认业务单元 | Hi Thomas, saw you lead SEO at Resolution/OMD NZ - large agency SEO directors are exactly who need GEO at scale. Built CiteAura to turn audits into tickets at scale. Would love to connect. | Thomas你好，看到你在Resolution/OMD NZ负责SEO，大代理的SEO负责人正需要规模化GEO。做了CiteAura把审计规模化转工单，想连接。 | Hi Thomas, thanks for connecting! For large agencies, manual Perplexity checks don't scale. CiteAura automates: sample 10+ engines per client, audit crawlability/extractability/citation evidence, generate prioritized tickets with 16+ checkers and auto-verify. BYOK keeps cost low per client. Want me to run a pilot on one client domain free and send the white-label pack? No deck needed. citeaura.com/app | Thomas你好，感谢通过！大代理手动测Perplexity无法规模化。CiteAura自动化采样+审计+工单验收，BYOK成本低。发我一个客户域名我免费跑份白标包做试点？ |
| 7 | Kai Cromwell | New Seas (Shopify SEO) | newseas.co* | 2-10人 | * 推断 待复核 | Hi Kai, big fan of New Seas' Shopify SEO for 7-8 figure brands. I built CiteAura for ecommerce SEO agencies - paste Shopify domain -> 3min AI visibility (is the brand cited in "best [category]" answers?). Would love to connect - happy to run a free audit for one of your Shopify clients. | Kai你好，很欣赏New Seas为7-8位数Shopify品牌做电商SEO。做了CiteAura专为电商代理：贴Shopify域名3分钟看在"best [品类]"AI答案里是否被引用，想连接并免费为你一个客户跑份报告。 | Hi Kai, thanks for connecting! Saw New Seas focuses on Shopify SEO - next frontier is GEO. I can run any of your client Shopify domains free: CiteAura checks "can AI read the PDP?" (extractability), llms.txt, and Perplexity citation vs competitors, then gives 3 tickets (e.g., PDP answerability block + product JSON-LD + llms.txt). Want me to run one? Just reply a Shopify domain. Or try citeaura.com/app - 7-day free, BYOK. | Kai你好，感谢通过！看到New Seas专注Shopify - 下一步是GEO。对你任意Shopify客户域名我可免费跑：查PDP可抽取性、llms.txt、Perplexity引用率，给3条工单。发我一个域名就行，或直接试 citeaura.com/app。 |
| 8 | Andy Ng | YOYI TECH SG | yoyi.tech | 51-200人 SG | ✓ 活 yoyi.tech | Hi Andy, saw YOYI TECH (yoyi.tech) pioneering AI for cross-border - exactly the brands that need GEO. Built CiteAura for cross-border - paste domain -> 3min AI visibility. Would love to connect. | Andy你好，看到YOYI TECH (yoyi.tech) 用AI推动出海，正是需要GEO的品牌。做了CiteAura为出海品牌：填域名3分钟出报告，想连接。 | Hi Andy, thanks for connecting! Saw YOYI's AI + cross-border partnership with Punch Digital - GEO is the next gap: are your clients cited in Perplexity/ChatGPT when buyers ask "best [category]"? CiteAura audits yoyi.tech or any client domain in 3min: robots/llms.txt/schema + per-engine citation. Want me to run yoyi.tech free as demo? Reply domain and I'll send the pack. citeaura.com/app | Andy你好，感谢通过！看到YOYI的AI+出海，GEO是下一缺口：客户在Perplexity搜品类时是否被引用？CiteAura 3分钟审yoyi.tech或任意客户。发我域名我免费跑份？ |
| 9 | Justin Perez | Retail & DTC Founder | 待补充 Shopify店 | 2-10人 US | 待补充具体店域 | Hi Justin, saw you lead ecommerce at Retail & DTC - impressive. Built CiteAura for DTC founders - paste Shopify domain -> 3min AI visibility vs competitors. Would love to connect and run your store free. | Justin你好，看到你在Retail & DTC负责电商，很厉害。做了CiteAura为DTC创始人：贴Shopify域名3分钟看与竞品差距，想连接并免费为你店铺跑一次。 | Hi Justin, thanks for connecting! Quick Q: when shoppers ask ChatGPT "best [your category]" is your brand the cited answer? CiteAura for DTC: checks PDP extractability, llms.txt, product schema, and Perplexity citation share vs competitors, then gives 3 executable tickets. Want me to run your Shopify domain free? Reply domain and I'll send the delivery pack. No call needed. citeaura.com/app | Justin你好，感谢通过！好奇在ChatGPT搜品类时你品牌是否被引用？CiteAura查PDP可抽取性+llms.txt+商品结构化，给3条可执行工单。发我店铺域名我免费跑份交付包？ |
| 10 | Allan Muteti | Homestead Studio | homesteadstudio.co | 11-50人 | ✓ 活 homesteadstudio.co | Hi Allan, love Homestead Studio (homesteadstudio.co) - DTC acquisition & retention is exactly where GEO adds value. Built CiteAura - domain -> 3min AI visibility. Would love to connect. | Allan你好，很喜欢Homestead Studio (homesteadstudio.co) 的DTC获客与留存，正是GEO能增值的点。做了CiteAura填域名3分钟出报告，想连接。 | Hi Allan, thanks for connecting! Saw Homestead Studio's DTC acquisition focus - next is AI acquisition: are your clients cited when buyers ask AI? CiteAura: sample 10+ engines, audit extractability/llms.txt, generate tickets (answerability block + collection JSON-LD + fact library). BYOK ~$0.30/run. Want me to run homesteadstudio.co or a client Shopify domain free? Reply domain and I'll send white-label zip. | Allan你好，感谢通过！看到Homestead做DTC获客 - 下一步是AI获客。对homesteadstudio.co或任意客户Shopify，CiteAura采样+审计+工单。发我域名我免费跑份白标包？ |
| 11 | Anthony Lee | NextMarket LLC | nextmarket 待复核 | 11-50人 US | * 待复核 | Hi Anthony, saw you run NextMarket (borderless) for cross-border brands. I built CiteAura for that exact ICP - paste domain -> 3min AI visibility + tickets your clients can execute. Would love to connect and run a free demo for one client. | Anthony你好，看到你做NextMarket服务出海品牌，正是我做CiteAura的客群。填域名3分钟出报告+可执行工单，想连接并免费为你一个客户演示。 | Hi Anthony, thanks for connecting! Saw NextMarket helps brands go borderless - AI visibility is the next border to cross. CiteAura can be your GEO backend: white-label packs, BYOK keeps margin, 16+ auto-verify checkers. Want me to run a free audit for one of your client domains? Just reply a domain. Or try citeaura.com/app 7-day free. | Anthony你好，感谢通过！NextMarket帮品牌出海，AI可见性是下一道边境。CiteAura可做你GEO后端：白标包+BYOK保利润+自动验收。发我一个客户域名我免费跑份？ |
| 12 | Bastien Dubuc | resistant.ai | resistant.ai | 51-200人 CZ | ✓ 活 resistant.ai | Hi Bastien, saw you lead growth at resistant.ai - as an AI company you know AI visibility is the new SEO. Built CiteAura - domain-only 3min report: mention/citation across 10+ engines + raw answers. Would love to connect and run resistant.ai free. | Bastien你好，看到你在resistant.ai负责增长。作为AI公司你更懂AI可见性。做了CiteAura填域名3分钟出10+引擎报告，想连接并免费为resistant.ai跑一次。 | Hi Bastien, thanks! Quick idea: have you checked resistant.ai vs competitors when prospects ask Perplexity "best fraud detection AI"? CiteAura gives mention rate, citation share, and whether Perplexity actually cites resistant.ai or just mentions it. Pre-check: resistant.ai likely needs llms.txt + "what is resistant.ai" answerability block. Want me to run resistant.ai free and send the gap + 3 tickets? No call needed. citeaura.com/app | Bastien你好，感谢通过！好奇在Perplexity搜"best fraud detection AI"时 resistant.ai  vs 竞品谁被引用？我预检resistant.ai可能缺llms.txt和可引用定义块。发我域名我免费跑份差距+工单包给你？ |
| 13 | Johnathan Wang | The SaaS Consultants | jonwang.com* | 个人 Fractional | * 待复核 jonwang.com | Hi Johnathan, saw you run The SaaS Consultants - fractional CMO for multiple SaaS is exactly where CiteAura scales (one account, many projects). Would love to connect. | Johnathan你好，看到你做The SaaS Consultants，给多家SaaS做Fractional CMO，正是CiteAura能规模化的场景，想连接。 | Hi Johnathan, thanks for connecting! As a fractional CMO you can bring 5-10 SaaS domains at once - CiteAura's Agency plan ($499/30 projects) fits. For each domain: per-engine mention/citation + 6-dim audit + 4-type tickets with acceptance criteria. BYOK keeps margin. Want me to run one of your client domains free as demo? Reply domain and I'll send the white-label zip. Or try jonwang.com as test. citeaura.com/app | Johnathan你好，感谢通过！作为Fractional CMO你可一次带多域名，CiteAura Agency套餐$499/30项目很适配。每域出提及/引用+体检+工单。发我一个客户域名我免费跑份白标包？ |
| 14 | Tam Le | Head of Growth VN | 个人品牌 | 个人 | 无域 用LinkedIn | Hi Tam, saw you lead growth across ecommerce/logistics/SaaS in VN - rare cross-vertical view. Built CiteAura for growth leaders who need AI visibility as a new acquisition channel. Would love to connect. | Tam你好，看到你在越南跨电商/物流/SaaS做增长，视角很稀缺。做了CiteAura给增长负责人把AI可见性当新获客渠道，想连接。 | Hi Tam, thanks for connecting! For growth, AI answers are the new SERP. CiteAura tells you: are you mentioned, cited, and with what framing across 10+ engines? For any brand you grow, I can run a free 3min baseline + competitor gap. Want me to run one? Reply a domain and I'll send the pack. No call needed. citeaura.com/app | Tam你好，感谢通过！对增长来说AI答案就是新SERP。CiteAura看你是否被提及/引用及措辞。对你带的任意品牌我可免费3分钟跑基线+竞品差距。发我域名就行？ |
| 15 | Sandeep Nagpal | SaaS CMO IN | 个人品牌 | 个人 | 无域 用LinkedIn | Hi Sandeep, saw you lead SaaS & B2B growth in India - multi-brand CMO is exactly who needs GEO at scale. Built CiteAura - domain -> 3min visibility per brand. Would love to connect. | Sandeep你好，看到你在印度负责SaaS与B2B增长，多品牌CMO正需要规模化GEO。做了CiteAura填域名3分钟看每品牌可见性，想连接。 | Hi Sandeep, thanks for connecting! As a multi-brand CMO, you can benchmark all brands at once - CiteAura's BYOK keeps cost at ~$0.30/project. For each domain: mention/citation + 6-dim audit + tickets with auto-verify. Want me to run one of your brands free? Reply a domain and I'll send the delivery pack. Or try citeaura.com/app 7-day free (3 projects). | Sandeep你好，感谢通过！作为多品牌CMO可一次对标多品牌，CiteAura BYOK约2元/项目。对每域出提及/引用+体检+工单。发我一个品牌域名我免费跑份？ |

> 剔除说明：原Top10中 Guy/lovable外包、Zhong Li无域、Samantha单品牌小SaaS、Navneet巨头难触达、Jaclyn员工岗已移至观察名单，详见 audit。域名带 * 为推断待复核，发送前二次确认。

---

## 连接邀请 vs 私信 节奏（防风控）

- 连接邀请：全量 50 个 ≤300字符，已校验 0 条超限；带人名+公司+画像关键词，不带链接
- 首条私信：仅在对方通过后发送，600-800字符，含单一 CTA（回复域名或访问 citeaura.com/app），不带附件
- 跟进：3天未回用 `跟进_*` 列，1句顶贴，不重复首条
- 发送节奏：每天 ≤15 封连接，分 4 天发完；代理类优先（1-10），SaaS 次之，出海/DTC 最后补

---

## 执行清单

- [ ] 复核 Top10 域名（* 标注的 4 个）并在 CSV 中替换为准确域名
- [ ] 将 Top10 超个性化连接邀请粘贴至 LinkedIn（或 Expandi/HeyReach），记录通过率
- [ ] 通过后 2小时内发超个性化首条私信，记录回复率
- [ ] 对回复域名的客户，用 CiteAura 跑 `init -> crawl -> bootstrap -> sample -> deliver` 并回传 zip
- [ ] 每周复盘：连接通过率 / 私信回复率 / 免费跑报告转化率 / 试用注册率

