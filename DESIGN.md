---
name: pinkdooHub
description: 覆盖顾客与 ADMIN+ 工作流的移动拼豆店丝带账簿设计系统。
colors:
  canvas: "#fff8fa"
  canvas-deep: "#f8edf1"
  surface: "#fffdfd"
  surface-glass: "rgb(255 253 253 / 84%)"
  surface-muted: "#f8eef2"
  ink: "#2d2429"
  ink-soft: "#67575f"
  ink-faint: "#806b74"
  primary: "#b7355d"
  primary-strong: "#8f2346"
  primary-soft: "#fae7ed"
  line: "#ead8df"
  line-strong: "#d9b9c5"
  success: "#196244"
  success-soft: "#e8f4ed"
  danger: "#a92f38"
  danger-soft: "#fbeaec"
  warning: "#76531c"
  warning-soft: "#f8f0dd"
  on-primary: "#ffffff"
typography:
  caption:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "22px"
  label:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "23px"
  body:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "25px"
    fontWeight: 400
    lineHeight: 1.58
  input:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "27px"
    fontWeight: 400
    lineHeight: 1.4
  title:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.35
  heading:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "42px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.8px"
  display:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "48px"
    fontWeight: 700
    lineHeight: 1.22
    letterSpacing: "-1.2px"
  price:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "36px"
    fontWeight: 750
    fontFeature: "tnum"
  button:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "27px"
    fontWeight: 700
    lineHeight: 1.2
  button-compact:
    fontFamily: '-apple-system, "BlinkMacSystemFont", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'
    fontSize: "25px"
    fontWeight: 650
    lineHeight: 1.2
rounded:
  segment: "8px"
  compact: "11px"
  linked-action: "12px"
  field: "13px"
  small: "14px"
  emphasis: "15px"
  control: "16px"
  navigation: "18px"
  medium: "22px"
  large: "30px"
  pill: "999px"
spacing:
  s-5: "5px"
  s-8: "8px"
  s-10: "10px"
  s-12: "12px"
  s-14: "14px"
  s-16: "16px"
  s-18: "18px"
  s-20: "20px"
  s-22: "22px"
  s-24: "24px"
  s-28: "28px"
  s-32: "32px"
  s-36: "36px"
  s-48: "48px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.small}"
    padding: "0 18px"
    height: "88px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary-strong}"
    typography: "{typography.button}"
    rounded: "{rounded.small}"
    padding: "0 18px"
    height: "88px"
  button-quiet:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.button}"
    rounded: "{rounded.small}"
    padding: "0 18px"
    height: "88px"
  button-danger:
    backgroundColor: "{colors.danger-soft}"
    textColor: "{colors.danger}"
    typography: "{typography.button}"
    rounded: "{rounded.small}"
    padding: "0 18px"
    height: "88px"
  input-standard:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink}"
    typography: "{typography.input}"
    rounded: "{rounded.field}"
    padding: "0 20px"
    height: "88px"
    width: "100%"
  chip-default:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.button-compact}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "88px"
  chip-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-compact}"
    rounded: "{rounded.pill}"
    padding: "0 18px"
    height: "88px"
  tab-tray:
    backgroundColor: "transparent"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.navigation}"
    gap: "0"
    padding: "0"
    height: "158px"
    width: "100%"
  tab-tray-surface:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.navigation}"
    padding: "0"
    height: "128px"
    width: "100%"
  tab-item-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.pill}"
    height: "88px"
  card-record:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.medium}"
    padding: "23px"
    width: "100%"
  stock-panel:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.large}"
    padding: "26px"
    width: "100%"
  balance-ribbon:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.on-primary}"
    typography: "{typography.price}"
    rounded: "{rounded.large}"
    padding: "26px"
    width: "100%"
  ledger-transaction:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.medium}"
    padding: "23px"
    width: "100%"
  date-field:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "0 96px 0 0"
    height: "88px"
    width: "100%"
