# Product Module Business Rules

> **Document Version:** v1.6
> **Module:** Product
> **Phase:** 4.1 Product Module
> **Last Updated:** 2026-08-10
>
> 本文档定义 Product 模块的业务规则。所有数据库设计、API 设计、Service 实现均应遵循本规则。业务变化时优先修改本文档，再调整代码。
>
> 模块需求概要见 [product_module.md](./product_module.md)。

---

## 1. Domain Model

核心原则：**UI ≠ 数据模型**。用户在前端看到的是一个商品（如"拼豆体验"），在详情页选择时长、人数、日期类型后看到对应价格。但数据库层面，这是两张表：

```
Product（商品） 1 ──→ N ExperienceOption（体验配置）
```

### 1.1 Experience Product（拼豆体验）

拼豆体验在系统中只有**一个** Product 记录。用户看到的时长、人数、日期类型选择，实际来自其关联的 ExperienceOption 集合。

> **重要：** ExperienceOption **不是**商品。它表示一个体验商品的可选配置。例如「1 小时 + 2 人 + 工作日 = 299 元」是一条 Option，不是一个独立商品。

**Product 表存储：**

| 字段 | 示例值 |
|------|--------|
| name | 拼豆体验 |
| type | experience |
| description | 选择你的拼豆体验… |
| status | online |

**ExperienceOption 表存储：**

| product_id | duration | participants | day_type | price |
|------------|----------|-------------|----------|-------|
| 1 | 60 | 1 | weekday | 299 |
| 1 | 60 | 2 | weekday | 399 |
| 1 | 120 | 1 | weekday | 499 |
| 1 | 120 | 2 | holiday | 699 |
| … | … | … | … | … |

**API 返回示例：**

```json
GET /products/1

{
  "name": "拼豆体验",
  "description": "...",
  "options": [
    { "duration": { "value": 60, "label": "1小时" }, "participants": { "value": 1, "label": "1人" }, "day_type": { "value": "weekday", "label": "工作日" }, "price": 299 },
    { "duration": { "value": 60, "label": "1小时" }, "participants": { "value": 2, "label": "2人" }, "day_type": { "value": "weekday", "label": "工作日" }, "price": 399 }
  ]
}
```

前端根据 `options` 自动生成选择控件，用户选完后匹配对应价格。

**未来扩展：** 新增 3 人配置只需创建一条 ExperienceOption；如果相同组合曾被逻辑删除，则恢复原记录。无需重建其他组合。

**当前阶段不考虑：** 多种体验主题、预约日期 / 时间段、包场模式。

### 1.2 Kit Product（拼豆套装）

套装商品为固定内容商品，一个 Product 对应一个固定价格。不需要 Option 表。

| 属性 | 说明 |
|------|------|
| 默认套装 | 1 款 |
| 默认售价 | 599 元 |
| 价格可变 | 允许修改 |
| 数量可变 | 允许创建多个套装 |

**设计约束：** 系统不得假设永远只有一个套装商品。

---

## 2. Design Decisions

> 本节记录架构决策及其原因。未来维护者不仅知道系统怎么设计，还知道为什么这样设计。

### 2.1 为什么 ExperienceOption 不设计成独立 Product？

| 决策 | 原因 |
|------|------|
| 用户认知 | 用户认为「拼豆体验」是一个商品，不同时长/人数只是选项，不是不同商品 |
| 商品列表 | 避免列表出现大量名称相同、仅配置不同的体验商品 |
| 扩展成本 | 新增时长、人数等配置只需创建或恢复一条 ExperienceOption，无需重建全部组合 |
| 前端体验 | 用户在详情页选择配置即可获取对应价格，交互更自然 |

### 2.2 为什么库存不放在 Product 模块？

Phase 4.1 的 Product 模块在 `product_kits.stock` 中保存并展示套装的当前库存，管理员暂时通过“设置最终值”方式维护它。库存扣减、恢复、流水、并发控制等库存**业务流程**属于 Order / Payment / Inventory 模块，不在 Product Service 中提前实现。详见 §10 Inventory Dependency。

