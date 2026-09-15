# 本地 2 核 / 4GiB / 共享 5Mbps 压测工具

本目录是 [`capacity_load_test_runbook.md`](../../docs/09_release/capacity_load_test_runbook.md)
的可执行配套工具。它只面向本机可销毁 Docker 资源，不授予 Gate A、共享、预发布或生产环境
施压和写入权限。默认先跑 60 秒探索性 Profile；候选前证据必须使用干净提交、10–30 秒爬升、
300 秒稳态、三轮、60 秒预热和 30 秒冷却。

最近一次完整执行见
[`m8_local_2c4g_5mbps_load_test_2026-09-09.md`](../../docs/09_release/reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md)：
12/12 Profile 均采齐，11 项通过；10 VU 持续请求未压缩 51 KiB 色板 JSON 在共享 5 Mbps
出口发生排队/丢包，故探索轮整体为 `FAIL`。该报告是使用示例，不改变本工具的冻结门槛。

## 固定拓扑与资源语义

长期测量容器共用同一个恰好两核的 cpuset（默认 `0-1`），并分别设置禁用 swap 的上限：

| 容器 | 内存上限 |
|---|---:|
| MySQL 8.0.46 | 2240MiB |
| Redis 8.0.1 | 384MiB |
| FastAPI/Uvicorn（1 worker） | 1280MiB |
| Nginx edge | 128MiB |
| `tc` shaper | 64MiB |
| **合计** | **4096MiB** |

`image-init` 的上限为 128MiB；`migrate`、`mard`、`seed` 各继承 1280MiB。这些一次性
操作只在正式 Profile 窗口外运行；`snapshot`/最终 `verify` 会在窗口外短时以 seed one-off
容器与长期服务共存，因此不计入五个被测长期服务的 4096MiB 测量包络。证据会单列这一
口径。4GiB 是“业务容器包络近似”，不是完整 4GB VPS：宿主内核、Docker 守护进程、页缓存
和 Runner Python 主进程（负载发生与采样/编排）不在包络内。

因此本工具最高只输出 `candidate-pre`（候选前）证据，不能把同机 Docker Desktop 的逐容器
上限升级为正式候选级结论。CLI 仅接受 `exploratory|candidate-pre`。正式候选/发布容量
结论必须改用可验证的专用 2 vCPU / 4GiB Linux 主机或 VM，并按 Runbook 同时采集宿主总内存、
内核/页缓存及独立负载发生器证据。

MySQL、Redis 不发布宿主端口；唯一入口是回环地址 `127.0.0.1:18083`。Shaper 与 edge 共享
网络命名空间，只在该命名空间的唯一默认路由接口设置一个 TBF：`5mbit / 128kbit / 400ms`。
Runner 会保存接口、路由、qdisc 起止与逐秒计数，逐样本解析并核对内核实际采用的
`625000 B/s / 16000 B / 约 400ms` TBF 参数，并要求持续 A 流量产生约
`4.75–5.05Mbps`、`overlimits` 增长且 `drops == 0`。这也用于证明限速确实经过发布端口的
响应方向，而不是仅凭配置文本宣称 5Mbps。

## 场景

| 场景 | 行为与关键断言 |
|---|---|
| A | 5/10 个持续在途请求分别发送 `identity` 与 `gzip`；每个响应都核对冻结的 221 个 slot/code/name/HEX/兼容 URL，分别记录 wire/解压字节、TTFB 和下载时间。 |
| B | 5/10 个闭环认证用户，以固定随机种子执行商品列表、典型 Kit、221 色详情、订单列表、钱包和 `/users/me`；默认思考时间 0.4–0.6 秒。购物车是小程序本地状态，不虚构服务端接口。 |
| C v3 | `palette-page-load-v3` 旧客户端兼容 PNG 页面加载旅程。每个 VU 每 6 秒最多启动一次，每次严格遍历冻结的 221 张图且每图恰好一次；每 VU 最多 4 个连接，所以 5/10 VU 最多是 20/40 个图片请求在途。cold 使用唯一查询串强制完整 `200` 并核对 PNG 内容；warm 在采样前 prime，后续严格要求条件请求 `304` 且正文为空。ramp、warm-up、measured 各自在完整启动窗口后增加最多 6 秒 completion drain；A 独立承担把共享出口压到 5Mbps 的饱和证明。 |
| D | 隔离 MySQL 8 中循环完成三条颜色订单：创建后取消、创建后钱包支付并同 key 重放、ADMIN 代客钱包下单并同 key 重放；真实 Provider 始终关闭。 |

