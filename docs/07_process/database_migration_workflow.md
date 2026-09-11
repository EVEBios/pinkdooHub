# Database Migration Workflow

> **适用范围：** pinkdooHub 所有持久化 Model、字段、约束和索引变更
>
> **迁移工具：** Aerich 0.9.3
>
> **生产权威方言：** MySQL；SQLite 仅用于本地快速开发和自动化测试
> **Last Updated:** 2026-09-09

---

## 1. 为什么迁移必须独立于应用启动

生产应用启动只负责建立连接，不得把建表或改表作为隐式副作用。数据库结构变化必须进入版本化迁移文件，经过人工 Review 后再由部署流程执行。这样才能回答：

- 这次发布会执行哪些 SQL？
- 是否锁表、改列、删除数据或重建索引？
- 升级失败如何回滚？
- 哪些环境已经应用到哪个版本？

项目只允许 `development` 使用 `generate_schemas` 辅助本地开发；`testing` 使用独立临时 Schema；`production` 必须使用本流程。

---

## 2. Aerich 命令的职责

| 命令 | 作用 | 是否写数据库 |
|------|------|--------------|
| `aerich init` | 写入迁移工具配置并创建迁移目录 | 否 |
| `aerich init-migrations` | 离线生成当前完整 Model 状态的首个迁移文件 | 否 |
| `aerich migrate --offline` | 根据上一版本状态离线生成后续迁移文件 | 否 |
| `aerich upgrade` | 执行尚未应用的升级 SQL并记录版本 | **是** |
| `aerich downgrade` | 执行降级 SQL并回退版本 | **是** |
| `aerich heads/history` | 查看待应用版本或迁移历史 | 只读 |
| `aerich upgrade --fake` | 只写版本记录，不执行 Schema SQL | **是，高风险** |

`init-db` 会直接创建 Schema，不用于已有库或受控生产发布。`--fake` 只有在人工证明目标数据库与迁移后的 Schema 完全一致时才允许使用；表存在不等于字段、默认值、索引和外键一致。

---

## 3. 数据库方言策略

Aerich 迁移文件中的 `upgrade()` / `downgrade()` 返回生成时数据库方言的原始 SQL。SQLite 与 MySQL 在主键、自增、布尔值、时间类型、索引和表重建语法上不同，因此同一迁移文件不能默认跨方言执行。

项目采用以下边界：

1. MySQL 是生产迁移的权威生成和 Review 方言。
2. 首迁移及后续生产迁移使用 MySQL 配置离线生成，不需要连接真实数据库。
3. 离线生成显式设置 `AERICH_MYSQL_VERSION=8.0`，以 MySQL 8+ 语法作为迁移工具基线；部署前仍须确认目标实例版本。
4. SQLite 测试通过 Tortoise 临时建表并运行实体契约测试，验证 Model 行为和 SQLite 兼容性。
5. MySQL 离线 DDL 契约测试负责尽早发现生产字段、FK 和索引生成差异。
6. 不把 SQLite 生成的迁移应用到 MySQL，也不把 MySQL 迁移应用到 SQLite。

### 3.1 本地数据库策略

任何 Model、字段、约束或索引变化都必须先判断目标数据库和数据保留要求；`development` 的 `generate_schemas()` 只能补建不存在的表，不能为已有表增加/删除字段、修改 NULL/默认值或重建约束，也不维护 Aerich 版本。因此应用启动成功、出现新表或临时测试通过，都不能证明持久 SQLite 已升级。

```text
模型结构变化
   │
   ├─ MySQL／发布环境 → Aerich 增量迁移
   │
   └─ SQLite／本地开发
        ├─ 可丢数据 → 确认影响并备份后重建 + Seed
        └─ 必须保留 → 版本化、方言正确且经过 Review 的 SQLite 升级脚本
```

- MySQL/发布环境始终以 Aerich 迁移、版本记录和发布门槛为权威；本地 SQLite 脚本不得应用到 MySQL，也不得成为生产迁移证据。
- SQLite 可丢数据不等于可以静默删除：必须先确认目标路径、数据影响和备份，再重建并执行项目认可的 Seed。
- SQLite 必须保留数据时，每个结构阶段使用独立版本化脚本。脚本默认只预览，写入必须显式授权；写前创建一致性备份，执行前检查支持的基线，升级后核对字段、索引、外键、关键行数和业务数据不变量。遇到未知或部分迁移状态应停止，不猜测修复。
- 不修改 Aerich 版本表来伪装 SQLite 已执行 MySQL 迁移；SQLite 本地升级状态由目标结构和脚本自身的幂等核验确认。

---

## 4. 标准迁移流程

### 4.1 生成前

1. 确认业务规则、API、数据库设计和 DBML 已同步。
2. 运行相关测试和完整测试。
3. 确认目标数据库引擎与版本。
4. 检查迁移目录和数据库版本表，判断是首次迁移还是增量迁移。
5. 对任何已有数据库执行只读 Schema 审计；有数据时先确认备份和恢复方案。

### 4.2 离线生成

首次建立迁移历史使用 `init-migrations`，后续 Model 变化使用 `migrate --offline`。生成过程必须使用 MySQL 方言配置，并明确 `--app models`；离线模式不得连接或修改真实数据库。

Aerich 0.9.3 在 Tortoise ORM 1.0+ 环境会提示优先考虑 Tortoise 原生迁移。当前项目保持已选定的 Aerich 工具链，不在业务迁移中临时切换；依赖升级或迁移体系专项重构时必须重新评估，并通过新的基线迁移验证后才能切换。

### 4.3 人工 Review

逐项检查生成文件：

- 只包含当前逻辑变更，没有无关表改动；
- 表名、字段类型、NULL、默认值与 `database_design.md` 一致；
- 金额为 `DECIMAL(10,2)`，不存在 float；
- FK 目标和 `RESTRICT` / `SET NULL` 策略正确；
- Option 唯一索引为 `(product_id, duration, participants, day_type)`，且不包含 `is_deleted`；
- Kit 的 `product_id` 保持唯一；
- 所有命名索引与 DBML 一致；
- 不存在意外 `DROP TABLE`、`DROP COLUMN`、数据清空或共享历史覆盖；
- `downgrade()` 的能力与数据损失风险已明确说明。

### 4.4 执行前

1. 明确目标环境和数据库实例。
2. 获取执行授权。
3. 创建可验证的备份或快照。
4. 在临时或预发布 MySQL 上先执行并验证。
5. 评估事务、锁表时间和回滚窗口。

### 4.5 执行后

1. 检查 Aerich 版本记录。
2. 检查表、列、FK、唯一约束和命名索引。
3. 运行数据库契约测试和应用 smoke test。
4. 记录执行环境、版本、结果和任何人工处置。

---

## 5. 已有库与首次迁移

首次引入迁移时，已有数据库通常有三种处理方式：

| 场景 | 推荐处理 |
|------|----------|
| 空库或可丢弃的本地开发库 | 备份后重建，通过首迁移创建完整 Schema |
| Schema 与首迁移完全一致 | 完成人工比对后才可考虑 `upgrade --fake` |
| 有数据且 Schema 存在漂移 | 编写并 Review 专用基线/数据迁移；禁止直接 fake |

判断“一致”必须比较字段、NULL、默认值、索引、FK 和约束，不能只比较表名。

---

## 6. CHECK 约束策略

Product 的正数、金额范围、库存和图片排序规则当前由 Schema 与 Model 校验。物理数据库尚未声明对应 `CHECK`。

增加 CHECK 前必须同时满足：

1. 明确生产 MySQL 最低版本及其 CHECK 执行语义；
2. MySQL 迁移包含稳定的命名约束和可审查的降级 SQL；
3. SQLite 测试策略不会与生产约束产生无声差异；
4. 已有数据已通过约束前置扫描；
5. 数据库设计、DBML、Model/迁移和契约测试同时更新。

在这些条件未满足前，不在首迁移中手写一组无法由当前 Model/测试完整追踪的 CHECK；直接 SQL 写入必须保持受控。

---

## 7. 安全边界

- 未经明确授权，不执行 `upgrade`、`downgrade`、`--fake` 或任何数据重建。
- 不在命令、迁移、日志或文档中写入真实数据库密码。
- 不对共享或生产数据库使用 `init-db`。
- 不删除现有数据库文件来“解决”迁移冲突。
- 不修改已经在共享环境执行过的迁移文件；新增修正迁移。
- 迁移失败时保留现场和错误上下文，先确认数据库状态再决定回滚或前滚。

---

## 8. Inventory 期初流水迁移

`2_20260814104655_add_inventory_transactions.py` 是 MySQL 8+ 离线生成并人工 Review 的 Inventory 增量迁移。它先创建 `inventory_transactions`，再为每条正库存 ProductKit 写一条 `opening_balance`；零库存不生成零变化流水。该文件已在一次性 MySQL 8.0.46 实例完成演练，该次隔离演练本身未写持久库；Inventory M2 后续已随当前 Gate A 的 M0–M7 链应用，其他持久环境仍须分别核验和授权。

### 8.1 执行前硬门槛

1. 停止所有会创建 Kit 或调用旧 `PATCH .../stock` 的应用实例/后台任务，直到迁移与核验全部完成；否则建表与回填之间可能遗漏并发余额变化。
2. 确认目标为 MySQL 8+，Schema 与迁移 0、1 的预期状态一致，且 `inventory_transactions` 不存在。
3. 创建可验证备份或快照。
4. 以下库存范围扫描必须返回零行：

```sql
SELECT product_id, stock
FROM product_kits
WHERE stock < 0 OR stock > 999999;
```

5. 记录正库存 Kit 数量，供执行后比对：

```sql
SELECT COUNT(*) AS positive_kit_count
FROM product_kits
WHERE stock > 0;
```

### 8.2 非事务性与部分失败

MySQL DDL 会隐式提交，`RUN_IN_TRANSACTION = False` 是真实能力声明：建表成功后，即使期初 `INSERT ... SELECT` 失败，也不能依赖事务自动移除表。迁移刻意不使用 `CREATE TABLE IF NOT EXISTS`、`INSERT IGNORE` 或 `ON DUPLICATE KEY UPDATE`；这些语句会把漂移或幂等冲突伪装成成功。