### 2.3 为什么 ExperienceOption 不加 status 字段？

| 决策 | 原因 |
|------|------|
| Option 是配置项，不是独立销售对象 | Product 已经承担了上下架职责，Option 不需要再维护一套生命周期 |
| 当前无业务需求 | 不存在「某个配置暂停销售、其他配置继续销售」的场景 |
| 降低复杂度 | 不加 status 意味着 Option 只有 CRUD，没有状态流转逻辑 |

> 如果未来确实出现需要独立上下架某个 Option 的需求，再扩展 Option 的生命周期会更合理。届时可以给 Option 增加 `status` 字段（active / inactive），与 Product 的 `status` 形成双重控制。

---

## 3. Product Basic Rules

### 3.1 Product Name

| 规则 | 值 |
|------|-----|
| 必填 | 是 |
| 最大长度 | 100 字符 |
| 唯一性 | 允许重名 |

### 3.2 Product Type

| 规则 | 说明 |
|------|------|
| 创建后不可修改 | 商品类型决定业务结构（experience 关联 Option 表），修改类型可能导致关联数据失效 |

### 3.3 Product Status

| 状态 | 含义 | 管理员可见 | 普通用户可见 |
|------|------|-----------|-------------|
| `draft` | 编辑中，未发布 | ✅ | ❌ |
| `online` | 已上架，可购买 | ✅ | ✅ |
| `offline` | 已下架 | ✅ | ❌ |

状态流转：

```
draft ──→ online ──→ offline
  ↑                    │
  └────────←───────────┘
        (重新上架)
```

重新上架（`offline → online`）时**保持原 Product ID**，不得创建新商品。后续 API 设计中，上架/下架操作仅变更状态字段，商品标识不变。

**上线前置条件（体验商品）：** `draft → online` 时，体验商品必须至少拥有一个 ExperienceOption。无 Option 的体验商品禁止上线。这是聚合完整性的基本要求——一个没有可选配置的体验商品对用户没有意义。

下架后历史订单保持有效，不受商品状态变更影响。

---

## 4. Pricing Rules

### 4.1 Price Required

所有商品及 ExperienceOption **必须**配置价格，禁止空价格或未配置价格。

### 4.2 Price Range

```
0 < Price ≤ 99999
```

禁止 0 元、负数及超过 99999 元的价格。

### 4.3 Experience Pricing（via Options）

体验商品的价格通过 ExperienceOption 管理。体验商品可以拥有**任意数量**的 ExperienceOption；管理员可在 Product 为 `draft` / `offline` 时新增、修改或删除，`online` 时须先下架。每个 Option 都是一个独立可售配置，包含四个维度：

| 维度 | 说明 |
|------|------|
| 时长（Duration） | 1 Hour / 2 Hours / Full Day |
| 人数（Participants） | 1 Person / 2 Persons |
| 日期类型（Day Type） | Weekday / Holiday |
| 价格 | 该组合的唯一价格 |

商品上线后，前端展示全部有效 Option 供用户选择。管理员需要先将 Product 保持在 `draft` / `offline`，再新增不同时长或不同人数的配置（如新增 3 人、4 小时）；新组合 INSERT 一条记录，已逻辑删除的相同组合则恢复原记录。

### 4.4 Kit Pricing

套装商品为单一价格，存储在 `product_kits.price`。创建后允许修改，但仍遵守 Product 写操作的状态限制：`online` 时须先下架。系统支持创建多个套装 Product，每个 Product 对应一条 ProductKit 并独立定价。

### 4.5 Batch Price Update

支持批量修改 Option 价格。修改后仅影响新创建订单，历史订单保留价格快照。

### 4.6 Price Modification

| 规则 | 说明 |
|------|------|
| 谁可以修改 | 管理员 |
| 何时生效 | 修改后，仅影响新创建订单 |
| 历史订单 | 不受影响，保留创建时的价格快照 |

系统**不得**根据当前价格修改历史订单金额。

