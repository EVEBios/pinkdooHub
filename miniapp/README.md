# miniapp —— pinkdooHub 跨端客户端

> 正式前端工程（Taro 4.2.1 + React 18.3.1 + TypeScript strict + Webpack 5.91.0）。
> 首发微信小程序，同步验证 H5；6–12 个月目标扩展支付宝与抖音小程序。
> 架构与决策见 [`docs/08_frontend/`](../docs/08_frontend/)，配置结论继承自四端 Spike。

## 常用命令

```bash
npm install            # .npmrc 已固化 legacy-peer-deps
npm ci                 # 按 package-lock.json 干净复现依赖（CI/验收优先）
npm run typecheck      # tsc --noEmit（strict + skipLibCheck）
npm test               # jest（runInBand）
npm run lint           # eslint src
npm run lint:styles    # stylelint CSS/SCSS
npm run api:types      # 从 openapi/openapi.json 生成只读 TypeScript 类型
npm run api:types:check # 检查生成类型是否最新
npm run build:weapp    # 生产构建 → dist/weapp
npm run build:alipay   # 生产构建 → dist/alipay
npm run build:tt       # 生产构建 → dist/tt
npm run build:h5       # 生产构建 → dist/h5
npm run dev:weapp      # 开发构建（watch，加载 .env.development）
```

## 环境变量

- `TARO_APP_APP_ENV`：development / testing / production（`.env.*` 按构建模式加载）。
- `TARO_APP_API_ORIGIN`：后端 API Origin；生产构建禁止 HTTP/localhost。
- `TARO_ENV`：weapp / alipay / tt / h5，由 Taro 构建时注入。

环境变量必须通过 `src/config/env.ts` 的 `resolveEnv()` 读取；不要在其他位置直接散落
`process.env.TARO_APP_*`（Taro 只替换字面量形式的访问）。

生产环境只接受不含路径/凭据的 HTTPS Origin，并拒绝 localhost、127.0.0.1、
0.0.0.0 与 `[::1]`。`.env.production` 当前是不可发布的占位域名，部署前必须替换。

## OpenAPI 与 HTTP Client

后端 OpenAPI 是前端 API 类型的唯一来源。更新后端路由或 Schema 后执行：

```powershell
# 仓库根目录：使用后端虚拟环境导出稳定 OpenAPI JSON
.\.venv\Scripts\python.exe scripts\export_openapi.py

# miniapp/：重新生成并检查 TypeScript 类型
npm run api:types
npm run api:types:check
```

- `openapi/openapi.json`：由 FastAPI 导出的中间产物，禁止手工修改。
- `src/api/generated/schema.d.ts`：由 `openapi-typescript` 生成，禁止手工修改。
- `src/api/client.ts`：处理 Origin、Query、Bearer、响应信封和错误分类。
- `src/api/taro_transport.ts`：唯一直接调用 `Taro.request` 的 JSON Transport。
- `src/api/factory.ts`：组合环境配置、Transport 与可选 AuthSession。

HTTP Client 不默认重试写请求。只有后端已明确返回 Token 失效 code `1006` 时，
才通过共享 refresh Promise 刷新并重放一次；普通超时不会自动重新 POST/PATCH。

## 当前认证与 Product 链路

- `src/api/endpoints/auth.ts`：login/refresh/logout/getMe 与响应 Runtime Guard；
- `src/platform/storage.ts`：跨端 Storage Port 和 Taro Adapter；
- `src/auth/session.ts`：Token 内存状态、版本化持久化、过期时间和并发 refresh；
- `src/auth/context.tsx`：启动恢复、`/users/me` 验证及全局认证状态；
- `src/pages/login/`：受控账号密码表单；公开首页按认证状态展示登录、昵称或登出，游客不再被强制跳转；
- `src/api/endpoints/products.ts`：公开 Product 列表生成类型、运行时 Guard 与白名单投影；
- `src/features/product/`：第一页/下一页、Loading/Empty/Error/Content 和迟到响应隔离；
- `src/utils/asset_url.ts`：绝对图片 URL 保留、`/uploads/...` 相对 API Origin 补全；
- `src/pages/index/`：公开商品卡片、Experience 起价、Kit 固定价格、图片失败占位和分页按钮。