部分失败时必须停止重试并保留表、Aerich 版本记录和错误现场，先只读确认建表、流水和版本状态，再编写可 Review 的前滚恢复方案。禁止为“方便重跑”直接删除表或 fake 版本。

### 8.3 执行后核验

在恢复库存写入前，确认正库存 Kit 均有且只有一条匹配的期初流水，且不存在零库存期初流水：

```sql
SELECT pk.product_id
FROM product_kits AS pk
LEFT JOIN inventory_transactions AS it
  ON it.product_id = pk.product_id
 AND it.transaction_type = 'opening_balance'
 AND it.idempotency_key = CONCAT('inventory:opening:product:', pk.product_id)
WHERE (pk.stock > 0 AND (
         it.id IS NULL
         OR it.before_quantity <> 0
         OR it.change_quantity <> pk.stock
         OR it.after_quantity <> pk.stock
      ))
   OR (pk.stock = 0 AND it.id IS NOT NULL);
```

查询必须返回零行；同时检查期初流水数量等于执行前记录的正库存 Kit 数量，并验证 Aerich 版本已记录为 2。

### 8.4 downgrade 风险

该 downgrade 会删除整个 `inventory_transactions` 表，包括期初流水及启用后产生的调整、扣减和恢复历史，但不会修改 `product_kits.stock`。这不是无损回滚；一旦运行时开始写业务流水，优先前滚修复。只有在明确停机、确认数据影响、完成可验证备份并取得单独授权后，才可考虑执行 downgrade。

### 8.5 一次性 MySQL 演练记录（2026-08-14）

- 环境：MySQL Community Server 8.0.46，独立系统临时数据目录，`127.0.0.1:13306`，空测试 Schema；验证后关闭并删除，未接触现有 `MySQL80` 服务或持久业务库。
- 完整升级：Aerich 依次执行版本 0、1、2，`inventory_transactions` 为 InnoDB/utf8mb4，字段、五组业务索引/唯一键和两条外键均与迁移契约一致。
- 数据迁移：将版本 2 降级后插入 stock=7 与 stock=0 的 Kit，再升级版本 2；前者生成唯一 `0 → 7` 期初流水，后者不生成流水，核验查询返回零个 mismatch。
- Repository smoke：真实 asyncmy/MySQL 上通过升序集合锁查询、余额/流水同事务提交、强制回滚、幂等唯一冲突、批量写入、详情及 Order 来源分页补齐。
- 当时范围限制：该次 Repository smoke 不是并发竞争测试；后续 Phase 4.3.11 已完成两个独立连接的阻塞、稳定锁序、真实 1205 错误和全新事务重试门槛。
- 相邻问题及处置：演练发现 `OrderStatus` 写入普通 `SmallIntField` 时会作为 Enum 字符串传给 MySQL，`OrderRepository.create_order()` 默认状态与 `update_status()` 均报 1366。后续修复将 Model 默认值及 Repository 更新/筛选参数统一为原生整数，并在全新 MySQL 8.0.46 上验证创建 `0`、更新 `1` 及两种状态筛选；物理 Schema 未变化，因此没有新增迁移。

### 8.6 Phase 4.3.11 真实并发门槛（2026-08-14）

- 使用新的独立临时数据目录在 `127.0.0.1:13306` 启动 MySQL Community Server 8.0.46，创建专用 `pinkdoohub_inventory_4311` Schema，并通过 Aerich 真实执行 0、1、2 三份迁移；没有 `--fake`、`generate_schemas()` 或连接现有 3306 服务。
- 9 项真实 MySQL 门槛覆盖不同/相同 key 管理调整、最后一件库存、反向多 Kit 请求、同单取消、管理员调整与下单阻塞、真实 1205 后全新事务重试、迁移版本与 EXPLAIN，以及真实 FastAPI 并发重放/查询。
- `performance_schema.data_lock_waits` 在管理员持锁时观察到下单事务等待；释放后下单读取已提交余额。真实 `innodb_lock_wait_timeout=1` 产生 1205，第二次事务成功且最终只有一个余额变化、流水和 Audit。
- 代表性 5,000 条合法流水基数和选择性数据经 `ANALYZE TABLE` 后，锁查询使用 ProductKit `product_id` 唯一索引，指定 Product 与全局分页分别使用 `idx_inventory_product_created_id` 和 `idx_inventory_created_id`。小表或单一 Product 数据下优化器可能合理选择全表扫描，因此 EXPLAIN fixture 必须同时提供足够基数与选择性。
- 测试连接由安全 fixture 限制为 `127.0.0.1`、非 3306 端口和专用 Schema 前缀；跨 SQLite/MySQL 初始化前后清空 Tortoise 1.1.7 不区分后端的 Executor SQL 缓存，避免占位符污染。实例与 Schema 在验证后销毁。没有应用持久、共享或生产数据库，也没有更改迁移文件。

### 8.7 Phase 4.3.12 最终 Review 复验（2026-08-14）

- 最终 Review 使用新的独立临时数据目录重新启动 MySQL Community Server 8.0.46，只监听 `127.0.0.1:13306`，并在新的专用 Schema 上再次真实执行 Aerich 0 → 1 → 2；三条版本记录完整。
- 9 项 MySQL 门禁再次全部通过，随后在同一 pytest 进程中与 SQLite 回归共同执行完整 1431 项测试，证明最终 Schema/文档/响应边界修复没有破坏跨后端测试隔离。
- 复验未连接现有 3306 服务，未使用 `--fake` 或运行时自动建表。完成后通过 13306 正常发送 `SHUTDOWN`，确认端口退出，再删除经过绝对路径与临时目录前缀校验的专用数据目录；`MySQL80` 服务保持运行。
- 本次最终 Review 没有新增或修改迁移 SQL，也没有对任何持久、共享、开发或生产数据库执行迁移。

### 8.8 Phase 9.2.4 CI 门槛本地演练（2026-08-31）

- `.github/workflows/ci.yml` 的 `backend-mysql-release` 固定 `mysql:8.0.46`、`127.0.0.1:13306` 和 `pinkdoohub_inventory_4311_ci`。Phase 9.5 起真实执行 Aerich 0→1→2→3 后运行现有 9 项 MySQL release gate；禁止 `--fake`、`init-db`、运行时自动建表和默认 3306。在 2026-08-31 这个历史检查点，Gate A 已部署候选仍停留在 0→2，未获得发布授权前不得套用该 CI 迁移结论更新持久环境；Gate A 后续已于 2026-09-08 受控升级到 M7，当前待执行的是 M7→M8。
- `scripts/ci/check_mysql_gate.py` 在连接前要求 `APP_ENV=testing`，并证明 Aerich `DB_*` 与 pytest `INVENTORY_MYSQL_TEST_*` 完全指向同一个 disposable target；snapshot 只记录安全目标、MySQL 版本、三条 Aerich 版本、Git SHA 和 run ID，不写密码或连接串。
- 本地使用唯一命名 Docker 容器按同配置真实演练：MySQL 8.0.46、三条迁移和 9 项并发/1205/EXPLAIN/HTTP 门槛全部通过。cleanup 删除专用 Schema、停止容器并确认非运行和 13306 关闭；随后删除容器对象与临时证据目录，未连接 3306 或任何持久/共享数据库。固定 Docker image 只作为共享缓存保留。
- 9.2.6 已由 Draft PR #2 的 GitHub Actions Run 33355935212 在真实 MySQL 8.0.46 service 上重跑并通过，保存了 preflight、迁移日志、版本快照、JUnit 与 cleanup JSON，Phase 9.2 的 MySQL CI 风险据此关闭。该证据仍不替代 9.3 的生产相似备份恢复和失败处置演练。

---

## 9. Wallet / Payment / Refund M4 发布流程

`4_20260905162243_add_wallet_payment_refund.py` 是 MySQL 8+ 离线生成并人工 Review 的资金增量迁移。它创建 `wallet_accounts`、`recharge_orders`、`payments`、`payment_settlements`、`refunds`、`wallet_transactions`，并把 InventoryTransaction 的数据库注释补充为包含 `order_refund_restore`。`RUN_IN_TRANSACTION=False` 明确承认 MySQL DDL 隐式提交。

截至 2026-09-07，M4 已在一次性 MySQL 8.0.46 完成 Wallet `9 passed` 与 Inventory + Reservation + Wallet `30 passed`，覆盖关键资金/库存闭环、四个资金幂等列的 `ascii_bin`、并发调账/余额支付/退款、真实 1205、1213 整事务回滚重试、可观测资金库存锁等待和关键 `EXPLAIN`。在该历史检查点，新的 Wallet-expanded workflow 尚待远端干净 SHA 复现，M4 也尚未通过 Aerich 应用到任何持久环境；后续 workflow 已远端通过，当前持久 Gate A 已于 2026-09-08 完成 M4、两个历史 backfill 与 reconcile。共享、预发布和生产数据库仍须分别核验与授权。development 的 `generate_schemas` 会在应用启动或热重载时为 SQLite 自动补建缺失表，却不会写入 Aerich 版本记录；因此“表已存在”不等于本地持久 `db.sqlite3` 已按 Aerich 迁移，也不能作为可追溯的发布证据。

### 9.1 执行前硬门槛

1. 明确目标实例、Schema、当前 Aerich 版本及变更窗口，并取得迁移与停写授权；确认迁移 0→3 已正确应用且六张 M4 表尚不存在。
2. 停止注册、首次微信登录、注销、Order/Inventory 及全部钱包/支付/退款写入；全部历史 backfill 完成前不得让新旧应用版本并行创建钱包或结算事实。
3. 创建可验证备份或快照，并记录 `role=user`、`role=admin/super_admin` 各自数量。
4. 保持 `PAYMENT_PROVIDER=disabled`、`WALLET_TOPUP_ENABLED=false`，以及 production 的 `WALLET_ADMIN_WRITE_ENABLED=false`、`WALLET_ORDER_PAYMENT_ENABLED=false`、`WALLET_REFUND_ENABLED=false`。数据库迁移成功不等于资金能力可以启用。
5. 在新的可销毁 MySQL 8+ Schema 上先按“完整 Aerich 0→4 → 历史 NORMAL/DISABLED 普通 USER 钱包 backfill → 历史人工结算 backfill → reconcile/结构核验 → HTTP/并发门槛”的正式顺序演练，并覆盖失败处置；历史 DELETED USER 不补建钱包。
6. 商户号、AppID 关联、HTTPS notify URL、API v3 密钥、证书/私钥和经营进件资料不属于 M4 数据；正式微信接入阶段核验后再写入受控 Secret/发布记录，不进入迁移、日志或普通文档示例。

