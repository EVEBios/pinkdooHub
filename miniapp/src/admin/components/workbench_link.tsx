import { Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useRef, useState } from 'react'

import { ADMIN_WORKBENCH_PATH } from '@/auth'

import './workbench_link.scss'

export function AdminWorkbenchLink() {
  const openingRef = useRef(false)
  const [opening, setOpening] = useState(false)

  async function openWorkbench(): Promise<void> {
    if (openingRef.current) return
    openingRef.current = true
    setOpening(true)
    try {
      await Taro.reLaunch({ url: ADMIN_WORKBENCH_PATH })
    } catch {
      await Taro.showToast({ title: '工作台暂时无法打开', icon: 'none' })
    } finally {
      openingRef.current = false
      setOpening(false)
    }
  }

  return (
    <Button
      ariaLabel='返回店铺工作台'
      className='admin-workbench-link'
      disabled={opening}
      onClick={() => void openWorkbench()}
    >
      {opening ? '正在返回…' : '店铺工作台'}
    </Button>
  )
}
