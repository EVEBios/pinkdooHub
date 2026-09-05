# Database Migration Workflow

> **适用范围：** pinkdooHub 所有持久化 Model、字段、约束和索引变更
>
> **迁移工具：** Aerich 0.9.3
>
> **生产权威方言：** MySQL；SQLite 仅用于本地快速开发和自动化测试
> **Last Updated:** 2026-09-06

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

`2_20260814104655_add_inventory_transactions.py` 是 MySQL 8+ 离线生成并人工 Review 的 Inventory 增量迁移。它先创建 `inventory_transactions`，再为每条正库存 ProductKit 写一条 `opening_balance`；零库存不生成零变化流水。该文件已在一次性 MySQL 8.0.46 实例完成演练，但尚未应用到任何持久、共享或生产数据库。

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

- `.github/workflows/ci.yml` 的 `backend-mysql-release` 固定 `mysql:8.0.46`、`127.0.0.1:13306` 和 `pinkdoohub_inventory_4311_ci`。Phase 9.5 起真实执行 Aerich 0→1→2→3 后运行现有 9 项 MySQL release gate；禁止 `--fake`、`init-db`、运行时自动建表和默认 3306。Gate A 已部署候选仍停留在 0→2，未获得发布授权前不得套用该 CI 迁移结论更新持久环境。
- `scripts/ci/check_mysql_gate.py` 在连接前要求 `APP_ENV=testing`，并证明 Aerich `DB_*` 与 pytest `INVENTORY_MYSQL_TEST_*` 完全指向同一个 disposable target；snapshot 只记录安全目标、MySQL 版本、三条 Aerich 版本、Git SHA 和 run ID，不写密码或连接串。
- 本地使用唯一命名 Docker 容器按同配置真实演练：MySQL 8.0.46、三条迁移和 9 项并发/1205/EXPLAIN/HTTP 门槛全部通过。cleanup 删除专用 Schema、停止容器并确认非运行和 13306 关闭；随后删除容器对象与临时证据目录，未连接 3306 或任何持久/共享数据库。固定 Docker image 只作为共享缓存保留。
- 9.2.6 已由 Draft PR #2 的 GitHub Actions Run 33355935212 在真实 MySQL 8.0.46 service 上重跑并通过，保存了 preflight、迁移日志、版本快照、JUnit 与 cleanup JSON，Phase 9.2 的 MySQL CI 风险据此关闭。该证据仍不替代 9.3 的生产相似备份恢复和失败处置演练。

---

## 9. Wallet / Payment / Refund M4 发布流程

`4_20260905162243_add_wallet_payment_refund.py` 是 MySQL 8+ 离线生成并人工 Review 的资金增量迁移。它创建 `wallet_accounts`、`recharge_orders`、`payments`、`payment_settlements`、`refunds`、`wallet_transactions`，并把 InventoryTransaction 的数据库注释补充为包含 `order_refund_restore`。`RUN_IN_TRANSACTION=False` 明确承认 MySQL DDL 隐式提交。

截至 2026-09-05，M4 已在一次性 MySQL 8.0.46 容器完成 Aerich 0→4，钱包专项 `2 passed`，覆盖关键资金/库存闭环及四个资金幂等列的 `ascii_bin`/大小写 key 独立提交，但没有通过 Aerich 应用到本地持久 `db.sqlite3`、Gate A、共享、预发布或生产数据库。development 的 `generate_schemas` 会在应用启动或热重载时为 SQLite 自动补建缺失表，却不会写入 Aerich 版本记录；因此“表已存在”不等于 M4 已迁移，也不能作为可追溯的发布证据。既有 Phase 4.3.11、Phase 9.2/9.3 的 0→2 或 0→3 证据不能替代 M4 验证；当前 M4 证据也不替代钱包专项并发、1205/1213 与 EXPLAIN 扩展门槛。

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
- 证据边界：本次证明 M4 可在真实 MySQL 8.0.46 执行、关键单链路原子闭环成立且四个资金幂等列的 `ascii_bin` 行为正确；尚未覆盖钱包专项并发竞争、真实 1205/1213 重试和资金查询 EXPLAIN，生产启用前仍须完成 §9.5 对应扩展门槛。

### 9.9 M4 资金幂等键排序规则复验（2026-09-05）

- 原因：M4 原先只为资金表指定 `utf8mb4` 字符集，四个 `idempotency_key` 会继承 MySQL 默认的不区分大小写排序规则，使仅大小写不同的两个合法 ASCII key 可能被 UNIQUE 或重放查询错误地视为同一业务身份。
- 实现：`RechargeOrder`、`Payment`、`Refund` 与 `WalletTransaction` 统一使用 `AsciiBinaryCharField`；该字段在 MySQL 生成 `VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin`，并在 Aerich M4 快照记录相同方言类型。Tortoise ORM 1.1.7 不支持字段级 `collation` / `db_collation` 参数，未知参数会被静默忽略，因此不得用普通 `CharField` 伪装该约束。
- 验证：在新建的一次性 `mysql:8.0.46` 容器、回环 `127.0.0.1:13317` 与专用 `pinkdoohub_wallet_idempotency_m4` Schema 真实执行 Aerich 0→4；MySQL 专项 `2 passed`，通过 `information_schema.COLUMNS` 确认四列均为 `ascii_bin`，并证明 `Case-Sensitive-Key` 与 `case-sensitive-key` 的两次相同 ADMIN 调账分别提交、均非重放且余额累计两次。
- 清理：精确停止 `pinkdoohub-wallet-idempotency-m4` 后由 `--rm` 删除；`docker ps -a` 未发现该名称，`127.0.0.1:13317` 无监听。未连接或修改默认 3306、本地持久 SQLite、Gate A、共享、预发布或生产数据库。
