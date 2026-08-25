# pinkdooHub 前端架构

> **Document Version:** v0.5
> **Status:** Draft
> **Last Updated:** 2026-08-24
> **Scope:** 正式 `miniapp/` 架构；四端 Spike、工程基础、HTTP Client、Product、用户 Order 与首个 ADMIN 分包链路已落地
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

当前已完成最小技术 Spike、正式工程、OpenAPI/HTTP Client 基础、账号密码登录、公开 Product 列表/详情，以及 Phase 7.1–7.4 的本地 Cart、用户 Order 和 ADMIN Order 工程链路。认证、Product、Cart 与 Order 创建已通过微信开发者工具 Functional；用户查询/取消除 40921 双端竞态外均通过。ADMIN 列表/详情、完整筛选和人工 Pending → Paid → Completed 的自动化、后端回归与四端构建已通过，微信 Functional 待验证；H5 仍等待严格 CORS allowlist。

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
| 跨端框架 | Taro 4.2.1；所有 `@tarojs/*` 使用同一精确版本 | Accepted |
| UI 框架 | React 18.3.1（react-dom 同版本） | Accepted |
| 语言 | TypeScript strict | Accepted |
| 编译器 | Webpack 5.91.0 | Accepted（Spike 四端通过） |
| 样式 | SCSS（sass 1.102.0）+ 项目 Design Tokens | Accepted（工具链已验证；Tokens 待正式工程） |
| 基础组件 | `@tarojs/components` | Accepted |
| 增强组件 | `@nutui/nutui-react-taro` 2.7.15 候选，经项目组件层封装 | Deferred（Spike 通过但正式工程未安装；真实组件需要时再按 ADR-005 受控引入） |
| 网络 | `Taro.request` / `Taro.uploadFile` 的项目适配层 | Accepted |
| API 类型 | FastAPI OpenAPI + `openapi-typescript` 7.13.0 | Accepted（正式工程已落地） |
| 会话状态 | React Context + Session/Token Manager | Accepted / Implemented |
| 页面状态 | React Hooks 本地状态 | Accepted |
| 包管理 | npm + `package-lock.json` | Accepted |
| 测试 | Jest 29.7.0 + `@tarojs/test-utils-react` 0.1.1 + jsdom | Accepted（含已知 workaround，见 §4.1） |
| Node | 24 LTS（本机 24.13.0 已验证） | Accepted |

不全局安装或依赖系统 Taro CLI。工程内 `@tarojs/cli` 和所有运行时包必须保持同一精确版本，命令通过 npm script 执行。

### 4.1 Spike 结果摘要（2026-08-15）

临时工程位于仓库 `spikes/taro-four-end-spike/`（已被根 `.gitignore` 忽略，不进入版本控制），用于验证技术风险，不作为正式工程复制来源。验证结果：

**四端生产构建全部通过**（`taro build --type <weapp|alipay|tt|h5>`，Webpack 5.91.0）：

| 平台 | 构建 | 产物目录 | 体积（含 NutUI 桶导入 + 全量主题） |
|------|------|----------|----------------------------------|
| weapp | ✅ | `dist/weapp` | 543 KiB / 23 文件 |
| alipay | ✅ | `dist/alipay` | 492 KiB / 20 文件 |
| tt | ✅ | `dist/tt` | 487 KiB / 19 文件 |
| h5 | ✅ | `dist/h5` | 627 KiB（JS 413 + CSS 211） |

**环境变量注入规则（关键结论）**：Taro 通过 webpack DefinePlugin 只替换代码中“字面量”形式的 `process.env.TARO_APP_*` / `process.env.TARO_ENV`。环境读取模块必须直接书写这些字面量；经由参数/对象间接访问不会被注入，导致生产产物缺少配置。Spike 已按此修正 `resolveEnv()` 并通过产物字符串验证：四端生产包均注入 `TARO_APP_APP_ENV=production` 与占位 Origin，且不含 `localhost`。

