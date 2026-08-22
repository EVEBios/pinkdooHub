# Phase 6 学习笔记：公开 Product 列表

> **Date:** 2026-08-20
>
> **Status:** Endpoint、Runtime Guard、分页 Feature、首页四态、图片地址解析、搜索/类型筛选和自动化已完成；微信开发者工具的游客、Content、Empty、Error 恢复、登录/退出、相对图片、超过 10 条分页与筛选/搜索 Functional 已通过
>
> **对应代码:** `miniapp/src/api/endpoints/products.ts`、`miniapp/src/features/product/`、`miniapp/src/pages/index/`、`miniapp/src/utils/asset_url.ts`

这一步把首页从“登录后的占位页”改成真正的公开商品入口。游客不需要 Token 就能浏览 Online Product；登录状态只影响页头的登录、昵称和退出操作，不决定 Product 能否加载。

## 1. 本步范围

已实现：

- `GET /api/v1/products` 薄 Endpoint；
- 生成类型 + 运行时逐字段 Guard；
- 第 1 页固定 `page_size=10`；
- 按服务端 `page/pages/total` 加载下一页；
- Loading、Empty、Error、Content 四态；
- 首屏失败重试与加载更多失败重试；
- 迟到旧响应不得覆盖较新请求；
- Experience 显示“起”，Kit 显示固定价格；
- 相对图片 URL 统一补全 API Origin；
- 图片失败占位；
- 游客浏览、已登录昵称和退出入口共存。

暂未实现：

- keyword 搜索和防抖；
- Experience / Kit 筛选；
- 下拉刷新；
- Product 详情页；
- Experience Option 有效组合；
- ProductCard 点击导航；
- 真机、H5 和正式图片域名验证。

## 2. 完整调用链

```text
ProductListPage
  → useProductList Feature
    → ProductApi.listProducts()
      → ApiClient
        → TaroHttpTransport
          → GET /api/v1/products?page=1&page_size=10
            → FastAPI Product Service / Repository / Mapper
          ← 统一 SuccessResponse[Page[ProductListItemOut]]
        ← 信封解析
      ← Product Page Runtime Guard + 白名单投影
    ← loading / empty / error / content
  ← ProductCard + 分页操作
```

Page 不处理 Token、HTTP 信封或 URL Query。Endpoint 不依赖 React。Feature 负责请求和页面状态，页面只负责展示和用户事件。

## 3. 生成类型为什么还不够

OpenAPI 生成的类型让 TypeScript 知道预期结构：

```ts
type ProductListItem = components['schemas']['ProductListItemOut']
type ProductListPage = components['schemas']['Page_ProductListItemOut_']
```

这只能检查我们编写的 TypeScript，不能改变网络返回的 JSON。服务器、代理、旧版本或错误数据都可能在运行时返回：

- `id: -1`；
- `product_type.value: "unknown"`；
- `display_price: 299`；
- `display_price: "299"`；
- 不支持的图片相对路径；
- `page: 0`；
- `items` 不是数组。

因此 Endpoint 把 HTTP Client 结果先当成 `unknown`，校验后才返回 `ProductListPage`。Guard 还重新构造白名单对象，意外多出的内部字段不会自动进入 UI。

知识点：

- TypeScript 类型在编译后会被擦除；
- `unknown` 表示“必须先证明才能使用”；
- `as ProductListPage` 只是告诉编译器相信我们，不会验证 JSON；
- Runtime Guard 是网络信任边界的一部分。

## 4. 金额为什么继续使用字符串

后端列表价格固定为两位小数字符串：

```text
"299.00"
```

Endpoint Guard 校验：

- 必须有两位小数；
- 必须大于 0；
- 不能超过后端 Product 价格上限；
- 不接受指数形式、数字类型或客户端四舍五入结果。

页面只把字符串交给 `formatPrice()` 增加千分位，不用 JavaScript `number` 计算权威金额。体验商品是否显示“起”来自 `product_type.value`，不是根据价格猜测。

## 5. Enum 的 value 与 label

响应示例：

```json
{
  "value": "experience",
  "label": "拼豆体验"
}
```

规则：

- 业务判断使用 `value`；
- 用户展示使用 `label`；
- 不根据中文 label 推断类型；
- 未知 `value` 视为契约错误。

