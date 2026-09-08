import { ContractError } from '@/api/errors'
import type { ApiClient } from '@/api/client'
import type { components, operations } from '@/api/schema'

export type ProductType = components['schemas']['ProductType']
type KitKindLabel = NonNullable<components['schemas']['KitProductDetailOut']['kit_kind']>
type GeneratedProductListItem = components['schemas']['ProductListItemOut']
type GeneratedProductListPage = components['schemas']['Page_ProductListItemOut_']
type GeneratedKitColorOption = components['schemas']['KitColorOptionOut']
type GeneratedKitProductDetail = components['schemas']['KitProductDetailOut']
export type ProductListItem = Omit<
  GeneratedProductListItem,
  'kit_kind' | 'sale_unit_grams'
> & {
  readonly kit_kind: KitKindLabel | null
  readonly sale_unit_grams: number | null
}
export type ProductListPage = Omit<GeneratedProductListPage, 'items'> & {
  readonly items: readonly ProductListItem[]
}
export type ExperienceProductDetail = components['schemas']['ExperienceProductDetailOut']
export type KitColorOption = Omit<
  GeneratedKitColorOption,
  'swatch_hex' | 'swatch_image_url'
> & {
  readonly swatch_hex: string | null
  readonly swatch_image_url: string | null
}
export type KitProductDetail = Omit<
  GeneratedKitProductDetail,
  'kit_kind' | 'sale_unit_grams' | 'colors'
> & {
  readonly kit_kind: KitKindLabel
  readonly sale_unit_grams: number | null
  readonly colors: readonly KitColorOption[]
}
export type ProductDetail = ExperienceProductDetail | KitProductDetail
export type ExperienceOption = components['schemas']['_OnlineExperienceOptionOut']
type ProductImage = components['schemas']['ProductImageOut']
type OptionImage = components['schemas']['OptionImageOut']
type PositiveIntegerLabel = ExperienceOption['duration']
type DayTypeLabel = ExperienceOption['day_type']
export type ProductListQuery = NonNullable<
  operations['list_products_api_v1_products_get']['parameters']['query']
>

export interface ProductListRequest extends ProductListQuery {
  signal?: AbortSignal
}

export interface ProductDetailRequest {
  productId: number
  signal?: AbortSignal
}

type ProductApiClient = Pick<ApiClient, 'request'>

export class ProductApi {
  constructor(private readonly client: ProductApiClient) {}

  async listProducts(request: ProductListRequest = {}): Promise<ProductListPage> {
    const { signal, ...query } = request
    const result = await this.client.request<unknown>({
      operation: 'products.list',
      path: '/api/v1/products',
      query,
      auth: 'none',
      signal,
    })
    const parsed = parseProductListPage(result)
    if (!parsed) {
      throw new ContractError({ operation: 'products.list' })
    }
    return parsed
  }

  async getExperienceProduct(request: ProductDetailRequest): Promise<ExperienceProductDetail> {
    const operation = 'products.experience.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/products/experience/${request.productId}`,
      auth: 'none',
      signal: request.signal,
    })
    const parsed = parseExperienceProductDetail(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getKitProduct(request: ProductDetailRequest): Promise<KitProductDetail> {
    const operation = 'products.kit.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/products/kit/${request.productId}`,
      auth: 'none',
      signal: request.signal,
    })
    const parsed = parseKitProductDetail(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }
}

