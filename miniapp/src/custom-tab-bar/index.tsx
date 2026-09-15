import { Component } from 'react'
import { Image, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { ROOT_TABS, type RootTabIndex } from '@/navigation/root_tabs'

import './index.scss'

interface CustomTabItem {
  index: RootTabIndex
  text: string
  url: string
  icon: string
  selectedIcon: string
}

interface CustomTabBarState {
  selected: RootTabIndex | null
}

const CUSTOM_TAB_ICONS = [
  ['/assets/tab-bar/mall-outline.png', '/assets/tab-bar/mall-solid-white.png'],
  ['/assets/tab-bar/reservations-outline.png', '/assets/tab-bar/reservations-solid-white.png'],
  ['/assets/tab-bar/orders-outline.png', '/assets/tab-bar/orders-solid-white.png'],
  ['/assets/tab-bar/member-outline.png', '/assets/tab-bar/member-solid-white.png'],
] as const

const CUSTOM_TAB_ITEMS: readonly CustomTabItem[] = ROOT_TABS.map((tab, index) => {
  return {
    index: tab.index,
    text: tab.text,
    url: tab.url,
    icon: CUSTOM_TAB_ICONS[index][0],
    selectedIcon: CUSTOM_TAB_ICONS[index][1],
  }
})

export default class CustomTabBar extends Component<Record<never, never>, CustomTabBarState> {
  public state: CustomTabBarState = {
    selected: resolveCurrentTabIndex(),
  }

  public setSelected(selected: RootTabIndex): void {
    this.setState((current) => current.selected === selected ? null : { selected })
  }

  private switchTab(item: CustomTabItem): void {
    if (isCurrentTab(item.url)) {
      this.setSelected(item.index)
      return
    }

    // 微信会为每个根页缓存独立实例；只让目标页生命周期提交选中态。
    void Promise.resolve(Taro.switchTab({ url: item.url })).catch(() => undefined)
  }

  public render(): JSX.Element {
    return (
      <View className='root-tab-bar' ariaRole='tablist' ariaLabel='主导航'>
        <View className='root-tab-bar__dock'>
          <View className='root-tab-bar__surface'>
            {CUSTOM_TAB_ITEMS.map((item) => {
              const selected = item.index === this.state.selected
              return (
                <View
                  key={item.url}
                  className={`root-tab-bar__item${selected ? ' root-tab-bar__item--selected' : ''}`}
                  ariaRole='tab'
                  ariaLabel={selected ? `${item.text}，当前页面` : item.text}
                  onClick={() => this.switchTab(item)}
                >
                  <View
                    className={`root-tab-bar__icon-seat${selected ? ' root-tab-bar__icon-seat--selected' : ''}`}
                  >
                    <Image
                      className={`root-tab-bar__icon${selected ? ' root-tab-bar__icon--selected' : ''}`}
                      mode='aspectFit'
                      src={selected ? item.selectedIcon : item.icon}
                    />
                  </View>
                  <View
                    className={`root-tab-bar__label${selected ? ' root-tab-bar__label--selected' : ''}`}
                  >
                    {item.text}
                  </View>
                </View>
              )
            })}
          </View>
        </View>
      </View>
    )
  }
}

function isCurrentTab(url: string): boolean {
  const pages = Taro.getCurrentPages()
  const route = pages[pages.length - 1]?.route
  return typeof route === 'string' && `/${route.replace(/^\/+/, '')}` === url
}

function resolveCurrentTabIndex(): RootTabIndex | null {
  const current = ROOT_TABS.find((tab) => isCurrentTab(tab.url))
  return current?.index ?? null
}
