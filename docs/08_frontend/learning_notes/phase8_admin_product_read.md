# Phase 8.1 学习笔记：ADMIN Product 只读管理

> 状态：**工程实现与微信开发者工具 Functional 已全部完成；2026-08-29 按钮即时筛选、待应用提示和删除记录双按钮增量也已验收通过。** 本阶段只建立管理商品列表与详情的安全读模型，不包含任何 Product/Option/Image/Inventory mutation。

## 1. 为什么先做只读切片

Product 管理写操作互相依赖：创建后需要 Option/价格和图片，完整后才能上架，Kit 库存又必须经过独立 Inventory 幂等语义。若在第一步同时开放所有按钮，错误恢复、部分成功、readiness issues 和权限边界会混在一个页面中，难以测试。

8.1 先交付一条可观察纵向链路：

```text
首页 ADMIN 入口
  → 固定登录回跳 / 角色前置守卫
  → 管理 Product 筛选与服务端分页
  → 类型 + Product ID 安全动态路由
  → Experience 或 Kit 管理详情
  → 草稿缺失项 / 删除标记只读展示
```

## 2. 交付边界

- 管理列表支持 type、status、keyword、include_deleted 和服务端分页；
- Experience/Kit 详情调用两个类型专属端点；
- Draft 可显示空封面、空展示价格、空公共图片、空 Option/dimensions 和 null description；
- Kit 显示服务端 price 与权威 stock，但本阶段没有库存调整按钮；
- 普通用户在 Hook 挂载前被拦截，后端 ADMIN+ 继续承担最终授权；
- 登录 redirect 只增加固定管理商品列表，不允许动态详情或任意 URL；
- 页面明确标为只读，不提供尚未冻结的 mutation。

## 3. 知识点

### 3.1 同一领域可以有多个读模型

公开 Product 详情只返回已经上架并满足完整性规则的聚合，所以公开 Guard 可以要求封面、Experience Option 和有效维度都存在。管理端必须能修复尚未完成的 Draft，也要能追溯逻辑删除记录，因此空配置是合法业务状态。复用公开 Guard 会把合法草稿误判为协议损坏。

### 3.2 TypeScript 类型不能验证网络 JSON

OpenAPI 生成类型约束调用方的编译期代码，HTTP 响应仍是 `unknown`。Endpoint 必须逐字段验证并重新构造白名单对象，防止错误 Enum、非法金额/库存、非 UTC 时间或内部字段进入页面。

### 3.3 前端角色判断不是授权

首页隐藏入口、分包和页面 Hook 前置守卫只能改善体验并减少错误请求。客户端代码和 Storage 都能被修改，真正的授权必须由 FastAPI `get_current_admin` 在每个管理端点执行。普通用户直接请求 API 仍应得到 403，且 403 不触发 refresh。

### 3.4 筛选草稿与已提交 Query

2026-08-29 起采用混合提交语义：商品类型、状态和“是否包含删除记录”是离散按钮，点击后立即替换对应的已提交条件并请求第 1 页；商品名称是文字草稿，只有点击“查询”后才 trim 并进入已提交 Query。按钮即时查询必须组合上一次已经提交的文字条件，不能读取输入框里尚未提交的新文字，否则一次类型切换会偷偷改变两个维度。

“不含删除记录 / 包含删除记录”使用两个并列按钮，不再用一个按钮的文案变化表达布尔状态。商品名称草稿 trim 后与上次已提交名称不同时，界面显示“输入条件尚未应用”浅色提示；点击查询或清空后提示消失。清空操作同时清除文字与按钮条件并立即回到默认第一页。加载更多继续复用同一组已提交条件。

### 3.5 异步返回顺序不等于请求顺序

用户快速更换筛选时，旧请求可能更晚返回。sequence token 只允许最新请求更新 State；同页加载还用 ref 防止重复点击。服务端 `page/pages/total` 是分页事实，前端不根据数组长度猜测。

### 3.6 动态路由是外部输入

Product ID 和 type 都来自路由字符串。ID 必须是正安全整数，type 必须是 `experience|kit`。校验失败直接显示无效地址，不尝试用 0 请求，也不在 Experience 404 后猜测并请求 Kit。

### 3.7 逻辑删除不是恢复按钮