export function parseProductListPage(value: unknown): ProductListPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    return undefined
  }
  const items = value.items.map(parseProductListItem)
  if (
    items.some((item) => item === undefined) ||
    !isNonNegativeInteger(value.total) ||
    !isPositiveInteger(value.page) ||
    !isPositiveInteger(value.page_size) ||
    !isNonNegativeInteger(value.pages)
  ) {
    return undefined
  }
  return {
    items: items as ProductListItem[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function parseProductListItem(value: unknown): ProductListItem | undefined {
  if (!isRecord(value) || !isRecord(value.product_type)) {
    return undefined
  }
  if (!(
    isPositiveInteger(value.id) &&
    isNonEmptyString(value.name) &&
    isSupportedAssetUrl(value.cover_image) &&
    isMoneyString(value.display_price) &&
    (value.product_type.value === 'experience' || value.product_type.value === 'kit') &&
    isNonEmptyString(value.product_type.label)
  )) {
    return undefined
  }
  const kitMetadata = parseListKitMetadata(value, value.product_type.value)
  if (!kitMetadata) {
    return undefined
  }
  return {
    id: value.id,
    name: value.name,
    cover_image: value.cover_image,
    display_price: value.display_price,
    product_type: {
      value: value.product_type.value,
      label: value.product_type.label,
    },
    ...kitMetadata,
  }
}

export function parseExperienceProductDetail(value: unknown): ExperienceProductDetail | undefined {
  if (!isProductDetailBase(value, 'experience') || !isRecord(value.dimensions)) {
    return undefined
  }
  const images = parseArray(value.images, parseProductImage)
  const options = parseArray(value.options, parseExperienceOption)
  const durations = parseArray(value.dimensions.durations, parsePositiveIntegerLabel)
  const participants = parseArray(value.dimensions.participants, parsePositiveIntegerLabel)
  const dayTypes = parseArray(value.dimensions.day_types, parseDayTypeLabel)
  if (
    !images || !hasProductCover(images) ||
    !options || options.length === 0 ||
    !durations || durations.length === 0 ||
    !participants || participants.length === 0 ||
    !dayTypes || dayTypes.length === 0 ||
    !dimensionsMatchOptions(options, durations, participants, dayTypes)
  ) {
    return undefined
  }
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    product_type: { value: 'experience', label: value.product_type.label },
    images,
    options,
    dimensions: {
      durations,
      participants,
      day_types: dayTypes,
    },
  }
}

export function parseKitProductDetail(value: unknown): KitProductDetail | undefined {
  if (!isProductDetailBase(value, 'kit')) {
    return undefined
  }
  const images = parseArray(value.images, parseProductImage)
  const kitKind = parseKitKind(value.kit_kind)
  const colors = parseArray(value.colors, parseKitColorOption)
  if (
    !images || !hasProductCover(images) ||
    !isMoneyString(value.price) ||
    !kitKind || !colors ||
    typeof value.available !== 'boolean'
  ) {
    return undefined
  }
  if (kitKind.value === 'fixed') {
    if (value.sale_unit_grams !== null || !isStock(value.stock) ||
      colors.length !== 0 || value.available !== (value.stock > 0)) {
      return undefined
    }
  } else if (value.sale_unit_grams !== 10 || value.stock !== null || colors.length < 1 ||
    value.available !== colors.some((color) => color.available)) {
    return undefined
  }
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    product_type: { value: 'kit', label: value.product_type.label },
    images,
    kit_kind: kitKind,
    sale_unit_grams: value.sale_unit_grams as 10 | null,
    price: value.price,
    stock: value.stock as number | null,
    available: value.available,
    colors,
  }
}

function parseListKitMetadata(
  value: Record<string, unknown>,
  productType: ProductType,
): Pick<ProductListItem, 'kit_kind' | 'sale_unit_grams'> | undefined {
  if (productType === 'experience') {
    return value.kit_kind === null && value.sale_unit_grams === null
      ? { kit_kind: null, sale_unit_grams: null }
      : undefined
  }
  const kitKind = parseKitKind(value.kit_kind)
  if (!kitKind) {
    return undefined
  }
  if (kitKind.value === 'fixed') {
    return value.sale_unit_grams === null
      ? { kit_kind: kitKind, sale_unit_grams: null }
      : undefined
  }
  return value.sale_unit_grams === 10
    ? { kit_kind: kitKind, sale_unit_grams: 10 }
    : undefined
}

function parseKitKind(value: unknown): KitProductDetail['kit_kind'] | undefined {
  if (!isRecord(value) ||
    (value.value !== 'fixed' && value.value !== 'color_selectable') ||
    !isNonEmptyString(value.label)) {
    return undefined
  }
  return { value: value.value, label: value.label }
}

function parseKitColorOption(value: unknown): KitColorOption | undefined {
  if (!isRecord(value)) return undefined
  // Client-first rollout compatibility: pre-M8 public responses omit this
  // field. Normalize omission to null so the view can use the PNG fallback;
  // the generated current OpenAPI contract remains required non-null.
  const swatchHex = value.swatch_hex === undefined ? null : value.swatch_hex
  if (
    !isPositiveInteger(value.id) ||
    !isPositiveInteger(value.bead_color_id) ||
    !isPositiveInteger(value.slot_no) || value.slot_no > 221 ||
    !isNonEmptyString(value.color_code) || value.color_code.length > 50 ||
    !isNonEmptyString(value.name) || value.name.length > 100 ||
    !(swatchHex === null || isSwatchHex(swatchHex)) ||
    !(value.swatch_image_url === null || isSupportedAssetUrl(value.swatch_image_url)) ||
    typeof value.available !== 'boolean') {
    return undefined
  }
  return {
    id: value.id,
    bead_color_id: value.bead_color_id,
    slot_no: value.slot_no,
    color_code: value.color_code,
    name: value.name,
    swatch_hex: swatchHex,
    swatch_image_url: value.swatch_image_url,
    available: value.available,
  }
}