C v1 曾将每个 VU 的 4 条连接设为无停顿、无上限的条件重验证循环。大量零正文 `304`
既不是真实的页面重载节奏，也没有打满 5Mbps 出口，反而主要测到 Runner 对响应头、时序和
采样的处理能力，因此不能当作服务容量证据。历史 run `20260909t022930` 的 FAIL 与原始 artifact
原样保留；不能追溯改写、用 v2/v3 规则重新解释，或与新轮次拼接成 PASS。

C v2（`palette-page-load-v2`）专指已经使用真实页面旅程、但 warm-up/measured 没有
completion drain 的历史策略。run `20260909t040400` 先保留了 A identity/10 的容量失败并继续，
随后 C-cold/10 在完整 60 秒启动窗口共启动 80 个整页旅程，完成 70 个、留下 10 个未完成，
因此作为不完整 Profile 立即终止；其 `FAIL`、8/12 已记录 Profile 和原始 artifact 保持不可变。
该结果用于发现工具 deadline 边界，不是服务容量结论，不能用 C v3 补齐后拼成 PASS。

D 测后不只比对行数：Verifier 会检查每个新 Order 与 OrderItem、Payment、Settlement、
WalletTransaction、InventoryTransaction、Audit 的 1:1/金额/状态/来源/幂等串链，核对钱包
和库存不可变流水的连续余额。每个完整旅程必须严格产生 `CREATE_ORDER × 3`、
`CANCEL_ORDER × 1`、`PAY_ORDER × 2`；同 key replay 零新增。初始化只登录一次 admin 和十个
客户，固定的十一条 `LOGIN` Audit 作为测量前基线，Token 有效期在隔离栈内设为 8 小时，
不会在候选长跑途中重复登录。

D 不模拟机器流量，而是模拟真实并发顾客：每个 VU 最多每 6 秒开始一个完整七请求旅程。
固定候选前矩阵的可证明上限为 2880 个完整旅程、约 63360 条待跨域对账业务行，低于 Verifier
冻结的 3000 旅程硬上限；任意参数组合若可能超过该上限会在 plan/执行前直接拒绝。

## 先预览，再执行

以下 run ID 只是格式示例。每次必须换成当次唯一的上海/UTC 时间标识，格式严格为小写
`YYYYMMDDtHHMMSS`；不要复用旧 ID。

只读预览不会创建容器、卷、网络、镜像、目录或 Secret：

```bash
.venv/bin/python -m scripts.performance.harness plan \
  --run-id 20260909t120000 \
  --duration-seconds 60 \
  --rounds 1 \
  --vus 5 10 \
  --scenarios A B C D
```

确认预览中的端口、cpuset、场景和资源后，探索性执行显式增加 `--apply`：

```bash
.venv/bin/python -m scripts.performance.harness run \
  --apply \
  --run-id 20260909t120000 \
  --evidence-level exploratory \
  --duration-seconds 60 \
  --rounds 1 \
  --vus 5 10 \
  --scenarios A B C D
```

完整默认矩阵每轮共 12 个测量组：A identity/gzip、B、C cold/warm、D，分别跑 5/10 VU；
因此“60 秒”是每组稳态，不是整次任务总时长。可先用 `--scenarios A` 等子集排查工具，
但报告必须将未运行场景标为未覆盖，不能据此得出完整容量结论。