---

# Design System: pinkdooHub

## Overview

**Creative North Star: "Ribbon Ledger / 丝带账簿"**

pinkdooHub 把移动拼豆店组织成一本轻盈但可核对的丝带账簿：暖纸白承载真实商品与运营事实，克制莓果色只标记品牌、当前选择、权威结果和明确下一步。应用配置共包含顾客与 ADMIN+ 的 33 条已注册页面路由；登录、注册、启动分流和独立店铺工作台沿用同一视觉语法，业务状态、金额、库存和操作后果始终先于装饰。

系统以紧凑中文层级、短行标题和可扫读数字连接选购与运营。邻近莓色渐变像窄丝带一样组织关键动作，透明与模糊只用于导航、筛选和操作层级，普通内容继续是可读、可核对的实色纸面。顾客一级导航固定为“商城 / 预约 / 订单 / 会员中心”，商城页头只保留 `pinkdooHub` 品牌、商品任务与必要的购物流程动作；普通 USER 的账户信息和退出归入会员中心，ADMIN+ 则直接进入无顾客底栏的独立店铺工作台。真实商品图片仍是商城的主要视觉内容。

**Key Characteristics:**

- 暖纸白、瓷白表面与莓墨形成低刺激、高辨识的工作台。
- 邻近莓色渐变只强调品牌、选中态、主操作和权威库存。
- 中文标题以平衡短行呈现，价格、库存、订单和流水使用表格数字。
- 玻璃层稀少且有实色回退；卡片主要依靠色调、边线和轻阴影分层。
- 33 条已注册页面路由共享同一视觉世界；四个顾客根页面共享瓷白丝带托盘，独立店铺工作台与全部管理页保持无底栏。视觉验收以 390px 手机为基线，并在 768px 宽屏复核会员、工作台、钱包与关键工作流。

## Colors

调色板由暖纸中性色、单一莓果品牌轴和三组有文字语义的业务状态色组成；机器可读值以 frontmatter 为准。

### Primary

- **Ledger Berry / 账簿莓果** (`primary`): 品牌标识、主操作和选中筛选的核心强调。
- **Pressed Berry / 压深莓果** (`primary-strong`): 价格、库存余额、链接动作与高对比强调文字。
- **Ribbon Blush / 丝带浅粉** (`primary-soft`): 类型标签、日期活动段与轻量关联动作的底色。

### Secondary

- **Verified Green / 核验绿** (`success`, `success-soft`): 成功结果、可用状态和正向库存变化；文字与柔和底色成对出现。
- **Boundary Red / 边界红** (`danger`, `danger-soft`): 校验失败、危险动作、负向变化与禁止继续的边界。
- **Uncertain Ochre / 未决赭黄** (`warning`, `warning-soft`): 结果未知、待应用筛选和安全重试，不与失败红混用。

### Neutral

- **Warm Paper / 暖纸白** (`canvas`, `canvas-deep`): 页面底层及其轻微深色收束。
- **Porcelain Surface / 瓷白表面** (`surface`, `surface-glass`, `surface-muted`): 内容卡片、有限玻璃层以及字段和分组底色。
- **Berry Ink / 莓墨** (`ink`, `ink-soft`, `ink-faint`): 正文、辅助说明和最低层级元信息。
- **Blush Rule / 腮红边线** (`line`, `line-strong`): 卡片、字段与交互状态的边界。
- **Clean White / 净白** (`on-primary`): 深莓果动作和库存面板上的前景文字。

### Named Rules

**The Narrow Ribbon Rule.** 渐变只能连接相邻的莓果或暖白色阶，并且只服务于品牌、选中态、主操作和权威库存；跨大色域和彩虹渐变都不属于本系统。

## Typography

**Display Font:** 系统无衬线栈（优先 `-apple-system`，中文回退 `PingFang SC`）

