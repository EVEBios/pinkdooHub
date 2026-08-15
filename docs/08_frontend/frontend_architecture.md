# pinkdooHub 前端架构

> **Document Version:** v0.1
> **Status:** Draft
> **Last Updated:** 2026-08-15
> **Scope:** `miniapp/` 规划架构；当前尚未创建前端工程、安装依赖或完成技术 Spike
> **Decision Owners:** pinkdooHub

本文档定义 pinkdooHub 跨端客户端的目标架构、依赖方向、职责边界和实施门槛。首发目标为微信小程序，并要求同一套核心代码在 6–12 个月内扩展到 H5、支付宝小程序和抖音小程序。

技术选型的理由和历史保存在 [ADR](adr/)；多端差异、API 契约、测试和学习步骤分别见：

- [多端策略](multi_platform_strategy.md)
- [API 集成契约](api_integration_contract.md)
- [测试策略](testing_strategy.md)
- [学习路线](learning_roadmap.md)

---

## 1. 背景与当前边界

pinkdooHub 当前后端版本候选为 `v0.6.0`，已实现 User、Product、Order 与 Inventory 的核心契约和 FastAPI 端点。客户端必须与现有 `/api/v1`、Bearer JWT、统一响应信封、Product/Order/Inventory 业务边界配合，不得在前端重新定义权威价格、库存、权限或状态机。

已冻结的产品决策：

| 主题 | 决策 |
|------|------|
| 首发载体 | 微信小程序 |
| 6–12 个月目标 | H5、支付宝小程序、抖音小程序 |
| 跨端框架 | Taro 4 + React + TypeScript |
| MVP 登录 | 复用现有用户名与密码 |
| 正式公开发布前 | 增加微信登录 |
| MVP 支付 | ADMIN+ 人工确认订单已支付 |
| 正式商业发布前 | 增加服务端闭环的微信支付 |
| 首版管理端 | 同一 Taro 应用的 `admin` 分包 |
| 未来复杂管理端 | 同仓库增加独立 `admin-web/` |
| GitHub | 继续使用当前仓库，不嵌套第二个 Git 仓库 |

当前阶段只编写并 Review 架构文档。文档完成后先执行最小技术 Spike；只有 Spike 结果写回本文档和相关 ADR 后，才创建正式 `miniapp/` 工程。

---

## 2. 架构目标

### 2.1 必须达成

1. 一套核心业务与 React 组件代码支持微信、支付宝、抖音和 H5。
2. 平台差异集中在配置、Platform Adapter 或平台专属文件，不散落到业务页面。
3. FastAPI OpenAPI 是前端 API 类型的权威来源；生成类型禁止手工编辑。
4. 页面、组件、Feature、API 与平台层职责清晰，依赖方向可静态检查。
5. TypeScript 使用严格模式，不以 `any` 规避外部输入校验。
6. 认证、权限、金额、库存、状态变迁和幂等规则与后端契约一致。
7. 新功能至少通过类型、单元/组件、契约和四端构建门槛。
8. 架构适合逐步学习 JavaScript、TypeScript、React、Taro、HTTP 与测试。
9. 首版保持依赖最小化；只有明确收益和验证结果才能引入新框架。

### 2.2 质量属性

| 属性 | 目标 |
|------|------|
| 可维护性 | 业务页面不直接处理 Token、平台原生 API 或响应信封 |
| 可移植性 | 共享逻辑不依赖 `wx`、`my`、`tt` 或浏览器 DOM |
| 可测试性 | Feature 与 API Client 可通过注入的 transport、clock、storage 测试 |
| 安全性 | 前端包和日志中不存在 AppSecret、JWT Secret、密码或完整 Token |
| 一致性 | 金额、UTC、Enum、分页和错误形状遵循后端契约 |
| 可观测性 | 错误包含可定位上下文但不泄漏凭据和个人信息 |
| 性能 | 分页、分包、按需组件、图片策略和可测量优化优先 |

---

## 3. 非目标

以下内容不属于首个前端工程阶段，未经新的需求冻结和 ADR 不提前实现：

