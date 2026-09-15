# M8 本地 2 核 / 4 GiB / 共享 5 Mbps 压测报告（2026-09-09）

> **Exploratory Matrix Result:** FAIL（11/12 Profile 通过，唯一失败为 10 VU 持续请求未压缩色板 JSON）
>
> **Normal 5–10 User Paths:** PASS（gzip 色板、认证浏览、兼容 PNG 冷/热缓存、订单/库存/钱包写链路）
>
> **Release Decision:** BLOCKED / No-Go
>
> **Run ID:** `20260909t042800`
>
> **Evidence Window:** 2026-09-09 04:27:31–04:43:51（Asia/Shanghai）
>
> **Source Boundary:** `feature/phase9-ci`，Base HEAD `4e745848315aab56805a872ecf5b9f5e3c10135b`，包含其后尚未提交的压测与发布保护差异

## 1. 结论

本轮完整执行了 A/B/C/D、5/10 VU 共 12 个 Profile，记录数与计划数均为 12，
`matrix_complete=true`。11 个 Profile 通过；唯一失败是 A 的 10 VU identity 变体：10 个
并发用户持续、无 think time 地重复拉取每份线传 `51,063` bytes 的未压缩 221 色 JSON。
该 Profile 把单一出口稳定压到 `4.992 Mbps`，产生 `428` 个 qdisc drops，P95/P99 分别升至
`1,510/2,442 ms`，所以触发读延迟和丢包门槛。失败后工具完成严格中间对账、日志/SQL
检查和冷却，再继续采集剩余 Profile；继续采集只扩大诊断覆盖，没有把失败轮改判为通过。

这给出了清晰的容量边界：

- 对当前正常的 5–10 人使用方式，2 核服务包络和 4 GiB 容器限额有明显余量；认证浏览在
  10 VU 下 P95 仍为 `26 ms`，吞吐约为 5 VU 的 2.02 倍。gzip 色板、兼容 PNG 页面加载和
  真实订单/库存/钱包写入也都通过。
- 5 Mbps 出口不足以承受 10 个用户持续、不停顿地请求未压缩的 51 KiB 色板响应。这里的
  短板是出口队列和未压缩负载，不是 CPU 或内存：失败 Profile 的服务栈平均 CPU 仅为两核
  容量的 `10.03%`，内存峰值 `697,212,928` bytes，且没有 OOM、重启或请求错误。
- gzip 把同一响应的线传正文从 `51,063` 降为 `10,023` bytes，减少 `80.371%`。10 VU gzip
  变体在同一 5 Mbps 出口下 P95/P99 为 `271/290 ms`、0 drops，证明当前先启用压缩的路线
  有效；没有理由把 221 个纯数字色块改成 WebP。

整轮仍必须记为 **FAIL**，不能用“正常路径通过”覆盖唯一失败。它是单轮、本机 ARM64
Docker 的探索性证据，不是候选级三轮结果，也不是独立 2 核/4 GiB 云主机、TLS/公网 RTT、
真实微信终端或 Gate A 的发布验收。

## 2. 测试包络与冻结模型

| 项目 | 本轮配置 |
|------|----------|
| 证据级别 | `exploratory`，1 轮 |
| VU | `5`、`10` |
| 每个正式启动窗口 | `60s`；无 ramp、无 warm-up |
| 服务 CPU | MySQL、Redis、App、Nginx、Shaper 共享 `cpuset=0-1` |
| 稳态内存上限 | `2240 + 384 + 1280 + 128 + 64 = 4096 MiB`，swap 禁用 |
| 出口 | 唯一 client-facing TBF，十进制 `5,000,000 bit/s`，burst `128 kbit` |
| 数据库/缓存 | MySQL `8.0.46`、Redis `8.0.1-alpine` |
| 应用边界 | M0→M8、冻结 221 色 MARD、10 个合成普通用户、10 个 Kit |
| 客户端 | 同一宿主上的异步 HTTP Runner；客户端 CPU/内存不计入 4 GiB 服务包络 |
| 外部支付 | 关闭；D 只使用已实现的钱包/manual 本地链路 |

