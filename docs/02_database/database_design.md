# pinkdooHub 数据库设计 v2.0

> **Last Updated:** 2026-09-06

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
  ├── external_identities
  ├── orders ── order_items
  │     ├── payments ── payment_settlements ── refunds
  │     └── inventory_transactions
  ├── wallet_accounts
  │     ├── wallet_transactions
  │     └── recharge_orders ── payments
  ├── operated inventory_transactions
  ├── operated wallet_transactions / refunds
  └── reservations

products
  ├── experience_options
  ├── product_kits
  ├── product_kit_colors ── bead_colors
  ├── product_images
  ├── inventory_transactions
  └── reservations

store_business_days ── reservations

audit_logs
```

### 2.1 数据完整性约束边界

Product、Order、Inventory、Wallet/Payment/Refund 与 Reservation 规则由三层共同保证，文档中的“必须”不等于所有规则都由物理数据库独立完成。M6 新增字段与表仍属于未应用的仓库增量：

| 层级 | 当前保证 |
|------|----------|
| 数据库 | `NOT NULL`、字段类型、默认值、外键删除策略、Kit/Wallet/Settlement/Refund 一对一唯一性、Option 全历史联合唯一性、颜色槽号/非空颜色编码/商品与颜色关联唯一性、营业日日期唯一性、业务编号唯一性、Inventory/Wallet/Payment/Refund 幂等键唯一性和命名索引；四类资金幂等键在 MySQL 使用 `ascii_bin` 逐字节区分大小写 |
| Schema / Model | 文本长度、正整数、金额范围与两位小数、库存 `0..999999`、颜色槽 `1..221`、自选颜色销售单位固定 10g、钱包余额 `0.00..1000.00`、流水单字段边界、非零变化量、Enum 合法性、Order Item 每色数量/分类项数/重复三元组边界、Reservation 日期与半小时时间输入、快照字段边界 |
| Service / Validator | Product 类型、KitKind 与扩展表匹配，颜色目录完整性、商品级启用和上架完整性，图片与 Option 同属一个 Product、单封面与 Option 禁止封面、状态流转；Order 聚合可售性、颜色归属、快照金额与状态机；Inventory 固定 Kit / 商品颜色余额权威选择、before/change/after 等式、类型/来源组合、锁后余额判断和余额/流水同事务；Wallet/Payment/Settlement/Refund 金额、状态、权限和幂等一致性；Reservation 上海营业日、提前量、完整营业时段、Option 日期类型、状态/原因/时间组合和店休批量取消原子性 |

当前 Product、Order、Inventory、Wallet/Payment/Refund 与 Reservation Model 没有声明数据库 `CHECK` 约束，因此绕过应用直接执行 SQL 可能绕过正数、金额范围、流水算术、预约状态/原因/时间组合等值域规则。生产数据写入必须经过应用或受 Review 的迁移/运维脚本；是否把这些值域进一步下沉为跨 MySQL/SQLite 的命名 `CHECK`，必须作为独立设计变更统一评估，不能只改某一数据库。

---

## 3. 表详细说明

### 3.1 users（用户表）

存储平台用户信息，支撑登录认证、JWT 身份识别和订单关联。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| username | VARCHAR(32) | NOT NULL, UNIQUE | 登录账号 |
| password | VARCHAR(128) | nullable | bcrypt 密码哈希；微信首次登录账号可为空 |
| nickname | VARCHAR(32) | NOT NULL | 用户昵称 |
| phone | VARCHAR(11) | nullable, UNIQUE | 手机号码；微信首次登录账号可为空；非空值由数据库兜底并发唯一性 |
| avatar | VARCHAR(256) | nullable | 头像 URL |
| role | SMALLINT | NOT NULL | 1:普通用户 2:管理员 3:超级管理员；ORM 默认 1 |
| status | SMALLINT | NOT NULL | 1:正常 2:禁用 3:已注销；ORM 默认 1 |
| last_login_at | DATETIME | - | 最后登录时间 |
| auth_version | INT | NOT NULL, DEFAULT 0 | 安全凭据版本；密码/绑定/注销变化时使旧 access 失效 |
| deleted_at | DATETIME(6) | nullable | 完成账号匿名化的 UTC 时间 |
| created_at | DATETIME | - | 注册时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

### 3.1a external_identities（外部身份绑定表，Phase 9.5）

一条记录表示一个用户在一个外部平台应用中的绑定。表名沿用通用 provider 边界，当前只允许 `wechat_miniprogram`。`subject_id` / `union_id` 字段名表示平台主体键，但实际值必须是用独立 `EXTERNAL_IDENTITY_PEPPER` 生成的 HMAC-SHA256 十六进制字符串；禁止写入原始 OpenID/UnionID 或 `session_key`。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| provider | VARCHAR(32) | NOT NULL | 当前为 `wechat_miniprogram` |
| app_id | VARCHAR(64) | NOT NULL | 非 Secret 的平台应用 ID |
| subject_id | VARCHAR(128) | NOT NULL | 原始平台主体标识的稳定 HMAC |
| union_id | VARCHAR(128) | nullable | 原始 UnionID 的稳定 HMAC；平台不返回时为空 |
| user_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | 绑定用户 |
| created_at | DATETIME(6) | NOT NULL | 绑定时间 |
| updated_at | DATETIME(6) | NOT NULL | 技术更新时间 |

唯一性与查询索引：

- `uidx_external_identity_subject(provider, app_id, subject_id)`：同一应用主体只绑定一个账号；
- `uidx_external_identity_union(provider, union_id)`：非空 UnionID 不允许跨账号冲突；MySQL 允许多行 NULL；
- `idx_external_identity_user_provider(user_id, provider, created_at)`：用户绑定摘要与解绑查询。

账号注销先删除绑定记录，再匿名化 users 行；Users 受 Order/Inventory/Audit 的历史外键约束，不物理删除。

---

### 3.2 products（商品表）

所有商品的公共信息，采用统一商品表设计。价格由各子表管理（体验 → `experience_options.price`，套装 → `product_kits.price`），products 表仅存储公共字段。

DB 使用 VARCHAR 存储 `product_type`、`status` 与 Kit 扩展中的 `kit_kind`，代码层 **必须** 使用 Python 3.10 兼容的 `str, Enum`（`ProductType` / `ProductStatus` / `KitKind`），禁止 Magic String。ORM 使用字符串枚举字段，数据库值仍为普通 VARCHAR。

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

拼豆套装的专有信息，与 `products` 一对一关联。`kit_kind` 决定库存余额权威：既有固定套装使用本表 `stock`；自选颜色套装使用 `product_kit_colors.stock_units`，本表 `stock` 必须为 NULL。两者共享 `price`，但自选颜色的价格语义为每 10g 单价。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| product_id | BIGINT | FK → products.id, NOT NULL, UNIQUE | 关联商品 |
| price | DECIMAL(10,2) | NOT NULL | 套装售价，0 < Price ≤ 99999 |
| stock | INT | nullable, DEFAULT 0 | `fixed` 的唯一权威当前库存，应用范围 `0..999999`；`color_selectable` 必须为 NULL |
| kit_kind | VARCHAR(20) | NOT NULL, DEFAULT `fixed` | `fixed` / `color_selectable`；创建后不可修改；默认值保持历史行兼容 |
| sale_unit_grams | SMALLINT | nullable | `color_selectable` 固定为 `10`；`fixed` 必须为 NULL |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

---

> `sold_count` 不存储在 Product 模块。累计销量由订单模块统计。

### 3.4a bead_colors（全局拼豆颜色目录，M6）

全系统固定保留 221 个颜色槽。槽位是稳定身份，不代表 221 个槽都已经配置或可销售；首次 M6 升级幂等创建 `slot_no=1..221` 的占位行，名称和业务编码可稍后补齐。色板图片属于全局颜色目录，不复制到每个商品。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 全局颜色内部 ID |
| slot_no | SMALLINT | NOT NULL, UNIQUE | 稳定槽位，应用范围 `1..221` |
| color_code | VARCHAR(50) | nullable, UNIQUE | 非空时全局唯一；占位槽可为空 |
| name | VARCHAR(100) | nullable | 顾客与管理员展示名；占位槽可为空 |
| swatch_image_url | VARCHAR(2048) | nullable | 可选全局色板图 URL；建议离线导入 192×192 或 256×256 sRGB WebP |
| sort | SMALLINT | NOT NULL, DEFAULT 0, CHECK 0..32767 | 管理/顾客展示排序；占位初始化为 slot_no，请求/响应/Model 使用相同上限 |
| is_active | BOOLEAN | NOT NULL, DEFAULT FALSE | 全局可用开关；只有 code/name 均完整时才允许 true |
| created_at / updated_at | DATETIME | - | 技术时间 |

`sort` 的单字段范围由 M6 `CHECK` 与有符号 SMALLINT 容量共同兜底。`is_active` 与 code/name 完整性、Online 商品引用保护属于 Service 规则而非跨字段数据库 `CHECK`。全局颜色维护按“引用 Product ID 升序 → BeadColor → 当前启用 ProductKitColor”锁序执行，上架和商品颜色启停也以 Product 行为共同互斥点；所有可售性判断都在锁后重载。`swatch_image_url` 本期只保存可选 URL；221 张图的离线批量导入工具应有 manifest、dry-run/apply、格式与尺寸校验，不能通过 221 次现有 Product 单图上传接口替代。

### 3.4b product_kit_colors（商品级颜色与库存，M6）

每个 `color_selectable` Kit 创建时在同一事务关联全部 221 个全局槽，初始全部 `is_enabled=false`、`stock_units=0`。启用状态和余额属于该商品，两个商品即使引用同一 `bead_color_id` 也不共享库存。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 下单 `kit_color_id` 指向的商品颜色身份 |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | 所属自选颜色 Kit |
| bead_color_id | BIGINT | FK → bead_colors.id, NOT NULL, ON DELETE RESTRICT | 全局颜色身份 |
| is_enabled | BOOLEAN | NOT NULL, DEFAULT FALSE | 商品是否销售该颜色；Online 时不可直接修改 |
| stock_units | INT | NOT NULL, DEFAULT 0 | 商品该颜色的权威余额，单位为 10g，范围 `0..999999` |
| created_at / updated_at | DATETIME | - | 技术时间 |

`UNIQUE(product_id, bead_color_id)` 防止同一商品重复关联同一全局槽。数据库不能单独保证“只有 color_selectable 才能关联”“每个商品恰好 221 行”；创建 Service 与上架 Validator 必须在聚合事务/快照中保证。库存为 0 不妨碍颜色被启用或商品上架，只会使公开详情的该色 `available=false`。

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

采用订单快照设计：保存下单时的商品名称、价格以及体验配置或自选颜色信息，保证历史订单不受商品后续修改影响。Experience、固定 Kit、自选颜色 Kit 形成互斥三态。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| order_id | BIGINT | FK → orders.id, NOT NULL, ON DELETE RESTRICT | 关联订单 |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | 关联原商品 |
| experience_option_id | BIGINT | FK → experience_options.id, nullable, ON DELETE RESTRICT | Experience Item 关联具体配置；Kit Item 为 NULL |
| kit_color_id | BIGINT | FK → product_kit_colors.id, nullable, ON DELETE RESTRICT | 自选颜色 Kit Item 必填；Experience / fixed Kit 为 NULL |
| option_duration_minutes | INT | nullable | 快照：正整数分钟数 |
| option_participants | INT | nullable | 快照：人数 |
| option_day_type | VARCHAR(20) | nullable | 快照：日期类型 |
| product_name | VARCHAR(100) | NOT NULL | 下单时商品名称快照 |
| kit_color_code | VARCHAR(50) | nullable | 自选颜色业务编码快照 |
| kit_color_name | VARCHAR(100) | nullable | 自选颜色名称快照 |
| kit_color_slot_no | SMALLINT | nullable | 自选颜色槽号快照，范围 `1..221` |
| sale_unit_grams | SMALLINT | nullable | 自选颜色销售单位快照，当前固定 `10` |
| product_price | DECIMAL(10,2) | NOT NULL | 下单时商品价格快照 |
| quantity | INT | NOT NULL | 数量，范围 1 至 99；自选颜色表示 10g 单位数 |
| subtotal | DECIMAL(10,2) | NOT NULL | 小计金额 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 最近更新时间 |

M6 后每单总计 1 至 30 行，其中颜色行最多 20、非颜色行最多 10；每个颜色一条 OrderItem，每色 `quantity <= 99`。请求 Schema 以 `(product_id, experience_option_id, kit_color_id)` 判重。当前不增加数据库唯一约束：nullable 组合在不同数据库中的唯一语义不适合作为三态规则的唯一保证，且一次订单创建只有单一受控写入口。Service 还必须验证 Experience 只带 Option、fixed Kit 二者皆空、color_selectable Kit 只带所属且启用/激活/已配置的 kit_color。

`total_weight_grams = quantity * sale_unit_grams` 是响应派生值，不持久化。颜色名称、编码、槽号和销售单位均为创建快照；后续全局颜色改名、停用或商品禁售不改历史订单。

**历史保护：** Order、OrderItem 不提供删除接口。用户、Product 与 Option 的物理删除均由 `RESTRICT` 阻止；Product 与 Option 的正常业务删除继续使用逻辑删除。历史展示始终读取 OrderItem 快照，不依赖当前 Product/Option 内容。

---

### 3.8 inventory_transactions（库存流水表，Phase 4.3.4 已生成离线迁移）

记录每一次已提交的库存变化。fixed Kit 的当前余额为 `product_kits.stock`，color_selectable Kit 的每色当前余额为 `product_kit_colors.stock_units`；流水用于追溯，不能通过实时汇总流水替代余额读取。表继承 `BaseModel`，因此包含技术字段 `updated_at`；业务上不提供更新或删除路径，API 也不输出该字段。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 流水 ID |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | Kit 的对外 Product ID |
| kit_color_id | BIGINT | FK → product_kit_colors.id, nullable, ON DELETE RESTRICT | fixed 流水为 NULL；颜色流水指向精确商品颜色余额行 |
| transaction_type | VARCHAR(40) | NOT NULL | `opening_balance` / `admin_adjustment` / `order_deduction` / `order_cancellation_restore` / `order_refund_restore` |
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

**不可变边界：** 数据库负责非空、外键、幂等唯一性和字段容量；Model 负责单字段范围与非零变化量；Service 根据 KitKind、类型/source 契约计算并验证 before/change/after，在持有对应 ProductKit 或 ProductKitColor 行锁的同一事务内更新余额和插入流水。当前不增加跨 MySQL/SQLite 的 `CHECK`，直接 SQL 仍属于受 Review 的受控路径。

**来源设计：** `source_id` 故意不关联 Order 外键，避免把通用来源列伪装为只属于订单。查询层只允许 `source_id` 与 `source_type=order` 组合，并在 Repository/Mapper 阶段按需加载安全订单号。

**增量迁移：** `2_20260814104655_add_inventory_transactions.py` 建立既有 fixed 流水并回填正库存期初余额；M6 候选迁移 `6_20260906123000_add_color_selectable_kits.py` 新增颜色目录、商品颜色余额、Order/Inventory FK 与快照字段，依靠 `kit_kind` 的 `DEFAULT 'fixed'` 保持历史 ProductKit 语义，并插入 1..221 占位槽。该迁移已离线生成但尚未通过真实 MySQL 0→6 门槛，也未应用任何持久环境；正式迁移必须在停写与备份后核对 221 槽、历史 fixed 余额不变、外键/索引和 Aerich 版本链。MySQL DDL 隐式提交使整个升级不能承诺原子回滚；downgrade 会删除颜色库存/关联并把 null 聚合库存转为 0，属于数据破坏操作。

---

### 3.9 audit_logs（审计日志表）

记录关键操作的审计日志，包括操作人、操作类型、目标对象及 IP 地址。日志为顺序写入（非 fire-and-forget）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键 |
| operator_id | BIGINT | NOT NULL | 操作人 ID |
| action | VARCHAR(50) | NOT NULL | 操作类型（如 `CREATE_PRODUCT`、`CREATE_ORDER`、`PAY_ORDER`、`ADJUST_WALLET`、`REFUND_ORDER`） |
| target_type | VARCHAR(50) | NOT NULL | 目标类型（`product` / `user` / `order` / `wallet`） |
| target_id | BIGINT | NOT NULL | 目标 ID |
| description | VARCHAR(256) | nullable | 附加描述（如价格变更前后值） |
| ip_address | VARCHAR(45) | NOT NULL | 操作人 IP（支持 IPv6） |
| created_at | DATETIME | - | 操作时间 |

---

### 3.10 wallet_accounts（会员钱包余额表，M4 离线迁移未应用）

为可用普通客户保存权威钱包余额；新建 USER 原子创建，历史 backfill 只覆盖 NORMAL/DISABLED USER。历史 DELETED USER 可没有钱包且禁止补建；ADMIN/SUPER_ADMIN 不创建钱包。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 钱包 ID |
| user_id | BIGINT | FK → users.id, NOT NULL, UNIQUE, ON DELETE RESTRICT | 每个已建钱包的普通 USER 至多一个；正常运行时 NORMAL/DISABLED USER 应恰好一个 |
| balance | DECIMAL(10,2) | NOT NULL, DEFAULT 0.00 | 权威余额；应用闭区间 `0.00..1000.00` |
| status | VARCHAR(32) | NOT NULL, DEFAULT `active` | `active` / `closed`；用户禁用仍以 users.status 为权威 |
| created_at | DATETIME | - | 创建时间 |
| updated_at | DATETIME | - | 余额或状态最近更新时间 |

新普通用户由注册/首次微信登录事务创建零余额钱包。M4 不回填历史用户；历史 `role=user AND status IN (normal, disabled)` 需在启用钱包能力前先运行 `python -m app.tasks.wallet_account_backfill` 预览，再显式使用 `--apply` 补齐。该命令不为历史 DELETED USER 或 ADMIN/SUPER_ADMIN 建钱包，也不创建零元 WalletTransaction；既有历史 deleted 钱包如已存在仍保留。完成 NORMAL/DISABLED 普通 USER wallet backfill 与 legacy manual settlement backfill 后运行只读 `python -m app.tasks.wallet_reconcile`，稳定核验权威余额、流水净额、单行算术/范围、相邻余额链、末条余额和无流水零余额规则；任一违规以非零状态退出，绝不自动改账。

余额硬上限为 `1000.00`，但不新增“预留余额”列。尚可全额退款的钱包支付敞口由 `payment_settlements`、`payments`、`orders` 和 `refunds` 的权威状态在锁内查询派生：PAID wallet Settlement，以及完成未满 30 天的 COMPLETED wallet Settlement，在 Refund succeeded 前占用敞口。ADMIN 正向调账及未来真实充值成功必须保持 `调整后余额 + 派生敞口 ≤ 1000.00`；退款成功与同额钱包入账原子提交后，该 Settlement 自然退出敞口集合。

### 3.11 wallet_transactions（钱包流水表，M4 离线迁移未应用）

记录每次已提交余额变化；WalletAccount.balance 仍是当前余额，不通过实时 SUM 流水提供在线余额。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 流水 ID |
| wallet_account_id | BIGINT | FK → wallet_accounts.id, NOT NULL, ON DELETE RESTRICT | 目标钱包 |
| transaction_type | VARCHAR(32) | NOT NULL | `recharge` / `order_payment` / `admin_adjustment` / `refund` |
| change_amount | DECIMAL(10,2) | NOT NULL | 非零变化量；应用范围 `-1000.00..1000.00` |
| before_balance | DECIMAL(10,2) | NOT NULL | 变化前余额，`0.00..1000.00` |
| after_balance | DECIMAL(10,2) | NOT NULL | 变化后余额，等于 before + change |
| source_type | VARCHAR(32) | NOT NULL | `recharge_order` / `order` / `admin` / `refund` |
| source_id | BIGINT | nullable | 通用业务来源 ID；故意不建多态 FK |
| operator_id | BIGINT | FK → users.id, nullable, ON DELETE RESTRICT | 用户自身或管理操作者 |
| reason | VARCHAR(256) | NOT NULL | 规范化管理原因或服务端稳定原因 |
| idempotency_key | VARCHAR(256) | NOT NULL, UNIQUE；MySQL `ascii_bin` | 内部命名空间业务身份，逐字节区分大小写，不向 API/日志输出 |
| created_at | DATETIME | - | 权威分页时间 |
| updated_at | DATETIME | - | BaseModel 技术字段；无业务修改入口 |

同一钱包的流水以 `(created_at ASC, id ASC)` 形成确定的余额链：每条记录变化量非零且满足 `after = before + change`，前后余额均在 `0.00..1000.00`，相邻记录的前后余额衔接，末条 `after_balance` 等于 WalletAccount.balance。没有流水是合法的零余额初始状态，但此时权威余额必须为 `0.00`；发布前由只读 `wallet_reconcile` 同时核验这些不变量和流水净额。

### 3.12 recharge_orders（充值业务单，M4 离线迁移未应用）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 充值单 ID |
| recharge_no | VARCHAR(28) | NOT NULL, UNIQUE | `RC` + 26 位 Crockford Base32 ULID |
| user_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | 充值普通 USER |
| wallet_account_id | BIGINT | FK → wallet_accounts.id, NOT NULL, ON DELETE RESTRICT | 目标钱包 |
| amount | DECIMAL(10,2) | NOT NULL | 单笔闭区间 `1.00..1000.00` |
| status | VARCHAR(32) | NOT NULL, DEFAULT `pending` | `pending` / `paid` / `failed` / `closed` |
| idempotency_key | VARCHAR(256) | NOT NULL, UNIQUE；MySQL `ascii_bin` | 创建意图内部幂等身份，逐字节区分大小写 |
| succeeded_at | DATETIME | nullable | 可信 Provider 成功时间 |
| created_at / updated_at | DATETIME | - | 技术时间 |

真实 Provider 当前关闭，运行时不会创建充值单；该表仅建立未来可信支付的结构边界。

### 3.13 payments（支付记录，M4 离线迁移未应用）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | Payment ID |
| payment_no | VARCHAR(28) | NOT NULL, UNIQUE | `PY` + 26 位 Crockford Base32 ULID |
| user_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | 付款普通 USER |
| purpose | VARCHAR(32) | NOT NULL | `order` / `recharge` |
| method | VARCHAR(32) | NOT NULL | `wallet` / `wechat` / `manual` |
| amount | DECIMAL(10,2) | NOT NULL | 正金额，订单支付必须等于 Order.total_amount |
| status | VARCHAR(32) | NOT NULL, DEFAULT `pending` | `pending` / `succeeded` / `failed` / `closed` |
| order_id | BIGINT | FK → orders.id, nullable, ON DELETE RESTRICT | Order purpose 关联 |
| recharge_order_id | BIGINT | FK → recharge_orders.id, nullable, ON DELETE RESTRICT | Recharge purpose 关联 |
| idempotency_key | VARCHAR(256) | NOT NULL, UNIQUE；MySQL `ascii_bin` | 支付意图内部幂等身份，逐字节区分大小写 |
| provider_transaction_id | VARCHAR(128) | nullable, UNIQUE | Provider 交易号；当前 wallet/manual 为 NULL |
| succeeded_at | DATETIME | nullable | 成功时间 |
| created_at / updated_at | DATETIME | - | 技术时间 |

purpose 与可空业务外键的组合由 Service 校验；数据库不使用当前跨方言策略之外的 CHECK。

ADMIN+ 代客钱包订单同样写 `purpose=order`、`method=wallet`、`status=succeeded`；其 Payment 幂等身份绑定管理员、目标普通 USER、Item 与 remark，Order/Items、Kit 库存扣减、钱包扣减、Payment/Settlement、直接 Paid 与双审计在一个事务中提交。该能力不增加专用订单或扣款表。

### 3.14 payment_settlements（成功订单结算，M4 离线迁移未应用）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | Settlement ID |
| payment_id | BIGINT | FK → payments.id, NOT NULL, UNIQUE, ON DELETE RESTRICT | 唯一成功 Payment |
| order_id | BIGINT | FK → orders.id, NOT NULL, UNIQUE, ON DELETE RESTRICT | 一个 Order 最多一个成功结算 |
| amount | DECIMAL(10,2) | NOT NULL | 必须与 Payment 和 Order 金额一致 |
| created_at / updated_at | DATETIME | - | 技术时间 |

M4 前经人工入口进入 PAID/COMPLETED 的历史 Order 尚无 Payment/Settlement。正式发布在钱包 backfill 收敛后运行 `legacy_manual_settlement_backfill`：只有唯一 `MARK_ORDER_PAID` Audit 且无矛盾资金事实的冻结范围旧单，才补一条同 User/Order/amount、`purpose=order`、`method=manual`、`status=succeeded` 的 Payment 与唯一 Settlement；成功时间取历史 Audit.created_at。命令默认 preview，apply 强制复用 preview 的 `through_order_id`，不新增或改写 Order/Audit，冲突阻断并人工裁决。

### 3.15 refunds（全额退款，M4 离线迁移未应用）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | Refund ID |
| refund_no | VARCHAR(28) | NOT NULL, UNIQUE | `RF` + 26 位 Crockford Base32 ULID |
| settlement_id | BIGINT | FK → payment_settlements.id, NOT NULL, UNIQUE, ON DELETE RESTRICT | 一个 Settlement 最多一次退款 |
| order_id | BIGINT | FK → orders.id, NOT NULL, UNIQUE, ON DELETE RESTRICT | 一个 Order 最多一次退款 |
| operator_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | 发起退款的 ADMIN+ |
| amount | DECIMAL(10,2) | NOT NULL | 固定等于 Settlement 全额 |
| status | VARCHAR(32) | NOT NULL, DEFAULT `pending` | `pending` / `succeeded` / `failed` |
| inventory_restored | BOOL | NOT NULL, DEFAULT false | 仅 PAID Kit/混合订单成功恢复时 true |
| reason | VARCHAR(256) | NOT NULL | 规范化管理原因 |
| idempotency_key | VARCHAR(256) | NOT NULL, UNIQUE；MySQL `ascii_bin` | 退款意图内部幂等身份，逐字节区分大小写 |
| provider_refund_id | VARCHAR(128) | nullable, UNIQUE | Provider 退款号；当前为 NULL |
| succeeded_at | DATETIME | nullable | 成功时间 |
| created_at / updated_at | DATETIME | - | 技术时间 |

Refund 状态独立于 OrderStatus；成功退款不修改 Paid/Completed。PAID Kit 恢复通过 InventoryTransaction `order_refund_restore` 追溯，COMPLETED 不恢复。

Refund `succeeded` 同时表示对应 wallet Settlement 的退款预留敞口已释放；`pending`、`failed` 或没有 Refund 的可退款 Settlement 仍占用敞口。退款窗口由当前业务规则在查询中使用 UTC 时间计算，不在 Settlement/Refund 表冗余保存动态布尔标记。

### 3.16 store_business_days（门店营业日锁点，M5 离线迁移未应用）

为预约创建与管理员设置单日店休提供“一日一行”的权威状态和共同并发锁点。行按需创建，不是预生成的完整日历；预约创建过但没有单日店休的日期也会保留 `is_closed=false` 行。每周固定店休由 `reservation_settings` 配置，不依赖这里存在一行。

### 3.16.1 reservation_settings（预约日历单例设置，M7 候选）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | 内部标识 |
| singleton_key | BOOL | NOT NULL, DEFAULT true, UNIQUE, CHECK=true | 数据库层保证最多一行 |
| weekly_closed_weekday | VARCHAR(32) | NOT NULL, DEFAULT `monday` | 每周固定店休日 |
| created_at / updated_at | DATETIME(6) | NOT NULL | 创建与更新时间 |

M7 建表并写入默认周一单例；更换固定店休与命中预约的 `store_closed` 批量取消在同一业务事务中提交。M7 尚未应用任何持久数据库，也尚未完成真实 MySQL 0→7 门槛。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 营业日内部 ID |
| business_date | DATE | NOT NULL, UNIQUE | `Asia/Shanghai` 当地营业日期，一日一行 |
| is_closed | BOOLEAN | NOT NULL, DEFAULT FALSE | 是否被管理员设置为自定义店休 |
| created_at / updated_at | DATETIME(6) | NOT NULL | 技术时间；恢复营业更新原行而非删除 |

命名唯一索引 `uidx_store_business_day_date(business_date)` 既兜底日期唯一性，也支持创建营业日并发竞态的精确识别。创建预约、设置店休和恢复营业必须在同一事务中锁定该行。恢复营业只把 `is_closed` 改为 false，不删除行，也不恢复任何历史预约。

### 3.17 reservations（独立体验预约，M5 离线迁移未应用）

Reservation 与 Order/Payment 相互独立，保存一个顾客选择的 ExperienceOption、UTC 排期、完整创建快照和人工确认状态。手机号不写入本表；管理列表/详情读取 User 当前手机号并分别输出掩码/完整值。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | Reservation ID |
| user_id | BIGINT | FK → users.id, NOT NULL, ON DELETE RESTRICT | Owner；历史用户行不得物理删除 |
| business_day_id | BIGINT | FK → store_business_days.id, NOT NULL, ON DELETE RESTRICT | 上海当地预约日期的共同锁点 |
| product_id | BIGINT | FK → products.id, NOT NULL, ON DELETE RESTRICT | 创建时 Experience Product |
| experience_option_id | BIGINT | FK → experience_options.id, NOT NULL, ON DELETE RESTRICT | 创建时具体 Option |
| scheduled_start_at | DATETIME(6) | NOT NULL | 权威 UTC 开始时间 |
| scheduled_end_at | DATETIME(6) | NOT NULL | 权威 UTC 结束时间；必须晚于开始且完整落在当地 11:00–20:00 |
| product_name | VARCHAR(100) | NOT NULL | 创建时 Product 名称快照 |
| option_duration_minutes | INT | NOT NULL | 创建时 Option 时长快照 |
| option_participants | INT | NOT NULL | 创建时 Option 人数快照 |
| option_day_type | VARCHAR(20) | NOT NULL | 创建时 `weekday` / `holiday` 快照 |
| option_price | DECIMAL(10,2) | NOT NULL | 创建时价格快照 |
| status | VARCHAR(32) | NOT NULL, DEFAULT `pending` | `pending` / `confirmed` / `rejected` / `cancelled` |
| rejection_reason | VARCHAR(32) | nullable | 仅 rejected 为 `no_capacity` |
| cancellation_reason | VARCHAR(32) | nullable | 仅 cancelled 为 `customer_request` / `store_closed` |
| confirmed_at | DATETIME(6) | nullable | 首次确认 UTC 时间；confirmed 后因顾客/店休取消仍保留 |
| rejected_at | DATETIME(6) | nullable | 拒绝 UTC 时间 |
| cancelled_at | DATETIME(6) | nullable | 顾客或店休取消 UTC 时间 |
| created_at / updated_at | DATETIME(6) | NOT NULL | 技术时间 |

完整 Option 快照是有意的反规范化：Product/Option 后续改名、改价、下架或逻辑删除不能覆盖历史预约和到店价格。四个业务外键全部 `RESTRICT`，但历史展示不依赖当前 Product/Option 内容。

N1 刻意不建立 `(user_id, experience_option_id, scheduled_start_at)` 或任何“时段容量”唯一约束。同一用户/Option/时段允许存在多条独立 Reservation，系统不据此占座或自动判满；每条记录均由门店人工确认或以 `no_capacity` 拒绝。创建结果未知时防止误重复由客户端先查列表收敛，而不是把业务允许的重复预约错误压成数据库唯一性。

数据库不独立表达以下跨字段规则，必须由 Reservation Service/Validator 在锁内维护：

- 上海时区、周一固定店休、今天到第 30 日、开始前至少 3 小时、半小时粒度和完整落在 11:00–20:00；
- 周二至周五 `weekday`、周末 `holiday` 的 Option 日期类型匹配；
- pending/confirmed/rejected/cancelled 的原因与三个状态时间组合；
- 管理员开始后不可确认/拒绝，顾客取消截止时间和店休批量取消范围；
- `store_business_days.is_closed` 与新建 Reservation 的并发互斥。

M5 仅建表和索引，没有历史数据回填。它已离线生成，并于 2026-09-06 在一次性 MySQL 8.0.46 专用 Schema 真实完成 0→5、并发关店/创建、事务回滚、1205/1213 重试与六个索引查询计划验证；Reservation 专项 `7 passed`，与 Inventory 联合门槛 `16 passed`。该验证实例已销毁，M5 尚未应用到本地持久 SQLite、Gate A、共享、预发布或生产数据库。

---

## 4. 关系总览

| 关系 | 类型 | 说明 |
|------|------|------|
| users → orders | 一对多 | 一个用户可以有多个订单 |
| orders → order_items | 一对多 | 一个订单包含多个商品明细 |
| order_items → products | 多对一 | 每个明细关联一个商品 |
| order_items → experience_options | 多对一 | 体验订单关联具体配置（套装为 NULL） |
| order_items → product_kit_colors | 多对一（可空） | 自选颜色行保存商品颜色 FK 与独立快照；其他行为空 |
| products → experience_options | 一对多 | 一个体验商品包含多个可选配置 |
| products → product_kits | 一对一 | 套装商品的扩展信息 |
| bead_colors → product_kit_colors | 一对多 | 全局颜色身份可供多个商品引用，但不共享商品库存 |
| products → product_kit_colors | 一对多 | 每个自选颜色 Kit 恰好关联 221 个槽 |
| products → product_images | 一对多 | 一个商品有多张图片 |
| products → inventory_transactions | 一对多 | 一个 Kit Product 可以有多条不可变库存流水 |
| product_kit_colors → inventory_transactions | 一对多（可空） | 颜色流水指向精确余额行；fixed 流水为空 |
| users → inventory_transactions | 一对多（可空） | 用户可作为流水触发者；迁移/系统事件允许无用户 |
| users → wallet_accounts | 一对一（仅 USER） | NORMAL/DISABLED 普通客户应有一个权威钱包；历史 DELETED 可无，ADMIN/SUPER_ADMIN 不建 |
| wallet_accounts → wallet_transactions | 一对多 | 一个钱包有多条不可变资金流水 |
| users / wallet_accounts → recharge_orders | 一对多 | 普通客户为自己的钱包创建充值意图 |
| users → payments | 一对多 | 用户的订单或充值支付记录 |
| orders / recharge_orders → payments | 一对多（可空分支） | Payment purpose 决定且仅决定一个业务归属 |
| orders / payments → payment_settlements | 一对一 | 一个订单最多一个成功 Payment 结算 |
| orders / payment_settlements → refunds | 一对一 | v1 一个订单/结算最多一次全额退款 |
| users → refunds | 一对多 | ADMIN+ 作为退款操作者 |
| users → reservations | 一对多 | 普通用户拥有独立预约；手机号不快照 |
| store_business_days → reservations | 一对多 | 一日锁点关联该日全部预约 |
| products → reservations | 一对多 | 保存创建时 Product 外键并同时保留名称快照 |
| experience_options → reservations | 一对多 | 保存创建时 Option 外键并同时保留完整配置/价格快照 |

**外键约束：** Product 子表指向 `products` 的 FK 使用 `ON DELETE RESTRICT`，防止绕过业务层物理删除。`product_images.experience_option_id` 是明确例外，使用 `ON DELETE SET NULL`；正常业务仍只逻辑删除 Option，该策略仅作为异常物理删除时的数据库兜底。颜色目录、商品颜色、订单、Inventory、Wallet、Payment、Settlement、Refund 与 Reservation 的历史 FK 全部使用 `ON DELETE RESTRICT` 保存追溯链。Inventory/Wallet 的 `source_id` 是通用来源标识，不建立多态外键。

---

## 5. 字段规范

### 公共字段

| 规范 | 说明 |
|------|------|
| 所有主键 | `id BIGINT AUTO_INCREMENT` |
| 所有时间 | `created_at` / `updated_at` |
| 所有金额 | `DECIMAL(10,2)`，单位：元 |
| 状态/类型字段 | 按模块权威设计：User / Order 使用 `SMALLINT`；Product（含 `KitKind`）、Inventory、Wallet、Payment、RechargeOrder、Refund 与 Reservation 使用容量明确的 VARCHAR 字符串 Enum |
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
| 时间字段 | `xxx_at` | `created_at`、`updated_at`、`scheduled_start_at` |

---

## 6. 数据库范式

当前设计满足：

| 范式 | 说明 | 实现方式 |
|------|------|----------|
| 1NF | 字段原子性 | 所有字段不可再分 |
| 2NF | 消除部分依赖 | 主键均为单字段 `id` |
| 3NF | 消除传递依赖 | 体验/套装信息通过外键关联，不冗余 |

**反规范化例外**：`order_items` 的 Product/Option/颜色/销售单位字段与 `reservations` 的 `product_name`、Option 配置和价格均为快照字段，故意冗余以保证历史订单/预约不被当前商品数据覆盖。这是可接受且有意识的反规范化设计。`order_items.total_weight_grams` 可由销售单位与数量推导，因而不存储；手机号不属于履约快照，不在 Reservation 中复制。

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

#### external_identities

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE provider=? AND app_id=? AND subject_id=?` | 极高（外部登录） | `uidx_external_identity_subject` |
| 2 | `WHERE provider=? AND union_id=?` | 中（绑定冲突） | `uidx_external_identity_union` |
| 3 | `WHERE user_id=? AND provider=?` | 中（摘要/解绑） | `idx_external_identity_user_provider` |

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

