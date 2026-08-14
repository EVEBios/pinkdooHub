# pinkdooHub 数据库设计 v1.6

> **Last Updated:** 2026-08-14

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| 满足当前需求 | 覆盖 v0.1 所有业务场景 |
| 保持扩展性 | 预留字段和表结构便于后续版本 |
| 避免过度设计 | 不做当前用不到的抽象 |
| 满足第三范式（3NF） | 消除冗余，保证数据一致性 |
| 支持 AI 扩展 | 为 AI 推荐和生成功能预留空间 |
| 主键统一 | 所有主键使用 `BIGINT` |

---

## 2. 数据库总体结构

```
users
  ├── orders ── order_items
  ├── operated inventory_transactions
  └── products
        ├── experience_options
        ├── product_kits
        ├── product_images
        └── inventory_transactions

audit_logs
```

### 2.1 数据完整性约束边界

Product、Order 与当前冻结的 Inventory 规则由三层共同保证，文档中的“必须”不等于所有规则都由物理数据库独立完成：

| 层级 | 当前保证 |
|------|----------|
| 数据库 | `NOT NULL`、字段类型、默认值、外键删除策略、Kit 一对一唯一性、Option 全历史联合唯一性、Order 编号唯一性、Inventory 幂等键唯一性和命名索引 |
| Schema / Model | 文本长度、正整数、金额范围与小数位、库存 `0..999999`、流水单字段数量边界、非零变化量、Enum 合法性、Order Item 数量/项数/重复组合边界 |
| Service / Validator | Product 类型与扩展表匹配、图片与 Option 同属一个 Product、单封面与 Option 禁止封面、状态流转和上架完整性；Order 聚合可售性、快照金额与状态机；Inventory before/change/after 等式、类型/来源组合、锁后余额判断和余额/流水同事务 |

当前 Product、Order 与 Inventory Model 没有声明数据库 `CHECK` 约束，因此绕过应用直接执行 SQL 可能绕过正数、金额范围、流水算术等值域规则。生产数据写入必须经过应用或受 Review 的迁移/运维脚本；是否把这些值域进一步下沉为跨 MySQL/SQLite 的命名 `CHECK`，必须作为独立设计变更统一评估，不能只改某一数据库。

---

## 3. 表详细说明

### 3.1 users（用户表）

存储平台用户信息，支撑登录认证、JWT 身份识别和订单关联。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| username | VARCHAR(32) | NOT NULL, UNIQUE | 登录账号 |
| password | VARCHAR(128) | NOT NULL | 加密密码 |
| nickname | VARCHAR(32) | NOT NULL | 用户昵称 |
| phone | VARCHAR(11) | NOT NULL, UNIQUE | 手机号码；Service 预检查，数据库兜底并发唯一性 |
| avatar | VARCHAR(256) | nullable | 头像 URL |
| role | SMALLINT | NOT NULL | 1:普通用户 2:管理员 3:超级管理员；ORM 默认 1 |
| status | SMALLINT | NOT NULL | 1:正常 2:禁用；ORM 默认 1 |
| last_login_at | DATETIME | - | 最后登录时间 |
| created_at | DATETIME | - | 注册时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.2 products（商品表）

所有商品的公共信息，采用统一商品表设计。价格由各子表管理（体验 → `experience_options.price`，套装 → `product_kits.price`），products 表仅存储公共字段。

DB 使用 VARCHAR 存储 `product_type` 和 `status`，代码层 **必须** 使用 Python 3.10 兼容的 `str, Enum`（`ProductType` / `ProductStatus`），禁止 Magic String。ORM 使用字符串枚举字段，数据库值仍为普通 VARCHAR。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| name | VARCHAR(100) | NOT NULL | 商品名称，允许重名 |
| product_type | VARCHAR(20) | NOT NULL | `"experience"` / `"kit"`，创建后不可修改 |
| description | TEXT | - | 商品描述 |
| status | VARCHAR(20) | NOT NULL, DEFAULT `"draft"` | `"draft"` / `"online"` / `"offline"` |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | 逻辑删除标记 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

> **价格分离原则：** 体验商品价格来自 `experience_options.price`，套装商品价格来自 `product_kits.price`。`products` 表不设 `price` 字段，避免语义混淆。

