import { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type {
  FileUploadTransport,
  FileUploadTransportRequest,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '@/api/types'

import {
  AdminProductApi,
  type AdminExperienceProductDetail,
  type AdminKitProductDetail,
  type AdminProductListPage,
} from '../admin_products'

const adminPage: AdminProductListPage = {
  items: [{
    id: 1,
    name: '未配置体验',
    product_type: { value: 'experience', label: '拼豆体验' },
    status: { value: 'draft', label: '草稿' },
    cover_image: null,
    display_price: null,
    updated_at: '2026-08-25T08:00:00Z',
    is_deleted: false,
  }],
  total: 1,
  page: 1,
  page_size: 20,
  pages: 1,
}

const experienceDetail: AdminExperienceProductDetail = {
  id: 1,
  name: '未配置体验',
  description: null,
  product_type: { value: 'experience', label: '拼豆体验' },
  status: { value: 'draft', label: '草稿' },
  images: [],
  dimensions: { durations: [], participants: [], day_types: [] },
  options: [],
  created_at: '2026-08-25T07:00:00Z',
  updated_at: '2026-08-25T08:00:00Z',
  is_deleted: false,
}

const kitDetail: AdminKitProductDetail = {
  id: 2,
  name: '已删除套装',
  description: '保留历史管理快照',
  product_type: { value: 'kit', label: '拼豆套装' },
  status: { value: 'offline', label: '已下架' },
  images: [],
  price: '99.00',
  stock: 0,
  created_at: '2026-08-25T07:00:00+00:00',
  updated_at: '2026-08-25T08:00:00.123456Z',
  is_deleted: true,
}

const experienceCreateResult = {
  id: 11,
  name: '新体验',
  product_type: { value: 'experience' as const, label: '拼豆体验' },
  status: { value: 'draft' as const, label: '草稿' },
}

const kitCreateResult = {
  id: 12,
  name: '新套装',
  product_type: { value: 'kit' as const, label: '拼豆套装' },
  status: { value: 'draft' as const, label: '草稿' },
}

const basicInfoResult = {
  id: 11,
  name: '改名体验',
  description: null,
  updated_at: '2026-08-25T09:00:00Z',
}

const optionResult = {
  id: 21,
  duration: { value: 120, label: '2 小时' },
  participants: { value: 2, label: '2 人' },
  day_type: { value: 'weekday' as const, label: '工作日' },
  price: '199.00',
  images: [],
}

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []
  constructor(private readonly data: unknown) {}
  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return { statusCode: 200, headers: {}, data: { code: 0, message: 'success', data: this.data } }
  }
}

class FakeUploadTransport implements FileUploadTransport {
  readonly requests: FileUploadTransportRequest[] = []
  constructor(private readonly data: unknown) {}
  async upload(request: FileUploadTransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return { statusCode: 201, headers: {}, data: { code: 0, message: 'success', data: this.data } }
  }
}

function createApi(data: unknown): {
  api: AdminProductApi
  transport: FakeTransport
  uploadTransport: FakeUploadTransport
} {
  const transport = new FakeTransport(data)
  const uploadTransport = new FakeUploadTransport(data)
  const client = new ApiClient({
    baseUrl: 'https://api.example.com',
    transport,
    uploadTransport,
    authSession: {
      getAccessToken: () => 'admin-token',
      refreshAccessToken: jest.fn(async () => 'new-token'),
      clearSession: jest.fn(async () => undefined),
    },
  })
  return { api: new AdminProductApi(client), transport, uploadTransport }
}

