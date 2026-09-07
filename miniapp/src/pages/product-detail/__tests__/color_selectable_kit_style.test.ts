import { join } from 'node:path'

import { compile } from 'sass'

const stylesheet = join(__dirname, '..', 'index.scss')

describe('自选颜色 Kit 色板布局', () => {
  const css = compile(stylesheet).css

  function declarationsFor(selector: string): string {
    const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))
    if (!match) throw new Error(`${selector} rule not found`)
    return match[1]
  }

  it('手机使用六列方形色板，宽屏扩展为十列', () => {
    const gridDeclarations = declarationsFor('.color-grid')

    expect(css).toMatch(
      /\.color-grid\s*\{[^}]*grid-template-columns: repeat\(6, minmax\(0, 1fr\)\)/,
    )
    expect(css).toMatch(
      /@media \(width >= 768px\)[^{]*\{[\s\S]*?\.color-grid\s*\{[^}]*grid-template-columns: repeat\(10, minmax\(0, 1fr\)\)/,
    )
    expect(css).toMatch(
      /\.color-card::before\s*\{[^}]*padding-top: 100%/,
    )
    expect(gridDeclarations).toContain('gap: 12px')
    expect(gridDeclarations).toContain('padding: 2px')
    expect(gridDeclarations).toContain('box-sizing: border-box')
  })

  it('色样铺满格子，名称无底框并直接居中色块', () => {
    const copyDeclarations = declarationsFor('.color-card__copy')

    expect(copyDeclarations).toContain('position: absolute')
    expect(copyDeclarations).toContain('inset: 0')
    expect(copyDeclarations).toContain('display: flex')
    expect(copyDeclarations).toContain('align-items: center')
    expect(copyDeclarations).toContain('justify-content: center')
    expect(copyDeclarations).toContain('background: transparent')
    expect(copyDeclarations).toContain('border: 0')
    expect(copyDeclarations).toContain('box-shadow: none')
    expect(css).toMatch(
      /\.color-card > \.color-swatch\s*\{[^}]*position: absolute;[^}]*width: 100%;[^}]*height: 100%;/,
    )
    const selectedDeclarations = declarationsFor('.color-card--selected')
    const selectedLabelDeclarations = declarationsFor('.color-card__selected-label')

    expect(selectedDeclarations).toContain('border-width: 3px')
    expect(selectedDeclarations).toContain('inset 0 0 0 2px var(--pd-color-surface)')
    expect(selectedDeclarations).toContain('0 0 0 2px var(--pd-color-primary-strong)')
    expect(selectedDeclarations).toContain('transform: translateY(-2px)')
    expect(selectedLabelDeclarations).toContain('position: absolute')
    expect(selectedLabelDeclarations).toContain('background: var(--pd-color-primary-strong)')
    expect(selectedLabelDeclarations).toContain('border: 2px solid var(--pd-color-surface)')
    expect(css).not.toContain('.color-card--selected .color-card__copy')
  })
})
