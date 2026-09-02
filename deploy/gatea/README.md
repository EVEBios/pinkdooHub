# Gate A 持久部署

> **Status:** Loopback、持久 Bootstrap、代表性数据与非空恢复已通过；待备份保管、DNS/HTTPS 和真机
> **Scope:** 微信小程序受邀内部测试环境；不是 Gate B 正式生产

本目录把 Phase 9.3 已验证的一次性演练拓扑收敛为单服务器长期 Gate A
环境。数据库、Redis、应用和图片只在 internal Docker network 中通信；仅
Nginx 可以加入 edge network。任何命令都不得把 3306、6379 或 8000 发布到
宿主公网。

## 文件

| 文件 | 用途 |
|------|------|
| `compose.yml` | MySQL、Redis、App、Nginx、显式迁移和三个固定数据卷 |
| `compose.loopback.yml` | 备案等待期只绑定 `127.0.0.1:18080` |
| `compose.tls.yml` | ICP/DNS/证书完成后才允许发布 80/443 |
| `compose.bootstrap.yml` | 一次性 SUPER_ADMIN Bootstrap；不属于常驻服务 |
| `compose.restore.yml` | 独立 MySQL/空 Redis/图片卷/Restore App；无宿主端口，验证后删卷 |
| `nginx/loopback.conf` | SSH 隧道/宿主环回 Smoke，不构成微信 RC 证据 |
| `nginx/tls.conf.template` | 真实 Gate A HTTPS、ACME、图片和反向代理 |
| `config.env.example` | 非 Secret 配置模板；真实文件位于 `/etc` |

共享应用镜像由 `deploy/runtime/Dockerfile` 构建，Phase 9.3 演练与 Gate A
使用同一非 root Runtime，避免两套入口脚本漂移。

## 不可跨越的边界

- Compose 必须使用完整 Git SHA 镜像标签，禁止 `latest`。
- App 启动不自动执行 Aerich；迁移是独立 `operations` profile。
- 常驻 Secret 只通过 `/run/secrets` 文件注入；非 Secret `config.env` 中禁止
  `DB_PASSWORD`、`REDIS_URL`、`JWT_SECRET_KEY` 和 Root 密码。
- App 不获得 MySQL Root 密码；Nginx 不获得任何应用 Secret。
- Bootstrap 临时密码文件只在明确操作时挂载，完成首次/重放/登录/轮换后删除。
- `docker compose down --volumes`、`docker volume prune` 和
  `docker system prune --volumes` 禁止进入普通部署流程。
- Loopback 模式和 TLS 模式不能同时合并使用。
- TLS override 只有在备案、DNS、证书、腾讯云防火墙和微信合法域名步骤分别
  取得授权后才可启用。

## 服务器路径与权限

```text
/etc/pinkdoohub/gatea/config.env                         root:root 0640
/etc/pinkdoohub/gatea/secrets/                           root:root 0700
/etc/pinkdoohub/gatea/secrets/mysql_app_password         root:10001 0440
/etc/pinkdoohub/gatea/secrets/mysql_root_password        root:root 0400
/etc/pinkdoohub/gatea/secrets/redis_password             root:10001 0440
/etc/pinkdoohub/gatea/secrets/jwt_secret                 root:10001 0440
/run/pinkdoohub-gatea/bootstrap_password.pending        root:10001 0440（仅临时）

/srv/pinkdoohub/gatea/releases/<git-sha>/
/srv/pinkdoohub/gatea/current -> releases/<git-sha>
/srv/pinkdoohub/gatea/backups/mysql/
/srv/pinkdoohub/gatea/backups/images/
/srv/pinkdoohub/gatea/records/{releases,backups,restores,bootstrap}/
/srv/pinkdoohub/gatea/staging/
```

