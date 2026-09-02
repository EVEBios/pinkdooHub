# Phase 6 Product 详情与有效 Option 学习笔记

> **Status:** Experience/Kit 公开详情 Endpoint、Runtime Guard、动态路由、详情四态、图片展示、Kit 库存提示与 Experience 有效 Option 组合选择已实现；自动化门禁与微信开发者工具 Functional 已通过
>
> **Date:** 2026-08-22

## 1. 本阶段目标

从公开 Product 列表点击卡片进入详情页，并严格沿用后端已实现的两条类型专属契约：

```text
Experience → GET /api/v1/products/experience/{id}
Kit        → GET /api/v1/products/kit/{id}
```

两个接口都不需要认证。类型不匹配、未上架、已删除和不存在统一由后端隐藏为 `40401`；前端不会在一个类型端点失败后自动尝试另一个端点，以免发出多余请求或模糊真实契约。

## 2. 动态路由参数

Taro 页面注册使用静态路径 `pages/product-detail/index`，业务参数通过 Query 传递：

```text
/pages/product-detail/index?id=12&type=experience
```

`buildProductDetailUrl()` 只接受正安全整数 ID 和后端 `ProductType`。进入页面后，`parseProductDetailRoute()` 再把路由中的字符串视为不可信输入，拒绝缺失、0、负数、小数、非数字以及 `all`/未知类型。

### 新知识点：TypeScript 类型不会验证 URL

函数内部的 `productId: number` 能约束调用代码，但微信页面 URL 最终仍是字符串，可能来自历史链接、二维码、手工修改或其他页面。因此动态路由和 HTTP JSON 一样，必须在运行时解析和校验。

## 3. 两条详情 Endpoint 与联合类型

Endpoint 复用 OpenAPI 生成类型：

```ts
type ProductDetail = ExperienceProductDetail | KitProductDetail
```

请求结果先保持 `unknown`，再由独立 Runtime Guard 白名单投影。共同字段包括 ID、名称、描述、类型和公共图片；Experience 额外校验 dimensions/options/Option 图片，Kit 额外校验金额、非负库存以及 `available === (stock > 0)`。

### 新知识点：嵌套判别字段需要 type predicate

生成类型的判别值位于 `detail.product_type.value`，不是顶层 `detail.type`。TypeScript 不会在所有表达式中自动把这个嵌套检查传播到最外层联合，因此页面提供：

```ts
function isExperienceDetail(detail: ProductDetail): detail is ExperienceProductDetail
```

返回类型中的 `detail is ExperienceProductDetail` 叫作 type predicate。它同时表达运行时判断和编译器缩窄证明，使 Experience 分支可以安全读取 `options`，Kit 分支可以安全读取 `stock`。

## 4. 详情状态与请求竞态

`useProductDetail()` 使用明确的三态联合：

```text
loading
error + errorMessage
content + detail
```

路由参数非法不发 HTTP 请求，由页面直接显示“无法打开商品”。合法路由进入 Hook；失败可以重试。请求使用 sequence token，页面卸载、ID/类型变化或重试后，旧响应不能覆盖新详情。

## 5. 为什么第一版选择完整 Option 卡片

Experience API 虽然同时返回 durations、participants、day_types 三组 dimensions，但数据库权威对象是完整 `ExperienceOption`：

```text
Option = duration + participants + day_type + price + images
```

各维度分别有值，不代表它们任意组合都存在。例如后端只有：

```text
60 分钟 + 1 人 + 工作日
120 分钟 + 2 人 + 节假日
```

前端不能据此制造：

```text
60 分钟 + 2 人 + 节假日
```

第一版因此把每个服务端 `option.id` 渲染成一张完整组合卡片。用户选择的永远是一个真实 Option；选中后价格和专属图片都从同一对象读取。未来若改为三级选择控件，也必须基于已有 Options 逐步过滤可选值，最后精确匹配一个 Option，不能直接计算三个维度的笛卡尔积。

## 6. Product 公共图片与 Option 专属图片

详情保留两层图片语义：

```text
detail.images          → Product 公共图片
selectedOption.images  → 当前 Experience Option 专属图片
```

Option 图片不回退到 Product 公共图。所有相对 `/uploads/...` 地址仍通过唯一 `resolveAssetUrl()` 补全 API Origin；单张图片失败只显示局部占位，不让整个详情进入 Error。

## 7. Kit 库存为什么只用于展示

Kit 详情展示：

