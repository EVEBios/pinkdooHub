# 容量与性能压测 Runbook

> **Status:** Active reusable methodology；本文件本身不构成环境写入或发布授权
>
> **Last Updated:** 2026-09-09
>
> **Scope:** 本地容量探测、候选版本性能验证、生产相似发布容量验收
>
> **Evidence Policy:** 长期规则维护在本文件；每次执行结果单独归档到 `reports/`，不得覆盖旧报告

本文定义 pinkdooHub 容量压测的设计、隔离、资源限额、流量模型、指标口径、通过标准、
证据和资源回收规则。它解决的是“怎样得到可比较、可复核且不会误伤现有环境的结果”，
不为任何共享、Gate A、预发布或生产环境授予写入或施压权限。

本地执行证据分两代保留：

- [2026-09-08 初版容量探测](reports/local_2c4g_5mbps_load_test_2026-09-08.md)使用
  SQLite/简化只读模型，先于本规范成文，属于不可追溯重算的历史样本。
- [2026-09-09 M8 A/B/C/D 完整探索矩阵](reports/m8_local_2c4g_5mbps_load_test_2026-09-09.md)
  使用 MySQL 8、M8、认证读、C v3 PNG 冷/热页面和真实本地写链路；12/12 Profile 已采齐，
  但 10 VU 未压缩色板 JSON 触发读延迟和 qdisc drop，因此整体严格记为 `FAIL`。

两份报告都是各自当次的不可变证据，不互相覆盖，也不能替代干净 SHA 的 candidate-pre
三轮或独立 2 vCPU / 4 GiB Linux 主机验收。本 Runbook 才是后续可迭代的方法规范。

---

## 1. 目标、术语与证据级别

### 1.1 压测开始前必须回答的问题

一次压测只回答预先冻结的问题，例如：

- `2 核 / 4GiB / 聚合 5Mbps` 下，5 个和 10 个正常浏览用户是否满足延迟与可用性门槛；
- 当前最大的 gzip JSON 响应在共享 5Mbps 出口上的饱和吞吐是多少；
- 真实尺寸 WebP 冷缓存时，图片出口是否先于 API、CPU 或数据库成为瓶颈；
- MySQL 8 下订单、库存、钱包或预约写事务在目标并发下是否正确、稳定并可对账。

不得在完成后根据结果改写问题，也不得把“只读接口稳定”推广成“写事务稳定”，或把本地
Docker Desktop 结果推广成目标云主机的最终容量。

### 1.2 统一术语

| 术语 | 含义 |
|------|------|
| Profile | 一组冻结的代码身份、拓扑、资源、网络、数据、请求组合和通过门槛 |
| Virtual User / VU | 闭环用户：请求完成、执行断言和思考时间后再发下一个请求 |
| 并发请求 | 同时在途的请求数；不等于用户数，也不等于固定 RPS |
| Round | 一次完整的预热、稳态测量和冷却过程 |
| Steady window | 计入正式统计的稳定测量窗口；预热数据不得混入 |
| Wire body bytes | HTTP 客户端实际下载的传输编码后正文；gzip 时是压缩正文，不等于自动解压后的 `content` 大小 |
| Network bytes | qdisc/网卡统计的网络层字节，包含比响应正文更多的协议开销 |
| 聚合 5Mbps | 所有客户端连接共享 `5,000,000 bit/s` 服务端出口，不是每连接各 5Mbps |

### 1.3 证据分层

| 级别 | 最低要求 | 可以支持的结论 | 不能支持的结论 |
|------|----------|----------------|----------------|
| 探索性 | 隔离环境；工作树和镜像身份可追溯；30–60 秒稳态；至少一轮 | 当前机器与当前 Profile 是否有明显瓶颈；设计下一轮测试 | 发布容量、目标云主机容量、未测写链路或真实图片容量 |
| 候选级 | 干净 SHA/可复现 artifact；原生架构；生产相似服务；三轮且每轮稳态至少 300 秒 | 候选版本在指定包络下是否达到预先冻结门槛 | 未覆盖的公网、CDN、真实 Provider、云盘或终端体验 |
| 发布级 | 明确授权；目标或等价架构；MySQL 8、Redis、HTTPS、真实缓存策略和代表性数据；候选级重复要求 | 指定 RC、环境与时间窗口的发布容量决策 | 未来版本、不同实例规格、不同数据规模或无限期容量承诺 |

证据级别由实际环境和执行质量决定，不能通过修改报告标题升级。探索性结果可以指导配置，
但只有预先列入发布 Gate 并满足发布级条件的结果才可作为阻断或放行依据。

---

## 2. 授权、安全边界与立即停止条件

### 2.1 默认允许与禁止范围

本地压测默认只允许操作本次任务创建或明确接管的可销毁资源。除非获得当次明确授权，禁止：

- 连接、写入或施压生产、共享、Gate A、预发布数据库和 Redis；
- 对持久 `db.sqlite3` 执行写压测，或在仍有写入时直接复制 SQLite 文件；
- 修改 Docker Desktop 全局 CPU/内存、宿主机 `pfctl`/`dnctl` 或系统网络配置；
- 停止、重启或重新配置用户已经运行的 Uvicorn、Redis、Taro watcher、微信开发者工具或容器；
- 使用真实用户、真实手机号、真实余额、真实支付 Provider 或不可撤销外部副作用；
- 为方便清理执行无精确目标的 `docker system prune`、`docker volume prune`、通用 `pkill`
  或按进程名批量结束服务。

每轮必须使用唯一 `run_id`，并由它派生可识别的 Compose project、容器、网络、卷、端口、
镜像标签、临时目录和结果目录。显式写死 `name:` 的 Compose 资源不会被 `--project-name`
自动隔离，必须逐项覆盖为任务唯一名称。

### 2.2 数据与 Secret

- 只读 SQLite Profile 使用 SQLite Backup API 在一致性视图下创建隔离副本，不把普通文件
  复制当作在线数据库备份。
- MySQL Profile 使用专用 Schema/实例或经验证的一致性快照恢复到可销毁实例；fixture 和
  人工预检都应拒绝默认 `3306`、来源不明地址和非专用 Schema。
- 写压测只使用合成账号和合成业务数据。Token 仅保存在压测进程内，不写日志、报告、命令
  参数或版本库。
- 报告只记录 Secret 键名、脱敏目标和摘要，不记录密码、Token、JWT、Cookie、连接串、
  AppSecret 或支付凭据。
- 原始请求/响应采样必须关闭敏感 Header 和个人信息正文；确需留样时使用最小字段投影和
  受控 artifact，不提交到 Git。

### 2.3 立即停止条件

出现以下任一情况，先停止负载发生器，再保护证据和数据；不得为了跑满时长继续施压：

