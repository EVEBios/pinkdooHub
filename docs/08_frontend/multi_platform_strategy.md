# pinkdooHub 前端多端策略

> **Document Version:** v0.3
> **Status:** Draft
> **Last Updated:** 2026-09-09
> **Scope:** 微信小程序、支付宝小程序、抖音小程序、H5

本文档定义同一 Taro 应用在四个目标平台上的共享边界、差异隔离、构建配置与验收方式。总体依赖方向见 [前端架构](frontend_architecture.md)。

> **当前发布范围：** 长期架构仍允许四端演进，但 Phase 9 本版只发布微信小程序。微信 `weapp` 是当前 PR/RC 的唯一平台构建、Smoke、Functional 和真机门槛；支付宝、抖音与 H5 均延后到各自重新冻结的产品阶段，不构成本版阻断项，也不得被描述为本版已发布能力。当前发布细则见 [Phase 9 微信小程序发布规划](phase9_wechat_release_plan.md)。

---

## 1. 目标与原则

Taro 可以统一大量 React、组件、路由和 API 用法，但不能保证不同平台在登录、支付、分享、上传、权限、生命周期和开发者工具上完全一致。因此本项目追求“最大化安全共享”，不追求用条件分支假装所有平台相同。

原则：

1. 领域、API DTO、格式化、错误模型和大部分 React 组件共享。
2. 优先使用 Taro API 和组件；仅在 Taro 无法统一时进入 Platform Adapter。
3. `process.env.TARO_ENV` 不散落到 Page/Feature。
4. 平台配置、AppID、域名和发布流程明确分离。
5. 每个平台单独通过 Build、Smoke 和 Functional 三层验收。
6. 共享层继续避免无必要的平台耦合；当前版本以微信正确性为发布门槛。未来恢复其他平台前必须重新完成对应 Build、Smoke、Functional 和安全审计，不能把历史构建记录当成当前支持证据。

---

## 2. 平台矩阵

| 能力 | 微信 | 支付宝 | 抖音 | H5 |
|------|------|--------|------|-----|
| Taro type | `weapp` | `alipay` | `tt` | `h5` |
| 项目配置 | `project.config.json` | `project.alipay.json` | `project.tt.json` | `config` 中 H5 配置 |
| MVP 账号密码 | 支持 | 支持 | 支持 | 支持 |
| 平台登录 | 正式公开发布前接微信 | 后续单独冻结 | 后续单独冻结 | 账号密码；未来另评 OAuth |
| MVP 支付 | ADMIN+ 人工确认 | 同左 | 同左 | 同左 |
| 平台支付 | 微信支付 | 后续 Provider | 后续 Provider | 后续单独设计 |
| 网络 | Taro Client | Taro Client | Taro Client | Taro Client + 浏览器 CORS |
| 文件上传 | Spike 验证 | Spike 验证 | Spike 验证 | Spike 验证 |
| Storage | Taro Adapter | Taro Adapter | Taro Adapter | Taro Adapter；公开发布前安全 Review |
| 分包 | order/admin | order/admin | order/admin | Taro 合并为页面，不依赖分包保证安全 |
| 四根页导航 | 自定义瓷白丝带托盘 | 原生 TabBar 降级 | 原生 TabBar 降级 | 原生 TabBar 降级 |
| ADMIN+ 默认入口 | 无底栏店铺工作台 | 同一路由结构 | 同一路由结构 | 同一路由结构 |
| 分享 | 微信 Adapter | 支付宝 Adapter | 抖音 Adapter | Web Share/链接，后续冻结 |
| 请求域名 | 微信合法域名 | 支付宝白名单 | 抖音白名单 | HTTPS + FastAPI CORS allowlist |
| 当前发布验证级别 | Build + Functional + 真机 | 本版延后 | 本版延后 | 本版延后 |

支付宝、抖音和 H5 应在对应产品阶段重新冻结功能、身份、支付、网络、安全和验收门槛。

---

## 3. 共享代码边界

必须共享：

