import type {
  ExperienceProductDetail,
  KitProductDetail,
} from '@/api/endpoints/products'

import {
  buildColorKitCartItem,
  buildExperienceCartItem,
  buildKitCartItem,
} from '../cart_item'

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
  price: '599.00',
  stock: 3,
  available: true,
  kit_kind: { value: 'fixed', label: '固定套装' },
  sale_unit_grams: null,
  colors: [],
}

const colorKitDetail: KitProductDetail = {
  ...kitDetail,
  id: 3,
  name: '自选颜色拼豆',
  price: '2.50',
  stock: null,
  kit_kind: { value: 'color_selectable', label: '自选颜色' },
  sale_unit_grams: 10,
  colors: [{
    id: 31,
    bead_color_id: 301,
    slot_no: 1,
    color_code: 'A01',
    name: '白色',
    swatch_image_url: '/uploads/bead-colors/a01.webp',
    available: true,
  }],
}

describe('Product detail → CartItem', () => {
  it('Experience 保存服务端真实 Option ID、组合说明和 Option 图片', () => {
    expect(buildExperienceCartItem(experienceDetail, experienceDetail.options[0])).toEqual({
      productId: 1,
      experienceOptionId: 11,
      kitColorId: null,
      productType: 'experience',
      productName: '周末拼豆体验',
      configurationLabel: '1小时 · 2人 · 工作日',
      unitPrice: '299.00',
      imageUrl: '/uploads/products/option.png',
      quantity: 1,
    })
  })

  it('拒绝把其他 Product 的 Option 塞进当前 Experience', () => {
    const foreignOption = { ...experienceDetail.options[0], id: 999 }

    expect(() => buildExperienceCartItem(experienceDetail, foreignOption))
      .toThrow('所选体验配置不属于当前商品')
  })

  it('Kit 明确保存 null Option，并且价格只是本地预览字段', () => {
    expect(buildKitCartItem(kitDetail)).toEqual({
      productId: 2,
      experienceOptionId: null,
      kitColorId: null,
      productType: 'kit',
      kitKind: 'fixed',
      productName: '基础拼豆套装',
      configurationLabel: null,
      unitPrice: '599.00',
      imageUrl: '/uploads/products/kit.png',
      quantity: 1,
    })
  })

  it('自选颜色 Kit 保存商品颜色 ID，并把份数解释为 10g 单位', () => {
    expect(buildColorKitCartItem(colorKitDetail, colorKitDetail.colors[0], 99)).toEqual({
      productId: 3,
      experienceOptionId: null,
      kitColorId: 31,
      productType: 'kit',
      kitKind: 'color_selectable',
      productName: '自选颜色拼豆',
      configurationLabel: 'A01 · 白色',
      saleUnitGrams: 10,
      unitPrice: '2.50',
      imageUrl: '/uploads/bead-colors/a01.webp',
      quantity: 99,
    })
  })

  it('色号与名称相同时购物车配置只保存一个标签', () => {
    const color = { ...colorKitDetail.colors[0], color_code: 'A1', name: 'A1' }

    expect(buildColorKitCartItem(
      { ...colorKitDetail, colors: [color] },
      color,
      1,
    ).configurationLabel).toBe('A1')
  })

  it('拒绝超过 990g 或不属于当前商品的颜色', () => {
    expect(() => buildColorKitCartItem(colorKitDetail, colorKitDetail.colors[0], 100))
      .toThrow('每种颜色必须选择 10g 至 990g')
    expect(() => buildColorKitCartItem(
      colorKitDetail,
      { ...colorKitDetail.colors[0], id: 999 },
      1,
    )).toThrow('所选颜色不属于当前商品')
  })
})
