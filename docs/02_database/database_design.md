# pinkdooHub 数据库设计 v1.2

> **Last Updated:** 2026-08-10

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
  │
  └── products
        ├── experience_options
        ├── product_kits
        └── product_images

audit_logs
```

### 2.1 数据完整性约束边界

Product 规则由三层共同保证，文档中的“必须”不等于所有规则都由物理数据库独立完成：

| 层级 | 当前保证 |
|------|----------|
| 数据库 | `NOT NULL`、字段类型、默认值、外键删除策略、Kit 一对一唯一性、Option 全历史联合唯一性和命名索引 |
| Schema / Model | 文本长度、正整数、金额范围与小数位、库存和图片排序非负、字符串 Enum 合法性 |
| Service / Validator | Product 类型与扩展表匹配、图片与 Option 同属一个 Product、单封面与 Option 禁止封面、状态流转和上架完整性 |

当前 Product Model 没有声明数据库 `CHECK` 约束，因此绕过应用直接执行 SQL 可能绕过正数、金额范围等值域规则。生产数据写入必须经过应用或受 Review 的迁移/运维脚本；是否把这些值域进一步下沉为跨 MySQL/SQLite 的命名 `CHECK`，在首次 Product 迁移 Review 时统一决定，不能只改某一数据库。

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
| stock | INT | NOT NULL, DEFAULT 0 | 当前库存；Phase 4.1 直接设置最终值，Phase 4.3 再引入库存流水与自动扣减/恢复 |
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

### 3.6 orders（订单表）

订单主表，记录下单用户、金额和状态。不直接保存商品信息，商品明细拆分到 `order_items`。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| order_no | VARCHAR | NOT NULL, UNIQUE | 订单编号 |
| user_id | BIGINT | FK → users.id | 下单用户 |
| total_amount | DECIMAL(10,2) | NOT NULL | 订单总金额，单位：元 |
| status | TINYINT | DEFAULT 0 | 0:待支付 1:已支付 2:已取消 3:已完成 |
| remark | VARCHAR | - | 订单备注 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.7 order_items（订单明细表）

采用订单快照设计：保存下单时的商品名称、价格及体验配置快照，保证历史订单不受商品后续修改影响。体验商品记录具体 Option 信息，套装商品这些字段为 NULL。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| order_id | BIGINT | FK → orders.id | 关联订单 |
| product_id | BIGINT | FK → products.id | 关联原商品 |
| experience_option_id | BIGINT | FK → experience_options.id, nullable | 关联体验配置（套装为 NULL） |
| option_duration | INT | nullable | 快照：正整数分钟数 |
| option_participants | INT | nullable | 快照：人数 |
| option_day_type | VARCHAR(20) | nullable | 快照：日期类型 |
| product_name | VARCHAR | NOT NULL | 下单时商品名称快照 |
| product_price | DECIMAL(10,2) | NOT NULL | 下单时商品价格快照 |
| quantity | INT | DEFAULT 1 | 数量 |
| subtotal | DECIMAL(10,2) | NOT NULL | 小计金额 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.8 audit_logs（审计日志表）

记录关键操作的审计日志，包括操作人、操作类型、目标对象及 IP 地址。日志为顺序写入（非 fire-and-forget）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| operator_id | BIGINT | NOT NULL | 操作人 ID |
| action | VARCHAR(50) | NOT NULL | 操作类型（如 `CREATE_PRODUCT`、`UPDATE_PRICE`） |
| target_type | VARCHAR(50) | NOT NULL | 目标类型（`product` / `user`） |
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

**外键约束：** Product 子表指向 `products` 的 FK 使用 `ON DELETE RESTRICT`，防止绕过业务层物理删除。`product_images.experience_option_id` 是明确例外，使用 `ON DELETE SET NULL`；正常业务仍只逻辑删除 Option，该策略仅作为异常物理删除时的数据库兜底。

---

## 5. 字段规范

### 公共字段

| 规范 | 说明 |
|------|------|
| 所有主键 | `id BIGINT AUTO_INCREMENT` |
| 所有时间 | `created_at` / `updated_at` |
| 所有金额 | `DECIMAL(10,2)`，单位：元 |
| 状态字段 | 按模块权威设计：User / Order 使用 `TINYINT`，Product 使用 `VARCHAR(20)` 字符串 Enum |
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
| 1 | `WHERE user_id = ? [AND status = ?] ORDER BY created_at DESC` | 高（我的订单） | `(user_id, status, created_at)` |
| 2 | `WHERE status = ? ORDER BY created_at DESC` | 中（管理后台） | `(status, created_at)` |
| 3 | `WHERE order_no = ?` | 极高（查询） | `UNIQUE(order_no)` ✅ 已有 |

```sql
-- Migration SQL
CREATE INDEX idx_orders_user_status_created ON orders (user_id, status, created_at);
CREATE INDEX idx_orders_status_created ON orders (status, created_at);
```

#### order_items

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE order_id = ?` | 高（订单详情） | `(order_id)` |

```sql
-- Migration SQL
CREATE INDEX idx_order_items_order ON order_items (order_id);
```

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
| `orders` | `idx_orders_user_status_created` | `(user_id, status, created_at)` | 普通 | 我的订单列表（含状态筛选） |
| `orders` | `idx_orders_status_created` | `(status, created_at)` | 普通 | 管理后台订单管理 |
| `order_items` | `idx_order_items_order` | `(order_id)` | 普通 | 订单详情（FK 查询） |
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
