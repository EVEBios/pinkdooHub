import { Button, Text, View } from '@tarojs/components'
import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { DestinationNavigationTarget } from '../use_latest_destination_navigation'
import {
  resolvePathNavigationTarget,
  useLatestDestinationNavigation,
} from '../use_latest_destination_navigation'

let controls: ReturnType<typeof useLatestDestinationNavigation> | undefined

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    reLaunch: jest.fn(() => Promise.resolve()),
    switchTab: jest.fn(() => Promise.resolve()),
  },
}))

function Subject() {
  controls = useLatestDestinationNavigation()
  return (
    <View>
      <Text className='navigation-error'>{controls.navigationError}</Text>
      <Button
        className='retry'
        onClick={() => void controls?.openDestination({
          method: 'reLaunch',
          url: '/admin/pages/workbench/index',
        })}
      >重试</Button>
    </View>
  )
}

describe('latest destination navigation', () => {
  let testUtils: ReactTestUtil

  beforeEach(async () => {
    testUtils = new ReactTestUtil()
    controls = undefined
    await testUtils.mount(Subject)
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('根 Tab 使用 switchTab，二级与管理页面使用 reLaunch', () => {
    expect(resolvePathNavigationTarget('/pages/orders/index')).toEqual({
      method: 'switchTab',
      url: '/pages/orders/index',
    })
    expect(resolvePathNavigationTarget('/pages/order-confirm/index')).toEqual({
      method: 'reLaunch',
      url: '/pages/order-confirm/index',
    })
    expect(resolvePathNavigationTarget('/admin/pages/workbench/index')).toEqual({
      method: 'reLaunch',
      url: '/admin/pages/workbench/index',
    })
  })

  it('旧导航未结束时不并发，并在结束后只重放最新角色目标', async () => {
    let rejectOld!: (cause: unknown) => void
    ;(Taro.switchTab as jest.Mock).mockReturnValueOnce(new Promise((_, reject) => {
      rejectOld = reject
    }))
    const customerTarget: DestinationNavigationTarget = {
      method: 'switchTab',
      url: '/pages/orders/index',
    }
    const adminTarget: DestinationNavigationTarget = {
      method: 'reLaunch',
      url: '/admin/pages/workbench/index',
    }

    void controls?.openDestination(customerTarget)
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)
    void controls?.openDestination(adminTarget)
    expect(Taro.reLaunch).not.toHaveBeenCalled()

    await testUtils.act(async () => rejectOld(new Error('old target failed')))
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
    expect(required(testUtils, '.navigation-error').textContent).toBe('')
  })

  it('已落点 A 后经过在途 B 又回到 A 时，会在 B 成功后重放 A', async () => {
    const adminTarget: DestinationNavigationTarget = {
      method: 'reLaunch',
      url: '/admin/pages/workbench/index',
    }
    const customerTarget: DestinationNavigationTarget = {
      method: 'switchTab',
      url: '/pages/orders/index',
    }
    await testUtils.act(async () => {
      await controls?.openDestination(adminTarget)
    })

    let resolveCustomer!: () => void
    ;(Taro.switchTab as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveCustomer = resolve
    }))
    void controls?.openDestination(customerTarget)
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)

    void controls?.openDestination(adminTarget)
    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)

    await testUtils.act(async () => resolveCustomer())
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
    expect(Taro.reLaunch).toHaveBeenLastCalledWith({ url: '/admin/pages/workbench/index' })
    expect(required(testUtils, '.navigation-error').textContent).toBe('')
  })

  it('当前目标失败后显示错误，并允许同一目标显式重试', async () => {
    ;(Taro.reLaunch as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    const target: DestinationNavigationTarget = {
      method: 'reLaunch',
      url: '/admin/pages/workbench/index',
    }

    await testUtils.act(async () => {
      await controls?.openDestination(target)
    })
    expect(required(testUtils, '.navigation-error').textContent).toContain('页面暂时无法打开')

    testUtils.fireEvent.click(required(testUtils, '.retry'))
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
