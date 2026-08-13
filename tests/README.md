# 测试目录导航

测试按业务领域组织；Product 与 Order 再按应用层分组。测试文件名和测试函数名继续描述被验证的行为，不使用 `unit` / `integration` 目录强行拆分同时覆盖契约与真实数据库的测试。

```text
tests/
├── conftest.py          # 全局数据库、HTTP Client 与用户 fixtures
├── support/             # 跨测试文件复用的响应数据工厂
├── common/              # 配置、版本、请求工具和基础迁移
├── users/               # 认证、用户资料、RBAC 与用户 Model
├── audit/               # 共享审计 Model、Repository、Service 与 Mapper
├── product/
│   ├── api/
│   ├── common/
│   ├── schemas/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   ├── mappers/
│   ├── validators/
│   └── storage/
└── order/
    ├── api/
    ├── common/
    ├── schemas/
    ├── models/
    ├── repositories/
    ├── services/
    └── mappers/
```

常用命令：

```bash
# 完整套件
python -m pytest tests/ -q

# 按领域
python -m pytest tests/order/ -q
python -m pytest tests/product/ -q

# 按领域中的应用层
python -m pytest tests/order/services/ -q
python -m pytest tests/product/repositories/ -q

# 共享能力
python -m pytest tests/common/ tests/audit/ tests/users/ -q
```

新增测试时，优先放入对应领域和被测层；只有真正跨领域的基础能力才放入 `common/`。全局 fixture 留在根 `conftest.py`，仅供多个测试文件复用的数据构造器放入 `support/`。
