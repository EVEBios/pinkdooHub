# Product Module Business Rules

> **Document Version:** v2.2
> **Module:** Product
> **Phase:** 4.1 Product Module
> **Last Updated:** 2026-08-12
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

Product 基础信息修改只接受 API Schema 使用 `exclude_unset=True` 得到的 `name` / `description` 显式字段。Service 通过字段白名单阻止调用方借通用更新方法修改 `product_type`、`status` 或 `is_deleted`；显式 `description=None` 表示清空，缺失字段保持原值。已删除 Product 抛 `ProductIsDeleted`（`40903`），Online Product 抛 `OnlineProductCannotBeModified`（`40905`, `Online product cannot be modified`）。成功更新与 `UPDATE_PRODUCT` 审计使用同一事务连接。

逻辑删除先区分不存在和已删除，再拒绝 Online Product 并抛 `ProductMustBeOfflineBeforeDelete`（`40904`, `Product must be offline before deletion`）。成功时只设置 `is_deleted=true`，关联 Option、Kit、Image 不变，并与 `DELETE_PRODUCT` 审计在同一事务中提交。更新或审计任一步失败时全部回滚；修改和删除都不调用 ProductValidator。

商品下架只允许 `online → offline`。Draft 与 Offline 都已处于“不对外销售”状态，执行下架统一抛 `ProductAlreadyOffline`（`40902`, `Product is already offline`），不为 Draft 另建错误码。Service 先区分不存在和逻辑删除，再检查 ProductStatus；成功时在同一事务连接上更新 `status=offline` 并写 `OFFLINE_PRODUCT` 审计。下架不调用 ProductValidator，状态更新或审计任一步失败时全部回滚。

### 7.2 Product 查询可见性

Product 查询 Service 返回 ORM Product 聚合或 `Page[Product]`，不依赖 API Out Schema，也不生成 `LabeledValue`、`cover_image`、`display_price`、`dimensions`、`available` 等展示字段；这些字段由 API Mapper 从已加载聚合计算并交给 Out Schema 白名单序列化。

- 管理端列表可查看全部状态，默认隐藏已删除记录；`include_deleted=true` 时包含已删除记录。管理端详情显式包含已删除记录，但请求的 ProductType 与实际类型不匹配时统一抛 `ProductNotFound`。
- 用户端列表固定 `status=online`、`include_deleted=false`，keyword 同时搜索名称和描述。调用方不能覆盖这两个可见性条件。
- 用户端详情只有 Product 存在、未删除、Online 且类型匹配时返回；不存在、未上线、已删除和类型不匹配全部抛 `ProductNotFound(40401)`，避免泄漏未发布资源。
- 查询不写审计、不调用 Validator、不开启事务。

> **实现状态：** 管理端/用户端列表与详情查询 Service、API Mapper 和路由均已实现，并有 Repository 参数编排、可见性、类型隐藏、零 SQL Mapper、权限和真实预加载聚合 HTTP 测试。

### 7.3 Product 创建事务

Product 创建 Service 接收已经过请求 Schema 校验和规范化的领域字段，不直接依赖 Pydantic Schema：

```python
create_experience_product(name, description, operator_id, ip_address) -> Product
create_kit_product(name, description, price, stock, operator_id, ip_address) -> Product
```

- Experience 创建在同一事务连接内创建 Draft Product 并写 `CREATE_PRODUCT` 审计。
- Kit 创建在同一事务连接内依次创建 Draft Product、必需的 ProductKit 扩展记录，并写 `CREATE_PRODUCT` 审计。
- `product_type`、`status=draft`、`is_deleted=false` 由 Service/Model 固定，调用方不能传入覆盖值。
- Service 返回 Product；创建响应只需要 Product 身份字段，API 使用对应 Create Out Schema 序列化。
- Product、ProductKit 或审计任一步失败时全部回滚；创建不调用 ProductValidator，Draft 可以暂时没有描述、图片或 Experience Option。

> **实现状态：** Experience/Kit 创建 Service、Mapper 与 ADMIN+ HTTP 201 路由均已实现，并有固定类型、同一事务连接、零库存、无 Validator 调用、真实聚合持久化、权限和审计失败全回滚测试。

### 7.4 Product 基础信息修改与逻辑删除