真实 Secret 值不得写入本文、仓库、命令行参数、聊天、日志或 Release Record。
Secret 目录本身保持 `root:root 0700`，因此宿主普通用户无法遍历。三个 App Runtime
Secret 使用未分配给宿主账号的数值 GID 10001 和 `0440`，使 Compose bind mount
保留宿主权限时，容器内 UID/GID 10001 仍能只读；MySQL Root Secret 继续保持
`root:root 0400`，App 不挂载它。临时 Bootstrap Secret 使用同一 Runtime
GID/mode，但只写入 `/run` tmpfs，并在完成登录与轮换后删除。

## 受控生命周期命令

Root 创建真实配置后，先执行只读预检。预检只检查非 Secret 配置语义、Secret
文件元数据/非空大小、环回端口和 Compose 渲染，不输出 Secret 值，也不创建
Docker 资源：

```bash
sudo python -m scripts.release.gatea_operations \
  preflight \
  --mode loopback
```

TLS 模式必须在真实证书和 ACME 目录准备完毕后才能预检：

`GATEA_LETSENCRYPT_DIR` 必须指向完整的 Let’s Encrypt 根目录（通常为
`/etc/letsencrypt`），不能只指向 `live/<域名>`；完整挂载才能保留证书指向
`archive/` 的软链接。

```bash
sudo python -m scripts.release.gatea_operations \
  preflight \
  --mode tls
```

当前脚本只实现首次 loopback 部署需要的最小生命周期，所有写操作都会再次验证
Root 配置/Secret、完整 SHA 镜像、镜像 revision、UID/GID、Entrypoint 和 CMD。
TLS 写操作仍被拒绝。

```bash
# 只启动 MySQL/Redis；失败时停止服务但保留命名卷。
sudo python -m scripts.release.gatea_operations \
  infra-up \
  --mode loopback

# 只允许空 application schema；迁移成功后原子记录 SHA 与 Image ID。
sudo python -m scripts.release.gatea_operations \
  initial-migrate \
  --mode loopback

# 必须存在与候选 SHA/Image ID 匹配的迁移记录；运行时复核唯一发布端口。
sudo python -m scripts.release.gatea_operations \
  app-up \
  --mode loopback

# 只输出 service/state/health、候选 SHA 和迁移记录布尔状态。
sudo python -m scripts.release.gatea_operations \
  status \
  --mode loopback

# 停止服务但不删除容器、命名卷、Secret 或迁移记录。
sudo python -m scripts.release.gatea_operations \
  safe-stop \
  --mode loopback
```

`initial-migrate` 在运行 Aerich 前通过 MySQL 容器内 Root Secret 查询
`information_schema`，只有目标 application schema 为 0 张表才继续。候选已有匹配
迁移记录时严格重放为 no-op；记录缺失但数据库非空时 fail closed，不会猜测状态或
使用 `--fake`。`app-up` 完成后要求 App/Nginx 均为 healthy，且只有 Nginx 发布
`127.0.0.1:${GATEA_LOOPBACK_PORT}:8080`。

## 受控 SUPER_ADMIN Bootstrap

`gatea_bootstrap.py` 是持久 Gate A 唯一批准的 Bootstrap 编排入口。它要求 Root、
完整 Runtime image/首次迁移 Record、MySQL/Redis/App/Nginx 四项健康、唯一 loopback
publisher，以及精确重复的用户名确认。命令不接受任何密码参数或密码环境变量；
初始密码和最终密码都通过 TTY 各隐藏输入两次，且最终密码必须不同。

执行前由 Root 创建脱敏 Record 目录：

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/bootstrap

sudo python -m scripts.release.gatea_bootstrap \
  --username <approved-username> \
  --nickname <approved-nickname> \
  --phone <approved-phone> \
  --confirm-username <approved-username> \
  --apply
