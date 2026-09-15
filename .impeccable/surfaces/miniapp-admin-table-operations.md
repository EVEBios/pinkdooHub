---
version: 2
slug: "miniapp-admin-table-operations"
primary_target: "miniapp/src/admin/pages/tables/index.tsx"
related_targets: ["miniapp/src/admin/pages/tables/index.scss","miniapp/src/admin/pages/tables/direct_open_form.tsx","miniapp/src/admin/pages/table-session-detail/index.tsx","miniapp/src/admin/pages/table-session-detail/index.scss"]
---

# Admin Table Operations — Ribbon Ledger

## Surface

ADMIN+ 的 30 桌状态总览、待付款会话收款入口、无顾客账号的直接开台表单，以及当前会话详情。服务于工作人员现场扫读剩余时间并执行下一步的任务；本次为既有管理界面的 ordinary extension，继承根目录 `DESIGN.md` 与共享管理样式，不改写全局设计系统或 `.impeccable/design.json`。

## Mode

Operate

## Direction contract

THESIS: 以桌号、阶段和剩余时间组织门店现场判断，让开台与收款动作紧邻对应桌台。

OWN-WORLD: 继承 Ribbon Ledger 的深莓纹理页头、暖纸画布、瓷白记录面和既有语义色；数字和状态先于装饰。

STORY: 先读待收款与到时桌数，按需筛出需关注桌台，再核对卡内具体预警组并确认收款、直接开台或查看当前会话。

FIRST VIEWPORT: 紧凑页头下先展示待收款与到时桌数、提前提醒说明和“全部桌台／需关注”两个完整按钮，再进入桌台网格；待付款卡内强调收款按钮。选择空闲桌后，直接开台表单位于提醒筛选区与网格之间并滚动到顶部。

FORM: Code-led 既有功能扩展；手机双列、宽屏三列，倒计时使用加粗表格数字，状态同时保留文字。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Layout and interaction

- 页头展示“30 桌实时状态”和服务端数据时间。桌台按现有列表顺序排列；网格在 `700px` 及以下为双列，更宽为三列，卡片内按钮占满可用宽度。
- 每桌依次呈现桌号与状态、付款等待／体验／缓冲剩余、来源及相关动作。倒计时单行加粗并使用表格数字；绿色与赭黄色边线和标题底色辅助分辨使用中与待付款，文字独立表达状态。
- 列表明确区分“系统订单”与“直接开台”；多组计时时说明当前展示最长一组。前端倒计时走完后展示“待确认结束”和同步提示，不把本地时钟当作已释放的证明。
- 提醒区以“待收款 N 桌 · 到时提醒 M 桌”先说明数量含义，再用完整宽度的两列按钮切换“全部桌台／需关注 N”；当前筛选使用既有莓果主按钮，另一项使用描边次按钮。筛选为空时显示“当前没有需要关注的桌台。”，查看和切换均不消除提醒。
- 到时桌卡沿用既有赭黄警示边线和浅警示标题底色；最长组倒计时仍保留，每个需提醒的具体组在其下用细分隔线、加粗警示文字和表格数字分别展示“分钟组 · 即将到时／缓冲中”及该组剩余。多组到时在同一桌卡内展开，数量汇总仍按桌表达。
- 待付款卡和会话详情使用同名主按钮“确认已收款并计时”，通过既有整单线下收款确认流程衔接计时；查看会话与停用新开台保持次要动作层级。
- 空闲且启用的桌台提供“直接开台”。顶部表单先显示目标桌号，再展示服务端体验时长选项、可选备注、所选时长与 10 分钟缓冲说明，最后是“确认开始计时”和“取消”。选中项与提交按钮沿用既有莓果主色。
- 表单显示时禁用列表中的开台、收款和启停写操作；提交处理中锁定选择及备注。结果未知时保留原操作并展示“重试原操作并确认结果”，不让工作人员误以为已经开台成功。
- 会话详情先呈现桌台身份、来源和可核对的会话信息，再呈现付款动作或各组计时；直接开台使用“无需顾客账号”说明，备注及开台管理员按实际响应展示。
- 会话详情只给当前预警组增加赭黄外框及“即将到时，请提醒顾客安排收尾。”或“已进入缓冲，请关注本组收尾。”说明；其他组保留普通瓷白卡片，不能因短组预警而让最长组一并突出。