**各平台输出目录**：默认 `outputRoot: 'dist'` 会让四端互相覆盖；Spike 固定为 `dist/<TARO_ENV>`（`config/index.ts` 按 `process.env.TARO_ENV` 拼接），微信开发者工具项目根指向 `dist/weapp`。

**H5 CORS 风险确认**：对 FastAPI 实测，`OPTIONS` 预检返回 405、GET 响应无 `Access-Control-Allow-Origin` 头——后端未配置 CORS 白名单，浏览器端 H5 跨域调用会被拦截。该缺口已记录于 [多端策略](multi_platform_strategy.md)，属于后端待办，不是前端可自行绕过的问题。

**测试工具链（Jest + Taro Test Utils）**：
- 必须 `--legacy-peer-deps`：`@tarojs/test-utils-react@0.1.1` 的 peerDependencies 仍声明 `@tarojs/* ^3.6.0`，与 Taro 4.2.1 冲突（`.npmrc` 已固化）。
- 官方 transformer 未启用私有方法/属性插件，会转译失败；Spike 提供自定义 `jest.transformer.js` 补齐。
- Taro 4.2.1 的 `@tarojs/router` 与 `@tarojs/components`（Stencil bundle）在 Jest 中经 taro-h5 runtime 形成循环依赖；组件测试需以工厂 mock `@tarojs/router`（`mount()` 不依赖 router）。
- `html()` 序列化 Stencil Web Component 的 shadow DOM 会递归爆栈；断言改用 `queries.querySelector*`。
- 运行时有 `ReactDOMTestUtils.act` 废弃告警（React 18.3 下 test-utils 内部 API），不阻断，升级测试工具时消除。

**TypeScript strict**：Taro 4.2.1 自带类型声明在 strict 下不干净（数千条 d.ts 错误），需 `skipLibCheck: true`（只跳过声明文件，应用代码仍严格检查）；模板生成的 `config/index.ts` 存在未用解构，需修正后才能 `tsc --noEmit` 通过。

**NutUI 体积（ADR-005 依据）**：2.7.15 没有按组件 JS 入口，`import { Button, Toast, Dialog, Input } from '@nutui/nutui-react-taro'` 会把整库打入包（构建日志可见 avatar/tour/sidenavbar 等全部模块）；全量主题 `default.scss` 使 h5 CSS 达 202 KiB。正式工程必须采用按需引入（babel-plugin-import 或等价方案）并重新测量门槛，否则违反架构性能目标。

**其余告警**：Sass `@import` 弃用告警来自 NutUI 主题内部（Dart Sass 3.0 将移除），正式工程需关注升级；h5 入口超过 webpack 244 KiB 建议线（485 KiB），与 NutUI 全量引入直接相关。

### 4.2 正式工程依赖复核与 API 基础层（2026-08-20）

- 正式 `miniapp/` 已用官方 npm registry 完成依赖收敛：清理 16 个未声明的 NutUI/React Spring 残留包，并显式安装 `solid-js@1.9.15`，补齐 `legacy-peer-deps` 模式跳过的 Taro H5 peer dependency；`npm ls --depth=0` 与生产依赖树均为零错误。
- 只保留规划中的 weapp/alipay/tt/h5 平台插件；百度、京东、QQ、鸿蒙、RN、已完成使命的 Taro Generator，以及未配置实际 Hook 的 Husky/Commitlint/Lint Staged 均移除，避免扩大安装面和安全审计面。
- `scripts/export_openapi.py` 从真实 `app.openapi()` 原子导出稳定 JSON；`openapi-typescript@7.13.0` 以 `--immutable --alphabetize` 生成 `miniapp/src/api/generated/schema.d.ts`，并提供 `--check` 漂移门槛。当前 Schema 为 45 条路径、99 个组件 Schema。
- 正式 HTTP Client 已实现环境 Origin、Query、JSON、Bearer、统一信封 Runtime Guard、Network/Timeout/HTTP/Business/Contract/Session 错误、取消、code `1006` single-flight refresh 以及一次受控重放；普通写请求和超时不自动重试，empty-body PATCH 不设置 data。
- 官方 registry 的 2026-08-20 审计仍报告 10 项生产依赖风险（4 moderate、1 high、5 critical），均位于 Taro 4.2.1 H5 上游链；Taro 4.2.1 当日仍为最新版，`audit fix --force` 会破坏性降级到 Taro 3.x，因此不执行。公开发布前必须重新审计并跟踪上游修复。
- 无 NutUI 的正式 H5 空应用入口仍为 281 KiB，超过 Webpack 244 KiB 建议线；这是当前 Taro H5 基线告警，后续每次引入 UI/业务依赖都必须重新测量，不能以“尚未引入 NutUI”为由忽略。

