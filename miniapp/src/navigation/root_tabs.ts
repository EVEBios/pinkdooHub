import { attentionStore } from '@/features/attention/runtime'
import { syncNativeReservationBadge } from '@/features/attention/tab_badge'
import Taro, { useDidShow } from '@tarojs/taro'

export const ROOT_TAB_INDEX = {
  mall: 0,
  reservations: 1,
  cart: 2,
  member: 3,
} as const

export type RootTabIndex = typeof ROOT_TAB_INDEX[keyof typeof ROOT_TAB_INDEX]

export interface RootTabDefinition {
  index: RootTabIndex
  text: string
  pagePath: string
  url: string
}

export const ROOT_TABS = [
  {
    index: ROOT_TAB_INDEX.mall,
    text: '商城',
    pagePath: 'pages/index/index',
    url: '/pages/index/index',
  },
  {
    index: ROOT_TAB_INDEX.reservations,
    text: '预约',
    pagePath: 'pages/reservations/index',
    url: '/pages/reservations/index',
  },
  {
    index: ROOT_TAB_INDEX.cart,
    text: '购物车',
    pagePath: 'pages/cart/index',
    url: '/pages/cart/index',
  },
  {
    index: ROOT_TAB_INDEX.member,
    text: '会员中心',
    pagePath: 'pages/member/index',
    url: '/pages/member/index',
  },
] as const satisfies readonly RootTabDefinition[]

export type RootTabUrl = typeof ROOT_TABS[number]['url']

const ROOT_TAB_URLS: ReadonlySet<string> = new Set(ROOT_TABS.map((tab) => tab.url))

export function isRootTabUrl(value: string): value is RootTabUrl {
  return ROOT_TAB_URLS.has(value)
}

export interface RootTabBarHandle {
  setSelected(index: RootTabIndex): void
}

/**
 * 微信为每个 tab 页单独创建自定义 TabBar 实例，页面显示时必须同步当前项。
 */
export function syncRootTabSelection(index: RootTabIndex): void {
  const page = Taro.getCurrentInstance().page
  if (!page) return

  Taro.getTabBar<RootTabBarHandle>(page)?.setSelected(index)
}

export function useRootTabSelection(index: RootTabIndex): void {
  useDidShow(() => {
    syncNativeReservationBadge()
    if (attentionStore.state.identity?.endsWith(':user')) void attentionStore.refresh(false)
    if (process.env.TARO_ENV !== 'weapp') return
    syncRootTabSelection(index)
  })
}