---

## 5. Visibility Rules

### 5.1 Normal Users

| 允许 | 禁止 |
|------|------|
| 浏览 `online` 商品 | 浏览 `draft` 商品 |
| 查看商品详情（含 Option 列表） | 浏览 `offline` 商品 |
| 查看商品价格 | — |

### 5.2 Administrators

允许查看全部状态商品（`draft`、`online`、`offline`）及其 Option。

---

## 6. Permission Rules

以下操作**必须**具有管理员权限：

| 操作 | 权限 |
|------|------|
| 创建商品 | ADMIN+ |
| 编辑商品信息 | ADMIN+ |
| 修改价格（Product 或 Option） | ADMIN+ |
| 新增 Option | ADMIN+ |
| 修改 Option | ADMIN+ |
| 删除 Option | ADMIN+ |
| 商品上架（draft → online / offline → online） | ADMIN+ |
| 商品下架（online → offline） | ADMIN+ |
| 删除商品（逻辑删除） | ADMIN+ |

> **说明：** 当前阶段所有管理操作统一要求 `ADMIN` 角色。Phase 3 已实现的 RBAC（`ADMIN` / `SUPER_ADMIN`）可直接复用。后续可根据业务需要将敏感操作（如删除商品）提升至 `SUPER_ADMIN`，无需改动本文档之外的结构。

普通用户不得执行上述任何操作。

---

## 7. Delete Rules

商品删除采用**逻辑删除**（Logical Delete），系统不得执行物理删除。

**原因：**
- 保留历史订单关联
- 保留审计日志完整性
- 保持历史数据可追溯

### 7.1 Business Layer（Service）

Service 层**禁止**执行 `DELETE` 语句。删除操作一律通过状态字段实现逻辑删除：

```
❌ DELETE FROM products WHERE id = 1
✅ UPDATE products SET is_deleted = 1 WHERE id = 1
```

`online` Product 会在更新前被 Service 拒绝；`draft` / `offline` Product 逻辑删除时保持原 `status`，删除动作不隐式制造额外状态流转。

### 7.2 Database Layer（Foreign Key）

直接指向 Product 的关联表（ExperienceOption、ProductKit、ProductImage）的 Foreign Key 必须使用 `ON DELETE RESTRICT`。`ProductImage.experience_option_id` 是明确例外，使用 `ON DELETE SET NULL` 作为 Option 异常物理删除时的兜底：

**原因：** 防止有人绕过业务层直接在数据库执行物理删除，导致关联数据孤立。

### 7.3 Preconditions

`online` 商品必须先下架才能删除。

### 7.4 Post-delete Behavior

- 普通用户不可见
- 管理员仍可查询历史记录
- 已关联的历史订单不受影响

---

## 8. Aggregate Rules（聚合规则）

> Product 与 ExperienceOption 构成一个聚合（Aggregate），Product 为聚合根（Aggregate Root）。聚合规则定义了两者的生命周期关系，是 Service 设计、事务设计、API 设计的核心依据。

### 8.1 Aggregate Boundary（聚合边界）

```
Product（聚合根）
  └── ExperienceOption × N
```

| 问题 | 答案 | 原因 |
|------|------|------|
| Product 可以单独创建吗？ | ✅ 可以 | 利用 `draft` 状态逐步完善商品信息 |
| Draft 可以没有 Option 吗？ | ✅ 可以 | 商品尚未完成编辑 |
| Online 可以没有 Option 吗？ | ❌ 不可以 | 用户必须能选择至少一种配置 |
| 一个 Product 至少需要几个 Option 才能上线？ | ≥ 1 | 保证商品可售 |
| Option 可以单独新增、修改、删除吗？ | ✅ 可以 | 便于后台维护 |
| 删除最后一个 Option 后还能保持 Online 吗？ | ❌ 不可以 | Online 商品不允许删除 Option。须先下架。

### 8.2 Status × Option Completeness Matrix

