# 微信 Gate A Functional / Smoke / E2E 验收矩阵

> **Status:** Matrix Frozen — 当前 RC 真机结果待填
> **Last Updated:** 2026-08-29
> **Scope:** 微信小程序内部测试版（Gate A）

本矩阵冻结“必须证明什么”和证据等级。2026-08-29 的本地自动化基线证明当前源码质量，但不等于未来 RC 在真实 HTTPS、MySQL、Redis 和微信真机上已经通过。

## 1. 证据等级与结果

| 标记 | 含义 |
|------|------|
| `A` | CI 自动化；结果绑定 Git SHA、锁文件和运行时版本 |
| `M` | RC 人工验证；记录设备、基础库、网络、环境、人员和结果 |
| `A+M` | CI 与真实设备都必须通过 |
| `N/A` | 当前 Gate 不适用；必须写明理由 |
| `GAP` | 当前无覆盖；必须关联风险、负责人和最晚关闭 Gate |

结果只能使用 `PASS`、`FAIL`、`BLOCKED`、`NOT RUN`。开发者工具关闭域名校验、历史截图、未绑定 SHA 的口头结果不能填 `PASS`。

当前自动化参考证据：后端 `1465 passed, 9 skipped`（9 项为 MySQL-only），前端 61 suites/387 tests、TypeScript、ESLint、Stylelint、OpenAPI 漂移和微信构建通过。它们在 9.2 CI 落地前仍是本地审计证据。

## 2. 身份、角色与权限

| ID | 场景 | 期望 | Gate A 证据 | 当前状态 |
|----|------|------|-------------|----------|
| ID-01 | Guest 冷启动与公共浏览 | 不要求登录；可浏览 Online Product；无管理入口 | `A+M` | RC `NOT RUN` |
| ID-02 | 普通用户账号密码登录 | 建立 Session，恢复用户态，错误信封可解释 | `A+M` | RC `NOT RUN` |
| ID-03 | 注册、登出、再次登录 | 状态与 Storage 一致；登出后敏感页面不可用 | `A+M` | RC `NOT RUN` |
| ID-04 | access 过期、refresh 有效 | single-flight 刷新并安全重放允许的请求 | `A+M` | RC `NOT RUN` |
| ID-05 | access/refresh 都失效 | 清理 Session、回到登录、不形成刷新循环 | `A+M` | RC `NOT RUN` |
| ID-06 | ADMIN | 可进入获授权管理能力；普通用户不可调用 | `A+M` | RC `NOT RUN` |
| ID-07 | SUPER_ADMIN | 首次初始化、登录及高权限边界正确 | `A+M` | bootstrap `BLOCKED` |
| ID-08 | 被禁用用户 | 新登录失败；已有 access/refresh 均不能继续 | `A+M` | RC `NOT RUN` |
| ID-09 | 资源与权限隐藏 | owner-only、ADMIN+、不存在资源语义符合 API 契约 | `A+M` | RC `NOT RUN` |
| ID-10 | 微信身份 | Gate A 不启用微信登录，界面明确为内部测试 | `M` | `N/A`（Gate B） |

## 3. 用户业务链路

| ID | 领域 | 场景与关键断言 | 证据 | 当前 RC |
|----|------|----------------|------|---------|
| US-01 | Product | Experience/Kit 列表、详情、Option 组合、图片与空/错/加载态 | `A+M` | `NOT RUN` |
| US-02 | Product | Offline/Draft/删除对象不向普通用户错误暴露 | `A+M` | `NOT RUN` |
| US-03 | Cart | 增删改、数量/条目上限、Option 隔离、Storage 恢复与坏缓存 | `A+M` | `NOT RUN` |
| US-04 | Cart | Kit 无库存、登录/登出、Product 变化后的收敛行为 | `A+M` | `NOT RUN` |
| US-05 | Order create | Experience、Kit、混合订单成功；快照与金额正确 | `A+M` | `NOT RUN` |
| US-06 | Order create | 最后一件、库存不足、并发/重复点击只产生预期结果 | `A+M` | `NOT RUN` |
| US-07 | Order create | 弱网/断网/服务端已成功但客户端 unknown 时安全恢复，不盲重发 | `A+M` | `NOT RUN`；Gate B 仍需服务端幂等 |
| US-08 | My Orders | 分页、筛选、详情、历史快照、owner-only | `A+M` | `NOT RUN` |
| US-09 | Cancel | Pending 取消恢复库存；终态不可取消；重复/40921 正确收敛 | `A+M` | `NOT RUN` |
| US-10 | Session | 登录后 Cart/页面恢复，登出后缓存和敏感数据策略一致 | `A+M` | `NOT RUN` |

## 4. 管理业务链路

