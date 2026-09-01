# Gate A 持久部署

> **Status:** 本地实现与静态契约已建立，尚未部署到真实服务器
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
/etc/pinkdoohub/gatea/secrets/mysql_app_password         root:root 0400
/etc/pinkdoohub/gatea/secrets/mysql_root_password        root:root 0400
/etc/pinkdoohub/gatea/secrets/redis_password             root:root 0400
/etc/pinkdoohub/gatea/secrets/jwt_secret                 root:root 0400

/srv/pinkdoohub/gatea/releases/<git-sha>/
/srv/pinkdoohub/gatea/current -> releases/<git-sha>
/srv/pinkdoohub/gatea/backups/mysql/
/srv/pinkdoohub/gatea/backups/images/
/srv/pinkdoohub/gatea/records/{releases,backups,restores}/
/srv/pinkdoohub/gatea/staging/
```

真实 Secret 值不得写入本文、仓库、命令行参数、聊天、日志或 Release Record。

## 当前只允许的预检

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

当前脚本故意还没有提供 `up`、`migrate`、`bootstrap`、`backup`、`restore` 或
`down` 子命令。它们必须先完成独立实现、测试和 Review，不能用一段未经审查的
现场 Shell 绕过。

## 后续执行顺序

1. 从干净 Git SHA 构建 `pinkdoohub-gatea:<40位SHA>` 并记录 image ID。
2. Root 创建配置/Secret/持久运维目录；仅运行 loopback preflight。
3. 启动 MySQL、Redis；确认健康后显式执行空库 Aerich 迁移。
4. 启动 App/Nginx loopback；验证 liveness/readiness，确认没有公网业务端口。
5. 临时注入 Bootstrap Secret，执行首次/严格重放、登录和凭据轮换后删除。
6. 实现并验证 MySQL/图片独立备份、恢复、校验和、保留和异机副本。
7. ICP 通过后再配置 DNS、证书、80/443 和 TLS override。
8. 将同一 SHA 绑定后端、OpenAPI 和微信 RC，配置合法域名并执行真机矩阵。

任一步失败都保持 Gate A `No-Go`。本目录不授权体验版上传、分发、提审或公开
发布。
