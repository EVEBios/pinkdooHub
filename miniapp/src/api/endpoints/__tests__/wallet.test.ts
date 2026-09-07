import { ContractError } from '@/api/errors'
import type { ApiRequestOptions } from '@/api/types'

import { WalletApi } from '../wallet'

const timestamp = '2026-09-05T08:00:00Z'
const wallet = {
  wallet_id: 4,
  user_id: 7,
  balance: '280.00',
  balance_limit: '1000.00',
  status: 'active',
  capabilities: { topup_enabled: false, wallet_payment_enabled: true, refund_enabled: true },
  created_at: timestamp,
  updated_at: timestamp,
}
const user = {
  id: 7,
  username: 'member_007',
  nickname: '拼豆会员',
  phone: null,
  avatar: null,
  role: 'user',
  status: 'normal',
  last_login_at: null,
  created_at: timestamp,
  updated_at: timestamp,
}
const transaction = {
  id: 31,
  transaction_type: 'admin_adjustment',
  direction: 'income',
  change_amount: '20.00',
  before_balance: '260.00',
  after_balance: '280.00',
  source_type: 'admin',
  source_id: null,
  source_order_no: null,
  operator_id: 2,
  operator_nickname: '店长',
  reason: '线下退款差额纠正',
  created_at: timestamp,
}

class FakeClient {
  readonly requests: ApiRequestOptions[] = []

  constructor(private readonly responses: readonly unknown[]) {}

  async request<T>(request: ApiRequestOptions): Promise<T> {
    this.requests.push(request)
    return this.responses[this.requests.length - 1] as T
  }
}