五个长期服务的容器上限总和精确为 4 GiB，并共享两个 CPU；初始化、迁移、MARD 导入和
seed 只在正式 Profile 之外运行。该做法可以稳定限制服务栈，但 Docker Desktop VM、宿主
内核、页缓存、Docker daemon 和 Runner 仍在限额之外，因此不能写成“整台机器精确只有
4 GiB”。本轮为本地 HTTP，也不包含 TLS 握手、公网抖动、丢包重传和微信客户端调度。

四类流量保持以下业务含义：

- A：持续请求完整 221 色详情，分别强制 `identity` 与 `gzip`，并逐次核验
  slot/code/name/HEX/兼容 URL。
- B：普通用户登录后的闭环认证浏览；购物车仍是客户端本地状态，不虚构服务端购物车 API。
- C v3：每个 VU 每 6 秒最多启动一次完整 221 PNG 页面加载，每 VU 最多 4 个图片连接；
  cold 返回 200 正文，warm 先 prime 后要求 304/零正文。60 秒启动窗口后另给最多 6 秒
  completion drain，drain 不减少原窗口；仍未完成则必须终止整个 Profile。
- D：真实执行颜色 Kit 下单后取消、钱包支付订单、代客钱包订单和同幂等键重放，并在末尾
  对账订单、库存、钱包、支付、结算与 Audit。

## 3. 完整 Profile 结果

| Profile | VU | 成功请求 | 失败请求 | 完整旅程/页面 | RPS | P95 / P99 | 平均出口 | drops | 结果 |
|---------|---:|---------:|---------:|----------------:|----:|-----------:|---------:|------:|------|
| A identity | 5 | 701 | 0 | — | 11.63 | 469 / 471 ms | 4.992 Mbps | 0 | PASS |
| A gzip | 5 | 3,470 | 0 | — | 57.77 | 136 / 151 ms | 4.988 Mbps | 0 | PASS |
| B 认证浏览 | 5 | 581 | 0 | — | 9.68 | 26 / 32 ms | 0.290 Mbps | 0 | PASS |
| C PNG cold | 5 | 11,050 | 0 | 50 | 167.42 | 106 / 167 ms | 1.348 Mbps | 0 | PASS |
| C PNG warm | 5 | 11,050 | 0 | 50 | 167.42 | 67 / 103 ms | 0.411 Mbps | 0 | PASS |
| A identity | 10 | 702 | 0 | — | 11.61 | 1,510 / 2,442 ms | 4.992 Mbps | 428 | **FAIL** |
| A gzip | 10 | 3,472 | 0 | — | 57.77 | 271 / 290 ms | 4.989 Mbps | 0 | PASS |
| B 认证浏览 | 10 | 1,171 | 0 | — | 19.51 | 26 / 39 ms | 0.590 Mbps | 0 | PASS |
| C PNG cold | 10 | 17,680 | 0 | 80 | 267.87 | 389 / 602 ms | 2.165 Mbps | 0 | PASS |
| C PNG warm | 10 | 22,100 | 0 | 100 | 334.83 | 155 / 243 ms | 0.822 Mbps | 0 | PASS |
| D 写链路 | 5 | 350 | 0 | 50 | 5.83 | 51 / 59 ms | 0.040 Mbps | 0 | PASS |
| D 写链路 | 10 | 700 | 0 | 100 | 11.67 | 77 / 94 ms | 0.081 Mbps | 0 | PASS |

所有 `73,027` 个已记录请求均成功；整轮失败来自延迟与网络队列容量门槛，而不是 HTTP、
传输、状态码或内容断言错误。A identity/10 的失败 gate 为
`per_operation_read_p95_gate`、`read_p95_gate` 和 `qdisc_drop`。

## 4. PNG 页面边界与 C v3 修正