### 4.3 账号密码登录纵向链路（2026-08-20）

- 后端 auth/users 成功响应已补齐精确统一信封 OpenAPI；User 内部 `IntEnum` 仍按原方式存储，但序列化 Schema 明确为 HTTP 字符串 Enum。当前生成输入为 45 paths / 108 schemas。
- `api/endpoints/auth.ts` 消费生成请求/响应类型，同时对所有认证响应做运行时 Guard；Endpoint 不依赖 React。
- `platform/storage.ts` 定义 Storage Port，Taro Adapter 隔离平台 API；`auth/session.ts` 通过 storage、clock 和 refresh 函数注入保持可测试，只向 React 暴露不含 Token 的 Session Snapshot。
- `AuthProvider` 管理 `initializing/guest/authenticated/error`，恢复时先读缓存，必要时刷新，再调用 `/users/me` 验证；登录页为受控表单，公开 Product 首页按认证状态展示登录、昵称或退出，不再把游客强制重定向到登录页。
- 29 项 Jest、后端完整 SQLite 套件 1425 项（9 项可选 MySQL 跳过）、静态检查与四端生产构建通过。H5 入口增长至 327 KiB；微信开发者工具连接本地 FastAPI + SQLite + Redis 的错误/正确/禁用账号、三种角色、Storage、重启恢复、登出及三类 refresh Functional 已通过。该结果仍不代表真机、H5、正式 HTTPS/合法域名或微信登录通过。

### 4.4 公开 Product 列表纵向链路（2026-08-20）

- `api/endpoints/products.ts` 直接消费 OpenAPI 生成的 Query/Page/Product 类型，同时把网络数据视为 `unknown`，运行时校验并白名单重建分页项；ID、两位小数金额、Product 字符串 Enum、图片地址与分页字段不合约时抛 `ContractError`。
- `features/product/use_product_list.ts` 拥有服务端列表状态：首屏固定 10 条、按服务端 `page/pages/total` 追加下一页、首屏/下一页分别处理错误，并用请求序号阻止迟到旧响应覆盖新结果。共享逻辑不依赖 `AbortController` 等不保证存在于所有小程序运行时的浏览器全局对象。
- `utils/asset_url.ts` 是开发期相对图片路径的唯一解析点：HTTP(S) URL 原样保留，`/uploads/...` 相对 API Origin，其他路径拒绝。首页 ProductCard 使用图片懒加载和失败占位。
- 首页现在是公开 Product 入口，明确渲染 Loading/Empty/Error/Content 四态；Experience 依据 `product_type.value` 展示“起”，Kit 展示固定价格。认证状态只影响账号操作，不阻断游客 Product 请求。
- Product 新增 Endpoint、Resolver、Feature 和 Page 测试；Jest setup 集中处理 Taro router 循环依赖及 jsdom `IntersectionObserver`。阶段 6 最终门禁为完整 Jest 11 套件 / 70 项、后端 SQLite 1442 项、TypeScript、ESLint、Stylelint、OpenAPI 漂移检查与四端生产构建通过。2026-08-22 微信开发者工具已通过游客、Content、相对图片、第二页、筛选/组合搜索、Empty、Error 恢复、登录/退出后继续浏览、Experience/Kit 详情及真实多配置 Option 切换。

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
    │   ├── admin/pages/              # ADMIN 分包页面
    │   ├── platform/                 # 跨端 Port 与 Adapter
    │   ├── shared/                   # 常量、Guard、Formatter、类型与存储
    │   ├── styles/                   # Token、Mixin、全局样式
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
| Order 创建提交 | Order Feature | 判别状态机 + 不可变提交快照 |
| Order 列表/详情 | Order Feature | 请求 Hook + sequence 迟到响应隔离 |
| Order 取消命令 | Order Feature | 判别状态机 + 进行中 Promise 合并 + 服务端重拉 |
| 平台信息 | Platform Adapter | 只读查询或小范围缓存 |

