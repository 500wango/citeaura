# 首页重构部署检查清单

## 部署前检查 ✓

### 1. 文件完整性
- [x] `web/index.html` - 新版首页已替换
- [x] `web/index.html.old` - 旧版已备份
- [x] `web/assets/landing-refactored.js` - 新JS已创建
- [x] `web/assets/landing-refactored.css` - 关键CSS已创建
- [x] 所有图片资源保持不变 (`/site-assets/product-*.png`)

### 2. 功能验证
```bash
# 本地测试服务器
cd web
python3 -m http.server 8000
# 访问 http://localhost:8000
```

**需要测试的功能：**
- [ ] 页面正常加载，无控制台错误
- [ ] Header 导航链接工作正常（#problem, #solution, #product, #pricing）
- [ ] 所有 CTA 按钮链接正确
  - [ ] Hero "开始免费试用" → `/app?auth=register`
  - [ ] "查看示例报告" → `/sample-report`
  - [ ] 定价卡片按钮 → `/app?auth=register`, `/app?plan=pro`, `/app?plan=agency`
- [ ] FAQ 折叠展开正常
- [ ] 图片加载正常（懒加载）
- [ ] 平滑滚动效果
- [ ] Hero 指标数字动画

### 3. 响应式测试
- [ ] 桌面端 (1920px) - 完整布局
- [ ] 笔记本 (1440px) - 正常显示
- [ ] 平板 (1024px) - 网格调整为单列
- [ ] 手机 (768px) - 移动端优化
- [ ] 手机 (375px) - 小屏幕适配

### 4. 浏览器兼容性
- [ ] Chrome/Edge (最新版)
- [ ] Firefox (最新版)
- [ ] Safari (最新版)
- [ ] 移动端 Safari (iOS)
- [ ] 移动端 Chrome (Android)

### 5. 性能检查
```bash
# 使用 Lighthouse 测试
# Chrome DevTools > Lighthouse > 生成报告

目标指标：
- Performance: 90+
- Accessibility: 95+
- Best Practices: 95+
- SEO: 100
```

### 6. SEO 元素检查
- [x] `<title>` 标签存在且清晰
- [x] `<meta name="description">` 存在
- [x] Open Graph 标签完整
- [x] `<link rel="canonical">` 正确
- [x] 语义化 HTML 标签 (`<header>`, `<section>`, `<footer>`)
- [x] 图片有 `alt` 属性

## 部署步骤

### 方案 A: 直接部署（推荐）
```bash
# 1. 已完成文件替换
# web/index.html 已经是新版

# 2. 提交到 Git
git add web/index.html web/index.html.old web/assets/landing-refactored.* web/REFACTOR-NOTES.md web/DEPLOYMENT-CHECKLIST.md
git commit -m "feat: refactor landing page for better conversion

- Simplify hero section, focus on core value proposition
- Reduce page sections from 8 to 6
- Add competitor comparison matrix
- Simplify 3-step workflow
- Optimize JS from 709 to 284 lines (-60%)
- Add scroll animations and metric counters
- Improve mobile responsiveness

Breaking changes: None (backward compatible)
Rollback: mv web/index.html.old web/index.html"

# 3. 推送到远程
git push origin main

# 4. 触发 CI/CD 部署
# (根据你的部署流程)
```

### 方案 B: 灰度发布（更安全）
```bash
# 1. 创建新路由 /landing-v2
cp web/index.html web/landing-v2.html

# 2. 配置 Nginx/CDN 路由规则
# 10% 流量到新版，90% 流量到旧版

# 3. 监控 24-48 小时

# 4. 如果指标良好，逐步增加到 100%

# 5. 最终替换主页
```

### 方案 C: A/B 测试
```bash
# 1. 使用 A/B 测试工具 (Google Optimize, VWO, etc.)
# 2. 50/50 分流
# 3. 运行 2-4 周
# 4. 根据转化率决定
```

## 监控指标

### 关键业务指标
- 试用注册转化率 (目标: +15-25%)
- Hero CTA 点击率
- 页面停留时间
- 跳出率
- 滚动深度

### 技术指标
- 页面加载时间 (FCP, LCP)
- JavaScript 错误率
- API 调用成功率
- 移动端性能

### 监控工具
- Google Analytics 4
- Hotjar / FullStory (会话录制)
- Sentry (错误监控)
- Web Vitals (性能监控)

## 回滚方案

### 快速回滚
```bash
# 如果新版出现严重问题，立即回滚
mv web/index.html web/index-refactored-broken.html
mv web/index.html.old web/index.html
git add web/index.html
git commit -m "revert: rollback landing page refactor"
git push origin main
```

### 部分回滚
```bash
# 只回滚有问题的部分（例如JS）
# 编辑 web/index.html
# 将 landing-refactored.js 改回 landing.js
```

## 发布后任务

### 第一天
- [ ] 检查所有监控面板
- [ ] 查看错误日志
- [ ] 测试关键用户流程
- [ ] 响应用户反馈

### 第一周
- [ ] 对比转化率数据
- [ ] 分析用户行为热力图
- [ ] 收集用户反馈
- [ ] 微调文案或设计

### 第一个月
- [ ] 生成 A/B 测试报告
- [ ] 决定是否保留新版
- [ ] 规划下一阶段优化

## 联系人

- 开发负责人: [Your Name]
- 产品负责人: [PM Name]
- 运维负责人: [DevOps Name]

## 应急联系

如果发现严重问题：
1. 立即在 Slack #engineering 频道报告
2. 执行快速回滚方案
3. 保存错误日志和截图
4. 安排紧急修复会议

---
Created: 2026-09-05
Status: Ready for Deployment
