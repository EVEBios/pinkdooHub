# M8 HEX 色块与压缩本地联调报告（2026-09-09）

> **Local Integration Result:** PASS
>
> **Release Decision:** BLOCKED / No-Go
>
> **Evidence Date:** 2026-09-09（Asia/Shanghai）
>
> **Branch / Base HEAD:** `feature/phase9-ci` / `4e745848315aab56805a872ecf5b9f5e3c10135b`
>
> **Evidence Boundary:** 当前本地工作区，包含 Base HEAD 之后尚未形成干净 SHA 的发布保护差异

## 1. 结论与范围

本轮确认本地持久 SQLite 已处于完整、可幂等重放的 M8 状态；221 色公开商品详情与
冻结 MARD manifest 的槽位、色号、名称、HEX 和兼容 PNG 文件名逐项一致；FastAPI 的
大 JSON gzip 协商、生效阈值与图片旁路符合当前设计；后端定向回归、Demo 数据核验、
钱包只读对账、前端完整测试和微信非发布构建检查均通过。

因此，规划中的“本地 M8 落库”和“本地 API/小程序工程联调”可以判定为本地通过。
本报告不把这些结果外推到 Gate A、共享、预发布或生产环境，也不把 CI 占位 Origin
构建、2026-09-08 微信开发者工具模拟器证据写成真实 RC、体验版或 iOS/Android 真机验收。

## 2. 本地 SQLite M8 与数据完整性

### 2.1 幂等 preview / apply

2026-09-09 对当前本地持久 `db.sqlite3` 执行 M8 专用工具 preview，结果为：

| 检查项 | 结果 |
|--------|------|
| `colors` | `221` |
| `column_present` | `true` |
| `missing_hex_values` | `0` |
| `already_current` | `true` |
| 模式 | `preview` |

随后显式执行一次安全 `--apply` 重放。工具再次返回 `already_current=true`、
`result=success`，并报告 `backup=not-created-already-current`。这是已达目标状态时的预期
零写入路径：本次没有 ALTER、回填或其他数据库写入，也没有创建一份内容完全相同的新
备份。2026-09-08 首次本地 M8 升级及其写前 `0600` 备份仍以
[changelog](../../05_development/changelog.md) 中的历史记录为准，不能与本次 no-op 重放
混为一次新的迁移。

### 2.2 只读完整性与冻结数据核验

使用 SQLite 只读连接复核后的结果如下：

| 检查项 | 结果 |
|--------|------|
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | `0` 条违规 |
| `bead_colors` 行数 | `221` |
| 非空 `swatch_hex` | `221` |
| 唯一 `swatch_hex` | `221` |
| HEX 格式 | 全部为规范大写 `#RRGGBB` |
| 槽位范围 | `1..221`，无缺槽 |

本轮还从真实本地 API 读取公开 `GET /api/v1/products/kit/14`，将响应中的 221 个颜色与
版本化 [`mard_221.json`](../../../app/tasks/manifests/mard_221.json) 逐项比较。`slot_no`、
`color_code`、`name`、`swatch_hex` 及 `swatch_image_url` 对应的兼容 PNG 文件名全部精确一致。
这证明公开契约已实际使用 M8 HEX；兼容 PNG 仍存在，但不再是数字色块的首选渲染来源。

## 3. API 压缩与媒体旁路

所有请求都命中用户已经启动的本地 FastAPI 服务；本轮没有重启、替换或接管该进程。

### 3.1 221 色商品详情

同一 `GET /api/v1/products/kit/14` 响应分别按禁用和启用 gzip 读取：

| 请求方式 | HTTP | `Content-Length` | `Content-Encoding` |
|----------|------|-----------------:|--------------------|
| `Accept-Encoding: gzip;q=0` | `200` | `42,571` bytes | 无 |
| `Accept-Encoding: gzip` | `200` | `9,913` bytes | `gzip` |

gzip 线传正文减少 `32,658` bytes，约 `76.7%`；响应同时包含
`Vary: Accept-Encoding`。解码后的 JSON 与上一节逐项核验使用的是同一公开业务数据。

### 3.2 阈值与图片类型

| 资源 | 正文大小 | 类型 | 压缩结果 |
|------|---------:|------|----------|
| `GET /api/v1/health/live` | `75` bytes | 小型 JSON | 未压缩 |
| 兼容色块 PNG | `582` bytes | `image/png` | 未压缩 |

这两项分别验证了小于 1 KiB 的响应不为压缩增加额外成本，以及 PNG 不进入文本 gzip
链路。它们不等同于 Brotli、真实商品 WebP、CDN 缓存或公网 HTTPS 性能测试。

## 4. 后端与本地代表数据验证

| 验证项 | 结果 |
|--------|------|
| 本轮定向后端回归 | `95 passed` |
| `local_demo_seed --verify` | PASS |
| `wallet_reconcile` | `scanned=11 mismatches=0 violations=0` |

