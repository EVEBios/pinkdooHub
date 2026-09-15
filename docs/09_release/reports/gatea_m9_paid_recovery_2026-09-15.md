# M9 日志失败与已付款恢复（2026-09-15）

## 当前执行授权与下一候选 G

用户已明确授权按规划持续修复、提交、推送和执行 Gate A 迁移至 M15，只有需要输入密码时交接。该授权覆盖本轮后续候选，不扩大到其他持久环境、真实微信资金或小程序发布；数据与受保护证据约束继续有效。

G 本地补齐 E paid failure + F prepared 的接管：安装前已经验证的 operations 模块显式传入嵌套 lineage、旧 retirement 与 live evidence 校验，避免回到 installed runtime；已付款 takeover 使用 schema 3 业务核验，并继续精确匹配失败归档的付款状态及首次 adoption ancestry。没有放宽任意更深候选链。

本地前置验证：

- 使用实际 S/A/B/E/F Git archive 和只读复制的发布记录，在断网的 Python 3.10 Linux root 容器重开完整 E/F/S 关联。保留真实内容/权限/digest 检查；Docker inspect 使用只读采集的白名单镜像元数据替代外部 Docker 边界。禁止 installed runtime 导入；检查通过，未复制数据库或 Secret，不是现场 stage。
- 双 pending 归档测试同时覆盖未付款与已付款，包含各耐久写入边界的故障恢复；相关 40 项通过。成功路径另外禁止 installed runtime fallback。这组测试加入完整 updater 之前的快速 CI。
- 新真实服务夹具在可销毁 MySQL 8.0.46 的实际 M0–M9 链上通过 paid verifier 与并发 QR 两项测试（0.45 秒）。容器与 tmpfs 存储清理并复核。首次本地 MySQL 就绪探测误命中初始化的 socket 服务，已改为指定库的 TCP 查询；失败发生于迁移前，该临时实例已清理。

发布关联完整本地回归为 `1119 passed`（29.52 秒），CI 工作流契约 `8 passed`，实际 YAML 解析与差异检查通过。未新增依赖、数据库结构或版本 tag。

升级入口另有独立的 takeover profile 校验，本轮同步允许与 nested predecessor 精确绑定的 paid schema 3；已付款归档重用完整候选校验器，不再按旧 pre-claim 字段拒绝。追加候选/升级/QR 关联验证 `401 passed`（9.89 秒），覆盖下游四种 paid/prepared 组合及真实归档的 paid profile 拒绝；这些契约也前置到 updater。初次 G CI 只绑定其旧提交，新增修正必须由更新后的提交重新取得 CI，尚未执行任何 G 现场安装。

G 仍需冻结自身提交、取得独立 CI，再以 E failure、F stage 和 F prepared 三摘要执行正式 stage/retirement。成功前不能继续 activation 或 QR rotation。

## 最新现场检查点：F retirement 被拦截

2026-09-15，本次 F head `f975086d1d3fd5a4611b5c5ade582e9b3c9cfd47`、merge target `9ae975eb9ab624d81ca2f17d48cae174e2d5ab02` 已由 PR #4 / Run `34968651961` attempt 1 完成 9/9。服务器重新验证 GitHub provenance、源码与 artifact 后，F schema 2 stage 成功，未切换 live 配置。

F 的 `retire-failed-acceptance` 在只读 paid verifier 返回 `DEPENDENT_FACTS` 后停止；工具恢复 E 五服务。现场只读诊断确认付款 ID、用户、方式、用途、状态、金额、时间、编号摘要均匹配，付款幂等键比较失败。付款、claim、release 的实际持久键均精确匹配正式业务的命名空间前缀。没有用原始敏感值或日志行作为诊断输出。

根因是 verifier 按客户端请求键比较数据库字段，漏掉既有 `WALLET_PAYMENT_IDEMPOTENCY_PREFIX`、`TABLE_CLAIM_IDEMPOTENCY_PREFIX` 和 `TABLE_RELEASE_IDEMPOTENCY_PREFIX`。此前 SQLite/MySQL 测试直接建 Payment/Session，重复了相同错误，因此真实数据库测试没有覆盖真实业务写入契约。

本次本地修正复用三个正式常量；成功夹具改为真实 `create_session` → `pay_order_with_wallet` → `release_session`，不直接拼付款/会话事实。先用新夹具复现旧 verifier 同一行失败，再修复并通过两个相关文件的 90 项测试（3.16 秒）；增加三类键缺前缀或串到另一 attempt 的六个拒绝用例，继续断言零写入。既有快速 CI 已运行这些文件，MySQL 用例也复用改后的真实服务夹具。本轮尚未重新执行 MySQL / 新候选 CI；旧 F 9/9 不代表新修复通过。

现场必须保留：

| 证据 | SHA-256 / 状态 |
|---|---|
| E failure pending | `114ff14dccc760c41677d9c72028d870e40e3e1fe1fd12911aa1cb1206bebd4c`，`fixtures_offline` |
| F stage Record | `630e277cec3a0842526da25f7605ff2ff4df849a71a34448b782d8cdfec01cb9`，passed |
| F retirement pending | `83db942ba45404b113bacdac59668f5c2b09bb66f14f3696a0221470da38a853`，`prepared` |

