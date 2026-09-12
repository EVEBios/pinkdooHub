---
version: 1
slug: "miniapp-member-wallet"
primary_target: "miniapp/src/pages/member"
related_targets: ["miniapp/src/pages/wallet-transactions","miniapp/src/admin/pages/user-wallet","miniapp/src/pages/order-detail","miniapp/src/admin/pages/order-detail"]
---

# Ribbon Ledger — Member Wallet

## Surface

会员中心、余额明细、充值前置态、订单余额支付，以及 ADMIN+ 用户资金调整和全额退款。沿用既有商品与订单世界，不改变服务端权威金额、权限或资金终态。

## Mode

Operate

## Direction contract

THESIS: 钱包首先是可核对的账本，其次才是快捷支付；每一笔金额都必须和来源、状态及下一步一起出现。

OWN-WORLD: 暖纸白承载个人信息，瓷白记录面承载账目，深莓果只标记可执行命令和已确认的资金事实。

STORY: 用户从身份与余额进入明细或支付；管理员从目标用户进入调整，从订单事实进入退款。

FIRST VIEWPORT: 首屏直接显示会员身份、权威余额、1000.00 元上限和当前可用动作；不使用营销 Hero、英文 eyebrow 或无意义指标卡。

FORM: Code-led Taro mobile workspace；金额始终以服务端两位小数字符串展示，收入/支出同时使用文字与正负号，全部操作保持 44px 触控高度。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Requirements

- 明示余额仅用于购买 pinkdooHub 自有商品或服务，不支持转账、提现和混合支付。
- 充值入口在真实支付未开通时显示准确前置条件，不创建假成功交易。
- 余额、流水、支付、退款均覆盖加载、空、错误、禁用、处理中和结果未知状态。
- ADMIN 不能操作自己或其他工作人员；前端提示不替代服务端授权。
- 页面在 390px 与 768px 下保持可扫描，订单号、原因与时间允许安全换行。