---

### 3.3 experience_options（体验配置表）

拼豆体验的可选配置，与 `products` **一对多**关联。每条 Option 代表一个独立可售配置（时长 + 人数 + 日期类型 → 价格）。

管理员可在 Product 为 `draft` / `offline` 时新增、修改或删除 Option；`online` Product 必须先下架。删除最后一个 Option 后 Product 保持原 `draft` / `offline` 状态，重新上架时由 Validator 拒绝空 Option 集合。Option 无独立状态字段，跟随 Product 的生命周期。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, NOT NULL | 关联商品 |
| duration | INT | NOT NULL | 分钟数，必须 > 0；60 / 120 / 540 只是当前常用值 |
| participants | INT | NOT NULL | 体验人数，必须 > 0；1 / 2 只是当前常用值 |
| day_type | VARCHAR(20) | NOT NULL | `"weekday"` 工作日 / `"holiday"` 节假日 |
| price | DECIMAL(10,2) | NOT NULL | 该配置的售价，0 < Price ≤ 99999 |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | 逻辑删除。保留图片关联和历史订单引用 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

**唯一约束：** `(product_id, duration, participants, day_type)` 在全历史范围内联合唯一，约束不包含 `is_deleted`。逻辑删除后再次创建相同组合时，Service 恢复原记录（保持 ID、更新价格、`is_deleted = false`），不插入第二条记录，也不物理删除可能已被订单或图片引用的 Option。

---

### 3.4 product_kits（套装商品表）

拼豆套装的专有信息，与 `products` 一对一关联。套装价格直接存储在此表。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, NOT NULL, UNIQUE | 关联商品 |
| price | DECIMAL(10,2) | NOT NULL | 套装售价，0 < Price ≤ 99999 |
| stock | INT | NOT NULL, DEFAULT 0 | 唯一权威当前库存，应用范围 `0..999999`；Phase 4.3 接入后每次变化必须同时写流水 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

> `sold_count` 不存储在 Product 模块。累计销量由订单模块统计。

### 3.5 product_images（商品图片表）

一个商品可有多张图片，采用一对多关系。通过 `experience_option_id` 区分 Product 公共图片和 Option 专属图片。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, NOT NULL | 关联商品 |
| experience_option_id | BIGINT | FK → experience_options.id, nullable | NULL = Product 公共图；非 NULL = Option 专属图 |
| image_url | VARCHAR(2048) | NOT NULL | 图片 URL |
| is_cover | BOOLEAN | NOT NULL, DEFAULT FALSE | 封面图，仅 `experience_option_id IS NULL` 时有效 |
| sort | INT | NOT NULL, DEFAULT 0 | 排序序号 |
| is_deleted | BOOLEAN | NOT NULL, DEFAULT FALSE | 逻辑删除。保留历史关联 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

**图片归属规则：**

| experience_option_id | 归属 | 用途 |
|----------------------|------|------|
| NULL | Product 公共图片 | 列表封面、详情页默认展示、商品整体介绍 |
| 非 NULL | Option 专属图片 | 用户选择具体 Option 后展示 |

**约束：**
- `is_cover = true` 仅在 `experience_option_id IS NULL` 时有效，每 Product 最多一张封面
- Option 图片的 `is_cover` 必须为 `false`，默认首图为 `sort ASC, id ASC` 第一张
- 逻辑删除 Option 时图片关联保持不动，随 Option 从正常查询隐藏；恢复 Option 时重新可见
- 仅异常物理删除 Option 时，FK 的 `ON DELETE SET NULL` 才将关联图片变为 Product 公共图片
- Option 无图片时返回 `"images": []`，前端展示占位图

---

### 3.6 orders（订单表，Phase 4.2 已实现 Model）

订单主表，记录下单用户、金额和状态。不直接保存商品信息，商品明细拆分到 `order_items`。Phase 4.3 已在既有聚合上开放纯 Experience、纯 Kit 与混合订单；Kit Item 使用已经预留的 nullable Option 字段，并在创建 Pending Order 时原子扣减库存。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| order_no | VARCHAR(28) | NOT NULL, UNIQUE | `OD` + 26 位大写 Crockford Base32 ULID；全局唯一 |
| user_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | 下单用户 |
| total_amount | DECIMAL(10,2) | NOT NULL | 订单总金额，单位：元 |
| status | SMALLINT | NOT NULL, DEFAULT 0 | 0:待支付 1:已支付 2:已取消 3:已完成；代码使用 `SmallIntField` + `OrderStatus(IntEnum)`，写入/筛选边界转换为原生整数 |
| remark | VARCHAR(500) | nullable | 用户备注；审计日志不得复制该字段 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

