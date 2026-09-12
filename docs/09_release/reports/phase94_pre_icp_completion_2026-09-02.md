# Phase 9.4 备案前 Gate A 收口报告

> **Result:** PASS（不依赖备案的自动化、持久主机和治理范围）
> **Gate A Decision:** No-Go / Not Authorized
> **Execution Date:** 2026-09-02
> **Runtime Candidate:** `51ad3152c8960bc133c25a600418f5f850d69199`
> **Operations Candidate:** `c4d27a8f20c5527e58665b4983ca0ed16ffb2954`

本报告只关闭备案前可以客观完成的 Gate A 工作：备份保管、异机加密副本、依赖故障与
应用重启、日志安全与查询、测试运营规则，以及不可发布的微信预 RC 构建。它不把保留
`.test` Origin 当作真实域名，不把开发者工具或自动化当作真机证据，也不授权上传、
分发、提审或公开发布。

## 1. 候选与 CI

| 项目 | 结果 |
|------|------|
| 运维实现 | `b69ee74f5f3bff14a2c651b3c8a0c900f40d456f` |
| 实现 CI | GitHub Actions Run 33584388085，8/8 Job `success` |
| 恢复修复 | `c4d27a8f20c5527e58665b4983ca0ed16ffb2954` |
| 修复 CI | GitHub Actions Run 33584789525，8/8 Job `success` |
| 应用 Runtime | 继续使用已经迁移、Bootstrap、代表性数据和恢复验证的 `51ad315...`；本次未重建或替换应用镜像 |

两次 Operations 候选都没有修改业务 API、OpenAPI、数据库 Schema/Aerich、依赖、应用
版本或 Runtime image。服务器只切换版本化运维源码软链接，长期应用数据与镜像身份保持
不变。

## 2. 加密异机备份

代表性非空 Backup `20260902t014211z` 已从来源主机按精确 ID 导出到管理电脑，并在
写入后立即完成一次完整解密与固定 Tar 成员复核。

| 断言 | 结果 |
|------|------|
| 来源 Restore Record | `passed=true` |
| 加密 | AES-256-GCM；随机数据密钥 |
| 密钥封装 | RSA-3072 / OAEP-SHA256 |
| key ID | `595d864b7c45c7cfa26a03184085e36bd6f304c929fe1a9c69d0b580f6bcfcae` |
| 加密副本 | 14,319 bytes；SHA-256 `940a5433641f044983b09f23134fb4eefb043fe7cefde19f390f256f99239931` |
| 权限 | 副本 `0400`、Record `0600`、私钥 `0600`、副本/密钥目录各 `0700` |
| 密钥隔离 | 私钥只在独立密钥目录；不在服务器、副本目录、仓库、日志或 Record |
| 存储加密 | 管理电脑 FileVault 已开启 |
| 导出后验证 | AEAD、Tar 白名单、四个来源文件大小/SHA、Backup/Restore PASS 全部通过 |
| 数据最小化 | Record 明确 `pii_recorded=false`、`secret_values_recorded=false` |

保管规则同步冻结为：测试期最长 24 小时 RPO、计划停写 RPO 0、30 分钟 RTO、来源与
管理电脑至少最近 7 个成功 Backup、停用后至少 30 日、脱敏 Record 至少 90 日、每个
RC 及活跃期每月恢复。工具不提供自动删除；任何删除、来源覆盖恢复、删 Schema 或删卷
都需要精确目标和单独授权。

## 3. 持久主机韧性与可观测性

### 3.1 首次执行发现的问题

实现候选第一次真实执行已完成 MySQL 停止/恢复、Redis 停止/恢复和 App 重启，但最终
收敛误用了“首次启动”帮助函数。该帮助函数正确要求 loopback 端口在首次启动前空闲，
而演练期间 Nginx 本来就应继续占用该端口，因此最终步骤产生了工具层假失败。

- 数据库和三张图片在失败前后没有被删除或改写；
- 四个长期服务独立复核均为 Healthy，liveness/readiness 均为 200；
- 没有写成功 Record，也没有把部分结果误报为 PASS；
- 修复改为幂等 Compose `up --wait` 恢复既有 edge，并增加“已有 loopback publisher”
  回归测试；修复提交经过 Run 33584789525 的 8/8 CI 后才重跑。

### 3.2 纠正版结果

纠正版演练从 2026-09-02 10:56:35 到 10:57:10（Asia/Shanghai）完成：

| 场景 | 故障时 readiness | 故障时 liveness | 服务恢复 | readiness 恢复 | 结果 |
|------|------------------|-----------------|----------|------------------|------|
| MySQL 停止/启动 | 503 | 200 | 5.671 s | 0.003 s | PASS |
| Redis 停止/启动 | 503 | 200 | 5.539 s | 0.005 s | PASS |
| App 重启 | N/A | N/A | 5.637 s | 0.003 s；总计 6.168 s | PASS |

恢复后数据库摘要和图片 manifest 均与演练前完全一致，图片文件数仍为 3；MySQL、Redis、
App、Nginx 全部 Healthy，liveness/readiness 为 200，唯一业务 publisher 仍精确绑定
`127.0.0.1:18080`。成功 Record 为 `root:root 0644`，SHA-256 为
`8138e75985836b350f5d285907c28667354d81a36ee8781d4fc7bb97b7a7ca43`。

