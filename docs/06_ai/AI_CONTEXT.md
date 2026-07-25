# AI Context — pinkdooHub

> 19 条强制规则已内置在项目根目录的 `CLAUDE.md` 中（每次会话自动加载）。
> 本文档是 AI 的"项目守则"——定义开发流程、文档维护规则和全局上下文。
> 完成任何代码修改后，按本文档检查是否需要同步更新。
> 遇到不确定的领域时，按索引去读对应文档，不要凭记忆猜测。

---

## 1. 文档索引

| 需要了解 | 读这个 |
|----------|--------|
| 代码怎么写 | [coding_standards.md](../05_development/coding_standards.md) |
| 项目怎么分层 | [architecture.md](../04_architecture/architecture.md) |
| 开发历史 | [changelog.md](../05_development/changelog.md) |
| API 通用规范 | [api_design_conventions.md](../03_api/api_design_conventions.md) |
| 用户 API | [user_api.md](../03_api/user_api.md) |
| 商品 API | [product_api.md](../03_api/product_api.md) |
| 订单 API | [order_api.md](../03_api/order_api.md) |
| 数据库设计 | [database_design.md](../02_database/database_design.md) |
| ER 图 | [er_diagram.dbml](../02_database/er_diagram.dbml) |
| 需求文档 | [../01_requirements/](../01_requirements/) |

---

## 2. 技术栈速查

| 层级 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.139 |
| ORM | Tortoise ORM | 1.1.7 |
| 数据校验 | Pydantic | 2.13 |
| 配置管理 | pydantic-settings | 2.14 |
| 密码加密 | passlib[bcrypt] | 1.7.4 |
| JWT | python-jose[cryptography] | 3.3.0 |
| 数据库 | MySQL（生产）/ SQLite（开发） | — |
| 缓存 | Redis | — |
| 迁移 | Aerich | 0.9.3 |
| 服务器 | Uvicorn | 0.51 |
| 测试 | pytest + pytest-asyncio + httpx | 9.1 / 1.4 / — |
| 时区 | tzdata | —（Windows 必需） |

---

## 3. 枚举速查

| 数据库 (TINYINT) | API (string) | Python Enum |
|-------------------|--------------|-------------|
| `users.role` 1/2/3 | `"user"` / `"admin"` / `"super_admin"` | `UserRole` |
| `users.status` 1/2 | `"normal"` / `"disabled"` | `UserStatus` |
| `products.product_type` 1/2 | `"experience"` / `"kit"` | `ProductType` |
| `products.status` 0/1/2 | `"draft"` / `"online"` / `"offline"` | `ProductStatus` |
| `orders.status` 0/1/2/3 | `"pending"` / `"paid"` / `"cancelled"` / `"completed"` | `OrderStatus` |

---

## 4. 错误码号段速查

| 模块 | 号段 | 已用 |
|------|------|------|
| 用户 | 1xxx | 1001-1007 |
| 商品 | 2xxx | 2001-2005 |
| 订单 | 3xxx | 3001-3006 |

---

## 5. 文档更新联动

```
修改 Model           → er_diagram.dbml + database_design.md
修改 API 端点        → docs/03_api/<module>_api.md
修改 Enum            → api_design_conventions.md §14
修改业务规则         → docs/01_requirements/<module>.md
修改目录结构         → architecture.md §2
修改通用规范         → coding_standards.md
完成功能模块         → changelog.md
```

---

## 6. Documentation Maintenance Rules

### Core Principle

**Documentation is part of the codebase.** Any code change that affects
architecture, API, database schema, business logic, or developer workflow
must update related documents before commit.

### When to Update

| Change Type | Update |
|-------------|--------|
| New/changed API endpoint | `docs/03_api/<module>_api.md` |
| New/changed database table/field | `database_design.md` + `er_diagram.dbml` |
| New/changed Enum | `api_design_conventions.md` §14 + `AI_CONTEXT.md` §3 |
| New/changed project structure | `architecture.md` §2 |
| New/changed dependency | `architecture.md` §1 + requirements.txt |
| New/changed coding rule | `coding_standards.md` + `CLAUDE.md`（如影响优先级） |
| Feature completion | `changelog.md` |
| New error code | `api_design_conventions.md` §8 + `AI_CONTEXT.md` §4 |

### Workflow After Code Changes

```
Code Change
  │
  ├─ Run tests                ← pytest tests/ -v
  ├─ Check architecture impact  ← new layer? new dependency direction?
  ├─ Check documentation impact  ← which docs are affected? (see table above)
  ├─ Update docs               ← keep in same commit as code
  ├─ Update changelog          ← if completing a feature
  ├─ git diff --stat review    ← sanity check
  └─ commit + push
```

### Documentation Style

- Explain **why** this design exists, not just what the code does
- Document important trade-offs and decisions
- Keep examples in sync with actual code
- Use the same format as existing documents in the same directory

---

## 7. 开发流程（AI 固定流程）

每完成一个任务，按以下顺序执行：

```
1. 修改代码
2. 运行测试        → 确保没有回归
3. 检查架构影响     → 新模块？新依赖方向？新层级？
4. 检查文档影响     → 对照 §6 的表格逐项确认
5. 更新相关文档     → 代码和文档同 commit
6. 更新 changelog   → 功能模块完成时
7. git diff review  → 最后确认变更范围
8. commit + push
```

**四件套原则：Code + Test + Documentation + Commit。缺一不可。**