live 仍是 E/M9，current 仍是 S；E 已付款订单未修改。未做本轮 source Backup/Restore、activation、adoption、QR rotation 或新验收。后续新候选必须先在写入前验证 **E paid failure + F prepared retirement + S→A→E lineage** 的双 pending 接管，再取得自身 CI。下方原单 pending 顺序不能直接用于这个新检查点；不得手改已安装 F、删除 pending 或借用 F CI。

资源检查：本轮远端输入目录已按精确摘要核验后删除，stage 临时目录为空，诊断 one-off 容器已退出并删除，五服务健康；F 安装及镜像、E/F 受保护记录为恢复依赖保留。Gate A 仍为 **No-Go**。

## 以下为 F 冻结前记录

## 状态与证据边界

本轮在独立 `codex/m9-paid-recovery` 分支修复四项阻塞。这里只记录仓库实现及隔离验证；新候选 F 尚未冻结、取得自身 CI 或部署。Gate A 仍为 **No-Go**。

上次现场只读核验：E merge target 为 `a599953ae8c6c548787ddbc185a44ca827ef0a5d`，其 Run `34960914654` attempt 1 已完成 9/9，stage、旧 A/B retirement、新 source Backup/Restore、M9→M9 adoption/replay 与 app-up 已完成。E 的管理员辅助验收在日志扫描失败；不能把这些证据当作本轮新候选的证据。

E pending 摘要为 `114ff14dccc760c41677d9c72028d870e40e3e1fe1fd12911aa1cb1206bebd4c`。其终态为 `fixtures_offline`、`failure=true`、`payment_committed=true`、`session_released=true`，支付/claim/release replay 与管理员可见性已验证，fixture 下架、两类登录 session 撤销。已支付订单必须保留：钱包 160→155、Kit 库存 10→9，1 条 closed Session、2 条 Timer、0 Occupancy；不是旧 A 的未支付取消场景。`current` 仍为 S，live 为 E。再次操作前必须重新核对这些摘要和现场状态。

## 四项修复

### 1. 认证日志

注册与登录日志仅保留事件和内部 `user_id`，去掉 username。真实注册/登录 HTTP 测试采集 logger 输出，检查用户名、密码、手机号和返回 Token 均未进入日志，再交给正式敏感值扫描器检测。

### 2. Nginx 访问日志

官方镜像 `nginx.conf` 在 http 层配置 main access log。原项目在同层另加 gatea access log，产生两份日志，原始 QR URL 仍被 main 记录。现在在每一个 server 内显式指定 gatea access log，覆盖继承，包括 loopback、TLS 重定向和 HTTPS 服务。

`scripts/ci/check_gatea_log_runtime.py` 使用实际 `nginx:1.27.5-alpine`、项目配置、一次性证书和受控 upstream。检查普通/TLS/重定向、200/503 六个请求：每请求只出现一条脱敏 access line，伪 QR Token、query 和 Authorization 不进入日志。它只使用 loopback 临时端口和带唯一所有权标签的容器；所有退出路径检查并回收容器，临时证书随临时目录删除。测试覆盖这组访问日志场景，不把它描述为任意 Nginx 错误日志场景的穷尽证明。

### 3. 扫描器与前置反馈

正式扫描逻辑集中到 `gatea_resilience.inspect_log_text`，返回行数、精确值匹配数、禁止模式匹配数。M9 acceptance 逐个读取固定的五个服务日志；失败仅报告服务名和次数，不返回命中值或原始行。真实 auth/Nginx 输出以及 username/password/QR/AuthHeader/连接串等负例共同覆盖正式扫描器。

CI 保持原九个 Job 身份：源码契约预检 → 固定 Python 版本 → 真实 Nginx 日志检查 → 安装依赖 → root archive loader → auth/scanner/paid recovery 定向检查 → 完整 updater。MySQL 发布 Job 增加已付款 verifier 与并发 QR 轮换检查。快速检查的失败先阻止昂贵演练。

### 4. 已付款 E 的受控恢复

