# Phase 9.3 隔离演练环境冻结记录

> **Status:** Topology and Tooling Frozen — Candidate Commit / Execution Evidence Pending
> **Frozen At:** 2026-08-31（Asia/Shanghai）
> **Owner / Executor / Reviewer / Decision Role:** Yijie Shen（执行和复核仍分步记录）

本文冻结 Phase 9.3 在当前 Mac Docker Desktop 上的生产相似、可销毁环境。它不授权连接生产、共享数据库、微信后台或真实用户数据。实际写操作前，仍必须把候选改动形成用户批准的 Git commit，取得干净工作树并通过自动预检。

## 1. 当前只读盘点

| 项目 | 冻结值 / 结论 |
|------|---------------|
| Docker Engine / Client | 29.7.2 / 29.7.2 |
| Docker Compose | v5.4.0 |
| Host architecture | arm64 |
| MySQL image | `mysql:8.0.46`，本机已有；实际执行记录 immutable image ID/digest |
| Redis image | `redis:8.0.1-alpine`，本机已有；实际执行记录 immutable image ID/digest |
| App base image | `python:3.10.9-slim-bullseye`，执行前拉取并记录 digest；3.10.9 没有对应的 Bookworm 官方标签 |
| HTTPS image | `nginx:1.27.5-alpine`，执行前拉取并记录 digest |
| 磁盘 | 约 842 GiB 可用，满足双 MySQL/备份/镜像需求 |
| 已有用户资源 | `pinkdoohub-dev-redis` / `127.0.0.1:6379`，不接管、不复用、不停止 |
| 候选 Git 基线 | `d714f1c70c200dc52a702660d1c6cdf4ef77768b`；9.3.1–9.3.4 尚未 commit，禁止作为正式演练 SHA |

## 2. 冻结拓扑与资源命名

所有容器、网络和 volume 统一由唯一 Compose project `pinkdoohub-phase93-<run-id>` 创建；清理只允许针对记录中的精确 project label，不按通用镜像名或进程名批量操作。

```text
Host 127.0.0.1:18443
        │ TLS（任务专属短期 CA / SAN=pinkdoohub-phase93.test）
        ▼
Nginx HTTPS
   ├── /api、/docs 等 → FastAPI/Uvicorn :8000（不暴露宿主端口）
   └── /uploads/products → 只读挂载 product_images volume
                                  ▲
FastAPI ──写图片──────────────────┘
   ├── mysql-source:3306
   └── redis:6379

Host 127.0.0.1:14307 → mysql-restore:3306（独立 volume / 独立恢复实例）
```

| 资源 | 宿主绑定 | 业务标识 | 持久性 |
|------|----------|----------|--------|
| Source MySQL 8.0.46 | `127.0.0.1:14306` | `pinkdoohub_phase93_source` | 专属 named volume，演练后删除 |
| Restore MySQL 8.0.46 | `127.0.0.1:14307` | `pinkdoohub_phase93_restore` | 与 Source 不共享 volume，演练后删除 |
| Redis 8.0.1 | `127.0.0.1:16379` | 独立认证 + AOF volume | 演练后删除 |
| HTTPS | `127.0.0.1:18443` | `pinkdoohub-phase93.test` | 短期 CA/证书仅在任务临时目录 |
| App | 无宿主端口 | production 配置语义、非 root UID 10001 | image 与容器可销毁 |
| Product images | 仅经 HTTPS 读取 | app 读写、Nginx 只读 | 独立 volume，必须备份/恢复验证 |

MySQL、Redis、App 与 Nginx 共享的 `rehearsal` network 设置为 `internal: true`；只有 Nginx 额外挂入非 internal 的 `edge` network，以便 Docker 实际发布 `127.0.0.1:18443`。所有入口仍只绑定回环地址，不绑定 `0.0.0.0`，不修改 `/etc/hosts`。Host 验证统一用 `curl --resolve pinkdoohub-phase93.test:18443:127.0.0.1 --cacert <task-ca>`。

