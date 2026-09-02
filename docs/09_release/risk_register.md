# Phase 9 微信发布风险登记

> **Status:** Active
> **Last Updated:** 2026-09-02
> **Current Gate:** Gate A — 内部微信测试版

风险状态使用 `open`、`mitigating`、`accepted-until`、`closed`、`deferred`。只有满足“关闭证据”才能标记 `closed`；降低优先级或口头接受不等于关闭。

## 1. 活跃风险

| ID | 级别 | 风险/信号 | 概率×影响 | 缓解与关闭证据 | 责任角色 | 最晚关闭 | 状态 |
|----|------|-----------|-----------|--------------|----------|----------|------|
| R-001 | P0 | 8 个 CI Job 缺少真实 PR Run | 高×高 | PR #2 Run 33355935212 在干净 checkout 8/8 通过，7 组 artifact 绑定 merge-ref/Run，head SHA 由 Run 元数据绑定 | Yijie Shen | 9.2 | closed |
| R-002 | P0 | 生产构建仍含 `.example.invalid` API Origin | 确定×高 | 冻结测试 HTTPS Origin；CI 语义扫描；真机 request 成功 | Yijie Shen | Gate A | open |
| R-003 | P0 | request/upload/download 合法域名、DNS、证书未冻结 | 高×高 | 微信后台配置、TLS 外部验证、iOS/Android 真机证据 | Yijie Shen | Gate A | open |
| R-004 | P0 | 备份恢复和迁移失败处置未实际演练 | 中×极高 | Run `20260831t221625` 的 DR-01–DR-05 全部通过：独立 DB/图片恢复、restore-app、耗时、数据断言和 MySQL DDL 部分提交恢复均有报告 | Yijie Shen | 9.3 | closed |
| R-005 | P0 | MySQL-only 门槛缺少当前 SHA 的远端 PR 证据 | 中×高 | Run 33355935212 使用专用 MySQL 8.0.46 完成 0→1→2、9 项并发/锁/重试/HTTP 门槛并保存 cleanup artifact | Yijie Shen | 9.2 | closed |
| R-006 | P0 | 受控 SUPER_ADMIN bootstrap 已实现但尚未在隔离 MySQL 执行并处置初始凭据 | 中×高 | DR-07 在隔离 MySQL 完成首次/重放、登录、唯一用户/Audit 与凭据轮换；初始/轮换 Secret 随任务目录删除 | Yijie Shen | 9.3 | closed |
| R-007 | P0 | npm audit 仍报 10 个包/5 个叶子公告；Taro 当前版没有无破坏修复 | 中×高 | 已逐项证明为未启用 esbuild serve、H5-only 或当前微信源码/产物不可达；精确策略、新告警 fail-closed，2026-11-30 到期 | Yijie Shen | 2026-11-30/Gate A | accepted-until |
| R-008 | P0 | 对外公开微信身份缺口 | 中×极高 | 9.5 已实现 code2Session 适配、HMAC 身份、自动创建/显式绑定/冲突/禁用/解绑/注销和自动化；仍需真实 AppID iOS/Android 真机矩阵 | Yijie Shen | Gate B | mitigating |
| R-009 | P0 | Order create 无服务端幂等，弱网重试可能重复订单/扣库存 | 中×极高 | 冻结键/身份/冲突语义并实现并发、unknown、重放测试 | Yijie Shen | Gate B | deferred |
| R-010 | P0 | 若公开在线收款，缺微信支付可信闭环 | 高×极高 | 服务端下单、验签、金额核对、通知幂等、查单、退款、对账和告警 | Yijie Shen | Gate B（收款时） | deferred |
| R-011 | P1 | dependency-aware readiness 已实现但尚未在生产相似 MySQL/Redis 验证摘流量与恢复 | 中×高 | DR-06 分别中断 MySQL/Redis，Readiness 安全返回 503，恢复后重新 200；Liveness、优雅重启与脱敏均通过 | Yijie Shen | 9.3 | closed |
| R-012 | P1 | Redis 初始化日志可能泄露连接凭据 | 中×高 | Run 33355935212 的后端契约证明 username、password、query 不输出 | Yijie Shen | Gate A | closed |
| R-013 | P1 | production fail-fast 与 Secret 隐藏缺少干净 CI 证据 | 中×高 | Run 33355935212 覆盖 debug/MySQL/JWT/Redis/HTTPS 图片配置的接受与拒绝路径 | Yijie Shen | Gate A | closed |
| R-014 | P1 | Gate A 图片依赖本地卷，主机/系统盘故障可能同时损坏来源与同机备份 | 高×高 | 3 张真实图片已完成持久卷、`0600` 归档、checksum 和无端口独立恢复；Backup `20260902t014211z` 已生成管理电脑 FileVault 上的 AES-256-GCM/RSA-OAEP-SHA256 异机副本并立即完整解密复核，私钥与副本分离 | Yijie Shen | Gate A 保管 | closed |
| R-015 | P1 | Gate A Secret 的保管、读取主体、轮换和泄漏响应未落地 | 中×高 | Root 文件型 Secret 的路径、`0700/0400/0440` 权限、容器 UID/GID 读取边界、人工 TTY Bootstrap、轮换/泄漏触发、备份私钥隔离和日志零精确命中均已验证；详细证据见备案前收口报告 | Yijie Shen | Gate A（测试） | closed |
| R-016 | P1 | Python/Node/npm/pip 固定缺少远端干净 CI 证据 | 高×中 | Run 33355935212 验证版本文件、engines 和 CI 精确版本 | Yijie Shen | 9.2 | closed |
| R-017 | P1 | pip-audit 修复可升级项后只剩 ecdsa 无修复的 P-256 时序公告 | 中×高 | 固定 pip-audit 2.10.1；production HS256 不可达策略 fail-closed，算法/版本变化重审，2026-11-30 到期 | Yijie Shen | 2026-11-30 | accepted-until |
| R-018 | P1 | 远端 CI 已证明 production artifact 配置关闭且 0 source map，尚缺真实 RC 证据 | 中×中 | Run 33355935212 已完成 CI 侧；9.4 真实 RC 继续证明无 source map/上传入口 | Yijie Shen | Gate A | mitigating |
| R-019 | P1 | 管理分包是否随公开包发布未决定 | 中×中 | Gate B 前评估包体、审核面、运营入口和后端授权 | Yijie Shen | Gate B | deferred |
| R-020 | P1 | 认证安全和监控告警缺口 | 中×高 | 9.5 已实现 refresh family 轮换/重放撤销、Redis 原子限流/fail-closed 和结构化安全事件；仍需正式监控接入、送达与恢复演练 | Yijie Shen | Gate B | mitigating |
| R-021 | P2 | OpenAPI CLI UTF-8/CP1252 回归缺少 CI 运行证据 | 高×低 | Run 33355935212 的 OpenAPI Job 完成 `--help`、真实导出、字节比较和类型漂移检查 | Yijie Shen | 9.2 | closed |
| R-022 | P2 | metadata/README 已收敛，artifact checker 拒绝 H5-only marker；尚缺 RC 复核 | 中×中 | Run 33355935212 已完成 CI 侧；9.4 RC 继续证明发布元数据只声明微信 | Yijie Shen | Gate A | mitigating |
| R-023 | P2 | Jest 重复提示 ReactDOMTestUtils.act deprecated | 高×低 | Taro 测试依赖升级窗口或有期限 warning 白名单 | Yijie Shen | Gate A 后可排期 | open |
| R-024 | P1 | Gate B 公开服务仍依赖单主机本地图片卷，缺少高可用存储/CDN | 高×高 | Phase 9.5 已冻结 `ImageStorage` 端口和对象存储验收门；仍需选型、真实 Bucket/CDN、最小权限和恢复演练 | Yijie Shen | Gate B | mitigating |
| R-025 | P1 | Gate B 缺少集中 Secret Manager、访问审计和自动轮换 | 中×高 | Phase 9.5 已冻结 Secret inventory、文件注入边界和 Pepper 轮换约束；仍需选择集中系统并验证最小权限、版本、轮换、撤销和审计 | Yijie Shen | Gate B | mitigating |

