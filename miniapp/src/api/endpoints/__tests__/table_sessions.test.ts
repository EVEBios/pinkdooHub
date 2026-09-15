import type { ApiRequestOptions } from '@/api/types'

import { TableSessionApi } from '../table_sessions'

const now = '2026-09-10T04:00:00Z'
const token = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'
const sessionNo = `TS${'1'.repeat(26)}`
const table = { id: 1, table_no: 'T01', display_name: 'T01号桌', is_enabled: true }
const session = {
  session_no: sessionNo,
  table,
  order_id: 8,
  order_no: `OD${'2'.repeat(26)}`,
  status: { value: 'awaiting_payment', label: '待支付' },
  claimed_at: now,
  payment_deadline_at: '2026-09-10T04:15:00Z',
  started_at: null,
  table_release_at: null,
  closed_at: null,
  close_reason: null,
  timers: [],
  server_now: now,
}

class FakeClient {
  readonly requests: ApiRequestOptions[] = []
  constructor(private readonly responses: readonly unknown[]) {}
  async request<T>(request: ApiRequestOptions): Promise<T> {
    this.requests.push(request)
    return this.responses[this.requests.length - 1] as T
  }
}

describe('TableSessionApi', () => {
  it('公开解析只投影桌台摘要且不发送认证', async () => {
    const client = new FakeClient([{
      table_no: 'T01', display_name: 'T01号桌', is_enabled: true, is_available: true, user_id: 99,
    }])
    const api = new TableSessionApi(client)
    await expect(api.resolveTableCode(token)).resolves.toEqual({
      table_no: 'T01', display_name: 'T01号桌', is_enabled: true, is_available: true,
    })
    expect(client.requests[0]).toMatchObject({
      path: `/api/v1/table-codes/${token}`, auth: 'none', method: 'GET',
    })
  })

  it('创建会话绑定请求与幂等键并验证订单', async () => {
    const client = new FakeClient([session])
    const api = new TableSessionApi(client)
    await expect(api.createSession(token, 8, 'claim-key')).resolves.toEqual(session)
    expect(client.requests[0]).toMatchObject({
      path: '/api/v1/table-sessions',
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': 'claim-key' },
      body: { qr_token: token, order_id: 8 },
    })
  })

  it('管理员释放携带原因和幂等键且只接受关闭终态', async () => {
    const closed = {
      ...session,
      status: { value: 'closed', label: '已结束' },
      closed_at: now,
      close_reason: { value: 'admin_released', label: '管理员释放' },
      user_id: 7,
      user_nickname: '顾客',
      payment_id: null,
      closed_by_user_id: 1,
      admin_close_reason: '现场调整',
    }
    const client = new FakeClient([closed])
    const api = new TableSessionApi(client)
    await expect(api.releaseAdminSession(sessionNo, '  现场调整  ', 'release-key')).resolves.toMatchObject(closed)
    expect(client.requests[0]).toMatchObject({
      headers: { 'Idempotency-Key': 'release-key' },
      body: { reason: '现场调整' },
    })
  })

  it('拒绝管理员会话列表中的未知状态与不一致时间形状', async () => {
    const malformed = {
      items: [{
        session_no: sessionNo,
        table,
        order_id: 8,
        order_no: `OD${'2'.repeat(26)}`,
        user_id: 7,
        user_nickname: '顾客',
        status: { value: 'mystery', label: '未知' },
        close_reason: null,
        timer_count: 0,
        minimum_duration_minutes: null,
        maximum_duration_minutes: null,
        claimed_at: now,
        payment_deadline_at: '2026-09-10T04:15:00Z',
        started_at: null,
        table_release_at: null,
        closed_at: null,
      }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }
    const api = new TableSessionApi(new FakeClient([malformed]))
    await expect(api.listAdminSessions()).rejects.toMatchObject({ name: 'ContractError' })
  })
})

const directSession = {
  ...session, source: 'direct', order_id: null, order_no: null, user_id: null, user_nickname: null,
  order_total_amount: null, payment_id: null, payment_deadline_at: null,
  opened_by_user_id: 1, source_option_id: 5, direct_duration_minutes: 60, opening_note: '团购',
  status: { value: 'active', label: '计时中' }, started_at: now, table_release_at: '2026-09-10T05:10:00Z',
  timers: [{ id: 1, duration_minutes: 60, buffer_minutes: 10, started_at: now,
    service_ends_at: '2026-09-10T05:00:00Z', grace_ends_at: '2026-09-10T05:10:00Z',
    phase: { value: 'experience', label: '体验中' }, ended_at: null, experience_items: [] }],
}

it('直接开台携带时长快照及幂等键，不携带顾客或订单', async () => {
  const client = new FakeClient([directSession])
  const api = new TableSessionApi(client)
  await expect(api.createDirectSession(1, { option_id: 5, duration_minutes: 60 }, ' 团购 ', 'direct-key')).resolves.toMatchObject(directSession)
  expect(client.requests[0]).toMatchObject({
    path: '/api/v1/admin/tables/1/direct-sessions', method: 'POST',
    headers: { 'Idempotency-Key': 'direct-key' },
    body: { option_id: 5, duration_minutes: 60, note: '团购' },
  })
})

it('拒绝伪造为直接开台但关联了付款的响应', async () => {
  const api = new TableSessionApi(new FakeClient([{ ...directSession, payment_id: 9 }]))
  await expect(api.getAdminSession(sessionNo)).rejects.toMatchObject({ name: 'ContractError' })
})

it('顾客会话接口不接受无订单的直接开台响应', async () => {
  const api = new TableSessionApi(new FakeClient([directSession]))
  await expect(api.getCurrentSession()).rejects.toMatchObject({ name: 'ContractError' })
})

it('确认付款精确绑定当前桌台会话', async () => {
  const client = new FakeClient([{}])
  await new TableSessionApi(client).confirmAdminPayment(8, sessionNo)
  expect(client.requests[0]).toMatchObject({
    path: '/api/v1/admin/orders/8/paid', method: 'PATCH', auth: 'required',
    headers: { 'Table-Session-No': sessionNo },
  })
})

it('时长列表拒绝重复或非法配置', async () => {
  const api = new TableSessionApi(new FakeClient([{ buffer_minutes: 10, items: [
    { option_id: 1, duration_minutes: 60 }, { option_id: 2, duration_minutes: 60 },
  ] }]))
  await expect(api.listDirectDurations()).rejects.toMatchObject({ name: 'ContractError' })
})

it('管理桌台完整返回各组计时，拒绝缺失、重复和时间不一致的摘要', async () => {
  const timer = { id: 1, duration_minutes: 60, service_ends_at: '2026-09-10T05:00:00Z', grace_ends_at: '2026-09-10T05:10:00Z' }
  const item = { ...table, state: 'active', current_status: { value: 'active', label: '计时中' }, timer_count: 1, timers: [timer], service_ends_at: timer.service_ends_at, table_release_at: timer.grace_ends_at }
  const list = { server_now: now, items: [item] }
  const api = new TableSessionApi(new FakeClient([list]))
  await expect(api.listAdminTables()).resolves.toMatchObject({ items: [{ timers: [timer] }] })
  for (const bad of [
    { ...item, timers: undefined }, { ...item, timer_count: 2 },
    { ...item, timer_count: 2, timers: [timer, timer] },
    { ...item, service_ends_at: now },
    { ...item, timers: [{ ...timer, grace_ends_at: timer.service_ends_at }] },
  ]) {
    await expect(new TableSessionApi(new FakeClient([{ ...list, items: [bad] }])).listAdminTables()).rejects.toThrow()
  }
})