**订单编号规则：** 使用 UTC 毫秒时间与密码学安全随机源生成 ULID，无需 Redis、第三方依赖或额外日序列表。`UNIQUE(order_no)` 是并发唯一性的最终兜底；冲突时整笔创建事务回滚并重新生成，最多尝试 3 次。编号仅可近似按时间排序，列表仍以 `created_at DESC, id DESC` 为权威顺序。旧草案的“YYYYMMDD + 当日六位序号”不再属于 Phase 4.2 契约。

---

### 3.7 order_items（订单明细表，Phase 4.2 已实现 Model）

采用订单快照设计：保存下单时的商品名称、价格及体验配置快照，保证历史订单不受商品后续修改影响。体验商品记录具体 Option 信息，套装商品这些字段为 NULL。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| order_id | BIGINT | FK → orders.id, NOT NULL, ON DELETE RESTRICT | 关联订单 |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | 关联原商品 |
| experience_option_id | BIGINT | FK → experience_options.id, nullable, ON DELETE RESTRICT | Experience Item 关联具体配置；Kit Item 为 NULL |
| option_duration_minutes | INT | nullable | 快照：正整数分钟数 |
| option_participants | INT | nullable | 快照：人数 |
| option_day_type | VARCHAR(20) | nullable | 快照：日期类型 |
| product_name | VARCHAR(100) | NOT NULL | 下单时商品名称快照 |
| product_price | DECIMAL(10,2) | NOT NULL | 下单时商品价格快照 |
| quantity | INT | NOT NULL | 数量；Phase 4.2 Schema 范围 1 至 99 |
| subtotal | DECIMAL(10,2) | NOT NULL | 小计金额 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

每单 1 至 10 个 Item，且同一订单内 `(product_id, experience_option_id)` 由请求 Schema 保证不重复；因此同一 Kit Product 最多一行。当前不增加数据库唯一约束：数据库的 nullable 语义会使 Kit Item 的组合约束不直观，而一次订单创建只有单一受控写入口；Schema 与 Service 测试已经覆盖重复组合、Experience 必填 Option 和 Kit 必须无 Option 的规则。

**历史保护：** Order、OrderItem 不提供删除接口。用户、Product 与 Option 的物理删除均由 `RESTRICT` 阻止；Product 与 Option 的正常业务删除继续使用逻辑删除。历史展示始终读取 OrderItem 快照，不依赖当前 Product/Option 内容。

---

### 3.8 inventory_transactions（库存流水表，Phase 4.3.4 已生成离线迁移）

记录每一次已提交的库存变化。`product_kits.stock` 仍是当前余额，流水用于追溯，不能通过实时汇总流水替代余额读取。表继承 `BaseModel`，因此包含技术字段 `updated_at`；业务上不提供更新或删除路径，API 也不输出该字段。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 流水 ID |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | Kit 的对外 Product ID；余额写入仍锁定 `product_kits` 行 |
| transaction_type | VARCHAR(40) | NOT NULL | `opening_balance` / `admin_adjustment` / `order_deduction` / `order_cancellation_restore` |
| change_quantity | INT | NOT NULL | 真实非零变化量，应用范围 `-999999..999999` |
| before_quantity | INT | NOT NULL | 变化前余额，应用范围 `0..999999` |
| after_quantity | INT | NOT NULL | 变化后余额，应用范围 `0..999999`，且必须等于 `before_quantity + change_quantity` |
| source_type | VARCHAR(30) | NOT NULL | `migration` / `admin` / `order`；当前每种流水都有明确来源 |
| source_id | BIGINT | nullable | 当前仅 Order 来源保存 Order ID；为避免多态外键不建立 FK |
| operator_id | BIGINT | FK → users.id, nullable, ON DELETE RESTRICT | 触发事件的用户；期初迁移及未来无用户系统事件允许为空 |
| reason | VARCHAR(256) | NOT NULL | 管理调整保存规范化原因，迁移/订单事件保存服务端稳定原因 |
| idempotency_key | VARCHAR(256) | NOT NULL, UNIQUE | 服务端完整业务身份；客户端调整 key 本身仍限制为 128 个可打印 ASCII 字符 |
| created_at | DATETIME | - | 流水创建时间、权威分页时间 |
| updated_at | DATETIME | - | BaseModel 技术字段；不可作为业务变更时间 |