```

初始密码只短暂写入 tmpfs 上的
`/run/pinkdoohub-gatea/bootstrap_password.pending`，权限为 `root:10001 0440`；
首次创建后使用同一 Secret 严格重放，要求 SUPER_ADMIN/Audit 各唯一且用户时间戳
不变。随后脚本只经 `127.0.0.1` Nginx 执行初始登录、密码轮换、旧密码拒绝、
新密码登录、两次 Refresh 会话注销与撤销验证。成功或失败都会删除临时 Secret 和
一次性容器；成功 Record 固定为
`records/bootstrap/super-admin-bootstrap.json`，只记录用户 ID、计数、候选、布尔
证据和 UTC 时间，不记录 username、nickname、phone、密码、Token 或密码 hash。

已有成功 Record 时命令 fail closed；不得删除 Record 后尝试创建第二个
SUPER_ADMIN。若操作返回失败，先保留数据库与日志现场并确认临时 Secret 已删除，
再按同一批准身份和已知初始密码决定是否恢复执行，不能改用不同身份绕过严格重放。

## 受控代表性备份数据

`gatea_representative_data.py` 只允许在 Bootstrap 已通过、业务表仍为空且图片卷无文件
时执行一次。工具先绑定 Runtime image、迁移/Bootstrap Record、四项服务健康和唯一
loopback publisher，再要求执行人通过 TTY 隐藏输入并确认当前 SUPER_ADMIN 密码；
密码不接受参数或环境变量，不写文件、日志或 Record。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/representative-data

sudo python -m scripts.release.gatea_representative_data \
  --super-admin-username <approved-username> \
  --confirm-super-admin-username <approved-username> \
  --apply
```

写入全部经过当前 `127.0.0.1` Nginx 和正式 API：一个随机临时密码的合成 USER、一个
Online Experience/Option、一个 Online Kit、三张真实 PNG、库存调整/订单扣减/取消
恢复，以及 Cancelled 混合订单和 Completed 体验订单。流程结束前注销并验证撤销
合成用户会话、禁用合成用户、拒绝其再次登录，并注销/撤销本次 SUPER_ADMIN 会话。
随机合成密码只存在于进程内存，不返回给调用者。

成功 Record 只保存前后计数、内部 ID、业务断言和清理布尔值，不保存真实管理员
身份、合成身份、密码、Token、手机号或 hash。任何部分失败都不写成功 Record，并
尽力注销两个会话、禁用已经创建的合成用户；此时必须保留现场人工审计，不能删除
订单或绕过空基线重跑。

## 受控备份与隔离恢复

`gatea_backup.py` 只备份权威 MySQL 与商品图片。Redis 当前只保存 refresh-token
会话，恢复旧快照可能重新激活应失效的会话，因此恢复环境固定启动空 Redis，使
全部旧 refresh 会话失效。备份 ID 必须使用 UTC `YYYYMMDDtHHMMSSz`；备份短暂
停止 Nginx/App 形成停写窗口，MySQL/Redis 保持运行，完成后自动恢复 App/Nginx
并再次验证 health。SQL/Tar 为 `root:root 0600`，Record 只保存摘要、计数、路径、
checksum 和 Redis 策略，不保存 Secret 值。

```bash
backup_id=20260902t120000z

sudo python -m scripts.release.gatea_backup \
  backup \
  --backup-id "$backup_id" \
  --mode loopback

sudo python -m scripts.release.gatea_backup \
  restore-verify \
  --backup-id "$backup_id" \
  --confirm-project "pinkdoohub-gatea-restore-$backup_id" \
  --mode loopback
```

恢复只写入精确确认的独立 project、internal network 和两个临时 named volumes；
不加入来源 project、不挂载来源卷、不发布宿主端口。工具比较数据库 Schema/业务
摘要与图片内容 manifest，启动 Restore App 验证 readiness，并在成功、失败和
中断路径执行精确 `down --volumes` 后复核恢复容器/卷消失。来源 Gate A 服务和
三个持久卷不属于清理目标。

同机备份只能证明流程和恢复能力，不能覆盖服务器或系统盘故障。Gate A Go 前仍需
定义保留期，并把批准备份加密复制到独立故障域；工具不自动上传或删除备份。

