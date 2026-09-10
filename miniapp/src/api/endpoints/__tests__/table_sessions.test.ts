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
    await expect(api.releaseAdminSession(sessionNo, '  现场调整  ', 'release-key')).resolves.toEqual(closed)
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
