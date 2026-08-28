import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AdminProductMutationState } from '@/features/product'

import AdminProductCreatePage, {
  AuthenticatedAdminProductCreate,
  normalizeAdminProductCreateForm,
  validateAdminProductCreateForm,
} from '../index'

let mockAuth: AuthContextValue
let mutationState: AdminProductMutationState
const mockUseMutation = jest.fn()
const mockCreateExperience = jest.fn()
const mockCreateKit = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), redirectTo: jest.fn() },
  useRouter: () => ({ params: { type: 'experience' } }),
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=admin-products',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
  parseAdminProductCreateRoute: () => ({ productType: 'experience' }),
  useAdminProductMutation: () => mockUseMutation(),
}))

describe('AdminProductCreatePage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticatedAdmin()
    mutationState = { status: 'idle' }
    mockUseMutation.mockImplementation(() => ({
      state: mutationState,
      createExperience: mockCreateExperience,
      createKit: mockCreateKit,
      updateBasicInfo: jest.fn(), deleteProduct: jest.fn(), reset: jest.fn(),
    }))
    mockCreateExperience.mockResolvedValue({
      action: 'create_experience',
      product: {
        id: 21, name: '新体验',
        product_type: { value: 'experience', label: '拼豆体验' },
        status: { value: 'draft', label: '草稿' },
      },
    })
    mockCreateKit.mockResolvedValue({
      action: 'create_kit',
      product: {
        id: 22, name: '新套装',
        product_type: { value: 'kit', label: '拼豆套装' },
        status: { value: 'draft', label: '草稿' },
      },
    })
  })

  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户在挂载 mutation Hook 前被拒绝', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductCreatePage)
    expect(requireElement(testUtils, '.admin-product-form-state').textContent).toContain('无管理权限')
    expect(mockUseMutation).not.toHaveBeenCalled()
  })

  it('Experience 只提交规范化名称，空描述不进入请求', async () => {
    await testUtils.mount(AuthenticatedAdminProductCreate, { props: { productType: 'experience' } })
    const inputs = testUtils.queries.querySelectorAll('.admin-product-form__input')
    expect(inputs).toHaveLength(1)
    input(testUtils, inputs[0], '  新体验  ')
    input(testUtils, requireElement(testUtils, '.admin-product-form__textarea'), '   ')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-form__submit'))
    await flush(testUtils)
    expect(mockCreateExperience).toHaveBeenCalledWith({ name: '新体验' })
    expect(mockCreateKit).not.toHaveBeenCalled()
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-detail/index?id=21&type=experience',
    })
  })

  it('Kit 提交价格但表单不存在库存字段', async () => {
    await testUtils.mount(AuthenticatedAdminProductCreate, { props: { productType: 'kit' } })
    const inputs = testUtils.queries.querySelectorAll('.admin-product-form__input')
    expect(inputs).toHaveLength(2)
    input(testUtils, inputs[0], '新套装')
    input(testUtils, inputs[1], '99.00')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-form__submit'))
    await flush(testUtils)
    expect(mockCreateKit).toHaveBeenCalledWith({ name: '新套装', price: '99.00' })
    expect(requireElement(testUtils, '.admin-product-form-page').textContent).toContain('库存固定从 0 开始')
  })

  it('unknown 禁止再次创建并提供列表核对入口', async () => {
    mutationState = {
      status: 'unknown', action: 'create_experience',
      errorMessage: '创建商品结果可能未知，系统不会自动重试',
    }
    await testUtils.mount(AuthenticatedAdminProductCreate, { props: { productType: 'experience' } })
    expect(requireElement(testUtils, '.admin-product-form-page').textContent).toContain('不会自动重试')
    expect(requireElement(testUtils, '.admin-product-form__submit').getAttribute('disabled')).not.toBeNull()
  })
})

describe('创建表单规则', () => {
  it('只规范化文本，不把 Experience 强行要求价格', () => {
    const form = normalizeAdminProductCreateForm({
      name: ' 商品 ', description: ' 描述 ', price: ' 99.00 ',
    })
    expect(form).toEqual({ name: '商品', description: '描述', price: '99.00' })
    expect(validateAdminProductCreateForm('experience', { ...form, price: '' })).toBe('')
  })

  it.each([
    [{ name: '', description: '', price: '99.00' }, '请输入商品名称'],
    [{ name: '套装', description: '', price: '' }, '请输入套装价格'],
    [{ name: '套装', description: '', price: '1.234' }, '最多两位小数'],
    [{ name: '套装', description: '', price: '0' }, '必须大于 0'],
    [{ name: '套装', description: '', price: '99999.01' }, '不超过 99999'],
  ])('拒绝非法 Kit 表单 %#', (form, message) => {
    expect(validateAdminProductCreateForm('kit', form)).toContain(message)
  })
})

function authenticatedAdmin(): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
      role: 'admin', status: 'normal', last_login_at: null,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    },
    register: jest.fn(), login: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
  }
}

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