Product Service 公开方法为：

```python
update_product(product_id, *, updates, operator_id, ip_address) -> Product
delete_product(product_id, *, operator_id, ip_address) -> Product
```

- `updates` 只允许非空的 `name` / `description` 显式字段映射，从而保留 PATCH 缺失字段与显式 `description=None` 的区别。
- 两个方法都使用 `get_product_by_id(..., include_deleted=True)`，依次处理不存在、逻辑删除和 Online 状态冲突。
- 修改支持 Draft/Offline；删除支持 Draft/Offline 且保持原 ProductStatus，不修改或删除关联聚合记录。
- Repository 更新和对应审计共享事务连接；Service 返回更新后的 Product，由 API Out Schema 负责响应白名单。
- 两条流程均不加载完整聚合、不调用 ProductValidator。

> **实现状态：** 基础信息修改与逻辑删除 Service、Mapper 与 ADMIN+ 路由均已实现，并有字段白名单、PATCH 缺失/null、冲突优先级、状态保留、关联记录保留、权限、共享事务及审计失败真实回滚测试。

### 7.5 ExperienceOption 新增与恢复事务

`create_experience_option(product_id, *, duration_minutes, participants, day_type, price, operator_id, ip_address)` 先使用 Product 主表查询依次处理不存在、逻辑删除、非 Experience 类型和 Online 状态，再按全历史组合查询 Option：

- 无历史组合：事务内 INSERT Option、写 `CREATE_OPTION` 审计，并返回 `restored=false`。
- 有效组合已存在：抛 `ExperienceOptionAlreadyExists`（`40911`, `Experience option already exists`），data 固定包含三个组合维度。
- 相同组合已逻辑删除：事务内恢复原记录，只更新当前价格与 `is_deleted=false`，保留原 ID 和图片外键；写 `RESTORE_OPTION` 审计，并返回 `restored=true`。
- 非 Experience Product 抛 `ProductTypeMismatch`（`40001`），data 固定包含 expected/actual；Online 状态复用 `OnlineProductCannotBeModified`（`40905`）。
- Service 查询和数据库全历史唯一索引双重保护。若不存在检查后发生并发 INSERT 冲突，Service 将 ORM `IntegrityError` 转换为同一 `40911`，不泄漏持久化异常。
- Option 写入、审计与响应所需的 Option/有效图片重载共享同一事务连接；审计失败时新建或恢复均回滚。该流程不调用上架 Validator。

Service 返回领域结果 `ExperienceOptionCreationResult(option, restored)`，不依赖 HTTP：API 根据 `restored=false` 返回 201，根据 `restored=true` 返回 200，并使用已预加载有效图片的 Option 生成 `ExperienceOptionOut`。

恢复审计通过现有 `AuditLog.description` 保存紧凑 JSON：`option_id` 以及 `before.price` / `after.price` 两位小数字符串。本阶段不新增 metadata 列，不需要数据库迁移。

> **实现状态：** ExperienceOption 新增/恢复 Service、Mapper 与 ADMIN+ 路由均已实现，并有 Product 前置冲突、唯一冲突、并发唯一约束翻译、Draft/Offline、恢复 ID/图片、权限、审计快照与真实回滚测试。

### 7.6 ExperienceOption 部分修改事务

`update_experience_option(option_id, *, updates, operator_id, ip_address)` 接收 API 通过 `model_dump(exclude_unset=True)` 得到的非空显式字段映射，只允许 `duration_minutes`、`participants`、`day_type`、`price`。Service 将 `duration_minutes` 映射到 Model 的 `duration`，其余缺失字段保持原值。

- 使用 `get_option_by_id(..., include_deleted=True)` 同时加载所属 Product；Option 不存在抛 `ExperienceOptionNotFound`（`40402`, `Experience option not found`），已逻辑删除抛 `ExperienceOptionAlreadyDeleted`（`40912`, `Experience option is already deleted`）。已删除 Product 下的 Option 对修改调用隐藏为 `40402`；Online Product 复用 `40905`。
- Service 用旧值与本次字段合并最终 `(duration, participants, day_type)`，再执行全历史组合查询。查询命中当前 Option ID 不算冲突，命中任何其他有效或已删除记录均抛 `40911`。
- 数据库唯一索引仍是并发兜底；事务内更新发生 `IntegrityError` 时转换为相同 `40911`。
- 只修改维度时写 `UPDATE_OPTION`；只修改价格时写 `UPDATE_PRICE`；同一次 PATCH 同时修改两类字段时按 `UPDATE_OPTION`、`UPDATE_PRICE` 顺序写两条审计。两种 description 都是紧凑 JSON，包含 `option_id` 和对应 before/after 快照。
- Option 更新、全部审计及响应 Option 重载共享一个事务；第二条审计或响应重载失败也会回滚字段变更和此前已写审计。更新不调用 ProductValidator，图片关系不由此接口修改。

