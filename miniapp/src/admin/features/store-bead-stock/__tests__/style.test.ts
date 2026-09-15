import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { devNull, tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { compile } from 'sass'

const stylesheet = resolve(__dirname, '../../../pages/store-bead-stock/index.scss')
const compiler = process.env.WXSS_COMPILER ?? '/Applications/wechatwebdevtools.app/Contents/Resources/app.asar.unpacked/node_modules/wcc-exec/wcsc'

describe('门店用豆库存 WXSS 兼容性', () => {
  it('页头按钮编译后保留共享按钮的居中与原生行高重置', () => {
    const css = compile(stylesheet).css
    const rule = css.match(/\.bead-stock__header-action\s*\{([^}]+)\}/)![1]
    // 最后生效的声明必须满足跨端按钮契约，避免局部样式覆盖 mixin。
    const declarations = Object.fromEntries([...rule.matchAll(/([a-z-]+):\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]))
    expect(declarations).toMatchObject({ display: 'flex', 'align-items': 'center', 'justify-content': 'center', 'line-height': '1.2', 'box-sizing': 'border-box' })
  })

  it('页头伸缩使用明确类名，不依赖 WXSS 不支持的否定伪类', () => {
    const css = compile(stylesheet).css
    expect(css).toContain('.bead-stock__header-copy')
    expect(css).not.toContain(':not(')
    expect(css).not.toMatch(/>\s*:/)
    expect(css).not.toMatch(/>\s*\*/)
  })

  // 有开发者工具的环境直接验证微信编译器；其他环境保留静态回归守卫。
  ;(existsSync(compiler) ? it : it.skip)('整页样式通过微信原生编译器', () => {
    const css = compile(stylesheet).css
    const directory = mkdtempSync(join(tmpdir(), 'pinkdoo-stock-wxss-'))
    try {
      writeFileSync(join(directory, 'stock.wxss'), css)
      expect(() => execFileSync(compiler, ['stock.wxss', '-o', devNull], { cwd: directory, timeout: 10_000, stdio: 'pipe' })).not.toThrow()
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })
})
