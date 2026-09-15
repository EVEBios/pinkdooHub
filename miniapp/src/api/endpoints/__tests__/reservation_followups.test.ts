import { ReservationFollowupApi } from '../reservation_followups'

const time = '2026-09-15T00:00:00Z'
const snapshot = { reservation_id: 1, kind: 'contact', eligible: true, completed: false, revision: 0, latest: null, server_now: time }
const request = jest.fn()
const api = new ReservationFollowupApi({ request })
afterEach(() => jest.resetAllMocks())

test('跟进摘要严格校验计数，读写仅请求管理员路径', async () => {
  request.mockResolvedValueOnce({ server_now: time, contact_pending: 1, overdue_pending: 2 })
  expect((await api.counts()).contact_pending).toBe(1)
  expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ path: '/api/v1/admin/reservation-followups/summary', auth: 'required' }))
  request.mockResolvedValueOnce({ server_now: time, contact_pending: -1, overdue_pending: 0 })
  await expect(api.counts()).rejects.toThrow()
})
test.each([{ reservation_id: 2 }, { kind: 'overdue' }, { completed: true }, { revision: 1 }])('详情拒绝串预约、串类型或自相矛盾版本 %s', async (update) => {
  request.mockResolvedValue({ ...snapshot, ...update })
  await expect(api.detail(1, 'contact')).rejects.toThrow()
})
test('列表不能把已完成事项混入待处理，也拒绝重复预约', async () => {
  const item = { ...snapshot, product_name: null, customer_name: '测试顾客', scheduled_start_at: time }
  request.mockResolvedValue({ items: [item], total: 1, page: 1, page_size: 20, pages: 1 })
  expect((await api.list('contact', 'pending')).items).toHaveLength(1)
  await expect(api.list('contact', 'completed')).rejects.toThrow()
  request.mockResolvedValue({ items: [item, item], total: 2, page: 1, page_size: 20, pages: 1 })
  await expect(api.list('contact', 'pending')).rejects.toThrow()
})
test('保存透传同一请求键和版本，校验返回预约归属', async () => {
  const body = { expected_revision: 0, request_key: '073629fd-095a-4058-85e1-c99014e6a830', outcome: 'retry' as const, note: '电话未接通' }
  request.mockResolvedValue(snapshot)
  await api.write(1, 'contact', body)
  expect(request).toHaveBeenCalledWith(expect.objectContaining({ path: '/api/v1/admin/reservation-followups/1/contact', method: 'POST', body }))
  request.mockResolvedValue({ ...snapshot, reservation_id: 2 })
  await expect(api.write(1, 'contact', body)).rejects.toThrow()
})