- React Native、原生 App、桌面客户端；
- SSR、Next.js、React Server Components；
- React 19 或实验性 Taro/Vite 插件；
- 微前端；
- Redux、Zustand、MobX 或 TanStack Query；
- 独立部署的 `admin-web/`；
- 微信、支付宝、抖音支付的占位伪实现；
- 未实现的后端能力，例如用户头像上传、管理员启用用户；
- 自研完整 UI 设计系统；
- 为假想业务抽象通用工作流、插件系统或低代码层。

---

## 4. 技术基线

| 层级 | 选择 | 状态 |
|------|------|------|
| 跨端框架 | Taro 4.x；所有 `@tarojs/*` 使用同一精确版本 | Accepted；精确版本由 Spike 固定 |
| UI 框架 | React 18 | Accepted；精确版本由 Spike 固定 |
| 语言 | TypeScript strict | Accepted |
| 编译器 | Webpack 5 | Proposed；四端 Spike 后决定是否 Accepted |
| 样式 | SCSS + 项目 Design Tokens | Proposed |
| 基础组件 | `@tarojs/components` | Accepted |
| 增强组件 | `@nutui/nutui-react-taro`，经项目组件层封装 | Proposed；逐组件四端验证 |
| 网络 | `Taro.request` / `Taro.uploadFile` 的项目适配层 | Accepted |
| API 类型 | FastAPI OpenAPI + `openapi-typescript` | Accepted |
| 会话状态 | React Context + Session/Token Manager | Proposed |
| 页面状态 | React Hooks 本地状态 | Accepted |
| 包管理 | npm + `package-lock.json` | Accepted |
| 测试 | Jest + Taro React Test Utils | Proposed；Spike 验证 |
| Node | 24 LTS | Proposed；工程初始化时锁定补丁版本 |

不全局安装或依赖系统 Taro CLI。工程内 `@tarojs/cli` 和所有运行时包必须保持同一精确版本，命令通过 npm script 执行。

---

## 5. 总体架构

```text
Page (TSX + Taro lifecycle)
  │
  ├─→ Project Component ─→ Taro Components / verified NutUI component
  │
  └─→ Feature Hook / Use Case
         │
         ├─→ Endpoint API ─→ HTTP Client ─→ Taro.request/uploadFile ─→ FastAPI
         │                        │
         │                        └─→ Session / Token Manager
         │
         └─→ Platform Port ─→ WeChat / Alipay / Douyin / H5 Adapter

FastAPI OpenAPI ─→ Generated TypeScript Types ─→ Endpoint API
```

核心原则：

- Page 负责页面生命周期、路由参数、用户交互和四态渲染；
- Component 负责展示与事件，不读取路由、不直接访问 API；
- Feature 负责编排前端用例，但不复制后端权威规则；
- Endpoint 负责把领域输入映射为具体 HTTP 请求；
- HTTP Client 负责跨端传输、信封、错误、Token 与重试边界；
- Platform Adapter 只封装不可消除的平台差异；
- Generated Types 只描述静态类型，运行时外部输入仍需 Guard。

---

## 6. 目标目录

```text
pinkdooHub/
├── app/                              # 现有 FastAPI 后端
├── tests/                            # 现有后端测试
├── scripts/
│   └── export_openapi.py             # 规划：从 FastAPI 导出 OpenAPI
├── docs/08_frontend/                 # 本文档组
└── miniapp/                          # Spike 批准后创建
    ├── config/                       # Taro 构建与环境配置
    ├── openapi/                      # OpenAPI 中间产物
    ├── src/
    │   ├── api/
    │   │   ├── generated/            # 生成类型，禁止手改
    │   │   ├── endpoints/            # 模块级薄 API
    │   │   ├── client.ts
    │   │   ├── errors.ts
    │   │   └── upload.ts
    │   ├── auth/                     # AuthContext、Session、Token Manager
    │   ├── components/               # 项目稳定组件边界
    │   ├── features/                 # auth/product/order/inventory/admin
    │   ├── hooks/                    # 经真实复用证明的通用 Hook
    │   ├── pages/                    # 主包页面
    │   ├── platform/                 # 跨端 Port 与 Adapter
    │   ├── shared/                   # 常量、Guard、Formatter、类型与存储
    │   ├── styles/                   # Token、Mixin、全局样式
    │   ├── subpackages/
    │   │   ├── order/
    │   │   └── admin/
    │   ├── app.config.ts
    │   ├── app.scss
    │   └── app.tsx
    └── tests/
        ├── unit/
        ├── components/
        ├── contract/
        └── e2e/
```