## 3. 配置与 Secret

- App 使用 `APP_ENV=production`、`APP_DEBUG=false`、MySQL、HS256、绝对 HTTPS 图片 URL，真实执行 production fail-fast 分支。
- DB、Redis、JWT、初始及轮换后 SUPER_ADMIN Secret 由运行工具生成到任务专属 `/tmp/pinkdoohub-phase93/<run-id>`，目录权限 0700、文件权限 0600；报告只记录 Secret 文件类别和校验状态，不记录值或 hash。
- MySQL 使用 `*_PASSWORD_FILE`；App entrypoint 从 `/run/secrets` 读取并只导出到当前进程环境；Redis 从 Secret 文件生成容器内临时配置，不把密码写进 Compose、命令参数或证据。
- 初始 SUPER_ADMIN 使用合成身份 `phase93_owner` / `13800009301`；密码只挂载到一次性 Bootstrap service。完成真实登录和轮换/撤销记录后，删除 Secret 文件。
- TLS 私钥和 CA 只属于本次演练，不进入 Git、CI artifact 或正式信任链。

## 4. 合成数据与场景边界

- 只创建 `phase93_` 前缀或 `[PHASE93]` 标记的合成用户、Product、Order、Inventory、Audit 和图片。
- Source 与 Restore 实例都不得包含现有开发 SQLite、用户开发 Redis 或任何真实用户导出。
- DR-01～DR-07 与 DR-09 服务端部分在本环境执行；DR-08 和微信真机/合法域名部分保持 Phase 9.4。
- 受控迁移失败只作用于独立失败场景/备份副本，不在已通过 Smoke 的唯一 Source 上直接试验。

## 5. 冻结停止条件

出现以下任一情况立即停止写操作并保全证据：

- 工作树不干净、候选 SHA/源码 digest 与记录不一致；
- 任一计划端口已占用，或发现同名/同 label 非本次资源；
- 目标不是回环地址、端口为 3306、数据库名不精确匹配上述值；
- Docker volume/network/container 所有者无法由 project label 证明；
- Secret 目录权限不安全，或日志/报告出现 Secret、连接串、Token；
- 独立恢复失败、Schema/Aerich/行数/业务聚合漂移；
- Readiness、Bootstrap、图片持久化、事务/库存/审计任一断言失败；
- 资源清理目标无法精确解析。

## 6. 证据与时间目标

原始证据目录固定为 `/tmp/pinkdoohub-phase93/<run-id>/evidence`，不进入仓库。最终只把脱敏摘要写入 `docs/09_release/reports/`。

| 目标 | 冻结值 |
|------|--------|
| 计划维护/停写窗口 | 本地专用环境，无其他写入者；每个写场景开始前重新确认 |
| 最大单步无进展时间 | 10 分钟，超过即停止并调查 |
| 备份恢复目标 RTO | 10 分钟以内 |
| 合成数据 RPO | 备份点之后 0 条预期保留写入；恢复按备份点比较 |
| 沟通/决策记录 | 当前 Codex 任务 + 最终脱敏报告 |
| 清理 | 无论成功/失败均停止精确 Compose project，删除其 containers/network/volumes 和任务 Secret/cert 临时目录；复核四个端口关闭 |

## 7. 写操作前未满足项

- [ ] 用户授权形成候选 Git commit；工作树 clean；记录最终 SHA；
- [x] 编排、预检、备份恢复、受控失败、HTTPS Smoke、脱敏摘要和精确清理工具已实现，并通过 50 项发布工具契约；完整项目回归仍在候选提交前执行；
- [ ] 四个镜像拉取/构建成功并记录 digest；
- [ ] 自动预检确认端口、项目名、目标身份、Secret 权限和证据目录；
- [ ] 对 DR-05 故障注入、恢复/覆盖和最终删除 volumes 的精确目标取得执行时授权。
