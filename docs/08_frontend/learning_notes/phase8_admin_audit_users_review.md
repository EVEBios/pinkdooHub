# Phase 8.8–8.9：Product Audit、ADMIN User 与管理端 Review

> **工程状态：** 已实现并通过自动化门槛；2026-08-28 微信开发者工具 Functional 全部通过
> **范围：** Product 操作历史、ADMIN 用户列表/筛选/禁用、管理端安全与多端 Review
> **不包含：** Phase 8.6 Inventory 前端、用户详情、启用用户、头像文件上传、Product 删除恢复

## 1. 规划与依赖

```text
FastAPI 真实契约
├─ Product Audit（既有稳定端点）
│  └─ OpenAPI → AuditApi → Audit Feature → 商品操作历史页
└─ ADMIN User（旧端点先收口）
   ├─ 严格 Query / typed response / Mapper
   ├─ Repository 稳定分页与行锁
   ├─ Service 同事务状态更新 + Audit
   └─ OpenAPI → AdminUserApi → User Feature → 管理用户页

页面权限
Guest → 固定白名单登录地址
普通用户 → 页面守卫直接拒绝，不挂载 ADMIN Hook
ADMIN+ → 发起 Bearer 请求，FastAPI 再做最终授权
```

Product Audit 只读能力不依赖 Product 是否 Online、Offline、Draft 或已逻辑删除，因此入口放在管理详情，但不受可编辑状态限制。ADMIN User 只实现后端已有的列表与禁用，不通过前端猜测详情、启用或头像接口。

## 2. 后端契约收口

### 2.1 用户列表

- `GET /api/v1/admin/users` 只接受 `page`、`page_size`、`status`、`role`；
- `status` 只接受 `normal/disabled`，`role` 只接受 `user/admin/super_admin`；
- 未知枚举和额外 Query 返回 HTTP 422，不再静默变成“无筛选”；
- 按 `created_at DESC, id DESC` 稳定分页；
- Mapper 只输出 `id/username/nickname/role/status/last_login_at/created_at`，不输出手机号、头像、密码或更新时间。

### 2.2 禁用用户

- `PUT /api/v1/admin/users/{user_id}/disable` 不接收 body；
- 路径 ID 必须为正整数；
- 目标用户在事务内 `SELECT ... FOR UPDATE`；
- 状态更新和 `DISABLE_USER` 审计使用同一数据库连接，审计失败会整体回滚；
- 重复禁用返回成功，但不会重复写审计；
- 不能禁用自己；ADMIN 不能禁用 SUPER_ADMIN；SUPER_ADMIN 可禁用其他 SUPER_ADMIN；
- 禁用后旧 access 立即返回 code `1005`，旧 refresh 首次返回 `1005` 并被撤销，再次使用返回 `1006`。

### 2.3 Product Audit

- `GET /api/v1/admin/products/{product_id}/audit-logs` 保持既有 ADMIN+ 契约；
- 支持逻辑删除 Product 的历史查询；真正不存在返回 `40401`；
- 只读响应字段为 `id/operator_id/action/target_type/target_id/description/ip_address/created_at`；
- 前端 Runtime Guard 额外要求 `target_type = product` 且 `target_id` 等于当前路由 Product ID，避免错误挂载。

## 3. 前端实现边界

- 固定用户管理路径：`/admin/pages/users/index`，已加入登录/注册 redirect 白名单；
- 动态商品审计路径：`/admin/pages/product-audit/index?id=<ProductId>&type=<experience|kit>`；动态详情不加入登录白名单，Guest 登录后返回固定管理商品列表；
- 首页仅对 ADMIN+ 展示“管理用户”，商品详情增加“操作历史”；
- 两个 Endpoint 都把网络响应当作 `unknown`，校验后重新构造白名单对象；额外字段不会进入 Feature/Page；
- 禁用过程中合并重复操作；network/timeout/cancel/contract/5xx 进入 `unknown`，不自动重发，只允许重新加载列表核对；
- 已禁用、自己以及 ADMIN 视角下的 SUPER_ADMIN 会在 UI 立即禁用按钮，FastAPI 仍是最终裁决；
- API Client 在受保护 JSON 或上传请求收到 `1005` 时清理本地 Session，不尝试 refresh，避免已禁用账号继续停留在伪认证状态。

## 4. Phase 8.9 Review 结论

| 检查项 | 结论 |
|--------|------|
| 权限 | Guest/普通用户在 Hook 挂载前拦截；ADMIN+ Bearer 与 FastAPI 403 保留；禁用即时阻断旧 Token |
| 上传 | 继续统一走 `Taro.uploadFile`；不手写 multipart boundary；2 MiB/MIME 前端预检不替代后端内容校验 |
| 幂等/结果未知 | Product 无幂等 mutation 与用户禁用不自动重试；用户禁用服务端幂等；Phase 8.6 Inventory key 语义未被本阶段提前实现 |
| 隐私 | User 列表不含 phone/avatar/password；Audit 只在 ADMIN+ 下展示允许字段；错误与测试不传播 Token |
| 分包 | Audit/User 都位于 `admin` 分包；公开主包只增加固定导航常量和入口 |
| 契约 | FastAPI OpenAPI → JSON → TypeScript 重新生成；User 成功响应不再是 unknown |
| 视觉兼容问题 | 当时延期的管理页白色图案与登录 `_` 闪烁已于 2026-08-29 完成专项复测并关闭；详见 changelog 的前端视觉兼容条目 |
| 仍未交付 | 8.6 Inventory 管理前端、用户详情/启用/头像上传、H5 CORS、正式合法域名/真机/支付 |

