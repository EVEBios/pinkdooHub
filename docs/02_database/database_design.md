# pinkdooHub 数据库设计 v1.0

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

---

## 3. 表详细说明

### 3.1 users（用户表）

存储平台用户信息，支撑登录认证、JWT 身份识别和订单关联。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| username | VARCHAR | NOT NULL, UNIQUE | 登录账号 |
| password | VARCHAR | NOT NULL | 加密密码 |
| nickname | VARCHAR | - | 用户昵称 |
| phone | VARCHAR | NOT NULL, UNIQUE | 手机号码 |
| avatar | VARCHAR | - | 头像 URL |
| role | TINYINT | DEFAULT 1 | 1:普通用户 2:管理员 3:超级管理员 |
| status | TINYINT | DEFAULT 1 | 1:正常 2:禁用 |
| last_login_at | DATETIME | - | 最后登录时间 |
| created_at | DATETIME | - | 注册时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.2 products（商品表）

所有商品的公共信息，采用统一商品表设计。价格由各子表管理（体验 → `experience_options.price`，套装 → `product_kits.price`），products 表仅存储公共字段。

DB 使用 VARCHAR 存储 `product_type` 和 `status`，代码层 **必须** 使用 `StrEnum`（`ProductType` / `ProductStatus`），禁止 Magic String。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| name | VARCHAR(100) | NOT NULL | 商品名称，允许重名 |
| product_type | VARCHAR | NOT NULL | `"experience"` / `"kit"`，创建后不可修改 |
| description | TEXT | - | 商品描述 |
| status | VARCHAR | DEFAULT `"draft"` | `"draft"` / `"online"` / `"offline"` |
| is_deleted | BOOLEAN | DEFAULT FALSE | 逻辑删除标记 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

> **价格分离原则：** 体验商品价格来自 `experience_options.price`，套装商品价格来自 `product_kits.price`。`products` 表不设 `price` 字段，避免语义混淆。

---

### 3.3 experience_options（体验配置表）

拼豆体验的可选配置，与 `products` **一对多**关联。每条 Option 代表一个独立可售配置（时长 + 人数 + 日期类型 → 价格）。

管理员可随时新增/修改/删除 Option。删除 Option 后若商品 `online` 且剩余 Option = 0，则自动转为 `draft`。Option 无独立状态字段，跟随 Product 的生命周期。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, NOT NULL | 关联商品 |
| duration | VARCHAR | NOT NULL | `"1h"` / `"2h"` / `"full_day"` |
| participants | INT | NOT NULL | 体验人数：1 / 2 |
| day_type | VARCHAR | NOT NULL | `"weekday"` 工作日 / `"holiday"` 节假日 |
| price | DECIMAL(10,2) | NOT NULL | 该配置的售价，0 < Price ≤ 99999 |
| sort | INT | DEFAULT 0 | 展示排序（如 10/20/30，留间隔便于插入） |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

**唯一约束：** `(product_id, duration, participants, day_type)` 联合唯一，禁止同一商品内出现重复配置。

---

### 3.4 product_kits（套装商品表）

拼豆套装的专有信息，与 `products` 一对一关联。套装价格直接存储在此表。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, UNIQUE | 关联商品 |
| price | DECIMAL(10,2) | NOT NULL | 套装售价，0 < Price ≤ 99999 |
| stock | INT | NOT NULL, DEFAULT 0 | 当前库存 |
| sold_count | INT | DEFAULT 0 | 累计销量 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.5 product_images（商品图片表）

一个商品可有多张图片，采用一对多关系。封面图通过 `is_cover = TRUE` 标记，`products` 表不再单独存储封面字段，统一由此表管理。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id | 关联商品 |
| image_url | VARCHAR | NOT NULL | 图片 URL |
| is_cover | BOOLEAN | DEFAULT FALSE | 是否封面图，每商品最多一张 |
| sort | INT | DEFAULT 0 | 排序序号 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

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
| option_duration | VARCHAR | nullable | 快照：时长 |
| option_participants | INT | nullable | 快照：人数 |
| option_day_type | VARCHAR | nullable | 快照：日期类型 |
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

**外键约束：** 所有 FK 使用 `ON DELETE RESTRICT`，防止绕过业务层物理删除。

---

## 5. 字段规范

### 公共字段

| 规范 | 说明 |
|------|------|
| 所有主键 | `id BIGINT AUTO_INCREMENT` |
| 所有时间 | `created_at` / `updated_at` |
| 所有金额 | `DECIMAL(10,2)`，单位：元 |
| 所有状态 | `TINYINT`，文档标注每个值的含义 |
| 所有外键 | `xxx_id BIGINT` |

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

## 7. 后续扩展计划

| 版本 | 新增内容 |
|------|----------|
| v0.2 | 收藏表、评价表、支付记录表 |
| v0.3 | AI 推荐记录、AI 生成模板表 |
| v1.0 | 微信登录凭证、退款记录、后台操作日志 |
