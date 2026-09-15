import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ADMIN_WORKBENCH_PATH } from '@/auth'

import './admin_workbench_redirect.scss'

export function AdminWorkbenchRedirect() {
  const navigatingRef = useRef(false)
  const [navigationError, setNavigationError] = useState('')

  const openWorkbench = useCallback(async (): Promise<void> => {
    if (navigatingRef.current) return
    navigatingRef.current = true
    setNavigationError('')
    try {
      await Taro.reLaunch({ url: ADMIN_WORKBENCH_PATH })
    } catch {
      navigatingRef.current = false
      setNavigationError('店铺工作台暂时无法打开，请重试。')
    }
  }, [])

  useEffect(() => {
    void openWorkbench()
  }, [openWorkbench])

  return (
    <View className='admin-workbench-redirect'>
      <Text className='admin-workbench-redirect__title'>正在进入店铺工作台…</Text>
      <Text className='admin-workbench-redirect__description'>工作人员操作与顾客商城相互独立</Text>
      {navigationError && (
        <>
          <View ariaRole='alert' className='admin-workbench-redirect__error'>
            <Text>{navigationError}</Text>
          </View>
          <Button className='admin-workbench-redirect__action' onClick={() => void openWorkbench()}>
            重新进入
          </Button>
        </>
      )}
    </View>
  )
}
