import type { UserProfile } from '@/api/endpoints/auth'

import { shouldMountCustomerCart } from '../app'

const baseUser: UserProfile = {
  id: 7,
  username: 'customer',
  nickname: '顾客',
  phone: null,
  avatar: null,
  role: 'user',
  status: 'normal',
  last_login_at: null,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T08:00:00Z',
}

describe('应用级购物车角色边界', () => {
  it('只在 Guest 或已确认的普通 USER 身份下挂载购物车', () => {
    expect(shouldMountCustomerCart('guest')).toBe(true)
    expect(shouldMountCustomerCart('authenticated', baseUser)).toBe(true)
    expect(shouldMountCustomerCart('authenticated', { ...baseUser, role: 'admin' })).toBe(false)
    expect(shouldMountCustomerCart('authenticated', { ...baseUser, role: 'super_admin' })).toBe(false)
  })

  it('角色确认前、认证错误、资料缺失与未知角色都不挂载购物车', () => {
    expect(shouldMountCustomerCart('initializing')).toBe(false)
    expect(shouldMountCustomerCart('error')).toBe(false)
    expect(shouldMountCustomerCart('authenticated')).toBe(false)
    expect(shouldMountCustomerCart('authenticated', {
      ...baseUser,
      role: 'operator' as never,
    })).toBe(false)
  })
})
