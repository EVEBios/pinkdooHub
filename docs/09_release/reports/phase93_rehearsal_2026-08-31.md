# Phase 9.3 隔离发布演练报告

> **Result:** PASS（Phase 9.3 服务端范围）
> **Run ID:** `20260831t221625`
> **Candidate SHA:** `136a8bd8833f9b23433cfb3a2f9ceca7dab70db5`
> **CI:** [GitHub Actions Run 33408135841](https://github.com/EVEBios/pinkdooHub/actions/runs/33408135841)，8/8 Job success
> **Executed At:** 2026-08-31（Asia/Shanghai）
> **Executor / Reviewer:** Yijie Shen

本报告是 Phase 9.3 的脱敏、可提交证据摘要。原始日志、数据库备份、图片备份、短期 CA、Secret 和场景目录只存在于任务专属临时目录，演练结束后已删除。报告不包含密码、Token、私钥、连接串或真实用户数据，也不授权微信后台变更、体验版上传、提审或公开发布。

## 1. 候选与隔离边界

- 候选工作树在准备时为 clean，manifest、Compose digest 和应用镜像 revision 均锁定上述 Git SHA。
- 固定运行环境为 Python 3.10.9、Docker/Engine 29.7.2、Compose 5.4.0、MySQL 8.0.46、Redis 8.0.1、Nginx 1.27.5；应用镜像以非 root UID 10001 运行。
- 唯一 Compose project 为 `pinkdoohub-phase93-20260831t221625`；Source/Restore MySQL、Redis、Source/Restore 图片卷和所有场景 Schema 都是本次运行专属资源。
- 宿主只使用 `127.0.0.1:14306/14307/16379/18443`。MySQL、Redis、App 和 Nginx 共享 internal `rehearsal` network；只有 Nginx 同时加入 `edge` network 并发布回环 HTTPS。
- 未连接默认 MySQL 3306、开发 SQLite、持久/共享/生产数据库或微信后台；既有 `pinkdoohub-dev-redis`（127.0.0.1:6379）未复用、未停止、未修改。

## 2. 场景结果

| 场景 | 结果 | 关键证据 |
|------|------|----------|
| DR-01 空库 0→当前 | PASS | Aerich 0→1→2；10 表、90 列、26 约束、63 条统计/索引记录；业务表为空 |
| DR-02 migration 0→当前 | PASS | 用户、2 Product、Option、Kit、2 Audit 与 stock=7 保持；生成唯一 opening balance `change=after=7` |
| DR-03 migration 1→当前 | PASS | 1 Order、2 Items、`160.00` Order/Item 快照总额、3 Audit 与库存保持；opening balance 正确 |
| DR-04 备份/独立恢复 | PASS | 数据库备份 155,302 bytes；独立 Restore MySQL/图片卷数据一致；restore-app Ready，轮换后账号登录成功 |
| DR-05 受控迁移失败 | PASS | 证明 MySQL DDL 部分提交：新表存在、Aerich 仍为 m1、opening balance 未写；从失败前备份恢复后官方 m2 升级通过 |
| DR-06 应用与依赖 | PASS | Liveness/Readiness、MySQL/Redis 分别故障 503 与恢复 200、优雅重启、图片持久化均通过 |
| DR-07 SUPER_ADMIN | PASS | 首次创建成功；重放不创建第二账号/Audit；登录、唯一性和凭据轮换通过 |
| DR-08 微信真机网络 | Deferred | 明确属于 Phase 9.4；本报告不把服务端 HTTPS 当作 iOS/Android 真机证据 |
| DR-09 服务端纵向 Smoke | PASS | 经真实 Nginx HTTPS 完成 32 个请求，覆盖 Guest、用户、ADMIN、SUPER_ADMIN、禁用用户和关键业务链 |

DR-09 的业务链包含 Product/Option/Kit、三类图片上传与静态读取、Inventory 调整与幂等重放、混合订单及取消恢复、Paid/Completed、权限拒绝、Refresh、禁用后的旧 Access/Refresh 失效，以及 SUPER_ADMIN 凭据轮换。全部请求通过短期 CA 校验的 `https://pinkdoohub-phase93.test:18443` 进入 Nginx，没有直接访问 App 宿主端口。

## 3. 恢复与故障数据

- DR-04 数据库备份 SHA-256：`8644b575feb483ef20cfe710c87399846203c84ab8ee6975323004218a13c9cd`；恢复耗时 3.197 秒。
- DR-04 同时比较 Source/Restore 图片 manifest 与内容哈希，并以独立 restore-app 验证启动、Readiness 和登录；验证后 restore-app 已停止。
- DR-05 失败前备份耗时 3.122 秒，独立恢复耗时 3.203 秒；恢复副本的业务数据与 m1 基线一致，官方 migration 2 完成后 Aerich/Inventory 断言通过。
- DR-06 分别停止并恢复 Source MySQL、Redis，Readiness 在故障期返回安全 503，依赖恢复后重新 Ready；应用重启后 Product/Order/Inventory/图片状态保持。

## 4. 演练中发现并关闭的问题

真实执行没有绕过失败，而是先清理失败轮次，再修复、加测试、提交、推送、等待新 SHA 的 8/8 CI，最后从空环境重跑：

1. `python:3.10.9-slim-bookworm` 官方标签不存在；改为已实际拉取并记录 digest 的 `python:3.10.9-slim-bullseye`，并增加 Dockerfile/镜像清单一致性断言。
2. Compose one-off service 错用不支持的 `--environment`；改为 Compose v5 的 `--env`，并增加参数防回归测试。
3. m1 合成订单号不符合 `OD + 26 位 Crockford Base32`；改为固定合法编号并直接用领域长度/正则测试。
4. Nginx 只加入 internal network 时 Docker 未实际发布宿主端口；新增仅 Nginx 使用的 `edge` network，并增加“只有 HTTPS 可加入 edge”的拓扑断言。

最终候选的 release 工具契约为 53 项通过，完整 GitHub Actions 为 8/8 success。

## 5. 清理与结论

- Compose project 的容器、网络和 named volumes 已通过精确 project label 删除；四个任务端口全部释放。
- `/tmp/pinkdoohub-phase93/20260831t221625` 中的备份、合成数据、短期 CA/私钥、Secret 和原始日志已删除；任务应用镜像 `pinkdoohub-phase93:20260831t221625` 已删除并复核不存在。
- 共享基础镜像缓存保留；用户已有 `pinkdoohub-dev-redis` 仍在 127.0.0.1:6379 运行，未被本任务接管。

Phase 9.3 的服务端隔离演练完成，R-004、R-006、R-011 的关闭证据成立。Gate A 仍是 **No-Go / Not Authorized**：Phase 9.4 还需冻结真实测试 Origin、DNS/证书和微信 request/upload/download 合法域名，并完成 iOS/Android 真机、弱网/断网、前后台和真实 RC 证据。DR-08 未执行，任何微信上传、体验版分发、提审或公开发布仍需单独授权。
