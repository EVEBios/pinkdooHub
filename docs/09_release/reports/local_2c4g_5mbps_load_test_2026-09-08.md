# 本地 2 核 / 4GiB / 5Mbps 容量探测报告（2026-09-08）

> **结论：** 当前 gzip JSON API 在 5–10 个快速浏览用户下余量充足；持续请求 221 色详情时，5Mbps 出口先于 CPU、内存到达上限
>
> **证据级别：** 本机 ARM64 + Docker Desktop + 隔离 SQLite/Redis 的单轮探索性测试，不是生产 MySQL、云主机或发布容量门槛
>
> **规范映射（事后归档）：** 本报告先于 [容量与性能压测 Runbook](../capacity_load_test_runbook.md) 成文；其实际执行对应探索性“快速浏览 + 单端点带宽饱和”Profile
>
> **规范偏差/证据缺口：** 每组仅一轮 30 秒、服务进程 4GiB 包络、SQLite、无 TLS/RTT/真实 WebP；只冻结了 untracked 文件清单摘要，没有 build context/untracked 内容摘要，也未保留临时 runner/config digest 与随机种子；因此不升级为候选级或发布级证据
>
> **执行基线：** HEAD `d33527659d2af0aa1551d669dbac15a4dfbe6323`，tracked diff SHA-256 `77cf558614bcb91d1ab4bfcd56f27317146bf682bfd2ed465b425ea40325ec9b`，untracked-list SHA-256 `13ab983dd23a02b7c3e070d31ed2daf9a3223426d87a6edadd0960fb93c78eba`
>
> **执行时间：** 2026-09-08 21:41–21:56 +08:00

## 1. 目标与隔离边界

本轮回答两个问题：当前项目在 `2 核 / 4GiB / 聚合 5Mbps` 包络下，5 个和 10 个用户快速浏览是否稳定；当用户不等待、持续请求最大的 221 色 JSON 时，首先到达的瓶颈是什么。

压测没有访问 `127.0.0.1:8000` 的 `--reload` 开发进程，也没有向持久 `db.sqlite3` 写入。运行时使用 SQLite Backup API 取得 M8 数据库隔离副本，单独启动 Redis、单 Uvicorn worker 和 Nginx/TBF 代理。只请求公开读 API；订单、库存、钱包、认证和预约写链路不在本轮范围。

拓扑如下：

```text
宿主 httpx 负载发生器（不计入服务资源）
    → 127.0.0.1:18082
    → Nginx + tc/TBF 聚合 5Mbit/s
    → 单 Uvicorn worker，无 reload
    → 隔离 SQLite M8 副本 + 隔离 Redis 8.0.1
```

应用镜像从当前工作区构建为原生 `linux/arm64`，镜像 ID 为 `sha256:eec401ebdf182eb7bf02d12b3c4ec7ebbb1a0a14638e6c3e1111bb3100a498d5`。它包含未提交 M8 工作区内容，只能作为本地探索性证据，不能映射成可复现发布 SHA。

## 2. 资源与限速模型

三个服务容器均设置 `cpuset=0-1` 和最多 2 CPU，因此它们可以在同两颗 Docker vCPU 上共享空闲算力，但总体不能离开这两颗 CPU。内存上限为：

| 服务 | 内存上限 |
|------|---------:|
| App + SQLite | 3.5GiB |
| Redis | 256MiB |
| Nginx/TBF | 256MiB |
| 合计 | 4GiB |

Docker Desktop VM 本身仍为 10 CPU / 约 7.75GiB；本轮只对任务容器施加上述 CPU 集合和内存上限，没有修改会影响用户现有容器的 Docker Desktop 全局设置。因此，这是“服务进程 cgroup 包络”的近似，不包含真实 4GB Linux 主机的内核、云盘和其他守护进程竞争。

Nginx 外部网卡使用 Linux TBF：

```text
rate    5Mbit/s
burst   16KiB
latency 400ms
```

`5Mbps` 按十进制等于 `625,000 bytes/s`。正式饱和窗口中，qdisc 实测为 `5.000–5.001Mbps`，`overlimits` 持续增长、`dropped=0`，证明全部连接共享同一出口上限，而不是每连接各有 5Mbps。

本轮未附加公网 RTT、丢包或 TLS 成本。

## 3. 流量模型

所有业务请求使用 HTTP keep-alive、`Accept-Encoding: gzip`，并验证 HTTP 200 与统一响应 `code=0`。每 5 秒通过独立连接请求一次 readiness；readiness 不计入业务请求数。

### 3.1 快速浏览用户

每个闭环用户依次循环：

1. `GET /api/v1/products?page=1&page_size=10`
2. `GET /api/v1/products/kit/14`（221 色，gzip 线传 9,913 bytes）
3. `GET /api/v1/products?page=2&page_size=10`
4. `GET /api/v1/products/kit/19`（3 色）

每次响应后等待 `0.4–0.6s`，分别运行 5、10 个用户，各 30 秒。这个节奏比真实阅读/选择颜色更积极，但仍保留用户思考时间。

### 3.2 221 色详情持续饱和

始终保持 5 或 10 个 `GET /api/v1/products/kit/14` 请求在途，不设置思考时间，各运行 30 秒。这是带宽上界测试，不代表 5 或 10 个真人的正常点击频率。

## 4. 结果

### 4.1 快速浏览用户

