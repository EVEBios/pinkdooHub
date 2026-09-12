import {
  buildAdminTableSessionUrl,
  buildTableEntryUrl,
  parseTableEntryRoute,
  parseTableToken,
} from '../table_session_route'

const token = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'

describe('桌台扫码路由', () => {
  it('接受官方 scene、查询参数和普通二维码占位载荷', () => {
    expect(parseTableEntryRoute({ scene: token })).toBe(token)
    expect(parseTableEntryRoute({ token })).toBe(token)
    expect(parseTableToken(`PINKDOOHUB_TABLE:v1:${token}`)).toBe(token)
    expect(parseTableToken(encodeURIComponent(`PINKDOOHUB_TABLE:v1:${token}`))).toBe(token)
    expect(buildTableEntryUrl(token)).toBe(`/pages/table-entry/index?token=${token}`)
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