- OpenAPI 生成类型；
- Endpoint API 与响应信封；
- HTTP 错误模型；
- Token 刷新核心流程；
- Product/Order/Inventory/Reservation 前端用例；Reservation N1 使用普通 HTTPS API，不需要平台专属订阅能力；
- 金额、日期、Enum 和分页格式化；
- Experience Option 有效组合算法；
- 表单字段规则与通用页面四态；
- 商城、预约、订单、会员中心四项的顺序、文案、路径、图标语义和根页 `switchTab` 行为；
- 无底栏启动分流、角色相容的登录落点、ADMIN+ 店铺工作台和顾客根页管理角色守卫；
- 大部分项目 React 组件；
- 测试夹具和安全 DTO。

允许平台专属：

- 平台登录临时 code；
- 平台支付 API；
- 分享与订阅消息；
- 平台权限申请；
- 项目配置和 AppID；
- 平台开发者工具自动化；
- Taro 无法统一的上传/文件 API 行为；
- 必要的样式或组件兼容实现；
- 微信自定义 TabBar 的瓷白托盘材质、选中圆座与安全区实现；其他端使用 Taro 原生 TabBar，不复制微信私有组件。

禁止整页复制为 `page-weapp.tsx`、`page-alipay.tsx`，除非 Spike 或真实缺陷证明页面主体无法共享，并通过新的 ADR 批准。

---

## 4. Platform Port

平台层以小接口表达差异：

```ts
interface PlatformInfo {
  kind: 'weapp' | 'alipay' | 'tt' | 'h5'
  canUseNativeLogin: boolean
  canUseNativePayment: boolean
}

interface ExternalLoginPort {
  getAuthorizationCode(): Promise<string>
}

interface PaymentPort {
  requestPayment(payload: PlatformPaymentPayload): Promise<void>
}

interface SharePort {
  shareProduct(input: ShareProductInput): Promise<void>
}
```

约束：

- Port 定义不得包含 `wx`/`my`/`tt` 原生类型；
- Adapter 把平台返回值转换为项目类型；
- Feature 依赖 Port，不依赖 Adapter；
- 未实现能力显式返回 Unsupported，不静默成功；
- AppSecret、商户密钥和签名不进入 Port 输入。

---

## 5. 平台判断

允许在以下位置使用 `process.env.TARO_ENV`：

- `platform/index.ts` 的 Adapter 选择；
- 平台配置工厂；
- 经批准的平台专属资源入口；
- `app.config.ts` 中 `tabBar.custom` 的目标平台差异；
- 测试中设置目标环境。

禁止在以下位置使用：

- Product/Order/Inventory/Reservation 业务页面；
- Endpoint API；
- OpenAPI DTO；
- 通用格式化和业务算法；
- 大多数组件渲染分支。

如果某组件需要大量平台判断，优先拆为统一 Props 的平台实现文件，而不是在一个 TSX 中持续增加 `if`。

---

## 6. 构建与配置

### 6.1 预期构建命令

```text
npm run dev:weapp
npm run dev:alipay
npm run dev:tt
npm run dev:h5
npm run build:weapp
npm run build:alipay
npm run build:tt
npm run build:h5
```

这些命令表示仓库保留的长期构建入口，不表示四个平台都属于当前发布范围。Phase 9 本版的阻断命令只有 `npm run build:weapp`；其他构建若被人工或定时任务执行，只产生非阻断兼容性信息。

### 6.2 版本一致性

- 所有 `@tarojs/*` 使用同一精确版本；
- 本地 CLI 来自项目依赖；
- `package-lock.json` 必须提交；
- CI 使用 `npm ci`；
- Taro 或 React 升级单独提交并完成四端回归。

### 6.3 配置维度

配置必须明确分离：

```text
APP_ENV  = development | testing | production
TARO_ENV = weapp | alipay | tt | h5
```

前端可公开配置可以进入编译产物，例如 API Origin、AppID。AppSecret、JWT Secret、商户密钥和数据库凭据禁止进入任何前端环境变量。

### 6.4 输出目录

Spike 已固定为 `outputRoot: dist/<TARO_ENV>`：weapp/alipay/tt/h5 产物分别输出到 `dist/weapp`、`dist/alipay`、`dist/tt`、`dist/h5`，避免四端互相覆盖；微信开发者工具项目根指向 `dist/weapp`。构建产物加入 `.gitignore`，正式工程不得提交，除非某个平台发布工具存在经 ADR 批准的强制要求。