四个长期容器均验证 Docker `json-file`、`max-size=10m`、`max-file=5`。24 小时窗口扫描
519 行组合日志，解析到 1 条 Nginx 请求，4xx/5xx 均为 0，median/p95/max 均为
0.002 秒；四项真实 Secret 精确匹配和高置信敏感模式匹配均为 0。成功 Record 只保存
聚合指标，不保存原始日志、IP、URI、User-Agent、身份或 Secret。

## 4. 微信备案前预 RC

本地在干净 Git 候选 `c4d27a8...` 上使用 Node 24.13.0、npm 11.6.2 和 Taro 4.2.1
完成以下备案前检查：

- `npm ci` 按锁文件重装；已知 npm 公告继续由现有精确、到期的依赖策略处理；
- 61 个 Jest suites / 387 tests、TypeScript、ESLint、Stylelint、OpenAPI 类型漂移和
  17 项 Node CI policy tests 全部通过；
- 使用 `production` 构建模式和保留的 `https://api.pre-icp.pinkdoohub.test` Origin，
  明确设置 `WEAPP_RELEASE_ELIGIBLE=0`；
- 产物 97 个文件，主包 425,532 bytes、`admin` 分包 178,092 bytes、总计 603,624
  bytes；0 source map，未命中 Secret、本机地址、占位域名或 H5-only marker；
- manifest SHA-256 为
  `aeb81ef46338424575f1e36fc77848cab345dafc099a2dd22717e3a2ba098bc1`，
  `project.config.json` SHA-256 为
  `0c9d34336b46bbdb82b511838bced106454e9028a61a312ea6e33d6beecb47db`；
- manifest 明确记录 `artifact_kind=wechat-ci-non-release`、
  `release_eligible=false`，不能被用作真实 Gate A RC。

微信开发者工具 Stable 2.02.2608060（Electron 36.6.0）已加载仓库 `miniapp/` 并完成
普通编译，模拟器成功渲染首页和预期的可恢复错误态。权威项目配置确认
`miniprogramRoot=dist/weapp/`、`urlCheck=true`、`uploadWithSourceMap=false` 且目标 AppID
已配置。检查时发现被忽略的本机 `project.private.config.json` 把 `urlCheck` 覆盖为
`false`；已只将该本机设置恢复为 `true` 并重新编译。

重新编译后的两条 Console Error 都精确说明保留的 `.test` Origin 不在 request 合法域名
列表中，证明域名校验已经开启并 fail closed；没有编译错误。其余提示是灰度基础库
3.17.2 和开发者工具内部 preload warning。编辑器还提示 Taro 测试链的间接
`miniprogram-api-typings@3.12.3` 旧于 5.2.3，但上游依赖约束仍为 3.x，当前 TypeScript、
Jest 和构建全部通过，因此没有为消除编辑器提示强行跨主版本覆盖；真实 RC 按当日稳定
基础库和 Taro 兼容范围重新冻结。检查没有调用预览、上传或登录命令，也没有修改微信
后台；完成后已退出本轮启动的工具并复核相关进程/监听均不存在。

## 5. 治理冻结

- 初始测试人员、allowlist、内部不可公开声明、14 日测试窗口和延长规则已冻结；
- 普通反馈使用 GitHub Issues，敏感信息只走既有私密渠道；P0 立即停测，P1 在下一会话
  前关闭或形成严格例外；
- 停用前要求最终备份、隔离恢复和加密异机副本；停用后保留 30 日恢复观察窗口；
- 测试、技术、发布、安全与事故责任人已映射；发现、复核、风险接受和恢复授权仍分别
  记录，不能因同一人承担多个角色而合并；
- Gate A 文件型 Secret 的路径、权限、读取主体、轮换/泄漏触发和备份私钥隔离已冻结；
  Gate B 的集中 Secret Manager、主动告警和高可用图片存储仍是独立后续门槛。

## 6. 仍受备案/HTTPS/真机阻塞的项目

下列项目没有执行，也没有被本报告标记为 PASS：

1. 真实 `pinkdoohub.cn` API/图片 Origin、DNS、证书签发与续期验证；
2. 微信后台 request/upload/download 合法域名；
3. 使用真实 Origin 重新生成 `release_eligible=true` 的同 SHA RC；
4. 微信开发者工具体验版上传与分发（还需要单独外部操作授权）；
5. iOS/Android 真机、Wi-Fi/移动网络、弱网/断网、前后台/锁屏、上传中断和 unknown
   mutation 收敛；
6. Gate A 全矩阵人工证据、缺陷关闭和正式 Go/No-Go 签署。

因此结论是：**Phase 9.4 的备案前服务器、自动化、备份和治理范围 PASS；整个 Gate A
仍为 No-Go / Not Authorized。**

## 7. 资源与保留

- 纠正版投放 archive/launcher 以及首次失败的旧投放文件均已从服务器删除；本地任务
  archive、launcher 和临时 Node Runtime 在文档与最终验证完成后删除；
- 演练没有创建临时容器、网络或卷；四个长期 Gate A 服务、三个持久卷、服务器同机
  Backup/Records 以及管理电脑加密副本/独立密钥按 Gate A 目的有意保留；
- 未连接开发 SQLite、共享 3306 或未知数据库，未开放公网业务端口，未修改 DNS、证书、
  微信后台、体验版、审核或发布状态。
