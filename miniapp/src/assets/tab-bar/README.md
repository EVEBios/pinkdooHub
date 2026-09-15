# TabBar icons

The four navigation symbols are derived from Heroicons v2.2.0:

- `building-storefront` for 商城
- `calendar-days` for 预约
- `shopping-cart` for 购物车；原 `document-text` 订单素材保留供既有界面使用
- `user` for 会员中心
- `plus` (24px outline, white) for the reservation creation action; [v2.2.0 source](https://github.com/tailwindlabs/heroicons/blob/v2.2.0/optimized/24/outline/plus.svg), rasterized at 81 × 81 px
- `home` (24px outline) for the small return-to-mall button in the table-flow header

The source SVGs are published by Tailwind Labs under the MIT License. They are rasterized locally at 81 × 81 px in the product's ink, white, and berry colors so every Taro target can consume stable local assets without a runtime icon dependency. The home icon uses the [v2.2.0 outline source](https://github.com/tailwindlabs/heroicons/blob/v2.2.0/optimized/24/outline/home.svg) with a white stroke. See `HEROICONS_LICENSE.txt` for the upstream license.

Member order shortcuts use Heroicons v2.2.0 `receipt-percent`, `document-check`, and `check-circle` (24px solid, berry), plus `chevron-right` (24px outline, dark berry). Cart uses `shopping-cart` outline/solid in the same existing three colors. Sources: `https://github.com/tailwindlabs/heroicons/tree/v2.2.0/optimized/24`. All new PNGs are 81 × 81 px and reuse the existing MIT license; no runtime dependency was added.

Member refinement (2026-09-13): `document-currency-yen-white`, `document-check-white`, `shopping-bag-white`, and `chevron-right-white` are Heroicons v2.2.0 24px outline sources, rasterized at 144 × 144 px in white. They reuse `HEROICONS_LICENSE.txt`.

`wallet-rose.png` is a custom Image Gen asset based on the user-approved member mockup, retaining its slanted banknote and clasp. The generated white background was removed, the visible bounds trimmed, and the result fitted proportionally into a transparent 144 × 144 PNG. Source generation: `exec-3ca45068-aad5-47ec-a208-4e2e6fb69d59.png`; target mock: `exec-14adb75b-7ed3-4915-8637-04c5082b06ff.png`. This asset is not derived from Heroicons. No runtime dependency was added.

Member attention refinement (2026-09-14): `table-two-chairs-white.png` is a custom Image Gen asset matching the user-selected Option 2 mockup. It depicts one central table and two symmetric chairs, with white rounded strokes. Source generation: `exec-dfe11747-0a29-4703-94be-51587fa4eebd.png`; target mock: `exec-ba789c7c-04f4-409e-8183-f8c683f5d1ec.png`. The opaque checkerboard was removed to create an actual alpha channel; the glyph was trimmed and fitted proportionally into a 144 × 144 transparent PNG. This replaces the earlier one-chair MDI asset, whose unused PNG and license have been removed. Existing white Heroicons chevron and order document assets are unchanged; no runtime dependency was added.

Generation brief: faithfully reproduce the selected mockup's single table with a central pedestal and two inward-facing side chairs; symmetric silhouette, slightly outward-leaning backrests, rounded white strokes, no surrounding frame or text, readable at 32 × 32 px. Generated with the built-in Image Gen tool; no CLI/API fallback.
