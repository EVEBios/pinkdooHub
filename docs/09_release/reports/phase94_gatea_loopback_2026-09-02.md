# Phase 9.4 Gate A Loopback 首次部署报告

> **Result:** PASS（持久 Gate A 主机的 loopback 生命周期范围）  
> **Runtime Candidate:** `51ad3152c8960bc133c25a600418f5f850d69199`  
> **Runtime CI:** [GitHub Actions Run 33568184860](https://github.com/EVEBios/pinkdooHub/actions/runs/33568184860)，8/8 Job success  
> **Operations Revision:** `17114d7278860c0e09901f493280a56bf6043c3f`  
> **Operations CI:** [GitHub Actions Run 33568983950](https://github.com/EVEBios/pinkdooHub/actions/runs/33568983950)，8/8 Job success  
> **Executed At:** 2026-09-02（Asia/Shanghai）  
> **Executor / Reviewer:** Yijie Shen

本报告只证明真实腾讯云 Gate A 主机上的持久 MySQL、Redis、App、图片卷和
loopback Nginx 已完成首次部署。当前没有启用 DNS/HTTPS、微信合法域名、体验版
上传或真机验收，因此 Gate A 仍是 **No-Go / Not Authorized**。报告不包含密码、
Token、私钥、连接串或 Secret 值。

## 1. 候选与环境边界

- 主机为 Ubuntu 24.04.4 LTS、Linux 6.8.0-138、Docker 29.7.2、Compose 5.5.0；
  主机名为 `pinkdoohub-gatea-nj-01`，时区为 `Asia/Shanghai`。
- Runtime candidate 的归档 SHA-256 为
  `09b57edaac572054871d0cc88b48c1522ba8547662966d82cca5927f7fdfa5fa`，
  App image ID 为
  `sha256:13a08366bc5644b6a63e6b209b1d8bcfc48452549cc2ae1a70554c1c07f07a1b`。
- Operations revision 的归档 SHA-256 为
  `1584ff3567ff9038d0e074eda2eeb60b1d649fe8ba84a18e64e7bd2880fab7b6`。
  该提交只修改宿主运维脚本、测试和 changelog；本地 Git diff 与服务器逐文件
  比较均确认 `app/`、`migrations/`、依赖清单、Runtime Dockerfile 和 Entrypoint
  与 runtime candidate 完全一致。因此首次迁移记录继续绑定 `51ad315...` App
  image，没有伪造或复制成另一个候选的迁移记录；`17114d7...` 只作为本次已过
  CI 的运维控制版本执行最终 `app-up`。
- 所有归档、CI Run、Image ID 和首次迁移结果均写入 root-owned、`0644` 的发布
  Record。配置与 Secret 值未进入仓库、命令参数、报告或普通用户可读输出。

## 2. 首次迁移与持久资源

- 固定 named volumes 为 `pinkdoohub-gatea-mysql-data`、
  `pinkdoohub-gatea-redis-data` 和 `pinkdoohub-gatea-product-images`；本次没有执行
  `down --volumes`、删卷或清空持久数据。
- `initial-migrate` 在 application schema 为 0 张表时才运行，顺序应用：
  `0_20260810101218_init.py`、`1_20260813130455_add_order_tables.py`、
  `2_20260814104655_add_inventory_transactions.py`。
- 迁移后只读核验为 10 张表：`aerich`、`audit_logs`、`experience_options`、
  `inventory_transactions`、`order_items`、`orders`、`product_images`、
  `product_kits`、`products`、`users`；Aerich 版本正好为上述 0→1→2 三条记录。
- 首次迁移记录原子绑定 runtime candidate SHA 与 Image ID；非空数据库没有再次
  执行初始化迁移。

## 3. 运行时与网络结果

| 检查 | 结果 | 证据摘要 |
|------|------|----------|
| MySQL | PASS | MySQL 8.0.46 Healthy；无宿主端口 |
| Redis | PASS | Redis 8.0.1 Healthy；认证启用；无宿主端口 |
| App | PASS | Healthy；UID/GID `10001:10001`；只读根文件系统；`no-new-privileges`；无宿主端口 |
| 图片卷 | PASS | `image-init` 一次性成功；App 内 `/data/images` 为 `pinkdoo:pinkdoo 0755` |
| Nginx | PASS | Nginx 1.27.5 Healthy；唯一绑定 `127.0.0.1:18080 -> 8080/tcp` |
| Liveness | PASS | 经 Nginx loopback 返回 HTTP 200 / `alive` |
| Readiness | PASS | 经 Nginx loopback 返回 HTTP 200；database/redis 均为 `up` |
| 公网边界 | PASS | 80/443/3306/6379/8000/18080 均无公网 listener；从公网地址访问 18080 失败 |

最终采样时 MySQL、Redis、App、Nginx 合计使用约 428 MiB 容器内存；主机可用
内存约 2.5 GiB，Swap 基本未使用，根盘剩余约 49 GiB（使用率 15%）。这只是
当前空载基线，不替代后续并发、容量或长期趋势观察。

## 4. 真实执行中发现并关闭的问题

所有失败轮次都按 fail-closed 停止相应服务，保留命名卷并在修复经过本地完整
回归、提交、推送和 8/8 CI 后重试，没有手工跳过门槛：

1. Compose 5.5 的 `ps --format json` 输出为 newline-delimited JSON；解析器从
   只接受数组改为同时接受数组、单对象和 NDJSON。
2. Compose file Secret bind mount 保留宿主文件权限，`root:root 0400` 使非 root
   App 无法读取。三个 App Runtime Secret 改为 `root:10001 0440`；Secret 目录
   仍为 `root:root 0700`，MySQL Root Secret 仍为 `root:root 0400` 且不挂载给 App。
3. Compose 5.5 把 Nginx 镜像未绑定的 `EXPOSE 80/tcp` 表示为 `URL=""`、
   `PublishedPort=0` 的 publisher。校验器只忽略这种没有宿主 listener 的元数据；
   任何额外、非 Nginx 或非环回宿主映射仍被拒绝。真实 Docker binding 和 `ss`
   同时确认唯一 listener 为 `127.0.0.1:18080`。

对应最终本地验证为 Release `85 passed`，完整后端 `1625 passed, 9 skipped`；9 项
skip 均为既有、显式隔离的 MySQL-only 门槛，真实远端 MySQL Job 已在两个最终 CI
Run 中通过。

## 5. 保留资源、清理与下一门槛

- 按 Gate A 测试环境要求，有意保留 4 个长期容器、3 个 named volumes、当前
  Runtime image、版本化 Release 目录、发布 Record 和配置备份。停止时必须使用
  `safe-stop`，不得删除 volumes。
- 一次性 migration/诊断容器均已退出或由 `--rm` 清理；两次诊断启动的 App/Nginx
  已在采证后精确停止，最终只保留正式生命周期创建的运行实例。上传归档和本地
  临时目录均已删除，未遗留临时端口、隧道或后台 Shell 会话。
- 尚未执行 SUPER_ADMIN Bootstrap、Gate A 持久资源的备份/恢复、DNS、备案后的
  HTTPS 证书与续期、微信 request/upload/download 合法域名、真实 RC 构建/上传、
  iOS/Android 真机、弱网/前后台矩阵、测试人员与数据清理安排。

因此本次结果关闭的是 Phase 9.4 的“持久主机 loopback 首次部署”子门槛，不是
Gate A Go。下一步应先完成域名备案等待与 DNS/证书准备，再把同一批准 RC 切换到
TLS，完成 Bootstrap、持久备份恢复和微信真机验收；任何体验版上传、分发、提审或
公开发布仍需单独授权。
