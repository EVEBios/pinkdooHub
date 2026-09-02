# Phase 5 学习笔记：账号密码登录纵向链路

> **Date:** 2026-08-20
>
> **Status:** 代码、自动化、四端构建与微信开发者工具账号密码 Functional 已完成
>
> **对应代码:** `miniapp/src/api/endpoints/auth.ts`、`miniapp/src/auth/`、`miniapp/src/platform/storage.ts`、`miniapp/src/pages/login/`

这一步不是只做一个“能点的登录按钮”，而是把一次用户动作贯穿 Page → Context → Endpoint → HTTP Client → FastAPI，再把响应安全地送回全局会话和页面。学习目标是看懂每层为什么存在，以及哪些事实不能只靠 TypeScript 保证。

## 1. 完整调用链

```text
登录页受控表单
  → AuthContext.login(username, password)
  → AuthApi.login(LoginRequest)
  → ApiClient（Origin、信封、错误）
  → TaroHttpTransport / Taro.request
  → FastAPI POST /api/v1/auth/login
  → Runtime Guard 校验 TokenOut
  → SessionManager 写内存与 Taro Storage
  → AuthContext 进入 authenticated
  → 首页展示公开 User
```

退出方向相反：页面调用 Context，Endpoint 请求后端撤销 refresh session，随后无论网络结果如何都清除本机内存和 Storage。若服务端结果未确认，页面明确提示，而不是假装远端一定成功。

## 2. TypeScript：生成类型不等于运行时证明

`LoginRequest`、`TokenOut` 和 `UserOut` 来自 FastAPI OpenAPI。它们让编辑器在编译期发现字段拼错、漏填和 null 处理错误，但服务端 JSON、代理错误页或损坏 Storage 在运行时仍是 `unknown`。

因此 Endpoint 的顺序是：

1. 先把网络 `data` 当作 `unknown`；
2. 用 Parser 检查实际字段；
3. 校验通过后重新构造白名单对象，丢弃包括潜在 `password` 在内的额外字段；
4. Parser 返回生成类型，失败则抛 `ContractError`，不让坏数据进入 Session。

需要记住：`as LoginResult` 只是在告诉编译器“相信我”，不会在 JavaScript 运行时生成任何检查；仅返回原对象的布尔 Guard 也不等于安全投影。

## 3. 同一个概念可以有不同边界表示

User 的 role/status 在数据库和 Python 领域内部使用 `IntEnum`，例如 1/2/3；HTTP 实际输出则是 `"user" / "admin" / "super_admin"`。原 OpenAPI 描述成数字，导致生成类型与真实 JSON 冲突。

本次通过 Pydantic serialization schema 明确输出字符串 Enum，并用 OpenAPI 测试固定。知识点是：数据库表示、领域表示和传输表示可以不同，但每次跨边界都必须有明确映射，不能让前端猜。

## 4. React 受控表单与 State

用户名、密码、提交中和错误提示分别由 `useState` 保存。`Input.value` 来自 State，`onInput` 再更新 State，这叫受控组件。

好处：

- 提交时拿到的是明确的当前值；
- 可以统一做必填校验，同时按当前后端契约原样提交用户名，不擅自改写凭据；
- `submitting` 可禁用按钮，防止连续提交；
- 登录失败后可主动清空密码；
- UI 是 State 的函数，比较容易测试。

不要直接修改 State，也不要在 render 过程中发请求。网络请求属于用户事件或 Effect 中的副作用。

## 5. Context 解决什么，不解决什么

登录用户会被多个页面读取，所以属于应用级状态，适合放在 AuthContext。用户名输入框只属于登录页，因此仍留在页面本地 State。

Context 当前只暴露：认证状态、公开 User、login/logout/retry 方法，不暴露 access token 或 refresh token。Token 由 SessionManager 和 HTTP Client 管理，页面没有理由读取它。

Context 不是“所有数据的全局仓库”。后续 Product 列表、筛选和页面 loading 不应因为方便就全部塞进 AuthContext。

## 6. Effect、依赖数组与清理

AuthProvider 的 Effect 负责应用启动后的会话恢复，因为读取 Storage、刷新 Token、调用 `/users/me` 都是外部副作用。

恢复顺序是：

```text
Storage unknown
  → 校验版本与字段
  → access token 临近过期则 refresh
  → GET /users/me 验证服务端身份
  → authenticated
```

缓存 User 不是授权证据。即使本地写着 `role=admin`，后端仍必须校验 Token、当前用户和每个 ADMIN API 权限。Effect 使用 active 标记和清理函数，避免组件卸载后继续写 React State。

依赖数组不是“随便填到不报警”。Effect 中用到且可能变化的 runtime/attempt 必须进入依赖；事件函数用 `useCallback` 稳定；组合 Context value 用 `useMemo`，避免无意义的新对象。

## 7. 判别状态比多个布尔值更安全

认证状态使用一个联合值：

```text
initializing | guest | authenticated | error
```

这比 `isLoading/isLoggedIn/hasError` 三个布尔值更难出现矛盾组合，例如同时 loading、logged in 和 error。页面根据一个状态选择互斥界面：恢复中、去登录、显示内容或重试。

## 8. Storage Port、Adapter 与依赖注入

`SessionManager` 不直接调用 Taro。它只依赖 `StoragePort`、Clock 和 refresh 函数；真正的 Taro API 放在 `TaroStorageAdapter`。

这样做的直接收益不是“架构更漂亮”，而是测试可以注入：

- MemoryStorage：不写真实设备；
- 固定 Clock：精确断言 `expiresAt`；
- fake refresh：验证并发三次只发一次请求。

