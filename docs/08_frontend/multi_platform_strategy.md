# pinkdooHub 前端多端策略

> **Document Version:** v0.1
> **Status:** Draft
> **Last Updated:** 2026-08-15
> **Scope:** 微信小程序、支付宝小程序、抖音小程序、H5

本文档定义同一 Taro 应用在四个目标平台上的共享边界、差异隔离、构建配置与验收方式。总体依赖方向见 [前端架构](frontend_architecture.md)。

---

## 1. 目标与原则

Taro 可以统一大量 React、组件、路由和 API 用法，但不能保证不同平台在登录、支付、分享、上传、权限、生命周期和开发者工具上完全一致。因此本项目追求“最大化安全共享”，不追求用条件分支假装所有平台相同。

原则：

1. 领域、API DTO、格式化、错误模型和大部分 React 组件共享。
2. 优先使用 Taro API 和组件；仅在 Taro 无法统一时进入 Platform Adapter。
3. `process.env.TARO_ENV` 不散落到 Page/Feature。
4. 平台配置、AppID、域名和发布流程明确分离。
5. 每个平台单独通过 Build、Smoke 和 Functional 三层验收。
6. 新功能从第一天保持四端可构建，不能在 6 个月后第一次发现代码无法编译。

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
| 分享 | 微信 Adapter | 支付宝 Adapter | 抖音 Adapter | Web Share/链接，后续冻结 |
| 请求域名 | 微信合法域名 | 支付宝白名单 | 抖音白名单 | HTTPS + FastAPI CORS allowlist |
| 首版验证级别 | Build + Functional + 真机 | Build + Smoke | Build + Smoke | Build + Functional |

支付宝和抖音的完整 Functional 应在对应产品阶段提升为发布门槛。

---

## 3. 共享代码边界

必须共享：

- OpenAPI 生成类型；
- Endpoint API 与响应信封；
- HTTP 错误模型；
- Token 刷新核心流程；
- Product/Order/Inventory 前端用例；
- 金额、日期、Enum 和分页格式化；
- Experience Option 有效组合算法；
- 表单字段规则与通用页面四态；
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
- 必要的样式或组件兼容实现。

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
- 测试中设置目标环境。

禁止在以下位置使用：

- Product/Order/Inventory 业务页面；
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

---

## 9. 登录与支付演进

MVP 四端共享用户名密码。微信登录只在微信 Adapter 取得临时 code，后端负责换取平台身份和签发 pinkdooHub Token。

未来支付宝、抖音登录不得复制微信专属数据模型。后端需先冻结通用外部身份关联契约。

MVP 的 Paid 状态由 ADMIN+ 人工确认。正式支付由服务端创建支付单、签名、验签和消费异步通知；客户端支付 API 成功回调不能直接把 Order 标记 Paid。

---

## 10. 验收等级

### Build

- 目标平台生产构建退出码为 0；
- 无未处理编译错误；
- 产物未包含禁止 secret；
- 包体积在平台门槛内。

### Smoke

- 应用可启动；
- 首页可打开；
- 可访问健康检查；
- 登录页可输入并提交；
- 页面导航、Storage、网络错误和一项 UI 组件可用。

### Functional

- 该平台的完整用户路径、异常、权限和关键边界通过；
- 使用该平台开发者工具或浏览器自动化；
- 发布候选还需真机与弱网验证。

首版门槛：微信/H5 Functional，支付宝/抖音 Smoke。对应平台进入发布阶段时提升为 Functional + 真机。

---

## 11. 新功能跨端检查清单

- [ ] 没有新增散落的 `wx`、`my`、`tt` 调用；
- [ ] 没有在 Page/Feature 新增平台条件分支；
- [ ] 新依赖已检查四端支持和许可证；
- [ ] 新组件完成目标平台矩阵；
- [ ] 四端生产构建通过；
- [ ] 微信/H5 行为测试通过；
- [ ] 支付宝/抖音 Smoke 未回退；
- [ ] 平台专属失败有显式反馈；
- [ ] 域名、权限、隐私或项目配置变化已更新文档；
- [ ] 不支持的平台能力没有伪装成功。