describe('WalletApi', () => {
  it('读取会员与分页流水时严格投影响应', async () => {
    const client = new FakeClient([
      { user: { ...user, private_field: 'drop' }, wallet: { ...wallet, secret: 'drop' } },
      { items: [{ ...transaction, secret: 'drop' }], total: 1, page: 1, page_size: 20, pages: 1 },
    ])
    const api = new WalletApi(client)

    const member = await api.getMemberWallet()
    const page = await api.listWalletTransactions({ page: 1, page_size: 20 })

    expect(member).toEqual({ user, wallet })
    expect(page.items[0]).toEqual(transaction)
    expect(client.requests[1]).toMatchObject({
      path: '/api/v1/wallet/transactions',
      method: 'GET',
      auth: 'required',
      query: { page: 1, page_size: 20 },
    })
  })

  it('余额支付与人工调账携带 Idempotency-Key 并只发送白名单字段', async () => {
    const payment = {
      id: 8,
      payment_no: `PY${'A'.repeat(26)}`,
      order_id: 101,
      recharge_order_id: null,
      purpose: 'order',
      method: 'wallet',
      amount: '99.00',
      status: 'succeeded',
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const client = new FakeClient([
      {
        order_id: 101,
        order_no: `OD${'B'.repeat(26)}`,
        order_status: { value: 'paid', label: '已支付' },
        payment,
        post_payment_balance: '181.00',
      },
      { wallet, transaction },
    ])
    const api = new WalletApi(client)

    await api.payOrderWithWallet(101, 'wallet-payment-key')
    await api.adjustAdminUserWallet(
      7,
      { change: '20.00', reason: '  线下退款差额纠正  ', ignored: true } as never,
      'wallet-adjust-key',
    )

    expect(client.requests[0]).toMatchObject({
      path: '/api/v1/orders/101/payments/wallet',
      method: 'POST',
      headers: { 'Idempotency-Key': 'wallet-payment-key' },
    })
    expect(client.requests[0].body).toBeUndefined()
    expect(client.requests[1]).toMatchObject({
      path: '/api/v1/admin/users/7/wallet-adjustments',
      method: 'POST',
      headers: { 'Idempotency-Key': 'wallet-adjust-key' },
      body: { change: '20.00', reason: '线下退款差额纠正' },
    })
  })

  it('代客钱包订单复用 OrderCreate、携带幂等键并校验真实已支付结果', async () => {
    const payment = {
      id: 18,
      payment_no: `PY${'C'.repeat(26)}`,
      order_id: 201,
      recharge_order_id: null,
      purpose: 'order',
      method: 'wallet',
      amount: '50.00',
      status: 'succeeded',
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const order = {
      id: 201,
      order_no: `OD${'D'.repeat(26)}`,
      user_id: 7,
      user_nickname: '拼豆会员',
      total_amount: '50.00',
      status: { value: 'paid', label: '已支付' },
      remark: '门店代客下单',
      items: [{
        id: 301,
        product_id: 8,
        experience_option_id: null,
        kit_color_id: null,
        product_name: '拼豆材料套装',
        option_duration_minutes: null,
        option_participants: null,
        option_day_type: null,
        kit_color_code: null,
        kit_color_name: null,
        kit_color_slot_no: null,
        sale_unit_grams: null,
        total_weight_grams: null,
        product_price: '25.00',
        quantity: 2,
        subtotal: '50.00',
      }],
      created_at: timestamp,
      updated_at: timestamp,
    }
    const client = new FakeClient([{ order, payment, post_payment_balance: '230.00' }])
    const api = new WalletApi(client)

    await expect(api.createAssistedWalletOrder(7, {
      items: [{ product_id: 8, experience_option_id: null, quantity: 2, ignored: true } as never],
      remark: '  门店代客下单  ',
    }, 'assisted-order-key')).resolves.toEqual({ order, payment, post_payment_balance: '230.00' })
    expect(client.requests[0]).toMatchObject({
      path: '/api/v1/admin/users/7/wallet-orders',
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': 'assisted-order-key' },
      body: { items: [{ product_id: 8, quantity: 2 }], remark: '门店代客下单' },
    })
  })

  it('接受无结算订单的 null 资金事实，并绑定用户端和管理端请求订单', async () => {
    const financial = {
      order_id: 101,
      order_status: { value: 'pending', label: '待支付' },
      payment: null,
      refund: null,
    }
    const client = new FakeClient([financial, financial])
    const api = new WalletApi(client)

    await expect(api.getOrderFinancials(101)).resolves.toEqual(financial)
    await expect(api.getAdminOrderFinancials(101)).resolves.toEqual(financial)
    expect(client.requests.map(({ path }) => path)).toEqual([
      '/api/v1/orders/101/financials',
      '/api/v1/admin/orders/101/financials',
    ])
  })

  it('仅接受 Paid 或 Completed 订单上的成功支付事实', async () => {
    const payment = {
      id: 8,
      payment_no: `PY${'A'.repeat(26)}`,
      order_id: 101,
      recharge_order_id: null,
      purpose: 'order',
      method: 'wallet',
      amount: '99.00',
      status: 'succeeded',
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const financialFor = (status: 'pending' | 'paid' | 'cancelled' | 'completed') => ({
      order_id: 101,
      order_status: {
        value: status,
        label: status === 'pending' ? '待支付' : status === 'paid' ? '已支付' :
          status === 'cancelled' ? '已取消' : '已完成',
      },
      payment,
      refund: null,
    })
    const paymentFor = (status: 'pending' | 'paid' | 'cancelled' | 'completed') => ({
      order_id: 101,
      order_no: `OD${'B'.repeat(26)}`,
      order_status: financialFor(status).order_status,
      payment,
      post_payment_balance: '181.00',
    })
    const api = new WalletApi(new FakeClient([
      financialFor('pending'),
      financialFor('cancelled'),
      paymentFor('pending'),
      paymentFor('cancelled'),
      financialFor('completed'),
      paymentFor('completed'),
    ]))

    await expect(api.getOrderFinancials(101)).rejects.toBeInstanceOf(ContractError)
    await expect(api.getOrderFinancials(101)).rejects.toBeInstanceOf(ContractError)
    await expect(api.payOrderWithWallet(101, 'payment-key-1')).rejects.toBeInstanceOf(ContractError)
    await expect(api.payOrderWithWallet(101, 'payment-key-2')).rejects.toBeInstanceOf(ContractError)
    await expect(api.getOrderFinancials(101)).resolves.toEqual(financialFor('completed'))
    await expect(api.payOrderWithWallet(101, 'payment-key-3')).resolves.toEqual(paymentFor('completed'))
  })

  it('拒绝不自洽流水与非两位小数写入', async () => {
    const api = new WalletApi(new FakeClient([{
      items: [{ ...transaction, after_balance: '279.00' }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }]))
    await expect(api.listWalletTransactions()).rejects.toBeInstanceOf(ContractError)
    await expect(api.createRecharge('1', 'key-1')).rejects.toThrow('两位小数')
  })

  it('在发请求前拒绝充值与调账的越界金额', async () => {
    const client = new FakeClient([])
    const api = new WalletApi(client)

    await expect(api.createRecharge('0.01', 'key-1')).rejects.toThrow('1.00–1000.00')
    await expect(api.createRecharge('1000.01', 'key-2')).rejects.toThrow('1.00–1000.00')
    await expect(api.adjustAdminUserWallet(
      7,
      { change: '-1000.01', reason: '越界验证' },
      'key-3',
    )).rejects.toThrow('不得超过 1000.00')
    expect(client.requests).toHaveLength(0)
  })

  it('拒绝调账结果中与钱包余额不一致的流水', async () => {
    const api = new WalletApi(new FakeClient([{
      wallet,
      transaction: { ...transaction, after_balance: '279.00', change_amount: '19.00' },
    }]))

    await expect(api.adjustAdminUserWallet(
      7,
      { change: '20.00', reason: '线下退款差额纠正' },
      'wallet-adjust-key',
    )).rejects.toBeInstanceOf(ContractError)
  })

  it('拒绝与 URL 目标或原始调账意图不一致的资源响应', async () => {
    const payment = {
      id: 8,
      payment_no: `PY${'A'.repeat(26)}`,
      order_id: 102,
      recharge_order_id: null,
      purpose: 'order',
      method: 'wallet',
      amount: '99.00',
      status: 'succeeded',
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const refund = {
      id: 9,
      refund_no: `RF${'B'.repeat(26)}`,
      order_id: 102,
      method: 'wallet',
      amount: '99.00',
      status: 'succeeded',
      reason: '客户协商退款',
      operator_id: 2,
      inventory_restored: false,
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const mismatchedFinancial = {
      order_id: 102,
      order_status: { value: 'paid', label: '已支付' },
      payment,
      refund: null,
    }
    const mismatchedPayment = {
      order_id: 102,
      order_no: `OD${'C'.repeat(26)}`,
      order_status: { value: 'paid', label: '已支付' },
      payment,
      post_payment_balance: '181.00',
    }

    await expect(new WalletApi(new FakeClient([mismatchedFinancial]))
      .getOrderFinancials(101)).rejects.toBeInstanceOf(ContractError)
    await expect(new WalletApi(new FakeClient([mismatchedPayment]))
      .payOrderWithWallet(101, 'wallet-payment-key')).rejects.toBeInstanceOf(ContractError)
    await expect(new WalletApi(new FakeClient([{
      user: { ...user, id: 8 },
      wallet: { ...wallet, user_id: 8 },
    }])).getAdminUserWallet(7)).rejects.toBeInstanceOf(ContractError)
    await expect(new WalletApi(new FakeClient([{
      wallet,
      transaction: { ...transaction, change_amount: '19.00', before_balance: '261.00' },
    }])).adjustAdminUserWallet(
      7,
      { change: '20.00', reason: transaction.reason },
      'wallet-adjust-key',
    )).rejects.toBeInstanceOf(ContractError)
    await expect(new WalletApi(new FakeClient([mismatchedFinancial]))
      .getAdminOrderFinancials(101)).rejects.toBeInstanceOf(ContractError)
    await expect(new WalletApi(new FakeClient([refund]))
      .refundAdminOrder(101, refund.reason, 'refund-key')).rejects.toBeInstanceOf(ContractError)
  })

  it('拒绝代客订单中目标用户、金额或支付终态不自洽的响应', async () => {
    const api = new WalletApi(new FakeClient([{
      order: {
        id: 201,
        order_no: `OD${'D'.repeat(26)}`,
        user_id: 8,
        user_nickname: '另一位会员',
        total_amount: '50.00',
        status: { value: 'paid', label: '已支付' },
        remark: null,
        items: [{
          id: 301, product_id: 8, experience_option_id: null, product_name: '拼豆材料套装',
          option_duration_minutes: null, option_participants: null, option_day_type: null,
          product_price: '25.00', quantity: 2, subtotal: '50.00',
        }],
        created_at: timestamp,
        updated_at: timestamp,
      },
      payment: {
        id: 18, payment_no: `PY${'C'.repeat(26)}`, order_id: 201, recharge_order_id: null,
        purpose: 'order', method: 'wallet', amount: '49.00', status: 'succeeded',
        created_at: timestamp, updated_at: timestamp, succeeded_at: timestamp,
      },
      post_payment_balance: '230.00',
    }]))

    await expect(api.createAssistedWalletOrder(
      7,
      { items: [{ product_id: 8, quantity: 2 }] },
      'assisted-order-key',
    )).rejects.toBeInstanceOf(ContractError)
  })

  it('拒绝与原始代客订单商品、配置、数量或备注不一致的响应', async () => {
    const order = {
      id: 201,
      order_no: `OD${'D'.repeat(26)}`,
      user_id: 7,
      user_nickname: '拼豆会员',
      total_amount: '50.00',
      status: { value: 'paid', label: '已支付' },
      remark: '门店代客下单',
      items: [{
        id: 301,
        product_id: 8,
        experience_option_id: 12,
        product_name: '拼豆体验课',
        option_duration_minutes: 60,
        option_participants: 1,
        option_day_type: { value: 'weekday', label: '工作日' },
        product_price: '25.00',
        quantity: 2,
        subtotal: '50.00',
      }],
      created_at: timestamp,
      updated_at: timestamp,
    }
    const payment = {
      id: 18,
      payment_no: `PY${'C'.repeat(26)}`,
      order_id: 201,
      recharge_order_id: null,
      purpose: 'order',
      method: 'wallet',
      amount: '50.00',
      status: 'succeeded',
      created_at: timestamp,
      updated_at: timestamp,
      succeeded_at: timestamp,
    }
    const response = { order, payment, post_payment_balance: '230.00' }
    const api = new WalletApi(new FakeClient([response, response, response, response]))

    await expect(api.createAssistedWalletOrder(
      7,
      { items: [{ product_id: 9, experience_option_id: 12, quantity: 2 }], remark: order.remark },
      'assisted-product-key',
    )).rejects.toBeInstanceOf(ContractError)
    await expect(api.createAssistedWalletOrder(
      7,
      { items: [{ product_id: 8, experience_option_id: 13, quantity: 2 }], remark: order.remark },
      'assisted-option-key',
    )).rejects.toBeInstanceOf(ContractError)
    await expect(api.createAssistedWalletOrder(
      7,
      { items: [{ product_id: 8, experience_option_id: 12, quantity: 1 }], remark: order.remark },
      'assisted-quantity-key',
    )).rejects.toBeInstanceOf(ContractError)
    await expect(api.createAssistedWalletOrder(
      7,
      { items: [{ product_id: 8, experience_option_id: 12, quantity: 2 }], remark: '另一条备注' },
      'assisted-remark-key',
    )).rejects.toBeInstanceOf(ContractError)
  })
})