### 9.2 非事务性与部分失败

M4 中任一 `CREATE TABLE` 或最后的 `ALTER TABLE` 成功后，即使后续语句失败，也不能依赖数据库事务自动恢复。迁移不应通过手工删表、重跑、`--fake`、`IF NOT EXISTS` 或忽略冲突伪装成功。

失败后保持停写，保存错误与 Aerich 版本现场，只读检查六张表、每个字段/FK/UNIQUE/索引和 Inventory enum 注释究竟落到哪一步；基于实际状态编写可 Review 的前滚恢复方案。未经单独数据影响确认和授权，不执行 M4 downgrade。

### 9.3 普通 USER 钱包与历史人工结算 backfill

M4 刻意不为历史用户生成钱包或零元“期初流水”，也不在非事务 DDL 中猜测历史支付事实。应用 M4 后、应用恢复写入前必须严格按“钱包 → 人工结算 → reconcile”执行：

```bash
python -m app.tasks.wallet_account_backfill
# 记录 preview 摘要中的 through_user_id=N，复用同一个冻结上界：
python -m app.tasks.wallet_account_backfill --through-user-id N --apply
python -m app.tasks.wallet_account_backfill --through-user-id N
python -m app.tasks.legacy_manual_settlement_backfill
# 记录预览摘要中的 through_order_id=N，复用同一个上界：
python -m app.tasks.legacy_manual_settlement_backfill --through-order-id N --apply
python -m app.tasks.legacy_manual_settlement_backfill --through-order-id N
python -m app.tasks.wallet_reconcile
```

- 第一次 wallet backfill 默认为 dry-run，摘要报告 `through_user_id`、`scanned`、`would_create`；`through_user_id` 是预览时当前最大 User ID，用于冻结后续 apply 范围。可用 `--batch-size 1..1000` 调整批次，默认 500。
- apply 必须显式传入该预览上界：`--through-user-id N --apply`；缺少 `--through-user-id` 时必须在连接数据库前拒绝。命令按 User ID 稳定游标扫描，每批在独立事务内按 User ID 升序锁定候选 User，锁后复验仍为 `role=user` 且 `status=normal/disabled`，再重新查询 WalletAccount 存在性；只为仍合格且仍缺失者创建唯一 `0.00` WalletAccount。预选后已变为 DELETED/staff 或已有钱包者跳过，不创建 WalletTransaction。
- 第二次 wallet dry-run 必须显式复用同一 `--through-user-id N` 并报告 `would_create=0`，之后才进入 legacy settlement preview；不得使用一个新的未冻结上界伪装前一次 apply 的复核。
- legacy settlement 首次运行默认 dry-run；扫描固定上界内的 PAID/COMPLETED Order，只为仍归属普通 `USER` 的合格订单新增事实。disabled owner 允许回填停写前已经发生的历史人工收款，但不能发起新的消费；deleted owner 不得新增事实。每单必须存在且仅存在一条 `target_type=order/action=MARK_ORDER_PAID` Audit，才可按 Order 的 user/amount 和 Audit 时间创建 `purpose=order/method=manual/status=succeeded` Payment 及同额唯一 Settlement。Payment 使用 `PY` ULID 编号及 `payment:legacy-manual:order:{order_id}` 内部幂等键，充值关联和 Provider reference 均为空。
- `--apply` 必须显式传入预览得到的 `--through-order-id`，缺少时在连接数据库前拒绝。apply 先对固定范围做全量只读预检，发现任一 blocker 时全局零写入；随后才按 Order ID 稳定游标、小批事务以及 User→Order 锁序执行。已有完全一致 Payment/Settlement 计为 replay，包含 deleted owner 的零写入完整重放。非普通客户 owner、deleted owner 缺失事实、缺失/重复 Audit、内部 key 被其他 Order 占用、只有 Payment 没有 Settlement、Settlement 未绑定预期 Payment、金额/用户/状态/渠道不一致或同一历史订单出现多 Payment，均逐单报告 blocker 并让命令最终非零退出；命令不得自动删除、覆盖或猜测修复矛盾事实。若预检后仍在某个锁内批次发现新 blocker，该批不写并立即停止；之前已提交批次保持可重放，不伪装为全局成功。
- apply 后以同一 `through_order_id` 再次 dry-run，必须 `would_create=0`、`blocked=0`，且 eligible 数全部计入 `replayed`。若有 blocker，保持功能开关关闭，导出对应 Order/Audit/Payment/Settlement 只读证据并逐单人工裁决。
- reconcile 全程只读，按钱包 ID 及每个钱包的 `created_at ASC, id ASC` 稳定扫描，将权威余额与流水净额比较，并检查非零变化量、单行余额算术、前后余额范围、相邻余额链、末条余额与权威余额；无流水钱包必须保持 `0.00`。摘要中的 `mismatches` 是异常钱包数，`violations` 是可重叠的具体规则命中数；同一钱包只计一个 mismatch，非零余额且无流水会同时命中净额与无流水两项规则。任一违规都会令任务退出非零。任务绝不自动更新余额、删除坏流水或伪造纠错流水；任何差异都必须保持能力关闭并人工调查。

### 9.4 执行后数据核验

至少执行以下只读核验；全部必须返回预期结果：

```sql
-- 所有 NORMAL/DISABLED 普通 USER 都有且只有一个钱包（UNIQUE 保证“至多一个”）；历史 DELETED 可无钱包
SELECT COUNT(*) AS missing_user_wallets
FROM users AS u
LEFT JOIN wallet_accounts AS w ON w.user_id = u.id
WHERE u.role = 1 AND u.status IN (1, 2) AND w.id IS NULL;

-- ADMIN/SUPER_ADMIN 不得拥有钱包
SELECT COUNT(*) AS privileged_wallets
FROM wallet_accounts AS w
JOIN users AS u ON u.id = w.user_id
WHERE u.role IN (2, 3);

-- backfill 本身不得制造零元流水
SELECT COUNT(*) AS zero_amount_ledger_rows
FROM wallet_transactions
WHERE change_amount = 0.00;

-- 所有当前余额都在硬上限内
SELECT id, user_id, balance
FROM wallet_accounts
WHERE balance < 0.00 OR balance > 1000.00;

-- 固定历史上界内的 PAID/COMPLETED 必须已有唯一结算
SELECT o.id, o.order_no
FROM orders AS o
LEFT JOIN payment_settlements AS s ON s.order_id = o.id
WHERE o.id <= <through_order_id>
  AND o.status IN (1, 3)
  AND s.id IS NULL;
```

`missing_user_wallets`、`privileged_wallets`、`zero_amount_ledger_rows` 必须为 0，余额范围和历史缺失结算查询必须返回零行。零金额 SQL 保留为独立的纵深核验；`wallet_reconcile` 还必须覆盖单行算术、余额范围、流水链、末条余额和无流水钱包规则，并得到 `mismatches=0 violations=0`。另需核对 Aerich 已记录版本 4、六张表的字段/FK/UNIQUE/命名索引与 `database_design.md` / DBML 一致。

### 9.5 新增真实 MySQL 发布门槛

恢复或开启任何生产资金写前，必须在可销毁 MySQL 8+ 上覆盖：

- 新注册/首次微信 USER 原子建钱包、历史人工结算与 NORMAL/DISABLED USER wallet backfill 可续跑、冲突阻断、历史 DELETED 不补钱包及 ADMIN/SUPER_ADMIN 零钱包；
- ADMIN 调账、余额支付、ADMIN+ 代客钱包订单、人工结算和 PAID/COMPLETED 全额退款的真实行锁、唯一幂等、1205/1213 完整事务重试与故障回滚；四个资金幂等列必须验证为 ASCII / `ascii_bin` 的大小写敏感逐字节比较，并证明仅大小写不同的合法 key 不会碰撞或误重放；调账重放需核验完整流水身份与余额算术，余额/代客支付重放需核验 Order、Payment、Settlement 和扣款流水，退款重放需核验 Settlement、Payment、Refund 及钱包渠道入账流水，任何篡改或部分事实均须零写入拒绝；人工 `pending → paid` 需覆盖 `User → Order` 锁序、仅 NORMAL 普通 USER 成功以及 staff/disabled/deleted 零写入拒绝；
- `0.00..1000.00` 余额、`1.00..1000.00` 单笔充值 Schema、正向入账的退款预留敞口，以及退款成功释放敞口并全额入账；
- 干净 M4 数据运行只读 `wallet_reconcile` 必须得到 `mismatches=0 violations=0`；在同一可销毁 Schema 通过直接 SQL 分别注入零金额、单行算术/范围或流水链异常后，任务必须稳定非零退出，相同 `created_at` 的流水仍以 ID 打破顺序平局。异常夹具验证后随专用 Schema 一并销毁，不得用于持久数据修复；
- 多 Kit 的 Product ID 升序锁、代客订单与退款恢复竞争、PAID 恢复/COMPLETED 不恢复、相关关键查询 `EXPLAIN`；
- Provider disabled 和所有关闭 Feature Flag 的 HTTP 503，且 Wallet/Payment/Settlement/Refund/Inventory/Audit 零写入；
- 注销对非零余额、处理中资金和可退款钱包结算敞口的阻断（余额为零也不能绕过），以及钱包关闭和历史 RESTRICT 外键保留；还要注入“DB commit 成功、提交后 Redis family 清理失败”，确认 API 仍成功、`status/auth_version` 阻断后续会话，只记录不含 Token/JTI 的高优先级安全事件，并将运维重试清理纳入发布处置。
- 六个用户侧 wallet/payment 端点对 ADMIN/SUPER_ADMIN 统一返回 403；严格资金 Out Schema 必须拒绝 Payment 用途/关联互斥错误、成功 Payment/Refund 缺失 `succeeded_at`、OrderFinancial 的订单/渠道/金额错配，以及 WalletPayment/AssistedWalletOrder 的非成功状态或错误关联。

