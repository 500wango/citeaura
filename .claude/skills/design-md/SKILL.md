---
name: design-md
description: Use when building or restyling any UI, landing page, dashboard, or component. Turns a DESIGN.md design system file into production UI.
---

# DESIGN.md Skill — 让 Claude Code 按设计系统写 UI

## 何时触发
用户说"做个页面/改个样式/按 Stripe 风格/用 DESIGN.md"时自动触发。

## 工作流

### 1. 选择风格
没有 DESIGN.md 时先选一个：
```bash
npx getdesign list                    # 看 80+ 风格
npx getdesign add <brand>             # 如 stripe / linear / vercel / supabase / apple
# 第一次 → ./DESIGN.md ，第二次 → ./<brand>/DESIGN.md
npx getdesign add stripe --out ./DESIGN.md --force  # 指定路径
```
常用：
- SaaS/dashboard: `linear.app` `supabase` `vercel` `notion`
- 营销/落地页: `stripe` `apple` `airbnb` `shopify`
- AI/技术: `claude` `openai` `cursor` `voltagent`

### 2. 读写 DESIGN.md
DESIGN.md 是 YAML + Markdown，含 `colors` / `typography` / `spacing` / `rounded` / `shadows` / `components`，是唯一信源。
- 读：解析 colors/typography 作为 CSS 变量
- 写 UI 时：所有颜色、字阶、圆角、间距必须来自 DESIGN.md，禁止自创

### 3. 生成 UI
1. 生成 `colors_and_type.css`（或注入到现有 `tokens.css`）
2. 生成组件（button/card/nav/input）— 按 DESIGN.md 的 `components` 样式
3. 组装页面 `index.html` + 预览卡片
4. 保持 token 命名一致（`--color-primary` `--text-display-xl` 等）

### 4. 校验
- 搜索 DESIGN.md 外的硬编码色值（#xxx / rgb）→ 替换为变量
- 检查字体是否按 DESIGN.md 的 fontFamily 回退链

## 提示词模板

- "按 DESIGN.md 把 /web/index.html 重做一遍"
- "用 linear 风格做一个定价页，保持 DESIGN.md 变量"
- "在这个 DESIGN.md 基础上加 dark mode 变体"

## 来源
- 仓库: https://github.com/rohitg00/awesome-claude-design (VoltAgent 维护，80+ DESIGN.md)
- 官方: https://getdesign.md
- CLI: `npx getdesign@latest add <brand>`