> **实现状态：** ExperienceOption 修改 Service、Mapper 与 ADMIN+ 路由均已实现，并有 PATCH 白名单、缺失字段合并、资源/状态优先级、有效/已删除组合冲突、并发冲突翻译、单/双审计、权限、图片保留及真实全事务回滚测试。

### 7.7 ExperienceOption 逻辑删除事务

`delete_experience_option(option_id, *, operator_id, ip_address)` 使用 `get_option_by_id(..., include_deleted=True)` 加载 Option 与所属 Product，依次处理不存在、Option 已删除、所属 Product 已删除和 Online 状态：

- Option 不存在或所属 Product 已删除统一抛 `ExperienceOptionNotFound(40402)`；Option 已删除优先抛 `ExperienceOptionAlreadyDeleted(40912)`；Online Product 复用 `OnlineProductCannotBeModified(40905)`。
- Draft/Offline 允许删除，包括删除最后一个有效 Option。成功时只设置 `ExperienceOption.is_deleted=true`，不修改 ProductStatus，不更新或删除任何 ProductImage。
- 删除前快照以紧凑 JSON 写入 `AuditLog.description`，包含 `option_id`、`duration_minutes`、`participants`、`day_type` 和两位小数 `price`；action 为 `DELETE_OPTION`，审计目标为所属 Product。
- Option 更新与审计共享同一事务连接；更新失败不审计，审计失败回滚删除标记。该流程不查询有效 Option 数量，也不调用 ProductValidator；后续重新上架时由 Validator 对零 Option 聚合统一返回 `42201`。

> **实现状态：** ExperienceOption 逻辑删除 Service、Mapper 与 ADMIN+ 路由均已实现，并有资源/状态优先级、Draft/Offline、最后一项删除、Product 状态保留、权限、图片外键保留、快照审计及真实回滚测试。

### 7.8 ProductKit 价格修改与 Inventory 边界

`update_kit_price(product_id, *, price, operator_id, ip_address)` 保留在 Product 模块：

- 使用 `get_product_by_id(..., include_deleted=True)`，依次处理 `ProductNotFound(40401)`、`ProductIsDeleted(40903)`、非 Kit 的 `ProductTypeMismatch(40001)` 和 `OnlineProductCannotBeModified(40905)`；只有 Draft/Offline Kit 可继续修改。
- Product 确为可修改 Kit 后，再使用 `get_kit_by_product_id()` 加载一对一扩展；扩展记录缺失抛已登记的 `ProductKitNotFound`（`40404`, `Product kit not found`），不得伪造默认价格或库存。
- 价格接口只修改 `ProductKit.price` 并写 `UPDATE_PRICE`；价格快照使用两位小数字符串，以紧凑 JSON 写入现有 `AuditLog.description`。
- Kit 价格更新和对应审计共享同一事务连接，更新失败不审计，审计失败回滚字段修改。该流程不加载完整 Product 聚合，也不调用 ProductValidator。

Service 返回更新后的 `ProductKit`；API Mapper 使用 `product_id` 作为 `KitPriceOut` 的 `id`，不会把 ProductKit 内部主键暴露为 Product ID。

Phase 4.3.10 已从 Product 模块移除直接库存设置路由、请求/响应 Schema、Mapper 与 Service 用例，也从 Kit 创建请求移除 `stock`。新 Kit 固定从 0 开始；管理员库存变化统一使用 Inventory adjustment。ProductRepository 保留通用 ProductKit 持久化原语，但业务层不得绕过 Inventory 流水直接修改余额。

