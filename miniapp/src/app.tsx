import { type PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'

import { AuthProvider } from '@/auth'

import './app.scss'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    // 应用级生命周期只记录启动；会话恢复由 AuthProvider 的 Effect 管理。
  })

  return <AuthProvider>{children}</AuthProvider>
}

export default App
