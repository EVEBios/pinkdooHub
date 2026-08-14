# Database Migration Workflow

> **适用范围：** pinkdooHub 所有持久化 Model、字段、约束和索引变更
>
> **迁移工具：** Aerich 0.9.3
>
> **生产权威方言：** MySQL；SQLite 仅用于本地快速开发和自动化测试
> **Last Updated:** 2026-08-14

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
