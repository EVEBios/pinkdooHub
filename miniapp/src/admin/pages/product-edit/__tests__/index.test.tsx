import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import AdminProductEditPage, {
  AuthenticatedAdminProductEdit,
  buildProductBasicInfoPatch,
  normalizeAdminProductEditForm,
  validateAdminProductEditForm,
} from '../index'

let mockAuth: AuthContextValue
const mockUseDetail = jest.fn()
const mockUseMutation = jest.fn()
const mockUpdate = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), redirectTo: jest.fn() },
  useRouter: () => ({ params: { id: '7', type: 'experience' } }),
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=admin-products',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
  parseAdminProductEditRoute: () => ({ productId: 7, productType: 'experience' }),
  useAdminProductDetail: (...args: unknown[]) => mockUseDetail(...args),
  useAdminProductMutation: () => mockUseMutation(),
}))

describe('AdminProductEditPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticatedAdmin()
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: draftProduct() } })
    mockUseMutation.mockReturnValue({
      state: { status: 'idle' },
      updateBasicInfo: mockUpdate,
      createExperience: jest.fn(), createKit: jest.fn(), deleteProduct: jest.fn(), reset: jest.fn(),
    })
    mockUpdate.mockResolvedValue({
      action: 'update_basic_info',
      product: {
        id: 7, name: '草稿体验', description: null, updated_at: '2026-08-25T09:00:00Z',
      },
    })
  })

  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载详情或 mutation Hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductEditPage)
    expect(requireElement(testUtils, '.admin-product-form-state').textContent).toContain('无管理权限')
    expect(mockUseDetail).not.toHaveBeenCalled()
    expect(mockUseMutation).not.toHaveBeenCalled()
  })

  it('清空描述时只发送 description:null，并返回权威详情', async () => {
    await testUtils.mount(AuthenticatedAdminProductEdit, {
      props: { productId: 7, productType: 'experience' },
    })
    input(testUtils, requireElement(testUtils, '.admin-product-form__textarea'), '   ')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-form__submit'))
    await flush(testUtils)
    expect(mockUpdate).toHaveBeenCalledWith(7, { description: null })
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-detail/index?id=7&type=experience',
    })
  })

  it('没有差异时在客户端阻止空 PATCH', async () => {
    await testUtils.mount(AuthenticatedAdminProductEdit, {
      props: { productId: 7, productType: 'experience' },
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-form__submit'))
    expect(mockUpdate).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.admin-product-form__error').textContent).toContain('没有需要保存')
  })

  it('Online 商品显示边界并禁用保存', async () => {
    mockUseDetail.mockReturnValue({
      retry: jest.fn(),
      state: {
        status: 'content',
        product: { ...draftProduct(), status: { value: 'online', label: '已上架' } },
      },
    })
    await testUtils.mount(AuthenticatedAdminProductEdit, {
      props: { productId: 7, productType: 'experience' },
    })
    expect(requireElement(testUtils, '.admin-product-form-page').textContent).toContain('不能编辑')
    expect(requireElement(testUtils, '.admin-product-form__submit').getAttribute('disabled')).not.toBeNull()
  })
})

describe('基本信息 PATCH 差异', () => {
  const product = { name: '原名称', description: '原描述' }

  it('区分缺失与显式清空', () => {
    expect(buildProductBasicInfoPatch(product, { name: '原名称', description: '原描述' }))
      .toEqual({})
    expect(buildProductBasicInfoPatch(product, { name: '新名称', description: '原描述' }))
      .toEqual({ name: '新名称' })
    expect(buildProductBasicInfoPatch(product, { name: '原名称', description: '' }))
      .toEqual({ description: null })
  })

  it('规范化首尾空白并校验名称', () => {
    expect(normalizeAdminProductEditForm({ name: ' 新名称 ', description: ' 新描述 ' }))
      .toEqual({ name: '新名称', description: '新描述' })
    expect(validateAdminProductEditForm({ name: '', description: '' })).toBe('请输入商品名称')
  })
})

function draftProduct() {
  return {
    id: 7,
    name: '草稿体验',
    description: '原描述',
    product_type: { value: 'experience' as const, label: '拼豆体验' },
    status: { value: 'draft' as const, label: '草稿' },
    images: [],
    dimensions: { durations: [], participants: [], day_types: [] },
    options: [],
    created_at: '2026-08-25T07:00:00Z',
    updated_at: '2026-08-25T08:00:00Z',
    is_deleted: false,
  }
}

function authenticatedAdmin(): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
      role: 'admin', status: 'normal', last_login_at: null,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    },
    register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
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