**不可变边界：** 数据库负责非空、外键、幂等唯一性和字段容量；Model 负责单字段范围与非零变化量；Service 根据类型/source 契约计算并验证 before/change/after，在持有 ProductKit 行锁的同一事务内更新余额和插入流水。当前不增加跨 MySQL/SQLite 的 `CHECK`，直接 SQL 仍属于受 Review 的受控路径。

**来源设计：** `source_id` 故意不关联 Order 外键，避免把通用来源列伪装为只属于订单。查询层只允许 `source_id` 与 `source_type=order` 组合，并在 Repository/Mapper 阶段按需加载安全订单号。

**增量迁移：** `2_20260814104655_add_inventory_transactions.py` 使用 MySQL 8+ 方言离线生成，尚未执行。升级在建表后为每条 `stock > 0` 的 ProductKit 写一条 `opening_balance`，零库存不写；不修改余额，不静默忽略幂等冲突。DDL 隐式提交导致建表和数据回填不具备整体原子性，因此执行前必须停写、扫描库存范围并备份，执行后必须核对正库存 Kit 与期初流水的一一对应。downgrade 只删除流水表，不重算余额，属于数据破坏操作。

---

### 3.9 audit_logs（审计日志表）

记录关键操作的审计日志，包括操作人、操作类型、目标对象及 IP 地址。日志为顺序写入（非 fire-and-forget）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| operator_id | BIGINT | NOT NULL | 操作人 ID |
| action | VARCHAR(50) | NOT NULL | 操作类型（如 `CREATE_PRODUCT`、`CREATE_ORDER`、`MARK_ORDER_PAID`） |
| target_type | VARCHAR(50) | NOT NULL | 目标类型（`product` / `user` / `order`） |
| target_id | BIGINT | NOT NULL | 目标 ID |
| description | VARCHAR(256) | nullable | 附加描述（如价格变更前后值） |
| ip_address | VARCHAR(45) | NOT NULL | 操作人 IP（支持 IPv6） |
| created_at | DATETIME | - | 操作时间 |

---

## 4. 关系总览

| 关系 | 类型 | 说明 |
|------|------|------|
| users → orders | 一对多 | 一个用户可以有多个订单 |
| orders → order_items | 一对多 | 一个订单包含多个商品明细 |
| order_items → products | 多对一 | 每个明细关联一个商品 |
| order_items → experience_options | 多对一 | 体验订单关联具体配置（套装为 NULL） |
| products → experience_options | 一对多 | 一个体验商品包含多个可选配置 |
| products → product_kits | 一对一 | 套装商品的扩展信息 |
| products → product_images | 一对多 | 一个商品有多张图片 |
| products → inventory_transactions | 一对多 | 一个 Kit Product 可以有多条不可变库存流水 |
| users → inventory_transactions | 一对多（可空） | 用户可作为流水触发者；迁移/系统事件允许无用户 |

**外键约束：** Product 子表指向 `products` 的 FK 使用 `ON DELETE RESTRICT`，防止绕过业务层物理删除。`product_images.experience_option_id` 是明确例外，使用 `ON DELETE SET NULL`；正常业务仍只逻辑删除 Option，该策略仅作为异常物理删除时的数据库兜底。订单历史链 `orders.user_id`、`order_items.order_id/product_id/experience_option_id` 全部使用 `ON DELETE RESTRICT`；Inventory 的 `product_id` 与可空 `operator_id` 同样使用 `RESTRICT` 保存追溯链。`inventory_transactions.source_id` 是通用来源标识，不建立多态外键。

---

## 5. 字段规范

### 公共字段

