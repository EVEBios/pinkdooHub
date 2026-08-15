# pinkdooHub 前端学习路线

> **Document Version:** v0.1
> **Status:** Draft
> **Last Updated:** 2026-08-15
> **Audience:** 首次系统学习 JavaScript、TypeScript、React 与 Taro 的项目开发者

本项目采用“知识点 → 小练习 → 真实功能 → 测试 → 复盘”的循环，不要求先学完全部前端理论再开始，也不把复制示例代码当作掌握。

---

## 1. 每个阶段的固定学习循环

1. 阅读本阶段概念和官方资料；
2. 写一个不超过单一职责的小练习；
3. 为练习补正常、失败和边界测试；
4. 把概念用于真实页面/Feature；
5. 在微信与 H5 观察运行行为；
6. 主动制造一次错误并读懂报错；
7. 运行本阶段质量门槛；
8. 在 `docs/08_frontend/learning_notes/` 写短复盘。

复盘回答：

- 今天新增了什么概念？
- 它解决了什么真实问题？
- 最容易混淆的点是什么？
- 哪个测试防止了哪种错误？
- 下次如何独立定位？

---

## 2. 阶段路线

| 阶段 | 工程交付 | 新知识 |
|------|----------|--------|
| 0 | 架构文档与 ADR | 架构、边界、ADR、API 契约 |
| 1 | TypeScript 纯函数练习 | JS 运行时、类型、模块、Promise |
| 2 | 四端 Taro Spike | Node/npm、Taro、编译、项目配置 |
| 3 | 正式脚手架 | React 组件、TSX、Props、事件 |
| 4 | HTTP Client | 泛型、unknown、async、错误、JWT |
| 5 | 登录纵向链路 | State、Context、Effect、Storage |
| 6 | Product | 列表、分页、派生状态、组合算法 |
| 7 | Order | 表单、状态机、幂等、未知结果 |
| 8 | Admin | 权限、上传、复杂表单、审计 |
| 9 | 多端发布 | HTTPS、域名、CORS、安全、CI/E2E |

---

## 3. 阶段 0：架构与契约

学习：

- 客户端、服务端、API；
- 分层和依赖方向；
- 什么是架构目标/非目标；
- ADR 为什么记录理由和代价；
- OpenAPI、HTTP Method、Header、Body、Query；
- HTTP status 与业务 code；
- Build、Smoke、Functional。

实践：

- 阅读本目录五份主文档与六个 ADR；
- 用自己的话画出 Page 到 FastAPI 的调用链；
- 从 OpenAPI 找到登录、商品、订单、库存端点；
- 找出一个文档计划和实际 OpenAPI 的差异。

完成标准：能解释为什么业务页面不能直接请求后端，以及为什么隐藏管理按钮不等于权限控制。

---

## 4. 阶段 1：JavaScript 与 TypeScript

先学：

- `const`/`let`；
- string/number/boolean/null/undefined；
- object/array；
- function/arrow function；
- map/filter/find/reduce 的基本用途；
- module import/export；
- Promise 与 async/await；
- interface/type；
- union、可选字段、泛型；
- unknown、类型收窄和 Guard；
- 不可变数据更新。

暂不学：装饰器、高级条件类型、类型体操、复杂类继承。

项目练习：

```text
formatMoney
formatUtcDate
isApiEnvelope
parsePositiveId
resolveAssetUrl
findMatchingExperienceOption
buildOrderItem
```

测试：正常、null/undefined、非法输入、边界和未知 Enum。

关键认识：TypeScript 不改变 JavaScript 运行时；有 TS 类型不代表网络 JSON 真实符合类型；`number` 不能自动解决金额精度。

---

## 5. 阶段 2：Node、npm 与 Taro Spike

学习：

- Node 与浏览器/小程序运行时的区别；
- npm、package、dependency、devDependency、lockfile；
- 本地 CLI 与全局 CLI；
- Taro source/build output；
- `weapp/alipay/tt/h5`；
- Webpack 5 编译；
- 平台开发者工具；
- 环境变量与 secret 的区别。

实践：

- 创建临时最小 Taro React TypeScript 应用；
- 四端生产构建；
- 微信/H5 打开页面；
- 验证一组候选 UI 组件；
- 验证 Request、Upload、Storage；
- 验证 Jest/Taro Test Utils。

完成标准：能解释同一 TSX 如何生成四种平台产物，并能区分编译错误、React 错误和平台运行错误。

