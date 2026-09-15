import { resolveAssetUrl } from '../asset_url'

describe('resolveAssetUrl', () => {
  it('保留绝对图片 URL', () => {
    expect(resolveAssetUrl('https://cdn.example.com/product.webp', 'https://api.example.com'))
      .toBe('https://cdn.example.com/product.webp')
  })

  it('使用 API Origin 补全开发期相对图片路径', () => {
    expect(resolveAssetUrl('/uploads/products/product.webp', 'http://127.0.0.1:8000/'))
      .toBe('http://127.0.0.1:8000/uploads/products/product.webp')
  })

  it('拒绝无法确定来源的相对路径', () => {
    expect(() => resolveAssetUrl('uploads/product.webp', 'https://api.example.com'))
      .toThrow('图片地址必须是 HTTP(S) URL 或以 / 开头的路径')
  })
})