1. 实际目标、数据库、Redis、端口、镜像或资源名称与冻结 Profile 不一致；
2. 发现请求到达持久、共享或未授权环境，或产生未计划的业务写入/外部副作用；
3. Secret、Token、真实个人信息或带凭据 URL 出现在输出或报告中；
4. 任一任务容器 OOM、反复重启、readiness 连续失败，或错误率在 10 秒窗口持续超过 1%；
5. 磁盘、内存、连接池、日志或队列逼近会影响宿主机和用户既有服务的安全边界；
6. 资源限额、聚合限速、指标采样或业务断言未生效，导致结果无法解释；
7. 负载发生器失控、无法优雅停止，或任务资源的所有权与回收目标不再明确。

停止并不等于立即删除现场。先记录时间、Profile、最后一组指标和错误摘要；确认无需进一步
诊断后，再按第 14 节精确回收任务资源。

### 2.4 允许继续采集的测后容量失败

“继续采集”与“通过门槛”是两个独立维度。一个 Profile 只有在稳态窗口正常完整结束、零请求/
传输/业务断言错误、证据完整且失败项全部命中 Test Card 事前冻结的精确白名单时，才允许在
安全检查后继续剩余矩阵。失败 Profile 必须进入汇总且保持 `FAIL`；即使矩阵最终完整，整轮也
必须是 `FAIL`，不能用 `matrix_complete`、后续成功轮或 aggregate 平均值覆盖它。

当前 `observational-capacity-v1` 白名单如下：

| 类别 | 可继续采集但仍失败的 gate |
|------|--------------------------------|
| 延迟 | `read_p95_gate`、`per_operation_read_p95_gate`、`write_p95_gate`、`per_operation_write_p95_gate`、`json_latency_gate`、`per_operation_json_tail_gate` |
| 被测栈 CPU | `average_cpu_gate`、`sustained_cpu_gate` |
| 正常网络 | `normal_network_above_85_percent`、`normal_network_sustained_above_90_percent` |
| 可排空拥塞 | `qdisc_drop`；请求必须全部成功，继续前 backlog 必须归零 |
| A 未压满 | `aggregate_5mbps_not_demonstrated`、`qdisc_overlimits_not_increasing`；仅当 bytes 正增长且平均值是有限数并满足 `0 < Mbps < 4.75` |

白名单之外的失败全部 terminal-by-default。特别是以下情况不得继续：

- Profile 异常或结果不完整，任意请求、HTTP、连接、超时、响应契约或业务断言失败；
- ramp、warm-up、cache prime、数据发现、目标/路由/源码身份或限速配置失败；
- readiness、容器退出/重启/OOM、cgroup `high/max/oom/oom_kill` 增长或 swap 非零；
- 指标、operation、延迟、qdisc、MySQL、Redis、主机安全证据缺失或采样断档；
- qdisc 字节不增长，A 平均速率超过 `5.05Mbps` 或为 NaN/Infinity/其他非法值；
- 内存峰值、内存增长、Runner CPU/RSS、宿主内存/磁盘安全门槛失败；Runner CPU 超线意味着
  负载发生器可能成为瓶颈，不能继续积累并误解为服务端容量；
- MySQL slow query、锁未排空、死锁或其他错误，Redis eviction/rejection，日志/statement error，严格数据
  对账或 cooldown 失败，以及任何未来新增但尚未加入白名单的 gate。

继续前必须按累计完成旅程执行与最终阶段相同的严格数据核验，并确认日志和 MySQL statement
零错误；随后 cooldown 连续两次确认 readiness、宿主安全水位、所有长期容器/cgroup、零 swap、
Redis、qdisc backlog、MySQL 运行线程和当前锁等待均安全。只有该 checkpoint 全部通过才能
进入下一 Profile。最后一个 Profile 若发生白名单失败仍要完成 checkpoint/cooldown，但报告应
只记 `cooldown_passed=true`，不得虚构“已经执行了后续 Profile”。

本策略只对 Test Card 已冻结 `observational-capacity-v1` 的新执行生效，不追溯重算旧 artifact。
历史 run `20260909t030853` 由旧 fail-fast Runner 在 A identity 10 VU 的 P95/qdisc drop 失败后
终止；它仍是未采齐的 `FAIL`，不得补写 continuation 字段、拼接后续结果或改判。

---

## 3. 冻结 Test Card 与执行身份

### 3.1 Test Card 必填项

执行前先在当次报告草稿中冻结以下内容：

| 类别 | 必填内容 |
|------|----------|
| 容量问题 | 要判断的用户数、接口/旅程、资源规格、可接受延迟和业务结果 |
| 证据级别 | 探索性、候选级或发布级，以及未满足更高级别的原因 |
| 代码身份 | Git HEAD、clean/dirty、tracked diff 摘要、untracked build context 摘要、版本 |
| 构建身份 | App image ID、架构、Dockerfile、基础镜像 digest、构建时间和 CI artifact（如有） |
| 运行栈 | App worker、Nginx、MySQL/SQLite、Redis、对象存储/CDN及精确版本 |
| 资源语义 | CPU 是共享核还是逐容器 quota；内存是服务/预算近似/整机实测；swap 策略；压测器是否计入 |
| 存储 | 数据库/图片卷或云盘类型、文件系统、容量、可用空间、IOPS/吞吐/延迟配额和 fsync 策略 |
| 网络语义 | Mbps 定义、限速方向/接口、burst/latency、TLS、RTT、丢包、gzip/Brotli 和缓存 |
| 数据集 | 来源、快照时间、行数/图片数、最大响应、图片尺寸、合成 persona 与清理策略 |
| 负载 | VU/RPS、权重、思考时间、随机种子、预热、稳态、冷却、轮数和执行顺序；C v3 各阶段的 options 启动窗口、completion drain 和总阶段时长 |
| 门槛 | 正确性、P95/P99、错误、CPU、内存、网络、数据库、Redis 和数据完整性阈值 |
| 失败处置 | continuation policy 版本、精确可继续白名单、条件式网络规则、terminal-by-default、继续前 checkpoint/cooldown 及整轮失败保持规则 |
| 安全 | 授权范围、禁止目标、停止条件、Secret 策略、资源所有者和清理负责人 |

测量开始后不得修改 Profile 来“修正”结果。需要改变 worker 数、图片大小、缓存、压缩、
数据库或资源限制时，停止当前轮并创建新的 Profile/报告段落，保留失败或失效原因。

### 3.2 当前工作树身份

本地探索允许测试 dirty 工作树，但必须使受测内容可追溯。至少记录下列命令的结果或摘要：

```bash
git rev-parse HEAD
git status --short
git diff --binary | shasum -a 256
git diff --cached --binary | shasum -a 256
git ls-files --others --exclude-standard | LC_ALL=C sort | shasum -a 256
```

若 untracked 文件进入 Docker build context，仅保存文件名列表摘要还不够；还需记录纳入构建
文件的内容摘要或整个 build context 的可复核摘要。报告不得打印被 `.gitignore` 排除的
Secret 或凭据文件。

候选级和发布级默认要求干净、已提交 SHA 和可复现 artifact。若因紧急诊断必须使用 dirty
工作树，只能降级为探索性证据。

### 3.3 镜像和架构

