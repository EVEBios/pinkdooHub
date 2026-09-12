import type {
  ExperienceOption,
  ExperienceProductDetail,
  KitColorOption,
  KitProductDetail,
} from '@/api/endpoints/products'
import { formatColorLabel } from '@/utils/format'

import {
  COLOR_SELECTABLE_SALE_UNIT_GRAMS,
  type AddCartItemInput,
  type ColorKitCartItem,
  type KitCartItem,
} from './cart'

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
    kitColorId: null,
    productType: 'experience',
    productName: detail.name,
    configurationLabel: `${option.duration.label} · ${option.participants.label} · ${option.day_type.label}`,
    unitPrice: option.price,
    imageUrl: option.images[0]?.image_url ?? detail.images[0]?.image_url ?? null,
    quantity: 1,
  }
}

export function buildKitCartItem(detail: KitProductDetail): KitCartItem {
  if (detail.kit_kind.value !== 'fixed' || detail.stock === null) {
    throw new Error('自选颜色商品必须先选择具体颜色')
  }
  return {
    productId: detail.id,
    experienceOptionId: null,
    kitColorId: null,
    productType: 'kit',
    kitKind: 'fixed',
    productName: detail.name,
    configurationLabel: null,
    unitPrice: detail.price,
    imageUrl: detail.images[0]?.image_url ?? null,
    quantity: 1,
  }
}

export function buildColorKitCartItem(
  detail: KitProductDetail,
  color: KitColorOption,
  quantity: number,
): ColorKitCartItem {
  if (detail.kit_kind.value !== 'color_selectable' ||
    detail.sale_unit_grams !== COLOR_SELECTABLE_SALE_UNIT_GRAMS) {
    throw new Error('固定套装不能选择单独颜色')
  }
  const currentColor = detail.colors.find((candidate) => candidate.id === color.id)
  if (!currentColor || currentColor.bead_color_id !== color.bead_color_id) {
    throw new Error('所选颜色不属于当前商品')
  }
  if (!currentColor.available) {
    throw new Error('所选颜色暂时无货')
  }
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) {
    throw new Error('每种颜色必须选择 10g 至 990g')
  }
  return {
    productId: detail.id,
    experienceOptionId: null,
    kitColorId: currentColor.id,
    productType: 'kit',
    kitKind: 'color_selectable',
    productName: detail.name,
    configurationLabel: formatColorLabel(currentColor.color_code, currentColor.name),
    saleUnitGrams: COLOR_SELECTABLE_SALE_UNIT_GRAMS,
    swatchHex: currentColor.swatch_hex,
    unitPrice: detail.price,
    imageUrl: currentColor.swatch_image_url,
    quantity,
  }
}
