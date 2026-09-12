---
version: 1
slug: "miniapp-src-pages-index-index-tsx"
primary_target: "miniapp/src/pages/index/index.tsx"
related_targets: ["miniapp/src/admin/pages/product-inventory/index.tsx","miniapp/src/admin/pages/inventory-transactions/index.tsx","miniapp/src/admin/components/inventory.tsx","miniapp/src/admin/components/masked_date_input.tsx","miniapp/src/styles/theme.scss"]
---

# Ribbon Ledger UI Refresh

## Surface

公开商品首页与关联的 Kit 库存工作台。真实工程实现，保留现有数据、状态和操作。

## Mode

Operate

## Direction contract

THESIS: 用克制的莓果色账本感，让顾客浏览轻盈、让库存操作准确可复核。

OWN-WORLD: 粉暖纸面、窄色域渐变、功能性玻璃层、紧凑中文排版、真实商品图与清晰数字。

STORY: 先确认页面与当前身份，再筛选内容或读取库存，最后完成浏览、调整与追溯。

FIRST VIEWPORT: 首页先看到品牌、短标题、搜索与首批商品；库存页先看到商品身份、权威余额与调整入口。

FORM: Code-led Ribbon Ledger A，方向已由用户选定；不使用角色图案，不新增装饰资产。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Requirements

- 主色块只使用相邻莓果粉或暖白色阶的低跨度渐变。
- 透明与模糊只用于顶部信息、筛选和操作层级，并提供不支持模糊时的实色回退。
- 控制正文行宽、标题字数与长内容换行；价格、库存和流水数字便于扫读。
- 继续使用服务端商品图；不加入 Hello Kitty、emoji、手绘 SVG 或占位装饰。
- 保留所有既有入口、筛选、分页、错误态、提交与幂等重试行为。
