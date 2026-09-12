import { useDidHide, useDidShow } from '@tarojs/taro'
import { useRef } from 'react'

/**
 * 页面从隐藏状态再次展示时执行最新的刷新函数。
 *
 * 首次展示前没有发生 hide，因此不会和数据 hook 的首次加载产生重复请求；
 * Tab 被平台保活时则通过 hide -> show 触发权威重读。
 */
export function useRefreshAfterPageReturn(refresh: () => void): void {
  const refreshRef = useRef(refresh)
  const hiddenRef = useRef(false)
  refreshRef.current = refresh

  useDidHide(() => {
    hiddenRef.current = true
  })

  useDidShow(() => {
    if (!hiddenRef.current) return
    hiddenRef.current = false
    refreshRef.current()
  })
}