describe('AdminProductApi', () => {
  it('创建 Experience 时只发送名称和可选描述', async () => {
    const { api, transport } = createApi(experienceCreateResult)
    await expect(api.createExperienceProduct({
      name: '新体验',
      description: '草稿描述',
      unexpected: 'ignored',
    } as never)).resolves.toEqual(experienceCreateResult)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.admin.experience.create',
      method: 'POST',
      url: 'https://api.example.com/api/v1/admin/products/experience',
      headers: {
        Authorization: 'Bearer admin-token',
        'Content-Type': 'application/json',
      },
      body: { name: '新体验', description: '草稿描述' },
    })
  })

  it('创建 Kit 发送价格但绝不投影旧 stock 字段', async () => {
    const { api, transport } = createApi(kitCreateResult)
    await expect(api.createKitProduct({
      name: '新套装',
      price: '99.00',
      stock: 100,
    } as never)).resolves.toEqual(kitCreateResult)
    expect(transport.requests[0].body).toEqual({ name: '新套装', price: '99.00' })
  })

  it('PATCH 只发送明确字段，并在请求前拒绝空 patch', async () => {
    const { api, transport } = createApi(basicInfoResult)
    await expect(api.updateProductBasicInfo(11, { description: null }))
      .resolves.toEqual(basicInfoResult)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.admin.basic_info.update',
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/admin/products/11',
      body: { description: null },
    })
    await expect(api.updateProductBasicInfo(11, {})).rejects.toThrow('至少需要一个改动字段')
    expect(transport.requests).toHaveLength(1)
  })

  it('DELETE 不附带 body，并严格接受 is_deleted=true', async () => {
    const { api, transport } = createApi({ id: 11, is_deleted: true })
    await expect(api.deleteProduct(11)).resolves.toEqual({ id: 11, is_deleted: true })
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.admin.delete',
      method: 'DELETE',
      url: 'https://api.example.com/api/v1/admin/products/11',
    })
    expect(transport.requests[0].body).toBeUndefined()
    await expect(createApi({ id: 11, is_deleted: false }).api.deleteProduct(11))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('Option 新增/恢复只投影四个写字段并严格接收完整 Option', async () => {
    const { api, transport } = createApi(optionResult)
    await expect(api.createExperienceOption(7, {
      duration_minutes: 120,
      participants: 2,
      day_type: 'weekday',
      price: '199.00',
      images: ['ignored'],
    } as never)).resolves.toEqual(optionResult)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.admin.experience_option.create_or_restore',
      method: 'POST',
      url: 'https://api.example.com/api/v1/admin/products/experience/7/options',
      body: { duration_minutes: 120, participants: 2, day_type: 'weekday', price: '199.00' },
    })
  })

  it('Option PATCH 只发送改动字段，DELETE 不带 body', async () => {
    const base = { ...optionResult }
    delete (base as Partial<typeof optionResult>).images
    const update = createApi(base)
    await expect(update.api.updateExperienceOption(21, { price: '229.00' }))
      .resolves.toEqual(base)
    expect(update.transport.requests[0]).toMatchObject({
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/admin/options/21',
      body: { price: '229.00' },
    })
    await expect(update.api.updateExperienceOption(21, {})).rejects.toThrow('至少需要一个改动字段')
    const deletion = createApi({ id: 21, is_deleted: true })
    await expect(deletion.api.deleteExperienceOption(21)).resolves.toEqual({ id: 21, is_deleted: true })
    expect(deletion.transport.requests[0].body).toBeUndefined()
  })

  it('Kit 改价只发送 price，绝不发送库存', async () => {
    const { api, transport } = createApi({ id: 8, price: '299.00' })
    await expect(api.updateKitPrice(8, { price: '299.00', stock: 99 } as never))
      .resolves.toEqual({ id: 8, price: '299.00' })
    expect(transport.requests[0]).toMatchObject({
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/admin/products/kit/8/price',
      body: { price: '299.00' },
    })
  })

  it('Product 公共图片使用 multipart 上传并只发送封面和排序表单', async () => {
    const image = { id: 31, image_url: '/uploads/products/image.webp', is_cover: true, sort: 0 }
    const { api, uploadTransport } = createApi(image)
    await expect(api.uploadProductImage(7, {
      filePath: 'wxfile://selected.webp',
      isCover: true,
      sort: 10,
    })).resolves.toEqual(image)
    expect(uploadTransport.requests[0]).toMatchObject({
      operation: 'products.admin.product_image.upload',
      url: 'https://api.example.com/api/v1/admin/products/7/images',
      filePath: 'wxfile://selected.webp',
      name: 'file',
      headers: { Authorization: 'Bearer admin-token' },
      formData: { is_cover: 'true', sort: '10' },
    })
  })

  it('Option 图片上传不发送 is_cover，并严格接受无封面字段响应', async () => {
    const image = { id: 32, image_url: '/uploads/products/option.png', sort: 0 }
    const { api, uploadTransport } = createApi(image)
    await expect(api.uploadOptionImage(21, { filePath: 'wxfile://option.png' }))
      .resolves.toEqual(image)
    expect(uploadTransport.requests[0].formData).toEqual({ sort: '0' })
    await expect(createApi({ ...image, is_cover: false }).api.uploadOptionImage(21, {
      filePath: 'wxfile://option.png',
    })).resolves.toEqual(image)
  })

  it('图片 PATCH 只发送 sort/is_cover，DELETE 无 body', async () => {
    const updated = createApi({
      id: 31, image_url: '/uploads/products/image.webp', is_cover: true, sort: 20,
    })
    await expect(updated.api.updateProductImage(31, {
      sort: 20,
      is_cover: true,
      unexpected: 'ignored',
    } as never)).resolves.toEqual({
      id: 31, image_url: '/uploads/products/image.webp', is_cover: true, sort: 20,
    })
    expect(updated.transport.requests[0]).toMatchObject({
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/admin/product-images/31',
      body: { sort: 20, is_cover: true },
    })
    await expect(updated.api.updateProductImage(31, {})).rejects.toThrow('至少需要一个')

    const deletion = createApi({ id: 31, is_deleted: true })
    await expect(deletion.api.deleteProductImage(31)).resolves.toEqual({ id: 31, is_deleted: true })
    expect(deletion.transport.requests[0]).toMatchObject({ method: 'DELETE' })
    expect(deletion.transport.requests[0].body).toBeUndefined()
  })

  it('上下架使用 empty-body PATCH，并严格校验目标状态', async () => {
    const online = createApi({ id: 7, status: { value: 'online', label: '已上架' } })
    await expect(online.api.onlineProduct(7)).resolves.toEqual({
      id: 7, status: { value: 'online', label: '已上架' },
    })
    expect(online.transport.requests[0]).toMatchObject({
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/admin/products/7/online',
    })
    expect(online.transport.requests[0].body).toBeUndefined()

    const offline = createApi({ id: 7, status: { value: 'offline', label: '已下架' } })
    await expect(offline.api.offlineProduct(7)).resolves.toEqual({
      id: 7, status: { value: 'offline', label: '已下架' },
    })
    expect(offline.transport.requests[0].body).toBeUndefined()
    await expect(createApi({ id: 7, status: { value: 'draft', label: '草稿' } }).api.onlineProduct(7))
      .rejects.toBeInstanceOf(ContractError)
  })

  it.each([
    { ...optionResult, price: '199' },
    { ...optionResult, images: [{ id: 1, image_url: 'javascript:bad', sort: 0 }] },
  ])('拒绝不符合 Option mutation 契约的数据：%p', async (data) => {
    await expect(createApi(data).api.createExperienceOption(7, {
      duration_minutes: 120, participants: 2, day_type: 'weekday', price: '199.00',
    })).rejects.toBeInstanceOf(ContractError)
  })

  it('只投影管理列表白名单 Query 并要求 Bearer', async () => {
    const { api, transport } = createApi(adminPage)
    await expect(api.listProducts({
      page: 1,
      page_size: 20,
      product_type: 'experience',
      status: 'draft',
      keyword: ' 未配置 ',
      include_deleted: true,
    })).resolves.toEqual(adminPage)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.admin.list',
      method: 'GET',
      url: 'https://api.example.com/api/v1/admin/products?page=1&page_size=20&product_type=experience&status=draft&keyword=%20%E6%9C%AA%E9%85%8D%E7%BD%AE%20&include_deleted=true',
      headers: { Authorization: 'Bearer admin-token' },
    })
  })

  it('接受管理草稿的空封面、空价格和空 Option', async () => {
    const { api } = createApi(adminPage)
    await expect(api.listProducts()).resolves.toEqual(adminPage)
    const detailApi = createApi(experienceDetail).api
    await expect(detailApi.getExperienceProduct(1)).resolves.toEqual(experienceDetail)
  })

  it('读取包含逻辑删除标记和零库存的 Kit 管理详情', async () => {
    const { api, transport } = createApi(kitDetail)
    await expect(api.getKitProduct(2)).resolves.toEqual(kitDetail)
    expect(transport.requests[0].url).toBe('https://api.example.com/api/v1/admin/products/kit/2')
  })

  it.each([
    { ...adminPage, items: [{ ...adminPage.items[0], status: { value: 'unknown', label: '未知' } }] },
    { ...adminPage, items: [{ ...adminPage.items[0], updated_at: '2026-08-25' }] },
    { ...adminPage, items: [{ ...adminPage.items[0], display_price: '0.00' }] },
  ])('拒绝不符合管理列表契约的数据：%p', async (data) => {
    await expect(createApi(data).api.listProducts()).rejects.toBeInstanceOf(ContractError)
  })

  it.each([
    { ...experienceDetail, product_type: { value: 'kit', label: '拼豆套装' } },
    { ...experienceDetail, dimensions: { durations: [{ value: 60, label: '1小时' }], participants: [], day_types: [] } },
    { ...kitDetail, stock: 1_000_000 },
    { ...kitDetail, price: '99' },
  ])('拒绝不符合管理详情契约的数据：%p', async (data) => {
    const api = createApi(data).api
    const promise = 'stock' in data ? api.getKitProduct(2) : api.getExperienceProduct(1)
    await expect(promise).rejects.toBeInstanceOf(ContractError)
  })

  it('在发请求前拒绝非法 Product ID', async () => {
    await expect(createApi(kitDetail).api.getKitProduct(0)).rejects.toThrow('正安全整数')
    await expect(createApi(basicInfoResult).api.updateProductBasicInfo(0, { name: '商品' }))
      .rejects.toThrow('正安全整数')
    await expect(createApi({ id: 1, is_deleted: true }).api.deleteProduct(0))
      .rejects.toThrow('正安全整数')
  })

  it.each([
    { ...experienceCreateResult, status: { value: 'online', label: '已上架' } },
    { ...kitCreateResult, product_type: { value: 'experience', label: '拼豆体验' } },
    { ...basicInfoResult, updated_at: '2026-08-25' },
  ])('拒绝不符合 mutation 成功响应契约的数据：%p', async (data) => {
    const api = createApi(data).api
    const promise = 'updated_at' in data
      ? api.updateProductBasicInfo(1, { name: '商品' })
      : data.name === '新套装'
        ? api.createKitProduct({ name: '新套装', price: '99.00' })
        : api.createExperienceProduct({ name: '新体验' })
    await expect(promise).rejects.toBeInstanceOf(ContractError)
  })
})