| 状态 | Option 最小数量 | Option 最大数量 | 说明 |
|------|----------------|----------------|------|
| `draft` | 0 | 不限 | 可先创建空商品，再逐步添加 Option |
| `online` | 1 | 不限 | 上线前必须校验 Option ≥ 1 |
| `offline` | 0 | 不限 | 已下架，Option 数量不限制 |

### 8.3 Lifecycle Rules（生命周期规则）

**创建阶段（Create → Edit → Complete → Publish）：**

```
Step 1  POST /admin/products/experience  → Product (draft)  →  前端跳转编辑页
Step 2  POST .../images                  → 上传 Product 公共图片
Step 3  POST .../options                 → 新增 Option
Step 4  POST .../images                  → 上传 Option 图片（body 带 option_id）
Step 5  PUT  /admin/products/{id}        → 完善描述等信息
Step 6  PATCH .../online                 → Validate → Product (online)
```

**核心原则：Create 只创建主资源。** 创建接口仅负责 Product 主记录（`name` + `description`），不接收任何关联资源（图片、Option、价格）。关联资源通过独立接口逐步添加。

**前端交互：** 创建 Draft 后前端应立即跳转到编辑页（`/admin/products/experience/{id}/edit`），而非返回列表。用户可以分多次、跨会话逐步完善商品，Draft 就是"尚未完成的工作区"。

**维护阶段：**

| 操作 | 前置条件 | 后置处理 |
|------|----------|----------|
| 新增 / 恢复 Option | Product 必须为 draft / offline | 新组合 INSERT；已删除相同组合恢复原 ID |
| 修改 Option | Option 存在且 Product 为 draft / offline | 历史订单不受影响 |
| 删除 Option | Product 必须为 draft / offline | Online 商品不允许删除 Option。删除最后一条 Option 后商品保持原状态（draft/offline），重新上架时 Validator 拒绝 |

**下线阶段：**

```
PUT /products/1/offline  → Product (offline)
  └── 历史订单仍可查询
  └── Option 数据保留
```

### 8.4 Consistency Guarantees（一致性保证）

| 保证 | 实现方式 |
|------|----------|
| 上线前 Option ≥ 1 | Service 传入已预加载聚合，由 Validator 校验；不满足时抛命名异常 |
| 删除最后 Option 后保持原状态 | 仅 `draft` / `offline` 允许删除 Option；重新上架时由 Validator 拒绝空 Option 集合 |
| FK 约束 | `ON DELETE RESTRICT`，数据库层兜底 |
| 事务边界 | 上线、下线、Option 增删均在单次请求内完成，无需跨请求事务 |

### 8.5 Online Validation（上架校验）

`draft → online` 或 `offline → online` 时，Service 不得直接设置 `status = "online"`，必须先通过 `ProductValidator.validate_before_online()` 执行完整性校验。全部通过后才能上架。

`validate_before_online(product) -> None` 是**同步、纯计算**接口：成功时返回 `None`，失败时一次性收集全部缺项并抛出 `ProductNotReadyForOnline`，不返回 bool。Validator 不查询或写入数据库，不调用 Repository、Service、Redis，不开启事务，不校验权限，不写审计日志，也不修改 Product 聚合中的任何对象。

Service 必须使用 `ProductRepository.get_product_detail(product_id, include_deleted=True)` 加载聚合后再调用 Validator；这样才能先区分“不存在”和“已经逻辑删除”，基础查询 `get_product_by_id()` 不满足输入契约。已加载聚合包含：

```text
Product
├── kit
├── 有效 ExperienceOption（is_deleted = false）
├── 有效 Product 公共图片（is_deleted = false 且 experience_option_id IS NULL）
└── 每个有效 Option 的有效专属图片（is_deleted = false）
```

Validator 只读取这些已加载关系。调用方忘记预加载关系而触发 `NoValuesFetched` 等异常属于内部编程错误，必须原样暴露给统一异常处理，不得伪装成 `42201` 业务错误。Product 不存在、已经逻辑删除、已经 Online 等资源或状态冲突仍由 Service 在调用 Validator 前处理。

