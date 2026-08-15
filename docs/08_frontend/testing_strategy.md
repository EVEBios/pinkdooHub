# pinkdooHub 前端测试策略

> **Document Version:** v0.1
> **Status:** Draft
> **Last Updated:** 2026-08-15
> **Applies To:** 规划中的 `miniapp/` 与其 FastAPI 集成边界

本文档定义测试层级、Mock 边界、四端矩阵、CI 与发布门槛。具体工具版本由 Taro Spike 固定。

---

## 1. 测试原则

1. 优先验证用户可观察行为和稳定契约，不绑定组件内部实现。
2. 纯业务算法、请求层、认证与幂等逻辑必须可脱离开发者工具运行。
3. Mock 平台、网络、时间和 Storage 等不稳定边界，不 Mock 被测 Feature 本身。
4. 构建成功不等于功能可用；Build、Smoke、Functional 分层验收。
5. 微信通过不代表支付宝、抖音或 H5 通过。
6. 不为固定覆盖率制造低价值测试；关键风险必须完整覆盖正常和失败分支。
7. 测试夹具不得包含真实密码、Token、手机号或 AppSecret。

---

## 2. 测试金字塔

| 层级 | 目标 | 工具候选 | 频率 |
|------|------|----------|------|
| Typecheck | 静态 DTO、null、联合类型、调用边界 | `tsc --noEmit` | 每次提交 |
| Lint/Format | 规则与格式 | ESLint/Prettier | 每次提交 |
| Unit | 纯函数、Feature 算法、Error、Session | Jest | 每次提交 |
| Component | Props、事件、四态、生命周期外观 | Taro React Test Utils + Jest | 每次提交 |
| API Client | transport、信封、Token、上传、幂等 | Jest + fake transport/storage/clock | 每次提交 |
| Contract | OpenAPI 类型和关键 Operation | OpenAPI 导出 + 生成 + diff | 每个 PR |
| Build | 四端可编译 | Taro CLI | 每个 PR |
| Smoke | 启动、导航、网络、Storage | 各端工具/H5 浏览器 | 阶段候选 |
| E2E | 用户/管理员纵向链路 | 平台自动化/H5 E2E | PR 或发布候选 |
| Real device | 真机、弱网、前后台、上传 | 人工/平台能力 | 发布候选 |

---

## 3. 静态门槛

预期命令：

```text
npm run typecheck
npm run lint
npm run format:check
```

规则：

- production source 禁止无说明 `any`；
- 禁止业务层直接引用 `wx`、`my`、`tt`；
- 禁止 Page 直接引用低层 HTTP transport；
- Generated 目录排除人工格式化修改，但参与 typecheck；
- 未使用变量、浮动 Promise 和危险类型断言按工具能力收紧。

---

## 4. 单元测试重点

### 4.1 Shared

- Money 原样/显示格式；
- UTC 转本地与本地筛选转 UTC；
- `{value,label}` 未知值；
- 相对/绝对图片 URL；
- 正整数路由参数；
- Page 响应与下一页判断；
- Runtime Envelope Guard。

### 4.2 Product

- Experience 有效组合筛选；
- 每一步选择后的可用值；
- 最终唯一 Option；
- 无匹配/多个异常匹配；
- Kit available 只用于 UI，不生成权威订单金额。

### 4.3 Order

- Experience/Kit Item 构造；
- 重复 Product/Option 合并或拒绝策略；
- 数量与 Item 边界；
- 空白 remark；
- 状态对应按钮；
- empty-body PATCH；
- 本地购物车持久化与坏数据恢复。

### 4.4 Inventory

- Idempotency-Key 生命周期；
- 同一次重试复用；
- 新操作使用新 key；
- 201/200 成功分支；
- key 不进入日志/error。

---

## 5. API Client 测试矩阵

必须覆盖：

- HTTP 2xx + code 0；
- HTTP 2xx + 非 0 code；
- HTTP 401 缺少凭据；
- HTTP 403 不触发 refresh；
- HTTP 400 + code 1006；
- 三个并发 1006 只有一次 refresh；
- refresh 成功后每项最多重放一次；
- refresh 失败清理会话；
- refresh 自身 1006 不递归；
- HTTP 422 `data.errors`；
- Product 42201 `data.issues`；
- 404/409 结构化业务错误；
- 非 JSON、坏信封和错误 content-type；
- network fail、timeout、abort；
- JSON Query 编码；
- 无 body PATCH 完全不设置 data；
- upload Header、formData、成功与失败；
- 日志和错误不含 Token、密码、幂等键。

写请求超时测试必须断言“未自动重试”。

---

## 6. React 组件测试

组件测试关注：

- 用户看到什么；
- 用户点击/输入后发出什么事件；
- Loading/Empty/Error/Content 是否互斥；
- disabled/submitting 是否阻止重复事件；
- 长文本、null 和未知状态的安全表现；
- Props 变化后的渲染；
- 页面生命周期触发的外部行为。

避免：

