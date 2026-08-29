# Phase 9 微信发布风险登记

> **Status:** Active
> **Last Updated:** 2026-08-29
> **Current Gate:** Gate A — 内部微信测试版

风险状态使用 `open`、`mitigating`、`accepted-until`、`closed`、`deferred`。只有满足“关闭证据”才能标记 `closed`；降低优先级或口头接受不等于关闭。

## 1. 活跃风险

| ID | 级别 | 风险/信号 | 概率×影响 | 缓解与关闭证据 | 责任角色 | 最晚关闭 | 状态 |
|----|------|-----------|-----------|--------------|----------|----------|------|
| R-001 | P0 | 无 CI；候选包与历史测试不绑定 | 高×高 | 9.2 全部门槛在干净 checkout 通过，artifact 绑定 SHA/checksum | Yijie Shen | 9.2 | open |
| R-002 | P0 | 生产构建仍含 `.example.invalid` API Origin | 确定×高 | 冻结测试 HTTPS Origin；CI 语义扫描；真机 request 成功 | Yijie Shen | Gate A | open |
| R-003 | P0 | request/upload/download 合法域名、DNS、证书未冻结 | 高×高 | 微信后台配置、TLS 外部验证、iOS/Android 真机证据 | Yijie Shen | Gate A | open |
| R-004 | P0 | 备份恢复和迁移失败处置未实际演练 | 中×极高 | DR-01–DR-05 完成，独立恢复、耗时与数据断言通过 | Yijie Shen | Gate A | open |
| R-005 | P0 | 当前 SHA 的 9 项 MySQL-only 未进入稳定 CI | 中×高 | 专用 MySQL 8+ CI 0→当前并发/锁/重试/HTTP 门槛通过 | Yijie Shen | 9.2 | open |
| R-006 | P0 | 无受控、幂等、可审计的 SUPER_ADMIN bootstrap | 高×高 | 实现命令/流程、测试重复执行与凭据处置、演练通过 | Yijie Shen | Gate A | open |
| R-007 | P0 | npm audit 报 10 项（4 moderate/1 high/5 critical），含 components/swiper 与构建链，微信可达性未知 | 中×高 | 逐项判断生产/构建/微信 reachability，升级或隔离；高风险无未审批残留 | Yijie Shen | 9.2/Gate A | open |
| R-008 | P0 | 对外公开仍无微信登录和账号关联规则 | 高×极高 | 9.5 实现 code2Session 服务端链路、绑定/冲突/禁用和真机矩阵 | Yijie Shen | Gate B | deferred |
| R-009 | P0 | Order create 无服务端幂等，弱网重试可能重复订单/扣库存 | 中×极高 | 冻结键/身份/冲突语义并实现并发、unknown、重放测试 | Yijie Shen | Gate B | deferred |
| R-010 | P0 | 若公开在线收款，缺微信支付可信闭环 | 高×极高 | 服务端下单、验签、金额核对、通知幂等、查单、退款、对账和告警 | Yijie Shen | Gate B（收款时） | deferred |
| R-011 | P1 | `/health` 仅检查进程，不代表 DB/Redis 可服务 | 高×高 | 拆分 liveness/readiness；故障时摘流量且不泄漏明细 | Yijie Shen | Gate A | open |
| R-012 | P1 | Redis 初始化日志可能输出完整 URL | 中×高 | 日志仅显示脱敏目标；测试/Review 证明凭据不输出 | Yijie Shen | Gate A | open |
| R-013 | P1 | production 只拒绝默认 JWT，未强制 debug=false/MySQL/必要配置 | 中×高 | 生产启动 fail-fast 校验及测试，错误不含 Secret | Yijie Shen | Gate A | open |
| R-014 | P1 | 图片依赖本地目录，重建/扩缩容可能丢失 | 高×高 | Gate A 持久卷+备份恢复；Gate B 对象存储/CDN 或等价 Review | Yijie Shen | Gate A/B | open |
| R-015 | P1 | Secret Manager、轮换、最小权限和泄漏响应未选 | 中×高 | Secret inventory 映射到实际系统、主体、轮换和审计 | Yijie Shen | Gate A（测试）/B（正式） | open |
| R-016 | P1 | Node/npm 未由仓库 pin，干净构建可能漂移 | 高×中 | 冻结支持版本、仓库版本文件/engines、CI 校验 | Yijie Shen | 9.2 | open |
| R-017 | P1 | Python 无漏洞扫描工具/结果 | 中×高 | 锁定工具和策略，保存报告并处置可达高风险 | Yijie Shen | 9.2 | open |
| R-018 | P1 | `uploadWithSourceMap=true`，上传/访问/保留策略未冻结 | 中×中 | 决定关闭或受控上传；artifact/权限/保留有证据 | Yijie Shen | Gate A | open |
| R-019 | P1 | 管理分包是否随公开包发布未决定 | 中×中 | Gate B 前评估包体、审核面、运营入口和后端授权 | Yijie Shen | Gate B | deferred |
| R-020 | P1 | refresh 不轮换、登录/注册不限流、监控告警缺失 | 高×高 | 9.5 安全方案、测试和告警演练完成 | Yijie Shen | Gate B | deferred |
| R-021 | P2 | OpenAPI CLI 在 Windows 非 UTF-8 控制台显示帮助会编码失败 | 高×低 | 脚本强制/兼容 UTF-8，Windows 回归通过 | Yijie Shen | 9.2 | open |
| R-022 | P2 | 前端 metadata/文档仍可能暗示同步 H5 | 中×中 | 本版发布元数据只声明微信；H5 保留为未来能力 | Yijie Shen | 9.2 | open |
| R-023 | P2 | Jest 重复提示 ReactDOMTestUtils.act deprecated | 高×低 | Taro 测试依赖升级窗口或有期限 warning 白名单 | Yijie Shen | Gate A 后可排期 | open |

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
