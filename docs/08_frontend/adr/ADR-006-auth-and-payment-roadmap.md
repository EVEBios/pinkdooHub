# ADR-006：认证与支付采用 MVP/正式发布分阶段路线

> **Status:** Accepted
> **Date:** 2026-08-15
> **Decision Owners:** pinkdooHub

## Context

现有后端已经实现用户名密码、Bearer JWT、refresh/logout 和 ADMIN+ 人工确认订单 Paid；尚未实现微信登录和微信支付。客户端需要先形成可学习、可测试的业务纵向链路，又不能把临时能力误报为商业支付闭环。

## Decision

### MVP

- 四端使用现有用户名密码；
- 使用 access/refresh token；
- Pending 订单由 ADMIN+ 人工确认 Paid；
- 用户 UI 明确展示“待商家确认”；
- 不创建伪微信登录/支付按钮。

### 正式公开发布前

- 微信小程序增加服务端换取身份的微信登录；
- 正式商业场景增加服务端支付单、签名、验签、异步通知和幂等；
- Order Paid 由可信服务端支付结果驱动，不由客户端回调直接驱动；
- 补充 Order create idempotency、登录/注册限流与认证安全 Review。

### 后续平台

支付宝、抖音登录/支付按 Provider 扩展，不复制微信专属 Service。后端优先评估通用 ExternalIdentity 和 Payment Provider 边界。

## Rationale

- 复用已测试后端，先验证商品→登录→下单→订单→管理闭环；
- 降低第一阶段同时学习支付安全和平台认证的范围；
- 明确商业发布前的安全硬门槛；
- 为多平台身份和支付预留正确扩展方向，而不提前实现。

## Security Requirements

- AppSecret、商户密钥和签名证书只在后端；
- 平台临时 code 只传后端；
- 客户端支付成功只表示 UI 调用结果，不是 Order Paid 权威证据；
- 支付通知验签、金额/订单重检和幂等在服务端；
- Token、密码、平台 code 不进入日志和监控；
- H5 Bearer Storage 在公开发布前专项 Review。

## Consequences

- MVP 不是完整线上商城支付体验；
- 用户必须理解人工确认语义；
- 正式发布前需要新的后端需求、Schema、迁移、API、测试与文档阶段；
- 当前架构必须通过 Platform Port 隔离未来登录/支付差异。

## Release Gate

如果产品对外宣称支持微信登录或微信支付，本 ADR 的正式发布阶段必须已实现并通过真实平台沙箱/真机测试；仅有前端页面或 Mock 不算完成。

