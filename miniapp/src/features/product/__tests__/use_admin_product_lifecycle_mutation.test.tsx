import { Text, View } from '@tarojs/components'
import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, TimeoutError } from '@/api'
import type {
  AdminProductLifecycleFeature,
  AdminProductLifecycleSource,
} from '@/features/product'

import {
  MAX_PRODUCT_IMAGE_BYTES,
  translateReadinessIssue,
  useAdminProductLifecycleMutation,
} from '../use_admin_product_lifecycle_mutation'

let feature: AdminProductLifecycleFeature

function Harness({ source }: { readonly source: AdminProductLifecycleSource }) {
  feature = useAdminProductLifecycleMutation(source)
  return <View><Text className='status'>{feature.state.status}</Text></View>
}

describe('useAdminProductLifecycleMutation', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('multipart 上传期间合并重复点击，只调用一次 source', async () => {
    const deferred = createDeferred<ProductImage>()
    const source = createSource({ uploadProductImage: jest.fn(() => deferred.promise) })
    await testUtils.mount(Harness, { props: { source } })
    const file = { filePath: 'wxfile://cover.png', size: 1_024, mediaType: 'image/png' }
    let first!: Promise<unknown>
    let second!: Promise<unknown>
    await testUtils.act(async () => {
      first = feature.uploadProductImage(7, file, true)
      second = feature.uploadProductImage(7, file, true)
    })
    expect(first).toBe(second)
    expect(source.uploadProductImage).toHaveBeenCalledTimes(1)
    deferred.resolve(productImage())
    await testUtils.act(async () => { await first })
    expect(feature.state).toEqual({
      status: 'succeeded',
      result: { action: 'upload_product_image', image: productImage() },
    })
  })

  it('客户端提前拒绝超 2 MiB 和不支持 MIME，且不调用上传 source', async () => {
    const source = createSource({})
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => {
      await feature.uploadProductImage(7, {
        filePath: 'wxfile://large.png', size: MAX_PRODUCT_IMAGE_BYTES + 1, mediaType: 'image/png',
      }, false)
    })
    expect(feature.state.status).toBe('failed')
    if (feature.state.status === 'failed') expect(feature.state.errorMessage).toContain('2 MiB')
    expect(source.uploadProductImage).not.toHaveBeenCalled()
    feature.reset()
    await testUtils.act(async () => {
      await feature.uploadOptionImage(21, {
        filePath: 'wxfile://bad.gif', size: 100, mediaType: 'image/gif',
      })
    })
    if (feature.state.status === 'failed') expect(feature.state.errorMessage).toContain('jpg')
    expect(source.uploadOptionImage).not.toHaveBeenCalled()
  })

  it('上传 Timeout 进入 unknown，且不自动重发', async () => {
    const source = createSource({
      uploadOptionImage: jest.fn(async () => {
        throw new TimeoutError({ operation: 'products.admin.option_image.upload' }, new Error('timeout'))
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => {
      await feature.uploadOptionImage(21, { filePath: 'wxfile://option.webp', size: 100 })
    })
    expect(feature.state.status).toBe('unknown')
    expect(source.uploadOptionImage).toHaveBeenCalledTimes(1)
  })

  it('42201 一次保留全部 readiness issues，未知 issue 不丢失', async () => {
    const issues = [
      'product description is required',
      'product cover image is required',
      'option 21 has no image',
      'future server issue',
    ]
    const source = createSource({
      onlineProduct: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'products.admin.online', statusCode: 422 },
          42201,
          'Product is not ready to go online',
          { issues },
        )
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => { await feature.onlineProduct(7) })
    expect(feature.state.status).toBe('failed')
    if (feature.state.status === 'failed') expect(feature.state.readinessIssues).toEqual(issues)
    expect(translateReadinessIssue('option 21 has no image')).toContain('Option #21')
    expect(translateReadinessIssue('future server issue')).toBe('future server issue')
  })

  it('42221 使用稳定图片原因提示，状态成功结果保持服务端目标状态', async () => {
    const invalidSource = createSource({
      uploadProductImage: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'products.admin.product_image.upload', statusCode: 422 },
          42221,
          'Invalid image file',
          { reason: 'content_type_mismatch' },
        )
      }),
    })
    await testUtils.mount(Harness, { props: { source: invalidSource } })
    await testUtils.act(async () => {
      await feature.uploadProductImage(7, { filePath: 'wxfile://bad.jpg', size: 100 }, false)
    })
    if (feature.state.status === 'failed') expect(feature.state.errorMessage).toContain('文件类型不一致')

    testUtils.unmout()
    testUtils = new ReactTestUtil()
    const source = createSource({})
    await testUtils.mount(Harness, { props: { source } })
    await expect(feature.offlineProduct(7)).resolves.toEqual({
      action: 'offline',
      product: { id: 7, status: { value: 'offline', label: '已下架' } },
    })
  })
})

type ProductImage = ReturnType<typeof productImage>

function productImage() {
  return { id: 31, image_url: '/uploads/products/cover.png', is_cover: true, sort: 0 }
}

function createSource(overrides: Partial<AdminProductLifecycleSource>): AdminProductLifecycleSource {
  return {
    uploadProductImage: jest.fn(async () => productImage()),
    uploadOptionImage: jest.fn(async () => ({
      id: 32, image_url: '/uploads/products/option.png', sort: 0,
    })),
    updateProductImage: jest.fn(async () => productImage()),
    deleteProductImage: jest.fn(async (imageId) => ({ id: imageId, is_deleted: true as const })),
    onlineProduct: jest.fn(async (productId) => ({
      id: productId, status: { value: 'online' as const, label: '已上架' },
    })),
    offlineProduct: jest.fn(async (productId) => ({
      id: productId, status: { value: 'offline' as const, label: '已下架' },
    })),
    ...overrides,
  }
}

function createDeferred<T>(): { readonly promise: Promise<T>; resolve(value: T): void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}