| 指标 | 5 用户 | 10 用户 |
|------|-------:|--------:|
| 完成请求 | 291 | 583 |
| 吞吐 | 9.55 req/s | 19.12 req/s |
| 错误率 | 0% | 0% |
| 全局 P50 | 12.67ms | 12.83ms |
| 全局 P95 | 30.42ms | 33.98ms |
| 全局 P99 | 34.99ms | 56.00ms |
| 最大延迟 | 56.92ms | 63.81ms |
| 221 色详情 P95 | 32.28ms | 40.36ms |
| 网络层吞吐 | 0.276Mbps | 0.549Mbps |
| 5Mbps 占用 | 5.5% | 11.0% |
| 服务栈平均 CPU | 13.42% 单核单位 | 21.45% 单核单位 |
| 折合两核平均占用 | 6.71% | 10.73% |
| 服务栈 CPU 峰值 | 15.44% 单核单位 | 25.12% 单核单位 |
| 内存峰值 | 103.59MiB | 104.81MiB |
| readiness 失败 | 0/7 | 0/7 |

从 5 人增加到 10 人后，请求吞吐几乎精确翻倍，P95 仅增加约 11.7%，没有进入 CPU、内存、数据库或网络饱和区。

### 4.2 持续饱和 221 色详情

| 指标 | 5 个持续请求 | 10 个持续请求 |
|------|-------------:|--------------:|
| 完成请求 | 1,721 | 1,724 |
| 吞吐 | 57.20 req/s | 57.16 req/s |
| 错误率 | 0% | 0% |
| P50 | 87.10ms | 174.63ms |
| P95 | 104.50ms | 191.22ms |
| P99 | 107.84ms | 195.20ms |
| 最大延迟 | 128.07ms | 262.13ms |
| gzip 正文吞吐 | 4.536Mbps | 4.533Mbps |
| qdisc 网络吞吐 | 5.000Mbps | 5.001Mbps |
| qdisc 丢包 | 0 | 0 |
| TBF overlimits | 12,946 | 13,743 |
| 折合两核平均 CPU | 27.63% | 26.75% |
| 服务栈 CPU 峰值 | 57.28% 单核单位 | 64.38% 单核单位 |
| 内存峰值 | 104.64MiB | 106.48MiB |
| readiness 失败 | 0/6 | 0/6 |

并发从 5 翻倍到 10 后，吞吐没有增加而 P50 约翻倍；同时出口精确保持 5Mbps，CPU 与内存仍低。这是清晰的网络带宽平台，不是应用计算或内存不足。即使在该饱和条件下，10 个持续请求的业务 P95 仍低于 200ms，且无 HTTP/业务错误。

## 5. 稳定性与数据核验

- 四个正式测量窗口合计完成 4,319 个业务请求，HTTP/业务错误均为 0。
- readiness 共 26 次，全部 HTTP 200、`code=0`。
- App、Redis、Nginx 均 `restart=0`、`OOMKilled=false`。
- 三个容器的 cgroup `memory.events` 均为 `low/high/max/oom/oom_kill=0`。
- App、Proxy、Redis 日志中的 ERROR/Traceback/FATAL 计数均为 0。
- 隔离 SQLite 测后 `integrity_check=ok`、外键违规 0、订单仍为 8、非空 HEX 仍为 221，确认压测只读。
- 持久 `db.sqlite3` 同样保持完整、订单 8、非空 HEX 221；主 `8000` 服务与用户原有 Redis 保持健康。

## 6. 容量判断

在当前数据和 API 形态下，5–10 个实际用户不是这套规格的风险点。即使每人约每 0.5 秒完成一次列表或详情请求，10 人也只使用约 11% 的 5Mbps 出口、约 11% 的两核容量和约 105MiB 内存。

当前 221 色响应的真实网络上限约为 `57 req/s`。持续超过这一速率不会提高吞吐，只会排队；10 个持续请求已体现为 P50 从约 87ms 增长到 175ms。若流量结构不变，长期接近 4.5–5Mbps，或增加并发后吞吐不再增长而延迟近似线性上升，即可判定公网出口不足。

更早造成 5Mbps 不够用的会是真实商品照片，而不是 HEX/JSON：

- 10 人同时各下载一张 200KiB WebP，纯传输下界约 `3.28s`；
- 10 人同时各下载一张 300KiB WebP，纯传输下界约 `4.92s`；
- 10 人冷启动、每人下载 10 张 100KiB 首页缩略图，总带宽下界约 `16.38s`。

上述时间尚未包含 TCP/TLS、移动网络 RTT 和其他 API 流量。因此维持“数字色块只传 HEX”，并把真实商品照片/未来实拍色样放到对象存储/CDN、设置长期缓存，能比继续优化这 221 色 JSON 带来更大的实际收益。

## 7. 不能从本轮推出的结论

- SQLite 只读结果不能证明生产 MySQL 的连接池、写锁、事务或云盘能力。
- 本轮没有压订单、库存、钱包、退款或预约写接口，不能给出写事务 TPS。
- 当前 Product 图片是 77–583 byte 的合成占位资源，不能当作真实 WebP 图片性能证据。
- 本机 ARM64 Docker Desktop 与未来云主机 x86 CPU、网络和磁盘不同。
- 每组只有一轮 30 秒测量，适合当前容量判断，不是需要三轮中位数和 5 分钟稳态的正式发布门槛。
- 本轮没有注入公网 RTT、TLS、丢包、移动端解码或 CDN 缓存变量。

如进入发布容量验收，应在目标架构上使用 MySQL 8、真实大小 WebP、HTTPS 和 30–80ms RTT，按 5→10、10→5、5→10 顺序各跑三轮；写链路另用隔离账号和可对账幂等场景测试。

## 8. 资源回收

任务专属 App、Redis、Nginx/TBF 容器均已优雅停止并删除；任务卷、网络、ARM64 App 镜像、隔离数据库、临时 runner/config 和 `18082` 监听均已删除或释放。没有修改宿主 `pfctl/dnctl` 或 Docker Desktop 全局资源。用户原有 `pinkdoohub-dev-redis`、`8000` Uvicorn、Taro watcher 和微信开发者工具均保持不动。
