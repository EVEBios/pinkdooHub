# Phase 7.2 学习笔记：确认页与 Order 创建纵向切片

> 状态：**Phase 7.2 已完成。** 工程实现、自动化契约测试、真实 FastAPI + SQLite 创建矩阵、四端 production build 均已通过；2026-08-24 用户进一步完成微信开发者工具 Functional，确认 Guest 登录返回、Experience/Kit/混合创建、库存不足、快速连点、弱网 unknown 与成功 Cart 对账全部通过。该结论不代表真机、H5 或正式 HTTPS/合法域名已验收；H5 真实联调仍等待后端 CORS allowlist。

## 1. 本阶段的最小闭环

Phase 7.2 只交付一条可观察的纵向切片：

```text
Product 详情 → 本地购物清单 → 订单确认 → 登录后返回
                                      ↓
                              POST /api/v1/orders
                                      ↓
                           服务端 Order 快照结果
                                      ↓
                          按提交快照对账本地 Cart
```

Phase 7.2 交付当时没有提前实现我的订单列表、详情、取消、支付、ADMIN 状态操作、微信登录或微信支付；其中用户侧列表/详情/Pending 取消已于 Phase 7.3 补齐。

## 2. Step 7.2.1：冻结 Order Endpoint 契约

`OrderApi.createOrder()` 使用现有 `ApiClient` 发送认证请求：

```json
{
  "items": [
    { "product_id": 1, "experience_option_id": 11, "quantity": 2 },
    { "product_id": 2, "quantity": 1 }
  ],
  "remark": "周六到店"
}
```

其中 Experience 必须携带真实 `experience_option_id`；Kit 不发送该字段，不能把本地 `null` 机械写进请求。Endpoint 还会重新做一次白名单投影，确保名称、配置文案、图片、ProductType 和预览价格不会越过网络边界。

响应虽然有 OpenAPI 生成类型，运行时仍然是 `unknown`。Guard 校验订单号、状态 value/label、UTC 时间、Item 数量、金额格式、小计乘法、总额求和，以及 Experience 完整 Option 快照/Kit 全 null Option 快照。

这里的新知识点是 **OpenAPI 类型只保护编译期，Runtime Guard 才保护真实网络输入**，以及 **请求 DTO 应在 Endpoint 边界做显式白名单投影**。

测试覆盖：正确 Experience/Kit 请求、null/undefined Option 省略、认证 POST 参数、未知字段丢弃、坏订单号、坏状态、坏金额、坏 Option 快照、总额不一致和坏时间。

## 3. Step 7.2.2：把提交建模成状态机

创建订单不是一个 `isLoading + error` 就能完整描述的操作。当前使用判别联合：

```text
idle → submitting → succeeded
                  ↘ failed
                  ↘ unknown
```

- `failed`：后端明确拒绝、认证失效或响应契约错误；用户修正问题后可以再次主动提交；
- `unknown`：NetworkError、TimeoutError、请求取消、成功响应契约损坏或 HTTP 5xx，客户端无法证明服务端事务没有提交；
- `succeeded`：只由通过 Guard 的服务端 Order 快照触发。

点击提交时先复制 Cart 和 request，形成不可变提交快照。同一个进行中的 `submit()` 返回同一个 Promise，只产生一个 POST；页面按钮也禁用，形成两层防重复保护。

这里的新知识点是 **状态机应区分业务失败与执行结果未知**、**Snapshot 隔离请求发出后的本地变化**，以及 **前端防重复不等于服务端幂等**。

因为 `POST /orders` 没有客户端 Idempotency-Key，unknown 状态绝不自动重试，也不提供立即再次创建按钮。

测试覆盖：快照冻结、Experience/Kit 最小映射、同 Promise/单 POST、明确失败、network/timeout/cancel/contract/5xx unknown、空 Cart/边界、remark trim/空白省略/500 上限。

## 4. Step 7.2.3：确认页与安全登录返回

确认页先处理 Cart 初始化/错误/空，再处理 Auth 初始化/错误/Guest/Authenticated。Guest 点击登录时只携带固定的确认页 redirect：

```text
/pages/login/index?redirect=%2Fpages%2Forder-confirm%2Findex
```

登录页不会直接信任路由字符串。`parseLoginRedirect()` 解码后只接受注册白名单中的 `/pages/order-confirm/index`，外部 URL、未注册页面和畸形编码全部回退首页；成功后使用 `reLaunch` 回确认页，使认证与 Cart 都从应用级 Provider 的权威状态重新进入页面。

remark 使用受控 `Textarea`，React state 是唯一输入事实；空白由 Feature 省略，非空 trim 后最多 500 字符。

这里的新知识点是 **路由参数也是不可信输入**、**登录回跳需要 allowlist 防开放重定向**，以及 **受控表单让 UI、校验和请求值保持一致**。

页面对 `40931` 库存不足、`42231` Product 不可下单、`42232` Experience Option 不可用和 SessionExpired 提供稳定提示。库存不足不展示后端没有承诺的 available 数量。