候选前固定命令形状如下；执行前必须先 commit，并保证 `git status` 为空：

```bash
.venv/bin/python -m scripts.performance.harness run \
  --apply \
  --run-id 20260909t130000 \
  --evidence-level candidate-pre \
  --duration-seconds 300 \
  --ramp-seconds 20 \
  --warmup-seconds 60 \
  --cooldown-seconds 30 \
  --rounds 3 \
  --vus 5 10 \
  --scenarios A B C D
```

候选前轮次自动交替 `5→10`、`10→5`、`5→10`。为避免写入造成商品/订单基数漂移而污染浏览
对比，Runner 先完成 A/B/C 的全部三轮，再单独执行 D 的全部三轮。每组先在 20 秒内逐步激活
VU，再执行 60 秒全量预热和 300 秒稳态。C v3 对 ramp、warm-up 和 measured 采用相同的
“完整启动窗口 + 最多 6 秒 completion drain”语义：三个启动窗口仍分别是 20、60、300 秒，
总阶段最长分别是 26、66、306 秒。启动窗口结束后不再启动新的 palette load，只允许已经
启动的 221 图整页旅程完成；到 drain 截止仍有未完成旅程时，Profile 必须 terminal `FAIL`。
这 6 秒是在原窗口之后增加，不从原窗口扣除，不减少 VU、启动频率或请求负载。A/B/D 各阶段
仍使用原时长，不增加图片 drain。
D 的 ramp、warm-up 与 measured 使用不同幂等命名
空间，三个阶段的完整旅程都进入最终对账，但 ramp/warm-up HTTP 样本不混入稳态分位数。
按上述候选前固定矩阵，36 个 Profile 的配置内顺序时长下界是 `14,976` 秒
（`4:09:36`）：相比普通 `20+60+300+30` 秒口径，12 个 C Profile 的三个阶段各增加
6 秒 drain，共增加 216 秒。默认探索矩阵则从普通口径的 780 秒增加到 804 秒：4 个 C
measured Profile 各增加 6 秒。
该估算不包含构建、迁移、MARD/seed、warm prime、最终对账和每组最多 5 秒的冷却扩展；
plan 和新报告会单列这一配置内下界，不把它写成整次任务的墙钟上限。
每组冷却时间结束后最多再采 5 次、间隔 1 秒，并要求连续两次满足 readiness 成功、qdisc
backlog 为 0、MySQL 当前行锁等待为 0、`Threads_running <= 2`。该上限只适用于负载任务已经
被 cancel/await 完成、没有遗留请求的当前隔离栈；两个线程对应采样 SQL 自身与可能重叠的
后台 readiness/容器健康检查，不是允许两个业务查询继续运行。每次尝试都会在判定前写入脱敏
`cooldown-samples.jsonl`，瞬态非空闲不会被后一次采样静默覆盖。

## 证据与通过线

脱敏证据保存到已被 Git 忽略的
`backups/performance/<run_id>/`，目录和文件分别为 `0700`、`0600`。其中包括 Test Card、
数据集安全摘要、有界请求样本 JSONL、逐秒指标 JSONL、逐 Profile 摘要、MySQL digest 摘要、最终
`summary.json` 和 `report.md`。Token、密码、完整请求体、敏感 Header、连接串不会落盘。
每个 Profile 的请求统计采用在线精确计数和 1ms 向上取整的固定内存直方图；原始证据只保留
确定性 reservoir 中最多 2048 个成功样本及最多 64 个失败样本。摘要会记录保留/丢弃数量，
因此高 RPS 的 C-warm 不会把全部请求常驻内存或生成数 GiB JSONL。
若后续冷却或 Profile 失败，顶层摘要仍保留此前已经完成的 Profile；对内部受控错误只记录
脱敏 `failure_type`/`failure_reason`，不会展开底层异常链、命令输出或请求凭据。

### 测后容量失败与继续采集

