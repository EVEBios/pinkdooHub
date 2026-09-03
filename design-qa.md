# Ribbon Ledger UI Refresh — Design QA

## Comparison target

- Source visual truth: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/ribbon-ledger.jpg`
- Browser-rendered release candidate: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/implemented-home-release-candidate.jpg`
- Same-scale full comparison: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/reference-vs-implementation-home-release.png`
- Same-scale first-viewport comparison: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/reference-vs-implementation-home-release-focus.png`
- Route and state: public Product list, guest, `all` filter, first page with 10 of 13 isolated local preview records.
- CSS viewport: 390 × 844 px at device pixel ratio 1.

The 247 × 526 px phone viewport inside the 1280 × 720 source board is explicitly resized to 390 × 830 px, then vertically centered in a 390 × 844 px panel. The implementation keeps its native 390 × 844 px capture. Both comparison files use true PNG encoding. The source character is an intentional difference: the user asked to remove all character artwork from the current direction.

## Findings and corrections

- Typography: the initial Song-style display stack was replaced with a stable Apple/WeChat Chinese system sans stack. Short display copy remains weight-led rather than relying on an uncertain WeChat serif fallback.
- Touch targets and text centering: the source sizes were recalibrated for Taro `designWidth: 750`. Primary buttons, segmented filters, inputs, inventory choices, date fields, paging controls and order links now share an 88 rpx source minimum, which renders at about 44 CSS px on a 390 px device. The H5 compatibility surface explicitly maps this token to `44PX` so Taro's minimum root font size cannot enlarge controls to about 71 px. Redesigned buttons no longer use Taro's `mini` preset because its H5 rule replaced the custom flex layout and moved text into the upper half of the control; buttons and input hosts now use flex centering with compact line heights.
- Transparency: account, filter, status and adjustment layers first declare an opaque surface. Semi-transparent fills and `backdrop-filter` are enabled only inside `@supports`, so unsupported WeChat runtimes retain readable contrast.
- Hierarchy: the Kit stock panel now labels the authority once, shows the balance once at display scale and follows it with a short traceability note.
- Content robustness: Product names reserve a stable two-line area; price, stock and transaction numbers use tabular figures; long identifiers and reasons wrap only inside their content boundary.
- Assets: the implementation continues to use Product API image URLs. No new character, emoji, handcrafted SVG, CSS illustration or decorative raster was added.

## Interaction and automated evidence

- H5 compatibility preview: searching “材料包 01” returns 1 card; selecting “材料套装” returns 6 cards; loading the next page increases the list from 10 to 13 and displays “已经到底了”.
- Static gates: TypeScript, ESLint, Stylelint, OpenAPI type drift and all 17 frontend CI policy tests pass.
- Components and behavior: all 61 Jest suites / 392 tests pass.
- Builds: production `weapp` and H5 compatibility builds compile successfully. The H5 build retains the pre-existing asset/entry-size warnings.
- Impeccable detector: the single required run returned `[]`, but the result was explicitly treated as degraded because `htmlparser2`, `css-select`, `css-tree` and `domutils` were unavailable. Screenshot review and executable checks therefore remained the acceptance evidence; the detector was not rerun.
- WeChat release surface: the Stable 2.02.2608060 simulator successfully loaded the local Product API with domain validation disabled only in the ignored private project config. Captures cover the public home, authenticated global inventory and authenticated Kit inventory.
- Boundary state: the isolated local preview database was adjusted through the official Inventory API to stock `999999` with a long Chinese reason. Both the authoritative balance and the resulting first transaction remain legible without horizontal overflow.

## WeChat release-surface evidence

The actual WeChat Mini Program simulator captures are:

1. public Product home at the target device size: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/wechat-home.png`;
2. authenticated global inventory with title, filters, masked date inputs and transaction card: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/wechat-global-inventory.png`;
3. authenticated Kit inventory with identity, status, authoritative max stock and centered adjustment controls: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/wechat-product-inventory-boundary-top.png`;
4. first transaction with max-value balance and long-reason wrapping: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/wechat-product-inventory-boundary-transaction.png`.