目录按职责划分，不要求为空目录占位。只有某层出现第一份真实代码时才创建相应目录。

---

## 7. 分层职责与依赖规则

### 7.1 Page

允许：

- 读取 Taro 路由参数和页面生命周期；
- 调用 Feature Hook；
- 维护表单、选择、提交中和展示状态；
- 渲染 Loading、Empty、Error、Content；
- 导航和展示页面级反馈。

禁止：

- 直接调用 `Taro.request`、`Taro.uploadFile`；
- 直接读取或写 Token；
- 拼接 API URL 和 Authorization Header；
- 直接使用 `wx`、`my`、`tt`；
- 按 HTTP code 自行实现一套刷新逻辑；
- 重新判断权威库存、金额、权限和后端状态迁移。

### 7.2 Project Component

组件通过 Props 接收数据，通过事件回调暴露行为。组件不得：

- 读取页面路由；
- 依赖具体 Endpoint；
- 执行跨页面导航，除非组件职责就是项目导航；
- 修改外部对象；
- 在内部隐藏关键业务写操作。

NutUI 复杂组件优先封装为项目组件，例如 `AppDialog`、`AppUploader`，让业务页面不直接依赖第三方特有 Props。

### 7.3 Feature Hook / Use Case

Feature 负责客户端用例编排，例如：

- 根据有效 Experience Option 派生可选维度；
- 加载下一页并防止旧请求覆盖新结果；
- 把登录结果交给 Session；
- 构造严格 OrderCreate 输入；
- 为同一次 Inventory 调整保存稳定 Idempotency-Key。

Feature 可以做用户体验级前置校验，但服务端仍是最终权威。Feature 不得定义后端没有的状态迁移，也不得把前端缓存价格作为订单金额。

### 7.4 Endpoint API

每个模块用薄函数暴露明确用例：

```ts
login(request)
listProducts(query)
getExperienceProduct(productId)
createOrder(request)
cancelOrder(orderId)
adjustInventory(productId, request, idempotencyKey)
```

Endpoint 依赖生成类型和 HTTP Client，不依赖 React、页面或组件。

### 7.5 HTTP Client

统一负责：

- 环境 base URL；
- Query 编码；
- JSON 与 multipart；
- Bearer Header；
- HTTP 状态与项目响应信封；
- `1006` Token 过期刷新；
- 并发 single-flight refresh；
- 错误标准化；
- 可取消请求；
- 安全、受控的诊断上下文。

不默认重试写请求。尤其 `POST /orders` 当前没有客户端幂等键，超时不能自动再发一遍。

### 7.6 Platform

平台层定义 Port，再提供微信、支付宝、抖音和 H5 Adapter。仅当 Taro 无法完全统一能力时才新增平台分支。业务代码不得反向依赖某个平台实现。

### 7.7 Shared

`shared/` 只存放稳定、无领域归属或被多个 Feature 真实复用的内容。禁止把未决定归属的代码全部丢进 `utils/`。

---

## 8. 状态管理

按状态所有权选择最小工具：

| 状态 | 所有者 | 方案 |
|------|--------|------|
| 登录用户与会话 | 应用级 | AuthContext + Session/Token Manager |
| 页面表单 | 页面 | `useState` / `useReducer`（复杂时） |
| 服务端列表/详情 | 页面 Feature | 请求 Hook + 明确 Loading/Error/Data |
| 路由参数 | 路由 | Taro Router 参数，进入页面后严格解析 |
| 本地购物车 | Order Feature | 独立 Store/Service + Taro Storage Adapter |
| 平台信息 | Platform Adapter | 只读查询或小范围缓存 |

首版不引入 Redux、Zustand 或服务端缓存框架。出现以下证据之一时再写 ADR：

- 多个非父子页面频繁修改同一复杂状态；
- Context 更新造成已测量的广泛重渲染；
- 服务端缓存、失效和并发请求逻辑显著重复；
- 手写状态流已经难以测试或发生多次真实缺陷。

