import { Text, View } from '@tarojs/components'
import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, TimeoutError } from '@/api'
import type {
  AdminProductConfigurationFeature,
  AdminProductConfigurationSource,
} from '@/features/product'

import { useAdminProductConfigurationMutation } from '../use_admin_product_configuration_mutation'

let feature: AdminProductConfigurationFeature

function Harness({ source }: { readonly source: AdminProductConfigurationSource }) {
  feature = useAdminProductConfigurationMutation(source)
  return <View><Text className='status'>{feature.state.status}</Text></View>
}

describe('useAdminProductConfigurationMutation', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('Option POST 期间合并重复点击并保留服务端原 Option ID', async () => {
    const deferred = createDeferred<OptionResult>()
    const source = createSource({ createExperienceOption: jest.fn(() => deferred.promise) })
    await testUtils.mount(Harness, { props: { source } })
    const request = { duration_minutes: 60, participants: 1, day_type: 'weekday' as const, price: '99.00' }
    let first!: Promise<unknown>
    let second!: Promise<unknown>
    await testUtils.act(async () => {
      first = feature.createOption(7, request)
      second = feature.createOption(7, request)
    })
    expect(first).toBe(second)
    expect(source.createExperienceOption).toHaveBeenCalledTimes(1)
    deferred.resolve(optionResult())
    await testUtils.act(async () => { await first })
    expect(feature.state).toEqual({ status: 'succeeded', result: { action: 'create_option', option: optionResult() } })
  })

  it('改价 Timeout 进入 unknown 且不自动重发', async () => {
    const source = createSource({
      updateKitPrice: jest.fn(async () => {
        throw new TimeoutError({ operation: 'products.admin.kit.price.update' }, new Error('timeout'))
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => { await feature.updateKitPrice(8, '199.00') })
    expect(feature.state.status).toBe('unknown')
    expect(source.updateKitPrice).toHaveBeenCalledTimes(1)
  })

  it('重复组合 40911 是明确失败并给出稳定提示', async () => {
    const source = createSource({
      updateExperienceOption: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'products.admin.experience_option.update', statusCode: 409 },
          40911,
          'Experience option already exists',
          null,
        )
      }),
    })
    await testUtils.mount(Harness, { props: { source } })
    await testUtils.act(async () => { await feature.updateOption(21, { price: '109.00' }) })
    expect(feature.state.status).toBe('failed')
    if (feature.state.status === 'failed') expect(feature.state.errorMessage).toContain('相同时长')
  })

  it('逻辑删除与 Kit 改价返回分型结果', async () => {
    const source = createSource({})
    await testUtils.mount(Harness, { props: { source } })
    await expect(feature.deleteOption(21)).resolves.toEqual({
      action: 'delete_option', option: { id: 21, is_deleted: true },
    })
    feature.reset()
    await expect(feature.updateKitPrice(8, '199.00')).resolves.toEqual({
      action: 'update_kit_price', kit: { id: 8, price: '199.00' },
    })
  })
})

type OptionResult = ReturnType<typeof optionResult>

function optionResult() {
  return {
    id: 21,
    duration: { value: 60, label: '1 小时' },
    participants: { value: 1, label: '1 人' },
    day_type: { value: 'weekday' as const, label: '工作日' },
    price: '99.00',
    images: [],
  }
}

function createSource(overrides: Partial<AdminProductConfigurationSource>): AdminProductConfigurationSource {
  return {
    createExperienceOption: jest.fn(async () => optionResult()),
    updateExperienceOption: jest.fn(async () => {
      const { images: _images, ...base } = optionResult()
      return base
    }),
    deleteExperienceOption: jest.fn(async () => ({ id: 21, is_deleted: true as const })),
    updateKitPrice: jest.fn(async (_productId, request) => ({ id: 8, price: request.price })),
    ...overrides,
  }
}

function createDeferred<T>(): { readonly promise: Promise<T>; resolve(value: T): void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}