| C Profile | VU | 启动窗口 | Drain | Started | Completed | Drain 内完成 | Incomplete |
|-----------|---:|---------:|------:|--------:|----------:|-------------:|-----------:|
| cold | 5 | 60s | 6s | 50 | 50 | 0 | 0 |
| warm | 5 | 60s | 6s | 50 | 50 | 0 | 0 |
| cold | 10 | 60s | 6s | 80 | 80 | 10 | 0 |
| warm | 10 | 60s | 6s | 100 | 100 | 0 | 0 |

C cold/10 的最后 10 个页面在 60 秒停止新启动后、6 秒 drain 内完整结束；没有页面被截断，
每个完成页面都恰好访问 221 个 manifest 图片，且没有页面之外的图片请求。其请求 RPS、
平均 CPU 和平均 Mbps 均以包括 drain 的 66 秒总观察时间为分母。这个结果同时表明 cold
页面在 10 VU 时无法始终保持每 6 秒一次的理论最高 cadence；但 CPU、内存和 5 Mbps
均未饱和，单轮证据不能进一步归因为服务端容量问题。

早期 C v2 使用 60 秒硬截止，会把截止瞬间仍在正常执行的页面误报为 incomplete，并暴露
被取消 `_GatheringFuture` 未消费终态的问题。当前 C v3 保留完整启动窗口、增加有界 drain，
并在超时和外部取消路径显式 cancel/await 聚合 Future；drain 后仍 incomplete 依然是 terminal
FAIL，未被软化或从统计中静默删除。历史 artifact 保持原样，不与本轮拼接。

## 5. 写入一致性、日志与 SQL

D 的 5/10 VU 分别完成 `50/100` 个完整旅程。最终严格 reconcile 与静态 fixture 核验结果：

| 检查项 | 实际 / 预期 | 结果 |
|--------|-------------|------|
| 写旅程 | `150 / 150` | PASS |
| Orders / Order Items | `450 / 450`、`450 / 450` | PASS |
| Cancelled / Paid | `150 / 150`、`300 / 300` | PASS |
| Payments / Settlements | `300 / 300`、`300 / 300` | PASS |
| Wallet Transactions | `310 / 310` | PASS |
| Inventory Transactions | `832 / 832` | PASS |
| Audit Logs | `911 / 911` | PASS |
| 钱包差异/违规 | `0 / 0` | PASS |
| 库存违规/写关联违规 | `0 / 0` | PASS |
| Audit action/count 差异 | `0 / 0` | PASS |

App、Nginx、MySQL、Redis、Shaper 日志的 fatal、traceback、MySQL 1205/1213 计数均为 0；
MySQL statement digest 的错误数均为 0。所有容器在 Profile 边界均无 OOM、重启或异常退出。

## 6. 方法迭代记录

以下运行用于发现和关闭测试工具问题，不作为本轮最终容量结论，也不能互相拼成 PASS：

| Run ID | 结果与用途 |
|--------|------------|
| `20260909t021800` | 首个 A identity/5 通过；旧 cooldown 判定误报，修正后废弃 |
| `20260909t022930` | C v1 的 304 无停顿循环扭曲页面模型，废弃 |
| `20260909t023853` | B/D 子集通过，用于写链路和最终 reconcile 诊断 |
| `20260909t030853` | A identity/10 首次触发容量失败；旧 runner 在首个失败处停止 |
| `20260909t033900` | continuation 分类回归使已通过的 A/5 被错误终止，修复后废弃 |
| `20260909t035200` | 成功继续至 6 个 Profile；零旅程 checkpoint 的 Audit 预期含零值键，修复后废弃 |
| `20260909t041500` | 独立复现上述严格 checkpoint 错误 |
| `20260909t042500` | checkpoint 修复诊断通过，`LOGIN=11`、差异为 0 |
| `20260909t040400` | C v2 在硬截止截断 10 个正常页面并暴露 Future 回收警告，记录 8/12 后终止 |
| `20260909t042800` | C v3 权威探索轮；12/12 完成，唯一容量失败为 A identity/10 |

