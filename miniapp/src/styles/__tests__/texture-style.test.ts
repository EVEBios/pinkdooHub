import { join } from 'node:path'

import { compile, compileString } from 'sass'

const stylesDirectory = join(__dirname, '..')

describe('共享页头纹理', () => {
  it('只在全局主题声明图片，并让页面 mixin 引用共享变量', () => {
    const theme = compile(join(stylesDirectory, 'theme.scss')).css
    const page = compileString(
      "@use 'ribbon' as ribbon; .subject { @include ribbon.page-header; }",
      { loadPaths: [stylesDirectory] },
    ).css

    expect(theme).toContain(
      "--pd-image-header-texture: url('../assets/admin/workbench-header-texture.jpg')",
    )
    expect(page).toContain('var(--pd-image-header-texture)')
    expect(page).not.toContain('workbench-header-texture.jpg')
    expect(page).not.toContain('data:image')
  })
})
