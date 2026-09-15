---
version: 4
slug: "miniapp-admin-workbench"
primary_target: "miniapp/src/admin/pages/workbench/index.tsx"
related_targets: ["miniapp/src/admin/pages/workbench/index.scss","miniapp/src/admin/styles/_surface.scss","miniapp/src/admin/styles/product-form.scss","miniapp/src/styles/_ribbon.scss","miniapp/src/assets/admin/workbench-header-texture.jpg","miniapp/src/pages/entry/index.tsx","miniapp/src/navigation/admin_workbench_redirect.tsx","miniapp/src/auth/login_route.ts","miniapp/src/app.config.ts","miniapp/src/styles/theme.scss"]
---

# Admin Workbench — Ribbon Ledger Operations Index

## Surface

ADMIN 与 SUPER_ADMIN 的独立店铺工作台。它整理已有的六条管理链路，不创造新的统计、待办、权限、资金或后端汇总能力。

## Mode

Operate

## Direction contract

THESIS: 用一张分组清楚的门店事务目录取代顾客底栏和“会员中心”中转，让工作人员登录后立刻找到今天要处理的事情，同时保留对真实业务页面的自然返回关系。

OWN-WORLD: Ribbon Ledger 的暖纸画布以深莓／李子色页头建立 ADMIN+ 身份边界，三组瓷白账簿再用深李子、核心莓果和灰粉三种 L 形装饰脊线组织扫描节奏；标题、工作人员身份与每行的小型“进入”胶囊保持清楚、可核对。

STORY: 先确认当前工作人员身份，再按时效从“今日处理”进入预约或订单；商品、库存、营业日历与用户权限按业务关系继续下沉。完成子任务后通过系统返回回到同一目录，最后从安静的退出动作结束会话。

FIRST VIEWPORT: 紧凑的深莓／李子色页头展示“店铺工作台”、品牌、昵称／用户名／角色和一句工作提示；标题、品牌和身份使用白色，副标题使用近白粉 `#fbeef3`。首个“今日处理”瓷白账簿紧随其后，让预约审核和订单处理在手机首屏优先可见。

SIGNATURE INTERACTION: 每个完整宽度的账簿行仍是唯一触控目标，同时提供任务标题、短说明和白字莓果渐变“进入”胶囊；胶囊只强化去向，不成为嵌套按钮。按下时行的瓷白底与文字完全不变，只让“进入”胶囊轻微收紧并加深；导航处理中也只让当前胶囊转为无阴影的柔和禁用态。进入管理页使用普通页面栈，返回自然落回工作台。

FORM: 保留用户确认的方案二“独立店铺工作台”；本轮选定的 Option 2 视觉精修只增强页头、分组脊线与去向提示，不改变信息架构。本阶段明确不增加管理员底部导航，也不让管理员进入顾客商城购买流程。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and rendered implementation evidence when the target runtime can be captured

## Information architecture

| 分组 | 入口 | 辅助文案 | 目标路径 |
|------|------|----------|----------|
| 今日处理 | 预约审核 | 确认、拒绝与联系顾客 | `/admin/pages/reservations/index` |
| 今日处理 | 订单处理 | 支付确认与履约 | `/admin/pages/orders/index` |
| 商品与库存 | 商品管理 | 商品、价格与配置 | `/admin/pages/products/index` |
| 商品与库存 | 库存流水 | 变动记录与来源 | `/admin/pages/inventory-transactions/index` |
| 门店与权限 | 营业日历 | 固定店休与单日店休 | `/admin/pages/store-closures/index` |
| 门店与权限 | 用户与权限 | 账号状态与资金入口 | `/admin/pages/users/index` |

六项入口恰好对应仓库已有页面，全部使用 `navigateTo`。首版没有汇总接口，因此不展示未审核预约、待处理订单、低库存或其他数字；也不以六个列表请求拼接工作台摘要。

## Role and navigation boundaries

- `/pages/entry/index` 是微信、抖音和 H5 的默认无底栏分流页。它只等待认证上下文：Guest/普通 USER 使用 `switchTab` 进入商城，ADMIN+ 使用 `reLaunch` 进入工作台。支付宝因第一个 Tab 必须是首页而从商城启动，再复用商城的 ADMIN+ 工作台守卫。
- 登录和已有会话进入登录／注册页时，只有与实际角色相容的固定白名单 redirect 会被保留；无目标或不相容目标回到角色默认落点。根 Tab 落点用 `switchTab`，其他落点用 `reLaunch`，登录/注册互换用 `redirectTo`。
- Entry、登录和注册共用串行最新目标导航：在途原生跳转不可取消时只记录最新角色落点，旧跳转结束后先同步真实落点，再必要时重放，避免并发和 A→B→A 回跳。
- ADMIN+ 误入商城、预约、订单或会员中心时，在任何顾客业务 Hook 挂载前进入共享重定向状态，并清空顾客页面栈回到工作台。
- Guest 在工作台只看到登录引导；普通 USER 只看到无权限状态和返回商城；认证初始化、错误或用户资料缺失时 fail closed，不展示六项入口。
- 工作台和全部管理页都不是 Tab 页面。当前不使用动态 TabBar、`hideTabBar` 作为权限边界，也不实现管理员专属底栏。
- 管理顶层页返回工作台时清空旧管理栈；预约审核与营业日历的对等捷径使用 `redirectTo`，不在子页间反复堆栈。
- 管理顶层页的纹理页头最多只容纳一个右上角“店铺工作台”小按钮。预约审核与营业日历的互跳作为页头下方关联卡片呈现，不能再与工作台入口并列成两个页头按钮。
- 管理员退出时先废弃内存 Token/User，再删除持久 Session 或写入无凭据 tombstone；只有设备凭据确实失效后才发布 Guest 并回裸登录页。若两步都失败，AuthProvider 进入全局可见 error 并要求清理小程序数据，不误报成功也不强制跳转；同一运行期的“重新检查”先重试失效旧凭据，不恢复退出前 Session。服务端登出失败但本地安全清除时则明确区分。导航失败保留明确重试。

