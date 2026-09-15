import {
  buildAdminTableSessionUrl,
  buildTableEntryUrl,
  buildTableOrderConfirmUrl,
  parseTableCheckoutIntentId,
  parseTableEntryOrderId,
  parseTableEntryRoute,
  parseTableOrderConfirmRoute,
  parseTableToken,
} from '../table_session_route'

const token = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'
const intentId = 'miniapp-table-checkout-m1234567-1-abcdefghijklmnopqrst'

describe('桌台扫码路由', () => {
  it('接受官方 scene、查询参数和普通二维码占位载荷', () => {
    expect(parseTableEntryRoute({ scene: token })).toBe(token)
    expect(parseTableEntryRoute({ token })).toBe(token)
    expect(parseTableToken(`PINKDOOHUB_TABLE:v1:${token}`)).toBe(token)
    expect(parseTableToken(encodeURIComponent(`PINKDOOHUB_TABLE:v1:${token}`))).toBe(token)
    expect(buildTableEntryUrl(token)).toBe(`/pages/table-entry/index?token=${token}`)
  })

  it('只接受严格正整数的订单聚焦参数', () => {
    expect(buildTableEntryUrl(token, 101)).toBe(
      `/pages/table-entry/index?token=${token}&order_id=101`,
    )
    expect(parseTableEntryOrderId({ order_id: '101' })).toBe(101)
    expect(parseTableEntryOrderId({ order_id: '0' })).toBeUndefined()
    expect(parseTableEntryOrderId({ order_id: '01' })).toBeUndefined()
    expect(parseTableEntryOrderId({ order_id: '9007199254740992' })).toBeUndefined()
    expect(() => buildTableEntryUrl(token, 0)).toThrow('订单标识无效')
  })

  it('用严格意图 ID 绑定本次订单确认页与回桌路由', () => {
    expect(buildTableOrderConfirmUrl(intentId)).toBe(
      `/pages/order-confirm/index?table_intent=${intentId}`,
    )
    expect(parseTableOrderConfirmRoute({ table_intent: intentId })).toBe(intentId)
    expect(parseTableCheckoutIntentId(intentId)).toBe(intentId)
    expect(buildTableEntryUrl(token, 101, intentId)).toBe(
      `/pages/table-entry/index?token=${token}&order_id=101&table_intent=${intentId}`,
    )
    expect(parseTableCheckoutIntentId('invalid')).toBeUndefined()
    expect(() => buildTableOrderConfirmUrl('invalid')).toThrow('桌台结算意图无效')
    expect(() => buildTableEntryUrl(token, undefined, intentId))
      .toThrow('桌台结算意图缺少订单')
  })

  it.each(['short', `${token}!`, token.toLowerCase().slice(0, 31), '%ZZ'])('拒绝错误桌台码：%s', (value) => {
    expect(parseTableToken(value)).toBeUndefined()
  })

  it('构造严格管理员会话地址', () => {
    expect(buildAdminTableSessionUrl(`TS${'1'.repeat(26)}`)).toBe(
      `/admin/pages/table-session-detail/index?session_no=TS${'1'.repeat(26)}`,
    )
    expect(() => buildAdminTableSessionUrl('TS-invalid')).toThrow('桌台会话编号无效')
  })
})