“某个 Profile 失败后继续采齐剩余矩阵”只是一种证据收集策略，不是放宽门槛。Runner 在
Test Card 中以 `observational-capacity-v1` 事前冻结白名单，未知失败一律按 terminal 处理。
只有测量窗口正常完整结束、`failed_requests == 0`、没有 Profile 异常，且全部失败项都属于
下列测后容量白名单时，才会进入继续检查：

- 延迟：`read_p95_gate`、`per_operation_read_p95_gate`、`write_p95_gate`、
  `per_operation_write_p95_gate`、`json_latency_gate`、`per_operation_json_tail_gate`；
- 被测栈 CPU：`average_cpu_gate`、`sustained_cpu_gate`；Runner 自身 CPU 超线会使负载发生器
  成为结果瓶颈，属于证据失真并立即终止；
- 网络：`normal_network_above_85_percent`、`normal_network_sustained_above_90_percent`、
  `qdisc_drop`；A 的 `aggregate_5mbps_not_demonstrated` 和
  `qdisc_overlimits_not_increasing` 还必须同时满足 qdisc 平均值是有限数且
  `0 < average_mbps < 4.75`，表示“未能压满”，不能把超过 `5.05Mbps` 或非法数值误当成
  普通容量不足；

白名单失败在继续前必须先用累计完成旅程执行严格数据对账，确认服务日志和 MySQL statement
均零错误，再通过冷却检查。冷却要求连续两次 readiness、宿主安全水位、容器/cgroup、零 swap、
Redis eviction/rejection、qdisc backlog、MySQL 运行线程和当前锁等待全部安全。任一检查失败都
立即终止，不再执行后续 Profile。

下列情况必须终止：请求/传输/业务断言失败，Profile 非正常结束，ramp/warm-up/prime 失败，
目标或源码身份变化，readiness、重启、OOM 或 cgroup 事件，采样/路由/qdisc 证据缺失，qdisc
字节不增长，A 实测超过 `5.05Mbps` 或不是有限数，内存峰值/增长、swap、Runner CPU/RSS 或宿主
安全门槛失败，MySQL slow query、其他 MySQL 门槛、Redis 门槛、严格对账、服务日志、statement
error 或 cooldown 失败。即使所有剩余 Profile 最终采齐，只要出现过一个白名单容量失败，
该 Profile 与整轮仍为 `FAIL` 并以非零状态退出；`matrix_complete=true` 只说明覆盖完整。

逐 Profile 的 `failure_handling` 保存 disposition、完整性和静态失败分类；checkpoint/cooldown
成功后才在内存汇总的独立 `continuation` 字段记录是否通过冷却及是否实际进入后续 Profile，
避免预先落盘的 Profile 文件声称一个尚未发生的结果。顶层 `profile_execution` 保存计划数、
记录数、矩阵完整性和全部容量失败明细。
`capacity-failure-checkpoints.jsonl` 与 `capacity-failure-continuations.jsonl` 分别保留继续前检查
和实际处置证据。历史 run `20260909t030853` 由当时的 fail-fast Runner 执行，在
A identity 10 VU 的 P95/qdisc drop 门槛失败后结束；其 artifact、未采齐状态和 `FAIL` 结论
原样保留，不用新策略回算、补写或改判。

Runner 至少执行以下硬门槛：

- 非预期状态、业务断言、连接错误、超时、readiness 失败、重启、OOM、qdisc drop 均为 0；
- A/B/C 只读请求 P95 < 1s；其中 10 VU 正常 JSON 继续使用更严的 P95 ≤ 800ms、
  P99 ≤ 2s、max < 5s；D 写请求 P95 < 2s；
- 两核平均 CPU < 70%，不得连续 30 秒高于 85%；栈内存峰值 < 4GiB 的 80%，后半段不比
  前半段持续增长超过 10%；