**Body Font:** 与 Display 相同的系统无衬线栈

**Label/Mono Font:** 短标签沿用系统无衬线栈；掩码日期局部使用 `ui-monospace`

**Character:** 单一系统字体栈保证微信小程序与 H5 的稳定中文渲染，通过字重、短行和轻微负字距建立层级。价格、库存和流水使用表格数字；日期分段使用等宽字形，便于扫描和录入。

### Hierarchy

- **Caption** (源 22px；H5 12PX): 数量摘要、时间、辅助状态与胶囊内的最低层级文字。
- **Label** (源 23px；H5 13PX): 字段标签、状态与紧凑身份信息。
- **Body** (400，源 25px，1.58；H5 14PX): 说明、元信息和管理工作流正文，常见最大行宽为 24–34em。
- **Input** (400，源 27px，1.4；H5 14PX): 搜索、普通表单和库存调整输入。
- **Title** (700，源 30px，1.35；H5 18PX): 卡片组、工作区与空状态标题。
- **Heading** (700，源 42px，1.25；H5 24PX): 商品详情和 ADMIN+ 页面的一层标题。
- **Display** (700，源 48px，1.22；H5 28PX): 商城与认证入口的短行主标题。
- **Price** (750，源 36px；H5 21PX，表格数字): 商品价格和订单总额。
- **Button** (700，源 27px，1.2；H5 14PX): 提交、返回、分页和主要导航动作。
- **Button Compact** (650，源 25px，1.2；H5 13PX): 密集筛选、日期清除和记录关联跳转。

H5 的固定 `PX` 映射只覆盖 `.taro_page`，用来避免 Taro 最小根字号扩大控件；源样式值继续服务 750 宽设计画布和小程序编译。不要用 H5 值反写源 token。

### Named Rules

**The Two-Wrap Rule.** 长中文标题使用 `text-wrap: balance` 与 `word-break: keep-all` 保持词组完整；订单号、Product ID、时间和其他长标识符使用 `overflow-wrap: anywhere` 保证窄屏不横溢。

## Layout

系统以 750 宽 Taro 设计画布为源，移动端优先，并为底部安全区留白。页面主体常用 24px 左右内边距，页头使用 28px，模块间以 18–24px 建立节奏；内容与页头内部通常限制在 960px 最大宽度。控件源最小高度为 88px，H5 显式映射为 44 CSS px，所有按钮、筛选、输入和关联动作都以触控可达性为先。四个根页面必须为托盘的可见高度和 `safe-area-inset-bottom` 共同预留滚动尾部空间，最后一条内容不能被固定导航遮挡。

顾客商品区默认是两列网格；768px 起扩为三列。订单、商品、用户与资金记录在手机上保持单列，关键列表和详情在 768px 使用两列或更宽的动作布局；详情主动作在宽屏通常收束到 420px，而不是横跨整个画布。完成态视觉验收应覆盖 33 条已注册页面路由的 390px 手机视口，并对商城、会员、店铺工作台、钱包、商品、购物车、订单和核心 ADMIN+ 页面执行 768px 宽屏复核。

粘滞筛选距顶部 12px；会员中心的资料与钱包使用纵向分组列表，店铺工作台则以三个纵向账簿分组承载六项真实入口。两者都不产生横向滚动；只有密集筛选允许在自身容器内横向滚动，页面本身不得横向溢出。普通中文内容控制行宽；长标题遵循平衡与不拆词规则，长标识符遵循安全任意换行规则。

## Elevation & Depth

系统采用“色调分层为主、环境阴影为辅”的混合深度。暖纸画布、瓷白卡片和浅粉分组先建立层级，阴影只加强底部导航、粘滞筛选、可点击记录、主操作与权威库存。透明和模糊是有限功能层：底部导航、筛选、认证卡和少数关键操作容器可在支持时使用 14–22px 模糊及轻饱和，且必须先定义不透明实色回退。