验证必须记录 disposable target、MySQL 精确版本、Aerich 0→4 记录、测试结果和清理证据；不得连接默认 3306 或任何持久 Schema。

### 9.6 downgrade 风险

M4 downgrade 会删除全部 WalletTransaction、Refund、PaymentSettlement、Payment、RechargeOrder 和 WalletAccount，并从 Inventory enum 注释移除 `order_refund_restore`；不会逆向重建被扣减/退款的资金或库存。这是明确的数据破坏操作。一旦产生任何业务事实，默认只允许经 Review 的前滚修复；只有在停写、完成可验证备份、确认精确数据影响并取得单独授权后，才可考虑 downgrade。

### 9.7 本地 SQLite 边界

MySQL M4 不得应用到 SQLite。development 启动或热重载调用 `generate_schemas()` 时，既有持久 `db.sqlite3` 可能被自动补建缺失表，但不会对既有表执行 `ALTER`，也不会写入 Aerich 版本记录；因此“表已存在”不能作为 M4 已迁移或结构完整的证据，也不能通过删除数据库文件掩盖迁移缺口。可丢弃的本地库只能在明确备份/确认后重建；需保留数据的 SQLite 必须另行设计和 Review 方言正确的受控迁移/导入方案。创建六张表之前不得运行 wallet backfill，也不得把 development 或临时测试库自动建表的结果误报为持久本地库已完成迁移。

### 9.8 一次性 MySQL M4 闭环记录（2026-09-05）

- 环境：一次性 `mysql:8.0.46` 容器，回环地址非 3306 端口，`pinkdoohub_wallet_` 前缀专用 Schema；通过 Aerich 真实执行完整 0→4，未使用 `--fake` 或运行时自动建表。
- 验证：`tests/wallet/mysql/test_wallet_mysql_flow.py` 在迁移后的真实 asyncmy/MySQL 上 `2 passed`；一项完成 ADMIN 正向调账、ADMIN+ 代客钱包 Kit 订单、订单直接 PAID、钱包/库存扣减、PAID 全额退款、钱包/库存恢复及退款幂等重放，最终 Wallet/Inventory 流水、Payment、Settlement、Refund 和四条 Audit 数量/类型一致；另一项确认四个资金幂等列均为 `ascii_bin`，并证明仅大小写不同的合法 ASCII key 分别提交且不被误判为重放。
- 安全：fixture 只有在 `WALLET_MYSQL_TEST_ENABLED=1` 时运行，并拒绝非 `127.0.0.1`、默认 3306、非法端口和非专用 Schema 前缀；测试前仅清空已验证专用 Schema 的业务表，保留 Aerich 版本链。
- 清理：容器停止后由 `--rm` 自动删除，`docker ps` 复核无匹配；没有读取或修改本地持久 `db.sqlite3`、Gate A、共享、预发布或生产数据库。
- 证据边界：本节记录 2026-09-05 当时的 M4 单链路与 `ascii_bin` 基线；当时尚未覆盖的钱包专项并发、真实 1205/1213 与资金查询 EXPLAIN 已由后续 §9.10 关闭。M4 持久应用、backfill/reconcile 和生产启用仍不在本节证据内。

### 9.10 Wallet 扩展 MySQL 门槛（2026-09-07）

- 环境：一次性 `mysql:8.0.46`、回环 `127.0.0.1:13316`，分别使用 Wallet 专用 Schema 与 CI 冻结 `pinkdoohub_inventory_4311_ci`，均真实执行 Aerich M0→M7。
- 验证：Wallet 专项 `9 passed in 4.35s`，Inventory + Reservation + Wallet 联合 `30 passed in 13.33s`。覆盖并发不同/相同 key 调账、并发余额支付与退款只提交一次、真实 1205 后全新事务重试、首轮写后注入 1213 的完整回滚重试、`performance_schema.data_lock_waits` 可观测资金/库存等待，以及五个冻结资金索引的 `EXPLAIN`。
- CI：`backend-mysql-release` 候选加入 `tests/wallet/mysql`，SQLite Job 显式忽略该目录；Wallet fixture 可复用统一受保护的 `INVENTORY_MYSQL_TEST_*`，仍拒绝远端地址、3306 和非专用 Schema。
- 清理与边界：任务容器精确停止并由 `--rm` 删除，13316 已释放；未访问任何持久数据库。完整记录见 `docs/09_release/reports/wallet_mysql_release_gate_2026-09-07.md`。该候选随后由 Run 34134341829 远端 8/8；Gate A 又于 2026-09-08 完成 M4、两个 backfill 与 reconcile。该历史证据仍不授权生产资金开关。

### 9.9 M4 资金幂等键排序规则复验（2026-09-05）

- 原因：M4 原先只为资金表指定 `utf8mb4` 字符集，四个 `idempotency_key` 会继承 MySQL 默认的不区分大小写排序规则，使仅大小写不同的两个合法 ASCII key 可能被 UNIQUE 或重放查询错误地视为同一业务身份。
- 实现：`RechargeOrder`、`Payment`、`Refund` 与 `WalletTransaction` 统一使用 `AsciiBinaryCharField`；该字段在 MySQL 生成 `VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin`，并在 Aerich M4 快照记录相同方言类型。Tortoise ORM 1.1.7 不支持字段级 `collation` / `db_collation` 参数，未知参数会被静默忽略，因此不得用普通 `CharField` 伪装该约束。
- 验证：在新建的一次性 `mysql:8.0.46` 容器、回环 `127.0.0.1:13317` 与专用 `pinkdoohub_wallet_idempotency_m4` Schema 真实执行 Aerich 0→4；MySQL 专项 `2 passed`，通过 `information_schema.COLUMNS` 确认四列均为 `ascii_bin`，并证明 `Case-Sensitive-Key` 与 `case-sensitive-key` 的两次相同 ADMIN 调账分别提交、均非重放且余额累计两次。
- 清理：精确停止 `pinkdoohub-wallet-idempotency-m4` 后由 `--rm` 删除；`docker ps -a` 未发现该名称，`127.0.0.1:13317` 无监听。未连接或修改默认 3306、本地持久 SQLite、Gate A、共享、预发布或生产数据库。

## 10. Reservation N1 M5 发布流程

`5_20260906094653_add_reservations.py` 是 MySQL 8+ 离线生成的 Reservation N1 增量迁移候选。它创建：

- `store_business_days`：上海当地日期的一日一行并发锁点，含命名唯一索引 `uidx_store_business_day_date`；
- `reservations`：四个 `ON DELETE RESTRICT` 外键、UTC 起止时间、完整 Option 创建快照、四状态、拒绝/取消原因、三个状态时间和五组查询索引。

M5 不创建 Order/Payment 关联，不保存手机号，不回填历史预约，也不包含 N2 通知 Outbox/Subscription/Recipient/Delivery 表。`RUN_IN_TRANSACTION=False` 明确承认 MySQL DDL 隐式提交。

截至 2026-09-06，M5 已在仓库中离线生成，并在一次性 MySQL 8.0.46 专用 Schema 真实完成 Aerich 0→5、Reservation 核心并发、事务回滚、1205/1213 重试与 EXPLAIN 门槛；详细记录见 §10.8。当时 M5 尚未通过 Aerich 应用到本地持久 `db.sqlite3`、Gate A、共享、预发布或生产数据库。2026-09-08 的后续受控执行已将 M5/M7 应用到当前持久 Gate A M7；共享、预发布和生产数据库仍须分别核验和授权。development 的 `generate_schemas()` 可能给 SQLite 补建缺失表，但不会 ALTER 既有表或写 Aerich 版本，不能视为目标环境迁移证据。

### 10.1 迁移链与执行顺序

M5 完成验证时的权威链为（当前完整链另见 §11）：

```text
0_20260810101218_init.py
→ 1_20260813130455_add_order_tables.py
→ 2_20260814104655_add_inventory_transactions.py
→ 3_20260902125032_phase95_external_identity.py
→ 4_20260905162243_add_wallet_payment_refund.py
→ 5_20260906094653_add_reservations.py
```

不能从 3 跳过 M4 直接手工创建 Reservation 表，也不能用 `--fake` 补版本。若目标库仍停留在 0→2 或 0→3，必须先执行并核验 M4，再执行 M5；M4 的 wallet backfill、legacy manual settlement backfill、reconcile 与开关启用仍按 §9 的独立业务门槛处理。M5 无历史回填，但不能用“无回填”弱化结构、并发和 HTTP 验证。

现有 CI / Gate A 若只执行 0→3 或 0→4，属于滞后发布链，必须在正式合入/启用前升级到 0→5 并保留每一条 Aerich 版本记录。旧 Inventory 或 Wallet smoke 不能作为 M5 证据。

### 10.2 执行前硬门槛

1. 明确目标实例、Schema、当前 Aerich 版本、变更窗口和回滚/前滚负责人；获得迁移和停写授权。
2. 确认目标使用 MySQL 8.x、`utf8mb4`，M4 已按顺序应用；确认两张 M5 表和所有索引均不存在。
3. 备份目标库并实际验证恢复路径；记录备份标识、校验和和恢复耗时。
4. 停止注册/注销、Product/Option 写入、预约写入以及会产生关联用户状态变化的管理操作；不得让不认识 M5 的旧应用和新应用同时写。
5. 扫描现有 User/Product/ExperienceOption 外键前置数据；M5 不回填 Reservation，因此预期建表后两张表均为空。
6. 在新的可销毁 MySQL 8.x 专用 Schema 先真实执行完整 0→5，禁止默认 3306、共享 Schema、`--fake`、运行时自动建表或手工跳过语句。
7. 在启用 Router 前完成 §10.5 的真实 MySQL 与 HTTP 门槛，并确认 OpenAPI/客户端契约已经同步。