---

## 9. API、数据与运行时边界

详细规则见 [API 集成契约](api_integration_contract.md)。本节只保留架构级原则：

1. 生成类型不是运行时验证；来自网络、路由和 Storage 的值均视为 `unknown`。
2. 金额保持普通十进制字符串，UI 不使用浮点数生成权威金额。
3. UTC 时间解析后按用户时区显示；发送管理时间筛选时转换为 UTC。
4. `{value, label}` 中业务判断使用 `value`，展示优先使用 `label`。
5. 用户端 Product 库存只用于展示；下单结果以服务端锁后校验为准。
6. 写接口失败不得无条件乐观成功；未知执行结果必须保守处理。
7. Product/Order/Inventory 的业务错误结构不得被通用错误层抹平。

---

## 10. 认证与授权

### 10.1 MVP

MVP 使用现有用户名密码和 Bearer JWT：

- access token：短期请求凭据；
- refresh token：换取新 access token；
- user：AuthContext 的安全公开字段；
- expiresAt：由登录响应 `expires_in` 和客户端时钟计算。

Token Manager 必须处理当前后端的特殊契约：无凭据为 HTTP 401；无效或过期 Token 当前为 HTTP 400 + code `1006`。多个并发请求遇到 `1006` 时只能共享一次 refresh。

### 10.2 平台登录

正式公开发布前增加微信登录。平台临时 code 只传后端，AppSecret 只存在后端。考虑未来支付宝与抖音身份，后端应评估通用 `ExternalIdentity`，而不是不断向 User 添加平台专属字段。

### 10.3 授权

- 隐藏 ADMIN 入口只改善体验，不构成授权；
- 所有管理 API 仍由后端 ADMIN+ 依赖校验；
- 普通用户得到 403 时不得误判为 Token 过期；
- 路由守卫不能替代服务端资源可见性与权限判断。

认证和支付分阶段理由见 [ADR-006](adr/ADR-006-auth-and-payment-roadmap.md)。

---

## 11. 错误模型

前端统一错误至少区分：

```text
AppError
├── NetworkError             # 未收到 HTTP 响应
├── TimeoutError             # 请求超时
├── HttpError                # 非预期 HTTP/非项目信封
├── BusinessError            # 后端稳定业务 code
├── ValidationError          # HTTP 422 data.errors
├── AuthenticationError      # 缺失/刷新失败/1006
├── AuthorizationError       # HTTP 403
└── ContractError            # 响应不符合最低运行时形状
```

错误适配层保留：

- HTTP status；
- 业务 code；
- 安全 message；
- 允许公开的结构化 data；
- 可用于定位但不包含敏感值的 endpoint/operation。

禁止：

- 将密码、Token、幂等键写进 error message；
- 把所有非 0 code 都改成同一句错误；
- 按业务 code 数字段推断 HTTP 语义；
- 对非幂等写入自动重试。

---

## 12. 跨端 UI 与样式

### 12.1 组件层级

```text
Taro standard component
        ↓
verified NutUI component（可选）
        ↓
project component boundary
        ↓
business page
```

### 12.2 样式规则

- 使用 SCSS Token 管理颜色、间距、字号、圆角和层级；
- 避免依赖只在浏览器成立的 DOM/CSS 行为；
- 不在业务逻辑中读取布局结果来决定权威业务状态；
- 样式类遵循简单稳定的命名，不首发 CSS-in-JS；
- 响应式以移动端为基线，H5 明确最大内容宽度和安全区；
- 平台差异样式使用受控的平台文件或构建条件，不复制整页。

NutUI 的使用是否扩大，取决于 [ADR-005](adr/ADR-005-cross-platform-ui-strategy.md) 定义的 Spike。

---

## 13. 性能策略

性能优化必须基于测量，不以习惯性 `useMemo`/`useCallback` 代替测量。

首版要求：

- Product/Order/Inventory 列表保持后端分页；
- 搜索防抖并防止旧响应覆盖新查询；
- Order 与 Admin 使用分包；H5 接受 Taro 将分包合并的行为；
- 第三方组件按需引入；
- 图片使用合适尺寸、懒加载和失败占位；
- 避免把完整详情对象复制到多个全局状态；
- 组件列表使用稳定 key；
- 构建阶段记录各平台包体积并设置发布门槛；
- 不在渲染函数中执行 I/O 或昂贵、不可缓存的副作用。

