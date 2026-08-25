# Phase 7 学习笔记：本地购物车与持久化

> 状态：**Phase 7.1 已完成。** 代码、自动化和微信 Functional 均已通过；2026-08-24 用户确认此前剩余的“有库存 Kit 加入且无 Experience 配置”界面分支通过。Phase 7.2 确认页与创建订单也已完成，详见 [Phase 7.2 学习笔记](phase7_order_create.md)；订单列表/详情/取消和 ADMIN 状态操作仍属于后续步骤。

## 1. 为什么先做本地购物车

Product 详情是服务端状态，购物车是用户在当前设备上的临时选择。两者的所有者不同：

```text
Product 详情       FastAPI 权威，页面按需查询
购物车选择         当前设备本地状态，允许游客先选择
Order              FastAPI 权威，登录后一次性创建
订单金额/库存/状态  FastAPI 权威，客户端不能自证
```

如果一开始就把购物车当成 Order，容易产生三个错误：

1. 把本地显示价格当成最终金额；
2. Product 改价、下架或库存变化后仍认为旧缓存有效；
3. 网络超时时自动重复 POST，可能创建两张订单。

因此第一步先把本地选择建模清楚，下一步才把它转换成最小 Order 请求。

## 2. 后端契约如何决定 CartItem

后端 Order 创建要求：

- 每单 1–10 个不同 Item；
- `quantity` 为 1–99；
- 唯一身份是 `(product_id, experience_option_id)`；
- Experience 必须提交真实有效的正整数 Option ID；
- Kit 必须省略 Option 或提交 `null`；
- 客户端不能提交商品名、配置、价格、小计、总额、库存、状态或用户 ID。

前端内部使用 camelCase，本地展示字段与服务端请求字段明确分开：

```ts
type CartItem = ExperienceCartItem | KitCartItem

interface ExperienceCartItem {
  productType: 'experience'
  productId: number
  experienceOptionId: number
  configurationLabel: string
  quantity: number
  // productName / unitPrice / imageUrl 只用于本地预览
}

interface KitCartItem {
  productType: 'kit'
  productId: number
  experienceOptionId: null
  configurationLabel: null
  quantity: number
}
```

### 新知识点：判别联合类型

`productType` 是判别字段。TypeScript 看到 `productType === 'experience'` 后，就知道 Option 一定是 `number`；看到 `kit` 后，就知道 Option 一定是 `null`。

这比一个宽松接口更安全：

```ts
// 编译期即失败：Kit 不允许携带 Option。
const invalid: CartItem = {
  productType: 'kit',
  experienceOptionId: 123,
  // ...
}
```

类型检查保护的是我们自己写的代码；Storage 仍是外部输入，所以恢复时还必须做运行时校验。

## 3. 重复加入为什么在购物车合并

后端不会静默合并重复 Item，而是拒绝重复 `(product_id, experience_option_id)`。本地购物车采用以下 UX 策略：

- 再次加入同一 Experience Option：合并 quantity；
- 同一 Experience 的不同 Option：保持不同条目；
- 再次加入同一 Kit：合并 quantity；
- 合并后超过 99：前端立即拒绝；
- 已有 10 个不同组合后再加新品：前端立即拒绝。

这样发送请求前天然没有重复组合，但后端仍会独立校验，不能因为前端做过检查就放松服务端规则。

## 4. Storage 为什么必须从 unknown 开始

Storage 可能来自旧版本、用户调试、插件、损坏写入或未来代码。`Taro.getStorage()` 读出的内容不能因为“是我们以前写的”就直接断言成 `CartItem[]`。

当前持久化格式：

```json
{
  "version": 1,
  "items": []
}
```

恢复步骤：

1. 读取 `pinkdoohub.cart.v1`；
2. 把结果视为 `unknown`；
3. 校验版本、数组长度和每个字段；
4. 校验 Experience/Kit 的跨字段一致性；
5. 校验组合没有重复；
6. 任何结构错误都删除整份坏缓存并恢复为空购物车；
7. 合法数据也重新按白名单投影后写回，清除多余字段。

购物车不保存 Token、密码、User、remark 或任何个人资料。当前是**设备级游客购物车**：登录和退出不会自动清除，方便游客先选商品再登录；它不是某个账号的服务端购物车。

## 5. 为什么先写 Storage，再更新 React

一次本地修改有两种常见策略：

```text
乐观更新：先改 UI → 写 Storage → 失败时回滚
保守更新：先写 Storage → 成功后发布 UI 状态
```

本阶段选择保守更新。购物车写入规模很小，Storage 延迟低，避免回滚代码和“页面显示已加入、重启却消失”的伪成功。

`CartStore` 还使用 Promise 队列串行化 mutation。两个快速点击如果同时从 quantity=1 读取并各写 quantity=2，会丢失一次更新；串行执行后结果稳定为 3。

### 新知识点：并发不只存在于后端