> **实现状态：** Product Validator 阶段已完成。异常契约、公共规则、Experience/Kit 专属规则、稳定 issues 顺序、未知 ProductType fail-closed，以及真实 Repository 聚合上的零查询与零修改边界均已有自动化测试；Product Service、状态写入、事务、审计和 API 路由不属于本阶段，仍待后续实现。

#### 8.5.1 Service 上架编排契约

Product Service 的上架公开方法冻结为异步编排接口：

```python
async def online_product(
    self,
    product_id: int,
    *,
    operator_id: int,
    ip_address: str,
) -> Product:
    ...
```

`operator_id` 和 `ip_address` 仅用于成功操作的审计上下文；ADMIN+ 身份认证由 API 权限依赖完成，Validator 不接收操作者信息。Service 返回已经更新为 `ProductStatus.ONLINE` 的 Product Model，API 负责通过 `ProductOnlineOut` 生成公开响应，不返回完整详情，也不由 Service 构造 `{code, message, data}` 信封。

执行顺序必须固定为：

1. `ProductRepository.get_product_detail(product_id, include_deleted=True)` 加载完整聚合；返回 `None` 时抛 `ProductNotFound`（`40401`, `Product not found`）。
2. `is_deleted = true` 时抛 `ProductIsDeleted`（`40903`, `Product is deleted`）。删除状态优先于当前 ProductStatus 判断。
3. `status = online` 时抛 `ProductAlreadyOnline`（`40901`, `Product is already online`）。
4. 同步调用 `ProductValidator.validate_before_online(product)`；`42201`、未预加载关系和未知 ProductType 等异常原样传播，不捕获或改写。
5. 校验通过后开启事务，通过 `ProductRepository.update_product(..., status=ProductStatus.ONLINE, using_db=connection)` 更新状态。
6. 在同一事务连接上通过 `AuditLogService.log(..., action="ONLINE_PRODUCT", target_type="product", target_id=product.id, using_db=connection)` 写审计；状态更新或审计任一失败时，两者全部回滚。
7. 事务提交后返回更新后的 Product；校验和所有前置冲突均发生在写事务前，不写状态、不写审计。

为支持步骤 6，现有共享审计边界必须向后兼容地增加可选 `using_db: BaseDBAsyncClient | None = None`，由 `AuditLogService.log()` 透传给 `AuditLogRepository.create()` 和 `AuditLog.create(using_db=...)`。不提供时保持现有用户模块的顺序审计行为；Product 上架必须提供当前事务连接。Product Service 通过构造函数接收 `ProductRepository` 和 `AuditLogService`，不得在方法内部实例化 Repository，也不得直接操作 Product 或 AuditLog Model。

本阶段不增加行锁、条件更新或跨请求幂等键；两个并发上架请求仍可能都通过事务前状态检查，属于后续并发策略需要处理的已知限制。单次请求内的状态与审计原子性是本阶段强制契约。

**校验流程：**

```
管理员点击上架
  │
  ▼
ProductValidator.validate_before_online(product)  # 同步调用，不使用 await
  │
  ├─ product_type = "experience" → _collect_experience_issues()
  ├─ product_type = "kit"        → _collect_kit_issues()
  └─ 未知 ProductType             → 抛内部编程错误，fail-closed
  │
  ▼
全部通过 → 返回 None，Service 才可进入状态更新事务
存在缺项 → 一次抛出全部 issues，阻止上架
```

**失败契约：**

- HTTP status：`422`
- response `code`：`42201`
- response `message`：精确为 `Product is not ready to go online`
- response `data`：精确为 `{ "issues": [...] }`
- `issues`：非空数组；每一项都是下表规定的非空英文字符串，并按下表顺序稳定返回

该 HTTP 语义由通用 `UnprocessableEntityException` 表达；Product 命名异常 `ProductNotReadyForOnline` 继承它并固定上述业务错误码、消息与数据结构。异常中间件不得根据 `42201` 的数字范围推断 HTTP 状态。

