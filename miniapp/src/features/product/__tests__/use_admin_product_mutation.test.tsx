import ReactTestUtil from '@tarojs/test-utils-react'
import { Text, View } from '@tarojs/components'

import { BusinessError, ContractError, HttpError, TimeoutError } from '@/api'
import type {
  DeletedProductResult,
  ExperienceProductCreateResult,
  KitProductCreateResult,
  ProductBasicInfoResult,
} from '@/api/endpoints/admin_products'

import {
  type AdminProductMutationFeature,
  type AdminProductMutationSource,
  isAdminProductMutationUnknownError,
  useAdminProductMutation,
} from '../use_admin_product_mutation'

const experienceResult: ExperienceProductCreateResult = {
  id: 11,
  name: '新体验',
  product_type: { value: 'experience', label: '拼豆体验' },
  status: { value: 'draft', label: '草稿' },
}

let feature: AdminProductMutationFeature

function Harness({ source }: { readonly source: AdminProductMutationSource }) {
  feature = useAdminProductMutation(source)
  return (
    <View>
      <Text className='status'>{feature.state.status}</Text>
      <Text className='message'>
        {feature.state.status === 'failed' || feature.state.status === 'unknown'
          ? feature.state.errorMessage
          : ''}
      </Text>
    </View>
  )
}

describe('useAdminProductMutation', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => testUtils.unmout())

  it('创建期间复用同一 Promise，成功保留服务端 Product ID', async () => {
    const deferred = createDeferred<ExperienceProductCreateResult>()
    const source = createSource({ createExperienceProduct: jest.fn(() => deferred.promise) })
    await testUtils.mount(Harness, { props: { source } })

    let first!: Promise<unknown>
    let second!: Promise<unknown>
    await testUtils.act(async () => {
      first = feature.createExperience({ name: '新体验' })
      second = feature.createExperience({ name: '重复点击' })
    })
    expect(first).toBe(second)
    expect(source.createExperienceProduct).toHaveBeenCalledTimes(1)
    expect(text(testUtils, '.status')).toBe('submitting')

    deferred.resolve(experienceResult)
    await testUtils.act(async () => { await first })
    expect(feature.state).toEqual({
      status: 'succeeded',
      result: { action: 'create_experience', product: experienceResult },
    })
  })

  it('Timeout 进入 unknown 且不自动重放', async () => {
    const source = createSource({
      createKitProduct: jest.fn(async () => {
        throw new TimeoutError({ operation: 'products.admin.kit.create' }, new Error('timeout'))
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => {
      await feature.createKit({ name: '新套装', price: '99.00' })
    })
    expect(text(testUtils, '.status')).toBe('unknown')
    expect(text(testUtils, '.message')).toContain('不会自动重试')
    expect(source.createKitProduct).toHaveBeenCalledTimes(1)
  })

  it('明确删除前置条件进入 failed 并映射稳定提示', async () => {
    const source = createSource({
      deleteProduct: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'products.admin.delete', statusCode: 409 },
          40904,
          'Product must be offline before deletion',
          null,
        )
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => { await feature.deleteProduct(7) })
    expect(text(testUtils, '.status')).toBe('failed')
    expect(text(testUtils, '.message')).toContain('必须先下架')
  })

  it('PATCH 与 DELETE 返回判别结果', async () => {
    const updated: ProductBasicInfoResult = {
      id: 7,
      name: '新版商品',
      description: null,
      updated_at: '2026-08-25T10:00:00Z',
    }
    const deleted: DeletedProductResult = { id: 7, is_deleted: true }
    const source = createSource({
      updateProductBasicInfo: jest.fn(async () => updated),
      deleteProduct: jest.fn(async () => deleted),
    })
    await testUtils.mount(Harness, { props: { source } })
    await expect(feature.updateBasicInfo(7, { description: null }))
      .resolves.toEqual({ action: 'update_basic_info', product: updated })
    feature.reset()
    await expect(feature.deleteProduct(7)).resolves.toEqual({ action: 'delete', product: deleted })
  })

})

describe('ADMIN Product mutation unknown 分类', () => {
  it('只把 Contract 与 5xx HTTP 归为结果未知', () => {
    expect(isAdminProductMutationUnknownError(
      new ContractError({ operation: 'products.admin.delete' }),
    )).toBe(true)
    expect(isAdminProductMutationUnknownError(
      new HttpError({ operation: 'products.admin.delete', statusCode: 503 }, null),
    )).toBe(true)
    expect(isAdminProductMutationUnknownError(
      new HttpError({ operation: 'products.admin.delete', statusCode: 400 }, null),
    )).toBe(false)
  })
})

function createSource(overrides: Partial<AdminProductMutationSource>): AdminProductMutationSource {
  const kit: KitProductCreateResult = {
    id: 12,
    name: '新套装',
    product_type: { value: 'kit', label: '拼豆套装' },
    status: { value: 'draft', label: '草稿' },
  }
  return {
    createExperienceProduct: jest.fn(async () => experienceResult),
    createKitProduct: jest.fn(async () => kit),
    updateProductBasicInfo: jest.fn(async () => ({
      id: 7,
      name: '商品',
      description: null,
      updated_at: '2026-08-25T10:00:00Z',
    })),
    deleteProduct: jest.fn(async () => ({ id: 7, is_deleted: true as const })),
    ...overrides,
  }
}

function createDeferred<T>(): {
  readonly promise: Promise<T>
  resolve(value: T): void
} {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

function text(testUtils: ReactTestUtil, selector: string): string {
  return testUtils.queries.querySelector(selector)?.textContent ?? ''
}
