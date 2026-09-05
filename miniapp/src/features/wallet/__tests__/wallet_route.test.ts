import {
  buildAdminUserWalletUrl,
  buildAdminWalletOrderUrl,
  parseAdminUserWalletRoute,
  parseAdminWalletOrderRoute,
} from '../wallet_route'

describe('管理用户钱包路由', () => {
  it('只接受正安全整数用户 ID', () => {
    expect(buildAdminUserWalletUrl(7)).toBe('/admin/pages/user-wallet/index?id=7')
    expect(parseAdminUserWalletRoute({ id: '7' })).toEqual({ userId: 7 })
    expect(parseAdminUserWalletRoute({ id: '0' })).toBeUndefined()
    expect(parseAdminUserWalletRoute({ id: '01' })).toBeUndefined()
    expect(parseAdminUserWalletRoute({ id: '1.5' })).toBeUndefined()
    expect(buildAdminWalletOrderUrl(7)).toBe('/admin/pages/wallet-order/index?id=7')
    expect(parseAdminWalletOrderRoute({ id: '7' })).toEqual({ userId: 7 })
  })

  it('构造时拒绝无效 ID', () => {
    expect(() => buildAdminUserWalletUrl(0)).toThrow('正安全整数')
    expect(() => buildAdminWalletOrderUrl(0)).toThrow('正安全整数')
  })
})