> **实现状态：** Kit 价格修改 Service、Mapper、ADMIN+ 路由及 `40404 ProductKitNotFound` 均已实现；Inventory adjustment 已替代旧库存写入口。

### 7.9 ProductImage 生命周期事务

图片业务由四个 Service 用例组成；Service 接收已经由未来 API/文件存储适配器生成的 `image_url`，不依赖 FastAPI `UploadFile`，也不负责文件内容、大小、MIME、路径或对象存储操作：

- `create_product_image(product_id, *, image_url, is_cover, sort, operator_id, ip_address)` 先处理 Product 的 40401/40903/40905。公共图固定 `experience_option_id=NULL`；设为封面时，在同一事务中锁定 Product 行以串行化同一聚合的封面写入，再批量清除该 Product 其他有效公共封面、创建图片并写 `CREATE_PRODUCT_IMAGE`。
- `create_option_image(option_id, *, image_url, sort, operator_id, ip_address)` 复用 Option 的 40402/40912/40905 优先级；已删除所属 Product 隐藏为 40402。归属从 Option 自动取得，`is_cover=false` 固定，并写 `CREATE_OPTION_IMAGE`。
- `update_product_image(image_id, *, updates, operator_id, ip_address)` 只接收非空 `sort` / `is_cover=true` 显式映射。不存在、已删除、所属 Product 已删除或所属 Option 已删除统一抛 `ProductImageNotFound`（`40403`, `Product image not found`）；Online Product 抛 40905。Option 专属图设置封面抛 `OptionImageCannotBeCover`（`40021`, `Option image cannot be set as product cover`）。普通修改写 `UPDATE_PRODUCT_IMAGE` before/after 快照；真正发生封面切换时再按顺序写 `SET_PRODUCT_COVER`，记录旧/新封面 ID。
- `delete_product_image(image_id, *, operator_id, ip_address)` 复用相同可修改图片检查，只设置 `is_deleted=true`，不物理删除文件和数据库记录；允许删除公共封面或 Option 最后一张图。删除与 `DELETE_PRODUCT_IMAGE` 审计同事务回滚，不调用 Validator。

封面创建/切换先在事务内通过 `SELECT ... FOR UPDATE` 锁定 Product 行，防止同一 Product 的并发封面请求在清理后各自留下一个封面；图片创建、封面批量清理、图片修改/删除和对应一至两条审计均使用同一事务连接。当前 `AuditLog.description` 只有 256 字符，删除快照保存 `image_id`、`product_id`、`experience_option_id`、`is_cover` 和 `sort`，不复制最长可达 2048 字符的 `image_url`；完整 URL 继续保留在逻辑删除的 ProductImage 中，可由 `image_id` 追溯。

文件内容校验和存储由 API/基础设施边界负责：在调用 Service 前完成 jpg/png/webp、2 MiB 和安全 UUID 文件名/路径检查并生成 URL。数据库事务无法回滚已上传文件；若 Service 失败，API 上传编排使用 storage key 执行幂等删除补偿，补偿自身失败时记录存储键以便清理，且不掩盖原 Service 异常。`42221` 只属于该上传边界。

逻辑删除后的物理文件清理由独立、可重试的批处理执行，不进入 DELETE 请求和数据库事务：`ProductImage.is_deleted=true`、`updated_at` 与保留的 `image_url` 共同构成持久化候选来源。清理命令必须显式接收带时区的截止时间，只扫描 `updated_at <= before` 的删除记录；只允许删除当前存储适配器能解析出的 UUID key，外部 URL 或异常 URL 一律跳过。每批一次性查询仍被有效 ProductImage 引用的 URL 并在内存中保护，避免逐候选查询；文件删除幂等，单项失败记录 image_id/storage key、继续处理本批其他项，并通过非零进程退出码让外部调度器重试。数据库记录和审计日志始终保留。

批处理不会由 Web 进程启动时自动执行，也不在 DELETE 响应后创建内存后台任务。命令默认是只记录候选的预览模式；运维方先按保留期选择截止时间核对结果，再使用完全相同的参数显式增加 `--apply` 执行删除：

```bash
python -m app.tasks.product_image_cleanup --before 2026-08-01T00:00:00+08:00 --batch-size 100
python -m app.tasks.product_image_cleanup --before 2026-08-01T00:00:00+08:00 --batch-size 100 --apply
```