`include_deleted=true` 只让管理员看见历史记录，`is_deleted` 只用于标识。后端没有恢复 Product 契约时，前端不能从“可查询”推导“可恢复”。

## 4. 测试与错误定位

本阶段测试覆盖：Query/Bearer 投影、管理草稿合法空值、非法状态/金额/UTC/库存、类型专属详情、路由边界、筛选换页、权限前置守卫、固定登录回跳、缺失配置展示与详情导航。

最终工程门槛：

```text
TypeScript strict                         PASS
ESLint（全 src，0 warning）               PASS
Stylelint（全 CSS/SCSS）                  PASS
OpenAPI generated type drift             PASS
Phase 8.1 定向前端                        8 suites / 39 tests PASS
完整前端 Jest                             37 suites / 240 tests PASS
Product API 后端                          52 tests PASS
完整后端 SQLite                           1445 passed / 9 MySQL-only skipped
weapp / alipay / tt / h5 production build PASS
git diff --check                          PASS
```

首次 Node 工具冷扫描在 Windows 上出现极慢文件加载；所有结论都来自最终真实退出码。后续热跑恢复正常。React 组件测试仍输出项目已记录的 Taro Test Utils `ReactDOMTestUtils.act` 弃用告警；H5 保持 276 KiB 主 JS / 360 KiB 入口体积告警与 Webpack `[hash]` 告警。四端构建在隔离临时副本执行，避免覆盖用户任务前已运行的 weapp watch；构建后临时联接与目录均已清理。

2026-08-25 用户完成微信开发者工具 Functional：Guest 固定入口登录跳转、普通用户边界、ADMIN 登录返回、筛选/分页、Experience/Kit 详情、断网重试和只读无 mutation 按钮均通过。清单中的 Draft 空配置与逻辑删除标记因当前环境没有对应商品而未执行真实数据验证；这两个形状已有 Endpoint、Hook 和页面自动化覆盖，待后续具备真实样本时补测，不误记为人工通过。同期根据真实设备截图把首页账号信息与操作按钮拆成两层，按钮文字保持单行，窄屏空间不足时整颗按钮换行。

为补测上述两个场景，仓库提供严格限制为 development + 仓库内 SQLite 的 ADMIN Product Seed。它通过正式 Product Service 创建两个 Draft，并将第三个 Draft Kit 通过正式删除用例逻辑删除，因此 Product 与 AuditLog 保持一致；重复执行按保留名称跳过，不会重复造数据：

```powershell
.\.venv\Scripts\python.exe -m app.tasks.admin_product_functional_seed `
  --operator-username dev_super_admin `
  --apply `
  --confirm-local-only
```

样本名称固定为：

- `[LOCAL-ADMIN-FE] Draft 空配置体验`：无描述、封面、Option、dimensions 和展示价格；
- `[LOCAL-ADMIN-FE] Draft 无封面材料包`：价格 `49.90`、库存 `0`，无封面；
- `[LOCAL-ADMIN-FE] 已逻辑删除材料包`：价格 `19.90`、库存 `0`，`is_deleted=true`。

逻辑删除样本默认不会出现在列表中；必须开启“包含已删除”后查询。脚本不创建图片文件、不调整库存，也不触碰原有 `[LOCAL-FE]` Online 商品。

2026-08-25 用户使用上述三个真实样本完成剩余补测，确认 Draft 空配置、无封面 Kit、包含/排除逻辑删除记录、删除详情标记及无恢复按钮均通过；Phase 8.1 微信 Functional 至此全部收口。

常见定位顺序：

1. 页面没有请求：先看 Auth 状态和角色前置守卫；
2. URL/Query 错误：看 Endpoint 白名单投影与已提交 filters；
3. 收到 200 仍报错：看 Runtime Guard 对哪一字段拒绝；
4. 列表被旧数据覆盖：检查 sequence 是否属于最新筛选；
5. 详情 40401：检查列表传入的 Product type 与 ID，不做跨类型回退。

## 5. 下一步

按 Phase 8 规划进入 8.2：先冻结 Experience/Kit 创建、基本信息 PATCH 和逻辑删除的表单、失败与恢复语义，再实现写操作。8.2 不顺带实现 Option、图片上传、上下架或库存。