因此“体验价格显示起”判断的是：

```ts
product.product_type.value === 'experience'
```

而卡片标签展示后端返回的 `product_type.label`。

## 6. 四态不是四个互不相关的 boolean

如果分别保存：

```text
isLoading / isEmpty / hasError / hasData
```

就可能产生矛盾组合，例如同时 `isLoading=true` 和 `isEmpty=true`。当前使用判别状态：

```ts
type ProductListStatus = 'loading' | 'empty' | 'error' | 'content'
```

状态含义：

| 状态 | 页面行为 |
|------|----------|
| loading | 首屏请求中，显示加载说明 |
| empty | 请求成功但 `items=[]`，说明当前无 Online Product |
| error | 首屏请求失败，显示安全错误与重新加载按钮 |
| content | 显示卡片、总数和分页操作 |

加载下一页失败时不丢掉已有 Content，而是在卡片下方展示错误并允许重试同一下一页。

## 7. 分页为什么使用服务端事实

客户端请求：

```text
page=1&page_size=10
```

后续是否还有下一页，使用服务端：

```text
page < pages
```

不能用“本页刚好有 10 条”猜测还有下一页，因为最后一页也可能正好等于 page size；也不能自己根据当前数组长度重算 total，因为服务端筛选结果可能随数据变化。

加载下一页时：

- 保留现有 items；
- 阻止同一时刻重复加载更多；
- 成功后追加新 items；
- 使用新响应覆盖 `total/page/pages`；
- 没有下一页时按钮消失。

## 8. 请求竞态与迟到响应

网络响应顺序不一定等于请求发出顺序：

```text
请求 A 发出
用户点击重试，请求 B 发出
请求 B 先成功
请求 A 后返回
```

如果 A 仍然写入 State，就会用旧结果覆盖新结果。Feature 为每次请求递增 sequence；只有与当前 sequence 相同的响应可以更新 State。

当前没有强依赖全局 `AbortController`。原因是它虽然存在于 DOM TypeScript 声明中，但不能由此推断所有微信、支付宝和抖音小程序运行时都原生实现。请求序号是一种不依赖浏览器全局 API的跨端保护。

本阶段尚无搜索输入；后续加入搜索/筛选时继续复用该原则，并在筛选变化时重置 items/page。

## 9. 相对图片 URL

开发后端可能返回：

```text
/uploads/products/<uuid>.webp
```

小程序页面不能把它当作完整远端地址。唯一 `resolveAssetUrl()` 规则是：

- HTTP(S) 绝对地址原样使用；
- `/` 开头的地址拼接已校验 API Origin；
- 其他相对形式拒绝；
- 各页面禁止各自硬编码 `localhost` 或重复拼接。

图片加载失败只改变卡片展示为占位文案，不把 Product 本身从列表删除。

## 10. 公开 Product 与认证状态解耦

Product 列表是公开接口，Endpoint 使用 `auth: 'none'`，即使 Storage 中有 access token 也不会附带 Authorization。

页面仍然读取 AuthContext，用于：

- guest 显示登录按钮；
- authenticated 显示昵称和退出；
- initializing 显示会话恢复提示；
- auth error 明确“不影响浏览”。

Product 数据不放进 AuthContext。Context 只承担跨页面共享的认证状态；列表由页面 Feature 自己拥有，避免所有业务数据都变成全局状态。

## 11. 自动化测试分层

| 层级 | 验证内容 |
|------|----------|
| Product Endpoint | 精确 Query、无认证头、空页、坏 ID/Enum/Money/Image/Page 拒绝 |
| Asset Resolver | 绝对 URL、相对 URL 补全、非法路径拒绝 |
| Product Feature | 第一页、下一页追加、服务端分页事实、旧响应不覆盖新结果 |
| Page | Loading/Empty/Error/Content、Experience 起价、Kit 固定价格 |
| Type/Lint | strict TypeScript、ESLint、Stylelint |
| Build | Taro 微信、支付宝、抖音与 H5 真实编译 |

Jest 全局 setup 统一 mock Taro 4.2.1 router 循环依赖，并为 jsdom 提供 `IntersectionObserver`，使 `Image lazyLoad` 测试不产生无关运行错误。已有的 `ReactDOMTestUtils.act` 弃用提示来自当前 Taro Test Utils 上游，暂不隐藏。