### 10.3 非事务性与部分失败

M5 两条 `CREATE TABLE` 各自可能隐式提交。若第一张表成功、第二张表或 Aerich 版本写入失败，数据库事务不能自动还原。失败后必须：

1. 保持应用停写，不重跑、不 `--fake`、不加 `IF NOT EXISTS` 掩盖现场；
2. 保存错误、Aerich 版本表、`SHOW CREATE TABLE`、外键和索引现场；
3. 判断 `store_business_days` / `reservations` 中是否已经存在任何业务行；
4. 基于实际完成步骤制定可 Review 的前滚恢复方案；
5. 只有在确认没有业务数据、备份可恢复并获得单独破坏性授权后才考虑精确 downgrade/删除表。

### 10.4 执行后结构与数据核验

至少确认：

- Aerich 版本完整到 5，且不存在跳号、重复或 fake 记录；
- `store_business_days.business_date` 为 DATE、NOT NULL，并命中 `uidx_store_business_day_date`；`is_closed` 默认 false；
- `reservations` 四个外键分别指向 users、store_business_days、products、experience_options，全部 `ON DELETE RESTRICT`；
- `scheduled_start_at/scheduled_end_at` 和三个状态时间为 `DATETIME(6)`；Option price 为 `DECIMAL(10,2)`；所有 Enum 列为冻结长度 VARCHAR；
- 五个 Reservation 查询索引的列顺序精确为 Model/数据库文档所列；
- 不存在 `(user_id, experience_option_id, scheduled_start_at)` 或时段容量 UNIQUE；同槽多条预约是 N1 业务允许行为，不得在迁移现场手工追加去重约束；
- 新装空库两表行数为 0；迁移本身没有伪造预约、手机号或营业日；
- 通过正式 API 创建后，每条 Reservation 的 business_day/product/option/user FK 有效，UTC 起止与上海当地响应一致，快照不依赖后续 Product/Option 修改；
- 状态、原因和状态时间组合满足 N1 不变量；不存在 rejection/cancellation reason 同时非空的脏数据。

### 10.5 新增真实 MySQL 发布门槛

在一次性 MySQL 8.x 专用 Schema 上至少覆盖：

- 完整 Aerich 0→5 和 `SHOW CREATE TABLE` / information_schema 结构验证；
- 同一日期首次 `StoreBusinessDay` 创建竞争，只产生一行且仅精确命名 UNIQUE 冲突可触发完整事务重试；
- 创建预约与管理员设置同日店休竞争，不允许“店休成功后仍提交新预约”的双成功结果；
- 同一用户对同一 Option/时段连续提交两次会得到两个不同 Reservation ID，证明 N1 没有误加同槽去重或自动容量限制；
- 两个管理员并发关同日，只有一方首次关闭/批量取消，另一方为确定性 replay，不重复状态变化和 Audit；
- 同一预约 confirm/reject/cancel 竞争只有一个合法状态迁移；
- 相反日期、多预约和大批量店休的稳定营业日/Reservation ID 锁序；
- 真实 1205 与 1213 注入，确认每次重试是全新完整事务，最多 3 次，失败尝试不遗留 Reservation、状态、批量取消或 Audit；
- 用户全部列表、用户按状态列表、管理状态/日期筛选、店休批量取消和注销 `user + status + scheduled_end_at` 查询的真实 `EXPLAIN` 命中预期索引或有明确可接受计划；
- FastAPI 真实认证/权限/严格 422、40451/40452、40951–40953、42251–42255、手机号掩码/详情隔离、UTC/上海本地字段与 201/200 店休重放；
- Product/Option 下架或改价、用户改手机号、账号注销阻断与匿名化后的历史手机号 null 等跨模块回归。

验证记录必须包含 disposable target、MySQL 精确版本、Aerich 0→5 版本行、测试/EXPLAIN 结果、未触碰持久库声明和实例/端口/临时目录清理证据。

### 10.6 downgrade 风险

M5 downgrade 按外键顺序先删除 `reservations`，再删除 `store_business_days`。这会永久删除全部预约、Option/价格快照、状态历史和自定义店休锁点；AuditLog 的通用 target 不是数据库外键，不会自动级联清除，可能留下无目标审计。downgrade 不会恢复被店休取消的预约，也不能还原顾客联系方式。

一旦产生任何 Reservation 或店休业务事实，默认只允许经 Review 的前滚修复。只有在停写、验证备份、精确评估数据影响并取得单独破坏性授权后，才可考虑 downgrade；不得把 downgrade 当作普通部署回滚按钮。

### 10.7 本地 SQLite 边界

MySQL M5 不得直接应用到 SQLite。development `generate_schemas()` 只能创建当前缺失表，不会对已有表做增量 ALTER，也不会维护 Aerich 版本。即使本地 `db.sqlite3` 已出现 `reservations` 表，也必须单独检查字段、索引和来源，不能声称“已执行 M5”。需要保留的 SQLite 数据必须另行设计方言正确的受控迁移/导入方案；可丢弃数据库也只能在用户确认备份/重建影响后处理。

### 10.8 一次性 MySQL M5 核心门槛记录（2026-09-06）

- 环境：任务专属 `mysql:8.0.46` 容器 `pinkdoohub-reservation-n1-mysql-20260906`，只绑定回环 `127.0.0.1:13307`，使用专用 `pinkdoohub_inventory_4311_ci` Schema；未连接默认 3306、开发、Gate A、共享、预发布或生产数据库。
- 迁移：通过 Aerich 真实顺序执行 0→1→2→3→4→5，六条版本记录完整，未使用 `--fake`、`init-db` 或运行时 `generate_schemas()`。
- Reservation 专项：`tests/reservation/mysql` 为 `7 passed`，覆盖“创建先持营业日锁后被店休取消”和“店休先持锁后创建拒绝”两个方向、同日并发店休首次/重放、批量预约与审计同事务回滚、真实 InnoDB 1205、首轮事务写后注入 1213 的完整事务重试，以及营业日唯一索引和五个 Reservation 查询索引的 EXPLAIN。
- 联合回归：同一迁移后 Schema 连续运行 `tests/inventory/mysql tests/reservation/mysql`，结果 `16 passed`，确认 M5 没有破坏既有 Inventory MySQL 门槛。
- 清理：容器以优雅 stop 结束并由 `--rm` 删除；`docker ps -a` 按精确名称复核为空，`127.0.0.1:13307` 无监听，任务临时 preflight/snapshot 报告目录已删除。
- 证据边界：该记录证明 M5 可在精确版本的可销毁 MySQL 上完成迁移，核心关店一致性、回滚、重试和索引计划成立；它不表示任何持久环境已经迁移，也不替代正式发布流水线留证、真实客户端验收、备份恢复、变更窗口与上线授权。

---

## 11. Color-selectable Kit M6 发布流程

`6_20260906123000_add_color_selectable_kits.py` 是跨 Product、Order 与 Inventory 的 MySQL 8+ 增量迁移候选。它为 `product_kits` 增加 fixed / color-selectable 形态与 10g 销售单位，创建全局 `bead_colors` 221 槽和商品级 `product_kit_colors` 余额表，并给 `order_items`、`inventory_transactions` 增加颜色关联/快照字段。M6 的 ALTER、建表和 221 行种子插入受 MySQL 隐式提交影响，`RUN_IN_TRANSACTION=False`；不得把它描述为整份原子迁移。

当前权威链为：

```text
0_20260810101218_init.py
→ 1_20260813130455_add_order_tables.py
→ 2_20260814104655_add_inventory_transactions.py
→ 3_20260902125032_phase95_external_identity.py
→ 4_20260905162243_add_wallet_payment_refund.py
→ 5_20260906094653_add_reservations.py
→ 6_20260906123000_add_color_selectable_kits.py
→ 7_20260907190000_add_reservation_settings.py
→ 8_20260908140000_add_bead_color_swatch_hex.py
```

M6 没有导入真实色号、名称或色板图，只创建 1–221 的未配置、未激活占位槽；后续批量清单/图片导入属于独立的 dry-run/apply 运维步骤，不能混进迁移。历史 `product_kits` 必须保持原库存，新增 `kit_kind` 取数据库默认 `fixed`，`sale_unit_grams` 保持 null。M6 不能绕过 M4 的钱包 backfill/reconcile 或 M5 的 Reservation 发布边界；完整迁移记录到 6 也不表示这些业务开关已经获准启用。

### 11.1 执行前与部分失败门槛

1. 确认目标是 MySQL 8.x、`utf8mb4`，Aerich 精确停在 M5；保存七条迁移文件的 Review 版本，并确认 M6 表、列、外键和索引尚不存在。
2. 备份并实际验证恢复路径；停写 Product/Order/Inventory/Wallet/Refund。M6 会改变订单和库存事实的外键形状，不能让旧应用与新应用并行写。
3. 扫描历史 `product_kits`：`stock` 必须在既有范围内且不可为 null；记录 fixed Kit 数量与库存摘要，作为升级后对账基线。
4. 若任何 ALTER、CREATE、INSERT 或 Aerich 版本写入失败，保持停写并保存 `SHOW CREATE TABLE`、`information_schema`、221 槽计数和 Aerich 现场；不得用 `IF NOT EXISTS`、手工补列或 `--fake` 掩盖部分提交。
5. 一旦 M6 表产生颜色配置、订单或库存流水事实，默认只允许经 Review 的前滚修复。downgrade 会删除全部颜色级库存配置，并把 color-selectable 父级库存压回旧形状；只有在精确数据评估、可验证备份和单独破坏性授权后才可执行。

### 11.2 一次性 MySQL CI 演练

`backend-mysql-release` 当前在固定 disposable Schema 中执行以下顺序：

