import { join } from 'node:path'

import { compile } from 'sass'

const stylesheet = join(__dirname, '..', 'index.scss')

describe('代客扣款自选颜色布局', () => {
  const css = compile(stylesheet).css

  it('手机使用六列纯文字色号网格，宽屏扩展为十列', () => {
    expect(css).toMatch(
      /\.wallet-order-color-grid\s*\{[^}]*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/,
    )
    expect(css).toMatch(
      /@media \(width >= 768px\)[^{]*\{[\s\S]*?\.wallet-order-color-grid\s*\{[^}]*grid-template-columns: repeat\(10, minmax\(0, 1fr\)\)/,
    )
    expect(css).toMatch(
      /\.wallet-order-color-option::before\s*\{[^}]*padding-top: 100%/,
    )
    expect(css).not.toMatch(/\.wallet-order-color-(?:grid|option)[^{]*\{[^}]*background-image:/)
  })

  it('已选颜色用独立列表呈现文字身份、重量与数量控件', () => {
    expect(css).toMatch(
      /\.wallet-order-selected-color\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\) auto/,
    )
    expect(css).toMatch(
      /\.wallet-order-selected-color__controls\s*\{[^}]*grid-template-columns: var\(--pd-control-height\) 44px var\(--pd-control-height\)/,
    )
  })
})
