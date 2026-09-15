import { type PropsWithChildren, useEffect } from 'react'
import { useLaunch } from '@tarojs/taro'

import { AuthProvider, type AuthStatus, useAuth } from '@/auth'
import type { UserProfile } from '@/api/endpoints/auth'
import { CartProvider } from '@/features/order'

import { attentionStore } from '@/features/attention/runtime'
import { syncNativeReservationBadge } from '@/features/attention/tab_badge'

import './app.scss'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // 应用级生命周期只记录启动；会话恢复由 AuthProvider 的 Effect 管理。
  })

  return (
    <AuthProvider>
      <CustomerCartBoundary>{children}</CustomerCartBoundary>
    </AuthProvider>
  )
}

function CustomerCartBoundary({ children }: PropsWithChildren) {
  const auth = useAuth()
  const attentionIdentity = auth.status === 'authenticated' && auth.user ? `${auth.user.id}:${auth.user.role}` : undefined
  useEffect(() => attentionStore.subscribe(() => syncNativeReservationBadge()), [])
  useEffect(() => { attentionStore.setIdentity(attentionIdentity) }, [attentionIdentity])
  // 保持路由子树位置稳定，身份恢复时切换包装层会重挂载 H5 页面并丢失入场状态。
  return <CartProvider enabled={shouldMountCustomerCart(auth.status, auth.user)}>{children}</CartProvider>
}

export function shouldMountCustomerCart(status: AuthStatus, user?: UserProfile): boolean {
  return status === 'guest' || (status === 'authenticated' && user?.role === 'user')
}

export default App