---

## 6. 阶段 3：React 基础与正式脚手架

学习顺序：

1. JSX/TSX；
2. 函数组件；
3. Props；
4. 条件/列表渲染和稳定 key；
5. 事件；
6. `useState`；
7. 受控表单；
8. 组件组合。

练习：

- `ProductCard`；
- `PageState`；
- `OrderStatusCard`；
- 登录表单；
- 数量 Stepper。

注意：Props 只读；State 不直接修改；不要用数组 index 当会变化列表的 key；不要在 render 中执行请求。

---

## 7. 阶段 4：请求、错误和异步

学习：

- HTTP 与 Taro.request；
- 泛型 `ApiEnvelope<T>`；
- Runtime Guard；
- Promise 并发；
- Abort/Timeout；
- Bearer JWT；
- Refresh single-flight；
- 错误分类；
- 幂等与自动重试边界；
- Dependency Injection 的简单形式。

实践：

- fake transport；
- 登录成功；
- HTTP 400 + 1006；
- 三请求共享 refresh；
- 403 不刷新；
- empty-body PATCH；
- upload adapter。

完成标准：页面看不到 Token 和信封细节；能解释为什么创建订单超时后不能自动再 POST。

---

## 8. 阶段 5：React Effect、Context 与认证

学习：

- `useEffect` 和依赖数组；
- 清理函数与请求竞态；
- Taro 页面生命周期；
- Context；
- Storage；
- 登录守卫；
- 派生状态与重复状态；
- 敏感信息。

实践：登录、注册、恢复 Session、`/users/me`、登出、普通/ADMIN 入口。

注意：Effect 只处理副作用；能在 render/事件中算出的值不放 Effect；Context 不承载所有业务数据；密码不持久化。

---

## 9. 阶段 6：Product 与 UI 状态

学习：

- 分页；
- 搜索防抖；
- 请求竞态；
- Loading/Empty/Error/Content；
- 派生状态；
- 有效组合而不是无约束笛卡尔积；
- 图片和响应式布局。

实践：公开 Product 列表、搜索/筛选、Experience/Kit 详情、Option 选择。

完成标准：只允许选择真实 Option；Kit stock 只用于展示；旧查询不会覆盖新筛选。

---

## 10. 阶段 7：Order、状态机和幂等

学习：

- 本地缓存与服务端权威；
- Snapshot；
- 状态机；
- 乐观/保守更新；
- 幂等键；
- 网络结果未知；
- 防重复提交。

实践：本地购物车、确认、创建、列表、详情、取消，ADMIN 人工支付/完成。

完成标准：不伪造 Paid；不重复组合；不自动重试无幂等的 Order create；金额只用后端快照。

---

## 11. 阶段 8：Admin、上传与权限

学习：

- 分包；
- 角色入口与后端授权；
- multipart；
- 客户端/服务端文件校验；
- 复杂表单拆分；
- Product readiness issues；
- Inventory Idempotency-Key；
- Audit Log。

实践按 Product → Option → Image → Inventory → Order → Audit → User 顺序接入。

完成标准：普通用户 403；上传/库存错误可解释；同次库存重试复用 key；不存在的后端功能没有按钮。

---

## 12. 阶段 9：多端、CI 与发布

学习：

- HTTPS、DNS、证书；
- 小程序合法域名；
- H5 CORS/CSP/XSS；
- AppID 与 AppSecret；
- Build/Smoke/E2E/真机；
- CI、可重复构建；
- 数据库迁移与回滚；
- 隐私与审核。

实践：微信/H5 Functional，支付宝/抖音 Smoke，再按发布顺序提升平台门槛。

完成标准以 [测试策略](testing_strategy.md) 的正式发布门槛为准。

---

## 13. 依赖引入学习规则

每次想增加包时回答：

1. 标准库、React、Taro 或现有依赖能否完成？
2. 它解决的是已发生问题还是假想问题？
3. 微信/支付宝/抖音/H5 是否支持？
4. 维护、许可证、体积和传递依赖如何？
5. 如何测试和移除？
6. 是否需要 ADR？

不能回答时先不引入。

---

## 14. 学习完成的判断

对一个知识点“学会”至少意味着：

- 能用自己的话解释；
- 能写一个最小例子；
- 能写失败/边界测试；
- 能读懂常见报错；
- 知道它属于哪一层；
- 知道何时不该使用；
- 能在不复制旧实现的情况下完成一个相似任务。

