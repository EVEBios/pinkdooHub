import Taro from '@tarojs/taro'
import { attentionStore, type AttentionState } from './runtime'

/** 原生底栏与页面缓存无关；身份清空时同步移除旧账号数字。 */
export function syncNativeReservationBadge(state: AttentionState = attentionStore.state): void {
  if (process.env.TARO_ENV === 'weapp') return
  const memberCount = state.identity?.endsWith(':user') ? (state.summary?.order_total ?? 0) + (state.summary?.table_total ?? 0) + (state.summary?.wallet_unread ?? 0) : 0
  syncBadge(3, memberCount)
  const count = state.identity?.endsWith(':user') ? state.summary?.reservation_unread ?? 0 : 0
  syncBadge(1, count)
}

function syncBadge(index: number, count: number): void {
  if (count && typeof Taro.setTabBarBadge === 'function') {
    void Taro.setTabBarBadge({ index, text: count > 99 ? '99+' : String(count) }).catch(() => undefined)
  } else if (typeof Taro.removeTabBarBadge === 'function') {
    void Taro.removeTabBarBadge({ index }).catch(() => undefined)
  }
}
