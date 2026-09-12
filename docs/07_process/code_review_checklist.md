# Code Review Checklist

> 每次 PR / commit 前逐项检查。AI 在完成代码修改后自动执行此清单并生成 Review Report。

---

## 1. Architecture

- [ ] API 层只做参数提取和路由分发，不写业务逻辑
- [ ] Service 层不直接操作 Model（通过 Repository）
- [ ] Service 不调用另一个 Service（跨领域通过 Repository）
- [ ] Repository 不包含业务判断（`if status == 0: raise`）
- [ ] 文件位置符合 `architecture.md` 中定义的目录结构
- [ ] 无反向依赖（Model → Service、Repository → Service 等）
- [ ] 跨 Order/Wallet/Payment/Refund/Inventory 用例由一个顶层 Service 直接协调 Repository；不得通过业务 Service 互调拆散事务

---

## 2. Naming & Types

- [ ] 类名 PascalCase，函数 snake_case，常量 SNAKE_CASE
- [ ] Schema 后缀正确（Create / Out / Update / LoginRequest / ListItem）
- [ ] 所有函数标注返回类型（`-> None`, `-> User`, `-> dict`）
- [ ] 无 Magic Number，使用 `common/constants/` 中的命名常量
- [ ] 枚举存储遵循模块权威设计：User 使用 SmallIntField + IntEnum；Product 使用 VARCHAR + 字符串 Enum

---

## 3. Security

- [ ] 密码已通过 bcrypt 哈希，不可逆存储
- [ ] 任何接口不得返回 `password` 字段
- [ ] JWT_SECRET_KEY 不在生产环境使用默认值
- [ ] 日志中不打印密码、Token 等敏感信息
- [ ] 无 SQL 注入风险（使用 ORM 参数化查询）
- [ ] `.env` 文件未提交到 git
- [ ] ADMIN/SUPER_ADMIN 资金写只允许普通 USER 目标；ADMIN 身份不隐含普通客户钱包能力
- [ ] disabled USER 的主动充值/消费及 ADMIN+ 代客商品消费被拒绝，但人工余额纠错和法定义务退款仍可执行；deleted USER 禁止任何新资金写入
- [ ] ADMIN+ 人工 `pending → paid` 先定位 owner 并按 `User → Order` 锁序复验；仅 NORMAL 普通 USER 可写，staff/disabled/deleted 拒绝且 Order/Payment/Settlement/Audit 零写入
- [ ] Provider 密钥、证书、AppID/AppSecret、商户号和 notify 凭据只来自受控 Secret；503 关闭路径不创建任何资金、库存或审计事实

---

## 4. Exception & Response

- [ ] Service 层抛命名异常（`raise UsernameAlreadyExists()`），不用裸 BusinessException
- [ ] 错误码在对应模块号段内
- [ ] API 层使用 `success()` / `error()` 工厂函数，不手写 `{"code": 0, ...}`
- [ ] 禁止在 API 层 try/except 构造错误响应

---

## 5. Database

- [ ] 新字段设计合理（类型、约束、默认值）
- [ ] 查询字段有对应索引（username、user_id、status 等高频筛选字段）
- [ ] nullable 字段显式声明，不滥用空字符串代替
- [ ] 金额用 DecimalField(max_digits=10, decimal_places=2)，不用 float
- [ ] 枚举字段的数据库类型、Python Enum 和 API 映射与 Enum Registry 及模块数据库设计一致
- [ ] 新建普通 USER 创建唯一 WalletAccount；历史 backfill 只补 NORMAL/DISABLED 普通 USER，历史 DELETED 不补，ADMIN/SUPER_ADMIN 钱包数必须为零
- [ ] WalletAccount.balance 保持 `0.00..1000.00`；单笔充值保持 `1.00..1000.00`，所有金额使用两位 Decimal
- [ ] PaymentSettlement 的 `order_id` / `payment_id` 与 Refund 的 `order_id` / `settlement_id` 一对一 UNIQUE 未被绕过
- [ ] 不可变 Wallet/Inventory 流水的 before + change = after、非零变化、来源与内部幂等身份保持一致

---

## 6. Data & Performance