## Content authority

本 brief 只记录局部信息层级、布局和交互表达。时长、缓冲、整单收款、权限、幂等、并发与自动释放的权威规则见 [`table_session_module.md`](../../docs/01_requirements/table_session_module.md)；HTTP 契约见 [`table_session_api.md`](../../docs/03_api/table_session_api.md)，前端接入边界见 [`api_integration_contract.md`](../../docs/08_frontend/api_integration_contract.md)。不在此维护另一份业务规则或 API 清单。

## Review evidence and limits

2026-09-14 的独立 finish reviewer 返回 `ship`。收尾记录核对了当前页面实现及以下截图：

- `.impeccable/review/table-operations/mobile.png`：390 × 844，双列总览，体验、待付款、缓冲及空闲桌台。
- `.impeccable/review/table-operations/desktop.png`：768 × 1024，三列总览与卡片信息层级。
- `.impeccable/review/table-operations/direct-form.png`：390 × 844，顶部直接开台表单、选中时长、缓冲说明和列表禁用态。

截图来自 H5 隔离模拟 API，只支持所捕获视口和展示状态的视觉结论；不构成微信真机、真实收款、持久数据库迁移、完整 30 桌全页或会话详情视觉验收证据，也不表示已发布或任何发布 Gate 已通过。全局视觉沿用 `DESIGN.md`；本次收尾仅新增此局部 brief，不重新记录或覆盖既有设计系统。

## P2.3 finish review（2026-09-15）

管理员到时预警局部扩展的独立 finish review disposition 为 `ship`。本轮记录依据已构建的桌台列表、筛选与会话详情源码及截图；继承 Ribbon Ledger／Operate、原字体层级和语义色，不增加全局设计规则。

提前提醒与缓冲的业务边界以 [P2.3 管理员桌台到时预警](../../docs/01_requirements/table_session_module.md#p23-管理员桌台到时预警2026-09-15) 为准。展示上逐组标明提前 10 分钟提醒和缓冲阶段，同桌去重；直接开台和暂停新开台的活动桌保留提醒。全部计时走完而服务端尚未确认释放的桌台仍留在需关注范围，并显示“待确认结束”。

- [tables-320.png](../../docs/08_frontend/qa/p2-table-warning/tables-320.png)、[tables-390.png](../../docs/08_frontend/qa/p2-table-warning/tables-390.png)、[tables-768.png](../../docs/08_frontend/qa/p2-table-warning/tables-768.png)：完整筛选按钮、最长组概览与具体预警组、缓冲中的暂停新开台桌、收款动作及空闲桌。
- [filtered-320.png](../../docs/08_frontend/qa/p2-table-warning/filtered-320.png)、[filtered-390.png](../../docs/08_frontend/qa/p2-table-warning/filtered-390.png)、[filtered-768.png](../../docs/08_frontend/qa/p2-table-warning/filtered-768.png)：需关注筛选选中态及筛选后的桌卡。
- [detail-320.png](../../docs/08_frontend/qa/p2-table-warning/detail-320.png)、[detail-390.png](../../docs/08_frontend/qa/p2-table-warning/detail-390.png)、[detail-768.png](../../docs/08_frontend/qa/p2-table-warning/detail-768.png)：短组即将到时的突出状态，以及未预警最长组的普通卡片。

本轮共用证据还包括工作台的三个视口，详见 [P2 桌台预警 QA](../../docs/08_frontend/qa/p2-table-warning-review.md)。12 张证据均为隔离模拟 API 的 H5 展示；本轮详情截图补充了对应状态的视觉证据，但仍不构成微信真机、真实资金操作、完整 30 桌全页、持久环境迁移或发布 Gate 的验收。未将模拟数据数量、会话标识或局部预警排版提升为全局设计规范。