- 断言私有 state；
- 调用组件内部非公开函数；
- 把整页做成巨大、难 Review 的 snapshot；
- 仅测试 NutUI 自己已经保证的内部行为。

快照只用于小而稳定的展示结构，并配合语义断言。

---

## 7. OpenAPI 契约测试

CI 流程：

```text
FastAPI app.openapi()
  → export openapi.json
  → openapi-typescript
  → generated/schema.d.ts
  → typecheck
  → git diff --exit-code（生成物策略批准后）
```

额外断言关键 Operation 存在：

- auth login/refresh/logout；
- public Product list/detail；
- user Order create/list/detail/cancel；
- admin Product/Inventory/Order；
- HTTP Bearer scheme；
- 成功/错误信封 Schema。

如果文档计划接口不存在，测试不得伪造类型让前端继续开发。

---

## 8. 四端构建与 Smoke

### 8.1 Build

每个 PR：

```text
npm run build:weapp
npm run build:alipay
npm run build:tt
npm run build:h5
```

检查：

- exit code；
- 编译 warning 白名单；
- secret 扫描；
- 包体积；
- 目标配置文件；
- 没有 development Origin 进入 production 产物。

### 8.2 Smoke

至少覆盖：

- 启动与首页；
- 健康检查；
- 登录输入与提交；
- Storage；
- 页面导航/返回；
- 一项 Dialog/Toast；
- 一次图片或上传验证；
- 网络失败提示。

---

## 9. 纵向 E2E

### 9.1 用户路径

1. 游客浏览 Product；
2. 注册/登录；
3. Experience 选择有效 Option 并下单；
4. Kit 下单与库存不足；
5. 查看订单；
6. 取消 Pending；
7. Token 过期刷新；
8. 登出并清理会话。

### 9.2 管理路径

1. 普通用户进入管理入口失败；
2. ADMIN 创建 Product 草稿；
3. 配置 Option/价格/图片；
4. 上架失败完整展示 issues；
5. 上架成功；
6. Kit Inventory 调整首次/重放；
7. 管理订单 Pending → Paid → Completed；
8. 查看审计历史。

E2E 使用隔离测试账号和可重复种子。不得依赖开发者个人数据库中的手工数据。

---

## 10. 真机与非功能测试

发布候选覆盖：

- Android/iOS；
- 常见屏幕、小屏和大字体；
- Wi-Fi、移动网络、弱网和断网；
- 前后台切换、锁屏、请求中断；
- Token 即将/已经过期；
- 上传中断；
- 重复点击和结果未知；
- 图片 HTTPS、失败占位和预览；
- 小程序冷启动和分包首次加载；
- H5 移动浏览器、刷新、后退和直接链接；
- 合法域名、证书、CORS 和 CSP；
- 无障碍基础：点击区域、对比度、非纯颜色提示。

性能以测量为准：首屏时间、列表滚动、请求数、包体积和图片体积。没有测量证据不做预优化。

---

## 11. Mock 边界

应该 Mock：

- Taro transport；
- Taro Storage；
- 当前时间/随机 key；
- Platform login/payment/share；
- 外部图片选择和上传；
- 不稳定网络和超时。

不应该 Mock：

- 被测 Feature 本身；
- 简单纯格式化函数的真实行为；
- OpenAPI DTO 到 Endpoint 的关键映射；
- 集成测试中的 FastAPI 业务服务。

后端真实 HTTP 集成使用现有 pytest/httpx 体系；前端 E2E 通过隔离环境调用真实 API。

---

## 12. CI 路径

建议任务：

| 变更路径 | 后端测试 | 前端静态/单测 | OpenAPI | 四端构建 |
|----------|----------|---------------|---------|----------|
| `app/`、`tests/` | 是 | 契约相关时 | 是 | 是 |
| `docs/` only | 文档契约相关时 | 否 | 否 | 否 |
| `miniapp/src/` | 相关 smoke | 是 | 是 | 是 |
| OpenAPI Schema/路由 | 是 | 是 | 是 | 是 |
| 前端构建配置/依赖 | 否 | 是 | 否 | 是 |

先保证正确性，再根据真实 CI 时长做安全缓存和路径优化。

---

## 13. 阶段门槛

### 架构 Draft → Approved

- [ ] Taro 四端空应用构建；
- [ ] 测试工具可运行；
- [ ] Request/Upload 最小验证；
- [ ] 候选组件矩阵；
- [ ] H5 CORS Spike；
- [ ] Proposed ADR 更新状态。

### MVP 功能完成

- [ ] 微信/H5 用户纵向 E2E；
- [ ] 支付宝/抖音 Build + Smoke；
- [ ] API Client 风险矩阵；
- [ ] 后端完整测试；
- [ ] 文档与类型无漂移。

### 正式公开发布

- [ ] 微信登录；
- [ ] 商业需要时的微信支付闭环；
- [ ] Order create 幂等；
- [ ] 生产对象存储/CDN；
- [ ] 登录/注册限流和认证安全 Review；
- [ ] 持久 MySQL 迁移按流程执行；
- [ ] 真机、隐私、HTTPS、合法域名、回滚全部通过。