### Shadow Vocabulary

- **Ambient Small** (`0 8px 22px rgb(83 31 49 / 8%)`): 瓷白底部托盘、筛选与普通操作容器。
- **Ambient Medium** (`0 18px 48px rgb(83 31 49 / 12%)`): 高层级操作区和粘滞动作容器。
- **Product Card** (`0 12px 34px rgb(83 31 49 / 9%)`): 顾客商品卡片静止态。
- **Record Card** (`0 9px 26px rgb(83 31 49 / 7%)`): 高频订单、库存和管理记录。
- **Primary Action** (`0 10px 24px rgb(143 35 70 / 18%)`): 明确下一步的主操作。
- **Authoritative Stock** (`0 20px 44px rgb(103 24 54 / 24%)`): 仅用于服务端权威库存余额。

### Named Rules

**The Functional Glass Rule.** 透明与模糊必须表达导航、筛选、认证或操作层级，并始终提供实色回退；普通正文和高频记录保持不透明。

## Shapes

形状语言从日期分段的 8px、紧凑选择的 11px 和关联动作的 12px，过渡到字段的 13px、基础控件的 14–16px、导航托盘的 18px、记录卡的 22px 和重点面板的 30px。999px 胶囊只用于短状态、类型、筛选和独立分页动作，不把正文或整张卡片包成胶囊。

内容容器以 1px 腮红边线和圆角共同界定；聚焦字段加深一档边线，主操作以莓果色面和阴影承担轮廓。图片卡片裁切内容但让真实商品图保持主体，权威库存使用单一大圆角轮廓，不叠加图案。

## Components

### Buttons

- **Shape:** 默认 14px 圆角，局部动作使用 13px 或 16px，独立筛选与分页可用胶囊；最小高度为源 88px／H5 44px。
- **Primary:** 白字置于邻近莓色窄域渐变，字重 700；只用于提交、确认、重试与加载更多等明确下一步。
- **Secondary / Quiet / Danger:** Secondary 使用瓷白底、压深莓果文字和强一档边线；Quiet 使用浅粉底和柔莓墨；Danger 使用危险红文字与柔红底。
- **Hover / Focus / Press:** 全局按钮状态以 160ms ease 过渡；键盘焦点使用 3px 半透明莓果轮廓并外移 3px，按下位移 1px。系统偏好减少动态时取消过渡。
- **Native Override:** 登录主按钮不使用 Taro `type='primary'`，通过自定义莓果 `hoverClass` 保持品牌按压态；工作台完整动作行也使用自定义 `hoverClass`，只收紧行内“进入”胶囊，行背景与文案不随平台默认反馈变暗。
- **Disabled:** 全局禁用透明度为 0.62，使用小程序与 H5 都支持的 `button[disabled]` 属性选择器；禁用按钮的按下位移由更高优先级的 `button[disabled]:active` 规则归零。共享按钮统一使用浅粉灰表面、柔莓墨文字、弱边线和无阴影，避免不可点击控件仍保留主操作或危险操作的高强调外观。

### Chips

- **Style:** 默认使用浅粉表面和柔莓墨；选中项切换为邻近莓色渐变与白字。
- **State:** 管理筛选可换行或在容器内横向滚动；首页三段筛选保持等宽，在浅粉轨道内截断过长标签并使用 11px 紧凑圆角。

### Color Palette