**公共检查项（所有 ProductType）：**

| 顺序 | 不通过条件 | `issue` 精确值 |
|------|------------|----------------|
| 1 | `name` 为 `None`、空字符串或纯空白 | `product name is required` |
| 2 | `description` 为 `None`、空字符串或纯空白 | `product description is required` |
| 3 | 没有有效 Product 公共封面图 | `product cover image is required` |

名称与描述使用 `value is None or not value.strip()` 判断。公共封面必须同时满足 `is_deleted = false`、`experience_option_id IS NULL` 和 `is_cover = true`；Option 专属图片不能作为公共封面回退。

**Experience 上架检查项：**

公共检查项之后按以下顺序继续收集：

| 顺序 | 不通过条件 | `issue` 精确值 |
|------|------------|----------------|
| 4 | 没有有效 Product 公共图片 | `at least one product image is required` |
| 5 | 没有有效 ExperienceOption | `at least one experience option is required` |
| 6 | 某个有效 Option 的 `price <= 0` | `option {id} price must be greater than 0` |
| 7 | 某个有效 Option 没有有效专属图片 | `option {id} has no image` |

有效 Option 按 Repository 已固定的 `duration ASC, participants ASC, day_type ASC, id ASC` 顺序检查；同一 Option 先追加价格 issue，再追加图片 issue。没有有效 Option 时只追加顺序 5，不产生任何 Option 级 issue。公共封面同时算作公共图片，因此完全没有公共图片时会依次返回 `product cover image is required` 和 `at least one product image is required`。

Option 配置唯一性不属于本 Validator 的 `42201`：创建/修改 Option 时由 Service 返回 `40911`，数据库全历史唯一索引 `(product_id, duration, participants, day_type)` 负责最终兜底，Validator 不重复扫描组合。

**图片两层结构：**

```
product_images
├── experience_option_id = NULL   → Product 公共图片（列表封面、默认展示）
└── experience_option_id = 11     → Option 11 专属图片（选中配置后展示）
```

| 规则 | 说明 |
|------|------|
| 封面归属 | 仅 Product 公共图片参与 `is_cover`，Option 图片 `is_cover` 恒为 false |
| Option 默认图 | `sort ASC, id ASC` 第一张 |
| Option 无图片 | 返回 `[]`，前端展示占位图；**不**回退到 Product 公共图片 |
| 逻辑删除 Option | 关联图片保持不动，随已删除 Option 从正常查询中隐藏；恢复 Option 时重新可见 |
| 异常物理删除 Option | FK 的 `ON DELETE SET NULL` 将关联图片归入 Product 公共图片，仅作数据库兜底 |

**Kit 上架检查项：**

公共检查项之后按以下顺序继续收集：

| 顺序 | 不通过条件 | `issue` 精确值 |
|------|------------|----------------|
| 4 | 缺少 ProductKit 扩展记录 | `kit configuration is required` |
| 5 | `price <= 0` 或 `price > 99999` | `kit price must be greater than 0 and no more than 99999` |
| 6 | `stock < 0` | `kit stock must be non-negative` |

如果 ProductKit 扩展记录缺失，只追加 `kit configuration is required`，不再追加价格或库存 issue；记录不存在与字段值非法不是同一问题。`stock = 0` 允许上架。Kit 的图片完整性目前只有公共封面规则，不额外要求第二项“至少一张公共图片”。

**设计原则：** `draft` 状态允许不完整（逐步完善），`online` 状态必须完整（校验通过）。这是聚合完整性的最终体现。

---

## 9. Data Consistency Rules

### 9.1 Experience Option Uniqueness

同一体验商品内，每个 Option 的配置组合在**全历史范围内**必须唯一。唯一键为：

```
product_id + Duration + Participants + Day Type
```

| 场景 | 结果 |
|------|------|
| 商品 1：工作日 + 2h + 2 人 = 1 条 Option | ✅ 允许 |
| 商品 1：工作日 + 2h + 2 人 = 2 条 Option | ❌ 禁止 |

