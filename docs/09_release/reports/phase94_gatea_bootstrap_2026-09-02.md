# Phase 9.4 Gate A 持久 SUPER_ADMIN Bootstrap 报告

> **Result:** PASS（持久 Gate A 初始化、严格重放与凭据轮换范围）  
> **Runtime Candidate:** `51ad3152c8960bc133c25a600418f5f850d69199`  
> **Operations Revision:** `0ebe25a546b60bcf8445b50e711824b92b3bde38`  
> **Implementation CI:** [GitHub Actions Run 33573459444](https://github.com/EVEBios/pinkdooHub/actions/runs/33573459444)，8/8 Job success  
> **Compatibility Fix CI:** [GitHub Actions Run 33574718103](https://github.com/EVEBios/pinkdooHub/actions/runs/33574718103)，8/8 Job success  
> **Executed At:** 2026-09-02 08:23:31–08:23:37（Asia/Shanghai）  
> **Executor / Reviewer:** Yijie Shen

本报告证明真实腾讯云 Gate A 主机完成唯一 SUPER_ADMIN 的首次初始化、同输入严格
重放、初始登录、正式密码轮换、旧密码拒绝、正式密码登录和两个验证 Refresh 会话
撤销。批准的 username、nickname、phone，以及初始/最终密码、Token、hash 和连接
Secret 均不进入本报告、仓库、命令参数、成功 Record 或日志。

该结果只关闭持久 Gate A 管理员初始化子门槛。DNS、HTTPS、微信合法域名、真实 RC、
iOS/Android 真机与体验版分发尚未完成，Gate A 继续保持 **No-Go / Not Authorized**。

## 1. 执行边界

- 主机：`pinkdoohub-gatea-nj-01`，Ubuntu 24.04.4 LTS。
- App Runtime 继续使用已迁移候选 `51ad315...`，Image ID 为
  `sha256:13a08366bc5644b6a63e6b209b1d8bcfc48452549cc2ae1a70554c1c07f07a1b`；
  本次没有重建或替换应用镜像、修改 Schema、运行 Aerich、重启常驻服务或删除卷。
- Operations 最终切换到 `0ebe25a...`；该提交只修复 Compose v5 未发布 `EXPOSE`
  元数据识别，并增加测试和文档，不改变业务代码、迁移、依赖、API 或 Runtime Compose。
- 密码由执行人通过真实 TTY 隐藏输入并各确认两次。初始值只短暂存在于
  `/run/pinkdoohub-gatea/bootstrap_password.pending`，最终值只存在于编排进程内存与
  loopback API 请求体。
- 所有 API 验证只经 `127.0.0.1:18080` Nginx 进行；未开放公网业务端口。

## 2. 前置失败与处置

首次尝试因初始密码两次输入不一致，在 `execute_bootstrap()` 前终止；没有创建 Secret、
用户、Audit 或 Record。第二次尝试在任何数据库写入前发现 Compose v5 把 MySQL 镜像
内部 `EXPOSE 3306/tcp` 报告为 `URL=""`、`PublishedPort=0` 的未绑定 publisher，旧
校验顺序将其误判为宿主端口发布并 fail closed。

宿主 `ss -lnt` 独立确认不存在 3306、6379 或 8000 listener，唯一业务 listener 仍为
`127.0.0.1:18080`。修复后校验器先忽略 `PublishedPort=0` 且无 URL 的无宿主绑定
元数据，再拒绝任何非 Nginx 的真实 publisher；MySQL/Redis Compose v5 回归、103 项
Release 测试和完整后端 `1643 passed, 9 skipped` 均通过，远端 Run 33574718103 的
8 个 Job 全部成功后才重新投放。两次前置失败均未留下临时 Secret 或成功 Record。

## 3. Bootstrap 结果

| 检查 | 结果 |
|------|------|
| Runtime image、首次迁移 Record、四项服务健康 | PASS |
| SUPER_ADMIN 首次创建 | PASS；`created_on_this_run=true` |
| 同身份/同初始密码严格重放 | PASS；数据库快照未变化 |
| SUPER_ADMIN 数量 | PASS；恰好 1 |
| `BOOTSTRAP_SUPER_ADMIN` Audit | PASS；恰好 1 且自指向创建用户 |
| 角色与状态 | PASS；`super_admin` / `normal` |
| 初始密码登录 | PASS |
| 初始密码替换为最终密码 | PASS |
| 旧密码拒绝 | PASS |
| 最终密码登录 | PASS |
| 初始及最终验证 Refresh 会话 | PASS；均已注销并验证撤销 |
| 一次性 Bootstrap 容器 | PASS；严格重放后确认不存在 |
| 临时初始密码文件 | PASS；成功 Record 前确认已删除 |

## 4. 脱敏 Record 与独立验收

成功 Record 位于
`/srv/pinkdoohub/gatea/records/bootstrap/super-admin-bootstrap.json`：

| 属性 | 结果 |
|------|------|
| Owner / mode / size | `root:root 0644` / 800 bytes |
| SHA-256 | `e51319dcfa1d147b568d25bc0648a54a58189cc7922f5d5180cd048936626cf0` |
| Schema | 只包含固定候选、Image ID、内部 user ID、计数、UTC 时间和布尔证据 |
| PII | `pii_recorded=false`；无 username、nickname、phone 字段 |
| Secret | `secret_values_recorded=false`；无密码、Token、连接串或 hash 值 |
| 总结论 | `passed=true` |

独立只读白名单解析再次确认 Record 字段集合、类型、候选、数量和所有成功布尔值；
Readiness 返回 HTTP 200 / `ready`，其中 database/redis 均为 `up`。宿主 listener 为
SSH、系统本地 DNS 与唯一 `127.0.0.1:18080`，没有 MySQL/Redis/App 宿主发布。

## 5. 清理与剩余门槛

- 当前 Operations 软链接为
  `/srv/pinkdoohub/gatea/releases/0ebe25a546b60bcf8445b50e711824b92b3bde38`。
- 已确认临时 Bootstrap Secret、一次性容器、部署启动器、新旧上传归档和 staging
  临时目录均不存在。
- 有意保留成功 Bootstrap Record、版本化 Release、来源 4 个健康常驻服务、3 个
  持久 named volumes，以及 Phase 9.4 空数据备份/恢复 Artifact。
- 现有备份是在 Bootstrap 前生成的空数据证据；下一阶段仍需在受控代表性数据和图片
  写入后重做备份/独立恢复，并冻结保留期、加密异机副本与周期演练。
- DNS/HTTPS、证书续期、微信 request/upload/download 合法域名、真实生产 Origin RC、
  iOS/Android 真机、弱网/前后台矩阵和体验版上传仍未执行。

本次不授权体验版上传、分发、提审或公开发布。
