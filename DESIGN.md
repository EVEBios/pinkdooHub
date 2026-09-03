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
  nav-account:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary-strong}"
    rounded: "{rounded.navigation}"
    gap: "16px"
    padding: "0"
    width: "100%"
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

pinkdooHub 把移动拼豆店组织成一本轻盈但可核对的丝带账簿：暖纸白承载真实商品与运营事实，克制莓果色只标记品牌、当前选择、权威结果和明确下一步。系统已经落到顾客与 ADMIN+ 的 20 条已注册页面路由；登录、注册等认证入口沿用同一视觉语法，业务状态、金额、库存和操作后果始终先于装饰。

系统以紧凑中文层级、短行标题和可扫读数字连接选购与运营。邻近莓色渐变像窄丝带一样组织关键动作，透明与模糊只用于导航、筛选和操作层级，普通内容继续是可读、可核对的实色纸面。首页页头保留 `pinkdooHub` 品牌与主标题，已移除右上角冗余“拼豆店”文字；真实商品图片仍是顾客界面的主要视觉内容。

**Key Characteristics:**

- 暖纸白、瓷白表面与莓墨形成低刺激、高辨识的工作台。
- 邻近莓色渐变只强调品牌、选中态、主操作和权威库存。
- 中文标题以平衡短行呈现，价格、库存、订单和流水使用表格数字。
- 玻璃层稀少且有实色回退；卡片主要依靠色调、边线和轻阴影分层。
- 390px 手机视口覆盖 20 条已注册页面路由，关键工作流同时在 768px 宽屏复核。

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
- **Display** (700，源 48px，1.22；H5 28PX): 首页与认证入口的短行主标题。
- **Price** (750，源 36px；H5 21PX，表格数字): 商品价格和订单总额。
- **Button** (700，源 27px，1.2；H5 14PX): 提交、返回、分页和主要导航动作。
- **Button Compact** (650，源 25px，1.2；H5 13PX): 密集筛选、日期清除和记录关联跳转。

H5 的固定 `PX` 映射只覆盖 `.taro_page`，用来避免 Taro 最小根字号扩大控件；源样式值继续服务 750 宽设计画布和小程序编译。不要用 H5 值反写源 token。

### Named Rules

**The Two-Wrap Rule.** 长中文标题使用 `text-wrap: balance` 与 `word-break: keep-all` 保持词组完整；订单号、Product ID、时间和其他长标识符使用 `overflow-wrap: anywhere` 保证窄屏不横溢。

## Layout

系统以 750 宽 Taro 设计画布为源，移动端优先，并为底部安全区留白。页面主体常用 24px 左右内边距，页头使用 28px，模块间以 18–24px 建立节奏；内容与页头内部通常限制在 960px 最大宽度。控件源最小高度为 88px，H5 显式映射为 44 CSS px，所有按钮、筛选、输入和关联动作都以触控可达性为先。

顾客商品区默认是两列网格；768px 起扩为三列。订单、商品与用户记录在手机上保持单列，关键列表和详情在 768px 使用两列或更宽的动作布局；详情主动作在宽屏通常收束到 420px，而不是横跨整个画布。完成态验证覆盖 20 条已注册页面路由的 390px 手机视口，并对首页、商品、购物车、订单和核心 ADMIN+ 页面执行 768px 宽屏复核。

粘滞筛选距顶部 12px；首页账户入口使用整行分组列表，不产生横向滚动，只有密集筛选允许在自身容器内横向滚动，页面本身不得横向溢出。普通中文内容控制行宽；长标题遵循平衡与不拆词规则，长标识符遵循安全任意换行规则。

## Elevation & Depth

系统采用“色调分层为主、环境阴影为辅”的混合深度。暖纸画布、瓷白卡片和浅粉分组先建立层级，阴影只加强粘滞筛选、可点击记录、主操作与权威库存。透明和模糊是有限功能层：账户导航、筛选、认证卡和少数关键操作容器可在支持时使用 14–22px 模糊及轻饱和，且必须先定义不透明实色回退。

### Shadow Vocabulary

- **Ambient Small** (`0 8px 22px rgb(83 31 49 / 8%)`): 账户托盘、筛选与普通操作容器。
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
- **Disabled:** 全局禁用透明度为 0.62，且只由 `button[disabled='true']` 匹配；不要扩大为任意 `[disabled]`。组件局部可以在此基础上替换颜色、边线或阴影，以保持业务状态可读。

### Chips

- **Style:** 默认使用浅粉表面和柔莓墨；选中项切换为邻近莓色渐变与白字。
- **State:** 管理筛选可换行或在容器内横向滚动；首页三段筛选保持等宽，在浅粉轨道内截断过长标签并使用 11px 紧凑圆角。

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

首页账户导航是瓷白分组账簿列表：“我的”与 ADMIN+ 的“店铺管理”使用低跨度浅粉区段标题，入口保持 44px 最小触控高度、左侧动作名和右侧轻量提示；“退出”位于面板外并降为安静文字动作。面板在手机上接近满宽、不横向滚动，支持模糊时才切换为半透明功能玻璃。页头只保留 `pinkdooHub` 品牌、页面任务与必要身份动作，已删除的右上角“拼豆店”标签不得恢复。

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
