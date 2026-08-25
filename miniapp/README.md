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

## 当前认证、Product、用户侧与 ADMIN Order 链路

- `src/api/endpoints/auth.ts`：login/refresh/logout/getMe 与响应 Runtime Guard；
- `src/platform/storage.ts`：跨端 Storage Port 和 Taro Adapter；
- `src/auth/session.ts`：Token 内存状态、版本化持久化、过期时间和并发 refresh；
- `src/auth/context.tsx`：启动恢复、`/users/me` 验证及全局认证状态；
- `src/pages/login/`：受控账号密码表单；公开首页按认证状态展示登录、昵称或登出，游客不再被强制跳转；
- `src/api/endpoints/products.ts`：公开 Product 列表生成类型、运行时 Guard 与白名单投影；
- `src/features/product/`：第一页/下一页、Loading/Empty/Error/Content 和迟到响应隔离；
- `src/utils/asset_url.ts`：绝对图片 URL 保留、`/uploads/...` 相对 API Origin 补全；
- `src/pages/index/`：公开商品卡片、Experience 起价、Kit 固定价格、图片失败占位和分页按钮。
- `src/features/order/cart.ts`：Experience/Kit 判别联合、版本化本地购物车、串行持久化和 Order Item 最小映射；
- `src/features/order/context.tsx`：游客/登录用户共享的 CartProvider，不与 Auth Session 混存；
- `src/api/endpoints/orders.ts`：严格的用户/ADMIN Order 请求投影、认证调用，以及 Detail/Page/Status Runtime Guard；
- `src/features/order/submission.ts`：一次提交快照、重复点击合并、失败/结果未知区分，以及成功后的保守 Cart 对账；
- `src/features/order/use_order_list.ts`：状态筛选、服务端分页、重复加载保护和迟到响应隔离；
- `src/features/order/use_order_detail.ts`：owner-only 详情读取、Pending empty-body cancel、unknown/40921 状态收敛和成功后重拉；
- `src/features/order/use_admin_order_list.ts`：ADMIN 完整筛选、服务端分页、重复加载保护和迟到响应隔离；
- `src/features/order/use_admin_order_detail.ts`：Pending → Paid、Paid → Completed 的唯一命令派生，以及 unknown/40921/成功后重拉收敛；
- `src/auth/login_route.ts`：只允许已注册确认页、用户订单列表或管理订单列表的固定登录回跳，拒绝动态详情、外部或任意内部地址；
- `src/pages/product-detail/`：把当前真实 Experience Option 或 Kit 加入购物车；
- `src/pages/cart/`：购物车恢复四态、预览字段、数量修改、移除和进入确认页；
- `src/pages/order-confirm/`：登录守卫、受控备注、确认提交、权威下单结果与未知结果核对入口；
- `src/pages/orders/`：当前账号订单列表、状态筛选、分页和详情入口；
- `src/pages/order-detail/`：服务端历史快照、Pending 取消确认及结果反馈。
- `src/admin/pages/orders/`、`src/admin/pages/order-detail/`：ADMIN 分包的完整筛选、管理详情和人工 Paid/Completed；普通用户在挂载管理请求前被拦截，后端 ADMIN+ 仍负责最终授权。

本地联调时先启动 FastAPI，再执行 `npm run dev:weapp`，用微信开发者工具导入仓库的 `miniapp/`（`miniprogramRoot` 已指向 `dist/weapp`）。开发环境 Origin 默认是 `http://localhost:8000`；开发者工具需按本地调试策略处理合法域名校验，真机不能把电脑的 `localhost` 当成后端。H5 真实跨域联调仍需后端配置严格 CORS allowlist。

认证缓存只保存 Token、过期时间和公开 User，密码不会持久化；不要用真实生产密码做本地测试，也不要打印 Storage 或完整 Token。

Product 列表接口无需登录。若本地数据库没有完整且已上架的 Product，首页会正确显示 Empty。日常业务操作应通过现有 ADMIN Product API 配置并上架数据；本地 Functional 也可使用严格限定为 development + 仓库内 SQLite 的 Seed 脚本，执行条件和命令见[阶段 6 列表学习笔记](../docs/08_frontend/learning_notes/phase6_product_list.md)。Seed 会让 `[LOCAL-FE] 拼豆材料包 01` 初始库存为 8，其余 5 条 Kit 保持 0；库存通过正式 Inventory Service、流水和审计写入。不要直接修改数据库绕过 Product readiness 或 Inventory 一致性规则。

## 目录约定（随阶段逐步落地）

- `src/pages/`：页面（TSX + 页面配置）。
- `src/admin/pages/`：`admin` 分包的 ADMIN+ 页面。
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
- 判别联合让 Experience 在类型层必须带真实 Option、Kit 必须为 null；Storage 的 unknown 数据仍需运行时校验；
- 本地购物车与服务端 Order 不是同一事实：名称、配置和价格只用于预览，下单请求只发送 Product/Option/quantity；
- 异步 Storage 也会发生竞态，mutation 串行化可避免快速点击的 lost update；写入成功后再发布 UI 可避免伪成功；
- 当前 Cart 是设备级游客缓存，登录/退出保留；登录后通过白名单路由返回确认页；
- Order create 没有客户端幂等键：提交中复用同一个 Promise，超时/断网进入“结果未知”且不自动重发；
- 成功页只显示后端订单快照；Cart 对账失败只提示本地清理问题，不能把已经创建的订单降级为失败。
- 列表分页事实来自服务端 `page/pages/total`；筛选请求用 sequence 隔离迟到响应，不能把不同筛选结果混合；
- 订单详情展示历史 Item 快照，不用当前 Product 覆盖；40411 不区分不存在和他人订单；
- cancel 是无 body PATCH，只对 Pending 开放；结果未知不自动重发，成功或 40921 后重新读取服务端状态。
- ADMIN Order 只允许 Pending → Paid 与 Paid → Completed；两个 PATCH 都无 body，Paid/Complete 不改变库存；页面角色守卫和分包都不能替代后端 ADMIN+ 授权。
- 管理结束日期按“包含当日”输入时转换为次日 UTC 零点，匹配 FastAPI `created_to` 排他上界。
