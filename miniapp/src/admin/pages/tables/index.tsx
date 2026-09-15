import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useRef, useState } from 'react'

import type { AdminTable } from '@/api/endpoints/table_sessions'
import { ADMIN_WORKBENCH_PATH, buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import { buildAdminTableSessionUrl, getDefaultTableSessionApi } from '@/features/table_session'

import { confirmTablePayment, tableAdminError } from '@/features/table_session/admin_table_actions'
import { tableCountdown } from '@/features/table_session/use_admin_table_clock'
import { useAdminTableOverview } from '@/features/table_session/use_admin_table_overview'
import { tableNeedsAttention, tableTimeWarnings } from '@/features/table_session/admin_table_attention'
import { DirectOpenForm } from './direct_open_form'

import './index.scss'

export default function AdminTablesPage() {
  const auth = useAuth()
  if (auth.status === 'guest') return <AdminState title='登录后管理桌台'><Button onClick={() => void Taro.reLaunch({ url: buildLoginUrl(ADMIN_WORKBENCH_PATH) })}>去登录</Button></AdminState>
  if (auth.status === 'initializing') return <AdminState title='正在确认管理权限' />
  if (!auth.user || !isAdminRole(auth.user.role)) return <AdminState title='无桌台管理权限' />
  return <AdminTablesContent key={`${auth.user.id}:${auth.user.role}`} />
}

function AdminTablesContent() {
  const source = getDefaultTableSessionApi()
  const { data, error: readError, refresh: load, now, counts } = useAdminTableOverview()
  const [onlyAttention, setOnlyAttention] = useState(false)
  const [error, setError] = useState('')
  const [updating, setUpdating] = useState<number>()
  const [opening, setOpening] = useState<AdminTable>()
  const updatingRef = useRef(false)

  async function toggle(tableId: number, enabled: boolean): Promise<void> {
    if (updatingRef.current) return
    const confirmed = await Taro.showModal({ title: enabled ? '停用桌台' : '启用桌台', content: '当前会话不会被自动释放；如需释放请进入会话详情。' })
    if (!confirmed.confirm || updatingRef.current) return
    updatingRef.current = true
    setUpdating(tableId)
    try {
      await source.updateAdminTable(tableId, !enabled, '门店桌台状态调整')
      load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '桌台更新失败')
    } finally {
      updatingRef.current = false
      setUpdating(undefined)
    }
  }

  async function confirmPayment(table: AdminTable): Promise<void> {
    if (updatingRef.current || !table.current_session_no) return
    updatingRef.current = true
    setUpdating(table.id)
    try {
      await confirmTablePayment(source, table.current_session_no)
      load()
    } catch (cause) {
      setError(tableAdminError(cause))
    } finally {
      updatingRef.current = false
      setUpdating(undefined)
    }
  }

  return (
    <View className='admin-tables-page'>
      <View className='admin-tables-header'><Text>30 桌实时状态</Text><Text>{data ? new Date(data.server_now).toLocaleString() : '正在读取…'}</Text></View>
      {(error || readError) && <View className='admin-tables-alert' ariaRole='alert'><Text>{error || readError}</Text><Button onClick={() => { setError(''); load() }}>刷新状态</Button></View>}
      <View className='admin-tables-attention'>
        <Text className='admin-tables-attention__title'>{data ? `待收款 ${counts.payment} 桌 · 到时提醒 ${counts.time} 桌` : '正在读取桌台提醒…'}</Text>
        <Text>体验结束前 10 分钟提醒，缓冲期间继续显示。</Text>
        <View className='admin-tables-attention__filters'>
          <Button className={!onlyAttention ? 'is-selected' : ''} onClick={() => setOnlyAttention(false)}>全部桌台</Button>
          <Button className={onlyAttention ? 'is-selected' : ''} onClick={() => setOnlyAttention(true)}>需关注{data ? ` ${counts.total}` : ''}</Button>
        </View>
      </View>
      {onlyAttention && data && counts.total === 0 && <View className='admin-tables-empty'><Text>当前没有需要关注的桌台。</Text></View>}
      {opening && <DirectOpenForm key={opening.id} table={opening} source={source}
        onDone={() => { setOpening(undefined); load() }} onCancel={() => setOpening(undefined)}
      />}
      <View className='admin-tables-grid'>
        {data?.items.filter((table) => !onlyAttention || tableNeedsAttention(table, now)).map((table) => (
          <View className={`admin-table admin-table--${table.current_status?.value ?? table.state}${tableNeedsAttention(table, now) === 'time' ? ' admin-table--warning' : ''}`} key={table.id}>
            <View className='admin-table__heading'><Text>{table.table_no}</Text><Text>{tableStateLabel(table, now)}</Text></View>
            <TableRemaining table={table} now={now} />
            {tableTimeWarnings(table.current_status?.value, table.timers ?? [], now).map(({ timer, phase }) => <View className='admin-table__warning' key={timer.id}>
              <Text>{timer.duration_minutes} 分钟组 · {phase === 'soon' ? '即将到时' : '缓冲中'}</Text>
              <Text>{phase === 'soon' ? '体验' : '缓冲'}剩余 {tableCountdown(phase === 'soon' ? timer.service_ends_at : timer.grace_ends_at, now)}</Text>
            </View>)}
            {table.current_session_no && <Text className='admin-table__meta'>{table.current_source === 'direct' ? '直接开台' : '系统订单'}</Text>}
            {(table.timer_count ?? 0) > 1 && <Text className='admin-table__meta'>共 {table.timer_count} 组计时，显示最长一组</Text>}
            {!table.is_enabled && table.current_session_no && <Text className='admin-table__meta'>暂停新开台</Text>}
            {table.is_enabled && !table.current_session_no && <Button disabled={(updating !== undefined || !!opening) || undefined} onClick={() => {
              setOpening(table)
              void Taro.pageScrollTo({ scrollTop: 0, duration: 200 })
            }}
            >直接开台</Button>}
            {table.current_status?.value === 'awaiting_payment' && <Button className='admin-table__primary' disabled={(updating !== undefined || !!opening) || undefined}
              loading={updating === table.id} onClick={() => void confirmPayment(table)}
            >确认已收款并计时</Button>}
            {table.current_session_no && <Button onClick={() => void Taro.navigateTo({ url: buildAdminTableSessionUrl(table.current_session_no!) })}>查看当前会话</Button>}
            <Button disabled={(updating !== undefined || !!opening) || undefined} onClick={() => void toggle(table.id, table.is_enabled)}>{table.is_enabled ? '停用新开台' : '重新启用'}</Button>
          </View>
        ))}
      </View>
    </View>
  )
}

