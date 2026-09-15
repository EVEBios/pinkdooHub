import { Button, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import { useAuth } from '@/auth'

import { getTableErrorMessage } from './errors'
import { getDefaultTableSessionApi } from './runtime'
import { shoppingTableStore } from './shopping_table'
import { parseTableToken } from './table_session_route'
import { useShoppingTable } from './use_shopping_table'

import './table_selector.scss'

export function TableSelector({ disabled = false, onChange, value, allowClear = true }: {
  readonly disabled?: boolean
  readonly value?: string
  readonly allowClear?: boolean
  readonly onChange: (tableNo?: string) => Promise<void>
}) {
  const [input, setInput] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const blocked = disabled || busy
  async function choose(scan = false): Promise<void> {
    if (blocked) return
    setBusy(true)
    setError(undefined)
    try {
      const api = getDefaultTableSessionApi()
      let tableNo: string
      if (scan) {
        const scanned = await Taro.scanCode({ scanType: ['qrCode'] })
        const token = parseTableToken(scanned.result)
        if (!token) throw new Error('请扫描门店桌台二维码')
        tableNo = (await api.resolveTableCode(token)).table_no
      } else {
        const normalized = input.trim().toUpperCase().replace(/^T/, '')
        if (!/^\d{1,2}$/.test(normalized) || Number(normalized) < 1 || Number(normalized) > 30) {
          throw new Error('请输入 1–30 号桌，例如 8 或 T08')
        }
        tableNo = `T${Number(normalized).toString().padStart(2, '0')}`
      }
      const table = await api.resolveTableNumber(tableNo)
      if (!table.is_enabled || !table.is_available) throw new Error(`${table.table_no} 暂不可用，请选择其他桌台`)
      const confirmed = await Taro.showModal({
        title: `确认选择 ${table.table_no}？`,
        content: `${table.display_name}。请核对桌面桌号；提交订单后保留 15 分钟，付款成功开始计时。`,
        confirmText: '确认选桌', confirmColor: '#a92e51',
      })
      if (!confirmed.confirm) return
      await onChange(tableNo)
      setEditing(false)
      setInput('')
    } catch (cause) {
      if (cause && typeof cause === 'object' && 'errMsg' in cause && String(cause.errMsg).includes('cancel')) return
      setError(getTableErrorMessage(cause))
    } finally { setBusy(false) }
  }
  return <View className='table-selector'>
    <Text className='table-selector__title'>本次桌台：{value ?? '未选择'}</Text>
    <Text className='table-selector__hint'>{value
      ? '确认订单后保留桌台，付款成功开始计时。'
      : '到店体验可扫码或输入桌号；不选桌则按普通订单购买。'}</Text>
    <View className='table-selector__actions'>
      <Button className='table-selector__scan' disabled={blocked} onClick={() => void choose(true)}>扫码选桌</Button>
      <Button className='table-selector__edit' disabled={blocked} onClick={() => setEditing(!editing)}>{value ? '更换桌台' : '输入桌号'}</Button>
    </View>
    {editing && <View className='table-selector__entry'>
      <Input aria-label='桌台号' className='table-selector__input' maxlength={3} placeholder='例如 8 或 T08' value={input} disabled={blocked} onInput={(event) => setInput(event.detail.value)} />
      <Button className='table-selector__confirm' disabled={blocked || !input.trim()} onClick={() => void choose()}>核对桌台</Button>
    </View>}
    {value && allowClear && <Button className='table-selector__clear' disabled={blocked} onClick={() => {
      if (blocked) return
      setBusy(true)
      void Taro.showModal({ title: '取消本次开台？', content: '商品保留在购物车，结算时按普通订单购买。', confirmText: '取消开台' })
        .then(async (result) => { if (result.confirm) await onChange(undefined) })
        .catch((cause) => setError(cause instanceof Error ? cause.message : '取消选桌失败，请重试'))
        .finally(() => setBusy(false))
    }}
    >取消本次开台</Button>}
    {error && <Text className='table-selector__error'>{error}</Text>}
  </View>
}

export function ShoppingTableBanner() {
  const auth = useAuth()
  const table = useShoppingTable(auth.status === 'authenticated' ? auth.user?.id : undefined)
  if (!table.selection && !table.error && !table.attempt) return null
  return <View className='shopping-table-banner'>
    <Text>{table.error ?? (table.attempt ? '上次开台订单结果待核对，请前往确认订单页继续' : `本次桌台 ${table.selection!.tableNo} · ${table.expired ? '选桌已失效，请在结算时重新选桌' : '确认订单后保留桌台'}`)}</Text>
  </View>
}

export async function rememberScannedTable(userId: number, tableNo: string): Promise<boolean> {
  const saved = await shoppingTableStore.load(userId)
  if (saved.attempt) throw new Error('上次开台订单结果待核对，请从购物车进入确认订单页继续')
  if (saved.selection && saved.selection.tableNo !== tableNo) {
    const result = await Taro.showModal({ title: `更换为 ${tableNo}？`, content: `本次购物已选 ${saved.selection.tableNo}，更换后将使用新桌台。`, confirmText: '更换桌台' })
    if (!result.confirm) return false
  }
  await shoppingTableStore.select(userId, tableNo)
  return true
}