- 镜像必须从受测工作区或冻结 artifact 构建，不能复用来源不明或对应旧 revision 的镜像。
- 在 ARM64 主机上测试 ARM64 镜像，在 x86_64 主机上测试 x86_64 镜像；通过 QEMU 模拟的
  跨架构 App 结果不能作为 CPU 容量证据。
- 报告记录 App、Nginx、MySQL、Redis 和辅助镜像的 ID/digest，而不只记录可变 tag。
- 构建器、Docker/Compose、宿主 OS 与 CPU 架构进入环境元数据。

---

## 4. 隔离拓扑与资源包络

### 4.1 推荐拓扑

```text
负载发生器 + 指标采样器（服务资源包络之外）
        │
        ▼
唯一 loopback/专用测试入口
        │
        ▼
Nginx / Edge ── client-facing egress tc/TBF
        │
        ▼
Uvicorn App（无 reload）
        ├── 隔离 MySQL 8 或一致性 SQLite 副本
        ├── 隔离 Redis
        └── 隔离图片卷 / 测试对象存储
```

负载发生器和采样器默认不计入服务的 2 核/4GiB 包络，否则测到的是“服务与压测器争资源”。
如果目标问题就是整机连同压测器的极限，必须另建 Profile 并明确说明。

### 4.2 两核必须是全栈共享两核

模拟“2 核主机”时，App、数据库、Redis 和 Nginx 应限制在同一个两核 CPU 集合，例如共同
使用 `cpuset=0-1`。每个服务可在其他服务空闲时借用这两核，但所有服务合计不能离开它们。

不要把两核机械拆成互不借用的 `App 0.75 + MySQL 1.0 + ...` 后声称等价于共享两核；这种
模型会在依赖空闲时仍限制 App，通常比真实共享主机更悲观。若 Compose 原有逐服务 quota，
必须明确覆盖或记录其影响。

启动后至少核验：

```bash
docker inspect <exact-container-name> \
  --format 'cpuset={{.HostConfig.CpusetCpus}} nano_cpus={{.HostConfig.NanoCpus}}'
docker exec <exact-container-name> sh -c \
  'cat /sys/fs/cgroup/cpuset.cpus.effective; cat /sys/fs/cgroup/cpu.max'
```

同一 Docker/宿主机上的其他工作负载也可能被调度到这两核。开始前记录背景容器和进程；不得
为了压测擅自停止用户任务。无法取得专用或不相交 CPU 集合时，把竞争列为环境偏差并降低
证据级别。

### 4.3 4GiB 有三种不同语义

| 模型 | 定义 | 适用场景 | 配置原则 |
|------|------|----------|----------|
| 服务进程包络 | 任务容器的内存上限合计为 4GiB，不模拟宿主内核和守护进程竞争 | 快速回答应用本身是否接近 4GiB；本地探索 | 明确标为近似，不能称为完整 4GB VPS |
| 整机预算近似 | 在更大宿主/VM 中把业务容器上限合计控制为约 2.6–3.2GiB，账面预留约 0.8–1.4GiB | 本地探索、候选前配置校准 | 只能模拟预算，不能复现真实 4GiB 主机的内核、页缓存和回收压力 |
| 整机实测 | 专用 2 vCPU / 4GiB 主机或 VM 同时承载 Linux、页缓存、网络、日志和业务容器 | 候选/发布容量和真实 VPS 选型 | 在真实总内存边界内设置逐服务上限，并采集宿主与容器指标 |

用户只说“2 核 4GB 服务器”时，目标语义默认是整机实测。暂时只能采用服务进程包络或整机
预算近似时，必须在结论第一屏说明并降低证据级别，避免把“容器最多可分配 4GiB”或“账面
预留系统内存”误写成“整台 4GB 机器已被完整模拟”。

Docker Compose 通常只能设置逐容器内存上限，不能方便地为整个 Compose 栈建立可借用的
共享父级 4GiB cgroup。因此报告必须列出每个服务的 limit、峰值和合计；若逐服务限制妨碍
空闲内存借用，也要列为模型偏差。

候选级和发布级要求在专用、与目标规格一致的主机或 VM 上执行整机实测（当前默认 Profile
为 `2 vCPU / 4GiB`），除非 Test Card 事前批准了可验证的等价父级资源边界。若仍在更大的
Docker Desktop VM 中仅靠逐容器上限近似，即使预留了系统余量，也只能形成探索性或候选前证据。

项目当前生产相似的一个参考分配是 MySQL `1400MiB`、Redis `384MiB`、App `768MiB`、
Nginx `128MiB`，合计 `2680MiB`。这是参考 Profile，不是所有测试必须照抄的永久配置。

容器启动后核验：

```bash
docker inspect <exact-container-name> \
  --format 'memory={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}}'
docker exec <exact-container-name> sh -c \
  'cat /sys/fs/cgroup/memory.max; cat /sys/fs/cgroup/memory.current; \
   cat /sys/fs/cgroup/memory.swap.max; cat /sys/fs/cgroup/memory.swap.current; \
   cat /sys/fs/cgroup/memory.events'
```

Profile 必须冻结宿主与容器 swap 策略。用于判断“4GiB 是否够用”时默认不允许 swap 隐藏内存
不足；若目标生产机明确使用 swap，则保持同一配置，并把 swap 峰值和延迟影响作为结果。任何
未声明的非零 swap 使用都会使该轮证据失效。

### 4.4 运行时一致性

- 不压 `uvicorn --reload` 开发进程，不开启测试覆盖率或调试 profiler。
- worker 数应与目标部署一致。调整 worker 是新 Profile，不能在 5 VU 和 10 VU 之间变更。
- 日志级别、连接池、gzip/Brotli、Nginx 缓存、Keep-Alive 和静态资源策略在同组比较中保持一致。
- 用 SQLite 得到的读延迟可以做本地探索；涉及生产连接池、锁、事务或写吞吐时必须使用
  MySQL 8，且不得用 SQLite 结果补齐发布证据。

### 4.5 负载发生器自身不能成为瓶颈

- 记录负载工具及版本；自定义 runner 记录源码 SHA-256，并随候选 artifact 或报告保留。
- runner 必须支持确定性随机种子、闭环 VU/固定到达率的明确语义、HTTP Keep-Alive、压缩、
  逐响应业务断言、原始下载字节和逐端点分位数。
- 时长和延迟使用单调时钟计算，墙钟只用于把容器日志、采样和报告时间对齐，并记录时区。
- 负载端的 CPU、内存、连接数和失败也要采集。它必须能在无带宽限制控制组中产生高于目标
  的吞吐；否则服务端“没有打满”可能只是客户端不够快。
- 本项目当前机器字段 `load_generator.process_cpu_percent_of_one_core` 保持兼容命名，但它
  实际采集的是整个 Runner Python 进程在测量窗口内的单核 CPU 口径：包含进程内负载
  生成和采样/编排开销，不是只计 HTTP 协程；`time.process_time()` 不包含 Runner 启动的
  Docker/`ps` 等子进程 CPU。新报告必须显式写明该口径，不得因字段旧名而将其解释为
  “纯负载协程 CPU”，也不得借口径澄清放宽已冻结的 `< 70%` 门槛。历史报告保持当时原文和结论。