### 客户端加密异机副本

`gatea_offsite_backup.py` 在受控管理电脑执行，不把解密私钥发送到服务器。它通过
现有只读 SSH 身份下载精确 Backup/Restore Record 与两个 Artifact，在权限为 `0700`
的本机临时目录重算来源 checksum；随后使用随机 AES-256-GCM 数据密钥加密、用独立
RSA-3072 OAEP-SHA256 公钥封装数据密钥。成功后必须用私钥完成 AEAD 解密、Bundle
成员白名单、数据库/图片 SHA-256 和 Restore PASS Record 的再次验证。

```bash
python -m scripts.release.gatea_offsite_backup keygen \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem" \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem"

python -m scripts.release.gatea_offsite_backup export \
  --backup-id <YYYYMMDDtHHMMSSz> \
  --host <gate-a-host> \
  --user <ssh-user> \
  --identity-file <ssh-private-key> \
  --public-key "$HOME/.config/pinkdoohub/gatea-backup/public.pem" \
  --destination-dir "$HOME/Backups/pinkdoohub/gatea"

python -m scripts.release.gatea_offsite_backup verify \
  --copy "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb" \
  --record "$HOME/Backups/pinkdoohub/gatea/<backup-id>.pdhb.json" \
  --private-key "$HOME/.config/pinkdoohub/gatea-backup/private.pem"
```

私钥目录固定 `0700`、私钥 `0600`、公钥 `0644`；加密副本 `0400`，脱敏客户端
Record `0600`。密钥与副本必须位于仓库外且相互分离；脚本拒绝覆盖已有 key/copy，
不提供自动删除。私钥丢失会使副本不可恢复，因此其离线恢复保管仍由项目负责人负责。

## 依赖故障、应用重启与日志观察

`gatea_resilience.py` 只在代表性数据成功 Record、Runtime/迁移绑定、四项 Healthy 和
唯一 loopback publisher 全部匹配时执行一次。它依次停止 MySQL、Redis，要求依赖
故障时 readiness 为 503 而 liveness 保持 200；恢复各依赖并等待 readiness 200 后，
再重启 App。最终比较完整数据库摘要与图片 manifest，验证四项服务、端口、Docker
日志轮转、24 小时 Nginx 请求数量/4xx/5xx/时延，并以内存中的四项真实 Secret 扫描
日志但不记录日志正文或 Secret 值。

```bash
sudo install -d -o root -g root -m 0755 \
  /srv/pinkdoohub/gatea/records/resilience

sudo python -m scripts.release.gatea_resilience --apply
```

任何阶段失败都先尝试恢复 MySQL、Redis、App 和 Nginx，再返回失败且不写成功 Record；
不得为了得到 PASS 删除代表性数据、Record 或绕过日志匹配。

运维工具仍故意不提供备份删除、来源卷恢复、TLS 切换或公开发布命令；这些步骤
必须分别实现、测试和 Review，不能用未经审查的现场 Shell 绕过。

## 后续执行顺序

1. 从干净 Git SHA 构建 `pinkdoohub-gatea:<40位SHA>` 并记录 image ID。
2. Root 创建配置/Secret/持久运维目录；运行 loopback preflight。
3. 使用 `infra-up` 启动 MySQL、Redis；使用 `initial-migrate` 完成空库迁移。
4. 使用 `app-up` 启动 App/Nginx loopback；验证 liveness/readiness 与端口边界。
5. 临时注入 Bootstrap Secret，执行首次/严格重放、登录和凭据轮换后删除。
6. 使用受控工具验证 MySQL/图片独立备份、恢复和校验和；再定义保留和加密异机副本。
7. ICP 通过后再配置 DNS、证书、80/443 和 TLS override。
8. 将同一 SHA 绑定后端、OpenAPI 和微信 RC，配置合法域名并执行真机矩阵。

任一步失败都保持 Gate A `No-Go`。本目录不授权体验版上传、分发、提审或公开
发布。