测试覆盖：Cart/Auth 所有互斥状态、Guest 登录 URL、受控 remark、submitting 禁用、failed 与 unknown 不混淆。

## 5. Step 7.2.4：服务端结果与 Cart 对账

成功页只显示后端响应中的：

- `order_no`、状态和创建时间；
- Product/Option 名称与配置快照；
- 服务端单价、小计和总额；
- 服务端保存的 remark。

本地 Cart 的名称、配置和预览价格不参与结果页。即使管理员在提交前调整价格，成功页也只认事务内保存的 Order 快照。

成功后不能无条件 `clear()` 整个 Cart，因为请求期间用户可能加入其他商品或增加同一配置。当前按提交快照逐项对账：

| 当前同 key 数量 | 对账动作 |
|---|---|
| 等于提交数量 | 移除 |
| 大于提交数量 | 扣除提交数量，保留新增差额 |
| 小于提交数量 | 无法证明变化来源，保留并报告 conflict |
| 不在提交快照 | 原样保留 |

对账与其他 Cart mutation 共用 Promise 队列，仍然先持久化再发布。Storage 失败或 conflict 只作为成功结果的附加警告；服务端订单已经创建，不能把 UI 改成创建失败，否则会诱导重复 POST。

还有一个重要事件顺序：对账可能先把 Cart 发布为空，Submission 随后才发布 `succeeded`。确认页因此必须让服务端成功状态优先于 Cart empty。

这里的新知识点是 **服务端成功与本地清理是两个独立事实**、**并发本地状态需要按提交 Snapshot 对账**，以及 **渲染优先级必须服从事件发生顺序**。

测试覆盖：相等移除、差额保留、未知变化冲突、无关 Item 保留、Storage 失败不发布伪清理，以及 Cart 已空时仍展示服务端成功结果。

## 6. Step 7.2.5：纵向契约验证

前端纵向测试保留真实调用链：

```text
CartStore → OrderSubmissionStore → OrderApi → ApiClient
```

只替换平台边界：Storage、transport 和 Auth token。它验证：

1. Experience 与 Kit 混合请求的最终 JSON 精确符合 FastAPI 契约；
2. Bearer 认证进入请求；
3. 成功使用服务端快照并对账 Cart；
4. `40931` 明确失败保留 Cart；
5. timeout 进入 unknown、保留 Cart且只发一次 POST。

后端另运行真实 FastAPI + SQLite 的 34 项测试，覆盖创建主链、Experience/Kit/混合订单、库存边界和事务失败回滚。它不 Mock Order/Inventory Service，因此能验证前端所依赖的现有服务端契约。

最终工程验证：

```text
Jest                         19 suites / 130 tests PASS
TypeScript                   PASS
ESLint --max-warnings=0      PASS
Stylelint                    PASS
OpenAPI generated drift      PASS
FastAPI + SQLite Order       34 tests PASS
Full backend SQLite          1445 passed / 9 MySQL-only skipped
weapp production build       PASS
alipay production build      PASS
tt production build          PASS
h5 production build          PASS
```

H5 build 的 app 入口为 343 KiB、主 JS 为 259 KiB，超过 Webpack 244 KiB 建议线，但未触发失败门槛；同时保留 Taro/Webpack `[hash]` 弃用警告。

## 7. 微信开发者工具 Functional

2026-08-24 用户确认以下 Phase 7.2 可执行路径全部通过：

1. 微信开发者工具中 Guest → 登录 → 自动返回确认页；
2. 使用真实 Experience 创建并核对 Option 快照；
3. 使用有库存 Kit 创建，确认请求不含 Option；
4. 创建 Experience + Kit 混合订单并观察 Kit 库存扣减；
5. 数量超过库存时显示 `40931` 且 Cart 保留；
6. 提交中快速连点只创建一单；
7. 模拟断网/超时后进入 unknown，不出现立即重试入口；
8. 成功后 Cart 仅移除已提交数量，期间新增内容保留；
9. 重启后从后端“我的订单”核对 unknown 结果（由 Phase 7.3 提供，仍不计入 Phase 7.2 完成门槛）。

前 8 项均已通过。第 9 项的工程入口已由 Phase 7.3 实现，待 Phase 7.3 微信 Functional 一并验证。H5 真实联调不能通过临时代理伪装成后端 CORS 已完成，必须先由 FastAPI 配置严格 Origin allowlist。

## 8. 下一步

Phase 7.3 已按以下最小顺序完成工程实现：

1. `GET /api/v1/orders` 我的订单列表；
2. `GET /api/v1/orders/{id}` 权威详情；
3. unknown 提示链接到列表/详情核对；
4. Pending 订单的 empty-body cancel；
5. 成功取消后刷新服务端状态，不在前端伪造状态机结果。

实现与验证细节见[Phase 7.3 订单查询/取消学习笔记](phase7_order_query_cancel.md)。在后端增加 Order create 客户端幂等键前，任何页面或网络层都不得为 unknown 自动重放 POST。