- 本地探索可把负载端放在宿主机、服务放在 Docker cgroup 中；若同在一个 Linux 内核，至少
  使用不相交 cpuset。候选/发布级优先使用独立负载主机，并记录它到目标入口的 RTT、带宽和
  丢包，避免与服务端争用同一宿主资源。
- 客户端超时、连接池、重试和 HTTP 版本在对比组间固定。默认关闭自动重试；需要重试时按
  API 幂等契约单独统计首次尝试和重试，不把重试成功掩盖成零错误。

---

## 5. 聚合带宽和网络变量

### 5.1 单位与施加位置

本项目文档中的 `5Mbps` 固定表示十进制：

```text
5Mbps = 5,000,000 bit/s = 625,000 byte/s
```

它不是 `5MB/s`，后者相当于约 `40Mbps`。业务正文的可用吞吐会因为 TCP/IP、HTTP/TLS
头部低于 `625,000 byte/s`。

限速施加在 Nginx 面向客户端的服务端出方向，并位于 gzip/Brotli 处理后的网络路径。这样
所有 API 和源站图片共同分享一条 5Mbps 出口，符合小规格公网带宽的语义。

不得使用以下替代方案声称实现了聚合 5Mbps：

- 客户端 `curl --limit-rate`：限制的是单个客户端，不是服务端总出口；
- Nginx `limit_rate`：通常按请求/连接限速，10 个连接可能获得约十倍聚合带宽；
- 每个容器或每个网卡分别挂独立 5Mbps bucket：多条实际客户端出口会叠加；
- 宿主机全局 `pfctl`/`dnctl`：会影响用户其他任务，且难以精确归属和回收。

### 5.2 TBF 推荐配置

在隔离 Nginx 网络命名空间的 client-facing interface 上使用 Linux `tc` TBF：

```bash
tc qdisc replace dev <client-facing-interface> root handle 1: tbf \
  rate 5mbit \
  burst 128kbit \
  latency 400ms
tc -d -s qdisc show dev <client-facing-interface>
```

接口名不能凭 `eth0` 猜测。应根据测试客户端的路由、容器网络和压测前后网卡计数识别唯一
client-facing interface。若确有多条客户端出口，应先把拓扑收口到单一 edge 接口，或使用
能够对多接口聚合整形的方案；不能给每个接口各挂 5Mbps 后把合计称为 5Mbps。

标准 Nginx 镜像通常没有 `tc`，也不应直接获得 `NET_ADMIN`。本项目的可执行 Harness
使用只在当次测试期存在的 shaper helper：它通过
`network_mode: "service:<edge-service>"` 共享可销毁 edge 网络命名空间，以 `NET_ADMIN`
应用 TBF，并为 Runner 在测量期间持续读取 `tc -s -j qdisc` 状态而全程存活。这是为了
保留运行中 qdisc 证据而作的有意权限生命周期取舍，不是应用或 Nginx 容器的权限。
helper 不使用宿主网络、不发布端口，`NET_ADMIN` 的影响范围只限于该任务的
edge 网络命名空间，不得将其解读为宿主级网络权限。shaper 必须纳入当次
Compose project 的资源包络和回收清单；精确 Compose cleanup 会停止 helper，优雅退出时删除
qdisc，而 edge 网络命名空间销毁也会清除其中的限速状态，全程不修改宿主网络。

### 5.3 限速生效验证

仅看到配置命令返回 0 不算验证。正式测量前必须：

1. 保存 `tc -d -s qdisc` 的人类可读初始输出和 `tc -s -j qdisc` 的机器可读初始输出；
   Runner 必须解析并逐样本核对内核实际回报的 `rate=625000 B/s`（5mbit）、
   `burst=16000 B`（128kbit）与约 `400ms` latency；参数缺失、非法或漂移，或采样到的
   `bytes/packets/drops/overlimits/requeues` 累计计数回退，必须立即终止；
2. 对一个累计响应足够大的场景持续至少 30–60 秒；
3. 保存相同 qdisc 的结束输出和已解析参数；
4. 计算网络层实际平均速率；
5. 确认 `overlimits` 增长、`dropped=0`，并验证 5→10 并发不会让聚合吞吐翻倍。

网络层速率计算：

```text
Mbps = (after_bytes - before_bytes) × 8 ÷ elapsed_seconds ÷ 1,000,000
```

作为独立 sanity check，可通过同一 edge 下载一个不可压缩的测试资源，或让请求发送
`Accept-Encoding: identity` 并确认响应没有 `Content-Encoding`；同时确认实际 wire body
恰为 `5,000,000 bytes`。
在 5Mbps 下纯传输下界约 8 秒，实际应略高。若 10 个并发下载各自仍约 8 秒且聚合接近
50Mbps，说明误做成每连接 5Mbps。短请求会受 TBF burst 影响，不能用一次小响应推断长期带宽。

### 5.4 RTT、TLS、丢包和压缩

- 本地 localhost 的近零 RTT 不代表移动网络。需要模拟 30–80ms RTT 或丢包时，作为单独
  Profile 变量记录，不能只在某一个并发组临时加入。
- 发布级测试使用真实 HTTPS 终止位置和证书链；本地无 TLS 结果必须明确降级。
- 所有对比组冻结 `Accept-Encoding`。gzip、Brotli 和无压缩比较应分别建 Profile。
- `httpx.Response.content` 等通常是解压后内容，不能用于证明 5Mbps。使用客户端实际下载
  字节、Nginx body bytes 和 qdisc/网卡计数交叉核验。

---

## 6. 数据集、端点和缓存冻结

### 6.1 不在长期规范中写死易变 ID

每次执行前通过只读查询选择并记录：

- 商品列表第一页/后续页及返回条数；
- 当前最大 gzip JSON 的 Product/详情 ID、结构断言和压缩前后大小；
- 小型和大型 Kit、Experience Option 等代表对象；
- 合成用户的订单、预约和钱包数据分布；
- 图片数量、格式、P50/P95/max 大小与缓存 Header；
- 数据库关键表行数、Schema/Aerich 版本和一致性摘要。

某次报告中的 Product ID、221 色详情字节数或图片大小不得复制成永久规则。数据变化后重新
发现并冻结，保证测试仍覆盖最大和典型响应。

### 6.2 认证 persona

- 只读用户旅程使用 2–3 个固定合成 persona，分别覆盖有订单/钱包与有预约的数据。
- 测量前签发短期 access token，Token 只存在负载进程内；不在测量窗口反复登录。
- 登录、刷新、登出涉及 Redis、审计、bcrypt 或限流，应作为独立认证 Profile，不混入普通
  浏览结果。
- 每个认证响应都断言当前用户边界，不允许为了吞吐跳过权限和隐私检查。

### 6.3 缓存状态

