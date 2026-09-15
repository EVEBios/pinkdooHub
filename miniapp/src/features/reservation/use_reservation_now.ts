import { useDidHide, useDidShow } from '@tarojs/taro'
import { useEffect, useState } from 'react'

/** 仅更新展示时间；能否审核/取消仍由服务端在操作时复验。 */
export function useReservationNow(): number {
  const [now, setNow] = useState(Date.now)
  const [visible, setVisible] = useState(true)
  useDidShow(() => { setNow(Date.now()); setVisible(true) })
  useDidHide(() => setVisible(false))
  useEffect(() => {
    if (!visible) return
    const timer = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [visible])
  return now
}