#### bead_colors / product_kit_colors（M6）

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | 按 `slot_no` 校验/装载完整 221 槽目录 | 高（自选商品创建） | `UNIQUE(slot_no)` |
| 2 | 按非空 `color_code` 校验业务编码唯一 | 中（颜色维护） | `UNIQUE(color_code)` |
| 3 | 活跃颜色按 `sort, slot_no` 稳定分页 | 中（管理目录） | `(is_active, sort, slot_no)` |
| 4 | 按商品装载启用颜色 | 高（详情/上架/下单） | `(product_id, is_enabled)`；联合唯一也覆盖 product_id 前缀 |
| 5 | 检查颜色是否被 Online 商品使用 | 中（全局颜色维护） | `(bead_color_id, is_enabled)` |

`product_kit_colors` 的 `UNIQUE(product_id, bead_color_id)` 是商品/颜色身份兜底；两个普通索引分别优化商品聚合装载与全局颜色引用保护。`is_enabled`、`is_active` 单独选择性低，不建立单列索引。

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
| 2 | `WHERE product_name LIKE '%keyword%'` 子查询订单 ID | 低至中（管理端按历史商品名查订单） | 暂无可移植 B-Tree 索引；保留现有索引并按下述方式约束 |

```sql
-- Migration SQL
CREATE INDEX idx_order_items_order_id ON order_items (order_id, id);
```

