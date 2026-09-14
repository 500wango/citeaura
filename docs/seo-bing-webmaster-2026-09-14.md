# CiteAura Bing Webmaster 诊断 — 2026-09-14

Property: `https://citeaura.com/`（已验证）
对照窗口: 2026-09-05 → 2026-09-12
对照 Google: GSC 28 天 0 点击 / 500 展示 / 平均排名 64.3 / 已收录 15

用户确认：Cloudflare **Bot Fight 模式当前关闭**。

## 总分

| 指标 | Bing Webmaster | 含义 |
|---|---|---|
| 总点击 | 0 | 与 Google 不同：几乎没有可展示的索引页 |
| 总印象 | 0 | 不是 CTR 问题 |
| 关键字 | 无可用数据 | 没有进 SERP 的查询 |
| 反向链接 | 无可用数据 | 无 Bing 可见外链 |
| 网站地图 | Success，53 URL，上次爬网 2026-09-12 | 发现通道正常 |
| IndexNow UI | 有 Self 提交记录（当天约 48 URL） | Bing 侧收到过通知 |
| 本机 IndexNow POST | `403 UserForbiddedToAccessSite` | 本机出口验钥失败，不是「从未通知」 |
| 公开 `site:citeaura.com`（cn.bing） | **约 1 条结果** | 几乎没进 Bing 网页索引 |

## URL 检查（今天实测）

| URL | 状态 | 备注 |
|---|---|---|
| `https://citeaura.com/blog/what-to-put-in-llms-txt` | **已成功编制索引**；该 URL 可以在必应上显示 | 公开 SERP 唯一命中；「未找到 SEO/GEO 问题」 |
| `https://citeaura.com/` | 已发现但未爬网；**无法显示**；页面提取失败「我们无法连接到此 URL」；发现时间 `01 Jan 2006` | 2006 是 Bing 空值占位 |
| `https://citeaura.com/blog` | 已发现但未爬网；无法显示；文案改成「不符合网站管理员工具准则」 | 不是连接失败 |
| `https://citeaura.com/blog/gptbot-blocked-by-robots-txt` | 同上（准则/质量） | Google 上这页有展示 |
| `https://citeaura.com/blog/why-chatgpt-does-not-mention-my-brand` | 已发现但未爬网；无法显示；发现时间 **02 Sept 2026** | 已知 URL，仍不编入索引 |

站点管理器路由 `.../sitemanager` 显示「未找到任何页面」（该 UI 路径空）。网站扫描：未启动。

## 已排除（有证据）

1. **不是 robots**：`User-agent: Bingbot` / `*` 均为 `Allow: /`；`Disallow` 只有 `/api/` `/admin/` `/app` `/files/`。
2. **不是没提交 sitemap**：9/2 提交，9/12 成功读到 53 URL。
3. **不是源站对 Bingbot UA 返回错误**：本机 `bingbot` UA 首页 HTTP 200，约 42KB HTML，`index,follow`，canonical 正确，title `AI Visibility Tracking & GEO Software | CiteAura`。
4. **不是 Bot Fight 当前在拦真 Bingbot**：用户确认关闭。Cloudflare 安全分析过去 24h 采样日志里有真实 Microsoft 爬虫：
   - `207.46.13.154` `msnbot-207-46-13-154.search.msn.com` → `/blog/ai-crawler-access-checklist`、`/i18n/en.json`
   - `52.167.144.205` `msnbot-52-167-144-205.search.msn.com` → 字体/导航资源
   - `40.77.177.229` `msnbot-40-77-177-229.search.msn.com` → CSS/JS
   这些是 **Bingbot 已抓到博客与静态资源**。24h 缓解 23 / 服务 739，没有「Bing 全被拦」的证据。
5. **不是 TLS 1.3-only**：CF SSL/TLS 加密模式 **完全**；流量同时标 TLS v1.2 与 v1.3。
6. **不是「完全没被 Bing 发现」**：sitemap 53 + IndexNow UI Self 提交 + 至少 1 页已编制索引。

## 根因（按证据分层）

Bing 0 曝光 **不是** Google 那种「已收录、排在第 6 页、CTR=0」。

真正卡住的是：**网页索引几乎为空**。公开 `site:citeaura.com` 约 1 条（llms.txt 那篇博客）。首页在检查工具里甚至是「连不上」；多数已发现 URL 停在「已发现但未爬网 / 无法显示」。

两层不要混：

### A. URL 检查工具的「我们无法连接到此 URL」（首页）

