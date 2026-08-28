# Phase 8.4–8.5 学习笔记：ADMIN 商品图片与上下架

> 状态：**工程实现、自动化和四端生产构建已完成；微信开发者工具 Functional 待验收。** 本阶段开放 Product 公共图、Experience Option 专属图的上传/排序/封面/逻辑删除，以及 Product 上下架和完整 readiness issues。Phase 8.3 延期的“旧订单保留旧快照、新订单使用新价格”已具备真实界面验收条件，一并列入本次清单。

## 1. 范围与调用链

图片上传不是普通 JSON 请求。前端链路明确分层：

```text
Page
  → ImagePickerPort
  → Admin Product Lifecycle Feature
  → AdminProductApi
  → ApiClient.uploadFile
  → TaroFileUploadTransport
  → Taro.uploadFile
```

页面只负责交互和展示；选图平台差异集中在 `ImagePickerPort`；Bearer、统一信封、`1006` refresh 与错误分类由 Client 负责；业务错误、重复提交和结果未知由 Feature 负责。后端仍是权限、文件真实性、图片归属、封面唯一和状态变迁的权威边界。

| 用例 | Endpoint | 请求 | 成功响应 |
|------|----------|------|----------|
| 上传 Product 公共图 | `POST /api/v1/admin/products/{product_id}/images` | multipart `file/is_cover/sort` | HTTP 201，`ProductImageOut` |
| 上传 Option 专属图 | `POST /api/v1/admin/options/{option_id}/images` | multipart `file/sort` | HTTP 201，`OptionImageOut` |
| 修改图片元数据 | `PATCH /api/v1/admin/product-images/{image_id}` | `sort` 或 Product 公共图的 `is_cover: true` | Product/Option 图片响应 |
| 逻辑删除图片 | `DELETE /api/v1/admin/product-images/{image_id}` | 无 body | `DeletedResourceOut` |
| 上架商品 | `PATCH /api/v1/admin/products/{product_id}/online` | 无 body | `ProductOnlineOut` |
| 下架商品 | `PATCH /api/v1/admin/products/{product_id}/offline` | 无 body | `ProductOfflineOut` |

## 2. Multipart、Bearer 与 Token 刷新

`Taro.uploadFile` 的响应体是字符串，不能直接复用 `Taro.request` 的对象响应假设；Upload Transport 先解析 JSON，再交给统一响应信封 Guard。multipart boundary 由平台生成，客户端不能手工设置 `Content-Type`，否则 boundary 可能缺失而导致服务端无法解析。

上传仍携带 Bearer access token。服务端返回业务 code `1006` 时，与 JSON 请求一样进入 single-flight refresh，并且最多重放一次原上传；多请求并发过期只刷新一次。普通 network/timeout/cancel、HTTP 5xx 或成功响应契约错误不自动重传，因为服务端可能已经落库和写文件。

## 3. 文件校验与存储事务边界

前端在文件大小和 MIME 可用时先检查 `<= 2 MiB` 及 jpg/png/webp，以便即时反馈；这只是体验层校验。后端还会检查真实文件签名、声明 MIME、内容一致性和大小，并以 `42221.data.reason` 返回稳定原因。部分微信导出 JPEG 会在标准结束标记后带固定前缀和本体 MD5；后端只在前缀、摘要和 JPEG 头尾全部匹配时剥离 24 字节并保存规范化 JPEG，任意或伪造尾随内容继续拒绝。前端不修改用户原图。

数据库事务不能回滚文件系统。后端上传编排先安全写临时/最终文件，再调用 Product Service；Service 或数据库失败时按 storage key 幂等补偿文件。客户端不复制该补偿逻辑，也不能把“前端扩展名正确”当成文件合法证据。逻辑删除图片只改变数据库可见性；物理文件由独立、可重试的后端清理任务按截止时间处理，不由管理页面即时删除。

## 4. 图片归属、封面、排序与删除

- Product 公共图属于 Product 聚合，可设置唯一封面；新封面由后端事务清理旧封面标记。
- Option 专属图属于 Experience Option，没有封面语义，因此页面不显示“设为封面”。
- `sort` 是服务端持久化的显示顺序，不使用数组下标代替；页面修改后重新读取权威详情。
- 删除封面或最后一张 Option 图片是允许的逻辑删除，但可能让商品不再满足上架条件；页面二次确认，最终由 readiness Validator 统一判断。
- Online 或逻辑删除 Product 的图片页只读。客户端只读状态用于即时反馈，后端 `40905/40903/40912` 仍负责裁决过期页面和竞争请求。

## 5. 上下架与 readiness issues

上架不是前端自己拼接的一组校验。页面发送 empty-body PATCH，后端 ProductValidator 一次完成 Product、图片、Option 或 Kit 配置检查；失败时返回 `42201` 和有顺序的完整 `data.issues`。客户端保留所有未知 issue 原文，并为当前已知项补充中文说明，不能只显示第一条，也不能把本地规则当作权威结果。

下架只改变 Product 当前状态，不修改 Option、图片、Kit 库存、Inventory 流水或历史订单。成功后页面重新 GET 管理详情，以服务端状态收敛。`40901/40902` 表示状态竞争或重复操作，`40903` 表示逻辑删除，均由后端事实决定。

## 6. 写操作状态与结果未知

图片与状态操作共享生命周期状态机：

```text
idle → submitting → succeeded
                  ↘ failed
                  ↘ unknown
```