必须明确以下状态，且 5 VU/10 VU 对比保持一致：

- 数据库页缓存：冷、预热后，或不控制；
- HTTP Keep-Alive：开启/关闭及连接池大小；
- 客户端图片缓存：冷时实际发起请求；暖时可能完全不发请求，须记录请求数/304；
- Nginx/CDN 缓存：MISS/HIT/REVALIDATED 分开，使用 `Age`、`X-Cache` 或平台等价证据核验；
- gzip/Brotli：算法和阈值；
- 静态资源是否命中源站、对象存储或 CDN。

不得清除宿主机全局页缓存。需要冷缓存时，只重建/清理本次任务拥有的数据库、代理缓存或
测试对象存储，并在两组之间执行完全相同的步骤。

---

## 7. 标准负载场景

### 7.1 默认场景矩阵

| ID | 场景 | 默认目的 | 最低执行 |
|----|------|----------|----------|
| LT-BASE | 无带宽整形、1 VU | 诊断控制组：建立应用/数据库基础延迟，不计入候选/发布正式组 | 60 秒预热 + 60 秒测量；若纳入正式 Gate 则稳态 300 秒 |
| LT-BROWSE-5 | 目标带宽、5 个闭环用户 | 正常/快速浏览基线 | 候选级稳态 300 秒，探索性可 30–60 秒 |
| LT-BROWSE-10 | 与上组相同、10 个闭环用户 | 验证 5→10 用户扩展性 | 同上 |
| LT-SAT-5 | 5 个持续在途最大响应、无思考时间 | 找到带宽或服务吞吐平台 | 探索性 60 秒；候选/发布级稳态 300 秒 |
| LT-SAT-10 | 10 个持续在途最大响应、无思考时间 | 验证吞吐平台与排队增长 | 探索性 60 秒；候选/发布级稳态 300 秒 |
| LT-IMAGE-COLD | 代表尺寸 WebP、冷缓存、客户端并行度受控 | 测真实图片冷启动体验 | 5/10 用户分别执行，至少三轮 |
| LT-IMAGE-WARM | 相同图片、暖缓存 | 验证缓存/CDN收益 | 与冷缓存配对 |
| LT-COMPAT-PNG-C/W-v3 | 旧客户端 221 色 PNG 页面加载，cold/warm 配对 | 验证兼容回退在 5/10 VU 的页面加载可用性，不负责饱和出口 | 每 VU 每 6 秒最多一次，每次严格 221 图、最多 4 连接；5/10 VU 配对 |
| LT-WRITE | MySQL 8 隔离写事务 | 验证事务、锁、幂等、吞吐与对账 | 独立 Profile，不与只读结论混写 |

不是每次都必须执行全部场景，但报告必须把未执行项标为 `Not Run`，不能留空或暗示覆盖。

### 7.2 浏览用户模型

使用闭环 VU 模拟“用户看完响应后继续操作”，而不是把 VU 数直接当固定 RPS。请求组合至少
覆盖列表、最大详情、典型详情；需要回答完整小程序体验时，再加入订单、钱包和预约只读接口。

建议默认思考时间为确定性随机种子下的 `1–3 秒`。为保守评估，可另建“快速浏览”Profile
使用 `0.4–0.6 秒`；报告必须明确它比真人阅读节奏更积极。请求权重、步骤顺序、随机种子和
每 VU 连接池在 5/10 用户间保持一致。

如果目标是固定到达率而不是用户旅程，使用 open model 并单独记录目标 RPS、爬升和丢弃/
排队策略；不得把 open model 的请求并发解释成用户数。闭环 VU 会在服务变慢时自动降低
到达率，可能产生 coordinated omission；用于验证固定需求/SLO 时必须补充 open model，并按
计划发送时间统计排队延迟。

### 7.3 饱和场景

饱和场景始终维持指定数量的请求在途，不设置思考时间，优先选择当前最大且业务真实的传输
编码后响应（gzip 时为压缩响应）。它用于验证带宽整形、最大吞吐和排队曲线，不代表同数量
真人的点击频率。

理想响应正文吞吐上界可作为 sanity check：

```text
理论请求上界 ≈ 625,000 byte/s ÷ 单响应 wire body bytes
```

实际 qdisc 吞吐包含协议开销，因此完成 RPS 应低于仅按正文计算的理想上界。

### 7.4 真实 WebP 图片场景

当前开发图片若只是几十或几百字节的占位资源，不能代表真实照片。发布容量判断至少准备：

- 首页缩略图：约 100KiB/张；
- 详情主图：约 200–300KiB/张；
- 较大但仍允许的上界样本：约 500KiB/张；
- 记录宽高、WebP 编码参数、内容摘要和 Cache-Control。

这些图片只进入隔离图片卷、测试对象存储或专用临时静态 namespace，不覆盖持久商品资源。
冷缓存组按真实客户端并行度（建议先从 4 开始并冻结）请求首页图片；暖缓存组使用相同资源。

221 个纯数字色块继续通过 API 的 HEX 和客户端 `backgroundColor` 绘制，不应在正常 Profile
中人为请求 221 张兼容 PNG。只有专门验证旧客户端回退时，才建立独立兼容 Profile。
当前可执行 C v3（`palette-page-load-v3`）将它冻结为“页面加载旅程”：每个 VU 每 6 秒
最多启动一次，一次
严格遍历 221 张冻结 PNG 且每图恰好一次，同一 VU 内不重叠两次页面加载，每 VU 最多
4 个图片连接，因此 5/10 VU 全局最多 20/40 个请求在途。cold 要求逐图 `200`、
PNG 类型、长度和 SHA-256 与冻结内容精确一致；warm 的 prime 排除在测量窗口外，窗口内
逐图要求 `304` 且正文严格为空。时间窗口到期或取消时必须 cancel/await 全部未完成图片请求，
只有完整 221 图旅程才计入完成数。
C v3 中，options 的 `ramp_seconds`、`warmup_seconds` 和 `duration_seconds` 始终表示完整的
palette-load 启动窗口，不包含 drain。编排器只对 C 的每个实际存在阶段在原启动窗口之后增加
最多 6 秒 completion drain：候选前 ramp/warm-up/measured 因此分别是 `20+6`、`60+6`、
`300+6` 秒。启动窗口结束后不得开始新 palette load，已经启动的旅程可以在 drain 内完成；
到 completion deadline 仍未完成时必须 cancel/await、保留部分证据并 terminal `FAIL`，不能
把它软化为容量门槛失败。drain 不从原窗口扣除，不减少 VU、6 秒启动节奏或请求负载。
A/B/D 不增加该 drain。

Test Card 和报告必须分开记录 options 中的启动窗口、Profile setup 的
`palette_start_window_seconds`/`completion_drain_seconds`，以及实际总阶段时长。C measured 的
资源监控覆盖启动窗口和 drain；只允许启动窗口截止前已经开始的整页旅程在 drain 内继续，
这些请求仍属于原 measured Profile，不得另建或混入下一 Profile。

