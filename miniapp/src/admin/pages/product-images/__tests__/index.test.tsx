import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { ImagePickerPort } from '@/platform/image_picker'

import AdminProductImagesPage, { AdminProductImageManager } from '../index'

let mockAuth: AuthContextValue
const mockUseAdminProductDetail = jest.fn()
const mockUseAdminProductLifecycleMutation = jest.fn()
const mockUploadProductImage = jest.fn()
const mockUploadOptionImage = jest.fn()
const mockUpdateImage = jest.fn()
const mockDeleteImage = jest.fn()

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
  buildAdminProductDetailUrl: (id: number, type: string) => `/admin/pages/product-detail/index?id=${id}&type=${type}`,
  buildAdminProductImagesUrl: (id: number, type: string) => `/admin/pages/product-images/index?id=${id}&type=${type}`,
  parseAdminProductImagesRoute: () => ({ productId: 7, productType: 'experience' }),
  useAdminProductDetail: (...args: unknown[]) => mockUseAdminProductDetail(...args),
  useAdminProductLifecycleMutation: () => mockUseAdminProductLifecycleMutation(),
}))

jest.mock('@/utils/asset_url', () => ({ resolveAssetUrl: (url: string) => url }))

describe('AdminProductImagesPage', () => {
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
      register: jest.fn(), login: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockUseAdminProductLifecycleMutation.mockReturnValue({
      state: { status: 'idle' },
      uploadProductImage: mockUploadProductImage,
      uploadOptionImage: mockUploadOptionImage,
      updateImage: mockUpdateImage,
      deleteImage: mockDeleteImage,
      onlineProduct: jest.fn(),
      offlineProduct: jest.fn(),
      reset: jest.fn(),
    })
    mockUploadProductImage.mockResolvedValue({ action: 'upload_product_image', image: product().images[0] })
    mockUploadOptionImage.mockResolvedValue({ action: 'upload_option_image', image: product().options[0].images[0] })
    mockUpdateImage.mockResolvedValue({ action: 'update_image', image: product().images[0] })
    mockDeleteImage.mockResolvedValue({ action: 'delete_image', image: { id: 31, is_deleted: true } })
    ;(Taro.showModal as jest.Mock).mockResolvedValue({ confirm: true, cancel: false })
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('普通用户不挂载管理详情或图片 mutation Hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminProductImagesPage)
    expect(requireElement(testUtils, '.admin-product-images-state').textContent).toContain('无管理权限')
    expect(mockUseAdminProductDetail).not.toHaveBeenCalled()
    expect(mockUseAdminProductLifecycleMutation).not.toHaveBeenCalled()
  })

  it('选择公共图/Option 图后调用分型上传，并成功后重载权威详情', async () => {
    const picker: ImagePickerPort = {
      pickOne: jest.fn(async () => ({ filePath: 'wxfile://selected.png', size: 1_024, mediaType: 'image/png' })),
    }
    await testUtils.mount(AdminProductImageManager, { props: { product: product(), picker } })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-images-section__upload-cover'))
    await flush(testUtils)
    expect(mockUploadProductImage).toHaveBeenCalledWith(7, {
      filePath: 'wxfile://selected.png', size: 1_024, mediaType: 'image/png',
    }, true)

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-images-option__upload'))
    await flush(testUtils)
    expect(mockUploadOptionImage).toHaveBeenCalledWith(21, expect.objectContaining({
      filePath: 'wxfile://selected.png',
    }))
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/admin/pages/product-images/index?id=7&type=experience',
    })
  })

  it('公共图可以设为封面，删除前明确确认', async () => {
    await testUtils.mount(AdminProductImageManager, {
      props: { product: product(), picker: { pickOne: jest.fn() } },
    })
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-image-card__cover'))
    await flush(testUtils)
    expect(mockUpdateImage).toHaveBeenCalledWith(31, { is_cover: true })

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-product-image-card__delete'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ title: '确认逻辑删除图片' }))
    expect(mockDeleteImage).toHaveBeenCalledWith(31)
  })

  it('Online 商品只读，不允许上传、排序、设封面或删除', async () => {
    await testUtils.mount(AdminProductImageManager, {
      props: {
        product: { ...product(), status: { value: 'online', label: '已上架' } },
        picker: { pickOne: jest.fn() },
      },
    })
    expect(requireElement(testUtils, '.admin-product-images-summary__boundary').textContent).toContain('先在商品详情下架')
    const buttons = testUtils.queries.querySelectorAll('.admin-product-images-section button')
    buttons.forEach((button) => expect(button.getAttribute('disabled')).not.toBeNull())
  })
})

function product() {
  return {
    id: 7,
    name: '图片体验',
    description: '完整描述',
    product_type: { value: 'experience' as const, label: '拼豆体验' },
    status: { value: 'offline' as const, label: '已下架' },
    images: [{ id: 31, image_url: '/uploads/products/common.png', is_cover: false, sort: 10 }],
    dimensions: {
      durations: [{ value: 60, label: '1 小时' }],
      participants: [{ value: 1, label: '1 人' }],
      day_types: [{ value: 'weekday' as const, label: '工作日' }],
    },
    options: [{
      id: 21,
      duration: { value: 60, label: '1 小时' },
      participants: { value: 1, label: '1 人' },
      day_type: { value: 'weekday' as const, label: '工作日' },
      price: '99.00',
      images: [{ id: 32, image_url: '/uploads/products/option.png', sort: 0 }],
    }],
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