同一时刻的快速重复命令合并为一个进行中 Promise；详情页还使用同步 ref 防止同一事件循环内“删除 + 上下架”等不同按钮交叉触发。Promise 合并只减少当前客户端重复点击，并不是服务端幂等保证。

network、timeout、cancel、响应 ContractError 和 HTTP 5xx 进入 unknown，不自动重发。用户恢复网络后使用“重新加载详情核对”：上传可能已经创建图片，上下架也可能已经完成，先读后写才能避免重复或反向操作。

## 7. 自动化与质量门槛

自动化覆盖：

- Upload Transport 的 multipart 参数、Bearer、字符串信封、错误分类和取消；
- `ApiClient.uploadFile()` 的 `1006` single-flight refresh 与一次受控重放；
- 图片 Endpoint 的 URL、form 字段、请求白名单、响应联合 Runtime Guard；
- Product/Option 图片上传、排序、设封面、逻辑删除，以及 online/offline empty-body PATCH；
- 2 MiB、MIME、`42221`、`42201.data.issues` 完整保留和未知 issue；
- 重复点击 Promise 合并、unknown 不自动重发、成功后重新 GET；
- Guest 固定登录回跳、普通用户不挂载管理 Hook、Online/已删除只读；
- 图片管理页和商品详情页的按钮、确认、预览、Option 分组和 readiness 展示。

本阶段定向为 8 套件 / 66 项；完整前端为 47 套件 / 328 项。TypeScript strict、ESLint、Stylelint、OpenAPI 漂移、weapp/alipay/tt/h5 production build、Product API 52 项和完整后端 1446 项均通过，9 项 MySQL-only 按配置跳过。四端 Build 只证明可编译，不替代真实选图、上传、网络中断和微信页面 Functional。

## 8. 微信 Functional 验收清单

1. Guest 直接进入管理商品固定路径，确认跳到登录，登录成功只返回管理商品列表；普通用户直接进入详情/图片路径不挂载管理 API，直接调用 ADMIN API 返回 403。
2. 使用 Draft 或 Offline Product 进入“管理图片”，分别从相册/相机上传 jpg、png、webp；确认预览 URL、sort 和服务端详情一致。
3. 尝试超过 2 MiB、伪造扩展名、内容与 MIME 不一致的文件；确认前端可判定项即时拦截，其他由后端 `42221` 拒绝且不留下有效图片记录。
4. 上传 Product 公共图并直接设为封面；再把另一张设为封面，确认同一 Product 最终只有一个封面。
5. 修改公共图与 Option 图排序，离开页面后重新进入，确认顺序来自服务端而非本地数组。
6. 为 Experience 的不同 Option 分别上传专属图，确认图片只出现在所属 Option；Option 图不出现封面按钮。
7. 删除普通图、封面图和某 Option 最后一张图，核对二次确认、逻辑删除结果和重新加载后的详情；删除封面/最后 Option 图后应可能无法上架。
8. Online 或逻辑删除 Product 进入图片页应只读；用独立客户端制造状态竞争，确认后端仍返回 `40905/40903/40912`。
9. 对不完整 Experience 点击上架，确认页面一次展示服务端返回的全部 readiness issues；逐项补齐图片、封面、Option、价格和 Option 图片后再次上架成功。
10. 对 Kit 验证名称、描述、封面、配置和价格；库存为 0 仍允许上架，因为上架不要求正库存。
11. Online Product 点击下架，确认 Product 变 Offline，Option、图片、Kit 库存和历史订单均不变；再次编辑时才恢复可写。
12. 快速连续点击上传、删除或上下架，只产生一个进行中的业务命令；断网制造 unknown 后不自动重发，恢复网络后使用“重新加载详情核对”。
13. 补测 Phase 8.3：选择一件有历史订单的 Online 商品，先打开旧订单记录价格和 Option 快照；下架、改价、重新上架后再次打开旧订单，确认仍是旧快照；创建新订单，确认使用新价格。

验收完成后应记录具体 Product/Option/Order ID 和每项结果，但不得记录密码、Token 或其他凭据。Phase 8.2 当时独立延期的管理页白色图案与登录输入 `_` 闪烁不影响本阶段历史验收结论；两项已于 2026-08-29 完成专项复测并关闭。

## 9. 知识点

1. **multipart boundary 属于传输协议。** 平台上传 API 应生成 boundary，业务代码只提供文件与 form 字段。
2. **Adapter 隔离多端差异。** `chooseImage` 和 `uploadFile` 的平台形状不应泄漏到 Feature 与页面。
3. **客户端校验改善体验，服务端校验建立信任。** 文件签名、MIME 和大小必须在后端信任边界重新验证。
4. **数据库事务不能覆盖文件系统。** 上传失败补偿需要独立、幂等的 storage 清理语义。
5. **图片归属是聚合规则。** Product 公共图可以是封面，Option 专属图不能被误当作 Product 封面。
6. **上架 Validator 是唯一权威。** 客户端展示完整 issues，但不能复制一套可能漂移的 readiness 规则。
7. **读后收敛比乐观猜测可靠。** 写成功、状态竞争或结果未知后都重新读取服务端聚合。
8. **Promise 合并不等于服务端幂等。** 它只能防当前页面重复点击，不能证明网络重试安全。
9. **主数据与交易快照必须分离。** 下架、改价和图片变化影响当前商品及未来订单，不能重写历史 Order Item。
10. **UI 守卫不是授权。** 隐藏/禁用按钮保护体验，FastAPI ADMIN+ dependency 才保护资源。
