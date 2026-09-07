import { join } from 'node:path'

import { compile, compileString } from 'sass'

const stylesDirectory = join(__dirname, '..')

describe('共享按钮禁用态', () => {
  it('使用小程序与 H5 兼容的 disabled 属性，并阻止禁用按钮出现按压位移', () => {
    const css = compile(join(stylesDirectory, 'theme.scss')).css

    expect(css).toContain('button[disabled]')
    expect(css).toContain('button:active')
    expect(css).toContain('button[disabled]:active')
    expect(css).not.toContain(':disabled')
    expect(css).not.toContain(':not(')
    expect(css).toContain('opacity: 0.62')
  })

  it.each(['primary-button', 'secondary-button', 'quiet-button', 'danger-button', 'chip'])(
    '%s 使用统一的低强调禁用外观',
    (mixin) => {
      const css = compileString(
        `@use 'patterns' as pd; .subject { @include pd.${mixin}; }`,
        { loadPaths: [stylesDirectory] },
      ).css

      expect(css).toContain('.subject[disabled]')
      expect(css).toContain('color: var(--pd-color-ink-soft)')
      expect(css).toContain('background: var(--pd-color-surface-muted)')
      expect(css).toContain('border: 1px solid var(--pd-color-line)')
      expect(css).toContain('box-shadow: none')
      expect(css).toContain('opacity: 0.62')
    },
  )
})
