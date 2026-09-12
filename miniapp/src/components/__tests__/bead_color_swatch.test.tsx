import ReactTestUtil from '@tarojs/test-utils-react'

import { BeadColorSwatch } from '../bead_color_swatch'

jest.mock('@/utils/asset_url', () => ({
  resolveAssetUrl: (assetUrl: string) => `https://api.example.com${assetUrl}`,
}))

describe('BeadColorSwatch', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => {
    testUtils.unmout()
  })

  it('有 HEX 时直接绘制 View，且不请求兼容图片', async () => {
    await testUtils.mount(BeadColorSwatch, {
      props: {
        className: 'test-swatch',
        swatchHex: '#E60012',
        swatchImageUrl: '/uploads/swatches/a01.png',
      },
    })

    const swatch = required(testUtils, '.bead-color-swatch--hex') as HTMLElement
    expect(swatch.style.backgroundColor).toBe('rgb(230, 0, 18)')
    expect(testUtils.queries.querySelector('.bead-color-swatch--image')).toBeNull()
  })

  it('HEX 缺失时加载兼容图片，图片失败后显示占位', async () => {
    await testUtils.mount(BeadColorSwatch, {
      props: {
        className: 'test-swatch',
        emptyClassName: 'test-swatch--empty',
        emptyLabel: '无色样',
        swatchHex: null,
        swatchImageUrl: '/uploads/swatches/a01.png',
      },
    })

    const image = required(testUtils, '.bead-color-swatch--image')
    expect(image.getAttribute('src')).toBe('https://api.example.com/uploads/swatches/a01.png')

    await testUtils.act(async () => {
      image.dispatchEvent(new Event('error', { bubbles: true }))
      await Promise.resolve()
    })

    expect(testUtils.queries.querySelector('.bead-color-swatch--image')).toBeNull()
    expect(required(testUtils, '.test-swatch--empty').textContent).toBe('无色样')
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
