import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import type { FollowupKind, FollowupPage, FollowupRecord, FollowupSnapshot, FollowupWrite } from '@/api/endpoints/reservation_followups'
import { BusinessError } from '@/api/errors'
import { usePageVisibility } from '@/features/attention/hooks'
import { formatShanghaiUtc } from '@/features/reservation'
import { getFollowupApi } from './runtime'
import './style.scss'

function requestKey(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const n = Math.floor(Math.random() * 16)
    return (c === 'x' ? n : (n & 3) | 8).toString(16)
  })
}

export function FollowupPanel({ reservationId, kind, phone }: { readonly reservationId: number; readonly kind: FollowupKind; readonly phone?: string | null }) {
  const { visible, visibleRef } = usePageVisibility()
  const [snapshot, setSnapshot] = useState<FollowupSnapshot>()
  const [history, setHistory] = useState<FollowupPage<FollowupRecord>>()
  const [historyPage, setHistoryPage] = useState(1)
  const [error, setError] = useState('')
  const [feedbackTone, setFeedbackTone] = useState<'success' | 'error' | 'warning'>('warning')
  const [loadError, setLoadError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [outcome, setOutcome] = useState<FollowupWrite['outcome']>(kind === 'contact' ? 'contacted' : 'resolved')
  const [note, setNote] = useState('')
  const [draftRevision, setDraftRevision] = useState<number>()
  const [saving, setSaving] = useState(false)
  const [unknown, setUnknown] = useState(false)
  const busy = useRef(false)
  const intent = useRef<FollowupWrite>()
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!visible) return
    let cancelled = false
    let fetching = false
    async function load() {
      if (fetching) return
      fetching = true
      try {
        const [next, records] = await Promise.all([getFollowupApi().detail(reservationId, kind), getFollowupApi().history(reservationId, kind, historyPage)])
        if (!cancelled) { setSnapshot(next); setHistory(records); setLoadError('') }
      } catch { if (!cancelled) setLoadError('跟进记录读取失败，请重新加载后操作。') }
      finally { fetching = false }
    }
    void load()
    const timer = setInterval(() => void load(), 10_000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [reservationId, kind, visible, historyPage, attempt])
  const stale = draftRevision !== undefined && snapshot?.revision !== draftRevision
  const canEdit = !!snapshot?.eligible && !snapshot.completed && !saving && !unknown && !loadError
  async function save() {
    if (busy.current || !visibleRef.current || (!unknown && (!canEdit || stale || !note.trim()))) return
    busy.current = true; setSaving(true); setError('')
    const payload = intent.current ?? { expected_revision: draftRevision ?? snapshot!.revision, request_key: requestKey(), outcome, note: note.trim() }
    intent.current = payload
    try {
      const result = await getFollowupApi().write(reservationId, kind, payload)
      if (!mounted.current) return
      intent.current = undefined; setUnknown(false); setSnapshot(result); setDraftRevision(undefined); setNote(''); setHistoryPage(1); setAttempt((v) => v + 1)
      setFeedbackTone('success'); setError(result.completed ? '跟进已完成，记录已保存。' : '联系记录已保存，此事项仍待跟进。')
    } catch (cause) {
      if (!mounted.current) return
      if (cause instanceof BusinessError) {
        intent.current = undefined; setUnknown(false); setFeedbackTone('error'); setError(cause.message); setAttempt((v) => v + 1)
      } else {
        setUnknown(true); setFeedbackTone('warning'); setError('保存结果尚未确认。请重试保存核对同一次操作，暂勿再次联系或填写新记录。')
      }
    } finally { busy.current = false; if (mounted.current) setSaving(false) }
  }
  const choices: { value: FollowupWrite['outcome']; label: string }[] = [
    ...(kind === 'contact' ? [{ value: 'contacted' as const, label: '已联系' }] : []),
    { value: 'retry', label: '待重试' }, { value: 'unreachable', label: '号码不可用' }, { value: 'resolved', label: '结束跟进' },
  ]
  return <View className='followup-panel'>
    <View className='followup-panel__heading'><Text className='followup-panel__title'>{kind === 'contact' ? '店休联系' : '过期预约跟进'}</Text><Text className='followup-panel__status'>{snapshot?.latest?.label ?? '待处理'}</Text></View>
    <Text className='followup-panel__hint'>{kind === 'contact' ? '请联系顾客告知店休。顾客已读不代表门店已完成联系。' : '请核实后续安排。记录跟进不会将预约改为已确认、已拒绝或已取消。'}</Text>
    {phone && <Button className='followup-panel__secondary' onClick={() => void Taro.makePhoneCall({ phoneNumber: phone }).catch(() => { setFeedbackTone('error'); setError('未能发起拨号，请根据上方联系方式手动联系。') })}>拨打顾客电话</Button>}
    {!snapshot && !loadError && <Text>正在读取跟进记录…</Text>}
    {loadError && <View><Text className='followup-panel__feedback followup-panel__feedback--error'>{loadError}</Text><Button className='followup-panel__secondary' onClick={() => setAttempt((v) => v + 1)}>重新加载</Button></View>}
    {snapshot && !snapshot.eligible && !snapshot.completed && <Text>此预约已不符合待跟进条件，请核对预约最新状态。</Text>}
    {snapshot?.eligible && !snapshot.completed && <>
      <Text className='followup-panel__label'>本次处理结果</Text>
      <View className='followup-panel__choices'>{choices.map((choice) => <Button key={choice.value} disabled={(!canEdit) || undefined} ariaLabel={`${choice.label}${outcome === choice.value ? '，已选中' : ''}`} className={`followup-panel__choice${outcome === choice.value ? ' followup-panel__choice--active' : ''}`} onClick={() => { setOutcome(choice.value); setDraftRevision((v) => v ?? snapshot.revision) }}>{choice.label}</Button>)}</View>
      <Text className='followup-panel__hint'>{outcome === 'contacted' ? '已实际联系并告知顾客后选择，保存后移出待处理。' : outcome === 'resolved' ? '保存后结束此事项。无法继续联系时，请写明原因和已采取的措施。' : '此结果会继续保留在待处理列表，请在说明中记录下一步安排。'}</Text>
      <Text className='followup-panel__label'>联系情况或处理说明（必填）</Text>
      <Textarea className='followup-panel__note' value={note} maxlength={500} disabled={!canEdit} ariaLabel='联系情况或处理说明，必填' placeholder='记录联系情况、顾客回复或后续安排' onInput={(event) => { if (canEdit) { setNote(event.detail.value); setDraftRevision((v) => v ?? snapshot.revision) } }} />
      {stale && <View><Text className='followup-panel__feedback'>其他管理员已更新记录，请核对下方最新记录后继续。</Text><Button className='followup-panel__secondary' disabled={(saving || unknown) || undefined} onClick={() => setDraftRevision(snapshot.revision)}>已核对最新记录</Button></View>}
      {!unknown && <Button className='followup-panel__primary' disabled={(!canEdit || stale || !note.trim()) || undefined} loading={saving} onClick={() => void save()}>保存处理记录</Button>}
    </>}
    {error && <Text className={`followup-panel__feedback followup-panel__feedback--${feedbackTone}`}>{error}</Text>}
    {unknown && <Button className='followup-panel__primary' disabled={(saving) || undefined} loading={saving} onClick={() => void save()}>重试保存</Button>}
    <Text className='followup-panel__label'>处理记录{history ? ` · ${history.total} 条` : ''}</Text>
    {history?.items.length === 0 && <Text className='followup-panel__hint'>尚无处理记录。查看页面不会完成跟进。</Text>}
    {history?.items.map((record) => <View key={record.id} className='followup-panel__record'><Text className='followup-panel__record-title'>{record.label}</Text><Text className='followup-panel__hint'>{formatShanghaiUtc(record.created_at)} · 管理员 #{record.operator_id}</Text><Text className='followup-panel__record-note'>{record.note}</Text></View>)}
    {history && history.pages > 1 && <View className='followup-panel__pagination'><Button className='followup-panel__secondary' disabled={(historyPage <= 1) || undefined} onClick={() => setHistoryPage((v) => v - 1)}>上一页</Button><Text>{historyPage} / {history.pages}</Text><Button className='followup-panel__secondary' disabled={(historyPage >= history.pages) || undefined} onClick={() => setHistoryPage((v) => v + 1)}>下一页</Button></View>}
  </View>
}
