# Bento Grids 对 CiteAura 的风格参考

日期：2026-09-05

BentoGrids 是案例集合，不是单一设计系统。首页 `__NEXT_DATA__` 当前包含约 285 个案例。以下判断基于案例页及其标注的原始产品链接。

## 推荐顺序

1. **Wope**（https://wope.com/content-assistant）：深色数据面板、指标卡和异常提示，适合 AI 可见性、引用率和缺口展示。
2. **Better Stack**（https://betterstack.com/enterprise）：健康状态、事件流和时间序列，适合采样运行状态与体检结果。
3. **Linear Asks**（https://linear.app/features/asks）：紧凑任务列表、优先级和活动轨迹，适合工单、验收和回归重开。
4. **Dovetail**（https://dovetail.com/）：浅色研究证据卡片，适合原始 AI 回答、引用来源和客户报告。
5. **Attio**（https://attio.com/）：中性浅色的数据表与卡片混排，适合多租户项目和报告总览。

## CiteAura 的组合建议

- 工作台采用 Wope/Better Stack 的深色观测基底：细边框、状态色、时间线和高信息密度。
- 工单区吸收 Linear Asks 的列表层级与活动轨迹，不复制其营销动效。
- 报告和交付包采用 Dovetail/Attio 的浅色证据阅读面，便于客户审阅和导出。
- 保持现有 Grafana-native 深色控制台方向；bento 只作为信息编排方式，不改变现有状态、证据和验收数据契约。

## 不建议直接借鉴

- Apple、Alfa Bank 等偏品牌展示的全幅视觉，不适合作为 CiteAura 的核心工作台。
- 过度霓虹、渐变、装饰插画和大面积圆角，会削弱诊断证据与工单状态的可读性。