工具现在只允许“结果完整、请求零失败、无 profile error、严格中间对账/日志/SQL 通过且冷却
通过”的白名单纯容量失败继续采集；Runner CPU、MySQL slow query 和任何 C incomplete 仍是
terminal。任何被继续的失败都会保留，并使最终 verdict 为 FAIL。

本轮 artifact 生成后，提交前独立安全审查又发现并关闭了几处测试工具的 fail-open/证据完整性
缺口，包括：监控任务异常退出、Docker 日志或 SQL 统计证据缺失、TBF 实际参数漂移、清理失败
覆盖既有 FAIL、D cadence 追赶旧时间槽、图片 Origin 端口遗漏、D 幂等身份配对不完整，以及
`Vary` 子串匹配。上述修复没有重写或补造 `20260909t042800` 的历史 artifact，也不能追溯为
当轮已经生效；当轮原始配置和原始证据仍支持本报告的探索性观测，但最终提交版本必须重新执行
三轮 `candidate-pre` 才能形成候选级容量证据。

## 7. 证据、复现与限制

本轮原始 artifact 位于被 Git 忽略、权限为 `0700` 的
`backups/performance/20260909t042800/`；其中普通文件均为 `0600`。核心文件摘要：

| 文件 | SHA-256 |
|------|---------|
| `summary.json` | `70c2ef8c356976fc0db1012d8fd2fcc7050b14489e836190be1b3573783acf8b` |
| `test-card.json` | `33acfe2761f9d0d5b5d16df075216d9125367dcad8300110b67fdb31035f86d9` |
| `report.md` | `3c7027a498504d1faed65eeae6a33428002d69f1e32a8a8f9c874404c99a602c` |

Artifact 绑定 dirty 工作树的 `source_tree_sha256`：
`0cd6e82f3dd05b572b336598b848ad2d45070b46dd2a28f59d9daeeb8be1d880`。它不是最终提交
SHA 的候选级证据；源码形成干净提交后，若要作发布容量门槛，仍需按 Runbook 的
`candidate-pre` 参数执行三轮完整矩阵，并优先在独立 x86_64 Linux 目标近似主机上复现。

其他限制包括：当前兼容 PNG 每张约数百字节，不能替代未来 100–500 KiB 真实商品照片的
WebP 冷缓存测试；本轮没有 CDN/Brotli、TLS、公网 RTT、微信 iOS/Android 真机、真实对象
存储或真实微信支付 Provider；本轮也没有对 Gate A、共享、预发布或生产环境施压或写入。

## 8. 决策与后续动作

1. 保持 App/Nginx 的 JSON gzip，并在真实 CDN 可用后评估 Brotli；客户端不得主动禁用压缩。
2. HEX 继续作为纯数字色块的正式字段，小程序继续用 `backgroundColor`；221 张 PNG 仅作
   迁移兼容回退，不转 WebP，也不因本轮结果立即删除。
3. 商品照片和未来校色后的真实色样照片继续采用 WebP，并另建 100–500 KiB 冷/热缓存容量
   Profile；纯数字色块不需要图片格式。
4. 监控 5 Mbps 出口的队列 drops、P95/P99 和 gzip 命中；如果未来存在大量非压缩客户端、
   高频轮询、更多真实照片或并发长期高于 10，应先提升出口/CDN 缓存，再考虑增加 CPU/内存。
5. 本轮关闭了规划中的新版“2 核 / 4 GiB / 5 Mbps / 5–10 并发”本地探索阶段，但没有关闭
   candidate-pre 三轮、完整 Gate A updater、持久 M7→M8、真实 HTTPS RC 或真机灰度门槛。

因此当前发布决定仍为 **No-Go / Not Authorized**。

## 9. 资源回收

Run 结束后已执行并复核：专属 Compose 容器、网络、卷和两个唯一镜像标签均已删除；私有
临时工作目录不存在；`127.0.0.1:18083` 已释放；artifact 按预期保留。清理记录为
`verified=true`、`unrelated_resources_touched=false`。用户原有本地 Redis、Uvicorn 和小程序
watcher 未被本轮接管或停止。
