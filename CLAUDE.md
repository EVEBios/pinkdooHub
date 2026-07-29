# pinkdooHub

拼豆店管理系统 | FastAPI + Tortoise ORM + Pydantic + Redis + MySQL/SQLite

## 文档索引

需要细节时读对应文档，不要猜：

| 需要了解 | 文档 |
|----------|------|
| 代码怎么写 | `docs/05_development/coding_standards.md` |
| 项目怎么分层 | `docs/04_architecture/architecture.md` |
| API 通用规范 | `docs/03_api/api_design_conventions.md` |
| 用户 API | `docs/03_api/user_api.md` |
| 商品 API | `docs/03_api/product_api.md` |
| 订单 API | `docs/03_api/order_api.md` |
| 数据库设计 | `docs/02_database/database_design.md` |
| ER 图 | `docs/02_database/er_diagram.dbml` |
| AI 扩展参考 | `docs/06_ai/AI_CONTEXT.md` |

## 规则（必须遵守，无例外）

### 异常与响应

1. 抛出 `BusinessException(code=N, message="...")`，**禁止** `HTTPException`
2. 返回 `success(data=...)`，**禁止** 手写 `{"code": 0, ...}` 或任何自定义响应格式
3. API 的 `response_model` 必须是 Pydantic Schema（如 `UserOut`），**禁止** 直接返回 ORM Model

### 分层与依赖

4. 调用链：API → Service → Repository → Model，**禁止** 跳过层级或反向引用
5. Service **禁止**调用另一个 Service，跨领域通过 Repository
6. Repository **禁止**包含业务判断（`if status == 0: raise` 等），那是 Service 的职责

### 命名与类型

7. 类名 PascalCase，文件名 snake_case，常量 SNAKE_CASE
8. Schema 命名后缀：`XxxCreate` / `XxxOut` / `XxxUpdate`
9. **禁止** Magic Number，全部使用 `common/constants/` 中的命名常量
10. 枚举字段 DB 用 `SmallIntField`，Schema 用 `common/enums/` 中的 `IntEnum` 类型
11. Out Schema 必须配置 `from_attributes = True`（Pydantic → Tortoise 转换）

### 数据与性能

12. **禁止** `for ... await` 循环查询——用 `prefetch_related()` / `select_related()`
13. 分页返回用 `Page[T]`，**禁止** 裸 `tuple` 或裸 `list`
14. 跨表写操作必须用 `in_transaction()` 包裹
15. **禁止** 返回 `password` 字段到任何响应中
16. 金额用 `DecimalField(max_digits=10, decimal_places=2)`，**禁止** `float`

### 日志与流程

17. 用 `logging.getLogger(__name__)`，**禁止** `print()`
18. 编写模块代码前，**必须先读**对应的 `docs/03_api/<module>_api.md`
19. 修改代码后，检查是否需要同步更新文档（见下方联动表）
20. 每次 commit 前，**必须**对照 `docs/06_ai/AI_CONTEXT.md` §6-7 执行文档影响检查并更新
21. 完成独立功能模块后，**必须**更新 `docs/05_development/changelog.md`

## 文档更新联动

```
修改 Model           → er_diagram.dbml + database_design.md
修改 API 端点        → docs/03_api/<module>_api.md
修改 Enum            → api_design_conventions.md §14
修改业务规则         → docs/01_requirements/<module>_api.md
修改目录结构         → architecture.md §2
修改通用规范         → coding_standards.md
完成功能模块         → changelog.md
```

## 提交前检查清单

每次 commit 前逐项确认：

- [ ] 代码符合 `coding_standards.md`
- [ ] 架构无反向依赖、无跨层调用
- [ ] 相关文档已检查并更新
- [ ] `changelog.md` 已更新（功能模块完成时）
- [ ] 测试通过（`pytest tests/ -q`）
- [ ] 版本号是否需要升级
- [ ] 是否需要数据库迁移
