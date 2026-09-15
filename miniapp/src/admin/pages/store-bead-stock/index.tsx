import { Button, Input, Picker, Text, Textarea, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import type { StockBatch, StockBatchSummary, StockEntry, StockPage } from '@/api/endpoints/store_bead_stock'
import { formatShanghaiUtc } from '@/features/reservation'
import { COLOR_GROUPS, MAX_PACKS, REASONS, STOCK_FILTERS, changes, colorLabel, matchesStock, parsePacks, summarize, type StockFilter } from '@/admin/features/store-bead-stock/model'
import { getStoreStockApi, STORE_STOCK_PATH } from '@/admin/features/store-bead-stock/runtime'
import { useStoreStock } from '@/admin/features/store-bead-stock/use_store_stock'
import './index.scss'

export default function StoreBeadStockPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') return <View className='bead-stock'><Text>正在确认管理员身份…</Text></View>
  if (auth.status === 'error') return <View className='bead-stock'><Text>登录状态暂不可用</Text><Button onClick={auth.retryInitialization}>重新检查</Button></View>
  if (auth.status !== 'authenticated') return <View className='bead-stock'><Text>登录后管理门店用豆库存</Text><Button onClick={() => void Taro.navigateTo({ url: buildLoginUrl(STORE_STOCK_PATH) })}>去登录</Button></View>
  if (!isAdminRole(auth.user?.role)) return <View className='bead-stock'><Text>无管理权限</Text></View>
  return <StoreStockWorkspace key={`${auth.user!.id}:${auth.user!.role}`} />
}