管理端商品名查询必须使用 `order_items.product_name` 快照，并以订单 ID 子查询过滤外层 `orders`，不能直接 JOIN 后再分页，否则多条 Item 命中会放大 `total`、`pages` 或 `item_count`。包含匹配前导 `%` 无法利用普通 B-Tree；MySQL FULLTEXT 对中文分词还需要额外 ngram 设计，SQLite 则需独立 FTS 方案，两者不能由当前跨数据库 Model 索引安全表达。因此本阶段不增加无效的 `product_name` 普通索引，也不产生迁移；该 ADMIN-only 查询限制关键词为 1 至 100 字符并继续数据库分页。数据规模或查询频率增长后，应基于生产 MySQL `EXPLAIN` 和实际中文关键词分布决定是否引入专用搜索索引，而不是预建无法命中的索引。

#### inventory_transactions

| # | 查询 | 频率 | 索引 |
|---|------|------|------|
| 1 | `WHERE idempotency_key = ?` | 极高（写入前幂等判断与并发兜底） | `UNIQUE(idempotency_key)` |
| 2 | `WHERE product_id = ? ORDER BY created_at DESC, id DESC` | 高（单 Kit 流水） | `(product_id, created_at, id)` |
| 3 | `WHERE kit_color_id = ? ORDER BY created_at DESC, id DESC` | 高（单商品颜色流水） | `(kit_color_id, created_at, id)` |
| 4 | `WHERE source_type = ? AND source_id = ? ORDER BY created_at DESC, id DESC` | 中（Order 来源追溯） | `(source_type, source_id, created_at, id)` |
| 5 | `WHERE transaction_type = ? ORDER BY created_at DESC, id DESC` | 中（类型筛选） | `(transaction_type, created_at, id)` |
| 6 | `ORDER BY created_at DESC, id DESC` / 创建时间范围 | 中（全局流水） | `(created_at, id)` |