### 8.1 本地购物车已实现边界

Phase 7.1 使用应用级 `CartProvider` 注入可独立测试的 `CartStore`，没有引入 Redux/Zustand：

- `CartItem` 是 Experience/Kit 判别联合；Experience Option 为正整数，Kit Option 固定 null；
- 唯一身份与后端一致，为 `(productId, experienceOptionId)`；相同组合合并 quantity，不同 Option 保持独立；
- Storage key 为 `pinkdoohub.cart.v1`，所有恢复输入从 unknown 开始校验；版本、字段、组合或边界无效时清除整份坏缓存；
- 合法缓存也按白名单重写，不保存 Token、User、密码、remark 或订单状态；
- 购物车是设备级游客状态，登录/退出不自动清除；确认和创建订单时才要求有效认证；
- mutation 通过 Promise 队列串行化，并采用“Storage 成功后再发布 React 状态”的保守更新，避免快速点击丢失数量或写失败伪成功；
- 本地名称、配置、图片和价格只用于预览；Order 请求只投影 Product ID、真实 Option ID 和 quantity。

### 8.2 Order 创建已实现边界

Phase 7.2 在 Cart、Auth 和 HTTP Client 之间新增一个可独立测试的提交用例，而不是把协议判断放进页面：

- `OrderApi.createOrder()` 只负责认证 POST、请求白名单投影和 `unknown` 响应 Runtime Guard；
- `OrderSubmissionStore` 使用 `idle/submitting/succeeded/failed/unknown` 判别联合，开始时冻结 Cart/request 快照，同一进行中操作只发出一次 POST；
- network/timeout/cancel、成功响应契约损坏和 HTTP 5xx 都无法证明服务端事务未提交，进入 unknown 且不自动重试；明确业务/认证/非 5xx 拒绝与结果未知是不同状态；
- Guest 通过固定白名单 redirect 登录，登录成功 `reLaunch` 回确认页；外部 URL、未注册页面和畸形编码都回退首页；
- 成功页只渲染后端 Order/Item 金额和 Option 快照，不混入本地 Cart 预览字段；
- 成功后的 Cart 对账复用 mutation 队列并先持久化再发布。相同数量移除、增量重新加入保留差额、无法安全推断时保留并提示；清理失败不改变服务端成功状态；
- 成功状态的渲染优先级高于 Cart empty，因为对账可能先发布空 Cart，再发布 `succeeded`。这是事件顺序边界，不应通过延迟或伪造本地订单规避。

### 8.3 Order 查询与取消已实现边界

Phase 7.3 把 7.2 的创建结果和 unknown 恢复接到服务端权威查询：