---

## 7. 网络、域名与图片

### 7.1 API Origin

所有请求通过一个按环境选择的 HTTPS Origin，Endpoint 只持有 `/api/v1/...` 路径。禁止在页面中硬编码 host。

### 7.2 小程序平台

微信、支付宝和抖音分别配置 request/upload/download 白名单。开发者工具中关闭域名校验只允许本地开发，不构成发布配置。

### 7.3 H5

H5 需要 FastAPI 增加精确 CORS allowlist，并允许必要 Method/Header：

- `Authorization`；
- `Content-Type`；
- `Idempotency-Key`。

生产不使用通配 Origin。Bearer Storage 的 XSS 风险在公开发布前专项 Review。

Spike 实测（2026-08-15，`spikes/taro-four-end-spike/tools/cors_check.py`）：对 FastAPI 发送 `OPTIONS` 预检返回 405、普通 GET 响应无 `Access-Control-Allow-Origin` 头，确认后端当前未配置 CORS 白名单，H5 浏览器跨域调用会被拦截。该缺口是后端待办，前端不自行绕过（如禁用 CORS 检查或使用代理伪装成功）。

### 7.4 图片

当前开发后端可返回 `/uploads/products/...` 相对地址。客户端通过唯一 `resolveAssetUrl()` 在开发期补全 Origin。生产应优先由后端返回对象存储/CDN 的绝对 HTTPS URL。

---

## 8. UI 与组件兼容

### 8.1 基线

- 优先使用 Taro `View`、`Text`、`Image`、`Button`、`ScrollView` 等；
- 业务页面不使用普通 HTML 标签作为跨端基础；
- NutUI 只通过项目组件或经过确认的简单直接用法进入业务；
- 样式不依赖某个小程序的私有选择器或浏览器专属 DOM。

### 8.2 Spike 组件矩阵

| 组件/能力 | weapp | alipay | tt | h5 | 批准条件 |
|-----------|-------|--------|----|-----|----------|
| Button | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | 事件、disabled、loading 一致（受控用法有 Jest 覆盖；真机待验证） |
| Input/Form | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | 受控值、错误、键盘行为可接受（Input 受控 value/onChange 已验证） |
| Dialog/Toast | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | ✅ 编译通过 | 打开关闭、层级、回调一致（受控 visible/onClose 已验证） |
| Picker | 待验证 | 待验证 | 待验证 | 待验证 | value 和取消行为一致 |
| Upload | 待验证 | 待验证 | 待验证 | 待验证 | 选择、进度、失败、multipart 可控 |
| Image/Preview | 待验证 | 待验证 | 待验证 | 待验证 | HTTPS、失败占位和预览可用 |
| InfiniteLoading | 待验证 | 待验证 | 待验证 | 待验证 | 不重复请求，触底行为可用 |
| Safe area | 待验证 | 待验证 | 待验证 | 待验证 | 底部按钮不被遮挡 |

Spike 结果写回 [ADR-005](adr/ADR-005-cross-platform-ui-strategy.md)。

### 8.3 四根页导航降级

四个平台共享同一信息架构和路由契约：

- 四项固定为“商城 / 预约 / 订单 / 会员中心”，对应 `pages/index/index`、`pages/reservations/index`、`pages/orders/index`、`pages/member/index`；顾客导航本身不按身份重排，ADMIN+ 不消费这套 Tab，而从无底栏启动页进入独立工作台。
- 所有平台必须在 `app.config.ts` 保留标准 `tabBar.list`。微信编译目标设置 `custom: true`，并由 `src/custom-tab-bar/` 实现方案 1“瓷白丝带托盘”；支付宝、抖音和 H5 设置 `custom: false`，由平台原生 TabBar 负责布局和安全区。
- `src/navigation/root_tabs.ts` 是共享文案、路径、索引和 `switchTab` 边界；微信自定义栏不建立第二份路由配置。根路径不带 query，详情和表单继续使用普通页面栈。
- 本地导航 PNG 来自同一授权图标库。轮廓灰用于未选中态，实心白用于微信深莓圆座，实心莓用于其他平台原生选中态；平台差异只选择已批准的状态资产，不在业务 Page 拼图标。
- 微信、抖音和 H5 默认从共享无底栏 `pages/entry/index` 等待服务端确认角色：Guest/USER 进入商城、ADMIN+ 进入 `admin/pages/workbench/index`。支付宝要求第一个 Tab 同时是首页，因此编译时保持商城在 `pages[0]`，由商城同一 ADMIN+ 守卫完成分流。四个顾客根页仍在业务 Hook 挂载前提供工作台重定向兜底。
- 店铺工作台与管理子页不在 `tabBar.list`，所以四端依靠普通路由层级自然隐藏顾客底栏；不使用运行时替换 Tab、平台专属 `hideTabBar` 或只在微信实现的管理员栏。平台导航不能改变权限或请求数据，FastAPI 仍是最终授权边界。
- 支付宝、抖音和 H5 的降级目标是结构正确、可识别、可触达，不承诺复刻微信悬浮材质；它们仍不进入本版发布范围，历史构建也不能替代未来各自重新验收。