- **Density:** 顾客自选颜色使用紧凑方形色板，手机每行 6 色、宽屏每行 10 色；格间距使用 12px，并为色板边缘保留 2px 缓冲，使选中外环和相邻色样清楚分离。完整 221 色目录优先降低纵向查找距离，同时保持单格触控区域不小于约 44px。
- **Label:** 色号与可选名称不使用容器底色或边框，直接居中叠在色块上；使用轻量四向浅色文字描边兼顾深浅色样，长名称单行截断。选中状态使用莓红外环、浅色内环、轻微抬升和右上角“已选”状态标记形成双重识别，不改变未选色样的明度或饱和度，也不用标签底色遮挡真实颜色。
- **Shape:** 色块图片铺满方形格子并由外层 12px 圆角裁切；已选列表中的小色样继续保留紧凑圆形，避免把浏览目录与重量编辑混成同一种结构。
- **Cart grouping:** 购物车按自选颜色商品合并为一张主卡，商品名称与每 10g 预览单价只展示一次；卡内每种颜色保留独立行，以圆形色样、色号、当前克数、逐色步进器和移除动作维持可识别性与独立编辑能力。不同商品不得跨卡合并，下单仍保持每色一条明细。

### Cards / Containers

- **Corner Style:** 商品与记录卡通常为 22px，空状态与权威数据焦点为 30px。
- **Background:** 普通内容使用瓷白实色，输入、原因与分组使用浅粉实色。
- **Shadow Strategy:** 普通卡片只用低对比环境投影；按下时轻微收紧阴影，商品卡局部使用 180ms 过渡。
- **Border / Padding:** 1px 腮红边线承担静止边界；常用内部留白为商品 20px、记录 23px、操作容器 24px、权威库存 26px。

### Inputs / Fields

- **Style:** 普通字段使用浅粉实底、13–14px 圆角与透明静止边线；搜索字段使用瓷白底和明确腮红边线。
- **Focus:** 聚焦后切换为净白底与强一档腮红边线；全局可见焦点继续提供 3px 外轮廓。
- **Error / Disabled:** 错误、成功、待应用与结果未知分别使用红、绿、赭黄的文字和柔和底色，始终保留文字说明。

### Navigation

四个顾客一级入口固定为“商城 / 预约 / 订单 / 会员中心”，顺序和根路径不因身份变化。微信端使用悬浮“瓷白丝带托盘”自定义 TabBar：托盘左右留出呼吸空间，包含底部安全区，四项严格等宽且每项保持源 88px／H5 44px 的最小触控区域。未选中项使用柔莓墨灰轮廓图标与常规字重；选中项使用深莓圆形底座、白色实心图标、加粗莓果文字和克制上浮，同时用形状、填充、字重和位置表达状态，不只依赖颜色。图标使用同一授权图标库导出的本地 PNG 状态族，保留来源与许可证，不使用 emoji、手绘 SVG 或其他品牌资产。

微信每个根页拥有独立的自定义栏实例。初始选中项与后续选中同步都必须由当前路由或目标根页的页面显示生命周期确认；点击其他 Tab 只发起 `switchTab`，离开页不得先把自己的实例乐观高亮为目标项。点击当前 Tab 可以依据当前路由重新确认选中态，但不得堆叠页面或制造额外导航。

托盘采用不裁切抬升圆座的安全结构：外层只提供源 158px 高的真实 dock 边界；独立 surface 从顶部 30px 处开始，既绘制其下 128px 高的瓷白托盘，也直接承载四个等宽 item，并保持 `overflow: visible`。圆座在各自 item 内绝对定位，向上进入 dock 的 30px 透明区但不越真实边界，不用负 margin 把内容推出组件。微信实现使用普通 `View`/`Image` 层级，避免原生 cover 层及 surface/item sibling 叠层在目标运行时裁切圆座。选中切换可以对颜色、边线和阴影使用约 120ms 的短过渡，但 `width`、`height`、`top`、`margin` 等几何属性必须瞬时切换，避免抬升时挤压或裁切；按压只允许 `transform` 的轻微缩放反馈，系统减少动态偏好下同时禁用该反馈和非必要过渡。

