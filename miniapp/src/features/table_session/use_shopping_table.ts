import { useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import { shoppingTableStore, type ShoppingTableState } from './shopping_table'

export function useShoppingTable(userId?: number) {
  const [state, setState] = useState<ShoppingTableState>({})
  const [loading, setLoading] = useState(true)
  const [loadedUserId, setLoadedUserId] = useState<number>()
  const [error, setError] = useState<string>()
  const generation = useRef(0)
  const refresh = useCallback(async () => {
    const current = ++generation.current
    if (!userId) { setState({}); setLoadedUserId(undefined); setError(undefined); setLoading(false); return }
    try {
      const loaded = await shoppingTableStore.load(userId)
      if (current !== generation.current) return
      setState(loaded)
      setError(undefined)
    } catch (cause) {
      if (current === generation.current) setError(cause instanceof Error ? cause.message : '本次桌台读取失败，请重试')
    } finally {
      if (current === generation.current) { setLoadedUserId(userId); setLoading(false) }
    }
  }, [userId])
  useEffect(() => {
    setLoading(true)
    setState({})
    void refresh()
    const unsubscribe = shoppingTableStore.subscribe(() => { void refresh() })
    return () => { generation.current += 1; unsubscribe() }
  }, [refresh])
  useDidShow(() => { void refresh() })
  const current = loadedUserId === userId ? state : {}
  return { ...current, loading: loading || loadedUserId !== userId, error: loadedUserId === userId ? error : undefined, refresh,
    expired: current.selection ? shoppingTableStore.expired(current.selection) : false }
}
