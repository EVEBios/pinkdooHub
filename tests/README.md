# 测试目录导航

测试按业务领域组织；Product、Order、Inventory 与 Reservation 均按领域和应用层边界归类。Inventory 已包含 Phase 4.3.1–4.3.12 的完整回归，并在其 MySQL 门槛中承载 M6 颜色库存锁与结构验证；Reservation N1 覆盖上海营业日历、快照、状态机、用户归属、手机号隐私、店休批量取消、账号注销联动、OpenAPI/M5，以及真实 MySQL 创建/店休竞争、幂等店休、整批回滚、1205/1213 全事务重试与六个索引 EXPLAIN。测试文件名和测试函数名继续描述被验证的行为，不使用 `unit` / `integration` 目录强行拆分同时覆盖契约与真实数据库的测试。

```text
tests/
├── conftest.py          # 全局数据库、HTTP Client 与用户 fixtures
├── support/             # 跨测试文件复用的响应数据工厂
├── common/              # 配置、版本、请求工具和基础迁移
├── users/               # 认证、用户资料、RBAC 与用户 Model
├── audit/               # 共享审计 Model、Repository、Service 与 Mapper
├── product/              # 含 MARD 221 抓取清单、PNG 生成与本地 SQLite 导入安全契约
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
├── inventory/          # Phase 4.3/M6；常规测试、HTTP 矩阵与显式启用的 mysql 发布门槛
└── reservation/        # N1；Validator/Service/Mapper/HTTP/M5 与显式启用的 mysql 发布门槛
```

常用命令：

```bash
# 完整套件
python -m pytest tests/ -q

# 按领域
python -m pytest tests/order/ -q
python -m pytest tests/product/ -q
python -m pytest tests/product/test_mard_bead_color_import.py -q
python -m pytest tests/inventory/ -q
python -m pytest tests/reservation/ -q --ignore=tests/reservation/mysql

# 按领域中的应用层
python -m pytest tests/order/services/ -q
python -m pytest tests/product/repositories/ -q

# 共享能力
python -m pytest tests/common/ tests/audit/ tests/users/ -q
```

`tests/inventory/mysql/`、`tests/reservation/mysql/` 与 `tests/wallet/mysql/` 默认跳过，避免测试误连开发机现有 MySQL。仅在已经创建并迁移的隔离实例上显式启用；三者共用受保护的测试连接配置，fixture 会拒绝非回环地址、3306 和不符合专用前缀的 Schema：

```powershell
$env:INVENTORY_MYSQL_TEST_ENABLED = "1"
$env:INVENTORY_MYSQL_TEST_HOST = "127.0.0.1"
$env:INVENTORY_MYSQL_TEST_PORT = "13306"
$env:INVENTORY_MYSQL_TEST_DB = "pinkdoohub_inventory_4311_ci"
$env:INVENTORY_MYSQL_TEST_USER = "root"
$env:INVENTORY_MYSQL_TEST_PASSWORD = ""
python -m pytest tests/inventory/mysql tests/reservation/mysql tests/wallet/mysql -q
```

该命令不会创建 Schema 或执行迁移。必须先按数据库迁移流程在一次性实例中执行真实 Aerich 0→6；测试清空专用 Schema 的用例业务数据，但保留 `aerich` 版本记录和 M6 迁移产生的 221 条 `bead_colors` 占位槽，避免把运行时补种误当成迁移证据。

GitHub Actions 的 `backend-mysql-release` 会完成上述一次性实例生命周期。为同时证明空库 0→7、历史 fixed 兼容和 M7 设置升级，它会执行经审查的 M6/M7 回退、历史数据种入与重新升级。`scripts/ci/check_mysql_gate.py` 最终记录 MySQL 8.0.46、八条 Aerich 版本、221 槽、M7 单例和历史兼容证据；联合 pytest 还覆盖资金并发、真实 1205、1213 整事务重试、Wallet/Inventory 锁等待及关键 `EXPLAIN`。`always()` 清理路径删除专用 Schema、停止准确的 service container、确认容器不再运行和 13306 关闭。禁止为方便本地运行而放宽 fixture、改用 3306、`--fake`、`init-db` 或应用自动建表。

新增测试时，优先放入对应领域和被测层；只有真正跨领域的基础能力才放入 `common/`。全局 fixture 留在根 `conftest.py`，仅供多个测试文件复用的数据构造器放入 `support/`。