plan 和新报告必须在配置内矩阵时长下界中计入每个实际存在 C 阶段的 6 秒：默认探索完整
矩阵从 780 秒增加到 804 秒；候选前 36 Profile/三轮固定矩阵从 14,832 秒增加到 14,976 秒
（`4:09:36`）。该估算仍不包含构建、迁移、prime、最终对账和冷却扩展。

C v1 的每 VU 四连接无停顿 `304` 无限循环不是真实旧客户端页面重载节奏。零正文响应
没有打满 5Mbps，却将主要压力放在 Runner 响应头、时序与采样处理上，因此不能作为
服务端容量证据。历史 run `20260909t022930` 的 FAIL 和原始 artifact 保持不变，不得以 v2/v3
语义追溯改写，也不得与新轮次拼接成 PASS。

C v2（`palette-page-load-v2`）专指已有真实页面旅程、但 warm-up/measured 没有 completion
drain 的历史策略。run `20260909t040400` 先保留了 A identity/10 的容量失败并继续，随后
C-cold/10 在完整 60 秒启动窗口共启动 80 个整页旅程，只完成 70 个并在边界留下 10 个未完成，
因此作为不完整 Profile 立即终止；该 run 的 `FAIL`、8/12 已记录 Profile 和 artifact 必须
原样保留。这是工具 deadline 边界发现，不是可以回算的服务容量结论。
聚合 5Mbps 饱和由 A 的持续大 JSON 请求单独证明；C v3 只回答兼容 PNG 页面加载是否在
5/10 VU 下保持可用。

带宽下界应直接写入报告。例如 `N` 个用户同时下载每人一张 `S` byte 图片：

```text
最低传输时间 ≈ N × S ÷ 625,000
```

这一下界尚未包含 API、协议、TLS、RTT、重传和其他图片，不能通过增加 CPU 消除。

### 7.5 写事务场景

订单创建、库存扣减/恢复、钱包支付/退款和预约等写路径必须与只读压测分开：

1. 使用可销毁 MySQL 8+ 和隔离 Redis/图片存储，不用 SQLite 证明并发锁语义；
2. 冻结合成账号、初始余额、库存、订单状态、预计流水和 Audit 数量；
3. 只对已有幂等契约的操作按契约重放相同 key；相同 key 必须复验完整业务意图；
4. 对没有客户端幂等键的 POST，网络结果未知时先查询事实，不自动重发；
5. 真实支付、退款、微信通知和其他 Provider 保持关闭或使用正式 sandbox，不产生真实资金/
   消息；
6. 每个故障、超时和数据库重试路径都验证整事务原子性，不只统计 HTTP 状态；
7. 测后执行库存、钱包、Payment/Settlement/Refund、订单、预约和 Audit 对账；任何差异使
   本轮失败；
8. 清理优先销毁整个任务数据库/卷，不通过未经验证的反向业务写“还原”数据。

写 Profile 必须记录 MySQL `Threads_connected`、`Threads_running`、锁等待、死锁/1205/1213、
连接池等待、慢查询与关键查询计划。SQLite 只读报告不得补充或替代这些指标。

### 7.6 预热、稳态、顺序与重复

候选级和发布级默认每组：

```text
爬升 10–30 秒 → 预热 60 秒（丢弃） → 稳态 300 秒 → 冷却/排队清空 30 秒
```

正式结果运行三轮并交替顺序，降低缓存、温度和宿主后台负载造成的偏差：

```text
第 1 轮：5 VU → 10 VU
第 2 轮：10 VU → 5 VU
第 3 轮：5 VU → 10 VU
```

报告采用三轮中位数作为代表值，同时保留最差一轮的 P95/P99、错误和资源峰值。轮间至少
等待 30 秒并确认 qdisc 队列、连接和应用任务回到基线。单轮 30 秒只能标为探索性。

---

## 8. 请求断言与可用性

负载脚本不能只统计 HTTP 200。每类请求至少断言：

- HTTP 状态符合预期；
- 统一响应信封 `code == 0`，或命中预先声明的预期业务拒绝；
- ID、分页、条数、枚举、必要字段和边界数据符合冻结数据集；
- 最大颜色详情的颜色数、规范 `#RRGGBB` 和公开字段完整；
- 认证接口不返回其他用户数据或管理字段；
- 图片 `Content-Type`、正文非空、长度/摘要和缓存策略符合 Profile。

预期 4xx/业务拒绝应进入专门的负向场景，不能混入成功吞吐后从错误数中扣除。

以独立连接每 5–10 秒探测 `/api/v1/health/ready`。readiness 不计入业务 RPS 和延迟分位数，
但任何失败必须单独记录并按门槛处理。若 liveness 与 readiness 的语义不同，两者均采集。

---

## 9. 指标与统一计算口径

### 9.1 必采指标

| 层级 | 指标 |
|------|------|
| HTTP 全局及逐端点 | 完成数、RPS、旅程数、P50/P90/P95/P99/max、TTFB、下载时间、超时、连接错误、HTTP 非预期状态、业务错误、断言失败 |
| 响应体 | 实际压缩算法、wire body bytes、解压正文 bytes；最大/典型响应分别记录 |
| Edge/网络 | client-facing qdisc 前后 bytes、实际 Mbps、overlimits、drops、队列、网卡 bytes、连接数；可用时记录 TCP 重传 |
| 服务资源 | App/MySQL/Redis/Nginx 各自及合计 CPU、`memory.current`/peak、OOM、swap、restart、文件描述符 |
| 宿主资源 | 整机 CPU、可用内存、swap、memory/CPU/IO pressure、磁盘空间；整机实测时为必采 |
| 存储 | 数据库/图片卷 IOPS、读写吞吐、await/延迟、队列、fsync/flush 和空间水位 |
| App | readiness/liveness、错误/Traceback、事件循环或 worker 阻塞、连接池等待 |
| MySQL | QPS、连接、running threads、锁等待、死锁、1205/1213、慢查询、关键 EXPLAIN |
| Redis | ops、连接、内存、eviction、错误/超时 |
| 数据 | 前后表行数、业务不变量、SQLite integrity/FK 或 MySQL Schema/对账结果 |

所有容器指标建议每秒采样一次。采样器本身在服务包络之外，并记录采样间隔、缺失点和时钟。
服务栈合计内存峰值应取每个采样时刻的 `sum(memory.current)` 再求最大值，不能把发生在不同
时刻的各容器独立 peak 简单相加；独立 peak 仍作为逐服务诊断数据保留。

### 9.2 计算公式

```text
RPS = 稳态窗口内已完成请求数 ÷ 稳态秒数

错误率 = 非预期失败请求数 ÷ 总请求数 × 100%

N 核包络 CPU 占用 =
  cgroup CPU usage 增量 ÷ (墙钟时间 × N) × 100%

网络 Mbps =
  client-facing qdisc bytes 增量 × 8 ÷ 墙钟秒数 ÷ 1,000,000
```

