import { Button, Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'
import type { FollowupCounts } from '@/api/endpoints/reservation_followups'
import { AttentionBadge } from '@/features/attention'
import { usePageVisibility } from '@/features/attention/hooks'
import { FOLLOWUP_PATH, getFollowupApi } from './runtime'

export function FollowupEntry({ disabled, open }: { readonly disabled: boolean; readonly open: (action: { label: string; url: string }) => Promise<void> }) {
  const { visible } = usePageVisibility()
  const [counts, setCounts] = useState<FollowupCounts>()
  const [error, setError] = useState(false)
  useEffect(() => {
    if (!visible) return
    let cancelled = false
    let busy = false
    async function load() {
      if (busy) return
      busy = true
      try { const data = await getFollowupApi().counts(); if (!cancelled) { setCounts(data); setError(false) } }
      catch { if (!cancelled) setError(true) }
      finally { busy = false }
    }
    void load()
    const timer = setInterval(() => void load(), 10_000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [visible])
  const total = counts ? counts.contact_pending + counts.overdue_pending : 0
  const hint = error ? '跟进数量更新失败，点击进入重试' : counts ? `店休待联系 ${counts.contact_pending} · 过期待跟进 ${counts.overdue_pending}` : '正在读取跟进事项…'
  return <Button className='workbench-action' hoverClass='workbench-action--pressed' ariaLabel={`预约跟进，${total} 件待处理，${hint}`} onClick={() => { if (!disabled) void open({ label: '预约跟进', url: FOLLOWUP_PATH }) }}>
    <View className='workbench-action__copy'><View className='workbench-action__title-row'><Text className='workbench-action__label'>预约跟进</Text><AttentionBadge count={total} /></View><Text className='workbench-action__meta'>{hint}</Text></View><Text className='workbench-action__enter'>进入</Text>
  </Button>
}