这是 **Webmaster URL Inspection / Site Scan 抓取器**，不是 `msnbot-*.search.msn.com`。

Cloudflare 文档：[WAF troubleshooting — blocked Bing site scans](https://developers.cloudflare.com/waf/troubleshooting/blocked-bing-site-scans/)：Site Scan **不用 Bingbot IP 段**，`Verify Bingbot` 也不认这些 IP；WAF「假 Bingbot」托管规则会误伤。社区同类：检查工具 fetch fail，暂停 Cloudflare 后工具立刻能抓。

所以首页这条失败 **解释不了** 采样日志里真实 Bingbot 已经在拉 `/blog/ai-crawler-access-checklist`。不要把工具失败当成「Bingbot 被墙」。

### B. 真索引几乎只有 1 页（0 展示的直接原因）

Bingbot 能抓，但 **没有把站点编进网页索引**（除 `what-to-put-in-llms-txt`）。其余检查结果是「已发现但未爬网」+ 准则文案，不是 5xx。

与 Google 对照：Google 已收录 15 页、500 展示。差的是 Bing 的收录决策，不是源站对 Googlebot/Bingbot UA 的 HTML。

最吻合的组合：

1. 新域（注册 2026-08-08）+ Bing 可见反向链接 0 → 抓取预算/信任极低。
2. IndexNow **本机 API 仍 403**（2026-09-14 部署后密钥已是恰好 32 字节、无尾随 `\n`，`content-length: 32`）。`api.indexnow.org` / `www.bing.com/indexnow` 继续 `UserForbiddedToAccessSite`；Yandex 200。Webmaster UI 仍有 Self 提交。**换行不是 403 的根因。** 403 更像这台出口 IP 验钥失败，或 Bing 对提交方的站点授权失败；不要用它解释 0 展示。
3. URL 检查/Site Scan 被 CF 当假 Bingbot（层 A）→ 控制台一直红，诱导误判「连不上」，实际 msnbot 已在抓。
4. 站点管理器空、绝大多数 URL 停在 discovered-not-crawled：Bing 知道 sitemap，但没有把首页/产品页当可索引文档。

**不是**「改 title 就能出 Bing 量」。Google 500 展示是深位 CTR；Bing 是索引面接近 0。

## 不要做

- 不要因 Bing 0 展示重写全站或再批量写 GEO vs SEO
- 不要在首页仍显示「无法连接到此 URL」时狂点请求编制索引（配额 100；状态不会因此变绿）
- 不要再提交同一份 sitemap
- 不要把 Bot Fight「已关」理解成 URL 检查一定变绿（检查器 IP ≠ Bingbot）
- 不要把本机 IndexNow 403 说成「Bing 从没收到过」——UI 里已有 Self 提交

## 该做（按顺序）

1. **修 IndexNow 密钥文件**：body 必须是恰好 32 位 hex，无尾随 `\n`。部署后再跑 `scripts/submit_indexnow.py`，目标是 `api.indexnow.org` 与 `www.bing.com/indexnow` 非 403。
2. **给 URL 检查开绿灯（可选、可逆）**：按 Cloudflare 文档，对触发的「假 Bingbot」托管规则建 **临时 skip exception**，只为跑通 URL 检查 / Site Scan；扫完删掉。不要为这个长期 Skip 全部 Bot 规则。
3. **对已成功索引的那 1 页不要乱动**。对其余 P0 URL（首页、`/blog`、Google 已有展示的 3–5 篇）等检查器能提取后再点「请求编制索引」。
4. **外链仍是 Bing 和 Google 的共同瓶颈**。Bing 反向链接空；Google 也没有品牌词查询。PH 已提交，勿重复。下一步仍是 SaaSHub 认领 + Futurepedia/Crunchbase/AlternativeTo + 三封编辑信。
5. 一周后复核：`site:citeaura.com` 结果数、首页 URL 检查是否仍 FETCH_FAIL、Webmaster 印象是否仍全 0。

## 验证命令

```bash
curl -sL https://citeaura.com/robots.txt | grep -A2 'Bingbot'
curl -sL https://citeaura.com/sitemap.xml | grep -c '<loc>'
curl -s https://citeaura.com/59f477dc828647979b6a25acfbbfca7d.txt | xxd
python3 scripts/submit_indexnow.py
```

公开 SERP：Bing 搜 `site:citeaura.com`（本机 cn.bing 会强制国内版；以约 1 条为准，不要用 Google `site:` 代替）。
