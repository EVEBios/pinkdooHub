# AI Context — pinkdooHub（扩展参考）

> 19 条强制规则已内置在项目根目录的 `CLAUDE.md` 中（每次会话自动加载）。
> 本文档提供额外的上下文——文档索引、修改规范、和工作流程。
> 需要某个模块的细节时，按索引去读对应文档。

---

## 1. 文档索引

| 需要了解 | 读这个 |
|----------|--------|
| 代码怎么写 | [docs/05_development/coding_standards.md](../05_development/coding_standards.md) |
| 项目怎么分层 | [docs/04_architecture/architecture.md](../04_architecture/architecture.md) |
| API 通用规范 | [docs/03_api/api_design_conventions.md](../03_api/api_design_conventions.md) |
| 用户 API | [docs/03_api/user_api.md](../03_api/user_api.md) |
| 商品 API | [docs/03_api/product_api.md](../03_api/product_api.md) |
| 订单 API | [docs/03_api/order_api.md](../03_api/order_api.md) |
| 数据库设计 | [docs/02_database/database_design.md](../02_database/database_design.md) |
| ER 图 | [docs/02_database/er_diagram.dbml](../02_database/er_diagram.dbml) |
| 需求文档 | [docs/01_requirements/](../01_requirements/) |

---

## 2. 文档修改规范

修改或创建 `docs/` 下的文件时：

| # | 规则 |
|---|------|
| D1 | 保持与同级文档一致的格式风格（表格优先，ASCII 图次之，减少裸列表） |
| D2 | 修改数据库字段 → 同步更新 `er_diagram.dbml` + `database_design.md` |
| D3 | 修改 API → 同步更新对应的 `docs/03_api/` 模块文档 |
| D4 | 新增 Enum → 同步更新 `api_design_conventions.md` §14 Enum Mapping 表 |
| D5 | 新增接口 → 同步更新 `architecture.md` 中的目录树注释 |

---

## 3. 文档更新联动

```
修改 Model           → er_diagram.dbml + database_design.md
修改 API 端点        → docs/03_api/<module>_api.md
修改 Enum            → api_design_conventions.md §14
修改业务规则         → docs/01_requirements/<module>.md
修改目录结构         → architecture.md §2
修改通用规范         → coding_standards.md + CLAUDE.md（如涉及优先级规则）
```

---

## 4. 技术栈速查

| 层级 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.139 |
| ORM | Tortoise ORM | 1.1.7 |
| 数据校验 | Pydantic | 2.13 |
| 数据库 | MySQL（生产）/ SQLite（开发） | — |
| 缓存 | Redis | — |
| 迁移 | Aerich | 0.9.3 |
| 服务器 | Uvicorn | 0.51 |

---

## 5. 枚举速查

| 数据库 (TINYINT) | API (string) | Python Enum |
|-------------------|--------------|-------------|
| `users.role` 1/2/3 | `"user"` / `"admin"` / `"super_admin"` | `UserRole` |
| `users.status` 1/2 | `"normal"` / `"disabled"` | `UserStatus` |
| `products.product_type` 1/2 | `"experience"` / `"kit"` | `ProductType` |
| `products.status` 0/1/2 | `"draft"` / `"online"` / `"offline"` | `ProductStatus` |
| `orders.status` 0/1/2/3 | `"pending"` / `"paid"` / `"cancelled"` / `"completed"` | `OrderStatus` |

---

## 6. 错误码号段速查

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1006 |
| 商品 | 2xxx | 2001-2005 |
| 订单 | 3xxx | 3001-3006 |