1. `aerich --app models upgrade` 从空库真实执行完整 0→9，禁止 `--fake`、`init-db` 或运行时 `generate_schemas()`；
2. 依次回退 M9、M8 与 M7，写入受控 M7 前 Reservation/单日店休历史，再回退 M6 并写入 `stock=7` 的受控 fixed Kit；
3. 正常升级 M6→M7→M8→M9，执行 30 桌 bootstrap，再执行 no-op `upgrade` 与 bootstrap replay，证明历史 fixed 库存、Reservation 事实、M6/M7 默认值、M8 精确 HEX、M9 四表/30 桌和 Aerich 幂等边界保持；
4. `check_mysql_gate.py snapshot` 同时核验 MySQL 8.0.46、M0–M9 十条版本、M6 的 221 槽/关键列/FK/索引、M7 `reservation_settings` 单例/默认周一/CHECK/UNIQUE、M8 nullable `VARCHAR(7)` 与冻结清单逐槽相等的 221 个唯一 HEX，以及 M9 四表/命名 UNIQUE/10 个 RESTRICT 外键/精确 `T01`–`T30`；
5. 联合运行 `tests/inventory/mysql tests/reservation/mysql tests/wallet/mysql tests/table_sessions/mysql`，覆盖 M6 颜色集合锁/索引计划、M7 固定店休更换、资金/库存历史数据，以及 M9 同桌/同用户/同订单竞态、付款计时、超时竞争、幂等释放、回滚和 1205/1213；
6. 保存 preflight、M6/M7 legacy seed、迁移日志、最终 snapshot 与 JUnit；无论前序结果如何都删除精确专用 Schema、停止准确的 service container，并复核容器非运行与非默认端口已释放。

fixture 不负责执行迁移。为防止函数级清理把迁移种子抹掉后由运行时代码悄悄补种，MySQL 门槛在各用例之间保留 `bead_colors` 与 `aerich`，只清空其他业务表；snapshot 仍在 pytest 之前直接验证原始迁移结果。

### 11.3 当前证据边界

2026-09-07，本地提交 `58d8435` 的候选已在一次性 MySQL 8.0.46 中完成 Aerich 0→7、M0–M6 各历史起点→M7、M6/M7 snapshot 及 Inventory + Reservation 联合 `21 passed`。专用 Schema、容器和端口均已清理。该结果随后由 head `4d6430c...` / Run 34129910349 远端 8/8；持久 Gate A 又于 2026-09-08 完成 M2→M7 与 M6 色卡发布。SQLite 专用 M6 脚本的本地结果仍不是发布迁移证据，其他共享、预发布或生产环境也不因这些证据自动迁移。

### 11.4 保留数据的本地 SQLite M6 升级

现有本地 `db.sqlite3` 保留 13 个功能测试商品及用户、订单、库存、钱包、预约等其他数据，因此不能通过删除数据库和重新 Seed 处理 M6。仓库提供 SQLite 专用版本化脚本：

```bash
# 默认只读预览，输出目标库、商品/Kit 数量和当前结构状态
python scripts/local/upgrade_sqlite_m6.py

# 确认预览后显式执行；写入前自动备份到 backups/local-sqlite-migrations/
python scripts/local/upgrade_sqlite_m6.py --apply
```

脚本只接受包含 `product_kits`、`order_items`、`inventory_transactions` 的受支持本地基线。它在写入前通过 SQLite Backup API 建立一致性备份，在一个 `BEGIN IMMEDIATE` 事务中将旧 `product_kits` 重建为允许 nullable stock 的 M6 结构、保留全部 fixed Kit ID/余额并补 `kit_kind=fixed`，创建两张颜色表，初始化 1..221 占位槽，扩展订单快照与库存流水列。提交前核对所有原业务表行数、M6 字段、221 槽、零商品颜色映射及 `PRAGMA foreign_key_check`；未知结构或含业务数据的部分 M6 状态会拒绝执行。

该脚本不写 `aerich`，不能应用到 MySQL，也不证明 M6 已通过或应用任何发布环境。执行前应停止本地后端及其他 SQLite 写入者；执行后先保留备份，运行商品列表/详情、既有订单与库存 smoke，再决定是否长期保留备份。

2026-09-07 经用户授权对本地持久 `db.sqlite3` 执行 `--apply`：写前备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-m6-20260907-015954.bak`；升级后 SQLite `integrity_check` 与 `foreign_key_check` 通过，保留 13 个商品和 6 个 fixed Kit，建立 221 个占位槽且商品颜色映射为 0，Repository ORM 成功读取 13 个商品。再次 preview 返回 `already_current=true`。未执行 Aerich、未连接 MySQL，也未修改 Gate A、共享、预发布或生产环境。

### 11.5 MARD 221 本地目录数据导入

M6 创建颜色目录，M8 再把清单 HEX 变成正式字段；当前导入器只接受已经具备 `swatch_hex` 列的 M8 本地 SQLite。抓取工具仅允许 `https://peiseka.com/pindouseka.html`，严格验证 A1–M15 的固定序列、221 项数量、CSS/展示 RGB 与 HEX 一致、色号/HEX 唯一，再冻结来源 SHA-256：

```bash
python scripts/local/fetch_mard_bead_colors.py
python scripts/local/import_mard_bead_colors.py
python scripts/local/import_mard_bead_colors.py --apply --confirm-local-only
```

来源页没有逐色图片；导入器仍可复用既有确定性 256×256 sRGB PNG 作为迁移兼容回退，同时把 `swatch_hex` 与 code/name/URL/sort/active 一并按清单核验。预览不创建文件、备份或数据库写入；apply 写库前使用 SQLite Backup API，图片原子发布，BeadColor 元数据放在 `BEGIN IMMEDIATE` 中更新并在提交前执行精确清单与外键核验。事务失败删除本轮新图片；现有非空冲突、Online 商品已启用颜色或非 221 槽直接拒绝；相同重放不再备份或写入。纯数字色块不再生成新图片格式，现有 PNG 不在 M8 转 WebP 或删除。

2026-09-07 本地执行结果：221 槽全部写入 code/name/URL/sort 并激活，生成 221 张 PNG，内容总计 128,325 bytes；备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-mard-221-20260907-024129-065769.bak`。再次 preview 为 `database_changes=0 / images_reused=221 / already_current=true`，`PRAGMA foreign_key_check` 无结果。该操作本身不创建商品颜色映射、不启用销售、不调整库存、不写 Aerich，也未连接或修改任何 MySQL/发布环境；本地此前已有的草稿 Product `14` 保留其 221 条关联，当前全部禁用且库存为 0。

### 11.6 Gate A MARD 221 持久发布候选

候选镜像包含 `app.tasks.gatea_mard_publish`，只允许 production MySQL、固定
`/data/images` 和无凭据 HTTPS `/uploads/products` URL。默认 preview 会只读核验
221 个已经完成 M8 HEX 回填的槽、版本化 manifest SHA-256、全部目标图片内容、现有元数据
冲突与 Online 已启用颜色；apply 必须复用 preview 的精确 manifest SHA-256：

```bash
python -m app.tasks.gatea_mard_publish
python -m app.tasks.gatea_mard_publish \
  --apply \
  --confirm-manifest-sha256 <preview-manifest-sha256>