商城、预约、订单和会员中心四个根页面显示底栏；无底栏启动分流页、店铺工作台、商品详情、购物车、下单确认、订单/预约详情、登录注册、钱包充值/流水及所有管理页不显示。进入其他顾客根页统一使用 `switchTab`，重复选择当前页不得堆叠页面。Guest 在受保护根页看到登录引导，普通 USER 才展示自己的预约、订单和钱包；ADMIN+ 在服务端身份确认后使用 `reLaunch` 进入工作台，误入任一顾客根页时也回到工作台，且不挂载顾客商品、预约、订单或钱包请求。支付宝、抖音和 H5 使用同一四项顾客信息架构及本地图标的原生 TabBar 兼容降级，不要求复制微信悬浮造型。

会员中心的内容导航继续采用瓷白纵向分组账簿，仅服务 Guest 和普通 USER：USER 展示资料、钱包、资金入口与安静但清晰的退出动作；ADMIN+ 不在这里维护第二份管理入口。页头只保留 `pinkdooHub` 品牌、页面任务与必要业务动作，已删除的右上角“拼豆店”标签不得恢复。

### Admin Workbench Ledger

店铺工作台是 ADMIN+ 的默认一级落点，但不是 Tab 页面，也不复用顾客底栏。Option 2 精修后的紧凑页头以 `#8e2448` 和 `var(--pd-gradient-stock)` 作为回退，并在最上层叠加真实纹理资产 `miniapp/src/assets/admin/workbench-header-texture.jpg`；“店铺工作台”、`pinkdooHub` 和昵称／用户名／角色身份使用白色，任务副标题使用近白粉 `#fbeef3`。身份信息保持单行可扫读，不扩展成普通会员资料卡。

页面主体按“今日处理”“商品与库存”“门店与权限”排列三个瓷白账簿分组，每组恰好两个入口：预约审核／订单处理、商品管理／库存流水、营业日历／用户与权限。每组以同一块强调色基底配合裁切容器，一次形成顶部与标题区左侧连续的 L 形装饰脊线，避免圆角转角处由两条边框拼接产生断点；三组依次使用深李子 `#68213f`、核心莓果 `var(--pd-color-primary)`（回退 `#b7355d`）和灰粉 `#c97991`。三种色调只帮助区分分组和建立扫描节奏，不表示状态、优先级、风险或权限。

每个入口继续使用完整宽度的实色行作为唯一触控目标，行内保留明确标题、短辅助文案和小型白字莓果渐变“进入”胶囊；胶囊只是去向提示，不是独立按钮。自定义小程序按压态只让胶囊轻微缩放并加深，整行背景与左右文字完全不变；导航处理中不对完整行设置原生 `disabled`，只通过当前行的专用状态 class 让胶囊切换为柔莓墨、浅粉灰底且无阴影的反馈，其余五项保持正常对比度。独立的并发导航锁仍阻止第二次跳转。手机保持单列，`768px` 起同组两列。六条真实路由、`navigateTo`、返回、权限、退出与错误恢复行为不变；首版仍不使用图标、六宫格、虚假待办数字、并发摘要请求、管理员底部导航或顾客商城预览。

### Admin Secondary Surfaces

工作台之外的 17 个 ADMIN+ 页面通过 `miniapp/src/admin/styles/_surface.scss`、共享 `styles/_ribbon.scss` 和既有页面样式使用同一张真实深莓分块纹理。列表与表单把纹理放在任务页头，详情和配置放在对象身份／摘要区，各页面可按标题长度微调取景；库存与钱包仍让余额、库存和操作后果保持首要层级，正文与高密度记录维持瓷白实色。圆角面板的窄强调带使用内嵌阴影随圆角自然裁切，不拼接粗边框，因此转角不会断开。

管理顶层页的纹理页头最多只容纳一个右上角“店铺工作台”小按钮。预约审核与营业日历之间的互跳放到页头下方的独立关联卡片；其他管理页遵循同一规则，不在顶部区域并排两个大按钮。

品牌色只负责身份、分区和主要动作。成功、警告、危险、禁用、业务状态与权限提示继续沿用各自文字和语义色，不被深莓主题覆盖；全部管理页面仍保持无顾客底栏。

