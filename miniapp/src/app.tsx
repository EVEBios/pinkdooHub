import { type PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'

import { AuthProvider, type AuthStatus, useAuth } from '@/auth'
import type { UserProfile } from '@/api/endpoints/auth'
import { CartProvider } from '@/features/order'

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
  return shouldMountCustomerCart(auth.status, auth.user)
    ? <CartProvider>{children}</CartProvider>
    : children
}

export function shouldMountCustomerCart(status: AuthStatus, user?: UserProfile): boolean {
  return status === 'guest' || (status === 'authenticated' && user?.role === 'user')
}

export default App
