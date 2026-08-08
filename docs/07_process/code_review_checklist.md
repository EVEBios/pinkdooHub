# Code Review Checklist

> 每次 PR / commit 前逐项检查。AI 在完成代码修改后自动执行此清单并生成 Review Report。

---

## 1. Architecture

- [ ] API 层只做参数提取和路由分发，不写业务逻辑
- [ ] Service 层不直接操作 Model（通过 Repository）
- [ ] Service 不调用另一个 Service（跨领域通过 Repository）
- [ ] Repository 不包含业务判断（`if status == 0: raise`）
- [ ] 文件位置符合 `architecture.md` 中定义的目录结构
- [ ] 无反向依赖（Model → Service、Repository → Service 等）

---

## 2. Naming & Types

- [ ] 类名 PascalCase，函数 snake_case，常量 SNAKE_CASE
- [ ] Schema 后缀正确（Create / Out / Update / LoginRequest / ListItem）
- [ ] 所有函数标注返回类型（`-> None`, `-> User`, `-> dict`）
- [ ] 无 Magic Number，使用 `common/constants/` 中的命名常量
- [ ] 枚举存储遵循模块权威设计：User 使用 SmallIntField + IntEnum；Product 使用 VARCHAR + 字符串 Enum

---

## 3. Security

- [ ] 密码已通过 bcrypt 哈希，不可逆存储
- [ ] 任何接口不得返回 `password` 字段
- [ ] JWT_SECRET_KEY 不在生产环境使用默认值
- [ ] 日志中不打印密码、Token 等敏感信息
- [ ] 无 SQL 注入风险（使用 ORM 参数化查询）
- [ ] `.env` 文件未提交到 git

---

## 4. Exception & Response

- [ ] Service 层抛命名异常（`raise UsernameAlreadyExists()`），不用裸 BusinessException
- [ ] 错误码在对应模块号段内
- [ ] API 层使用 `success()` / `error()` 工厂函数，不手写 `{"code": 0, ...}`
- [ ] 禁止在 API 层 try/except 构造错误响应

---

## 5. Database

- [ ] 新字段设计合理（类型、约束、默认值）
- [ ] 查询字段有对应索引（username、user_id、status 等高频筛选字段）
- [ ] nullable 字段显式声明，不滥用空字符串代替
- [ ] 金额用 DecimalField(max_digits=10, decimal_places=2)，不用 float
- [ ] 枚举字段的数据库类型、Python Enum 和 API 映射与 Enum Registry 及模块数据库设计一致

---

## 6. Data & Performance

- [ ] 无 `for ... await` 循环查询（使用 `prefetch_related` / `select_related`）
- [ ] 列表接口有分页（limit + offset）
- [ ] 跨表写操作使用 `in_transaction()` 包裹
- [ ] 批量操作用 `bulk_create` / `bulk_update`，不循环单条 `save()`

---

## 7. Testing

- [ ] 新功能有对应的测试用例
- [ ] 正常流程覆盖（200/201）
- [ ] 异常流程覆盖（400/401/403/404）
- [ ] 业务错误码覆盖（1001、1003 等）
- [ ] `test_password_is_hashed` 确认密码不存明文

---

## 8. Logging

- [ ] 关键操作有 `logger.info()`（如注册、登录）
- [ ] 异常有 `logger.error(..., exc_info=True)`
- [ ] 无 `print()` 调用
- [ ] 日志中不包含密码、Token 等敏感字段

---

## 9. Documentation

- [ ] API 文档已更新
- [ ] 数据库文档已更新（`database_design.md` + `er_diagram.dbml`）
- [ ] Enum Mapping 表已更新（`api_design_conventions.md` §14）
- [ ] `changelog.md` 已更新（功能模块完成时）
- [ ] 版本号是否需要升级
- [ ] 是否需要数据库迁移（`aerich migrate`）
- [ ] 是否需要新增依赖（`requirements.txt`）

---

## 10. AI Review Report 模板

完成代码修改后，AI 自动输出：

```
## AI Code Review Report

### Changes
- [文件清单]

### Architecture Check
[通过 / 发现问题]

### Security Check
[通过 / 发现问题]

### Documentation Check
[通过 / 需更新：文件列表]

### Test Coverage
- 新增测试: N 条
- 通过: N/N

### Action Items
- [ ] [如需要] 升级版本号
- [ ] [如需要] 数据库迁移
- [ ] [如需要] 新增依赖
```