**原因：** 同一配置出现两条记录时，系统无法确定应使用哪个价格。

唯一约束不包含 `is_deleted`。每个配置组合在 `experience_options` 中最多只有一条记录：

- 相同组合不存在：创建新 Option。
- 相同组合存在且 `is_deleted = false`：拒绝为重复配置。
- 相同组合存在且 `is_deleted = true`：恢复原记录，保持原 Option ID，更新本次提交的价格并设为 `is_deleted = false`。

恢复时保留原有图片关联；不再需要的图片由图片删除接口单独逻辑删除。历史订单依赖订单项快照，审计历史依赖 Audit Log，因此无需为每次删除/恢复复制一条 Option 版本记录，也不得为了腾出唯一键而物理删除可能已被引用的旧 Option。

### 9.2 Price Snapshot

- 订单创建时快照当前 Option 价格
- 快照价格与 Option 当前价格解耦
- Option 价格变更不影响已有订单

---

## 10. Inventory Dependency

拼豆体验不涉及库存。

拼豆套装在 **Phase 4.1** 即使用 `product_kits.stock` 保存当前库存，支持管理端直接设置最终值，并在用户详情中派生 `available = stock > 0`。这一阶段不引入库存流水，也不在 Product Service 中实现订单驱动的扣减或恢复。

完整库存业务将在 **Inventory 模块（Phase 4.3）** 中实现：

| 库存操作 | 所属模块 | 触发时机 |
|----------|----------|----------|
| 当前库存最终值设置 | Product（Phase 4.1） | 管理员维护套装时 |
| 库存扣减 | Order / Payment + Inventory | 支付成功后 |
| 库存恢复 | Order + Inventory | 订单取消时 |
| 库存不足拒绝 | Order + Inventory | 下单 / 支付确认时 |
| 库存流水与调整原因 | Inventory | Phase 4.3 |

Product 模块只负责当前库存值的保存、展示和管理端直接设置，不负责扣减、恢复、流水及并发库存控制。

---

## 11. Lifecycle Summary（生命周期总览）

| 实体 | 生命周期 | 所属 Phase |
|------|----------|------------|
| Product（体验/套装） | Draft → Online → Offline → 逻辑删除 | Phase 4.1 |
| ExperienceOption | 创建 / 恢复 → 修改 → 逻辑删除（无独立状态，跟随 Product） | Phase 4.1 |
| Kit Product | 与 Product 相同，共用 Product 生命周期 | Phase 4.1 |
| Order | 待后续 Phase 4.2 设计 | Phase 4.2 |
| Kit 当前库存值 | 创建 → 管理员直接设置 → 展示 | Phase 4.1 |
| Inventory 流水与自动变更 | 待后续 Phase 4.3 设计 | Phase 4.3 |

> **关于 ExperienceOption 的 status：** 当前不设独立状态。Option 仅作为 Product 的配置项存在，Product 的状态（draft/online/offline）已覆盖了"该配置是否对用户可见"的需求。如需独立控制某个 Option 的可见性，后续再扩展。

---

## 12. Business Constraints（汇总）

### Status Constraints

| 规则 | 说明 |
|------|------|
| Draft 商品允许编辑 | ✅ |
| Online 商品允许编辑 | ✅ |
| Offline 商品允许编辑 | ✅ |
| Online 商品必须先下架才能删除 | 下架 → 删除 |
| 重新上架保持原 Product ID | 不创建新商品 |
| 删除采用逻辑删除 | 禁止物理删除 |

### Price Constraints

| 规则 | 说明 |
|------|------|
| 商品价格必须 > 0 | 禁止 0 元及负数 |
| 商品价格最大 99999 | 元 |
| 支持批量修改价格 | — |
| 修改价格仅影响未来订单 | — |
| 历史订单保存价格快照 | 与商品当前价格解耦 |

### Experience Constraints