> **实现状态：** ProductImage 创建、修改、封面切换和逻辑删除 Service，40403/40021/42221 命名异常，文件校验/本地存储，两个 ADMIN+ multipart API 路由、Service 失败的路由级删除补偿，以及逻辑删除后的可重试批处理清理均已实现；真实 HTTP/SQLite/临时文件测试固定文件归属、审计一致性与清理安全边界。

### 7.10 Database Layer（Foreign Key）

直接指向 Product 的关联表（ExperienceOption、ProductKit、ProductImage）的 Foreign Key 必须使用 `ON DELETE RESTRICT`。`ProductImage.experience_option_id` 是明确例外，使用 `ON DELETE SET NULL` 作为 Option 异常物理删除时的兜底：

**原因：** 防止有人绕过业务层直接在数据库执行物理删除，导致关联数据孤立。

### 7.11 Preconditions

`online` 商品必须先下架才能删除。

### 7.12 Post-delete Behavior

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

> **实现状态：** Product Validator 阶段已完成。异常契约、公共规则、Experience/Kit 专属规则、稳定 issues 顺序、未知 ProductType fail-closed，以及真实 Repository 聚合上的零查询与零修改边界均已有自动化测试；后续 Product Service、状态写入、事务、审计和 API 路由也已在 Phase 4.1 完成。

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

> **实现状态：** 上述 Service 上架编排、ADMIN+ 权限依赖、路由和 `ProductOnlineOut` 序列化均已实现。专项测试覆盖 Draft/Offline、Experience/Kit、404/409/422 前置失败、精确调用顺序、同一事务连接、权限、状态更新失败不审计，以及审计失败时真实数据库状态回滚。

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

Phase 4.3.1 已在 [Inventory Module](inventory_module.md) 冻结完整库存业务，但运行时代码尚未接入：

| 库存操作 | 所属模块 | 触发时机 |
|----------|----------|----------|
| 当前库存余额 | ProductKit + Inventory | `product_kits.stock` 继续作为唯一权威余额 |
| 管理员调整 | Inventory | ADMIN+ 提交调整量、原因和幂等键；允许 Online Kit |
| 库存扣减 | Order + Inventory | 创建 Pending Kit/混合订单时 |
| 库存恢复 | Order + Inventory | Pending 订单取消时 |
| 支付与完成 | Order | 不再改变库存 |
| 库存不足拒绝 | Order + Inventory | 创建订单并锁后校验时 |
| 库存流水 | Inventory | 与余额、Order 和 Audit 在相应事务内原子提交 |

Phase 4.3 已采用余额表 + 流水表模式：ProductKit 保存余额，Inventory 解释并控制每次变化。Phase 4.3.10 已移除管理员直接设置最终值的旧端点和 Kit 创建 `stock` 输入，新 Kit 从 0 开始并通过 Inventory adjustment 入库。Product 的价格、内容和图片仍遵守原状态限制，库存调整是独立 Inventory 行为。

---

## 11. Lifecycle Summary（生命周期总览）

| 实体 | 生命周期 | 所属 Phase |
|------|----------|------------|
| Product（体验/套装） | Draft → Online → Offline → 逻辑删除 | Phase 4.1 |
| ExperienceOption | 创建 / 恢复 → 修改 → 逻辑删除（无独立状态，跟随 Product） | Phase 4.1 |
| Kit Product | 与 Product 相同，共用 Product 生命周期 | Phase 4.1 |
| Order | Pending → Paid → Completed；Pending → Cancelled | Phase 4.2 已实现 |
| Kit 当前库存值 | 创建 → 管理员直接设置 → 展示 | Phase 4.1 |
| Inventory 流水与自动变更 | 契约已冻结、运行时尚未实现 | Phase 4.3 |

> **关于 ExperienceOption 的 status：** 当前不设独立状态。Option 仅作为 Product 的配置项存在，Product 的状态（draft/online/offline）已覆盖了"该配置是否对用户可见"的需求。如需独立控制某个 Option 的可见性，后续再扩展。

---

## 12. Business Constraints（汇总）

### Status Constraints

| 规则 | 说明 |
|------|------|
| Draft 商品允许编辑 | ✅ |
| Online 商品允许编辑 | ❌；须先下架 |
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
