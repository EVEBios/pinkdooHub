import { type PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'

import { AuthProvider } from '@/auth'
import { CartProvider } from '@/features/order'

import './app.scss'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // 应用级生命周期只记录启动；会话恢复由 AuthProvider 的 Effect 管理。
  })

  return (
    <CartProvider>
      <AuthProvider>{children}</AuthProvider>
    </CartProvider>
  )
}

export default App