JavaScript 单线程不等于异步操作不会竞态。两个 Promise 可以在等待 Storage 时交错；“读旧值—计算—写新值”仍然可能发生 lost update。

## 6. Store、Context 与 Page 的职责

```text
Product Detail Page
    ↓ 构造经过类型约束的 AddCartItemInput
CartContext
    ↓ 只负责 React 注入和订阅
CartStore
    ↓ 规则、串行 mutation、运行时校验
StoragePort
    ↓
TaroStorageAdapter
```

- `CartStore` 不依赖 React，可在 Jest 中直接测试；
- `CartContext` 让详情页和购物车页共享同一个 Store；
- `StoragePort` 让测试使用内存 Fake，不需要微信开发者工具；
- `CartProvider` 与 `AuthProvider` 相互独立，游客也能恢复购物车；
- 首版没有引入 Redux/Zustand，因为当前复杂度没有证明需要第三方状态库。

## 7. Product 详情如何构造购物车条目

Experience 使用当前实际选中的 `option.id`，不能根据时长、人数、日期类型自行拼出不存在的组合：

```ts
buildExperienceCartItem(detail, selectedOption)
```

该函数还会确认 Option 确实属于当前详情。Kit 固定构造 `experienceOptionId: null`；无库存时按钮禁用，但真正下单仍由后端事务内重新锁定并检查库存。

本地 `unitPrice` 是 Product 详情当时的两位小数字符串，只用于“预览单价”。本轮没有用 JavaScript `number` 或浮点数计算总价。

## 8. CartItem 如何变成 Order 请求

`buildOrderItems()` 执行显式白名单映射：

```ts
// Experience
{ product_id, experience_option_id, quantity }

// Kit
{ product_id, quantity }
```

以下本地字段全部不会进入请求：

- `productName`；
- `configurationLabel`；
- `unitPrice`；
- `imageUrl`；
- `productType`。

下一步创建订单时，后端会根据 Product/Option/Kit 的当前事实生成名称、配置、单价、小计和总额快照。

## 9. 自动化测试

新增 3 个套件、17 项测试：

- 空 Storage 恢复；
- 版本错误、重复组合、Kit 带 Option 等坏数据清理；
- 合法缓存白名单重写；
- 两次并发加入的串行合并；
- 同 Product 不同 Option 保持独立；
- 10 Item / 99 quantity 边界；
- Storage 写失败不发布伪成功；
- 数量修改、移除和清空；
- Order 请求只包含允许字段；
- Experience/Kit 详情映射；
- 外部 Option 拒绝；
- Cart 页面 initializing/error/empty/content 与数量操作。

最终自动化结果：

```text
TypeScript strict        PASS
ESLint --max-warnings=0  PASS
Stylelint                PASS
OpenAPI drift check      PASS
Jest                     14 suites / 87 tests PASS
weapp watcher output     PASS（app.json + Cart 页面产物）
alipay build             PASS
tt build                 PASS
h5 build                 PASS
```

已知非阻断警告：

- Taro Test Utils 间接使用旧 `ReactDOMTestUtils.act`；
- H5 Webpack `[hash]` 弃用警告；
- H5 app 入口 334 KiB、主 JS 251 KiB，超过 244 KiB 性能建议线。

## 10. 微信开发者工具 Functional

自动化完成后人工验证。2026-08-22 用户已完成其余项目；当前只需复测第 5 项的有库存分支：

1. 游客打开一个 Experience，切换到第二个真实 Option；
2. 点击“加入购物车”，进入购物车，确认配置和预览价属于第二个 Option；
3. 再加入同一 Option，确认 quantity 合并；
4. 加入同 Product 的另一个 Option，确认出现第二行；
5. 打开 `[LOCAL-FE] 拼豆材料包 01`（Product ID 7，当前 Seed 库存 8），确认按钮可用并加入购物车，且没有 Experience 配置；
6. 修改数量、移除条目；
7. 关闭并重新编译/打开小程序，确认购物车恢复；
8. 登录、退出，确认本地购物车仍存在；
9. 在 Console 把 `pinkdoohub.cart.v1` 改成坏版本，再重新打开，确认安全恢复为空；
10. 打开另外任一 `[LOCAL-FE] 拼豆材料包 02`–`06`，确认库存 0 且加入按钮禁用。

第 5 项通过后，Phase 7.1 的微信 Functional 才完整收口。

## 11. 下一步

Phase 7.2 已按上述 Cart→Order 边界实现确认页、登录返回、一次性创建、未知结果和成功后对账。下一步是：

1. 完成上面第 5 项有库存 Kit 的微信界面复测；
2. 按 [Phase 7.2 学习笔记](phase7_order_create.md) 完成真实登录、Experience/Kit/混合订单、库存不足与弱网未知结果的微信 Functional；
3. 进入 Phase 7.3 我的订单列表/详情/取消，为未知结果提供服务端权威查询入口。

在后端提供 Order create 客户端幂等键之前，网络超时后的恢复策略仍必须优先查询订单权威状态，不能简单再 POST 一次。