| 规则 | 说明 |
|------|------|
| 数据模型 | Product 1 → N ExperienceOption |
| 每个 Option 必含维度 | 时长 + 人数 + 日期类型 + 价格 |
| 唯一约束 | 同一 Product 内 (时长 + 人数 + 日期类型) 全历史唯一，不区分 `is_deleted` |
| Draft 允许无 Option | 先创建商品，再逐步添加配置 |
| Online 至少一个 Option | 无 Option 的体验商品禁止上线 |
| Option 可新增 | 不存在相同组合时 INSERT；相同组合已逻辑删除时恢复原记录 |
| Option 可修改 | 修改价格等字段，历史订单保持快照 |
| Option 可删除 | 仅 draft/offline；逻辑删除后立即影响未来订单，历史订单保持快照 |
| Option 可恢复 | 再次创建相同已删除组合时恢复原 ID、更新价格并保留图片关联 |

### Audit Constraints

以下操作必须记录 Audit Log（复用 Phase 3 审计系统）：

| 操作 | action |
|------|--------|
| 创建商品 | `CREATE_PRODUCT` |
| 编辑商品 | `UPDATE_PRODUCT` |
| 修改价格（Product 或 Option） | `UPDATE_PRICE`（记录修改前、修改后） |
| 新增 Option | `CREATE_OPTION` |
| 恢复 Option | `RESTORE_OPTION` |
| 修改 Option | `UPDATE_OPTION` |
| 删除 Option | `DELETE_OPTION` |
| 商品上架 | `ONLINE_PRODUCT` |
| 商品下架 | `OFFLINE_PRODUCT` |
| 删除商品 | `DELETE_PRODUCT` |

---

## 13. Future Expansion

当前阶段支持：

- 体验商品：新增时长、新增人数配置（通过新增 Option 实现）
- 套装商品：创建多款套装、独立定价
- 商品搜索、排序、分页

**当前不考虑（将在后续业务版本扩展）：**

| 功能 | 所属模块 | 计划版本 |
|------|----------|----------|
| 多种体验主题 | Product | 待定 |
| 预约日期 / 时间段 | Product | 待定 |
| 包场模式 | Product | 待定 |
| 库存流水、并发扣减与库存调整单 | Inventory | Phase 4.3 |
| 商品评价 | Review | 待定 |
| AI 商品推荐 | AI | v1.0 |

---

## 14. Business Rule Summary

> **核心原则：** UI 展示一个商品，数据库用 Product + ExperienceOption 实现多配置管理。Option 不是商品，是可选用法组合。

| 分类 | 规则 |
|------|------|
| 商品名称 | 必填，最大 100 字符，允许重名 |
| 商品类型 | 创建后不可修改 |
| 商品状态 | `draft` → `online` → `offline`；重新上架保持原 ID；`online` 必须先下架再删除 |
| 商品价格 | `0 < Price ≤ 99999`，支持批量修改 |
| 体验商品 | Product 1 → N ExperienceOption；每个 Option = 时长 + 人数 + 日期类型 + 价格；同 Product 内组合唯一；Draft 允许无 Option，Online 至少一个 |
| 套装商品 | 单一价格，支持多款套装独立定价 |
| Option 生命周期 | 可新增、恢复、修改、逻辑删除；删除后立即影响未来订单，历史订单保持快照 |
| 价格修改 | 仅影响未来订单，历史订单保留创建时价格快照 |
| 库存 | Phase 4.1 保存/展示 Kit 当前库存并允许管理员直接设值；Phase 4.3 实现流水、自动扣减/恢复与并发控制 |
| 用户可见性 | 普通用户仅可见 `online` 商品 |
| 管理员权限 | 当前统一 ADMIN；后续敏感操作可提升至 SUPER_ADMIN |
| 删除规则 | 逻辑删除，禁止物理删除；`online` 商品需先下架 |
| 审计日志 | 商品 CRUD、Option 创建/恢复/修改/删除、价格修改（含前后值）、上下架均记录 |
| 后续扩展 | 新组合 = 新增 Option；已删除组合 = 恢复原 Option；无需重建其他组合 |