H5 measurements at 390 × 844 px confirm a 60 × 44 px guest login button, 44 px search field and 44 px segmented filters, with centered button and input text. The same controls are visually centered in the WeChat captures above.

## 2026-09-03 typography follow-up

- Removed the redundant `拼豆店` label from the public home brand row; the header now keeps only the `pinkdooHub` wordmark.
- Introduced explicit action typography tokens: 27 rpx for regular buttons and 25 rpx for dense controls. The H5 compatibility surface maps them to fixed 14 px and 13 px values so desktop viewport width does not inflate control text.
- At 390 × 844 px, the guest login, three Product filters and load-more control render at about 14 px with 44 px control height. None report internal text overflow, and the document width remains 390 px.
- At 768 × 900 px, the same controls remain 14 px and 44 px high, remain inside the viewport and produce no horizontal page overflow.
- Post-adjustment regression gates pass: 61 frontend suites / 392 tests, 17 frontend CI policy tests, and 1693 repository tests with 9 environment-gated skips. The production WeChat artifact check also passes with `release_eligible=false`.
- This was a bounded post-ship typography verification. It does not replace or broaden the earlier independent finish verdict, and it changes no Product, account, filter or pagination behavior.

## Earlier release-surface verdict

The home and WeChat release-surface packet was independently reviewed after the control-size fix and corrected same-scale comparison. That bounded reviewer returned `disposition: ship`; the later full-route verdict below supersedes it as the current UI completion decision.

## 2026-09-03 full-surface completion

The final H5 matrix covered all 20 registered application screens at 390 × 844 px: login, registration, home, Product detail, Cart, Order Confirm, customer Order list/detail, ADMIN Product list/detail/audit/edit/configuration/images/create/inventory, global Inventory transactions, ADMIN Order list/detail and ADMIN User list. The 18 post-authentication screens were captured by one repeatable run; login and registration were then measured and captured separately in the same final build. Ten representative screens were repeated at 768 × 900 px: home, Product detail, Cart, customer Order detail, ADMIN Product list/detail/configuration, ADMIN Order list/detail and ADMIN User list. This produced 30 viewport checks.

- All 30 viewport checks reported `scrollWidth === viewportWidth`; no page-level horizontal overflow was found. The only element-level viewport flag was the home account tool strip, which is intentionally horizontally scrollable on a narrow phone.
- Login and the ADMIN Product query action were exercised as real clicks. Authentication, navigation and list summary remained functional, and the browser reported no page errors or failed requests.
- Primary, secondary, destructive, unavailable and disabled actions retain distinct semantics. Visible H5 buttons and fields use a 44 px interaction height; regular actions are 14 px and compact chips are 13 px. Inventory query/reset controls now share the same height, and inventory text inputs render at 14 px.
- Long order numbers are never truncated; identifiers may wrap within their cards. Long Chinese Product titles use balanced, word-preserving wrapping so no single Han character is stranded on a final line.
- At 768 px, customer and ADMIN Order detail actions share a centered 420 px maximum width. Empty Cart and Order Confirm actions use the same cap instead of stretching across the canvas.
- The Product detail add-to-cart action uses exact `disabled='true'` matching, preventing Taro H5's serialized `disabled='false'` from producing a false grey state. The current ADMIN account uses a neutral unavailable style rather than destructive red.

The fresh full-surface Impeccable finish reviewer first returned eight material fixes, then rechecked both correction rounds. Every item was scored resolved with `regressions: none`; the final verdict was `disposition: ship`. Root `DESIGN.md` and `.impeccable/design.json` were refreshed only after this verdict from the actual finished implementation.

This is a UI finish verdict, not permission to publish. The verified WeChat artifact remains `release_eligible=false` until the repository's existing real-Origin and release gates are satisfied.

## 2026-09-03 homepage account navigation — selected option 2

### Comparison target and normalization

