import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'
import WalletResultPage from '../index'

let mockId = '22'
let mockRole = 'user'
let mockStatus = 'authenticated'
const mockReceipt = jest.fn<null, [unknown]>(() => null)
jest.mock('@tarojs/taro', () => ({
  ...jest.requireActual('@tarojs/taro'),
  useRouter: () => ({ params: { id: mockId } }),
}))
jest.mock('@/auth', () => ({
  useAuth: () => ({ status: mockStatus, user: { id: 7, role: mockRole } }),
  buildLoginUrl: () => '/pages/login/index',
  WALLET_TRANSACTION_LIST_PATH: '/pages/wallet-transactions/index',
}))
jest.mock('@/features/attention', () => ({
  CommerceReceipt: (props: unknown) => mockReceipt(props),
  buildCommerceAttentionUrl: (scope: string) => `/pages/commerce-attention/index?scope=${scope}`,
}))

describe('余额变动详情入口', () => {
  let util: ReactTestUtil
  beforeEach(() => { util = new ReactTestUtil(); mockId = '22'; mockRole = 'user'; mockStatus = 'authenticated'; mockReceipt.mockClear() })
  afterEach(() => util.unmout())

  it('只读取精确事件并保留资金明细与其他结果入口', async () => {
    await util.mount(WalletResultPage)
    expect(mockReceipt).toHaveBeenCalledWith(expect.objectContaining({ scope: 'wallet', target: 22 }))
    const buttons = util.queries.querySelectorAll('.attention-page__all')
    util.fireEvent.click(buttons[0])
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({ url: '/pages/wallet-transactions/index' })
    util.fireEvent.click(buttons[1])
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({ url: '/pages/commerce-attention/index?scope=wallet' })
  })

  it.each(['0', '-1', 'abc', '9007199254740992'])('非法事件编号 %s 不挂载详情', async (value) => {
    mockId = value
    await util.mount(WalletResultPage)
    expect(mockReceipt).not.toHaveBeenCalled()
  })

  it.each(['guest', 'admin'])('%s 不挂载顾客结果', async (value) => {
    if (value === 'guest') mockStatus = 'guest'
    else mockRole = 'admin'
    await util.mount(WalletResultPage)
    expect(mockReceipt).not.toHaveBeenCalled()
  })
})
