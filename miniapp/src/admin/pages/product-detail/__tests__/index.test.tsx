import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import AdminProductDetailPage, { AuthenticatedAdminProductDetail } from '../index'

let mockAuth: AuthContextValue
const mockUseAdminProductDetail = jest.fn()
const mockUseAdminProductMutation = jest.fn()
const mockUseAdminProductLifecycleMutation = jest.fn()
const mockDeleteProduct = jest.fn()
const mockOnlineProduct = jest.fn()
const mockOfflineProduct = jest.fn()

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
  buildAdminProductEditUrl: (id: number, type: string) => `/admin/pages/product-edit/index?id=${id}&type=${type}`,
  buildAdminProductConfigurationUrl: (id: number, type: string) => `/admin/pages/product-configuration/index?id=${id}&type=${type}`,
  buildAdminProductImagesUrl: (id: number, type: string) => `/admin/pages/product-images/index?id=${id}&type=${type}`,
  parseAdminProductDetailRoute: () => ({ productId: 7, productType: 'experience' }),
  translateReadinessIssue: (issue: string) => `translated:${issue}`,
  useAdminProductDetail: (...args: unknown[]) => mockUseAdminProductDetail(...args),
  useAdminProductLifecycleMutation: () => mockUseAdminProductLifecycleMutation(),
  useAdminProductMutation: () => mockUseAdminProductMutation(),
}))

jest.mock('@/features/inventory', () => ({
  buildKitInventoryUrl: (id: number) => `/admin/pages/product-inventory/index?id=${id}`,
}))