- Source visual truth: `/Users/shenyijie/.codex/generated_images/01a06080-a607-74f0-ad6a-4b5b7930dd37/exec-9b3d50ef-f0e7-4fb7-804d-1b7b260c24b5.png` (1208 × 1302 px).
- Rendered implementation: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/account-ledger-option-2-implemented.png` (360 × 357 px component capture).
- Combined comparison input: `.ui-design-explorations/pinkdoo-ui-refresh/screenshots/account-ledger-option-2-comparison.png` (774 × 520 px).
- CSS viewport: 390 × 844 px, device pixel ratio 1. The implementation component is 360 CSS px wide inside 15 px page gutters. The source is proportionally fitted to the same 360 px comparison column. The in-app browser emits clipped element pixels at half the measured CSS scale, so the combined board applies a 2× display normalization only to the implementation bitmap; the layout measurements below remain browser-reported CSS pixels.
- State: authenticated ADMIN+ account with the same greeting and five destinations as the source. The comparison uses a controlled local component fixture made from the final generated H5 CSS and Taro host elements, avoiding credentials or live session mutation. Actual navigation and logout behavior is covered by the mounted page test.
- Focused evidence: the selected source is already a single focused account-navigation component rather than a complete product page, so no smaller crop is necessary. The combined input keeps greeting, both group labels, all five rows and the quiet exit action readable in one view.

### Comparison history

1. The first rendered pass exposed a P2 width mismatch: `max-width: 560px` in the 750-wide Taro source system rendered to about 291 CSS px on a 390 px device, while the selected source uses an almost full-width ledger. The implementation was changed to `700px` source width, which resolves to the available 360 CSS px between the page gutters.
2. The second rendered pass exposed a P2 row-width defect: Taro's H5 host combined `width: 100%` with horizontal padding under content-box sizing, producing 384 px rows inside a 360 px clipped panel. `box-sizing: border-box` was added; the post-fix browser measurement is 359 px for every row inside a 360 px bordered panel, with `scrollWidth === clientWidth` for all five rows and page `scrollWidth === viewportWidth === 390`.
3. The post-fix combined comparison shows no remaining P0/P1/P2 mismatch. The implementation intentionally keeps 44 px rows and more compact section bands than the exploratory source because the user requested controls that are not oversized and the live home continues into Product discovery below. The source underline on “退出” is also omitted to stay consistent with the existing quiet-action system. These are accepted product constraints, not unresolved defects.

### Required fidelity surfaces

- Fonts and typography: both sides use a compact Chinese system sans hierarchy. Implementation row labels are 14 px/650, metadata 12 px/600 and group labels 12 px/750; labels remain on one line without truncation at 390 px.
- Spacing and layout: 15 px page gutters, near-full-width ledger, 44 px row targets, 24 source-unit horizontal row padding, thin separators and an independent 44 px quiet logout target establish the selected list rhythm without horizontal scrolling.
- Colors and tokens: the existing Ribbon Ledger ink, berry and porcelain tokens are retained; section bands add only a low-span pale berry gradient, and the glass surface remains guarded by `@supports`.
- Image quality and assets: the target contains no logo, icon, illustration or Product image asset. No placeholder, emoji, inline SVG, CSS drawing or new raster asset was introduced.
- Copy and content: “我的 / 我的订单 / 查看 / 店铺管理 / 库存流水 / 管理商品 / 管理订单 / 管理用户 / 管理 / 退出” matches the selected direction while preserving every existing destination.

### Interaction and runtime evidence

- The homepage test exercises all four ADMIN+ destinations changed by this component and verifies logout; the customer state verifies that “店铺管理” remains hidden outside ADMIN+.
- Browser layout measurements confirm five 44 px rows, no row overflow and no page overflow at 390 × 844 px. The controlled comparison page reports no console logs or errors.
- The H5 build compiles successfully with only the existing Webpack asset-size recommendations. The active `npm run dev:weapp` watcher regenerated the WeChat WXSS, and the current WeChat development artifact points to `http://localhost:8000`.

final result: passed