---

## 14. 安全与隐私

1. AppSecret、JWT Secret、数据库凭据只能在服务端环境。
2. access/refresh token、密码、完整手机号不得进入日志、快照和错误监控。
3. H5 使用 Bearer Storage 的 XSS 风险必须在公开发布前专项 Review；生产配置 CSP，禁止未审查 HTML 注入。
4. H5 需要严格 CORS allowlist，不能因为开发方便开放生产通配符。
5. 文件上传的客户端检查只改善体验，服务端大小、MIME、内容和路径校验仍是权威。
6. 前端角色入口不是安全边界，后端权限不可绕过。
7. 微信登录临时 code 和支付结果不能由客户端自证；服务端负责换取身份、签名、验签和回调幂等。
8. Store 中的外部数据在使用前运行最低必要 Guard。

---

## 15. 构建、环境与发布

### 15.1 运行环境与构建平台是两个维度

运行环境：

```text
development / testing / production
```

构建平台：

```text
weapp / alipay / tt / h5
```

配置必须同时明确两者，禁止只用一个模糊的 `ENV` 变量承载全部含义。

### 15.2 预期命令

```text
npm run dev:weapp
npm run dev:alipay
npm run dev:tt
npm run dev:h5
npm run build:weapp
npm run build:alipay
npm run build:tt
npm run build:h5
```

具体 script 在 Spike 中验证后写入正式工程。

### 15.3 秘密与项目配置

- 可公开 AppID 与平台项目配置按平台文件管理；
- 开发者个人路径、私有配置和任何 secret 不提交；
- H5 API Origin、各小程序合法域名和图片域名由环境配置；
- 生产构建不得回退到 localhost 或 HTTP。

---

## 16. 测试与发布门槛

具体矩阵见 [测试策略](testing_strategy.md)。架构级门槛：

1. TypeScript、Lint、Format、单元和组件测试通过；
2. OpenAPI 类型重新生成无未提交漂移；
3. 微信、支付宝、抖音、H5 四端生产构建通过；
4. 首发微信与同步 H5 完成核心 Functional；
5. 支付宝和抖音至少完成 Build + Smoke，不允许长期完全不可编译；
6. 涉及后端变更时运行相关测试及完整 `pytest tests/ -q`；
7. 正式发布前完成真机、域名、HTTPS、隐私、安全和数据库迁移门槛。

---

## 17. 实施顺序

```text
架构文档 Draft
  → 文档 Review
  → 临时 Taro 四端 Spike
  → 回写结果并接受/否决 Proposed ADR
  → 正式 miniapp 脚手架
  → OpenAPI + HTTP Client
  → 账号登录纵向链路
  → 商品浏览纵向链路
  → 用户订单纵向链路
  → ADMIN 分包
  → 微信登录与支付等公开发布门槛
```

Spike 只验证技术风险，不实现业务功能，也不作为正式工程复制大量未经 Review 的实验代码。

---

## 18. 架构变更流程

以下变化必须新增或更新 ADR，并同步本文档：

- Taro、React 主版本变化；
- Webpack 5 切换 Vite；
- 引入全局状态或服务端缓存框架；
- 更换跨端 UI 组件库；
- 前端拆成独立仓库；
- 新增 `admin-web/`；
- 改变认证凭据存储/传输方式；
- 新增支付 Provider；
- 改变 OpenAPI 类型生成策略；
- 引入平台原生页面或大量不可共享代码。

文档状态从 Draft 变为 Approved 前，必须完成：

- [ ] 六个初始 ADR 已 Review；
- [ ] 四端空应用可构建；
- [ ] `Taro.request`/上传最小验证完成；
- [ ] 候选 UI 基础组件四端验证完成；
- [ ] Jest + Taro React Test Utils 验证完成；
- [ ] H5 与 FastAPI CORS 风险验证完成；
- [ ] Spike 结果已回写；
- [ ] 不存在与实际后端/OpenAPI 冲突的描述。