Port 是业务层需要的最小能力接口，Adapter 是某个平台的具体实现。这是依赖注入最基础、最实用的形式，不需要先引入大型 IoC 框架。

## 9. Token 生命周期与安全边界

- access token：每次受保护请求使用，生命周期较短；
- refresh token：换取新 access token，当前后端暂不轮换；
- expiresAt：客户端用 `Date.now() + expires_in * 1000` 计算，提前 30 秒视为到期；
- password：只存在于受控输入和本次登录请求，不进入 Session/Storage/日志；
- User：可以缓存用于恢复体验，但必须经服务端重新验证。

Taro Storage 不是硬件安全区；H5 下最终通常落到浏览器存储，更要防 XSS。前端不能保存 AppSecret、JWT Secret，也不能通过“加密后写本地”创造真正安全的密钥管理。正式发布还需要 HTTPS、合法域名、后端撤销、refresh 轮换/限流和安全 Review。

## 10. Single-flight 为什么有两层关注点

HTTP Client 已把多个同时收到 code `1006` 的请求合并到一个 refresh Promise。SessionManager 自身也防止重复 refresh，保证启动恢复或未来其他调用方不会并发更新同一会话。

这里学习的是 Promise 可以代表“正在进行的共享工作”：保存当前 Promise，其他调用方 await 它，结束后在 `finally` 中只清理自己创建的那一个引用。

## 11. 本次测试分别防什么

| 测试 | 防止的回归 |
|------|------------|
| 后端 OpenAPI 引用测试 | 登录成功响应退回 `unknown` |
| User Enum 输出测试 | 把数据库数字错误生成给前端 |
| AuthApi fake transport | 路径、Method、Bearer 或 body 拼错 |
| Endpoint Runtime Guard | 缺字段 Token/User 被写入会话 |
| MemoryStorage + fixed clock | 密码误存、过期单位算错、坏缓存不清 |
| 三并发 refresh | 重复刷新和竞争覆盖 Token |
| 表单错误映射 | 暴露“账号是否存在”的差异提示 |
| 页面组件测试 | 登录用户首页基本渲染回归 |
| 四端 Build | 使用了某一平台无法编译的 API/组件 |

Build 通过只证明“能编译”，不证明请求域名、CORS、Redis、Token 撤销和页面交互在真实环境可用，所以开发者工具 Functional 仍是独立门槛。本阶段已执行该门槛，结果见下一节。

## 12. 微信开发者工具 Functional 结果

2026-08-20 在微信开发者工具中，以本地 FastAPI、SQLite 开发库和 Redis 容器执行账号密码认证纵向链路，以下场景全部通过：

| 场景 | 观察结果 | 验证的边界 |
|------|----------|------------|
| 错误用户名/密码 | 统一显示“用户名或密码错误” | Taro Transport、业务信封和错误码映射 |
| `user/admin/super_admin` 正确登录 | 首页显示对应公开昵称与字符串角色 | Login Runtime Guard、Enum 传输映射、Context |
| 禁用账号 | 显示账号禁用提示 | 后端状态校验与 code `1005` 映射 |
| 登录后 Storage | 写入 `pinkdoohub.session.v1`，不含密码 | Session Manager 与 Taro Storage Adapter |
| 重新编译恢复 | `/users/me` 验证成功并保持登录 | Effect、Storage 恢复和服务端身份权威 |
| 正常登出 | 服务端登出后清除内存与 Storage，重启保持 guest | refresh session 撤销与本地 `finally` 清理 |
| 本地 `expiresAt` 置为过去 | 先 refresh，再 `/users/me`，无感保持登录 | 启动时主动 refresh 与新过期时间持久化 |
| 保持未来 `expiresAt` 并破坏 access token | `/users/me` 返回 `1006` 后 refresh 并受控重放成功 | 服务端权威、被动 refresh 和单次重放 |
| access/refresh 同时无效 | 清除本地 Session 并返回登录态入口 | refresh 失败的 SessionExpired 清理路径 |

测试过程中只查看必要的请求顺序、状态与非敏感字段，没有把密码或完整 Token 写入文档、日志或截图。页面保持登录本身不是 refresh 的充分证据；主动/被动路径分别通过 Network 请求顺序和刷新后的非敏感过期状态确认。

本结果的范围仅是“微信开发者工具 → 本机 HTTP FastAPI → 本地 SQLite/Redis”。它不证明以下门槛已经通过：

- 微信真机、前后台切换、弱网和不同设备系统；
- H5 CORS、Cookie/CSP/XSS 与浏览器 Storage 行为；
- 正式 HTTPS、微信 request 合法域名和证书；
- 正式微信登录、refresh token 轮换、登录/注册限流；
- 支付宝/抖音运行时 Functional。

## 13. 建议亲手完成的小练习

1. 在纸上写出 `initializing → authenticated` 的每一步和失败分支。
2. 把测试里的 `expires_in=7200` 改成 1，观察为什么 30 秒 skew 会立刻判定过期。
3. 临时让 fake login 少返回 `refresh_token`，确认 Runtime Guard 抛 `ContractError`，再恢复代码。
4. 给 MemoryStorage 放入 `version=2`，观察恢复时为什么必须删除未知版本。
5. 在微信开发者工具 Network 面板确认登录请求有 JSON body、没有 Authorization，`/users/me` 有 Bearer，页面和日志没有完整 Token。

完成以上练习后，应能独立回答：TypeScript 为什么不能验证网络 JSON、Context 和 Storage 分别保存什么、Effect 为什么要清理、以及隐藏管理入口为什么不等于授权。