### Customer Textured Surfaces

商城、预约、订单和会员中心四个根页，以及商品详情、购物车、下单确认、订单／预约详情和钱包流程，复用同一真实深莓分块纹理作为顶部身份区；白色标题与近白粉副标题建立稳定对比，各页只调整 `background-position`，不另造互相竞争的主题。真实商品图片仍保留在商品内容区，纹理不进入商品图片、业务状态、错误、表单正文或高密度流水。

顾客侧瓷白筛选、摘要、表单与记录卡使用窄内嵌强调带建立轻量分块节奏，色带由容器圆角裁切，不在角落拼接两条边框。强调带只服务层级，不替代成功、警告、危险、禁用等既有文字与语义色。

### Member Balance Ribbon

会员余额采用深莓色权威面板：当前余额是最大数字，上限、钱包状态与能力说明退后一层。充值、支付与退款入口必须由服务端能力和账户状态共同驱动；未开通的微信支付保持禁用，并清楚说明不会发起支付或生成成功结果。

### Wallet Ledger Row

资金流水沿用记录卡片，但把业务方向写成“入账／支出”，并同时显示正负号、变化前后余额、来源、原因与 UTC 时间。结果未知使用赭黄语义并冻结原操作意图；重试必须复用同一操作标识，不能让用户在未知态悄悄改成另一笔资金写入。

### Inventory Transaction Card

流水卡片把类型和变化量放在同一基线，正负变化分别使用核验绿与边界红；余额使用压深莓果，原因置于浅粉内嵌区，Product、流水、订单与 UTC 时间允许安全换行并使用表格数字。

### Authoritative Stock Panel

权威库存面板是系统最强的数据焦点：30px 大圆角、邻近深莓果渐变、大号表格数字和独占高层级阴影。它只显示服务端权威余额及简短追溯说明，不承载图案或无关装饰。

### Masked Date Field

日期字段在同一 13px 圆角容器内以 `YYYY-MM-DD` 三段等宽字符展示，当前段使用浅粉底和压深莓果文字；原生数字输入覆盖整个字段，右侧“清除”动作保留完整触控高度。

## Do's and Don'ts

### Do:

- **Do** 用暖白、浅粉与邻近莓色组织页面，让真实内容、状态和下一步先被看见。
- **Do** 把玻璃效果限制在导航、筛选、认证和关键操作层，并始终保留实色回退。
- **Do** 保持四个根 Tab 的固定顺序、等宽触控与非纯颜色选中态，并为底部安全区和内容尾部预留空间。
- **Do** 为价格、库存、订单和流水数字使用表格数字与稳定对齐。
- **Do** 保持源 88px／H5 44px 的触控高度，并提供焦点、按下、禁用和减少动态状态。
- **Do** 在 390px 检查每条完成态业务路由，并为关键流程补做 768px 宽屏复核。
- **Do** 继续使用服务端提供的真实商品图片，并为缺图和加载失败提供直接文字说明。

### Don't:

- **Don't** 使用跨大色域渐变、彩虹渐变或与莓果／暖白世界无关的高饱和装饰色。
- **Don't** 把所有容器做成玻璃卡片，也不要用强阴影替代信息层级。
- **Don't** 加入 Hello Kitty、角色图案、装饰图案、emoji、手绘 SVG 或虚构商品图作为视觉捷径。
- **Don't** 让普通中文逐字断行，也不要让订单号、ID、时间等长标识符制造页面横向溢出。
- **Don't** 用颜色作为状态的唯一线索；状态必须同时具有文字、数字或明确动作语义。
- **Don't** 让装饰压过价格、库存、权限、订单状态、幂等结果与操作后果。
- **Don't** 在二级详情、认证、钱包或管理工作流重复显示底栏，也不要在商城重新加入账户与店铺管理面板。
