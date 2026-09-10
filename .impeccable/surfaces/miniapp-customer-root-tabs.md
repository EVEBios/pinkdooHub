---
version: 2
slug: "miniapp-customer-root-tabs"
primary_target: "miniapp/src/custom-tab-bar/index.tsx"
related_targets: ["miniapp/src/navigation/root_tabs.ts","miniapp/src/navigation/admin_workbench_redirect.tsx","miniapp/src/app.config.ts","miniapp/src/pages/entry/index.tsx","miniapp/src/pages/index/index.tsx","miniapp/src/pages/reservations/index.tsx","miniapp/src/pages/orders/index.tsx","miniapp/src/pages/member/index.tsx","miniapp/src/styles/_customer.scss","miniapp/src/styles/_ribbon.scss","miniapp/src/assets/admin/workbench-header-texture.jpg","miniapp/src/admin/pages/workbench/index.tsx","miniapp/src/assets/tab-bar","miniapp/src/styles/theme.scss"]
---

# Customer Root Tabs — Porcelain Ribbon Tray

## Surface

顾客侧四个一级根页面与共同导航：商城、预约、订单、会员中心。它重组现有页面入口，不创造新的后端能力、订单/预约状态或工作人员钱包。

## Mode

Operate

## Direction contract

THESIS: 用一条轻盈的瓷白丝带把高频顾客任务固定在拇指可达区域，让用户无须返回商城也能在浏览、预约、订单和账户之间建立稳定方向感。

OWN-WORLD: Ribbon Ledger 的暖纸画布、瓷白托盘、腮红边线、单一莓果强调、真实商品图和可核对业务状态。

STORY: 先在固定四项中确认当前位置，再完成当前页任务；进入详情或敏感流程时导航退场，让内容和下一步成为唯一焦点。

FIRST VIEWPORT: 四个根页面使用同一深莓分块纹理页头建立任务身份，在内容下方共享悬浮瓷白托盘；当前项由深莓圆形图标座、白色实心图标、加粗文字和轻微抬升共同标记。商城首屏不再混入账户或管理入口，真实商品图仍是正文主体。

SIGNATURE INTERACTION: 当前根页的页面显示生命周期直接确认自己的选中圆座；切换时几何位置瞬时到位，只让颜色、边线和阴影做短过渡，按压以轻微 transform 回应。系统减少动态偏好下禁用按压位移和非必要过渡。

FORM: 用户已从三套预览中选定方案 1“瓷白丝带托盘”；参考快餐应用的是高频任务常驻底部这一信息架构，不复制其品牌、异形中央按钮或资产。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Information architecture

| 顺序 | 文案 | 根路径 | 内容边界 |
|------|------|--------|----------|
| 1 | 商城 | `/pages/index/index` | 公开商品搜索、筛选、分页与详情入口；Guest 可访问 |
| 2 | 预约 | `/pages/reservations/index` | 普通 USER 的预约列表；Guest 登录引导；ADMIN+ 自动回到工作台 |
| 3 | 订单 | `/pages/orders/index` | 普通 USER 的订单列表；Guest 登录引导；ADMIN+ 自动回到工作台 |
| 4 | 会员中心 | `/pages/member/index` | Guest 登录入口；USER 资料/钱包；ADMIN+ 自动回到工作台 |

四项的顺序、文案和路径是全局契约。商品全部归入商城；预约创建仍由 Experience 商品详情进入，不在预约根页复制商品目录。购物车仍是商城二级流程，不增加第五个 Tab，也不添加无权威数据来源的红点或数字角标。

## Visual and interaction rules

