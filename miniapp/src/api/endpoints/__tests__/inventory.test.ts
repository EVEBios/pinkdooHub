import { ContractError } from '@/api/errors'
import type { ApiRequestOptions, ApiResponse } from '@/api/types'

import { InventoryApi, type InventoryTransaction } from '../inventory'

const transaction: InventoryTransaction = {
  id: 31,
  product_id: 7,
  transaction_type: 'admin_adjustment',
  change_quantity: 5,
  before_quantity: 10,
  after_quantity: 15,
  reason: '盘点补录',
  source_type: 'admin',
  source_id: null,
  source_order_no: null,
  operator_id: 2,
  operator_nickname: '管理员',
  created_at: '2026-08-28T08:00:00Z',
}

class FakeClient {
  readonly requests: ApiRequestOptions[] = []

  constructor(
    private readonly data: unknown,
    private readonly statusCode = 200,
  ) {}

  async request<T>(request: ApiRequestOptions): Promise<T> {
    this.requests.push(request)
    return this.data as T
  }

  async requestWithMeta<T>(request: ApiRequestOptions): Promise<ApiResponse<T>> {
    this.requests.push(request)
    return { data: this.data as T, statusCode: this.statusCode }
  }
}

describe('InventoryApi', () => {
  it.each([
    [201, 'created'],
    [200, 'replayed'],
  ] as const)('根据 HTTP %i 区分首次提交与幂等重放', async (statusCode, disposition) => {
    const client = new FakeClient({
      product_id: 7,
      stock: 15,
      transaction: { ...transaction, unexpected: 'drop-me' },
      idempotency_key: 'must-not-leak',
    }, statusCode)
    const api = new InventoryApi(client)

    await expect(api.adjustStock(7, {
      change: 5,
      reason: '  盘点补录  ',
      unexpected: 'drop-me',
    } as never, 'inventory-key-1')).resolves.toEqual({
      disposition,
      adjustment: { product_id: 7, stock: 15, transaction },
    })
    expect(client.requests[0]).toMatchObject({
      operation: 'inventory.admin.adjust',
      method: 'POST',
      path: '/api/v1/admin/products/kit/7/inventory-adjustments',
      auth: 'required',
      headers: { 'Idempotency-Key': 'inventory-key-1' },
      body: { change: 5, reason: '盘点补录' },
    })
  })

  it('拒绝非 200/201 状态和不自洽的库存响应', async () => {
    const body = { product_id: 7, stock: 15, transaction }
    await expect(new InventoryApi(new FakeClient(body, 202)).adjustStock(
      7, { change: 5, reason: '补录' }, 'key-1',
    )).rejects.toBeInstanceOf(ContractError)
    await expect(new InventoryApi(new FakeClient({
      ...body,
      transaction: { ...transaction, after_quantity: 14 },
    }, 201)).adjustStock(7, { change: 5, reason: '补录' }, 'key-1'))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('Kit 与全局流水查询只投影契约字段', async () => {
    const page = { items: [transaction], total: 1, page: 1, page_size: 20, pages: 1 }
    const client = new FakeClient(page)
    const api = new InventoryApi(client)
    await api.listProductTransactions(7, {
      page: 1,
      page_size: 20,
      type: 'admin_adjustment',
      source_type: 'admin',
      source_id: null,
      created_from: '2026-08-01T00:00:00Z',
      created_to: '2026-09-01T00:00:00Z',
      unexpected: 'drop-me',
    } as never)
    await api.listTransactions({
      page: 1,
      page_size: 20,
      product_id: 7,
      unexpected: 'drop-me',
    } as never)

    expect(client.requests[0].query).toEqual({
      page: 1,
      page_size: 20,
      type: 'admin_adjustment',
      source_type: 'admin',
      created_from: '2026-08-01T00:00:00Z',
      created_to: '2026-09-01T00:00:00Z',
    })
    expect(client.requests[1].query).toEqual({ page: 1, page_size: 20, product_id: 7 })
  })

  it('接受四类合法流水，并丢弃服务端额外字段', async () => {
    const orderBase = {
      ...transaction,
      source_type: 'order' as const,
      source_id: 9,
      source_order_no: 'OD01J6DCTD6T2QE13E5YQB1QDB7A',
      operator_id: null,
      operator_nickname: null,
    }
    const items = [
      {
        ...transaction,
        id: 1,
        transaction_type: 'opening_balance',
        change_quantity: 10,
        before_quantity: 0,
        after_quantity: 10,
        source_type: 'migration',
        source_id: null,
        source_order_no: null,
        operator_id: null,
        operator_nickname: null,
      },
      transaction,
      {
        ...orderBase,
        id: 3,
        transaction_type: 'order_deduction',
        change_quantity: -2,
        before_quantity: 10,
        after_quantity: 8,
      },
      {
        ...orderBase,
        id: 4,
        transaction_type: 'order_cancellation_restore',
        change_quantity: 2,
        before_quantity: 8,
        after_quantity: 10,
        private_note: 'drop-me',
      },
    ]
    const api = new InventoryApi(new FakeClient({
      items,
      total: 4,
      page: 1,
      page_size: 20,
      pages: 1,
    }))

    const result = await api.listTransactions()
    expect(result.items.map((item) => item.transaction_type)).toEqual([
      'opening_balance',
      'admin_adjustment',
      'order_deduction',
      'order_cancellation_restore',
    ])
    expect(result.items[3]).not.toHaveProperty('private_note')
  })
})