---

## 9. 登录与支付演进

当前内部微信测试版沿用用户名密码。公开微信版本中，微信登录只在微信 Adapter 取得临时 code，后端负责换取平台身份和签发 pinkdooHub Token；AppSecret 和 `session_key` 不进入小程序。

未来支付宝、抖音登录不得复制微信专属数据模型。后端需先冻结通用外部身份关联契约。

MVP 的 Paid 状态由 ADMIN+ 人工确认。正式支付由服务端创建支付单、签名、验签和消费异步通知；客户端支付 API 成功回调不能直接把 Order 标记 Paid。

Reservation N1 在所有平台共享相同后端契约：上海营业日历、booking-options、创建/查询/取消和 ADMIN 审核/店休均通过普通 Bearer HTTPS；客户端设备时区不改变权威预约日期。N1 不调用微信 `requestSubscribeMessage`。未来 N2 若获批准，订阅授权只能放在微信 Platform Adapter，并为支付宝、抖音和 H5 明确不同能力或无能力降级；通知授权失败不得影响预约成功。

---

## 10. 验收等级

### Build

- 目标平台生产构建退出码为 0；
- 无未处理编译错误；
- 产物未包含禁止 secret；
- 包体积在平台门槛内。

### Smoke

- 应用可启动；
- 商城与其他三个根 Tab 可打开并正确选中；
- 可访问健康检查；
- 登录页可输入并提交；
- 页面导航、Storage、网络错误和一项 UI 组件可用。
- 二级详情/表单不显示底栏，返回根 Tab 使用正确页面栈；

### Functional

- 该平台的完整用户路径、异常、权限和关键边界通过；
- 使用该平台开发者工具或浏览器自动化；
- 发布候选还需真机与弱网验证。

当前本版门槛：微信 Build + Functional + 真机。支付宝、抖音和 H5 延后；对应平台未来进入发布阶段时必须以当时的代码和规则重新达到 Build + Functional + 真机，不能继承本版微信结论。

---

## 11. 当前微信发布检查清单

- [ ] 没有新增散落的 `wx`、`my`、`tt` 调用；
- [ ] 没有在 Page/Feature 新增平台条件分支；
- [ ] 新依赖已检查微信运行时支持、安全和许可证；
- [ ] 新组件完成微信开发者工具与真机验证；
- [ ] 微信自定义栏四项、安全区、选中态、减少动态和内容尾部遮挡已验证；
- [ ] ADMIN+ 冷启动、登录和顾客根页兜底均进入无底栏店铺工作台，角色确认前不挂载顾客业务请求；
- [ ] 其他端若运行非阻断构建，确认 `custom: false` 且没有编译微信自定义栏为运行入口；
- [ ] 微信生产构建、包体和产物扫描通过；
- [ ] 微信行为测试、真实 HTTPS 和合法域名通过；
- [ ] 非微信平台没有被写入本版发布承诺；
- [ ] 平台专属失败有显式反馈；
- [ ] 域名、权限、隐私或项目配置变化已更新文档；
- [ ] 不支持的平台能力没有伪装成功。

长期共享代码发生高风险基础设施变更时，可以额外运行四端构建作为非阻断早期信号；是否修复由对应平台 Phase 决定，不得挤占当前微信发布阻断项。
