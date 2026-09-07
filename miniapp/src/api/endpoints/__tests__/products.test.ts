import { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { HttpTransport, TransportRequest, TransportResponse } from '@/api/types'

import {
  ProductApi,
  type ExperienceProductDetail,
  type KitProductDetail,
  type ProductListPage,
} from '../products'

const productPage: ProductListPage = {
  items: [
    {
      id: 1,
      name: '周末拼豆体验',
      product_type: { value: 'experience', label: '拼豆体验' },
      cover_image: '/uploads/products/experience.webp',
      display_price: '299.00',
      kit_kind: null,
      sale_unit_grams: null,
    },
    {
      id: 2,
      name: '基础拼豆套装',
      product_type: { value: 'kit', label: '拼豆套装' },
      cover_image: 'https://cdn.example.com/kit.webp',
      display_price: '599.00',
      kit_kind: { value: 'fixed', label: '固定套装' },
      sale_unit_grams: null,
    },
  ],
  total: 12,
  page: 1,
  page_size: 10,
  pages: 2,
}

const experienceDetail: ExperienceProductDetail = {
  id: 1,
  name: '周末拼豆体验',
  product_type: { value: 'experience', label: '拼豆体验' },
  description: '选择一个服务端有效组合',
  dimensions: {
    durations: [{ value: 60, label: '1小时' }],
    participants: [{ value: 2, label: '2人' }],
    day_types: [{ value: 'weekday', label: '工作日' }],
  },
  options: [{
    id: 11,
    duration: { value: 60, label: '1小时' },
    participants: { value: 2, label: '2人' },
    day_type: { value: 'weekday', label: '工作日' },
    price: '299.00',
    images: [{ id: 21, image_url: '/uploads/products/option.png', sort: 0 }],
  }],
  images: [{ id: 20, image_url: '/uploads/products/cover.png', is_cover: true, sort: 0 }],
}

const kitDetail: KitProductDetail = {
  id: 2,
  name: '基础拼豆套装',
  product_type: { value: 'kit', label: '拼豆套装' },
  description: '新手套装',
  images: [{ id: 22, image_url: '/uploads/products/kit.png', is_cover: true, sort: 0 }],
  kit_kind: { value: 'fixed', label: '固定套装' },
  sale_unit_grams: null,
  price: '599.00',
  stock: 3,
  available: true,
  colors: [],
}

const colorSelectableKitDetail: KitProductDetail = {
  id: 3,
  name: '自选颜色拼豆',
  product_type: { value: 'kit', label: '拼豆套装' },
  description: '每色按 10g 选择',
  images: [{ id: 23, image_url: '/uploads/products/colors.png', is_cover: true, sort: 0 }],
  kit_kind: { value: 'color_selectable', label: '自选颜色' },
  sale_unit_grams: 10,
  price: '9.90',
  stock: null,
  available: true,
  colors: [{
    id: 301,
    bead_color_id: 1,
    slot_no: 1,
    color_code: 'A01',
    name: '正红',
    swatch_image_url: '/uploads/bead-colors/a01.webp',
    available: true,
  }],
}

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(private readonly data: unknown) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return {
      statusCode: 200,
      headers: {},
      data: { code: 0, message: 'success', data: this.data },
    }
  }
}