export function StoreStockWorkspace() {
  const stock = useStoreStock()
  const [filter, setFilter] = useState<StockFilter>('all')
  const [group, setGroup] = useState('全部')
  const [history, setHistory] = useState(false)
  const [batch, setBatch] = useState<StockBatch>()
  const editing = stock.mode === 'edit'
  const reviewing = ['confirm', 'saving', 'unknown', 'conflict'].includes(stock.mode)
  const dirty = Object.keys(stock.draft).length > 0
  const change = changes(stock.rows, stock.draft)
  const entries: StockEntry[] = change.items.map(item => {
    const row = stock.rows.find(r => r.bead_color_id === item.bead_color_id)!
    return { bead_color_id: row.bead_color_id, slot_no: row.slot_no, color_code: row.color_code, color_name: row.color_name, before_packs: row.packs, after_packs: item.packs, revision: row.revision + 1 }
  })
  const visible = stock.rows.filter(row => matchesStock(row, filter, group))

  useEffect(() => {
    if (process.env.TARO_ENV !== 'weapp') return
    if (dirty || reviewing) void Taro.enableAlertBeforeUnload({ message: '库存调整尚未完成，离开将丢失当前草稿。', fail: () => undefined })
    else void Taro.disableAlertBeforeUnload({ fail: () => undefined })
    return () => { void Taro.disableAlertBeforeUnload({ fail: () => undefined }) }
  }, [dirty, reviewing])
  useEffect(() => {
    if (process.env.TARO_ENV !== 'h5' || (!dirty && !reviewing)) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty, reviewing])

  async function cancel() {
    if (dirty) {
      const response = await Taro.showModal({ title: '放弃本次调整？', content: '尚未保存的库存修改会被清除。', cancelText: '继续修改', confirmText: '放弃修改' })
      if (!response.confirm) return
    }
    stock.cancel()
  }
  if (history) return <StockHistory onBack={() => setHistory(false)} />
  if (batch) return <View className='bead-stock bead-stock--review'><BatchDetail batch={batch} /><View className='bead-stock__footer'><Button className='bead-stock__primary' onClick={() => setBatch(undefined)}>返回库存</Button></View></View>

  return <View className={`bead-stock${editing ? ' bead-stock--editing' : reviewing ? ' bead-stock--review' : ''}`}>
    <View className='bead-stock__header'>
      <View className='bead-stock__header-copy'><Text className='bead-stock__title'>{reviewing ? '确认库存调整' : editing ? '调整库存' : '用豆库存'}</Text><Text className='bead-stock__subtitle'>{reviewing ? '核对全部变更后，统一保存' : '仅计未拆封整包 · 开包即减 1 包'}</Text></View>
      {!reviewing && <Button className='bead-stock__header-action' disabled={stock.loading || !stock.loaded ? true : undefined} onClick={() => editing ? void cancel() : void stock.begin()}>{editing ? '取消调整' : '调整库存'}</Button>}
    </View>
    {stock.error && <View className='bead-stock__message' ariaRole='alert'><Text>{stock.error}</Text>{stock.mode === 'browse' && <Button className='bead-stock__text-action' onClick={() => void stock.refresh()}>刷新库存</Button>}</View>}
    {stock.success && stock.mode === 'browse' && <View className='bead-stock__message'><Text>{stock.success}</Text>{stock.result && <Button className='bead-stock__text-action' onClick={() => setBatch(stock.result)}>查看本次记录</Button>}</View>}
    {reviewing ? <>
      <ChangeList entries={entries} />
      <AdjustmentReason reason={stock.reason} note={stock.note} />
      <Text className='bead-stock__save-hint'>确认后统一更新库存</Text>
      <View className='bead-stock__footer'>
        {stock.mode === 'conflict' ? <Button className='bead-stock__primary' disabled={stock.loading ? true : undefined} onClick={() => void stock.rebase()}>核对最新库存</Button> : stock.mode === 'unknown' ? <Button className='bead-stock__primary' onClick={() => void stock.submit(true)}>核查本次结果</Button> : <>
          <Button className='bead-stock__secondary' disabled={stock.mode === 'saving' ? true : undefined} onClick={stock.backToEdit}>返回修改</Button>
          <Button className='bead-stock__primary' loading={stock.mode === 'saving'} disabled={stock.mode === 'saving' ? true : undefined} onClick={() => void stock.submit()}>确认保存</Button>
        </>}
      </View>
    </> : <>
      <View className='bead-stock__filters'>
        <Text className='bead-stock__filter-label'>库存状态</Text>
        <View className='bead-stock__states'>{STOCK_FILTERS.map(option => <Button key={option.value} className={`bead-stock__filter${filter === option.value ? ' bead-stock__filter--active' : ''}`} ariaLabel={`${option.label}${filter === option.value ? '，已选中' : ''}`} onClick={() => setFilter(option.value)}>{option.label}</Button>)}</View>
        <Text className='bead-stock__filter-label'>颜色分组</Text>
        <View className='bead-stock__groups'>{COLOR_GROUPS.map(value => <Button key={value} className={`bead-stock__filter${group === value ? ' bead-stock__filter--active' : ''}`} ariaLabel={`${value}${group === value ? '，已选中' : ''}`} onClick={() => setGroup(value)}>{value}</Button>)}</View>
      </View>
      {!editing && <View className='bead-stock__meta'><Text>{stock.loaded ? `${group === '全部' ? '当前' : `${group} 组 ·`} ${visible.length} 色 · 共 ${stock.rows.length} 色` : stock.loading ? '正在读取库存…' : '库存暂不可用'}</Text><Button className='bead-stock__text-action' onClick={() => setHistory(true)}>调整记录</Button></View>}
      {stock.loading && <Text className='bead-stock__loading'>正在刷新…</Text>}
      {stock.loaded && !visible.length && <View className='bead-stock__empty'><Text>没有符合条件的颜色</Text><Button className='bead-stock__text-action' onClick={() => { setFilter('all'); setGroup('全部') }}>查看全部颜色</Button></View>}
      {editing && <View className='bead-stock__editor-reason'>
          <Picker mode='selector' range={REASONS.map(r => r.label)} value={REASONS.findIndex(r => r.value === stock.reason)} onChange={event => stock.setReason(REASONS[Number(event.detail.value)].value)}><View className='bead-stock__picker'><Text className='bead-stock__reason-label'>调整原因</Text><Text className='bead-stock__reason-value'>{REASONS.find(r => r.value === stock.reason)?.label}</Text><Text className='bead-stock__picker-action'>更改</Text></View></Picker>
          <View className='bead-stock__note-row'><Text className='bead-stock__reason-label'>备注（选填）</Text><Textarea className='bead-stock__note' ariaLabel='调整备注（选填）' placeholder='填写备注' maxlength={500} autoHeight value={stock.note} onInput={event => stock.setNote(event.detail.value)} /></View>
        </View>}
      {!!visible.length && <View className='bead-stock__ledger-head'>{[0, 1].map(column => <View key={column} className='bead-stock__ledger-column'><Text>色号</Text><Text>{editing ? '调整后' : '库存'}</Text></View>)}</View>}
      <View className='bead-stock__grid'>{visible.map((row, index) => {
        const raw = stock.draft[row.bead_color_id] ?? (row.packs === null ? '' : String(row.packs))
        const value = parsePacks(raw)
        const changed = stock.draft[row.bead_color_id] !== undefined && value !== row.packs
        return <View key={row.bead_color_id} className={`bead-stock__card${Math.floor(index / 2) % 2 ? ' bead-stock__card--stripe' : ''}${editing ? ' bead-stock__card--editing' : ''}`}>
          <View className='bead-stock__color-heading'><Text className='bead-stock__color'>{colorLabel(row)}</Text>{editing && changed && <Text className='bead-stock__changed'>已修改</Text>}</View>
          {row.color_name && row.color_name !== row.color_code && <Text className='bead-stock__name'>{row.color_name}</Text>}
          {editing ? <>
            <View className='bead-stock__stepper'>
              <Button className='bead-stock__step' ariaLabel={`${colorLabel(row)} 减少一包`} disabled={value === undefined || value === 0 || stock.loading ? true : undefined} onClick={() => value !== undefined && stock.update(row.bead_color_id, String(value - 1))}>−</Button>
              <Input className='bead-stock__input' ariaLabel={`${colorLabel(row)} 库存包数`} type='number' maxlength={6} placeholder='未盘点' value={raw} disabled={stock.loading} onInput={event => stock.update(row.bead_color_id, event.detail.value)} />
              <Button className='bead-stock__step' ariaLabel={`${colorLabel(row)} 增加一包`} disabled={(value !== undefined && value >= MAX_PACKS) || stock.loading ? true : undefined} onClick={() => stock.update(row.bead_color_id, String((value ?? row.packs ?? 0) + 1))}>+</Button>
            </View>
            <Text className='bead-stock__draft'>{changed ? `${row.packs === null ? '未盘点' : `原 ${row.packs} 包`} → ${value === undefined ? '待填写' : `${value} 包`}` : row.packs === null ? '输入 0 可确认无库存' : `当前 ${row.packs} 包`}</Text>
          </> : <Text className='bead-stock__quantity'>{row.packs === null ? '未盘点' : <>{row.packs}<Text className='bead-stock__unit'> 包</Text></>}</Text>}
        </View>
      })}</View>
      {stock.loaded && stock.rows.some(r => r.packs === null) && <Text className='bead-stock__uninitialized'>未盘点 {stock.rows.filter(r => r.packs === null).length} 色，仅在库存状态“全部”中显示</Text>}
      {editing && <>

        <View className='bead-stock__footer'><Text className='bead-stock__footer-count'>已修改 {change.items.length} 色</Text><Button className='bead-stock__primary' disabled={(!change.items.length && !change.invalid.length) || stock.loading ? true : undefined} onClick={stock.review}>确认调整</Button></View>
      </>}
    </>}
  </View>
}

