import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AdminProductConfigurationState } from '@/features/product'

import AdminProductConfigurationPage, {
  AuthenticatedAdminProductConfiguration,
  buildExperienceOptionPatch,
  normalizeExperienceOptionForm,
  validateExperienceOptionForm,
  validatePrice,
} from '../index'

let mockAuth: AuthContextValue
let mutationState: AdminProductConfigurationState
const mockUseDetail = jest.fn()
const mockUseMutation = jest.fn()
const mockCreateOption = jest.fn()
const mockUpdateOption = jest.fn()
const mockDeleteOption = jest.fn()
const mockUpdateKitPrice = jest.fn()

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), redirectTo: jest.fn(), showModal: jest.fn() },
  useRouter: () => ({ params: { id: '7', type: 'experience' } }),
}))

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=admin-products',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product', () => ({
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  buildAdminProductConfigurationUrl: (id: number, type: string) => `/admin/pages/product-configuration/index?id=${id}&type=${type}`,
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
  parseAdminProductConfigurationRoute: () => ({ productId: 7, productType: 'experience' }),
  useAdminProductConfigurationMutation: () => mockUseMutation(),
  useAdminProductDetail: (...args: unknown[]) => mockUseDetail(...args),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminProductConfigurationPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticatedAdmin()
    mutationState = { status: 'idle' }
    mockUseMutation.mockImplementation(() => ({
      state: mutationState,
      createOption: mockCreateOption,
      updateOption: mockUpdateOption,
      deleteOption: mockDeleteOption,
      updateKitPrice: mockUpdateKitPrice,
      reset: jest.fn(),
    }))
    mockCreateOption.mockResolvedValue({ action: 'create_option', option: option() })
    mockUpdateOption.mockResolvedValue({ action: 'update_option', option: baseOption() })
    mockDeleteOption.mockResolvedValue({ action: 'delete_option', option: { id: 21, is_deleted: true } })
    mockUpdateKitPrice.mockResolvedValue({ action: 'update_kit_price', kit: { id: 8, price: '299.00' } })
    ;(Taro.showModal as jest.Mock).mockResolvedValue({ confirm: true, cancel: false })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户在挂载详情和 mutation Hook 前被拒绝', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductConfigurationPage)
    expect(requireElement(testUtils, '.admin-product-form-state').textContent).toContain('无管理权限')
    expect(mockUseDetail).not.toHaveBeenCalled()
    expect(mockUseMutation).not.toHaveBeenCalled()
  })

  it('新增 Option 提交真实四维组合并重新加载权威详情', async () => {
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: experienceProduct() } })
    await testUtils.mount(AuthenticatedAdminProductConfiguration, { props: { productId: 7, productType: 'experience' } })
    const inputs = testUtils.queries.querySelectorAll('.admin-product-form__input')
    input(testUtils, inputs[0], '120')
    input(testUtils, inputs[1], '2')
    input(testUtils, inputs[2], '199.00')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-option-editor__holiday'))
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-option-editor__submit'))
    await flush(testUtils)
    expect(mockCreateOption).toHaveBeenCalledWith(7, {
      duration_minutes: 120, participants: 2, day_type: 'holiday', price: '199.00',
    })
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/admin/pages/product-configuration/index?id=7&type=experience' })
  })

  it('编辑 Option 只 PATCH 实际变化字段', async () => {
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: experienceProduct([option()]) } })
    await testUtils.mount(AuthenticatedAdminProductConfiguration, { props: { productId: 7, productType: 'experience' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-option-card__edit'))
    const inputs = testUtils.queries.querySelectorAll('.admin-product-form__input')
    input(testUtils, inputs[2], '109')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-option-editor__submit'))
    await flush(testUtils)
    expect(mockUpdateOption).toHaveBeenCalledWith(21, { price: '109' })
  })

  it('删除 Option 明示历史快照与恢复原 ID，再发无 body 删除用例', async () => {
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: experienceProduct([option()]) } })
    await testUtils.mount(AuthenticatedAdminProductConfiguration, { props: { productId: 7, productType: 'experience' } })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-option-card__delete'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining('恢复原 Option ID') }))
    expect(mockDeleteOption).toHaveBeenCalledWith(21)
  })

  it('Kit 页面只改价格并明确库存只读', async () => {
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: kitProduct() } })
    await testUtils.mount(AuthenticatedAdminProductConfiguration, { props: { productId: 8, productType: 'kit' } })
    expect(requireElement(testUtils, '.admin-product-configuration-page').textContent).toContain('库存余额 4 只读')
    input(testUtils, requireElement(testUtils, '.admin-product-form__input'), '299.00')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-form__submit'))
    await flush(testUtils)
    expect(mockUpdateKitPrice).toHaveBeenCalledWith(8, '299.00')
  })

  it.each([
    { ...experienceProduct(), status: { value: 'online' as const, label: '已上架' } },
    { ...experienceProduct(), is_deleted: true },
  ])('Online/已删除商品只读并禁用配置写入口：%p', async (product) => {
    mockUseDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product } })
    await testUtils.mount(AuthenticatedAdminProductConfiguration, { props: { productId: 7, productType: 'experience' } })
    expect(requireElement(testUtils, '.admin-product-configuration-summary__boundary')).toBeTruthy()
    expect(testUtils.queries.querySelectorAll('.admin-product-form__input')[0].getAttribute('disabled')).not.toBeNull()
  })
})

