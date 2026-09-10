import Taro from '@tarojs/taro'

import { ADMIN_WORKBENCH_PATH } from '@/auth'

import {
  isRootTabUrl,
  ROOT_TAB_INDEX,
  ROOT_TABS,
  syncRootTabSelection,
  type RootTabBarHandle,
} from '../root_tabs'

describe('root tabs', () => {
  afterEach(() => {
    jest.clearAllMocks()
    jest.restoreAllMocks()
  })

  it('固定四个主入口的顺序、文案与路径', () => {
    expect(ROOT_TABS).toEqual([
      { index: 0, text: '商城', pagePath: 'pages/index/index', url: '/pages/index/index' },
      { index: 1, text: '预约', pagePath: 'pages/reservations/index', url: '/pages/reservations/index' },
      { index: 2, text: '订单', pagePath: 'pages/orders/index', url: '/pages/orders/index' },
      { index: 3, text: '会员中心', pagePath: 'pages/member/index', url: '/pages/member/index' },
    ])
    expect(ROOT_TABS.map((tab) => tab.url)).not.toContain(ADMIN_WORKBENCH_PATH)
    expect(ROOT_TABS.every((tab) => isRootTabUrl(tab.url))).toBe(true)
    expect(isRootTabUrl('/pages/order-confirm/index')).toBe(false)
    expect(isRootTabUrl(ADMIN_WORKBENCH_PATH)).toBe(false)
  })

  it('把当前页面的选中项同步给微信自定义 TabBar 实例', () => {
    const page = {} as NonNullable<ReturnType<typeof Taro.getCurrentInstance>['page']>
    const tabBar: RootTabBarHandle = { setSelected: jest.fn() }
    jest.spyOn(Taro, 'getCurrentInstance').mockReturnValue({ page } as ReturnType<typeof Taro.getCurrentInstance>)
    jest.spyOn(Taro, 'getTabBar').mockReturnValue(tabBar)

    syncRootTabSelection(ROOT_TAB_INDEX.member)

    expect(Taro.getTabBar).toHaveBeenCalledWith(page)
    expect(tabBar.setSelected).toHaveBeenCalledWith(3)
  })

  it('页面实例尚未就绪时安全返回', () => {
    jest.spyOn(Taro, 'getCurrentInstance').mockReturnValue(
      { page: undefined } as unknown as ReturnType<typeof Taro.getCurrentInstance>,
    )
    const getTabBar = jest.spyOn(Taro, 'getTabBar')

    expect(() => syncRootTabSelection(ROOT_TAB_INDEX.orders)).not.toThrow()
    expect(getTabBar).not.toHaveBeenCalled()
  })
})