| 规范 | 说明 |
|------|------|
| 所有主键 | `id BIGINT AUTO_INCREMENT` |
| 所有时间 | `created_at` / `updated_at` |
| 所有金额 | `DECIMAL(10,2)`，单位：元 |
| 状态/类型字段 | 按模块权威设计：User / Order 使用 `SMALLINT`，Product 使用 `VARCHAR(20)` 字符串 Enum，Inventory 使用容量明确的 VARCHAR 字符串 Enum |
| 所有外键 | `xxx_id BIGINT` |

### 时间字段策略

| 字段 | DB 层 | ORM 层（Tortoise） | 说明 |
|------|-------|-------------------|------|
| `created_at` | `DATETIME`（无默认值） | `DatetimeField(auto_now_add=True)` | 首次 INSERT 时 ORM 自动填入当前时间，之后永不修改 |
| `updated_at` | `DATETIME`（无默认值） | `DatetimeField(auto_now=True)` | 每次 `save()` 时 ORM 自动更新为当前时间 |

> **数据库不设 `DEFAULT CURRENT_TIMESTAMP` 或 `ON UPDATE`。** 整个项目统一通过 ORM 操作数据库，时间戳由 Tortoise 的 `auto_now_add` / `auto_now` 管理，不依赖数据库层面的时间函数。这样做的原因：
>
> 1. **统一策略**——避免数据库和 ORM 之间的时间行为不一致
> 2. **可测试性**——ORM 管理的时间在测试中更容易被 mock/freeze
> 3. **代码可读**——看到 Model 定义中的 `auto_now_add=True` 就知道行为，无需查 DDL

### 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| 表名 | 小写、复数、snake_case | `users`、`order_items` |
| 字段名 | 小写、snake_case | `created_at`、`product_id` |
| 外键 | `关联表_id` | `user_id`、`product_id` |
| 时间字段 | `xxx_at` | `created_at`、`updated_at` |

---

## 6. 数据库范式

当前设计满足：

| 范式 | 说明 | 实现方式 |
|------|------|----------|
| 1NF | 字段原子性 | 所有字段不可再分 |
| 2NF | 消除部分依赖 | 主键均为单字段 `id` |
| 3NF | 消除传递依赖 | 体验/套装信息通过外键关联，不冗余 |

**反规范化例外**：`order_items` 中的 `product_name` 和 `product_price` 为快照字段，故意冗余以保证历史数据准确性。这是一个可接受的、有意识的反规范化设计。

---

## 7. 索引设计

### 7.1 设计原则

**根据查询场景设计索引，而不是根据字段设计索引。**

| 原则 | 说明 |
|------|------|
| 查询驱动 | 先梳理 SQL 查询模式，再确定索引列 |
| 最左匹配 | 复合索引按过滤频率和选择性的降序排列列 |
| 避免冗余 | 如果 `(a, b)` 已存在，无需再建 `(a)` |
| 空间权衡 | 低基数字段（如 boolean）可省略，除非是首列过滤条件 |

### 7.2 查询模式 → 索引映射

#### users

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE username = ?` | 极高（登录） | `UNIQUE(username)` ✅ 已有 |
| 2 | `WHERE phone = ?` | 高（注册查重） | `UNIQUE(phone)` ✅ 已有 |
| 3 | `WHERE status = ? AND role = ? ORDER BY created_at` | 中（管理后台） | `(status, role)` |

```sql
-- Migration SQL
CREATE INDEX idx_users_status_role ON users (status, role);
```

#### products

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE status = 'online' AND is_deleted = false ORDER BY created_at` | **极高**（首页列表） | **`(status, is_deleted)`** |
| 2 | `WHERE is_deleted = false [AND status = ?] [AND product_type = ?]` | 中（管理后台） | 传入 `status` 时可使用索引 #1；仅按 `is_deleted` 时不满足最左匹配 |

> **为什么 `status` 在前？** 因为 `status` 的选择性高于 `is_deleted`（`is_deleted` 绝大多数为 `false`）。索引 `(status, is_deleted)` 可以同时覆盖：
> - `WHERE status = ?`（最左匹配）
> - `WHERE status = ? AND is_deleted = ?`（完整匹配）
>
> 如果反过来建 `(is_deleted, status)`，单独按 `status` 过滤时索引无法使用。