describe('Option 与 Kit 价格表单规则', () => {
  it('规范化输入并拒绝非正整数与非法金额', () => {
    const form = normalizeExperienceOptionForm({ durationMinutes: ' 60 ', participants: ' 2 ', dayType: 'weekday', price: ' 99.00 ' })
    expect(form).toEqual({ durationMinutes: '60', participants: '2', dayType: 'weekday', price: '99.00' })
    expect(validateExperienceOptionForm(form)).toBe('')
    expect(validateExperienceOptionForm({ ...form, participants: '1.5' })).toContain('正整数')
    expect(validatePrice('1e2')).toContain('普通数字')
    expect(validatePrice('99999.01')).toContain('不超过')
  })

  it('Option PATCH 保留字段缺失语义，并把 99 与 99.00 视为同价', () => {
    expect(buildExperienceOptionPatch(experienceProduct([option()]), 21, {
      duration_minutes: 60, participants: 1, day_type: 'weekday', price: '99',
    })).toEqual({})
    expect(buildExperienceOptionPatch(experienceProduct([option()]), 21, {
      duration_minutes: 120, participants: 1, day_type: 'weekday', price: '99.00',
    })).toEqual({ duration_minutes: 120 })
  })
})

function experienceProduct(options: ReturnType<typeof option>[] = []) {
  return {
    id: 7, name: '体验草稿', description: null,
    product_type: { value: 'experience' as const, label: '拼豆体验' },
    status: { value: 'draft' as const, label: '草稿' },
    images: [], dimensions: { durations: [], participants: [], day_types: [] }, options,
    created_at: '2026-08-25T07:00:00Z', updated_at: '2026-08-26T08:00:00Z', is_deleted: false,
  }
}

function kitProduct() {
  return {
    id: 8, name: '套装草稿', description: null,
    product_type: { value: 'kit' as const, label: '拼豆套装' },
    status: { value: 'draft' as const, label: '草稿' },
    images: [], price: '199.00', stock: 4,
    created_at: '2026-08-25T07:00:00Z', updated_at: '2026-08-26T08:00:00Z', is_deleted: false,
  }
}

function option() {
  return { ...baseOption(), images: [] }
}

function baseOption() {
  return {
    id: 21,
    duration: { value: 60, label: '1 小时' }, participants: { value: 1, label: '1 人' },
    day_type: { value: 'weekday' as const, label: '工作日' }, price: '99.00',
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
  await testUtils.act(async () => { await Promise.resolve(); await Promise.resolve() })
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
