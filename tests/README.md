# 测试目录导航

测试按业务领域组织；Product、Order 与 Inventory 均按应用层分组。Inventory 已包含 Phase 4.3.1–4.3.12 的文档、common/schema、Model/迁移、Repository、Service、Mapper、API、真实 MySQL 发布门槛与最终 Review 回归；Kit/混合创建扣减与 Pending 取消恢复测试还分布在 Order Schema、Mapper、Service、API 及 Inventory/Product Repository。当前覆盖稳定集合锁、双层幂等、批量余额/流水、全写集回滚、库存隐私、MySQL 瞬态错误重试、ADMIN+ 路由、OpenAPI、首次 201/重放 200、查询参数适配、旧库存请求拒绝、Product Kit 响应库存上限、完整 HTTP 矩阵、真实 MySQL 竞争/1205/EXPLAIN 与 MySQL HTTP smoke。测试文件名和测试函数名继续描述被验证的行为，不使用 `unit` / `integration` 目录强行拆分同时覆盖契约与真实数据库的测试。

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
├── order/
│   ├── api/
│   ├── common/
│   ├── schemas/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   └── mappers/
└── inventory/          # Phase 4.3；常规各层测试、完整 HTTP 矩阵与显式启用的 mysql 发布门槛
```

常用命令：

```bash
# 完整套件
python -m pytest tests/ -q

# 按领域
python -m pytest tests/order/ -q
python -m pytest tests/product/ -q
python -m pytest tests/inventory/ -q

# 按领域中的应用层
python -m pytest tests/order/services/ -q
python -m pytest tests/product/repositories/ -q

# 共享能力
python -m pytest tests/common/ tests/audit/ tests/users/ -q
```

`tests/inventory/mysql/` 默认跳过，避免测试误连开发机现有 MySQL。仅在已经创建并迁移的隔离实例上显式启用；fixture 会拒绝非回环地址、3306 和不符合专用前缀的 Schema：

```powershell
$env:INVENTORY_MYSQL_TEST_ENABLED = "1"
$env:INVENTORY_MYSQL_TEST_HOST = "127.0.0.1"
$env:INVENTORY_MYSQL_TEST_PORT = "13306"
$env:INVENTORY_MYSQL_TEST_DB = "pinkdoohub_inventory_4311"
$env:INVENTORY_MYSQL_TEST_USER = "root"
$env:INVENTORY_MYSQL_TEST_PASSWORD = ""
python -m pytest tests/inventory/mysql -q
```

该命令不会创建 Schema 或执行迁移。必须先按数据库迁移流程在一次性实例中执行真实 Aerich 0 → 1 → 2；测试只清空专用 Schema 的业务表并保留 `aerich` 版本记录。

新增测试时，优先放入对应领域和被测层；只有真正跨领域的基础能力才放入 `common/`。全局 fixture 留在根 `conftest.py`，仅供多个测试文件复用的数据构造器放入 `support/`。