function AdjustmentReason({ reason, note }: { readonly reason: StockBatch['reason']; readonly note?: string | null }) {
  return <View className='bead-stock__reason'><View className='bead-stock__reason-row'><Text className='bead-stock__reason-label'>调整原因</Text><Text className='bead-stock__reason-value'>{REASONS.find(r => r.value === reason)?.label}</Text></View>{note && <View className='bead-stock__reason-row'><Text className='bead-stock__reason-label'>备注</Text><Text className='bead-stock__reason-value'>{note}</Text></View>}</View>
}

function ChangeList({ entries }: { readonly entries: readonly StockEntry[] }) {
  const totals = summarize(entries)
  return <>
    <View className='bead-stock__totals'><Text className='bead-stock__section-title'>本次修改 {entries.length} 色</Text><Text>增加 {totals.added} 包 · 减少 {totals.removed} 包</Text>{totals.initialColors > 0 && <Text>首次盘点 {totals.initialColors} 色，共 {totals.initialPacks} 包</Text>}</View>
    <View className='bead-stock__changes'>{entries.map(item => <View key={item.bead_color_id} className='bead-stock__change'><View><Text className='bead-stock__color'>{colorLabel(item)}</Text><Text className='bead-stock__change-note'>{item.before_packs === null ? '首次盘点' : `${item.after_packs >= item.before_packs ? '增加' : '减少'} ${Math.abs(item.after_packs - item.before_packs)} 包`}</Text></View><Text className='bead-stock__change-value'>{item.before_packs === null ? '未盘点' : `${item.before_packs} 包`} → {item.after_packs} 包</Text></View>)}</View>
  </>
}
function BatchDetail({ batch }: { readonly batch: StockBatch }) {
  return <><View className='bead-stock__header'><View><Text className='bead-stock__title'>库存调整记录</Text><Text className='bead-stock__subtitle'>{formatShanghaiUtc(batch.created_at)} · {batch.operator_name}</Text></View></View><ChangeList entries={batch.items} /><AdjustmentReason reason={batch.reason} note={batch.note} /></>
}
function StockHistory({ onBack }: { readonly onBack: () => void }) {
  const [page, setPage] = useState(1), [retry, setRetry] = useState(0)
  const [data, setData] = useState<StockPage<StockBatchSummary>>()
  const [batch, setBatch] = useState<StockBatch>()
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [failedDetailId, setFailedDetailId] = useState<number>()
  useEffect(() => {
    let cancelled = false
    setBusy(true); setError('')
    void getStoreStockApi().history(page).then(value => { if (!cancelled) setData(value) }).catch(() => { if (!cancelled) setError('调整记录读取失败，请重试') }).finally(() => { if (!cancelled) setBusy(false) })
    return () => { cancelled = true }
  }, [page, retry])
  async function open(id: number) {
    if (busy) return
    setBusy(true); setError('')
    try { setBatch(await getStoreStockApi().detail(id)); setFailedDetailId(undefined) } catch { setFailedDetailId(id); setError('记录详情读取失败，请重试') } finally { setBusy(false) }
  }
  return <View className='bead-stock bead-stock--review'>
    {batch ? <BatchDetail batch={batch} /> : <>
      <View className='bead-stock__header'><Text className='bead-stock__title'>调整记录</Text></View>
      {data?.items.map(item => <Button key={item.id} className='bead-stock__history-item' disabled={busy ? true : undefined} onClick={() => void open(item.id)}><Text className='bead-stock__section-title'>{REASONS.find(r => r.value === item.reason)?.label} · {item.changed_colors} 色</Text><Text>{formatShanghaiUtc(item.created_at)} · {item.operator_name}</Text></Button>)}
      {!busy && data?.total === 0 && <Text>还没有调整记录，首次盘点后会显示在这里。</Text>}
      {data && data.pages > 1 && <View className='bead-stock__pagination'><Button disabled={page <= 1 || busy ? true : undefined} onClick={() => setPage(p => p - 1)}>上一页</Button><Text>{page} / {data.pages}</Text><Button disabled={page >= data.pages || busy ? true : undefined} onClick={() => setPage(p => p + 1)}>下一页</Button></View>}
    </>}
    {busy && <Text>正在读取…</Text>}
    {error && <View className='bead-stock__message'><Text>{error}</Text><Button disabled={busy ? true : undefined} onClick={() => failedDetailId !== undefined ? void open(failedDetailId) : setRetry(n => n + 1)}>重试</Button></View>}
    <View className='bead-stock__footer'><Button className='bead-stock__primary' onClick={() => batch ? setBatch(undefined) : onBack()}>{batch ? '返回记录' : '返回库存'}</Button></View>
  </View>
}