describe('ProductApi', () => {
  it('只发送公开列表允许的查询参数且不携带认证头', async () => {
    const transport = new FakeTransport(productPage)
    const api = new ProductApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
    }))

    await expect(api.listProducts({
      page: 1,
      page_size: 10,
      product_type: 'experience',
      keyword: '周末 拼豆',
    })).resolves.toEqual(productPage)

    expect(transport.requests[0]).toMatchObject({
      operation: 'products.list',
      method: 'GET',
      url: 'https://api.example.com/api/v1/products?page=1&page_size=10&product_type=experience&keyword=%E5%91%A8%E6%9C%AB%20%E6%8B%BC%E8%B1%86',
    })
    expect(transport.requests[0].headers).not.toHaveProperty('Authorization')
  })

  it.each([
    [{ ...productPage, page: 0 }],
    [{ ...productPage, items: [{ ...productPage.items[0], id: -1 }] }],
    [{ ...productPage, items: [{ ...productPage.items[0], display_price: '299' }] }],
    [{ ...productPage, items: [{ ...productPage.items[0], cover_image: 'uploads/file.webp' }] }],
    [{ ...productPage, items: [{ ...productPage.items[0], product_type: { value: 'unknown', label: '未知' } }] }],
    [{ ...productPage, items: [{
      ...productPage.items[0],
      kit_kind: { value: 'fixed', label: '固定套装' },
    }] }],
    [{ ...productPage, items: [{
      ...productPage.items[1],
      kit_kind: { value: 'color_selectable', label: '自选颜色' },
      sale_unit_grams: null,
    }] }],
  ])('拒绝不符合 Product 列表契约的数据：%p', async (data) => {
    const api = new ProductApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: new FakeTransport(data),
    }))

    await expect(api.listProducts()).rejects.toBeInstanceOf(ContractError)
  })

  it('允许合法的空分页结果', async () => {
    const emptyPage: ProductListPage = {
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
      pages: 0,
    }
    const api = new ProductApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: new FakeTransport(emptyPage),
    }))

    await expect(api.listProducts()).resolves.toEqual(emptyPage)
  })

  it('请求公开 Experience 详情并保持无认证', async () => {
    const transport = new FakeTransport(experienceDetail)
    const api = new ProductApi(new ApiClient({ baseUrl: 'https://api.example.com', transport }))

    await expect(api.getExperienceProduct({ productId: 1 })).resolves.toEqual(experienceDetail)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.experience.detail',
      method: 'GET',
      url: 'https://api.example.com/api/v1/products/experience/1',
    })
    expect(transport.requests[0].headers).not.toHaveProperty('Authorization')
  })

  it('请求公开 Kit 详情并保持无认证', async () => {
    const transport = new FakeTransport(kitDetail)
    const api = new ProductApi(new ApiClient({ baseUrl: 'https://api.example.com', transport }))

    await expect(api.getKitProduct({ productId: 2 })).resolves.toEqual(kitDetail)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.kit.detail',
      method: 'GET',
      url: 'https://api.example.com/api/v1/products/kit/2',
    })
    expect(transport.requests[0].headers).not.toHaveProperty('Authorization')
  })

  it('解析自选颜色 Kit 的 10g 单位和可售颜色，但不透出精确颜色库存', async () => {
    const response = {
      ...colorSelectableKitDetail,
      colors: [{ ...colorSelectableKitDetail.colors[0], stock_units: 17 }],
    }
    const transport = new FakeTransport(response)
    const api = new ProductApi(new ApiClient({ baseUrl: 'https://api.example.com', transport }))

    await expect(api.getKitProduct({ productId: 3 })).resolves.toEqual(colorSelectableKitDetail)
    expect(transport.requests[0]).toMatchObject({
      operation: 'products.kit.detail',
      url: 'https://api.example.com/api/v1/products/kit/3',
    })
  })

  it.each<[unknown, 'experience' | 'kit']>([
    [{ ...experienceDetail, product_type: { value: 'kit', label: '拼豆套装' } }, 'experience'],
    [{ ...experienceDetail, options: [{ ...experienceDetail.options[0], images: [] }] }, 'experience'],
    [{ ...experienceDetail, dimensions: { ...experienceDetail.dimensions, durations: [{ value: 120, label: '2小时' }] } }, 'experience'],
    [{ ...kitDetail, images: [{ ...kitDetail.images[0], is_cover: false }] }, 'kit'],
    [{ ...kitDetail, price: '599' }, 'kit'],
    [{ ...kitDetail, available: false }, 'kit'],
    [{ ...kitDetail, stock: -1 }, 'kit'],
    [{ ...kitDetail, stock: 1_000_000 }, 'kit'],
    [{ ...kitDetail, sale_unit_grams: 10 }, 'kit'],
    [{ ...kitDetail, colors: colorSelectableKitDetail.colors }, 'kit'],
    [{ ...colorSelectableKitDetail, stock: 0 }, 'kit'],
    [{ ...colorSelectableKitDetail, sale_unit_grams: null }, 'kit'],
    [{ ...colorSelectableKitDetail, colors: [] }, 'kit'],
    [{ ...colorSelectableKitDetail, available: false }, 'kit'],
    [{
      ...colorSelectableKitDetail,
      colors: [{ ...colorSelectableKitDetail.colors[0], slot_no: 222 }],
    }, 'kit'],
  ])('拒绝不符合 Product 详情契约的数据：%p', async (data, type) => {
    const api = new ProductApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: new FakeTransport(data),
    }))

    const promise = type === 'experience'
      ? api.getExperienceProduct({ productId: 1 })
      : api.getKitProduct({ productId: 2 })
    await expect(promise).rejects.toBeInstanceOf(ContractError)
  })
})