- `price`：后端金额字符串；
- `stock`：详情请求时的库存快照；
- `available`：后端 Mapper 派生的 `stock > 0`。

页面明确提示“库存仅供展示”。用户停留详情页期间库存可能被其他订单改变，未来创建订单时必须由后端在事务和行锁内重新校验；前端不得因详情里 `available=true` 就假设下单一定成功，也不得自行扣减本地库存冒充服务端结果。

## 8. 自动化边界

新增测试覆盖：

- Experience/Kit 使用正确的公开路径且不携带 Authorization；
- 合法详情 JSON 被白名单投影；
- 错误类型、空 Option 图片、非法金额、负库存、available/stock 矛盾被拒绝；
- 合法动态路由与 URL 构造；
- 缺失、非整数、非正数和未知类型路由被拒绝。

2026-08-22 已补齐全部门禁：`tsc --noEmit`、ESLint `--max-warnings=0`、Stylelint 与 OpenAPI `--check` 均以退出码 0 完成；完整 Jest 为 11 套件、70 项全部通过。Jest 只有 `@tarojs/test-utils-react` 间接使用旧 `ReactDOMTestUtils.act` 的已知上游弃用警告。weapp/alipay/tt/h5 四端生产构建均通过；微信为避免与用户 watcher 同写 `dist/weapp`，在系统临时副本中复用同一 `node_modules` 隔离构建，并核对详情页 JS/WXML/WXSS 产物。H5 入口仍为 327 KiB，单个 app JS 为 245 KiB，保留 Webpack 244 KiB 性能建议和 `[hash]` 上游弃用警告。完整后端 SQLite 套件为 1442 项通过，9 项需要显式隔离 MySQL 8+ Schema 的可选门槛按配置跳过。

本机首次从 `node_modules` 加载大型包非常慢：最小 `require('typescript')` 冷加载为 86.7 秒，紧接着新进程热加载仅 0.7 秒；完整 typecheck、Jest、ESLint 与支付宝构建也受相同文件扫描延迟影响。门禁结论只依据真实退出码，不再把长时间无输出当作失败或成功。

## 9. 微信开发者工具 Functional

1. 从 Experience 卡片进入详情，请求只命中 `/products/experience/{id}`；
2. 公共图片、名称、描述与类型正确；
3. 每个 Option 卡片都是一条真实组合，切换后价格和专属图片同步变化；
4. 从 Kit 卡片进入详情，请求只命中 `/products/kit/{id}`；
5. Kit 显示价格、库存和有货/无货提示；
6. 游客和登录用户均可进入详情，请求无 Authorization；
7. 关闭 FastAPI 后进入详情显示 Error，恢复后重试成功；
8. 手工打开非法 `id/type` URL 时不发详情请求并显示可理解错误；
9. 图片失败只显示局部占位，页面其他内容保留；
10. 返回列表后原有筛选交互仍正常。

2026-08-22 用户确认本轮详情与多配置 Option 切换 Functional 全部通过。

local-only Seed 现包含 `[LOCAL-FE] 多配置拼豆体验`：两个有效 Option 分别是 `60 分钟 + 1 人 + 工作日 + ¥59` 与 `120 分钟 + 2 人 + 节假日 + ¥89`，各有一张不同配色的专属图片。脚本仍通过正式 Product Service、Validator、Audit 和图片存储创建，不直接写表；重复执行会跳过完整的 Online Product。2026-08-22 当前开发库增量执行结果为 `created=1 / skipped=12 / repaired_images=0`，随后迁移第二张旧默认配色时为 `created=0 / skipped=13 / repaired_images=1`；只读核验确认 Product 13 为 Online、两个 Option 各有一张图片且 SHA-256 不同，21 个 PNG 均可由 Windows `System.Drawing` 解码。

### 新知识点：Fixture 不能只满足数据库数量

如果测试只断言“有两个 Option”，那么两个 Option 图片内容相同、价格相同甚至组合字段错误，都可能被漏掉。当前集成测试会从 Online 详情重新读取两个 Option，核对完整组合、价格、关系预加载和图片内容差异。这是在验证可观察行为，而不是只验证某几条 INSERT 是否发生。

## 10. 下一步

Phase 6 公开 Product 列表、筛选、详情与有效 Option 选择已完成，可以进入 Phase 7 Order。购物车条目中 Experience 必须保存真实 `option_id`，Kit 不携带 Option；创建接口当前没有客户端幂等键，不能对结果未知的 POST 自动重试。
