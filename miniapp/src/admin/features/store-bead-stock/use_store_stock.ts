import { useEffect, useRef, useState } from 'react'
import type { StockBatch, StockWrite, StoreStock } from '@/api/endpoints/store_bead_stock'
import { BusinessError, HttpError } from '@/api/errors'
import { usePageVisibility } from '@/features/attention/hooks'
import { changes, newRequestKey, type Draft } from './model'
import { getStoreStockApi } from './runtime'

type Mode = 'browse' | 'edit' | 'confirm' | 'saving' | 'unknown' | 'conflict'
export function useStoreStock() {
  const [rows, setRows] = useState<StoreStock[]>([])
  const [draft, setDraft] = useState<Draft>({})
  const [mode, setMode] = useState<Mode>('browse')
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [result, setResult] = useState<StockBatch>()
  const [reason, setReason] = useState<NonNullable<StockWrite['reason']>>('stocktake')
  const [note, setNote] = useState('')
  const mounted = useRef(true), busy = useRef(false), modeRef = useRef<Mode>('browse')
  const intent = useRef<StockWrite>()
  const { visible } = usePageVisibility()
  function switchMode(value: Mode) { modeRef.current = value; setMode(value) }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  async function load(edit = false, rebase = false) {
    if (busy.current) return
    busy.current = true; setLoading(true); setError('')
    try {
      const next = await getStoreStockApi().list()
      if (!mounted.current) return
      setRows(next); setLoaded(true)
      if (edit || rebase) {
        if (!rebase) { setDraft({}); setReason('stocktake'); setNote(''); setSuccess('') }
        intent.current = undefined
        switchMode('edit')
        if (rebase) setError('已读取最新库存，请核对保留的调整数量，再进入确认清单。')
      }
    } catch (cause) {
      if (mounted.current) setError(cause instanceof BusinessError ? cause.message : '库存读取失败，请刷新重试。')
    } finally { busy.current = false; if (mounted.current) setLoading(false) }
  }
  useEffect(() => {
    if (visible && modeRef.current === 'browse') void load()
    // 草稿期间回前台不替换盘点快照；提交时由服务端复核每色版本。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  function update(id: number, value: string) {
    if (modeRef.current !== 'edit' || busy.current) return
    setDraft(current => ({ ...current, [id]: value }))
    setError('')
  }
  function cancel() {
    if (busy.current || modeRef.current === 'unknown') return
    setDraft({}); intent.current = undefined; setError(''); switchMode('browse')
    void load()
  }
  function review() {
    if (modeRef.current !== 'edit' || busy.current) return
    const next = changes(rows, draft)
    if (next.invalid.length) { setError(`${next.invalid.join('、')}：请输入 0 到 999999 的整数包数`); return }
    if (!next.items.length) return
    intent.current = { request_key: newRequestKey(), reason, note: note.trim(), items: next.items }
    setError(''); switchMode('confirm')
  }
  function backToEdit() {
    if (busy.current || modeRef.current !== 'confirm') return
    intent.current = undefined; switchMode('edit'); setError('')
  }
  async function submit(retry = false) {
    const body = intent.current
    if (busy.current || !body || (!retry && modeRef.current !== 'confirm') || (retry && modeRef.current !== 'unknown')) return
    busy.current = true; switchMode('saving'); setError('')
    try {
      let saved: StockBatch
      if (retry) {
        try { saved = await getStoreStockApi().byRequest(body.request_key) }
        catch (cause) {
          if ((cause instanceof BusinessError || cause instanceof HttpError) && cause.statusCode === 404) saved = await getStoreStockApi().write(body)
          else throw cause
        }
      } else saved = await getStoreStockApi().write(body)
      if (!mounted.current) return
      setResult(saved); setDraft({}); intent.current = undefined; switchMode('browse')
      setSuccess(`已保存 ${saved.changed_colors} 色库存调整`)
      // 保存成功与后续读取失败分开，不能把成功的批次误标为需要重新提交。
      try { const next = await getStoreStockApi().list(); if (mounted.current) { setRows(next); setLoaded(true) } }
      catch { if (mounted.current) setError('调整已保存，最新库存暂未读取成功，请刷新后继续。') }
    } catch (cause) {
      if (!mounted.current) return
      if (cause instanceof BusinessError && cause.statusCode === 409) {
        switchMode('conflict'); setError(cause.message)
      } else if (cause instanceof BusinessError && [400, 401, 403, 404, 422].includes(cause.statusCode ?? 0)) {
        switchMode('edit'); intent.current = undefined; setError(cause.message)
      } else {
        switchMode('unknown'); setError('保存结果尚未确认。请核查本次结果，系统不会重复增减库存。')
      }
    } finally { busy.current = false }
  }
  return { rows, draft, mode, loaded, loading, error, success, result, reason, note, setReason, setNote,
    update, cancel, review, backToEdit, submit, refresh: () => load(), begin: () => load(true), rebase: () => load(false, true) }
}