Demo verifier 与钱包 reconcile 都是核验步骤；reconcile 全程只读且没有自动修账。本轮未向
持久本地库写入联调订单、钱包流水或库存调整。2026-09-08 已完成的颜色订单/取消库存恢复
和代客钱包支付/幂等重放使用的是隔离数据库副本，见第 6 节，不能写成本轮对持久库的写入
测试。

## 5. 小程序工程与非发布构建

本轮前端验证结果为：

| 验证项 | 结果 |
|--------|------|
| Jest | `84 suites / 573 tests` 全部通过 |
| TypeScript | 通过 |
| ESLint | 通过 |
| Stylelint | 通过 |
| OpenAPI 生成类型漂移检查 | 通过 |

为恢复精确锁文件依赖执行了 `npm ci`；其产物位于被忽略的依赖目录，相较执行前没有改变
`git status`。

微信 production-mode 代码检查构建得到：

| 项目 | 值 |
|------|---:|
| 文件数 | `141` |
| 主包 | `650,646` bytes |
| `admin` 分包 | `408,353` bytes |
| 总计 | `1,058,999` bytes |
| manifest SHA-256 | `231a712643cbd76bde7c70606d52acc2f1f0178e6ee6687b4f048b768a9c4c17` |
| `release_eligible` | `false` |

该 manifest 明确使用 `git_sha=local-uncommitted`、`workflow_run_id=local` 和保留的
`https://api.ci.pinkdoohub.test` 占位 Origin。它只证明当前源码可构建、包体和语义检查
通过；不是绑定真实 HTTPS Origin 的 RC，也没有执行微信预览、上传、体验版分发或提审。

## 6. 2026-09-08 历史人工与隔离联调证据

以下证据来自 2026-09-08，作为当前自动化和 API 复核的前序证据引用；它们没有在
2026-09-09 重新录制：

- 微信开发者工具模拟器成功显示 221 色商品并以 HEX 直接绘制；选择 A1 时没有请求该色的
  兼容 PNG，控制台为 0 error。
- 颜色 Kit 下单后取消能够恢复库存；代客钱包支付与幂等重放通过。
- 写链路使用当前库的隔离副本，测试结束后隔离服务和临时数据库已清理，没有向持久
  `db.sqlite3` 写入测试订单。

权威摘要保存在 [changelog 的 M8 条目](../../05_development/changelog.md)。该历史
“开发者工具模拟器通过”不能替代真实 iOS/Android 真机、真实网络栈或本轮逐页网络面板
截图。

## 7. 未关闭项与发布判断

本轮仍未关闭：

1. 真实 HTTPS Origin、DNS/证书和微信 request/upload/download 合法域名。
2. 绑定干净候选 SHA、真实 Origin 且 `release_eligible=true` 的 RC。
3. 微信体验版上传/分发授权，以及 iOS、Android 真机矩阵。
4. 2026-09-09 逐页开发者工具网络请求截图；当前只有 API 抓取、自动化及
   2026-09-08 模拟器历史证据。
5. 当前未提交发布保护差异形成干净 SHA 后的完整远端 CI 与同 SHA 隔离 MySQL updater
   门槛。
6. Gate A 的新 Backup/独立 Restore、当次明确写授权、M7→M8 持久升级和 M8 数据后恢复。
7. 新版 2 核 / 4 GiB 容器包络 / 聚合 5 Mbps / 5–10 VU 探索矩阵已按
   [容量与性能压测 Runbook](../capacity_load_test_runbook.md)执行并完整采集认证读、兼容 PNG
   冷/热缓存及订单/库存/钱包写链路；其中 10 VU 持续未压缩色板 JSON 触发容量门槛，整轮
   为 `FAIL`。详见
   [独立压测报告](m8_local_2c4g_5mbps_load_test_2026-09-09.md)；仍待干净 SHA candidate-pre
   三轮和独立 Linux 主机验收。

所以当前结论严格为：**M8 本地前两阶段 PASS，整体发布继续 No-Go。** 本报告没有触碰
Gate A，也不授予数据库迁移、Runtime 切换、微信上传、分发、提审或公开发布权限。

## 8. 资源边界与回收

- 复用了用户此前已启动的本地 Uvicorn 与 Redis，仅做请求和健康检查；本任务没有取得
  所有权，也没有停止或修改它们。
- `npm ci` 仅恢复被忽略的本地依赖；验证后没有产生新的工作树差异。
- 本轮没有启动容器、临时数据库、代理、隧道、浏览器自动化或其他长驻服务，也没有新增
  需要回收的端口、PID、网络或卷。
- 因没有创建或接管新的长驻资源，本轮无额外任务资源需要停止；用户既有服务按原状态
  保留。
