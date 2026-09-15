import { Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'
import { formatShanghaiUtc } from '@/features/reservation'
import { tableCountdown } from '@/features/table_session/clock'
import type { SessionSnapshot } from './use_history_session'

export function SessionCountdowns({ snapshot, visible }: {
  readonly snapshot: SessionSnapshot
  readonly visible: boolean
}) {
  const { session, receivedAt } = snapshot
  const [localNow, setLocalNow] = useState(Date.now)
  const now = Date.parse(session.server_now) + Math.max(0, localNow - receivedAt)
  const closed = session.status.value === 'closed'
  const pending = session.status.value === 'awaiting_payment'

  useEffect(() => {
    if (!visible || closed) return
    setLocalNow(Date.now())
    const tick = setInterval(() => setLocalNow(Date.now()), 1_000)
    return () => clearInterval(tick)
  }, [snapshot, visible, closed])

  return <View className='table-history-countdowns'>
    {pending && <View className='table-history-countdowns__group'>
      <Text className='table-history-countdowns__label'>付款剩余时间</Text>
      <Text className='table-history-countdowns__value'>{tableCountdown(session.payment_deadline_at, now)}</Text>
      {now >= Date.parse(session.payment_deadline_at) && <Text className='table-history-countdowns__hint'>正在确认付款状态，请勿重复付款</Text>}
      <Text className='table-history-countdowns__hint'>付款截止：{formatShanghaiUtc(session.payment_deadline_at)}</Text>
    </View>}
    {session.timers.map((timer) => {
      const ended = closed || timer.phase.value === 'ended'
      const grace = timer.phase.value === 'grace'
      const deadline = grace ? timer.grace_ends_at : timer.service_ends_at
      return <View className='table-history-countdowns__group' key={timer.id}>
        <Text className='table-history-countdowns__label'>{timer.duration_minutes} 分钟体验 · {ended ? '已结束' : grace ? '缓冲剩余时间' : '体验剩余时间'}</Text>
        {!ended && <Text className='table-history-countdowns__value'>{tableCountdown(deadline, now)}</Text>}
        {!ended && now >= Date.parse(deadline) && <Text className='table-history-countdowns__hint'>{grace ? '正在确认结束状态' : '正在确认缓冲时间'}</Text>}
        {timer.experience_items.map((item) => <Text className='table-history-countdowns__hint' key={item.order_item_id}>{item.product_name} × {item.quantity}</Text>)}
        <Text className='table-history-countdowns__hint'>体验结束：{formatShanghaiUtc(timer.service_ends_at)}</Text>
        <Text className='table-history-countdowns__hint'>缓冲截止：{formatShanghaiUtc(timer.grace_ends_at)}</Text>
      </View>
    })}
  </View>
}