```

新 PNG 通过同目录 hard-link 原子发布并固定为公开只读 `0644`；数据库在一个事务中
锁定 221 槽、复查销售引用、批量更新并回读核验。数据库失败删除本轮新图片，已有
文件不删除。已有 Online 自选色商品时只允许严格 no-op：preview 必须同时为
`database_changes=0`、`images_to_create=0`、`images_reused=221`；apply 仍在事务内锁定
并重新读取完整目录、重新检查 221 图片与 Online 引用，任何漂移都会在写入前失败，
精确一致时不更新数据库或图片。任务不创建 ProductKitColor、不启用商品颜色、不写库存，
也不自行证明 App/Nginx 已停写或 Backup/Restore 已通过，因此只能由受控 Gate A 非空
升级入口在 M8 后调用，不能独立执行到持久环境。

该路径已在一次性 MySQL 8.0.46 完成 221 行真实事务更新、221 文件发布及 no-op 重放，
未修改 Gate A；Gate B 公开环境仍须使用经批准的对象存储/CDN，而不是沿用单主机卷。

持久 Gate A 随后已经在 M6 阶段发布 221 色元数据和 221 张 PNG，并存在 Online 自选色
商品/启用色。M7→M8 候选使用上述精确 no-op 分支，要求 M8 按 slot 回填 HEX 后 221 个
目录项与 manifest 一致、既有 PNG 全部复用且数据库/图片零写入；不能从编排中拆出直接
运行，也不能为通过 preview 临时修改商品状态。该分支已由 head `62b1b15...`、真实
CI checkout/merge-ref `a9ff3d2...` 的 Run 34288613644 在专用一次性 Linux/MySQL 完整
updater 中复现；进入持久执行评审仍须取得目标环境当次只读盘点、Backup/Restore 和写授权。

---

## 12. Reservation Settings M7 发布流程与证据

`7_20260907190000_add_reservation_settings.py` 创建全店唯一的 `reservation_settings`，以 `singleton_key=1` 的 CHECK + UNIQUE 保证单例，并插入 `weekly_closed_weekday='monday'` 默认行。M7 不改写历史 Reservation；应用上线后，ADMIN+ 的固定店休更换用例才在业务事务中更新设置，并取消新店休星期上尚未开始的 pending/confirmed 预约。MySQL DDL 隐式提交，该迁移的 `RUN_IN_TRANSACTION=False` 是真实能力声明。

### 12.1 一次性 MySQL 8.0.46 候选门槛（2026-09-07）

- 候选代码对应本地提交 `58d8435`；在专用、可销毁 MySQL 8.0.46 中真实完成空库 Aerich 0→7，未使用 `--fake`、`init-db` 或运行时自动建表。
- M0–M6 各历史起点均重放到 M7；M6 的历史 fixed Kit 与 M7 的历史 Reservation/单日店休样本保留，第二次 `upgrade` 是 no-op。
- M6/M7 snapshot 核验迁移版本、221 色槽、颜色列/FK/索引、`reservation_settings` 单例、默认周一及 CHECK/UNIQUE。随后 Inventory + Reservation 联合 MySQL 门槛为 `21 passed`。
- 专用 Schema、容器及非默认端口已销毁/释放。该提交随后随 head `4d6430c...` 由 Run 34129910349 远端 8/8；持久 Gate A 又于 2026-09-08 完成 M2→M7。以上都是 M7 历史检查点，不代表 M8 已应用。

### 12.2 历史 Gate A M7→M8→M9 停止条件

本节记录旧候选 A 进入 M9 之前的历史路径，不是当前 live A/M9 的可执行说明。当前唯一
允许的 A→B 恢复路径见 §14；不得依据本节回退数据库或重跑 M7→M8→M9。

持久 Gate A 已于 2026-09-08 从只读确认的 M2 受控升级到 M7，并完成 Wallet
backfill/reconcile、221 色/持久 PNG、综合数据及数据后 Backup/Restore；权威事实见
`docs/09_release/reports/gatea_m7_upgrade_and_data_2026-09-08.md`。后续不能继续把
2026-09-02 的 M2 当作当前起点。

`gatea_operations.py initial-migrate` 仍只支持空库。仓库候选已为
`scripts.release.gatea_upgrade` 增加显式 `--source-version 7`：它复用目标 SHA/Image、
新 Backup/独立 Restore、停写快照、逐步 evidence、部分 DDL 失败处置和成功 Record 绑定，
但只应用 M8 与 M9，不重复 M3–M7、Wallet backfill 或代表数据；旧调用仍默认 M2，M7 未显式
选择时在读取 Backup、停写和写入前 fail closed。入口以版本化
`m7-preserved-business-v1` 保护 20 个非 `bead_colors` 业务表的确定性内容 dump 与
`bead_colors` 的 M7 字段投影，共 21 个业务表；M8 的 `swatch_hex` 被有意排除，使该摘要
在合法 M7→M8 前后保持不变。Aerich 精确链、完整图片 manifest 和原有聚合摘要仍分别
核验，其中聚合只作诊断，不能替代内容摘要。M7/M8/M9 Backup 和独立 Restore 必须携带并
重算同一 profile；旧 M7 Backup 缺失时拒绝升级。精确 M9 数据后 Backup 另外必须带
`m9-table-business-v1`，按稳定主键顺序覆盖桌台、Session、Timer 和 Occupancy
四表；独立 Restore 必须重算完全相同的摘要，Record 不记录原始 Token/行内容。

在 App/Nginx 停止、live DB/图片与该 Backup 精确匹配后，入口先执行只使用 M7 字段的
raw source preflight：`information_schema` 必须确认不存在 `swatch_hex`，221 条
slot/code/name/URL/sort/active 必须逐项匹配冻结 manifest，221 张预期 PNG 必须为普通
非软链接文件、内容 SHA-256 匹配且权限 `0644`；额外 Product 图片允许存在，但完整图片
manifest 不得相对 Backup 漂移。以上任一失败都发生在 M8 原语前。之后三次 MARD
preview/apply/replay 均须为精确 no-op，再应用 M9 四表迁移并执行精确 30 桌
bootstrap/replay，最终比较同一 21 表内容摘要并运行桌台只读 reconcile/sweep。

成功 Record 生成后 App/Nginx 继续停止；执行人必须以同一显式 source version、source
SHA 和 Backup ID 紧邻重放 upgrade plan。该 replay 会验证 evidence 路径/哈希、当前
完整数据库摘要、图片 manifest、M7 内容摘要、M9 四表/30 桌与桌台一致性，并重新运行只读 MARD preview；只有
`already_current=true` 才能调用 `app-up`。`app-up` 本身只验证 Record、target SHA/Image
和合法迁移组合，不重读 live DB/图片/MARD，不能替代该 replay。本轮本地完整
`tests/release` 为 `229 passed`；新入口的历史加固点已收口为 head `fa6fce05...`、
merge-ref `b2f02ebc...`，并由 Run 34281512196 在干净 PR checkout 完成远端 8/8。
完整 updater 的受测实现 head `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、真实 CI checkout/merge-ref
`a9ff3d246c61a4aeede062596c32817a69834d7a` 又由 Run 34288613644 最终 attempt 2 完成
现行 9/9 required Job；其中 `gatea-m7-m8-updater` 首 attempt 用时 4m02s，14/14 阶段
通过。该结果仍不授予 Gate A 写入。

独立只读代码审查曾发现成功重放没有重新证明 App/Nginx 仍停服；修复并补齐服务状态
fail-closed 矩阵后，复核无未解决 P0–P3。该结论现已绑定上述干净候选与远端 Run。
历史一次性 MySQL M7→M8 updater 已复现；当前 M7→M8→M9 候选仍必须以自身干净 SHA
完成全部 required Jobs。持久执行前仍必须取得当前 M7 只读事实、
当次 Backup/Restore、明确停写/写入授权与目标镜像；
执行后核验 M0–M9、221 个精确 HEX、既有色卡/商品库存/21 表内容摘要零漂移、30 桌/
唯一 Token/零初始会话、table reconcile/sweep 与 gzip Runtime，并建立新的 M9 数据后
Backup/Restore/加密异机副本。不得手工补表/列、删除失败
evidence、直接调用内部原语、临时改商品状态、盲目重跑或使用 `--fake`。真实 Origin/RC、
iOS/Android 真机与微信外部条件也均未完成，当前发布判定仍为 No-Go。

`m7-preserved-business-v1` 的 20 表 dump 与 `bead_colors` 投影是先后两次数据库读取，
数据库事务与图片文件操作也不能组成跨系统原子提交。此保护明确依赖整个 Backup、迁移、
replay 到 `app-up` 的维护窗口内 App/Nginx 停止，且没有直接 SQL、另一个迁移进程或宿主
图片旁路写入；无法排除这些写入时必须保持 No-Go。

---

## 13. BeadColor HEX M8 发布流程

`8_20260908140000_add_bead_color_swatch_hex.py` 为 `bead_colors` 新增 nullable
`VARCHAR(7) swatch_hex`，并在同一迁移中按 `slot_no=1..221` 回填冻结 MARD 清单中的
规范大写 `#RRGGBB`。221 个值内嵌在迁移内，并由常量绑定清单 SHA-256；迁移执行结果不
依赖工作目录或未来应用包中的清单内容。M8 不修改 code/name/active、库存、订单快照、
`swatch_image_url` 或现有 PNG，也不把纯数字色块转换为 WebP。

### 13.1 本地 SQLite 保留数据升级

本地持久 SQLite 必须使用专用工具，不能执行 MySQL/Aerich M8：

```bash
# 默认只读：核验 221 槽、列状态和与冻结清单冲突
python scripts/local/upgrade_sqlite_m8_swatch_hex.py

# 仅在停止本地写入并复核 preview 后显式执行
python scripts/local/upgrade_sqlite_m8_swatch_hex.py --apply
```

apply 在首次写入前用 SQLite Backup API 创建 `0600` 备份；`ALTER + 221 项回填 +
精确核验` 位于同一个 `BEGIN IMMEDIATE` 事务。提交前后比较所有业务表行数、除 HEX 外
的全部 BeadColor 字段、221 个唯一 HEX，并运行 `integrity_check` 与
`foreign_key_check`。脚本接受精确 pre-M8、安全的部分 M8 和完整 post-M8 重放，拒绝
未知表形状、非 1..221 槽或冲突 HEX。它不写 Aerich，不能应用到 MySQL，也不构成发布
证据。当前持久 `db.sqlite3` 已于 2026-09-08 在停止本地写入后执行 M8；写前备份
`backups/local-sqlite-migrations/db.sqlite3.pre-m8-swatch-hex-20260908-130013-906106.bak`
权限为 `0600`，完整性/外键通过且确认没有 HEX 列。升级后 221 槽全部有唯一规范 HEX、
与冻结清单逐槽相等，完整性/外键、幂等 preview、本地 Demo verifier 和钱包 reconcile
均通过。该记录只证明当前本地 SQLite，不替代 Aerich、Gate A 或持久 MySQL 发布证据。

### 13.2 MySQL 非事务性、CHECK 与失败处置

M8 明确设置 `RUN_IN_TRANSACTION=False`。MySQL DDL 隐式提交，因此 `ADD COLUMN` 成功而
后续回填或 Aerich 记录失败时，可能留下“物理列存在、Aerich 仍为 M7”的部分状态。
Gate A 必须保存脱敏失败 evidence 并保持 App/Nginx 停止；禁止直接重跑、`--fake`、自动
downgrade 或猜测性补列。先只读核对 Aerich 链、列形状和 221 项 HEX，再在已验证备份
恢复与经 Review 的精确前滚修复之间作独立裁决。

本期不在 M8 添加仅 MySQL 可严格表达的大小写正则 `CHECK`。非空格式由 Pydantic
规范化、Tortoise Regex、Service 销售就绪规则以及 local/Gate A 发布工具逐槽精确核验；
SQLite 没有内建等价 REGEXP。若未来要把约束下沉数据库，必须先扫描所有环境，再用独立
跨方言迁移同时更新 Model、数据库设计、DBML 与契约测试，不能夹带修改已经 Review 的
M8。

### 13.3 一次性 MySQL 8.0.46 证据（2026-09-08）

- 在专用、可销毁实例真实执行 Aerich 0→8，九条版本记录完整；未使用 `--fake`、
  `init-db` 或运行时 `generate_schemas()`。
- M8 列为 nullable `VARCHAR(7)`；数据库 1..221 槽逐项等于冻结清单，且有 221 个唯一
  HEX。随后 Gate A MARD publish/replay 的真实事务与兼容 PNG 路径通过，共 `2 passed`。
- 容器 `pinkdoohub-m8-codex-20260908` 已删除，临时端口 `13308` 已确认释放；该一次性
  MySQL 验证没有连接或修改持久、共享、Gate A、预发布或生产 MySQL。本地 `db.sqlite3`
  后续已通过 §13.1 的专用 SQLite 工具独立升级，不属于这次 MySQL/Aerich 证据。
- 2026-09-08 M8 基线 head `4e745848315aab56805a872ecf5b9f5e3c10135b`、merge-ref `3ddda81...` 已由
  Run 34242753255 在干净 checkout 完成 8/8；MySQL Job 的 M6→M7→M8、联合门槛和
  cleanup 均 success。首轮 Run 34242022911 因 Reservation 测试迁移清单漏列 M8 而
  7/8，修复后完整重跑；详见
  `docs/09_release/reports/m8_remote_ci_2026-09-08.md`。其后新增的 M7→M8/Online exact
  no-op 发布保护现已由 head `fa6fce05...` / Run 34281512196 在干净远端完成 8/8，详见
  `docs/09_release/reports/m8_hardening_remote_ci_2026-09-09.md`。这是不可变的历史 8/8
  加固证据；当前完整 updater 证据见下文，二者都不表示 Gate A M8 已应用。