- `OrderApi` 对列表 Query 做白名单投影，对 Page/ListItem/Detail/Status 响应从 unknown 开始校验；列表和详情均要求认证；
- 列表 Hook 固定 `page_size=20`，使用服务端 `page/pages/total`，支持状态筛选、下一页、重复加载保护和 sequence 迟到响应隔离；
- 详情路由只接受正安全整数，页面只消费 Order Item 历史快照；owner-only 由后端保证，40411 不区分不存在与他人资源；
- Pending cancel 使用 empty-body PATCH 和 `idle/submitting/failed/unknown/succeeded` 状态机，同一进行中操作复用 Promise；
- network/timeout/cancel、5xx 或成功响应契约损坏进入 unknown，不自动重发；成功后 GET 详情，刷新失败不推翻已确认成功；40921 后也尝试 GET，以服务端状态收敛跨端竞态；
- 页面不模拟 Inventory 恢复。Kit 库存、流水、Audit 与 Order 状态由后端同一事务维护。

### 8.4 ADMIN Order 已实现边界

Phase 7.4 在同一应用中落地首个 `admin` 分包，但不把分包或缓存角色误作授权：

- `app.config.ts` 用 `root: admin` 注册管理列表和详情；首页只为 `admin/super_admin` 显示入口，普通用户在挂载管理 Hook 前被拦截；FastAPI ADMIN+ dependency 仍是唯一授权事实；
- 登录回跳只允许固定管理列表，不允许动态详情进入 redirect 白名单；详情 ID 仍从不可信路由参数校验；
- ADMIN 列表 Query 只包含冻结的 7 个字段。筛选草稿与已提交查询分离，结束日期转换为次日 UTC 零点，以满足后端排他 `created_to`；
- ADMIN 响应 Guard 在用户订单字段之外只接收 `user_id/user_nickname`，不允许用户隐私或内部字段穿过 Endpoint；
- 详情从服务端状态派生唯一命令：Pending → Paid、Paid → Completed，两个终态无按钮，不提供任意状态编辑器；
- paid/complete 使用 empty-body PATCH、进行中 Promise 合并和 `failed/unknown/succeeded` 收敛。成功或 40921 后 GET 权威详情；unknown 不自动重发；
- paid/complete 不触碰 Inventory。客户端不更新库存、流水或审计，只读取 Order 状态结果。

后端提供 Order create 客户端幂等键之前，UI 防抖和 Promise 合并都不能替代服务端幂等。首版仍不引入 Redux、Zustand 或服务端缓存框架。出现以下证据之一时再写 ADR：

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

这些 script 已写入正式工程 `miniapp/package.json` 并在四端执行通过。

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
  → 账号登录纵向链路（已完成）
  → 商品浏览纵向链路（已完成）
  → 用户订单纵向链路（7.1–7.3 已完成）
  → ADMIN Order 分包纵向链路（7.4 已完成工程实现）
  → 后续 ADMIN 最小能力（按需求逐项冻结）
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

- [x] 六个初始 ADR 已 Review（2026-08-15 Spike 后更新，ADR-003/ADR-005 已接受）；
- [x] 四端空应用可构建（`spikes/taro-four-end-spike`，weapp/alipay/tt/h5 生产构建通过）；
- [x] `Taro.request`/上传最小验证完成（HTTP Client 单测覆盖成功/业务/HTTP/网络/契约错误，`uploadFile` 信封解析已验证）；
- [x] 候选 UI 基础组件四端验证完成（Button/Toast/Dialog/Input 四端编译通过，受控用法有测试）；
- [x] Jest + Taro React Test Utils 验证完成（12+ 测试通过，含已知 workaround）；
- [x] H5 与 FastAPI CORS 风险验证完成（确认后端未配置 CORS，缺口已记录）；
- [x] Spike 结果已回写（本文档 §4.1、ADR-003/ADR-005、多端/测试策略）；
- [x] 不存在与实际后端/OpenAPI 冲突的描述。

剩余发布门槛（不属于 Spike，属于正式工程与发布阶段）：微信/H5 Functional、支付宝/抖音 Smoke、真机与弱网、合法域名/HTTPS/CORS 白名单落地、包体积按需优化、OpenAPI 类型生成与漂移检查。
