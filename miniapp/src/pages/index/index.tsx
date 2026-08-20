import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'

import { useAuth } from '@/auth'

import './index.scss'

export default function Index() {
  const { initializationError, logout, retryInitialization, status, user } = useAuth()
  const [logoutError, setLogoutError] = useState('')

  useEffect(() => {
    if (status === 'guest') {
      void Taro.reLaunch({ url: '/pages/login/index' })
    }
  }, [status])

  async function handleLogout(): Promise<void> {
    setLogoutError('')
    try {
      await logout()
    } catch {
      setLogoutError('服务端登出未确认，本机会话已清除')
    }
  }

  if (status === 'initializing') {
    return <View className='index'><Text>正在恢复登录状态…</Text></View>
  }

  if (status === 'error') {
    return (
      <View className='index'>
        <Text className='index__title'>暂时无法验证登录状态</Text>
        <Text className='index__subtitle'>{initializationError?.message}</Text>
        <Button className='index__action' onClick={retryInitialization}>重试</Button>
      </View>
    )
  }

  if (!user) {
    return <View className='index'><Text>正在前往登录页…</Text></View>
  }

  return (
    <View className='index'>
      <Text className='index__title'>pinkdooHub</Text>
      <Text className='index__subtitle'>你好，{user.nickname}（{user.role}）</Text>
      {logoutError && <Text className='index__error'>{logoutError}</Text>}
      <Button className='index__action' onClick={() => void handleLogout()}>退出登录</Button>
    </View>
  )
}