- [ ] 无 `for ... await` 循环查询（使用 `prefetch_related` / `select_related`）
- [ ] 列表接口有分页（limit + offset）
- [ ] 跨表写操作使用 `in_transaction()` 包裹
- [ ] 批量操作用 `bulk_create` / `bulk_update`，不循环单条 `save()`
- [ ] 资金事务遵循稳定有效锁序；多 Kit 始终按 Product ID 升序锁定，锁后重新校验用户、状态、余额、库存、结算和幂等事实
- [ ] 正向钱包入账保持 `入账后余额 + 尚可退款的钱包支付敞口 ≤ 1000.00`；未来充值成功也复用该校验
- [ ] 注销在 User 行锁内检查可退款钱包结算敞口；余额为零但仍有 PAID 或 30 天内 COMPLETED 未成功退款结算时必须拒绝关闭钱包
- [ ] ADMIN+ 代客钱包订单在一个事务中提交真实 Order/Items、Kit 扣减、钱包扣减、Payment/Settlement、直接 Paid 和 `CREATE_ORDER` + `PAY_ORDER`
- [ ] 人工 Paid 在新建 manual Payment/Settlement 前按 `User → Order` 锁序锁定并重检 NORMAL 普通 USER 目标；任何拒绝或后置失败都完整回滚
- [ ] PAID/COMPLETED 仅全额退款；PAID Kit 恢复、COMPLETED 不恢复，退款成功不回退 OrderStatus
- [ ] 退款前验证 Settlement 绑定 Payment 的 user/order/amount 一致，且 `purpose=order`、`status=succeeded`、`recharge_order_id=null`；矛盾事实拒绝且零写入
- [ ] 相同 Idempotency-Key 只重放完全一致意图；重放返回首次历史余额，UNIQUE 冲突必须退出失败事务后解析
- [ ] 仅 MySQL 1205/1213 可对无外部副作用的完整事务使用全新事务有限重试；Provider 网络调用不发生在数据库锁内

---

## 7. Testing

- [ ] 新功能有对应的测试用例
- [ ] 正常流程覆盖（200/201）
- [ ] 异常流程覆盖（400/401/403/404）
- [ ] 业务错误码覆盖（1001、1003 等）
- [ ] `test_password_is_hashed` 确认密码不存明文
- [ ] 资金测试覆盖 0/1000 余额边界、1/1000 充值边界、退款预留容量、余额/库存不足、closed 钱包及 disabled/deleted 权限矩阵
- [ ] 调账、代客钱包订单、余额支付和退款覆盖首次/同 key 重放/异意图冲突、并发唯一兜底及任一后置失败全回滚
- [ ] 人工 Paid 覆盖 NORMAL 普通 USER 成功与 staff/disabled/deleted owner 的权限/状态错误，并证明拒绝路径资金、订单和审计零写入
- [ ] 微信充值/支付/退款与关闭的 production Feature Flag 覆盖 HTTP 503 且 Wallet/Payment/Settlement/Refund/Inventory/Audit 零写入
- [ ] 新资金与锁序路径在发布前通过可销毁 MySQL 8+ 真实并发、1205/1213、EXPLAIN 和完整 HTTP 门槛；不能用 SQLite 或旧 Inventory 证据代替

---

## 8. Logging

- [ ] 关键操作有 `logger.info()`（如注册、登录）
- [ ] 异常有 `logger.error(..., exc_info=True)`
- [ ] 无 `print()` 调用
- [ ] 日志中不包含密码、Token 等敏感字段

---

## 9. Documentation

- [ ] API 文档已更新
- [ ] 数据库文档已更新（`database_design.md` + `er_diagram.dbml`）
- [ ] Enum Mapping 表已更新（`api_design_conventions.md` §14）
- [ ] `changelog.md` 已更新（功能模块完成时）
- [ ] 版本号是否需要升级
- [ ] 是否需要数据库迁移（`aerich migrate`）
- [ ] 是否需要新增依赖（`requirements.txt`）
- [ ] M4 若尚未应用，文档和发布记录明确标记；不得把仓库实现表述为持久库已升级
- [ ] 历史钱包补齐先运行 `python -m app.tasks.wallet_account_backfill` 预览，仅显式 `--apply` 为 NORMAL/DISABLED 普通 USER 写入；确认不造零流水，历史 DELETED 与 ADMIN+ 均不补建
- [ ] 历史人工结算先运行 `python -m app.tasks.legacy_manual_settlement_backfill` 预览，以同一 `through_order_id` 显式 apply 并复查；唯一 `MARK_ORDER_PAID` Audit 之外的缺失、重复或矛盾事实必须 blocker/非零退出，不得猜测修复
- [ ] 正式顺序保持 M4 → wallet backfill → legacy manual settlement backfill → 只读 `wallet_reconcile`/发布门槛 → 启用；差异或 blocker 必须人工调查，禁止自动改账
- [ ] 真实微信/经营资料尚未接入时保持占位边界，不把商户号、证书、密钥或未经核验的营业执照内容写入仓库

---

## 10. AI Review Report 模板

完成代码修改后，AI 自动输出：

```
## AI Code Review Report

### Changes
- [文件清单]

### Architecture Check
[通过 / 发现问题]

### Security Check
[通过 / 发现问题]

### Documentation Check
[通过 / 需更新：文件列表]

### Test Coverage
- 新增测试: N 条
- 通过: N/N

### Action Items
- [ ] [如需要] 升级版本号
- [ ] [如需要] 数据库迁移
- [ ] [如需要] 新增依赖
```