## 2. 风险例外规则

P0 默认不能豁免。任何例外至少包含：

- 风险 ID、适用 Git SHA/环境/Gate 和明确的业务理由；
- 可验证的补偿控制，不使用“当前用户少”替代安全措施；
- 接受人、责任人、到期时间和自动失效条件；
- 发生后的停止、数据保护、沟通和恢复方案；
- Go/No-Go 记录中的显式引用。

当前默认例外建议人、风险接受人和责任人均为 Yijie Shen；同一人承担多个角色时，必须分别记录建议、接受决定和时间，不能用一次签名合并三个步骤。

Secret 泄漏、越权、数据破坏、无法恢复、artifact 来源不明、真实支付状态不可信等风险不得通过普通例外进入相应 Gate。

## 3. 更新规则

- CI、演练、RC 真机或外部平台检查发现新风险时先登记，再决定是否阻断。
- 每个 RC 冻结时复核概率、影响、状态、负责人和到期日。
- `closed` 必须给出 CI run、测试、演练报告、配置复核或 Review 链接；仅合并代码不算关闭。
- Gate A 的 `deferred` 项在 Gate B 立项时自动重新打开，不能沿用旧结论。
- 微信平台、依赖、证书和合规规则具有时效性，RC 冻结时重新检查官方规则和后台配置。
