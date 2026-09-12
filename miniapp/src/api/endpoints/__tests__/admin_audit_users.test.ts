import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'

import { AdminUserApi } from '../admin_users'
import { AuditApi } from '../audit'

describe('8.8 ADMIN API 响应白名单', () => {
  it('商品审计只保留审计白名单并绑定目标商品', async () => {
    const request = jest.fn(async () => ({
      items: [{
        id: 3,
        operator_id: 2,
        action: 'UPDATE_PRODUCT',
        target_type: 'product',
        target_id: 7,
        description: '{"name":"新名称"}',
        ip_address: '127.0.0.1',
        created_at: '2026-08-28T08:00:00Z',
        password: 'must-not-leak',
      }],
      total: 1, page: 1, page_size: 20, pages: 1,
    }))
    const api = new AuditApi({ request } as Pick<ApiClient, 'request'>)
    const page = await api.listProductAuditLogs(7, { page: 1, page_size: 20 })

    expect(request).toHaveBeenCalledWith({
      operation: 'products.admin.audit.list',
      path: '/api/v1/admin/products/7/audit-logs',
      method: 'GET',
      auth: 'required',
      query: { page: 1, page_size: 20 },
    })
    expect(page.items[0]).not.toHaveProperty('password')
  })

  it('拒绝审计项被挂到另一个商品', async () => {
    const api = new AuditApi({
      request: jest.fn(async () => ({
        items: [{
          id: 3, operator_id: 2, action: 'UPDATE_PRODUCT', target_type: 'product', target_id: 8,
          description: null, ip_address: '127.0.0.1', created_at: '2026-08-28T08:00:00Z',
        }],
        total: 1, page: 1, page_size: 20, pages: 1,
      })),
    } as Pick<ApiClient, 'request'>)
    await expect(api.listProductAuditLogs(7)).rejects.toBeInstanceOf(ContractError)
  })

  it('用户列表不会保留手机号、头像或密码，禁用不发送 body', async () => {
    const request = jest.fn()
      .mockResolvedValueOnce({
        items: [{
          id: 5, username: 'normal_user', nickname: '普通用户', role: 'user', status: 'normal',
          last_login_at: null, created_at: '2026-08-28T08:00:00Z',
          phone: '13800000000', avatar: '/secret.jpg', password: 'must-not-leak',
        }],
        total: 1, page: 1, page_size: 20, pages: 1,
      })
      .mockResolvedValueOnce(null)
    const api = new AdminUserApi({ request } as Pick<ApiClient, 'request'>)
    const page = await api.listUsers({ status: 'normal', role: 'user' })
    await api.disableUser(5)

    expect(page.items[0]).not.toHaveProperty('phone')
    expect(page.items[0]).not.toHaveProperty('avatar')
    expect(page.items[0]).not.toHaveProperty('password')
    expect(request).toHaveBeenLastCalledWith({
      operation: 'users.admin.disable',
      path: '/api/v1/admin/users/5/disable',
      method: 'PUT',
      auth: 'required',
    })
  })

  it('禁用响应必须是统一信封解出的 null', async () => {
    const api = new AdminUserApi({
      request: jest.fn(async () => ({})),
    } as Pick<ApiClient, 'request'>)
    await expect(api.disableUser(5)).rejects.toBeInstanceOf(ContractError)
  })
})