| ID | 领域 | 场景与关键断言 | 证据 | 当前 RC |
|----|------|----------------|------|---------|
| AD-01 | Order | 组合筛选、分页、详情与历史快照 | `A+M` | `NOT RUN` |
| AD-02 | Order | Pending→Paid→Completed；非法前置条件；库存不变化 | `A+M` | `NOT RUN` |
| AD-03 | Order | 网络 unknown、竞态和重复点击不盲目重发 mutation | `A+M` | `NOT RUN` |
| AD-04 | Product | 创建/编辑/删除、Experience Option 恢复原 ID、Kit 改价 | `A+M` | `NOT RUN` |
| AD-05 | Product | Draft/Online/Offline readiness 与 Validator 错误展示 | `A+M` | `NOT RUN` |
| AD-06 | Image | jpg/png/webp、2 MiB、预览、删除、失败补偿、HTTPS 读取 | `A+M` | `NOT RUN` |
| AD-07 | Inventory | 调整首次 201/重放 200、同 key 冲突、正负边界与 40932 | `A+M` | `NOT RUN` |
| AD-08 | Inventory | Product/全局流水、筛选/分页、Order source、隐私字段不输出 | `A+M` | `NOT RUN` |
| AD-09 | Audit | Product/Order/Inventory/User 敏感操作顺序、主体与时间正确 | `A+M` | `NOT RUN` |
| AD-10 | User Admin | 列表筛选、禁用事务/审计、角色层级和旧 Token 阻断 | `A+M` | `NOT RUN` |

## 5. 运行时、设备、网络与生命周期

| ID | 场景 | 最低覆盖 | 证据 | 当前 RC |
|----|------|----------|------|---------|
| RT-01 | iOS 真机 | 一台支持设备；记录系统、微信、基础库、机型 | `M` | `NOT RUN` |
| RT-02 | Android 真机 | 一台支持设备；记录系统、微信、基础库、机型 | `M` | `NOT RUN` |
| RT-03 | 布局可用性 | 小屏/常见屏/大字体、键盘、安全区域、长文本 | `M` | `NOT RUN` |
| RT-04 | 网络切换 | Wi-Fi、移动网络、弱网、断网、恢复 | `M` | `NOT RUN` |
| RT-05 | 生命周期 | 冷/热启动、前后台、锁屏、请求中断、分包首次加载 | `M` | `NOT RUN` |
| RT-06 | request 域名 | 真实 HTTPS、证书、微信后台白名单；真机成功 | `M` | Origin `BLOCKED` |
| RT-07 | upload 域名 | 图片上传中断/恢复、大小/类型错误、unknown | `A+M` | 域名 `BLOCKED` |
| RT-08 | download 域名 | 商品图片加载、失败占位、缓存和恢复 | `M` | 域名 `BLOCKED` |
| RT-09 | Redis/DB 故障 | readiness 摘流量；客户端错误可恢复且不泄密 | `A+M` | readiness `BLOCKED` |
| RT-10 | 后端重启 | 连接恢复、Token/Cart/订单结果一致，不丢图片 | `A+M` | RC `NOT RUN` |
| RT-11 | 快速操作 | 双击、连点、重复进入、返回前台不会重复 mutation | `A+M` | RC `NOT RUN` |
| RT-12 | 版本来源 | 体验版 artifact、Git SHA、OpenAPI、环境和版本记录一致 | `A+M` | CI `BLOCKED` |

## 6. 安全、隐私与可观测性

| ID | 场景 | Gate A 断言 | 证据 | 当前 RC |
|----|------|-------------|------|---------|
| SE-01 | Secret 扫描 | 源码、日志、artifact、source map 无 Secret/私钥/连接串 | `A` | 本地扫描有限；CI `GAP` |
| SE-02 | 产物 Origin | 无 `.example.invalid`、开发 Origin 或意外主机 | `A` | 当前产物 `FAIL` |
| SE-03 | 权限 | UI 隐藏不替代后端 ADMIN+/owner 校验 | `A+M` | RC `NOT RUN` |
| SE-04 | 日志脱敏 | 无密码、Token、完整 Redis URL、reason/key 和个人敏感信息 | `A+M` | Redis URL 风险待修 |
| SE-05 | 依赖 | 微信运行时可达高风险均关闭或获有期限例外 | `A` | npm 可达性 `GAP` |
| SE-06 | 内部声明 | 体验版明确受邀、不可公开、无微信支付/登录误导 | `M` | `NOT RUN` |
| SE-07 | 隐私 | Gate A 使用合成/受控账号，数据保留、反馈和停用日期明确 | `M` | `NOT RUN` |

## 7. Gate B 追加域（本次不执行）

公开版必须另行扩充并通过：微信登录及账号绑定/冲突/禁用、登录/注册限流、refresh 轮换、Order create 服务端幂等、微信支付/回调/查单/退款/对账、正式监控告警、隐私保护指引、用户权利和平台提审。Gate A 的账号密码、ADMIN 人工 Paid 和合成数据不能作为这些项目的证据。

## 8. RC 验收报告模板

```text
RC / Git SHA / CI run / artifact checksum：
后端、前端、OpenAPI 版本：
环境 / API Origin / 数据集：
设备、系统、微信、基础库、网络：
执行人 / 日期：Yijie Shen（实际执行时填写日期）
矩阵 ID：
结果：PASS / FAIL / BLOCKED / NOT RUN
证据链接：
缺陷 ID、严重性、复现与处置：
风险例外 ID 与到期日（如有）：
```

测试账号只记录角色和受控标识，不在文档中记录密码、Token、OpenID 或个人信息。