### 4.1 自动化与构建结果

- OpenAPI 已重新导出并生成 TypeScript：45 paths / 109 schemas，类型漂移检查通过；
- 前端完整 Jest 54 套件 / 350 项通过；TypeScript strict、ESLint、Stylelint 全部通过；
- 后端完整 SQLite 1465 项通过，9 项 MySQL-only 门槛按当前配置跳过；
- weapp、alipay、tt、h5 四端 production build 全部通过；微信 `admin` 分包约 131.2 KiB；
- H5 主 JS 282 KiB、入口 369 KiB，仍超过 Webpack 244 KiB 建议线；`[hash]` 弃用提示属于既有上游告警；
- 官方 npm registry 的审计仍报告 10 项 Taro H5 上游依赖链问题（4 moderate、1 high、5 critical）。建议修复会破坏性降级到 Taro 3.x，因此本阶段不自动执行 `npm audit fix`，后续应跟踪 Taro 上游修复并单独安排依赖升级验证。

## 5. 微信开发者工具 Functional 清单

### 5.1 Guest 与普通用户权限

Guest 在 Console 输入：

```js
wx.navigateTo({ url: '/admin/pages/users/index' })
```

预期：页面不请求 `/api/v1/admin/users`，点击登录后使用固定 redirect；登录 ADMIN+ 后回到“管理用户”。

普通用户分别进入：

```js
wx.navigateTo({ url: '/admin/pages/users/index' })
wx.navigateTo({ url: '/admin/pages/product-audit/index?id=1&type=experience' })
```

预期：显示“无管理权限”，Network 面板没有对应 ADMIN API；用真实 HTTP 请求 ADMIN 端点时 FastAPI 返回 403。

### 5.2 用户列表与筛选

1. ADMIN+ 从首页进入“管理用户”；
2. 依次切换正常/已禁用和普通用户/管理员/超级管理员；
3. 确认换筛选从第一页重新查询，加载更多保留同一筛选；
4. 确认页面没有手机号、头像或密码；
5. 当前账号显示“当前账号”，ADMIN 看到 SUPER_ADMIN 时显示“无权禁用”。

### 5.3 禁用

1. 准备一个可丢弃的普通测试账号，确认弹窗后禁用；
2. 确认列表重载后状态为“已禁用”，重复操作没有第二个可点击命令；
3. 用该账号重新登录，预期 code `1005` 对应的禁用提示；
4. 若用断网模拟结果未知，恢复网络后只点“重新加载列表核对”，不要连续重发禁用；
5. 不要选择当前管理员或需要继续使用的账号作为目标。

### 5.4 商品操作历史

1. 从管理商品详情点“操作历史”，不要用 `wx.navigateTo()` 测 HTTP API；
2. 分别检查 Experience、Kit、Online/Offline/Draft 与逻辑删除样本；
3. 确认操作按新到旧展示，最近的编辑、图片、配置和上下架动作可见；
4. 确认未知 action 仍显示服务端原值，不会导致白屏；
5. 点击“返回商品详情”后仍回到原 Product ID 和类型；
6. 非法 ID/type 路由显示“操作历史地址无效”，不发请求。

## 6. 知识点

1. **页面角色守卫不是授权。** 它只避免明显无权限请求；真正的边界仍是 FastAPI `get_current_admin`。
2. **OpenAPI 类型不等于运行时可信。** TypeScript 生成类型在编译后消失，外部 JSON 仍要从 `unknown` 校验并白名单重建。
3. **稳定分页必须有唯一后备排序键。** 只按时间排序时，同一时间戳记录可能跨页漂移；追加 ID 可稳定顺序。
4. **幂等不等于应当自动重试。** 禁用的服务端结果是幂等的，但客户端遇到网络未知仍先查询权威状态，减少误操作与困惑。
5. **状态写入和审计要同事务。** 只更新用户而审计失败会留下不可追踪状态；反过来也会产生虚假审计。
6. **逻辑删除不是历史消失。** Product 删除只影响当前可见性，审计与历史订单仍应按既有 ID 可追溯。
7. **禁用账号要覆盖旧凭据。** 只在登录时检查状态会让旧 access/refresh 继续有效；鉴权和 refresh 都必须检查当前用户状态。
8. **固定 redirect 是开放重定向防线。** 登录页只允许显式登记的固定页面，动态 ID 路径不应直接接受任意用户输入。
9. **隐私最小化从后端响应开始。** 前端隐藏字段不等于没有泄露；User 列表 Schema 和 Mapper 本身就不应返回手机号。
10. **分包优化的是下载边界，不是权限边界。** `admin` 分包减少主包压力，但任何人仍可能构造路径，后端必须独立鉴权。

## 7. Functional 验收结果

2026-08-28 用户确认本页清单全部通过，包括 Guest 固定登录回跳、普通用户 Hook 前拦截与真实 HTTP 403、用户角色/状态筛选和分页、隐私字段隔离、幂等禁用、unknown 后重新核对、Product Audit 多状态/逻辑删除历史、非法动态路由，以及禁用账号旧 access/refresh 的即时阻断与本地 Session 清理。该结论不替代真机、正式 HTTPS 域名或 H5 跨域验收；Phase 8.6 Inventory 管理前端仍按独立阶段实施。