本地联调时先启动 FastAPI，再执行 `npm run dev:weapp`，用微信开发者工具导入仓库的 `miniapp/`（`miniprogramRoot` 已指向 `dist/weapp`）。开发环境 Origin 默认是 `http://localhost:8000`；开发者工具需按本地调试策略处理合法域名校验，真机不能把电脑的 `localhost` 当成后端。H5 真实跨域联调仍需后端配置严格 CORS allowlist。

认证缓存只保存 Token、过期时间和公开 User，密码不会持久化；不要用真实生产密码做本地测试，也不要打印 Storage 或完整 Token。

Product 列表接口无需登录。若本地数据库没有完整且已上架的 Product，首页会正确显示 Empty。日常业务操作应通过现有 ADMIN Product API 配置并上架数据；本地 Functional 也可使用严格限定为 development + 仓库内 SQLite 的 Seed 脚本，执行条件和命令见[阶段 6 列表学习笔记](../docs/08_frontend/learning_notes/phase6_product_list.md)。两种方式都会经过正式 Service/Validator；不要直接修改数据库绕过 readiness 规则。

## 目录约定（随阶段逐步落地）

- `src/pages/`：页面（TSX + 页面配置）。
- `src/components/`：项目共享组件。
- `src/api/`：生成类型、HTTP Client、Transport 与模块 Endpoint。
- `src/auth/`：认证 Context、Session Manager 与运行时组合。
- `src/features/`：页面业务用例和服务端状态，例如 Product 分页与请求竞态。
- `src/platform/`：Taro Storage 等平台能力适配。
- `src/config/`：环境与运行配置。
- `src/utils/`：无状态纯函数。

依赖方向：Page → Component/Feature → Service → HTTP Client → `Taro.request`。
页面禁止直接调用 `Taro.request` 或平台原生 API。

## 当前依赖风险

- 正式依赖树已通过 `npm ls --depth=0`；`solid-js@1.9.15` 用于补齐 Taro H5
  组件链在 `legacy-peer-deps` 模式下不会自动安装的 peer dependency。
- 未使用的百度/京东/QQ/鸿蒙/RN 平台插件、Generator、Husky/Commitlint 已移除；
  Git 提交仍遵循仓库 `AGENTS.md` 的 Conventional Commits 规则。
- 2026-08-20 使用官方 npm registry 审计时，生产依赖仍有 10 项来自 Taro 4.2.1
  上游链的报告（4 moderate、1 high、5 critical），主要涉及 H5 的 esbuild、
  lodash-es 和 swiper。Taro 4.2.1 当日仍是最新版，`audit fix --force` 会破坏性
  降级到 Taro 3.x，因此禁止执行；正式发布前必须重新审计并跟踪上游修复。

## 本阶段知识点

- `package.json` 描述允许安装的依赖范围，`package-lock.json` 冻结可复现依赖树；
- peer dependency 是宿主必须提供的兼容依赖，`legacy-peer-deps` 会跳过自动安装；
- OpenAPI 生成类型只在编译期生效，外部 JSON 仍必须做运行时信封校验；
- Transport 隔离平台网络 API，HTTP Client 负责协议，页面不处理 Token 和信封；
- `unknown` 要先校验再使用；超时与业务失败语义不同，写请求超时不能盲目重试；
- single-flight 用同一个 Promise 合并并发刷新，避免多个请求同时刷新 Token。
- 受控表单的输入值来自 React State；Context 只放跨页面共享的认证状态；
- Effect 用于启动恢复等副作用，缓存 User 必须经 `/users/me` 验证后才视为已认证；
- Port/Adapter 与依赖注入让 Storage、时钟和网络刷新在 Jest 中可替换；
- 数据库 `IntEnum` 和 HTTP 字符串 Enum 是不同表示，OpenAPI 必须描述真正的网络输出。
- Product Page 是服务端状态，使用互斥四态而不是多个可能矛盾的 boolean；
- 分页事实来自后端 `page/pages/total`，客户端不根据数组长度猜测总页数；
- 请求发出顺序不保证响应顺序，使用请求序号阻止迟到旧响应覆盖新数据；
- TypeScript DOM 类型不证明所有小程序运行时都支持同名 Web API，跨端 Feature 避免无验证地依赖 `AbortController`；
- Product 业务判断使用 Enum `value`，展示使用 `label`，金额保持服务端两位小数字符串。