```sql
CREATE UNIQUE INDEX uidx_inventory_idempotency_key ON inventory_transactions (idempotency_key);
CREATE INDEX idx_inventory_product_created_id ON inventory_transactions (product_id, created_at, id);
CREATE INDEX idx_inventory_color_created_id ON inventory_transactions (kit_color_id, created_at, id);
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

#### wallet_transactions

| # | 查询 | 索引 |
|---|------|------|
| 1 | `WHERE idempotency_key = ?` | `UNIQUE(idempotency_key)` |
| 2 | `WHERE wallet_account_id = ? ORDER BY created_at DESC, id DESC` | `(wallet_account_id, created_at, id)` |
| 3 | `WHERE source_type = ? AND source_id = ? ORDER BY created_at DESC, id DESC` | `(source_type, source_id, created_at, id)` |
| 4 | `WHERE transaction_type = ? ORDER BY created_at DESC, id DESC` | `(transaction_type, created_at, id)` |
| 5 | 全局稳定分页 | `(created_at, id)` |

#### recharge_orders

| # | 查询 | 索引 |
|---|------|------|
| 1 | `WHERE idempotency_key = ?` | `UNIQUE(idempotency_key)` |
| 2 | 用户充值单稳定分页 | `(user_id, created_at, id)` |
| 3 | 按状态扫描未完成充值 | `(status, created_at, id)` |

#### payments

| # | 查询 | 索引 |
|---|------|------|
| 1 | 幂等支付意图 | `UNIQUE(idempotency_key)` |
| 2 | Provider 通知定位 | `UNIQUE(provider_transaction_id)` |
| 3 | 用户支付稳定分页 | `(user_id, created_at, id)` |
| 4 | 订单支付追溯 | `(order_id, created_at, id)` |
| 5 | 充值支付追溯 | `(recharge_order_id, created_at, id)` |
| 6 | 按状态扫描未完成支付 | `(status, created_at, id)` |

#### refunds

| # | 查询 | 索引 |
|---|------|------|
| 1 | 幂等退款意图 | `UNIQUE(idempotency_key)` |
| 2 | Provider 退款通知定位 | `UNIQUE(provider_refund_id)` |
| 3 | 订单退款追溯 | `(order_id, created_at, id)` |
| 4 | 按状态扫描未完成退款 | `(status, created_at, id)` |

`wallet_accounts.user_id`、`payment_settlements.payment_id/order_id` 与 `refunds.order_id/settlement_id` 已由 UNIQUE 约束提供索引，不重复创建普通索引。

#### store_business_days

| # | 查询 | 索引 |
|---|------|------|
| 1 | `WHERE business_date = ?`（创建/店休/恢复共同锁点） | `UNIQUE(business_date)` |
| 2 | 日期范围内查询自定义店休日 | 当前使用日期唯一索引做范围扫描；`is_closed` 低基数且列表规模有限，M5 不增加冗余索引 |

#### reservations

| # | 查询 | 索引 |
|---|------|------|
| 1 | `WHERE user_id=? ORDER BY scheduled_start_at DESC, id DESC` | `(user_id, scheduled_start_at, id)` |
| 2 | 用户按状态筛选并按开始时间稳定分页 | `(user_id, status, scheduled_start_at, id)` |
| 3 | 注销阻断：`WHERE user_id=? AND status IN (...) AND scheduled_end_at>?` | `(user_id, status, scheduled_end_at, id)` |
| 4 | 店休批量取消：按营业日、活跃状态、开始时间筛选并锁定 | `(business_day_id, status, scheduled_start_at, id)` |
| 5 | 管理端按状态分页和开始时间排序 | `(status, scheduled_start_at, id)` |

管理端只按 `business_date` 筛选时先通过 `store_business_days.business_date` 唯一索引联表到 Reservation；`user_id` / `product_id` 可选组合的实际执行计划必须在真实 MySQL 数据量下复核。M5 不为每一种可选组合预建索引，避免写放大和无依据冗余。

### 7.3 索引汇总

| 表 | 索引名 | 列 | 类型 | 覆盖查询 |
|----|--------|-----|------|----------|
| `users` | `idx_users_status_role` | `(status, role)` | 普通 | 管理后台用户列表 |
| `external_identities` | `uidx_external_identity_subject` | `(provider, app_id, subject_id)` | UNIQUE | 外部身份登录与绑定唯一性 |
| `external_identities` | `uidx_external_identity_union` | `(provider, union_id)` | UNIQUE | 可选 UnionID 冲突兜底 |
| `external_identities` | `idx_external_identity_user_provider` | `(user_id, provider, created_at)` | 普通 | 用户绑定摘要与解绑 |
| `products` | `idx_products_status_deleted` | `(status, is_deleted)` | 普通 | 客户列表、管理后台列表 |
| `experience_options` | `idx_option_unique` | `(product_id, duration, participants, day_type)` | UNIQUE | 全历史唯一、创建/恢复校验、按 product 查询 |
| `bead_colors` | `uidx_bead_colors_slot_no` | `(slot_no)` | UNIQUE | 221 个稳定槽身份 |
| `bead_colors` | `uidx_bead_colors_color_code` | `(color_code)` | UNIQUE | 非空业务编码全局唯一 |
| `bead_colors` | `idx_bead_colors_active_sort_slot` | `(is_active, sort, slot_no)` | 普通 | 活跃过滤与稳定目录排序 |
| `product_kit_colors` | `uidx_product_kit_colors_product_color` | `(product_id, bead_color_id)` | UNIQUE | 商品与颜色身份唯一 |
| `product_kit_colors` | `idx_product_kit_colors_product_enabled` | `(product_id, is_enabled)` | 普通 | 商品颜色聚合与启用过滤 |
| `product_kit_colors` | `idx_product_kit_colors_color_enabled` | `(bead_color_id, is_enabled)` | 普通 | 全局颜色 Online 引用保护 |
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
| `inventory_transactions` | `idx_inventory_color_created_id` | `(kit_color_id, created_at, id)` | 普通 | 单商品颜色流水稳定分页 |
| `inventory_transactions` | `idx_inventory_source_created_id` | `(source_type, source_id, created_at, id)` | 普通 | Order 来源追溯 |
| `inventory_transactions` | `idx_inventory_type_created_id` | `(transaction_type, created_at, id)` | 普通 | 类型筛选稳定分页 |
| `inventory_transactions` | `idx_inventory_created_id` | `(created_at, id)` | 普通 | 全局流水与时间范围 |
| `wallet_transactions` | `uidx_wallet_transaction_idempotency` | `(idempotency_key)` | UNIQUE | 资金事件幂等兜底 |
| `wallet_transactions` | `idx_wallet_transaction_wallet_created_id` | `(wallet_account_id, created_at, id)` | 普通 | 用户钱包流水 |
| `wallet_transactions` | `idx_wallet_transaction_source_created_id` | `(source_type, source_id, created_at, id)` | 普通 | 业务来源追溯 |
| `wallet_transactions` | `idx_wallet_transaction_type_created_id` | `(transaction_type, created_at, id)` | 普通 | 类型筛选 |
| `wallet_transactions` | `idx_wallet_transaction_created_id` | `(created_at, id)` | 普通 | 全局稳定分页 |
| `recharge_orders` | `uidx_recharge_order_idempotency` | `(idempotency_key)` | UNIQUE | 充值创建幂等 |
| `recharge_orders` | `idx_recharge_order_user_created_id` | `(user_id, created_at, id)` | 普通 | 用户充值单 |
| `recharge_orders` | `idx_recharge_order_status_created_id` | `(status, created_at, id)` | 普通 | 未完成状态扫描 |
| `payments` | `uidx_payment_idempotency` | `(idempotency_key)` | UNIQUE | 支付意图幂等 |
| `payments` | `uidx_payment_provider_transaction` | `(provider_transaction_id)` | UNIQUE | Provider 交易号定位 |
| `payments` | `idx_payment_user_created_id` | `(user_id, created_at, id)` | 普通 | 用户支付历史 |
| `payments` | `idx_payment_order_created_id` | `(order_id, created_at, id)` | 普通 | 订单支付追溯 |
| `payments` | `idx_payment_recharge_created_id` | `(recharge_order_id, created_at, id)` | 普通 | 充值支付追溯 |
| `payments` | `idx_payment_status_created_id` | `(status, created_at, id)` | 普通 | 未完成状态扫描 |
| `refunds` | `uidx_refund_idempotency` | `(idempotency_key)` | UNIQUE | 退款意图幂等 |
| `refunds` | `uidx_refund_provider_reference` | `(provider_refund_id)` | UNIQUE | Provider 退款号定位 |
| `refunds` | `idx_refund_order_created_id` | `(order_id, created_at, id)` | 普通 | 订单退款追溯 |
| `refunds` | `idx_refund_status_created_id` | `(status, created_at, id)` | 普通 | 未完成状态扫描 |
| `store_business_days` | `uidx_store_business_day_date` | `(business_date)` | UNIQUE | 一日一行、创建/店休/恢复锁点 |
| `reservations` | `idx_reservations_user_start_id` | `(user_id, scheduled_start_at, id)` | 普通 | 用户预约稳定分页 |
| `reservations` | `idx_reservations_user_status_start_id` | `(user_id, status, scheduled_start_at, id)` | 普通 | 用户按状态筛选与稳定分页 |
| `reservations` | `idx_reservations_user_status_end_id` | `(user_id, status, scheduled_end_at, id)` | 普通 | 活跃预约注销阻断 |
| `reservations` | `idx_reservations_day_status_start_id` | `(business_day_id, status, scheduled_start_at, id)` | 普通 | 店休批量取消 |
| `reservations` | `idx_reservations_status_start_id` | `(status, scheduled_start_at, id)` | 普通 | 管理端状态筛选与分页 |
| `audit_logs` | `idx_audit_target_created` | `(target_type, target_id, created_at)` | 普通 | 实体审计追踪 |
| `audit_logs` | `idx_audit_operator_created` | `(operator_id, created_at)` | 普通 | 操作人行为审计 |

### 7.4 不需要索引的表

| 表 | 原因 |
|----|------|
| `product_kits` | 仅通过 `product_id`（已有 UNIQUE 约束及其索引）查询，无需额外索引 |
| `wallet_accounts` | 仅通过 `user_id`（已有 UNIQUE 约束及其索引）锁定/查询 |
| `payment_settlements` | `payment_id`、`order_id` 均已有 UNIQUE 约束及其索引 |

---

## 8. 后续扩展计划

M6 自选颜色 Kit 的仓库实现、离线迁移候选与本地定向/全量验证已经完成，真实 MySQL 0→6 验证仍待执行；本章描述已冻结目标结构，不代表迁移已应用到本地持久、共享、预发布或生产数据库。历史 Kit 必须保持 `fixed` 默认值与原库存语义。

| 版本 | 新增内容 |
|------|----------|
| v0.2 | 收藏表、评价表（Wallet/Payment/Refund 表已由 M4 仓库实现） |
| v0.3 | AI 推荐记录、AI 生成模板表 |
| v1.0 | 真实微信 Provider 通知/对账扩展、后台操作日志（微信身份表已由 Phase 9.5 实现；Reservation N2 主动店休通知仍为 Deferred） |