> 该索引**不能**覆盖只按 `is_deleted` 的查询。当前不为低选择性的布尔字段单独建索引；待 Repository 冻结管理列表的排序与筛选组合后，再用真实查询计划评估是否增加 `(is_deleted, updated_at)` 等管理端索引。

```sql
-- Migration SQL
CREATE INDEX idx_products_status_deleted ON products (status, is_deleted);
```

#### experience_options

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE product_id = ? AND duration = ? AND participants = ? AND day_type = ?`（包含已删除记录） | 中（创建/恢复与唯一校验） | `UNIQUE(product_id, duration, participants, day_type)` ✅ 已有 |
| 2 | `WHERE product_id = ?` | 高（详情页展示） | 被 UNIQUE 索引覆盖（最左匹配 product_id） |

```sql
-- 无需额外索引：UNIQUE(product_id, duration, participants, day_type) 已覆盖 product_id 查询
```

#### product_images

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE product_id = ? ORDER BY sort` | 中 | `(product_id, sort)` |
| 2 | `WHERE product_id = ? AND is_cover = true LIMIT 1` | 中（封面查找） | `(product_id, is_cover)` |
| 3 | `WHERE experience_option_id = ? ORDER BY sort, id` | 中（Option 图片展示） | `(experience_option_id, sort)` |

```sql
-- Migration SQL
CREATE INDEX idx_image_product_sort ON product_images (product_id, sort);
CREATE INDEX idx_image_product_cover ON product_images (product_id, is_cover);
CREATE INDEX idx_image_option_sort ON product_images (experience_option_id, sort);
```

#### orders

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE user_id = ? ORDER BY created_at DESC, id DESC` | 高（我的全部订单） | `(user_id, created_at, id)` |
| 2 | `WHERE user_id = ? AND status = ? ORDER BY created_at DESC, id DESC` | 高（我的订单状态筛选） | `(user_id, status, created_at, id)` |
| 3 | `WHERE status = ? ORDER BY created_at DESC, id DESC` | 中（管理端状态筛选） | `(status, created_at, id)` |
| 4 | `ORDER BY created_at DESC, id DESC` / 创建时间范围 | 中（管理端全部订单） | `(created_at, id)` |
| 5 | `WHERE order_no = ?` | 极高（精确查询） | `UNIQUE(order_no)` ✅ 已有 |

```sql
-- Migration SQL
CREATE INDEX idx_orders_user_created_id ON orders (user_id, created_at, id);
CREATE INDEX idx_orders_user_status_created_id ON orders (user_id, status, created_at, id);
CREATE INDEX idx_orders_status_created_id ON orders (status, created_at, id);
CREATE INDEX idx_orders_created_id ON orders (created_at, id);
```

`user_id` 和时间范围同时筛选时可使用 `idx_orders_user_created_id`；精确 `order_no` 使用唯一索引。是否为低频的复杂组合再增加索引，留待 Repository 固化 SQL 后用 MySQL `EXPLAIN` 评估，当前不为所有筛选排列建立组合索引。

#### order_items

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE order_id = ? ORDER BY id` | 高（订单详情） | `(order_id, id)` |

```sql
-- Migration SQL
CREATE INDEX idx_order_items_order_id ON order_items (order_id, id);
```

#### inventory_transactions

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE idempotency_key = ?` | 极高（写入前幂等判断与并发兜底） | `UNIQUE(idempotency_key)` |
| 2 | `WHERE product_id = ? ORDER BY created_at DESC, id DESC` | 高（单 Kit 流水） | `(product_id, created_at, id)` |
| 3 | `WHERE source_type = ? AND source_id = ? ORDER BY created_at DESC, id DESC` | 中（Order 来源追溯） | `(source_type, source_id, created_at, id)` |
| 4 | `WHERE transaction_type = ? ORDER BY created_at DESC, id DESC` | 中（类型筛选） | `(transaction_type, created_at, id)` |
| 5 | `ORDER BY created_at DESC, id DESC` / 创建时间范围 | 中（全局流水） | `(created_at, id)` |

```sql
CREATE UNIQUE INDEX uidx_inventory_idempotency_key ON inventory_transactions (idempotency_key);
CREATE INDEX idx_inventory_product_created_id ON inventory_transactions (product_id, created_at, id);
CREATE INDEX idx_inventory_source_created_id ON inventory_transactions (source_type, source_id, created_at, id);
CREATE INDEX idx_inventory_type_created_id ON inventory_transactions (transaction_type, created_at, id);
CREATE INDEX idx_inventory_created_id ON inventory_transactions (created_at, id);
```

只按 `source_type` 筛选时可利用索引首列过滤，但由于 `source_id` 位于排序列之前，可能仍需要排序；当前优先优化按具体 Order source 的追溯。是否增加第二组 source-only 索引留待 4.3.5 Repository 固化 SQL 后，用 MySQL `EXPLAIN` 和真实数据量决定，避免预先制造冗余索引。

#### audit_logs

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE target_type = ? AND target_id = ? ORDER BY created_at DESC` | 中（实体审计追踪） | `(target_type, target_id, created_at)` |
| 2 | `WHERE operator_id = ? ORDER BY created_at DESC` | 中（操作人行为审计） | `(operator_id, created_at)` |