- 商城、预约、订单与会员中心共享真实的深莓分块纹理页头，并按标题长度微调取景；白色标题与近白粉副标题保证对比。商品详情、购物车、下单确认、订单／预约详情和钱包页沿用同一身份区材质；纹理只出现于顶部身份区，不进入商品图、业务状态、表单正文或高密度列表。
- 瓷白筛选、摘要与表单面板允许使用受圆角裁切的窄内嵌强调带建立节奏，不能用拼接的粗边框制造转角断点，也不能让装饰色承担成功、警告或危险语义。
- 微信自定义栏使用瓷白实色回退，并在支持时以有限透明/模糊加强悬浮层级；1px 腮红边线和低对比环境阴影承担边界，不使用夸张胶囊或厚重投影。
- 托盘左右留白，四项严格等宽，包含 `safe-area-inset-bottom`；每项触控高度至少为源 88px／H5 44px，文字单行且不得裁切。
- dock 的源高度为 158px：内部顶部 30px 保持透明，独立 surface 只在其下绘制 128px 瓷白托盘。选中圆座绝对定位在等宽 item 中，抬升后的最高点仍在 dock 真实边界内，不能依赖负 margin 越界绘制。
- 未选中为柔莓墨灰轮廓图标与常规字重；选中为深莓圆形底座、白色实心图标、加粗莓果文字及克制上浮。形状、填充、字重和位置共同表达选中态。
- 选中态的 `width`、`height`、`top`、`margin` 等布局几何不参与 transition；只允许颜色、边线、阴影和按压 `transform` 的短反馈。减少动态偏好下取消非必要过渡，并让按压保持无位移、无缩放。
- 商城、日历、收据/订单、人物四个图标来自同一授权图标库，导出轮廓灰、实心白、实心莓三组本地 PNG 并记录来源与许可证；不使用 emoji、手绘 SVG、文字图形或参考产品资产。
- 微信为各根页缓存独立的自定义栏实例；选中态只由当前路由解析或该根页的页面显示生命周期确认，不能依赖实例之间共享 state。
- 点击其他根项只执行一次 `switchTab`，离开页不得乐观高亮目标项；目标页显示后再由其生命周期提交选中态。点击当前项只依据当前路由重新确认，不堆叠页面、不制造重复首屏请求。`switchTab` 路径不携带 query，二级页面继续使用其既有参数与返回关系。

## Presence and refresh boundaries

- 只有商城、预约、订单、会员中心显示底栏。默认启动分流页、店铺工作台、商品详情、购物车、下单确认、订单详情、预约创建/详情、登录/注册、钱包充值/流水和全部 ADMIN+ 页面均不显示。
- 商城普通 Tab 切换保留搜索、类型筛选和滚动上下文，不因重新显示强制清空。
- 预约和订单重新显示时保留筛选并刷新第一页；会员中心重新显示时重读当前资料，普通 USER 同步重读钱包摘要。刷新保留已有内容，避免闪回全页 Loading。
- 首次挂载与首次显示只能形成一次请求；已有 sequence/请求所有权继续阻止迟到响应覆盖新身份或新筛选。
- 微信、抖音和 H5 默认先进入无底栏、无业务请求的 `/pages/entry/index`，只在服务端确认身份后分流：Guest/USER `switchTab` 到商城，ADMIN+ `reLaunch` 到店铺工作台。支付宝因“第一 Tab 同时为首页”的平台约束从商城启动，并由商城相同角色守卫分流。显式登录回跳只保留与当前角色相容的固定白名单目标。
- ADMIN+ 深链误入任一顾客根页时自动 `reLaunch` 到工作台；角色确认前及跳转期间不得挂载商城、顾客预约、顾客订单或普通客户钱包请求。应用级 `CartProvider` 只在 Guest 或已确认普通 USER 时挂载，不在初始化、认证错误或 ADMIN+ 状态恢复顾客购物车。退出或身份变化时清理不再属于当前身份的受保护数据。

## Platform boundary

- 微信 `weapp` 在标准 `tabBar.list` 上设置 `custom: true`，由 `miniapp/src/custom-tab-bar/` 实现瓷白丝带托盘；`miniapp/src/navigation/root_tabs.ts` 维护四项共享配置与选中同步。
- 支付宝、抖音和 H5 使用同一四项、顺序、路径与本地图标的原生 TabBar 兼容降级，并设置 `custom: false`；独立工作台仍不是 Tab 页面，因此 ADMIN+ 流程不会显示顾客底栏。这些端不需要复制微信悬浮材质，也不因此进入本版发布承诺。
- 这次信息架构变更不改变 FastAPI API、OpenAPI、数据库 Schema/Aerich 迁移、业务权限、运行时依赖或版本号。

## Required states and checks

- 四个根页分别检查 Loading、Empty、Error、Content，以及 Guest、USER、ADMIN+ 身份分支；ADMIN+ 分支还必须验证不挂载顾客业务 Hook并只发起一次工作台重定向。
- 检查微信 iOS/Android 安全区、键盘弹出、最后一条内容、390px 手机和 768px 宽屏；底栏不能遮挡内容或形成页面横向溢出。
- 检查四个根页和顾客二级流程的纹理页头取景、白色文字对比、瓷白面板内嵌强调带及真实商品图优先级；业务状态色不得被品牌纹理覆盖。
- 检查深链进入二级页无底栏、二级页返回关系、登录回跳、重复点击、快速切换、切换失败时无乐观错亮、独立实例同步、圆座边界、迟到响应和减少动态偏好。
- 自动化、构建与真机结果只在实际执行后记录；本说明本身不是通过证据。