## 12. 微信开发者工具 Functional 清单

自动化和 Build 通过后仍需人工验证。2026-08-21 已完成其中的游客、Empty、Error 恢复以及登录/退出后继续浏览；其余项目保留为下一轮：

1. ✅ FastAPI、Redis 和 `npm run dev:weapp` 均在运行；
2. ✅ 清理 Storage 后打开首页，不登录也能请求 Product；
3. Network 中确认 `GET /api/v1/products?page=1&page_size=10` 无 Authorization；
4. ✅ 没有 Online Product 时显示 Empty，而不是错误；
5. 有 Experience 和 Kit 时分别显示“起”和固定价格；
6. 相对 `/uploads/products/...` 图片能通过 API Origin 加载；
7. 图片文件不可用时显示占位，不导致页面崩溃；
8. 超过 10 个 Online Product 时出现“加载更多”，点击后追加且不替换第一页；
9. ✅ 关闭 FastAPI 后重新加载，显示 Error 和重试；恢复 FastAPI 后重试成功；
10. ✅ 登录后返回首页显示昵称，退出后仍可继续浏览 Product。

如果本地数据库没有完整 Online Product，可以使用下面的本地开发脚本。脚本内部仍调用现有 Product Service 创建 Product、Option/Kit 价格和图片并上架，不会直接修改表字段绕过 readiness 规则。

## 13. 本地 Product 功能测试数据

脚本入口：`app/tasks/product_functional_seed.py`。

运行前确认：

- `.env` 中 `APP_ENV=development`；
- `.env` 中 `DB_ENGINE=sqlite`；
- `DB_SQLITE_PATH` 和 `PRODUCT_IMAGE_UPLOAD_DIR` 都位于当前仓库内；
- 本地库已有一个启用的 `ADMIN` 或 `SUPER_ADMIN` 用户；
- FastAPI 可以暂时保持关闭，避免同时调试时混淆日志；脚本会自行连接数据库。

PowerShell 命令：

```powershell
Set-Location D:\pinkdooHub

.\.venv\Scripts\python.exe -m app.tasks.product_functional_seed `
  --operator-username <本地管理员用户名> `
  --apply `
  --confirm-local-only