```sql
-- Migration SQL
CREATE INDEX idx_audit_target_created ON audit_logs (target_type, target_id, created_at);
CREATE INDEX idx_audit_operator_created ON audit_logs (operator_id, created_at);
```

### 7.3 索引汇总

| 表 | 索引名 | 列 | 类型 | 覆盖查询 |
|----|--------|-----|------|----------|
| `users` | `idx_users_status_role` | `(status, role)` | 普通 | 管理后台用户列表 |
| `products` | `idx_products_status_deleted` | `(status, is_deleted)` | 普通 | 客户列表、管理后台列表 |
| `experience_options` | `idx_option_unique` | `(product_id, duration, participants, day_type)` | UNIQUE | 全历史唯一、创建/恢复校验、按 product 查询 |
| `product_images` | `idx_image_product_sort` | `(product_id, sort)` | 普通 | 图片排序展示 |
| `product_images` | `idx_image_product_cover` | `(product_id, is_cover)` | 普通 | 封面图查找 |
| `product_images` | `idx_image_option_sort` | `(experience_option_id, sort)` | 普通 | Option 图片排序展示 |
| `orders` | `idx_orders_user_created_id` | `(user_id, created_at, id)` | 普通 | 我的全部订单、按用户筛选 |
| `orders` | `idx_orders_user_status_created_id` | `(user_id, status, created_at, id)` | 普通 | 我的订单状态筛选 |
| `orders` | `idx_orders_status_created_id` | `(status, created_at, id)` | 普通 | 管理端状态筛选 |
| `orders` | `idx_orders_created_id` | `(created_at, id)` | 普通 | 管理端全部订单与时间范围 |
| `order_items` | `idx_order_items_order_id` | `(order_id, id)` | 普通 | 订单详情稳定顺序 |
| `inventory_transactions` | `uidx_inventory_idempotency_key` | `(idempotency_key)` | UNIQUE | 自动事件与管理员请求幂等兜底 |
| `inventory_transactions` | `idx_inventory_product_created_id` | `(product_id, created_at, id)` | 普通 | 单 Kit 流水稳定分页 |
| `inventory_transactions` | `idx_inventory_source_created_id` | `(source_type, source_id, created_at, id)` | 普通 | Order 来源追溯 |
| `inventory_transactions` | `idx_inventory_type_created_id` | `(transaction_type, created_at, id)` | 普通 | 类型筛选稳定分页 |
| `inventory_transactions` | `idx_inventory_created_id` | `(created_at, id)` | 普通 | 全局流水与时间范围 |
| `audit_logs` | `idx_audit_target_created` | `(target_type, target_id, created_at)` | 普通 | 实体审计追踪 |
| `audit_logs` | `idx_audit_operator_created` | `(operator_id, created_at)` | 普通 | 操作人行为审计 |

### 7.4 不需要索引的表

| 表 | 原因 |
|----|------|
| `product_kits` | 仅通过 `product_id`（已有 UNIQUE 约束及其索引）查询，无需额外索引 |

---

## 8. 后续扩展计划

| 版本 | 新增内容 |
|------|----------|
| v0.2 | 收藏表、评价表、支付记录表 |
| v0.3 | AI 推荐记录、AI 生成模板表 |
| v1.0 | 微信登录凭证、退款记录、后台操作日志 |
