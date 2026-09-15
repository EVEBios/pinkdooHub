import { Button, Input, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'

import type { AdminTable, DirectTableDuration, TableSessionApi } from '@/api/endpoints/table_sessions'
import { createTableIntentKey } from '@/features/table_session/idempotency'
import { tableAdminError } from '@/features/table_session/admin_table_actions'
import { isWalletMutationUnknown } from '@/features/wallet'

export function DirectOpenForm({ table, source, onDone, onCancel }: {
  readonly table: AdminTable
  readonly source: TableSessionApi
  readonly onDone: () => void
  readonly onCancel: () => void
}) {
  const [options, setOptions] = useState<readonly DirectTableDuration[]>()
  const [selected, setSelected] = useState<DirectTableDuration>()
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [unknown, setUnknown] = useState(false)
  const intent = useRef<{ key: string; option: DirectTableDuration; note: string }>()
  const busy = useRef(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    void source.listDirectDurations().then((result) => {
      if (active) { setOptions(result.items); setError('') }
    }).catch((cause: unknown) => { if (active) setError(tableAdminError(cause)) })
    return () => { active = false }
  }, [attempt, source])

  async function start(): Promise<void> {
    if (busy.current || !selected) return
    busy.current = true
    setLoading(true)
    setError('')
    intent.current ??= { key: createTableIntentKey('direct'), option: selected, note }
    const original = intent.current
    try {
      await source.createDirectSession(table.id, original.option, original.note, original.key)
      intent.current = undefined
      onDone()
    } catch (cause) {
      const uncertain = isWalletMutationUnknown(cause instanceof Error ? cause : new Error('开台结果未知'))
      setUnknown(uncertain)
      if (!uncertain) intent.current = undefined
      setError(uncertain ? '开台结果可能未知。请重试原操作确认结果，不会重复开台或延长时间。' : tableAdminError(cause))
    } finally {
      busy.current = false
      setLoading(false)
    }
  }

  return <View className='direct-open-form'>
    <Text className='direct-open-form__title'>{table.table_no} · 直接开台</Text>
    <Text>选择已购买的体验时长，无需顾客登录。</Text>
    <View className='direct-open-form__options'>
      {options?.map((option) => <Button key={option.option_id} disabled={(loading || unknown) || undefined} className={selected?.option_id === option.option_id ? 'is-selected' : ''}
        onClick={() => setSelected(option)}
      >{option.duration_minutes} 分钟</Button>)}
    </View>
    {!options && !error && <Text>正在读取体验时长…</Text>}
    {options?.length === 0 && <Text>暂无可用时长，请先配置体验商品。</Text>}
    <Input className='direct-open-form__note' ariaLabel='开台备注（选填）' placeholder='备注（选填，如美团团购）' maxlength={200} value={note} disabled={(loading || unknown) || undefined}
      onInput={(event) => setNote(event.detail.value)}
    />
    {selected && <Text>体验 {selected.duration_minutes} 分钟 + 缓冲 10 分钟，确认后立即计时。</Text>}
    {error && <View ariaRole='alert'><Text>{error}</Text></View>}
    {error && !unknown && <Button onClick={() => { setOptions(undefined); setSelected(undefined); setAttempt((value) => value + 1) }}>重新读取时长</Button>}
    <Button className='direct-open-form__submit' disabled={(!selected || loading) || undefined} loading={loading} onClick={() => void start()}>{unknown ? '重试原操作并确认结果' : '确认开始计时'}</Button>
    <Button disabled={(loading || unknown) || undefined} onClick={onCancel}>取消</Button>
  </View>
}
