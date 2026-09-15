import { useDidHide, useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'
import { isAdminRole, useAuth } from '@/auth'
import { attentionStore } from './runtime'

export function usePageVisibility() {
  const [visible, setVisible] = useState(true)
  const visibleRef = useRef(true)
  useDidHide(() => { visibleRef.current = false; setVisible(false) })
  useDidShow(() => { visibleRef.current = true; setVisible(true) })
  useEffect(() => () => { visibleRef.current = false }, [])
  return { visible, visibleRef }
}

export function useAttentionSummary() {
  const auth = useAuth()
  const admin = isAdminRole(auth.user?.role)
  const identity = auth.status === 'authenticated' && auth.user ? `${auth.user.id}:${auth.user.role}` : undefined
  const [state, setState] = useState(attentionStore.state)
  const { visible } = usePageVisibility()
  useEffect(() => attentionStore.subscribe(() => setState(attentionStore.state)), [])
  useEffect(() => { attentionStore.setIdentity(identity); setState(attentionStore.state) }, [identity])
  const refresh = useCallback(() => {
    if (identity && attentionStore.state.identity === identity) void attentionStore.refresh(admin)
  }, [admin, identity])
  useEffect(() => {
    if (!identity || !visible) return
    refresh()
    const timer = setInterval(refresh, state.error ? 60_000 : admin ? 10_000 : 30_000)
    return () => clearInterval(timer)
  }, [admin, identity, refresh, state.error, visible])
  const current = state.identity === identity ? state : { identity }
  return { ...current, refresh, admin }
}