jest.mock('@/utils/asset_url', () => ({ resolveAssetUrl: (url: string) => url }))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminProductDetailPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2, username: 'admin', nickname: '管理员', avatar: null, phone: '13800000000',
        role: 'admin', status: 'normal', last_login_at: null,
        created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      },
      register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockUseAdminProductMutation.mockReturnValue({
      state: { status: 'idle' },
      deleteProduct: mockDeleteProduct,
      createExperience: jest.fn(), createKit: jest.fn(), updateBasicInfo: jest.fn(), reset: jest.fn(),
    })
    mockDeleteProduct.mockResolvedValue({ action: 'delete', product: { id: 7, is_deleted: true } })
    mockOnlineProduct.mockResolvedValue({
      action: 'online', product: { id: 7, status: { value: 'online', label: '已上架' } },
    })
    mockOfflineProduct.mockResolvedValue({
      action: 'offline', product: { id: 7, status: { value: 'offline', label: '已下架' } },
    })
    mockUseAdminProductLifecycleMutation.mockReturnValue({
      state: { status: 'idle' },
      uploadProductImage: jest.fn(), uploadOptionImage: jest.fn(), updateImage: jest.fn(),
      deleteImage: jest.fn(), onlineProduct: mockOnlineProduct, offlineProduct: mockOfflineProduct,
      reset: jest.fn(),
    })
    ;(Taro.showModal as jest.Mock).mockResolvedValue({ confirm: true, cancel: false })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载详情 Hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductDetailPage)
    expect(testUtils.queries.querySelector('.admin-product-detail-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminProductDetail).not.toHaveBeenCalled()
  })

  it('展示允许空图片与空 Option 的 Experience 草稿', async () => {
    mockUseAdminProductDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: draftProduct() } })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    expect(testUtils.queries.querySelector('.admin-product-detail-page')?.textContent).toContain('暂无商品描述')
    expect(testUtils.queries.querySelector('.admin-product-detail-page')?.textContent).toContain('尚未配置 Experience Option')
  })

  it('从详情进入编辑，并在确认后逻辑删除再返回列表', async () => {
    mockUseAdminProductDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: draftProduct() } })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    const editButton = requireElement(testUtils, '.admin-product-detail-actions__edit')
    const deleteButton = requireElement(testUtils, '.admin-product-detail-actions__delete')
    testUtils.fireEvent.click(editButton)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-edit/index?id=7&type=experience',
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__configuration'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-configuration/index?id=7&type=experience',
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__images'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-images/index?id=7&type=experience',
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__audit'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-audit/index?id=7&type=experience',
    })
    testUtils.fireEvent.click(deleteButton)
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ title: '确认逻辑删除' }))
    expect(mockDeleteProduct).toHaveBeenCalledWith(7)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/admin/pages/products/index' })
  })

  it('Draft 上架与 Online 下架均先确认，成功后重读权威详情', async () => {
    const retry = jest.fn()
    mockUseAdminProductDetail.mockReturnValue({ retry, state: { status: 'content', product: draftProduct() } })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__status'))
    await flush(testUtils)
    expect(mockOnlineProduct).toHaveBeenCalledWith(7)
    expect(retry).toHaveBeenCalledTimes(1)

    testUtils.unmout()
    testUtils = new ReactTestUtil()
    mockUseAdminProductDetail.mockReturnValue({
      retry,
      state: {
        status: 'content',
        product: { ...draftProduct(), status: { value: 'online', label: '已上架' } },
      },
    })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__status'))
    await flush(testUtils)
    expect(mockOfflineProduct).toHaveBeenCalledWith(7)
  })

  it('Kit 无论 Online 或 Draft 都提供库存管理入口，Experience 不提供', async () => {
    mockUseAdminProductDetail.mockReturnValue({
      retry: jest.fn(), state: { status: 'content', product: kitProduct() },
    })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'kit' },
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-detail-actions__inventory'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-inventory/index?id=7',
    })

    testUtils.unmout()
    testUtils = new ReactTestUtil()
    mockUseAdminProductDetail.mockReturnValue({
      retry: jest.fn(), state: { status: 'content', product: draftProduct() },
    })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    expect(testUtils.queries.querySelector('.admin-product-detail-actions__inventory')).toBeNull()
  })

  it('一次展示服务端返回的全部 readiness issues', async () => {
    mockUseAdminProductDetail.mockReturnValue({ retry: jest.fn(), state: { status: 'content', product: draftProduct() } })
    mockUseAdminProductLifecycleMutation.mockReturnValue({
      state: {
        status: 'failed',
        action: 'online',
        errorMessage: '商品尚未满足上架条件，请一次补齐以下项目',
        readinessIssues: ['product description is required', 'option 21 has no image'],
      },
      onlineProduct: mockOnlineProduct, offlineProduct: mockOfflineProduct, reset: jest.fn(),
    })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    const issues = requireElement(testUtils, '.admin-product-detail-readiness-issues')
    expect(issues.textContent).toContain('translated:product description is required')
    expect(issues.textContent).toContain('translated:option 21 has no image')
  })

  it.each([
    { status: { value: 'online', label: '已上架' }, is_deleted: false, message: '必须先下架' },
    { status: { value: 'draft', label: '草稿' }, is_deleted: true, message: '不提供编辑' },
  ])('对 Online/已删除商品禁用 mutation：%p', async ({ status, is_deleted, message }) => {
    mockUseAdminProductDetail.mockReturnValue({
      retry: jest.fn(),
      state: { status: 'content', product: { ...draftProduct(), status, is_deleted } },
    })
    await testUtils.mount(AuthenticatedAdminProductDetail, {
      props: { productId: 7, productType: 'experience' },
    })
    const page = requireElement(testUtils, '.admin-product-detail-page')
    expect(page.textContent).toContain(message)
    expect(requireElement(testUtils, '.admin-product-detail-actions__edit').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-product-detail-actions__delete').getAttribute('disabled')).not.toBeNull()
  })
})

function draftProduct() {
  return {
    id: 7,
    name: '草稿体验',
    description: null,
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

function kitProduct() {
  return {
    id: 7,
    name: '在线套装',
    description: null,
    product_type: { value: 'kit' as const, label: '拼豆套装' },
    status: { value: 'online' as const, label: '已上架' },
    images: [],
    price: '99.00',
    stock: 10,
    created_at: '2026-08-25T07:00:00Z',
    updated_at: '2026-08-25T08:00:00Z',
    is_deleted: false,
  }
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