## Visual and interaction rules

- 页头沿用 `header-band` 和 `page-title` 的结构，以 `#8e2448` 和 `var(--pd-gradient-stock)` 作为回退，并在最上层使用真实资产 `miniapp/src/assets/admin/workbench-header-texture.jpg`。纹理是经过裁切和压缩的深莓分块丝带，不包含文字、徽标或人物；标题、`pinkdooHub` 和身份行使用白色，副标题使用近白粉 `#fbeef3`。身份仍是紧凑文本，不复制普通会员的钱包／资料卡。
- 三个分组继续共用一个瓷白外轮廓和内部实色分隔，不把六项拆成六个同权悬浮卡片。每组先铺一整块分组强调色，再由同一裁切容器形成顶部与标题区左侧连续的 L 形装饰脊线，避免在圆角转角处拼接两条边框：今日处理使用深李子 `#68213f`，商品与库存使用核心莓果 `var(--pd-color-primary)`（回退 `#b7355d`），门店与权限使用灰粉 `#c97991`。
- 三种脊线颜色只区分账簿分组并建立视觉节奏，不表达状态、优先级、风险、权限或其他业务语义；业务状态仍必须依靠既有文字和交互反馈。
- 每个入口最小高度为源 118px，超过 88px 触控下限；完整宽度的行始终是触控目标。右侧“进入”使用小型白字莓果渐变胶囊作为去向提示，不能缩小为只点胶囊才生效；标题、辅助文案和“进入”文字本身也不依赖颜色即可说明用途。
- 工作行显式使用自定义 `hoverClass` 覆盖小程序原生整块变暗反馈：按压态只改变“进入”胶囊，行背景和左右文案保持原样。管理跳转处理中不得给完整动作行设置原生 `disabled`；当前行只增加专用 pending class，并由它把“进入”胶囊切换为柔莓墨、浅粉灰底、无阴影的静止状态，其余区域及另外五项保持原有对比度。并发导航仍由独立引用锁拦截，防止在原生导航尚未结束时发起第二次跳转。退出处理中则只禁用退出动作。
- 手机宽度下每组两项纵向排列；`768px` 起变成两列，并把第二项的上分隔线转换为左分隔线。页面本身不得横向滚动。
- 工作台不需要图标；因此不会用 emoji、文字图形、手绘 SVG、CSS 图案或占位资产伪装视觉层级。页头纹理是本轮专门生成并记录来源的真实位图资产，不用 CSS 图案近似参考效果。
- “退出当前账号”位于三组业务入口之后，使用 Quiet 语义而不是危险主按钮；处理中禁用以防重复提交。
- 所有可见状态沿用暖纸白、瓷白、浅粉、莓墨、腮红边线和现有系统字体栈；除上述三种局部分组装饰色与真实页头纹理外，不扩展颜色语义，也不引入新字体或运行时依赖。
- 工作台之外的 17 个 ADMIN+ 页面通过 `admin/styles/_surface.scss` 共享同一张真实深莓分块纹理；每页可按标题长度调整 `background-position`，但色域、对比度和材质保持一致。列表和表单使用纹理页头与瓷白筛选／表单面板，详情和配置把纹理用于对象身份／摘要区，库存与钱包仍以权威数字优先。业务状态、危险动作和高密度记录保留瓷白实色，不把纹理铺进正文。
- 圆角面板的顶部强调不使用独立粗边框；共享实现使用受圆角裁切的内嵌强调带，避免左上与右上转角出现断点。

## Required states and checks

- 检查 initializing、认证 error、Guest、authenticated-without-user、普通 USER、ADMIN、SUPER_ADMIN 七类身份／状态。
- 检查六项分组、顺序、文案和 URL，确认视觉精修没有改变整行触控、`navigateTo` 行为或任何路由，并且没有顾客钱包、商品购买入口、虚假数字、图标或顾客／管理员底栏。
- 检查页头的 `#8e2448` 实色回退、`var(--pd-gradient-stock)`、真实纹理图片、白色标题／品牌／身份和 `#fbeef3` 副标题；检查三组连续 L 形脊线依次为 `#68213f`、`var(--pd-color-primary)`／`#b7355d`、`#c97991`，并确认圆角转角没有断线，且没有把色调解释为业务状态。
- 检查每一行的白字莓果渐变“进入”胶囊、自定义局部按压态，以及当前导航处理中柔莓墨、浅粉灰底、无阴影的禁用胶囊；完整行的底色和文字在按压、禁用时都不得变暗。其余行应保持正常视觉但被并发导航锁保护。胶囊不得成为独立或嵌套触控目标。
- 检查 17 个二级管理页面均使用同一真实纹理和与页面任务相符的取景位置、瓷白面板变体；纹理页头最多一个右上角按钮，关联管理入口移到页头下方；状态色、危险动作、错误提示和权限语义不得被品牌色覆盖。
- 检查入口跳转、管理页返回、成功退出、服务端退出失败、本地清理以及登录页跳转失败的恢复行为。
- 在 390px 手机检查首屏优先级、长昵称／用户名换行、最后一个入口与退出按钮；在 768px 检查两列分隔与文字伸缩。
- 微信、支付宝、抖音和 H5 至少完成生产构建；真实视觉、交互或真机结论仅在相应运行时实际验证后记录。