function AdminState({ children, title }: { readonly title: string; readonly children?: React.ReactNode }) {
  return <View className='admin-tables-page admin-tables-page--state'><Text>{title}</Text>{children}</View>
}

export function tableStateLabel(table: AdminTable, now: number): string {
  if (table.current_status?.value === 'awaiting_payment') return '待付款'
  if (table.current_status?.value === 'active') {
    if (table.table_release_at && now >= Date.parse(table.table_release_at)) return '待确认结束'
    return table.service_ends_at && now >= Date.parse(table.service_ends_at) ? '缓冲中' : '体验中'
  }
  return table.is_enabled ? '空闲' : '暂停开台'
}

function TableRemaining({ table, now }: { readonly table: AdminTable; readonly now: number }) {
  if (table.current_status?.value === 'awaiting_payment' && table.payment_deadline_at) {
    return <View className='admin-table__remaining'><Text>付款等待剩余</Text><Text>{tableCountdown(table.payment_deadline_at, now)}</Text></View>
  }
  if (table.current_status?.value === 'active' && table.table_release_at) {
    const grace = table.service_ends_at && now >= Date.parse(table.service_ends_at)
    const end = grace ? table.table_release_at : table.service_ends_at
    if (now >= Date.parse(table.table_release_at)) return <Text>时间已到，正在确认释放状态</Text>
    return <View className='admin-table__remaining'>
      <Text>{grace ? '缓冲剩余' : '体验剩余'}</Text>
      <Text>{end ? tableCountdown(end, now) : '正在同步…'}</Text>
      <Text>{grace ? '结束后自动释放' : '结束后另有 10 分钟缓冲'}</Text>
    </View>
  }
  return <Text className='admin-table__meta'>{table.is_enabled ? '可接待下一组顾客' : '启用后可接待顾客'}</Text>
}
