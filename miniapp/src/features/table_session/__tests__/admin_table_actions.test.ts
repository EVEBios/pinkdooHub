import Taro from '@tarojs/taro'
import type { TableSessionApi } from '@/api/endpoints/table_sessions'
import { TimeoutError } from '@/api/errors'
import { confirmTablePayment } from '../admin_table_actions'

jest.mock('@tarojs/taro', () => ({ __esModule: true, default: { showModal: jest.fn() } }))
const pending = {
  table: { table_no: 'T01' }, status: { value: 'awaiting_payment' }, order_id: 8,
  user_nickname: '顾客', order_no: 'OD8', order_total_amount: '80.00', order_experience_durations: [60],
}

it('取消收款确认时不发起资金操作', async () => {
  jest.mocked(Taro.showModal).mockResolvedValueOnce({ confirm: false, cancel: true, errMsg: 'ok' })
  const source = { getAdminSession: jest.fn().mockResolvedValue(pending), confirmAdminPayment: jest.fn() }
  await expect(confirmTablePayment(source as unknown as TableSessionApi, 'TS1')).resolves.toBe(false)
  expect(Taro.showModal).toHaveBeenLastCalledWith(expect.objectContaining({
    confirmText: '收款计时',
    content: expect.stringContaining('确认后立即开始计时'),
  }))
  expect(Array.from(jest.mocked(Taro.showModal).mock.calls.at(-1)![0]!.confirmText!).length).toBeLessThanOrEqual(4)
  expect(source.confirmAdminPayment).not.toHaveBeenCalled()
})

it('超时后读取到原会话已付款，仅确认结果，不重复付款', async () => {
  jest.mocked(Taro.showModal).mockResolvedValueOnce({ confirm: true, cancel: false, errMsg: 'ok' })
  const source = {
    getAdminSession: jest.fn().mockResolvedValueOnce(pending).mockResolvedValueOnce({ status: { value: 'active' }, payment_id: 5 }),
    confirmAdminPayment: jest.fn().mockRejectedValue(new TimeoutError({ operation: 'confirm' }, null)),
  }
  await expect(confirmTablePayment(source as unknown as TableSessionApi, 'TS1')).resolves.toBe(true)
  expect(source.confirmAdminPayment).toHaveBeenCalledTimes(1)
  expect(source.getAdminSession).toHaveBeenLastCalledWith('TS1')
})

it('已关闭会话不能进入收款确认', async () => {
  const source = { getAdminSession: jest.fn().mockResolvedValue({ ...pending, status: { value: 'closed' } }), confirmAdminPayment: jest.fn() }
  await expect(confirmTablePayment(source as unknown as TableSessionApi, 'TS1')).rejects.toThrow('不处于待付款')
  expect(source.confirmAdminPayment).not.toHaveBeenCalled()
})