当前候选把完整 updater 固化为独立 `gatea-m7-m8-updater` CI Job。它只允许
GitHub-hosted disposable Ubuntu，使用冻结 M7 Runtime 和当前 checkout M8 镜像，真实
建立 M7 业务/221 PNG，执行 source Backup 与同 ID 独立 Restore，再运行 M8
plan/apply/停服 plan-replay、target app-up、221 HEX/gzip/PNG Runtime 核验，并追加
M8 数据后 Backup/Restore。任何资源预存、身份/链漂移、Restore/升级/Runtime/Secret
扫描或精确 cleanup 失败都阻断；workflow 不读取生产 Secret，且上传白名单不含 dump、
图片 tar、配置、密码或 Token。该 Job 即使通过也只关闭一次性 Linux 的编排风险，不能
自动应用持久 Gate A，也不替代目标主机当次 Backup/Restore、Image ID 与写授权。

2026-09-09，head `62b1b15f2f4bf4e80bf8433a25878d158a49ca9b`、真实 CI
checkout/merge-ref `a9ff3d246c61a4aeede062596c32817a69834d7a` 已由
Run 34288613644 最终 attempt 2 完成现行 9/9 required Job。updater 在 GitHub-hosted
disposable Ubuntu/Linux root 和本地 Unix Docker daemon 上执行 14/14 阶段：source SHA
为 `73dca350505d43775fb1ff1158ccf6aabc221998`，M7 source Backup/同 ID Restore
`20260908t230214z`、M8 target Backup/同 ID Restore `20260908t230329z` 均 PASS；221 个
HEX、gzip `63445→10948` bytes（减少 `52497`）及 PNG 回退通过。20 个 allowlist artifact
文件通过 Secret 扫描；第一次 `compose-down` 瞬态失败，第二次清理成功且最终零残留。
Run 首 attempt 的 `openapi-contract` 只在 pip truststore 安装阶段瞬态失败，相同提交重跑
通过，不能解释为 Schema 漂移。该环境未使用生产 Secret 或持久授权，也未触碰 Gate A、
共享、预发布或生产数据库；在该 2026-09-09 历史检查点，持久 Gate A 仍为 M7。后续
A/M9 现场失败检查点与 B 前滚约束以 §14 为准。

---

## 14. Table Session M9 发布流程

`9_20260910180000_add_table_sessions.py` 在 M8 之后建立 `store_tables`、
`table_sessions`、`table_session_timers` 与 `table_occupancies`。迁移只负责结构，不在 DDL
中生成环境专属 Token；`app.tasks.table_bootstrap --apply` 仅在桌台表为空时原子建立
`T01`–`T30`，再次执行必须逐项验证桌号、展示名、32 位大小写敏感字母数字 Token 与唯一性，
任何部分数据或漂移都 fail closed。M9 同样设置 `RUN_IN_TRANSACTION=False`，MySQL DDL
隐式提交后的失败必须保留现场并走经 Review 的前滚或已验证备份恢复，禁止 `--fake`、
手工补表或猜测性重跑。

当前 live Gate A 已由旧候选 A
`d6c09482ee0f5583d79bd847e995746c9c6ee1a3` 带到 M9；`current` 仍指向 finalized lineage S
`73dca350505d43775fb1ff1158ccf6aabc221998`。A acceptance 在创建订单后因桌台 Secret
读取绕过 Entrypoint 加载而安全失败，补偿已收口，但 canonical schema v3 failure pending
必须作为不可手工修改的恢复输入保留。当前禁止显式 `--source-version 7`、数据库降级、
重跑 M7→M9、手工删除 pending 或临时注入 Secret。

新候选 B 只有在自身同一 SHA 的全新 9/9 required Jobs 后，才可执行唯一受控链：stage
绑定 predecessor A、lineage S 和 pending digest；`retire-failed-acceptance` 以六阶段 durable
journal 停写并用 B 镜像只读证明补偿现场，原始 pending 以 `0600` no-clobber archive 保存，
发布脱敏 Record 后才按冻结 inode 删除 canonical，并无条件恢复及复验 A/M9 五服务。随后
创建新的 A/M9 Backup/独立 Restore；它们必须同时绑定 `m7-preserved-business-v1`、
`m8-swatch-content-v1` 和 `m9-table-business-v1`。再执行 A→B config activation，并以
schema v2、显式 `--source-version 9` 完成 M9→M9 adoption/replay；该路径只能快照和只读
reconcile，Record/evidence 必须固定 `database_changes_applied=false`、
`migrations_applied=[]`，不得调用 migration、bootstrap、MARD、Wallet 或 sweep 写入。

B `app-up` 后重新完成 admin-assisted acceptance、显式绑定 acceptance Record 的
resilience，以及 B 验收后的 M9 Backup/Restore；最后才以 source=S、predecessor=A、
target=B finalize。retirement archive 是 activate、rollback 和 finalize 的持续 lineage 依赖，
必须原位保持并逐次重验路径、权限、单链接、稳定内容与 digest。任一步失败即停止并维持
No-Go；只有完整成功链才能把 `current` 从 S 切到 B。

兼容 Job ID `gatea-m7-m8-updater` 在一次性环境中仍验证从 M7 全量升级到 M9，避免分支保护
required check 静默失联；它不能替代上述持久 M9→M9 前滚证据。新 M9 Backup/Restore
必须同时带有既有 21 表 M7 保留摘要、M8 色块摘要与 `m9-table-business-v1` 四表内容摘要；
通用 Core 行数聚合、30 桌 API 列表或单独 Token 唯一数都不能替代内容级恢复证据。

普通占位二维码不是迁移或数据库备份的一部分。内部验收如需生成，必须向全新的受控目录
运行 `app.tasks.table_bootstrap --output-dir <new-path>`；目录权限为 `0700`、PNG/清单为
`0600`，清单只保存 Token/Payload 摘要，目标微信环境固定 `develop`。当前也允许先跳过
物料生成；正式微信小程序码必须在备案和平台参数复核后单独立项替换，不能把普通占位码
标记为正式物料。

---

## 15. 本地 SQLite Refund 结构精确修复

development 启动时的 `generate_schemas()` 曾为本地 `db.sqlite3` 补建 M4 表，但不会 ALTER 既有表。2026-09-07 的只读结构对比证明 22 张表中唯一会阻断当前 ORM 投影的差异是 `refunds.inventory_restored` 缺失，同表还缺数据库设计已要求的一单一退款 `UNIQUE(order_id)`。

提交 `35e8630` 新增专用工具：

```bash
# 默认只读预览
python scripts/local/repair_sqlite_refunds_schema.py

# 确认目标为本项目本地 SQLite 后显式应用
python scripts/local/repair_sqlite_refunds_schema.py --apply --confirm-local-only
```

脚本只接受仓库内普通非 symlink SQLite 文件和精确的 legacy/current `refunds` 形状；存在 Refund 行的不完整基线会 fail closed。首次写入前通过 SQLite Backup API 建立 `0600` 一致性备份，然后在一个 `BEGIN IMMEDIATE` 事务内增加 `inventory_restored INT NOT NULL DEFAULT 0` 和命名唯一索引 `uidx_refund_order_id`；提交前后复核全表行数、完整性、外键和目标结构，已是目标状态时零写入且不重复备份。

已按当前任务授权应用到本地持久 `db.sqlite3`；写前备份为 `backups/local-sqlite-migrations/db.sqlite3.pre-refunds-repair-20260907-105304-874045.bak`，权限 `0600`，应用后完整性与外键核验通过。该脚本不写 Aerich、不能用于 MySQL，也不是发布迁移证据。`database_design.md` 与 DBML 已是目标形状，无需因本地修复改数据库/API 契约。

---

## 16. 本地综合 Demo Seed 边界

`python -m app.tasks.local_demo_seed --apply --confirm-local-only --operator-username <ADMIN>` 是本地 development SQLite 的可恢复演示数据工具，不是迁移或发布数据入口。它在写入前创建 SQLite Backup API 快照，并把合成用户的随机凭据只写入被 Git 忽略的 `0600` 本地文件；不伪造真实微信充值、支付、退款或外部身份。

2026-09-07 已实际应用，写前备份为 `backups/local-demo-data/db.sqlite3.pre-local-demo-20260907-105320-455438.bak`，凭据文件为 `backups/local-demo-data/synthetic-credentials.json`，两者权限均为 `0600`，不得输出或提交凭据值。`python -m app.tasks.local_demo_seed --verify` 通过，`wallet_reconcile` 为 `scanned=11 mismatches=0 violations=0`。最终本地表摘要：users 13、products 19、product images 24、orders 8/items 10、payments 6/settlements 6/refunds 2、inventory transactions 238、reservations 7、wallet accounts 11/transactions 9、audit logs 583、external identities 0。详细场景分布见 changelog 和根 README。

2026-09-08 修复了活跃预约样本随三小时提前量自然失效的问题：旧 pending/confirmed
合成预约作为历史保留，apply 只在当前 30 日窗口缺少对应样本时通过正式 Service 新建，
并优先选择窗口后段的不同营业日。首次错误操作者预检零业务写入，保留的 `0600` 备份为
`backups/local-demo-data/db.sqlite3.pre-local-demo-20260908-024201-529629.bak`；使用原 Seed
操作者成功刷新前的 `0600` 备份为
`backups/local-demo-data/db.sqlite3.pre-local-demo-20260908-024217-469378.bak`。本次只新增
1 条 pending 及 1 条创建审计，当前全表为 reservations 8、audit logs 584；其他上述关键
表计数不变。专用 verifier、SQLite 完整性/外键与钱包对账均通过。该滚动刷新仍只是本地
演示数据操作，不写 Aerich，不是 MySQL 或发布迁移证据。
