import { remainingSeconds } from '../index'

jest.mock('@/auth', () => ({
  buildLoginUrl: jest.fn(),
  isAdminRole: () => false,
  ORDER_LIST_PATH: '/pages/orders/index',
  useAuth: jest.fn(),
}))
jest.mock('@/features/table_session', () => ({
  buildTableEntryUrl: jest.fn(),
  parseTableEntryRoute: jest.fn(),
  useTableEntry: jest.fn(),
}))
jest.mock('@/navigation/admin_workbench_redirect', () => ({ AdminWorkbenchRedirect: () => null }))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('桌台倒计时', () => {
  it('使用持续推进的服务端估算时间且不显示负数', () => {
    expect(remainingSeconds(
      '2026-09-10T04:01:10Z',
      Date.parse('2026-09-10T04:00:00Z'),
    )).toBe(70)
    expect(remainingSeconds(
      '2026-09-10T04:01:10Z',
      Date.parse('2026-09-10T04:00:05Z'),
    )).toBe(65)
    expect(remainingSeconds(
      '2026-09-10T03:59:59Z',
      Date.parse('2026-09-10T04:00:00Z'),
    )).toBe(0)
  })
})