function isProductDetailBase(
  value: unknown,
  productType: ProductType,
): value is Record<string, unknown> & {
  id: number
  name: string
  description: string
  product_type: { value: ProductType; label: string }
} {
  return isRecord(value) &&
    isPositiveInteger(value.id) &&
    isNonEmptyString(value.name) &&
    typeof value.description === 'string' &&
    isRecord(value.product_type) &&
    value.product_type.value === productType &&
    isNonEmptyString(value.product_type.label)
}

function parseProductImage(value: unknown): ProductImage | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) ||
    !isSupportedAssetUrl(value.image_url) || typeof value.is_cover !== 'boolean' ||
    !isNonNegativeInteger(value.sort)) {
    return undefined
  }
  return { id: value.id, image_url: value.image_url, is_cover: value.is_cover, sort: value.sort }
}

function parseExperienceOption(value: unknown): ExperienceOption | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isMoneyString(value.price)) {
    return undefined
  }
  const duration = parsePositiveIntegerLabel(value.duration)
  const participants = parsePositiveIntegerLabel(value.participants)
  const dayType = parseDayTypeLabel(value.day_type)
  const images = parseArray(value.images, parseOptionImage)
  if (!duration || !participants || !dayType || !images || images.length === 0) {
    return undefined
  }
  return {
    id: value.id,
    duration,
    participants,
    day_type: dayType,
    price: value.price,
    images,
  }
}

function parseOptionImage(value: unknown): OptionImage | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) ||
    !isSupportedAssetUrl(value.image_url) || !isNonNegativeInteger(value.sort)) {
    return undefined
  }
  return { id: value.id, image_url: value.image_url, sort: value.sort }
}

function parsePositiveIntegerLabel(value: unknown): PositiveIntegerLabel | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.value) || !isNonEmptyString(value.label)) {
    return undefined
  }
  return { value: value.value, label: value.label }
}

function parseDayTypeLabel(value: unknown): DayTypeLabel | undefined {
  if (!isRecord(value) ||
    (value.value !== 'weekday' && value.value !== 'holiday') ||
    !isNonEmptyString(value.label)) {
    return undefined
  }
  return { value: value.value, label: value.label }
}

function parseArray<T>(value: unknown, parser: (item: unknown) => T | undefined): T[] | undefined {
  if (!Array.isArray(value)) {
    return undefined
  }
  const parsed = value.map(parser)
  return parsed.some((item) => item === undefined) ? undefined : parsed as T[]
}

function hasProductCover(images: readonly ProductImage[]): boolean {
  return images.length > 0 && images.some((image) => image.is_cover)
}

function dimensionsMatchOptions(
  options: readonly ExperienceOption[],
  durations: readonly PositiveIntegerLabel[],
  participants: readonly PositiveIntegerLabel[],
  dayTypes: readonly DayTypeLabel[],
): boolean {
  return sameValues(durations.map((item) => item.value), options.map((item) => item.duration.value)) &&
    sameValues(participants.map((item) => item.value), options.map((item) => item.participants.value)) &&
    sameValues(dayTypes.map((item) => item.value), options.map((item) => item.day_type.value))
}

function sameValues<T extends string | number>(left: readonly T[], right: readonly T[]): boolean {
  const leftValues = new Set(left)
  const rightValues = new Set(right)
  return leftValues.size === rightValues.size && [...leftValues].every((value) => rightValues.has(value))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isSwatchHex(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9A-F]{6}$/.test(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isStock(value: unknown): value is number {
  return isNonNegativeInteger(value) && value <= 999_999
}

function isSupportedAssetUrl(value: unknown): value is string {
  return isNonEmptyString(value) && value.length <= 2048 &&
    (value.startsWith('/') || /^https?:\/\//i.test(value))
}

function isMoneyString(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false
  }
  const match = /^(0|[1-9]\d{0,4})\.(\d{2})$/.exec(value)
  if (!match) {
    return false
  }
  const [, integer, decimal] = match
  if (integer === '0') {
    return decimal !== '00'
  }
  return integer !== '99999' || decimal === '00'
}