- 增加独立 schema 3 只读 paid verifier；精确核对冻结 Order/Items、下架 fixture、库存链 `0→10→9`、唯一成功钱包 Payment/Settlement、无 Refund、唯一 `160→155` 流水、closed Session、释放身份/原因/幂等键、900 秒付款期限及 60/120 分钟计时快照。拒绝退款、取消、回填余额或更改旧订单来适配旧流程。
- Retirement 同时支持旧 pre-claim 与新的已支付且已释放终态；schema、付款标志、清理状态、timer/payment hash、业务核验与 predecessor 类型必须匹配。继续采用既有停写、归档、稳定文件身份、耐久 journal 和恢复五服务机制，不修改或删除受保护旧证据来绕过阻塞。
- 重新打开 S→A→E 的 stage/activation/upgrade/evidence/replay 和旧 A/B 归档，允许 F 对首次 adoption 后的已支付失败做 M9→M9 接管。仅支持这一条已知层级；更深的 adoption 链或中间付款态会拒绝，不是通用的递归升级器。
- 新增 `scripts.release.gatea_m9_paid_recovery`：在 F 已通过 stage、adoption/replay 后，在共享运维锁内短暂停止三个写入服务，用 F 的固定 image 重新核验 E 的支付事实。先把 T01 旧/新 Token 的 SHA-256 写入 root-only pending，再通过有界 stdin 给镜像任务传递新 Token；事务只更新 T01 的 `qr_token`。不输出或保存原始 Token，不更新其他字段。提交失联后通过当前摘要识别已提交状态，不重复轮换。恢复 F 五服务后发布完成记录，精确清理自己的 pending。
- 新 acceptance schema 2 必须绑定 E failure 与 QR rotation record 的摘要；钱包基线固定 155→150，历史会话 1→2。旧 schema 1 继续保持 160→155 和 0→1；不接受任意金额或会话数。Resilience 和 finalize 都重新核对恢复记录与 deployment 的绑定。

## 本地验证及测试范围

已完成：

| 验证 | 结果 | 证明范围 |
|---|---|---|
| `tests/release` + `tests/users/test_auth.py` | 1107 passed，29.18 秒 | 发布工具兼容性、终态拒绝、文件归档、恢复/重试、扫描器与 auth 日志 |
| QR 恢复最后复核 | 17 passed，0.77 秒 | 补充旧 Token 被重新分配、CLI 错误回显的拒绝检查；其余 15 项复验 |
| CI 工作流契约 | 8 passed，0.19 秒 | YAML 解析通过，原九个 Job 身份保留 |
| 正式 Nginx 镜像 | loopback 2 + TLS 4 个请求通过 | 本文指定的访问日志场景；容器清理已复核 |
| 一次性真实 MySQL 8.0.46 | M0–M9 实际迁移后 2 passed，最终复核 0.29 秒 | paid verifier 与两个竞争 QR 比较交换仅一个成功；容器/临时存储已回收 |

其中 QR SQLite 测试比较全部已注册表的完整行，只允许 T01 的 Token 字段变化，并通过正式 HTTP 端点验证旧码 404、新码 200。宿主故障注入覆盖提交前、提交后、恢复服务、发布记录及清理失败；重试不重复更新 Token。既有发布回归仍使用其外部边界替身，不冒充现场 provenance 或完整 F 部署。

本轮未修改普通订单、预约、支付业务实现，没有反复运行全部业务测试。快速定向测试之后仅做一次发布关联范围的集中回归。没有新增依赖、表结构迁移或版本 tag。远端九个 Job、AMD64 updater、新候选现场流程仍是待执行门槛。

## 新候选现场顺序（F 自身 CI 通过后）

1. 冻结 F SHA，以它自己的 PR checkout/Run/artifact/source archive/launcher 完成 provenance。禁止复用 E 的 archive 或 Run。
2. 只读复核 S current、E live、上述 E pending 摘要、旧 A/B 归档、五服务和真实业务终态。
3. 用 F schema 2 stage 绑定 E failure；从 F 的已安装 Release 运行 `retire-failed-acceptance`，source=E、lineage=S，不再传旧 B takeover 参数。保留原始 E pending 的不可覆盖归档。
4. 对仍运行的 E/M9 创建新的 source Backup，并完成同 ID 独立 Restore。随后 activate F，执行 source-version=9 的 adoption/replay；必须证明零迁移、内容摘要与图片不变，再启动 F 五服务。
5. 从 F Release 执行 `python -B -m scripts.release.gatea_m9_paid_recovery --confirm-target-sha <F> --confirm-failed-acceptance-sha256 <E-pending-digest>`。先恢复/收口本步骤，再进入验收。使用新 QR Token；旧 Token 不得继续使用。
6. 运行 F 只读 acceptance plan，通过后再从 TTY 隐藏输入管理员凭据进行正式合成验收；不得把凭据放到命令行、聊天或记录。若再次失败，保留新 pending 并调查；本次狭窄恢复规则不授权自动开启更深的再次接管。
7. 绑定 F 新 acceptance 做 resilience、post-acceptance Backup/Restore，最后 finalize：predecessor=E、lineage=S。全部完成前仍为 No-Go，M10–M15 不开始持久迁移。

不得清空旧日志或等待日志窗口过期来制造通过；本轮替换泄漏日志来源并轮换已暴露桌码。现场真实 Secret 如另有泄漏，仍需单独撤销/轮换，不能因本报告推断它们均安全。

## Review

业务写入集中在受控任务，未修改普通业务分层；新 Token 输入有界、事务比较交换、输出只含摘要。付款、库存、权限身份和幂等键有真实数据库验证；记录兼容路径按 schema 分开。新恢复机制与现有工具共享运维锁和受保护文件规则；确认值、摘要或恢复状态不一致均拒绝。临时测试资源已回收，独立工作树和历史证据目录为交付材料保留。