- B 正常网络 < 4.25Mbps；A 的 qdisc 平均约 4.75–5.05Mbps，overlimits 增长且零丢包；
- MySQL 无 statement error、1205、1213、死锁或未清空锁等待，Redis 无 eviction/rejection；
- D 的订单、资金、库存、Payment/Settlement 和 Audit 全部对账一致。
- 预检至少保留 4GiB 宿主磁盘和 2GiB 可用内存；运行中逐采样要求磁盘至少 2GiB、宿主可用
  内存至少 1GiB，Runner Python 主进程 RSS < 1GiB、单核 CPU < 70%。该 CPU 值是整个
  Runner Python 进程口径，包含进程内负载生成和采样/编排开销，不只是 HTTP 协程；它不包含
  Runner 启动的 Docker/`ps` 等子进程 CPU。低水位、指标断档或采样失败会
  立即取消当前负载并保存已在内存中的有界证据；仅当内存重新达到 2GiB、磁盘达到 4GiB
  安全余量时才启动失败现场对账，否则明确记录 `skipped_due_to_safety_floor` 并直接精确清理。

图片 cold/warm 仍执行统一的只读 P95 < 1s，但不机械套用 B/10 的 800ms JSON 尾延迟线。
当前兼容 PNG 是数百字节的纯色块，
不能替代未来 100–500KiB 商品 WebP 的独立冷缓存容量测试。本地 edge 只提供 HTTP，没有 TLS、
公网 RTT、丢包、CDN 和真实微信终端，因此即使通过也只能按实际证据级别解释。

## 资源生命周期与异常恢复

正常成功、断言失败、超时、Ctrl-C 和 Python 异常都会进入同一个 `finally`：先停止负载/采样，
再保存可得的脱敏摘要，随后只对当前 run ID 执行 Compose `down --volumes --remove-orphans`、
删除两个唯一镜像标签、删除 `/tmp/pinkdoohub-performance/<run_id>` 下的 Secret/工作目录，并
复核容器、网络、卷、镜像标签、目录和回环端口均已释放。不会执行 prune、通用 `pkill`，也
不会停止现有 8000/6379 服务或其他 Compose project。证据目录有意保留。
清理步骤中的非零返回码会作为诊断保留，但是否真正残留只由最后一次精确 project-label、
镜像标签、工作目录和端口盘点决定；例如从未构建的唯一镜像标签删除返回 1 不等于有残留。

`SIGKILL`、宿主重启或 Docker daemon 崩溃无法执行进程内 `finally`。此时先用只读命令生成
该 run ID 的精确清理计划：

```bash
.venv/bin/python -m scripts.performance.harness cleanup-plan \
  --run-id 20260909t120000
```

只读盘点确认 run ID、精确 Compose label、两个唯一镜像标签、私有工作目录和端口都属于该
次任务后，使用同一参数执行受控恢复清理（证据目录不会删除）：

```bash
.venv/bin/python -m scripts.performance.harness cleanup \
  --run-id 20260909t120000 \
  --confirm-run-id 20260909t120000 \
  --apply
```

若原测试使用了非默认 `--http-port` 或 `--cpuset`，盘点和清理命令必须传入相同值。清理器仅
解析该 run ID 的精确 project label、镜像标签和私有直接子目录，随后复核对象、目录和端口；
不得用 `docker system prune`、`docker volume prune`、模糊容器名或通用进程名代替精确回收。

所有测试 run 还会持有 `/tmp/pinkdoohub-performance/.owner.lock` 的非阻塞文件锁；发现其他
performance project 或遗留 workspace 时只拒绝启动，不接管或清理别的 run。App 构建使用
一次性私有 staging context：只复制 Git 索引中且属于 Dockerfile 明确 COPY 路径的工作树文件，
未跟踪文件即使位于 `app/` 也不会送给 Docker daemon；符号链接和特殊文件直接拒绝。
`Dockerfile.app.dockerignore` 再递归排除环境文件、私钥、凭据、日志、本地数据库与 Python
缓存作为纵深防护；`Dockerfile.app` 与正式 runtime 镜像契约由单元测试保持同步。
