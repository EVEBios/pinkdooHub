import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import CustomTabBar from '../index'

describe('CustomTabBar', () => {
  let testUtils: ReactTestUtil
  const switchTab = Taro.switchTab as jest.MockedFunction<typeof Taro.switchTab>
  const getCurrentPages = Taro.getCurrentPages as jest.MockedFunction<typeof Taro.getCurrentPages>

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    switchTab.mockResolvedValue({ errMsg: 'switchTab:ok' })
    getCurrentPages.mockReturnValue([
      { route: 'pages/index/index' },
    ] as ReturnType<typeof Taro.getCurrentPages>)
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('渲染四个主入口，默认高亮商城', async () => {
    await testUtils.mount(CustomTabBar)

    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')
    expect(items).toHaveLength(4)
    expect(Array.from(items, (item) => item.textContent)).toEqual(['商城', '预约', '订单', '会员中心'])
    expect(items[0].classList.contains('root-tab-bar__item--selected')).toBe(true)
    expect(items[0].querySelector('.root-tab-bar__icon-seat--selected')).not.toBeNull()
    expect(items[0].querySelector('.root-tab-bar__icon--selected')).not.toBeNull()
    expect(items[0].querySelector('.root-tab-bar__label--selected')).not.toBeNull()
    expect(items[0].getAttribute('aria-label')).toContain('当前页面')
  })

  it('点击其他入口时使用 switchTab，且不重复打开当前页', async () => {
    await testUtils.mount(CustomTabBar)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    testUtils.fireEvent.click(items[1])
    await flush(testUtils)

    expect(switchTab).toHaveBeenCalledWith({ url: '/pages/reservations/index' })
    expectSelectedItem(items, 0)

    testUtils.fireEvent.click(items[0])
    expect(switchTab).toHaveBeenCalledTimes(1)
  })

  it('只有页面生命周期调用 setSelected 后才更新选中项', async () => {
    let tabBar: CustomTabBar | null = null

    function Harness() {
      return <CustomTabBar ref={(instance) => { tabBar = instance }} />
    }

    await testUtils.mount(Harness)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    expectSelectedItem(items, 0)
    await testUtils.act(async () => {
      tabBar?.setSelected(2)
    })

    expectSelectedItem(items, 2)
  })

  it('实例选中态尚未同步时，仍以真实页面路径决定是否跳转', async () => {
    getCurrentPages.mockReturnValue([])
    await testUtils.mount(CustomTabBar)
    getCurrentPages.mockReturnValue([
      { route: 'pages/reservations/index' },
    ] as ReturnType<typeof Taro.getCurrentPages>)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    testUtils.fireEvent.click(items[0])
    await flush(testUtils)

    expect(switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
  })

  it('冷启动到非商城 Tab 时直接使用当前路径初始化高亮', async () => {
    getCurrentPages.mockReturnValue([
      { route: 'pages/member/index' },
    ] as ReturnType<typeof Taro.getCurrentPages>)
    await testUtils.mount(CustomTabBar)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    expect(items[3].classList.contains('root-tab-bar__item--selected')).toBe(true)
    expect(items[0].classList.contains('root-tab-bar__item--selected')).toBe(false)
  })

  it('跳转失败时始终保持当前页面的唯一选中态', async () => {
    switchTab.mockRejectedValueOnce(new Error('navigation failed'))
    await testUtils.mount(CustomTabBar)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    testUtils.fireEvent.click(items[2])
    expectSelectedItem(items, 0)
    await flush(testUtils)

    expectSelectedItem(items, 0)
  })

  it('快速连续点击不会让源页面实例高亮任一目标入口', async () => {
    await testUtils.mount(CustomTabBar)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    testUtils.fireEvent.click(items[1])
    testUtils.fireEvent.click(items[2])
    expectSelectedItem(items, 0)
    await flush(testUtils)

    expect(switchTab).toHaveBeenNthCalledWith(1, { url: '/pages/reservations/index' })
    expect(switchTab).toHaveBeenNthCalledWith(2, { url: '/pages/orders/index' })
    expectSelectedItem(items, 0)
  })

  it('旧跳转迟到失败时不会按新页面路径污染源页面实例', async () => {
    const firstNavigation = deferred<Awaited<ReturnType<typeof Taro.switchTab>>>()
    const secondNavigation = deferred<Awaited<ReturnType<typeof Taro.switchTab>>>()
    switchTab
      .mockReturnValueOnce(firstNavigation.promise)
      .mockReturnValueOnce(secondNavigation.promise)
    await testUtils.mount(CustomTabBar)
    const items = testUtils.queries.querySelectorAll('.root-tab-bar__item')

    testUtils.fireEvent.click(items[1])
    testUtils.fireEvent.click(items[2])
    await testUtils.act(async () => {
      getCurrentPages.mockReturnValue([
        { route: 'pages/orders/index' },
      ] as ReturnType<typeof Taro.getCurrentPages>)
      secondNavigation.resolve({ errMsg: 'switchTab:ok' })
      firstNavigation.reject(new Error('stale navigation failed'))
      await Promise.resolve()
      await Promise.resolve()
    })

    expectSelectedItem(items, 0)
  })
})

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
  })
}

function expectSelectedItem(items: NodeListOf<Element>, expectedIndex: number): void {
  const selectedItems = Array.from(items).filter((item) => (
    item.classList.contains('root-tab-bar__item--selected')
  ))
  const expectedItem = items[expectedIndex]

  expect(selectedItems).toHaveLength(1)
  expect(selectedItems[0]).toBe(expectedItem)

  for (const selectedModifier of [
    '.root-tab-bar__icon-seat--selected',
    '.root-tab-bar__icon--selected',
    '.root-tab-bar__label--selected',
  ]) {
    const matches = Array.from(items).flatMap((item) => (
      Array.from(item.querySelectorAll(selectedModifier))
    ))

    expect(matches).toHaveLength(1)
    expect(matches[0]).toBe(expectedItem.querySelector(selectedModifier))
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, reject, resolve }
}