`docker stats` 的 CPU 百分比常以单核 100% 为单位。对于共享两核，服务栈合计 200% 才是
两核满载；报告应换算成“两核包络百分比”，同时保留原始值，避免把 100% 误读为两核全满。

延迟分位数只用稳态窗口内已完成请求计算，错误和超时另列，不能把超时样本静默丢弃。全局
分位数容易被高频小接口掩盖，必须同时给出逐端点 P95/P99 和样本量，并记录负载工具采用的
分位数算法。

### 9.3 字节口径

至少保留三层字节，不能混称“流量”：

1. 解压后的 JSON/图片正文：反映客户端处理数据量；
2. 客户端实际下载的传输编码后响应正文：用于估算单响应带宽成本；
3. qdisc/网卡网络字节：用于证明服务端聚合 5Mbps，包含协议开销。

三者数值不同是正常现象。压缩收益用第 1/2 层比较，公网限速用第 3 层判断。

---

## 10. 默认通过门槛

以下是 `2 核 / 4GiB / 聚合 5Mbps / 5–10 VU` 的项目默认起点。每次 Test Card 可以根据
真实 SLO 收紧，但必须在执行前冻结；放宽时要写明业务理由。图片冷启动和写事务使用各自
Profile 的端点级门槛，不机械套用 JSON 延迟。

| 类别 | 默认门槛 |
|------|----------|
| 功能正确性 | 业务断言失败、非预期 4xx/5xx、连接错误和超时均为 0 |
| 可用性 | readiness 全程成功；无 worker/container restart；无 FATAL/Traceback |
| 10 VU JSON 延迟 | 全部目标 JSON P95 ≤ 800ms，P99 ≤ 2s，max < 5s |
| 扩展性 | 非饱和浏览 Profile 中，10 VU 吞吐至少为 5 VU 的 1.7 倍，且 P95 不超过 2 倍并仍满足绝对门槛 |
| CPU | 稳态平均 < 两核容量的 70%；不得连续 30 秒高于 85% |
| 内存 | 合计峰值 < 声明内存包络的 80%；后半段相对前半段不持续增长超过 10%；`memory.events` 的 `high/max/oom/oom_kill` 不增长；无持续 swap |
| 正常网络 | 稳态一分钟平均 < 4.25Mbps（5Mbps 的 85%）；持续 30 秒 > 4.5Mbps 视为临界/不通过 |
| 带宽校验 | 饱和 Profile qdisc 平均约 4.75–5.05Mbps，overlimits 增长，drops=0；并发翻倍不应突破聚合上限 |
| 数据库/Redis | 无连接池耗尽、非预期锁超时/死锁、慢查询突增、Redis eviction 或依赖错误 |
| 数据完整性 | 只读前后业务数据不变且完整性通过；写 Profile 全部余额/库存/状态/流水/Audit 对账一致 |
| 重复性 | 候选/发布级三轮均满足硬门槛；报告中位数并披露最差一轮，不删除异常轮 |

饱和 Profile 的吞吐平台本身不是失败：它用于定位极限。若出口稳定约 5Mbps、CPU 较低、并发
增加后吞吐不再增长而延迟上升，应判定“带宽上限已被正确找到”；只有把这种流量误归为正常
用户 Profile，或正常 Profile 也长期接近上限时，才表示目标规格不够用。

门槛一旦失败，报告结论为 Fail 或 Inconclusive。不得用全局平均延迟、删除最差轮、缩短窗口
或提高客户端超时来改成 Pass。

第 2.4 节白名单内的“测后容量失败”可以在严格 checkpoint/cooldown 后继续采齐诊断矩阵，
但这不改变上句的判定：Profile 和整轮仍为 Fail。`profile_execution.matrix_complete` 只回答
是否采齐，`verdict` 才回答是否达到门槛。terminal 失败或安全检查失败仍须立即停止。

---

## 11. 瓶颈诊断矩阵

| 现象 | 优先判断 | 进一步核验 |
|------|----------|------------|
| qdisc 约 5Mbps、CPU低、大响应下载时间增长 | 聚合出口带宽 | overlimits、drops、wire bytes、TTFB 与下载时间 |
| 出口未满、两核持续 >85% | App 计算、压缩或日志 | 各容器 CPU、worker、gzip 开销、事件循环 |
| App CPU不高、MySQL running/锁等待/慢查询上升 | 数据库或连接池 | EXPLAIN、连接池等待、行锁和云盘延迟 |
| 内存持续增长、队列和超时同步增加 | 缓冲积压或泄漏 | memory.current/peak/events、连接队列、GC/worker |
| 只有最大 JSON 慢，TTFB正常、下载时间长 | 响应体/带宽 | 压缩比、wire bytes、qdisc 速率 |
| 所有接口 TTFB 都升高，下载时间正常 | App/数据库排队 | CPU、事件循环、连接池、慢查询 |
| 5 VU正常，10 VU 吞吐不增且 P95 超过 2 倍 | 已进入某项饱和区 | 按 CPU、网络、数据库、Redis逐层定位 |
| 冷图片慢、暖图片快、JSON正常 | 源站图片/CDN/缓存 | 图片大小、命中率、Cache-Control、并行度 |
| qdisc 明显超过 5Mbps | 限速位置/口径错误 | client-facing interface、是否每连接/每接口限速 |
| 客户端正文吞吐低于 5Mbps但 qdisc 已满 | 协议开销正常或响应过小 | 对比 wire body 与 network bytes，不先归因 App |

需要区分计算与带宽时，可在同一隔离栈先跑短暂的无限带宽控制组，再应用 TBF 执行正式组。
两组除带宽外必须完全相同，并分别记录，不能把控制组结果混入正式分位数。

---

## 12. 结果判定与不可外推边界

每份报告必须明确写出：

1. 本 Profile 通过、失败或因证据失效而无法判断；
2. 5→10 用户时吞吐、P95/P99、CPU、内存和网络如何变化；
3. 首个饱和资源及支持证据；
4. 当前规格在哪种流量/图片/写事务条件下会不够；
5. 可以支持的结论和不能支持的结论；
6. 若失败，下一次只改变哪个变量，以及为什么。

以下外推默认无效：

- SQLite 只读 → MySQL 写并发；
- ARM64 Docker Desktop → x86 云主机单核性能；
- localhost HTTP → HTTPS、公网 RTT、移动网络和丢包；
- 77–583 byte 占位图 → 100–500KiB 真实 WebP；
- 10 个闭环用户 → 10 个持续并发请求或某个固定 RPS；
- 单轮 30 秒 → 五分钟稳态、峰值小时或长期运行；
- 当前版本/数据量 → 未来代码、索引、数据规模或缓存状态；
- 源站带宽结果 → 已启用对象存储/CDN后的终端体验，反之亦然。

---

## 13. 报告与证据模板

### 13.1 文件规则

每次正式执行新建文件，不覆盖旧证据：

```text
docs/09_release/reports/<environment>_<profile>_load_test_<YYYY-MM-DD>.md
```

例如本地探索为 `local_2c4g_5mbps_load_test_2026-09-08.md`。同一天多次独立执行时在 profile
中加入安全、稳定的 run 标识，避免覆盖。

