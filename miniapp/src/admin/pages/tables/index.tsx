import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { AdminTableList } from '@/api/endpoints/table_sessions'
import { ADMIN_WORKBENCH_PATH, buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import { buildAdminTableSessionUrl, getDefaultTableSessionApi } from '@/features/table_session'

import './index.scss'

export default function AdminTablesPage() {
  const auth = useAuth()
  if (auth.status === 'guest') return <AdminState title='登录后管理桌台'><Button onClick={() => void Taro.reLaunch({ url: buildLoginUrl(ADMIN_WORKBENCH_PATH) })}>去登录</Button></AdminState>
  if (auth.status === 'initializing') return <AdminState title='正在确认管理权限' />
  if (!auth.user || !isAdminRole(auth.user.role)) return <AdminState title='无桌台管理权限' />
  return <AdminTablesContent />
}

function AdminTablesContent() {
  const source = getDefaultTableSessionApi()
  const [data, setData] = useState<AdminTableList>()
  const [error, setError] = useState('')
  const [updating, setUpdating] = useState<number>()
  const loadSequenceRef = useRef(0)
  const updatingRef = useRef(false)
  const load = useCallback(() => {
    const sequence = ++loadSequenceRef.current
    setError('')
    void source.listAdminTables()
      .then((result) => {
        if (sequence === loadSequenceRef.current) setData(result)
      })
      .catch((cause: unknown) => {
        if (sequence === loadSequenceRef.current) {
          setError(cause instanceof Error ? cause.message : '桌台读取失败')
        }
      })
  }, [source])
  useEffect(() => {
    load()
    return () => { loadSequenceRef.current += 1 }
  }, [load])
  useEffect(() => {
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [load])
  useDidShow(load)

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

  return (
    <View className='admin-tables-page'>
      <View className='admin-tables-header'><Text>30 桌实时状态</Text><Text>{data ? new Date(data.server_now).toLocaleString() : '正在读取…'}</Text></View>
      {error && <View className='admin-tables-alert' ariaRole='alert'><Text>{error}</Text><Button onClick={load}>重试</Button></View>}
      <View className='admin-tables-grid'>
        {data?.items.map((table) => (
          <View className={`admin-table admin-table--${table.state}`} key={table.id}>
            <View className='admin-table__heading'><Text>{table.table_no}</Text><Text>{table.state}</Text></View>
            <Text>{table.current_order_no ?? '当前空闲'}</Text>
            {table.current_session_no && <Button onClick={() => void Taro.navigateTo({ url: buildAdminTableSessionUrl(table.current_session_no!) })}>查看当前会话</Button>}
            <Button disabled={updating === table.id} onClick={() => void toggle(table.id, table.is_enabled)}>{table.is_enabled ? '停用新开台' : '重新启用'}</Button>
          </View>
        ))}
      </View>
    </View>
  )
}

function AdminState({ children, title }: { readonly title: string; readonly children?: React.ReactNode }) {
  return <View className='admin-tables-page admin-tables-page--state'><Text>{title}</Text>{children}</View>
}