```

它会生成：

- 6 条 `[LOCAL-FE] 拼豆体验 xx`；
- 6 条 `[LOCAL-FE] 拼豆材料包 xx`；
- 1 条 `[LOCAL-FE] 多配置拼豆体验`；
- 每条 Product 的公共封面；
- 6 条普通 Experience 各有一个有效 Option；多配置 Experience 有两个不同的完整 Option，分别为 `60 分钟 + 1 人 + 工作日 + ¥59` 与 `120 分钟 + 2 人 + 节假日 + ¥89`；
- 每个 Option 都有专属图片，多配置 Experience 的两张 Option 图片使用不同像素配色，切换时肉眼可辨；
- 共 13 条 Online Product 和 21 个本地 PNG，可覆盖两种价格展示、相对图片、第二页和详情 Option 切换。

2026-08-21 首版脚本暴露了一个测试夹具缺陷：旧文件只有 PNG 签名和 IEND 结尾，能够通过当时的轻量文件签名校验，但没有 IHDR、IDAT、像素数据和完整 CRC，因而无法被 Windows 或微信解码。脚本现已改为用标准库生成结构完整的 2×2 RGB PNG；每个 chunk 都包含正确长度和 CRC，IDAT 使用 zlib 压缩真实像素。再次运行时只修复 `[LOCAL-FE]` Product 已引用、且内容精确等于旧错误夹具的文件或缺失文件，不覆盖其他上传内容。2026-08-22 增量 Seed 后，本地库共有 21 个文件，Windows `System.Drawing` 独立解码全部成功；多配置 Experience 第二个 Option 若仍引用脚本早期生成的默认配色，则只在内容精确匹配该旧夹具时迁移为备用配色。

重复运行时，完整的同名 Online 数据会被跳过；脚本不会重复制造 13 条。如果保留名称已被 Draft、Offline、逻辑删除或错误类型占用，命令会停止，要求开发者先检查异常数据，而不是猜测如何覆盖。

脚本没有提供批量物理删除功能。需要清理时应通过正式管理能力先下架再逻辑删除；如果希望长期自动清理，应作为独立需求设计并测试审计、图片生命周期和 Inventory/Order 引用边界。

### 新知识点：Seed Script 也是应用入口

测试数据脚本与 HTTP API 的共同点是它们都会触发业务操作。两者只在输入适配层不同：API 从 HTTP 读取输入，脚本从 CLI 读取输入。因此脚本应该复用 Service、Repository、Validator 和存储适配器，而不是直接写 Model。

本脚本还有三层“纵深防御”：配置环境限制回答“允许在哪运行”，路径限制回答“允许写到哪里”，显式双参数和管理员身份回答“谁确认了这次写入”。任何单一条件配置错误时，其余条件仍能阻止误操作。

图片文件先写入磁盘、再登记数据库；如果数据库登记失败，脚本会补偿删除刚写入的文件。这不是完整的跨资源事务，因为普通文件系统无法加入数据库事务，但补偿操作可以避免最常见的孤儿文件。

另一个知识点是“文件签名正确”不等于“文件可解码”。上传边界的头尾签名检查只能做低成本初筛；端到端测试夹具仍必须是结构完整的真实格式。本阶段新增测试会遍历 PNG chunks、核对 CRC、解压 IDAT 并检查像素行，再使用 Windows 图片解码器复核当前开发文件，避免生成器用自己的宽松规则证明自己正确。

### 新知识点：测试数据也需要可观察性

两个 Option 只拥有不同图片 URL 还不够；如果像素内容完全相同，人工测试只能在调试器里观察 URL，无法从界面确认图片是否真的随选择变化。专用 Seed 因此让两个 Option 同时具有不同组合、不同价格和不同像素配色。一个行为最好至少有一个直接可见的输出，这叫可观察性；它能降低测试者把“点击成功”误判为“状态联动成功”的风险。

## 14. 类型筛选与 keyword 防抖搜索

首页现提供“全部 / 拼豆体验 / 材料套装”类型筛选和最长 100 字符的受控搜索框。类型切换立即生效；keyword 保留用户正在输入的原始状态，停止输入 300ms 后才去除首尾空白并成为已生效查询。筛选变化统一重新请求第 1 页，加载更多则继续携带相同的 `product_type` 和 `keyword`。

### 新知识点：受控输入

`Input.value` 来自 React state，`onInput` 再把新值写回 state，这叫受控输入。它让界面显示值、长度限制和查询状态有单一事实来源。这里没有直接拿输入事件调用 API，否则每输入一个字都会发一次请求。

### 新知识点：防抖不是节流

防抖会在每次输入后重新计时，只有连续 300ms 没有新输入才执行；节流是在连续操作期间按固定间隔执行。搜索框适合防抖，因为用户通常希望完整词语形成后再查询。`useEffect` 返回 `clearTimeout` 清理函数，确保下一次输入和组件卸载都会取消旧计时器。

### 新知识点：原始状态与已生效状态

`keyword` 负责让输入框即时响应，`debouncedKeyword` 负责触发网络请求。两者分开后，用户敲键不会感觉界面延迟，但 API 仍能减少无价值请求。首尾空白只在生效边界归一化；纯空白最终省略 `keyword`，而不是发送空字符串。

### 新知识点：筛选与分页是同一个查询上下文

从“全部第 2 页”切换到“材料套装”时，不能继续请求第 2 页，因为 total/pages 已属于另一组查询。任何筛选变化都必须清空旧 items 并回到第 1 页；之后加载更多必须携带同一组筛选条件。已有 sequence token 同时保护筛选请求：旧查询即使晚返回，也不能覆盖当前查询。

### 新知识点：TypeScript 字面量联合类型

`ProductTypeFilter = 'all' | 'experience' | 'kit'` 把 UI 允许值收紧为有限集合。`all` 是界面状态，不是后端 `ProductType`，所以构造 Query 时省略 `product_type`；另外两个值才映射到 API。相比普通 `string`，拼写错误会在编译期暴露。

## 15. 下一步

类型筛选、组合搜索、Empty、快速连续输入和筛选后的分页已在微信开发者工具通过。Experience / Kit 详情和有效 Option 组合也已完成自动化与微信 Functional，详见 [Phase 6 Product 详情学习笔记](phase6_product_detail.md)。下一阶段进入本地购物车、确认页和 Order 创建。