Git 中只提交脱敏后的 Test Card、汇总、必要日志摘要、结论和 artifact digest。大体积逐请求
原始数据、完整容器日志和监控导出放入批准的受控 artifact 存储，并记录 URI、SHA-256、
保留期和访问边界；没有受控存储时明确写“未保留”，不得虚构证据。

### 13.2 报告正文模板

```markdown
# <环境> <Profile> 容量压测报告（YYYY-MM-DD）

> **结论：** PASS / FAIL / INCONCLUSIVE + 一句话原因
> **证据级别：** 探索性 / 候选级 / 发布级
> **执行规范：** capacity_load_test_runbook.md @ <Last Updated>
> **执行身份：** HEAD / diff digest / image ID / architecture / CI artifact
> **执行时间：** 开始–结束，含时区
> **矩阵执行：** recorded / scheduled、matrix_complete、capacity_failed_profile_count
> **失败处置：** continuation policy 版本；继续采集不等于通过

## 1. 目标、授权与隔离边界
## 2. Test Card 与相对 Runbook 的偏差
## 3. 拓扑、资源和网络限额的生效证据
## 4. 数据集、响应大小、缓存和压缩
## 5. 场景、断言、预热、稳态、轮数和顺序
## 6. 逐场景/逐端点结果、失败 gate 与 disposition
## 7. CPU、内存、网络、数据库、Redis 和日志
## 8. 数据完整性与写事务对账
## 9. 通过门槛逐项判定
## 10. 容量结论、首个瓶颈和不可外推范围
## 11. 原始 artifact、摘要和保留期
## 12. 资源回收与复核
```

报告中资源表至少包含配置上限、实测平均/峰值和阈值；结果表同时给出样本量、RPS、错误、
P50/P95/P99/max、wire body、network Mbps、Profile verdict、failure disposition 和失败 gate。
C Profile 还必须分列 options 启动窗口、setup 的 completion drain、总阶段时长、started/
completed/incomplete palette loads；任何 incomplete 都是 terminal failure，不能仅从完成数中扣除。
顶层还必须列出计划/已记录 Profile 数、矩阵是否完整、容量失败 Profile 数，以及每项的
Profile/round/VU/checkpoint/cooldown/是否实际进入后续 Profile。任何 Runbook 偏差都在结果前披露。

---

## 14. 资源回收与复核

### 14.1 执行前建立所有权清单

记录本任务创建或接管的：

- Shell/PTY/负载发生器/采样器 PID 与进程树；
- Compose project、容器、helper、镜像标签/ID；
- 网络、卷、数据库 Schema/实例、图片 namespace；
- loopback 端口、临时目录、Secret 文件、结果和锁/PID 文件；
- 明确属于用户、不得停止的既有服务。

### 14.2 清理顺序

1. 先停止新负载，等待或终止在途请求；
2. 停止 readiness/资源采样和辅助进程，按 PID/会话复核进程树退出；
3. 保存最后的 qdisc、cgroup、日志、数据完整性与对账摘要；
4. 使用精确 Compose project 优雅停止 App、Nginx、Redis、MySQL 和 helper；
5. 仅删除该 project 明确拥有的容器、网络、卷、临时镜像和 namespace；
6. 删除任务创建的临时数据库、图片、配置和 Secret 目录；Secret 优先安全清理；
7. 按 exact name、label、PID、端口和路径复核无残留；
8. 复查用户既有 Uvicorn、Redis、Taro 等服务仍健康且未被改动。

以下命令只展示精确项目清理形式。实际执行前必须把示例名称替换为本轮已经人工核验的唯一
名称，且确认它不属于其他任务：

```bash
docker compose \
  --project-name pinkdoohub-perf-20260908t120000 \
  --file <base-compose> \
  --file <perf-override> \
  down --timeout 20 --volumes --remove-orphans

docker ps -a \
  --filter label=com.docker.compose.project=pinkdoohub-perf-20260908t120000
docker volume ls \
  --filter label=com.docker.compose.project=pinkdoohub-perf-20260908t120000
docker network ls \
  --filter label=com.docker.compose.project=pinkdoohub-perf-20260908t120000
lsof -nP -iTCP:<exact-test-port> -sTCP:LISTEN
```

前三项复核应不返回该 project 的资源，测试端口应无 listener。qdisc 随任务 edge 网络命名
空间销毁；不得为“清除限速”修改宿主网络。

若用户明确要求保留某个测试环境，报告必须列出保留资源的 exact name、用途、访问方式、
所有者和后续停止方法。无法安全确认归属的资源不得猜测性强杀，应在报告中列为残留风险。

---

## 15. 快速复用清单

### 执行前

- [ ] 容量问题、证据级别、Profile 和通过门槛已冻结
- [ ] 当次环境授权明确，持久/共享/生产目标默认拒绝
- [ ] Git/diff/untracked、镜像 ID、架构和工具版本已记录
- [ ] run_id、容器、卷、网络、端口、临时目录和资源所有者唯一
- [ ] 数据库、Redis、图片和合成 persona 完全隔离
- [ ] 两核共享语义、4GiB 包络语义和 worker 数已核验
- [ ] client-facing 聚合 5Mbps 已通过 qdisc 计数和持续流量验证
- [ ] gzip/Brotli、TLS、RTT、缓存、图片大小和随机种子已冻结
- [ ] 负载发生器与采样器是否计入资源包络已写明
- [ ] 停止条件、数据对账和清理路径可执行
- [ ] continuation policy 已事前冻结；未知 gate 默认终止，继续采集不改变最终失败

### 执行中

- [ ] 预热数据未混入稳态统计
- [ ] 每个响应执行 HTTP、业务信封和数据断言
- [ ] readiness 独立持续探测
- [ ] 每秒采集 CPU、内存、网络、restart/OOM 及依赖指标
- [ ] 逐端点记录样本量、延迟、错误和 wire body bytes
- [ ] C v3 分列 options 启动窗口、setup drain、配置/实测总阶段与 started/completed/incomplete；drain 未从原窗口扣除
- [ ] 未出现停止条件；若出现，已先停负载并保留证据
- [ ] 白名单容量失败继续前已完成严格对账、日志/statement 检查和连续两次安全 cooldown

### 执行后

- [ ] 三轮中位数与最差轮均保留，失败轮未删除
- [ ] Profile verdict 与执行 disposition 分列；matrix_complete 未被写成 PASS 的同义词
- [ ] qdisc 实际速率、overlimits、drops 与流量公式已核验
- [ ] 只读数据不变，或写事务余额/库存/状态/流水/Audit 全量对账
- [ ] 报告明确首个瓶颈、适用结论和不可外推范围
- [ ] 原始 artifact 已脱敏并记录 digest/保留期，或明确未保留
- [ ] 任务进程、容器、网络、卷、镜像、端口和临时目录已精确回收并复核
- [ ] 用户既有服务保持健康；有意保留或无法安全清理的资源已列明
