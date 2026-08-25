import type {
  ExperienceOption,
  ExperienceProductDetail,
  KitProductDetail,
} from '@/api/endpoints/products'

import type { AddCartItemInput } from './cart'

export function buildExperienceCartItem(
  detail: ExperienceProductDetail,
  option: ExperienceOption,
): AddCartItemInput {
  if (!detail.options.some((candidate) => candidate.id === option.id)) {
    throw new Error('所选体验配置不属于当前商品')
  }
  return {
    productId: detail.id,
    experienceOptionId: option.id,
    productType: 'experience',
    productName: detail.name,
    configurationLabel: `${option.duration.label} · ${option.participants.label} · ${option.day_type.label}`,
    unitPrice: option.price,
    imageUrl: option.images[0]?.image_url ?? detail.images[0]?.image_url ?? null,
    quantity: 1,
  }
}

export function buildKitCartItem(detail: KitProductDetail): AddCartItemInput {
  return {
    productId: detail.id,
    experienceOptionId: null,
    productType: 'kit',
    productName: detail.name,
    configurationLabel: null,
    unitPrice: detail.price,
    imageUrl: detail.images[0]?.image_url ?? null,
    quantity: 1,
  }
}
