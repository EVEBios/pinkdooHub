import { useEffect, useRef, useState } from 'react'

export { tableCountdown } from './clock'

export function useAdminTableClock(serverNow?: string, visible = true): number {
  const [localNow, setLocalNow] = useState(Date.now)
  const anchor = useRef<{ server: number; local: number; source: string }>()
  if (serverNow && anchor.current?.source !== serverNow) {
    anchor.current = { server: Date.parse(serverNow), local: Date.now(), source: serverNow }
  }
  useEffect(() => {
    if (!visible) return
    setLocalNow(Date.now())
    const timer = setInterval(() => setLocalNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [visible])
  return anchor.current ? anchor.current.server + Math.max(0, localNow - anchor.current.local) : localNow
}
