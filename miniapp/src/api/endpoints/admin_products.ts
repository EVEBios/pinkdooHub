import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type AdminProductListRequest = NonNullable<operations[
  'list_admin_products_api_v1_admin_products_get'
]['parameters']['query']>
export type AdminProductListItem = components['schemas']['AdminProductListItemOut']
export type AdminProductListPage = components['schemas']['Page_AdminProductListItemOut_']
export type AdminExperienceProductDetail = components['schemas']['AdminExperienceProductDetailOut']
export type AdminKitProductDetail = components['schemas']['AdminKitProductDetailOut']
export type AdminProductDetail = AdminExperienceProductDetail | AdminKitProductDetail
export type AdminProductType = 'experience' | 'kit'
export type ExperienceProductCreateRequest = components['schemas']['ExperienceProductCreate']
export type KitProductCreateRequest = components['schemas']['KitProductCreate']
export type ExperienceProductCreateResult = components['schemas']['ExperienceProductCreateOut']
export type KitProductCreateResult = components['schemas']['KitProductCreateOut']
export type ProductBasicInfoUpdateRequest = {
  readonly name?: string
  readonly description?: string | null
}
export type ProductBasicInfoResult = components['schemas']['ProductBasicInfoOut']
export type DeletedProductResult = components['schemas']['DeletedResourceOut']
export type ExperienceOptionCreateRequest = components['schemas']['ExperienceOptionCreate']
export type ExperienceOptionUpdateRequest = {
  readonly duration_minutes?: number
  readonly participants?: number
  readonly day_type?: 'weekday' | 'holiday'
  readonly price?: string
}
export type ExperienceOptionCreateResult = components['schemas']['ExperienceOptionOut']
export type ExperienceOptionUpdateResult = components['schemas']['ExperienceOptionBaseOut']
export type DeletedExperienceOptionResult = components['schemas']['DeletedResourceOut']
export type KitPriceUpdateRequest = components['schemas']['KitPriceUpdate']
export type KitPriceUpdateResult = components['schemas']['KitPriceOut']
export type ProductImageResult = components['schemas']['ProductImageOut']
export type OptionImageResult = components['schemas']['OptionImageOut']
export type ProductImageUpdateRequest = {
  readonly sort?: number
  readonly is_cover?: true
}
export type ProductImageUpdateResult = ProductImageResult | OptionImageResult
export type ProductImageUploadRequest = {
  readonly filePath: string
  readonly isCover?: boolean
  readonly sort?: number
}
export type OptionImageUploadRequest = {
  readonly filePath: string
  readonly sort?: number
}
export type ProductStatusResult = components['schemas']['ProductOnlineOut'] |
components['schemas']['ProductOfflineOut']

type AdminProductApiClient = Pick<ApiClient, 'request' | 'uploadFile'>
type ProductImage = components['schemas']['ProductImageOut']
type ExperienceOption = components['schemas']['ExperienceOptionOut']
type PositiveIntegerLabel = ExperienceOption['duration']
type DayTypeLabel = ExperienceOption['day_type']

const UTC_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/

export class AdminProductApi {
  constructor(private readonly client: AdminProductApiClient) {}

  async createExperienceProduct(
    request: ExperienceProductCreateRequest,
  ): Promise<ExperienceProductCreateResult> {
    const operation = 'products.admin.experience.create'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/products/experience',
      method: 'POST',
      auth: 'required',
      body: projectExperienceProductCreate(request),
    })
    const parsed = parseExperienceProductCreateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async createKitProduct(request: KitProductCreateRequest): Promise<KitProductCreateResult> {
    const operation = 'products.admin.kit.create'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/products/kit',
      method: 'POST',
      auth: 'required',
      body: projectKitProductCreate(request),
    })
    const parsed = parseKitProductCreateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async updateProductBasicInfo(
    productId: number,
    request: ProductBasicInfoUpdateRequest,
  ): Promise<ProductBasicInfoResult> {
    assertProductId(productId)
    const body = projectProductBasicInfoUpdate(request)
    if (Object.keys(body).length === 0) {
      throw new Error('商品基本信息至少需要一个改动字段')
    }
    const operation = 'products.admin.basic_info.update'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/${productId}`,
      method: 'PATCH',
      auth: 'required',
      body,
    })
    const parsed = parseProductBasicInfoResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async deleteProduct(productId: number): Promise<DeletedProductResult> {
    assertProductId(productId)
    const operation = 'products.admin.delete'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/${productId}`,
      method: 'DELETE',
      auth: 'required',
    })
    const parsed = parseDeletedProductResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async createExperienceOption(
    productId: number,
    request: ExperienceOptionCreateRequest,
  ): Promise<ExperienceOptionCreateResult> {
    assertProductId(productId)
    const operation = 'products.admin.experience_option.create_or_restore'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/experience/${productId}/options`,
      method: 'POST',
      auth: 'required',
      body: projectExperienceOptionCreate(request),
    })
    const parsed = parseExperienceOptionCreateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async updateExperienceOption(
    optionId: number,
    request: ExperienceOptionUpdateRequest,
  ): Promise<ExperienceOptionUpdateResult> {
    assertOptionId(optionId)
    const body = projectExperienceOptionUpdate(request)
    if (Object.keys(body).length === 0) throw new Error('Experience Option 至少需要一个改动字段')
    const operation = 'products.admin.experience_option.update'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/options/${optionId}`,
      method: 'PATCH',
      auth: 'required',
      body,
    })
    const parsed = parseExperienceOptionUpdateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async deleteExperienceOption(optionId: number): Promise<DeletedExperienceOptionResult> {
    assertOptionId(optionId)
    const operation = 'products.admin.experience_option.delete'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/options/${optionId}`,
      method: 'DELETE',
      auth: 'required',
    })
    const parsed = parseDeletedProductResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async updateKitPrice(
    productId: number,
    request: KitPriceUpdateRequest,
  ): Promise<KitPriceUpdateResult> {
    assertProductId(productId)
    const operation = 'products.admin.kit.price.update'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}/price`,
      method: 'PATCH',
      auth: 'required',
      body: { price: request.price },
    })
    const parsed = parseKitPriceUpdateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async uploadProductImage(
    productId: number,
    request: ProductImageUploadRequest,
  ): Promise<ProductImageResult> {
    assertProductId(productId)
    assertFilePath(request.filePath)
    assertImageSort(request.sort)
    const operation = 'products.admin.product_image.upload'
    const result = await this.client.uploadFile<unknown>({
      operation,
      path: `/api/v1/admin/products/${productId}/images`,
      filePath: request.filePath,
      auth: 'required',
      formData: {
        is_cover: String(request.isCover ?? false),
        sort: String(request.sort ?? 0),
      },
    })
    const parsed = parseProductImageResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async uploadOptionImage(
    optionId: number,
    request: OptionImageUploadRequest,
  ): Promise<OptionImageResult> {
    assertOptionId(optionId)
    assertFilePath(request.filePath)
    assertImageSort(request.sort)
    const operation = 'products.admin.option_image.upload'
    const result = await this.client.uploadFile<unknown>({
      operation,
      path: `/api/v1/admin/options/${optionId}/images`,
      filePath: request.filePath,
      auth: 'required',
      formData: { sort: String(request.sort ?? 0) },
    })
    const parsed = parseOptionImageResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async updateProductImage(
    imageId: number,
    request: ProductImageUpdateRequest,
  ): Promise<ProductImageUpdateResult> {
    assertImageId(imageId)
    assertImageSort(request.sort)
    const body = {
      ...(request.sort === undefined ? {} : { sort: request.sort }),
      ...(request.is_cover === undefined ? {} : { is_cover: request.is_cover }),
    }
    if (Object.keys(body).length === 0) throw new Error('图片至少需要一个排序或封面改动')
    const operation = 'products.admin.product_image.update'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/product-images/${imageId}`,
      method: 'PATCH',
      auth: 'required',
      body,
    })
    const parsed = parseProductImageUpdateResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async deleteProductImage(imageId: number): Promise<DeletedProductResult> {
    assertImageId(imageId)
    const operation = 'products.admin.product_image.delete'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/product-images/${imageId}`,
      method: 'DELETE',
      auth: 'required',
    })
    const parsed = parseDeletedProductResult(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async onlineProduct(productId: number): Promise<ProductStatusResult> {
    return this.changeProductStatus(productId, 'online')
  }

  async offlineProduct(productId: number): Promise<ProductStatusResult> {
    return this.changeProductStatus(productId, 'offline')
  }

  async listProducts(request: AdminProductListRequest = {}): Promise<AdminProductListPage> {
    const operation = 'products.admin.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/products',
      method: 'GET',
      auth: 'required',
      query: projectAdminProductListRequest(request),
    })
    const parsed = parseAdminProductListPage(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async getExperienceProduct(productId: number): Promise<AdminExperienceProductDetail> {
    assertProductId(productId)
    const operation = 'products.admin.experience.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/experience/${productId}`,
      method: 'GET',
      auth: 'required',
    })
    const parsed = parseAdminExperienceProductDetail(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async getKitProduct(productId: number): Promise<AdminKitProductDetail> {
    assertProductId(productId)
    const operation = 'products.admin.kit.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}`,
      method: 'GET',
      auth: 'required',
    })
    const parsed = parseAdminKitProductDetail(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  private async changeProductStatus(
    productId: number,
    status: 'online' | 'offline',
  ): Promise<ProductStatusResult> {
    assertProductId(productId)
    const operation = `products.admin.${status}`
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/${productId}/${status}`,
      method: 'PATCH',
      auth: 'required',
    })
    const parsed = parseProductStatusResult(result, status)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }
}

export function parseExperienceProductCreateResult(
  value: unknown,
): ExperienceProductCreateResult | undefined {
  const parsed = parseProductCreateResult(value, 'experience')
  return parsed
    ? {
        id: parsed.id,
        name: parsed.name,
        product_type: { value: 'experience', label: parsed.product_type.label },
        status: { value: 'draft', label: parsed.status.label },
      }
    : undefined
}

export function parseKitProductCreateResult(value: unknown): KitProductCreateResult | undefined {
  const parsed = parseProductCreateResult(value, 'kit')
  return parsed
    ? {
        id: parsed.id,
        name: parsed.name,
        product_type: { value: 'kit', label: parsed.product_type.label },
        status: { value: 'draft', label: parsed.status.label },
      }
    : undefined
}

export function parseProductBasicInfoResult(value: unknown): ProductBasicInfoResult | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) ||
    !isBoundedNonEmptyString(value.name, 100) ||
    !(value.description === null || isBoundedString(value.description, 2000)) ||
    !isUtcDatetime(value.updated_at)) return undefined
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    updated_at: value.updated_at,
  }
}

export function parseDeletedProductResult(value: unknown): DeletedProductResult | undefined {
  return isRecord(value) && isPositiveInteger(value.id) && value.is_deleted === true
    ? { id: value.id, is_deleted: true }
    : undefined
}

export function parseExperienceOptionCreateResult(
  value: unknown,
): ExperienceOptionCreateResult | undefined {
  return parseExperienceOption(value)
}

export function parseExperienceOptionUpdateResult(
  value: unknown,
): ExperienceOptionUpdateResult | undefined {
  return parseExperienceOptionBase(value)
}

export function parseKitPriceUpdateResult(value: unknown): KitPriceUpdateResult | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isMoneyString(value.price)) return undefined
  return { id: value.id, price: value.price }
}

export function parseProductImageResult(value: unknown): ProductImageResult | undefined {
  return parseProductImage(value)
}

export function parseOptionImageResult(value: unknown): OptionImageResult | undefined {
  return parseOptionImage(value)
}

export function parseProductImageUpdateResult(
  value: unknown,
): ProductImageUpdateResult | undefined {
  if (!isRecord(value)) return undefined
  return Object.prototype.hasOwnProperty.call(value, 'is_cover')
    ? parseProductImage(value)
    : parseOptionImage(value)
}

export function parseProductStatusResult(
  value: unknown,
  expectedStatus: 'online' | 'offline',
): ProductStatusResult | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isRecord(value.status) ||
    value.status.value !== expectedStatus || !isNonEmptyString(value.status.label)) return undefined
  return expectedStatus === 'online'
    ? { id: value.id, status: { value: 'online', label: value.status.label } }
    : { id: value.id, status: { value: 'offline', label: value.status.label } }
}

export function parseAdminProductListPage(value: unknown): AdminProductListPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items)) return undefined
  const items = value.items.map(parseAdminProductListItem)
  if (items.some((item) => item === undefined) || !isNonNegativeInteger(value.total) ||
    !isPositiveInteger(value.page) || !isPositiveInteger(value.page_size) ||
    !isNonNegativeInteger(value.pages)) return undefined
  return {
    items: items as AdminProductListItem[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

export function parseAdminExperienceProductDetail(
  value: unknown,
): AdminExperienceProductDetail | undefined {
  const base = parseAdminProductDetailBase(value, 'experience')
  if (!base || !isRecord(value) || !isRecord(value.dimensions)) return undefined
  const images = parseArray(value.images, parseProductImage)
  const options = parseArray(value.options, parseExperienceOption)
  const durations = parseArray(value.dimensions.durations, parsePositiveIntegerLabel)
  const participants = parseArray(value.dimensions.participants, parsePositiveIntegerLabel)
  const dayTypes = parseArray(value.dimensions.day_types, parseDayTypeLabel)
  if (!images || !options || !durations || !participants || !dayTypes ||
    !dimensionsMatchOptions(options, durations, participants, dayTypes)) return undefined
  return {
    ...base,
    product_type: { value: 'experience', label: base.product_type.label },
    images,
    options,
    dimensions: { durations, participants, day_types: dayTypes },
  }
}

export function parseAdminKitProductDetail(value: unknown): AdminKitProductDetail | undefined {
  const base = parseAdminProductDetailBase(value, 'kit')
  if (!base || !isRecord(value)) return undefined
  const images = parseArray(value.images, parseProductImage)
  if (!images || !isMoneyString(value.price) || !isStock(value.stock)) return undefined
  return {
    ...base,
    product_type: { value: 'kit', label: base.product_type.label },
    images,
    price: value.price,
    stock: value.stock,
  }
}

function parseAdminProductListItem(value: unknown): AdminProductListItem | undefined {
  if (!isRecord(value) || !isRecord(value.product_type) || !isRecord(value.status) ||
    !isPositiveInteger(value.id) || !isNonEmptyString(value.name) ||
    !isProductType(value.product_type.value) || !isNonEmptyString(value.product_type.label) ||
    !isProductStatus(value.status.value) || !isNonEmptyString(value.status.label) ||
    !isNullableAssetUrl(value.cover_image) || !isNullableMoney(value.display_price) ||
    !isUtcDatetime(value.updated_at) || typeof value.is_deleted !== 'boolean') return undefined
  return {
    id: value.id,
    name: value.name,
    product_type: { value: value.product_type.value, label: value.product_type.label },
    status: { value: value.status.value, label: value.status.label },
    cover_image: value.cover_image,
    display_price: value.display_price,
    updated_at: value.updated_at,
    is_deleted: value.is_deleted,
  }
}

interface AdminProductDetailBase {
  id: number
  name: string
  description: string | null
  product_type: { value: AdminProductType; label: string }
  status: { value: 'draft' | 'online' | 'offline'; label: string }
  created_at: string
  updated_at: string
  is_deleted: boolean
}

function parseAdminProductDetailBase(
  value: unknown,
  productType: AdminProductType,
): AdminProductDetailBase | undefined {
  if (!isRecord(value) || !isRecord(value.product_type) || !isRecord(value.status) ||
    !isPositiveInteger(value.id) || !isNonEmptyString(value.name) ||
    !(value.description === null || typeof value.description === 'string') ||
    value.product_type.value !== productType || !isNonEmptyString(value.product_type.label) ||
    !isProductStatus(value.status.value) || !isNonEmptyString(value.status.label) ||
    !isUtcDatetime(value.created_at) || !isUtcDatetime(value.updated_at) ||
    typeof value.is_deleted !== 'boolean') return undefined
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    product_type: { value: productType, label: value.product_type.label },
    status: { value: value.status.value, label: value.status.label },
    created_at: value.created_at,
    updated_at: value.updated_at,
    is_deleted: value.is_deleted,
  }
}

function parseProductImage(value: unknown): ProductImage | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isSupportedAssetUrl(value.image_url) ||
    typeof value.is_cover !== 'boolean' || !isNonNegativeInteger(value.sort)) return undefined
  return { id: value.id, image_url: value.image_url, is_cover: value.is_cover, sort: value.sort }
}

function parseExperienceOption(value: unknown): ExperienceOption | undefined {
  const base = parseExperienceOptionBase(value)
  if (!base || !isRecord(value)) return undefined
  const images = parseArray(value.images, parseOptionImage)
  if (!images) return undefined
  return { ...base, images }
}

function parseExperienceOptionBase(value: unknown): ExperienceOptionUpdateResult | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isMoneyString(value.price)) return undefined
  const duration = parsePositiveIntegerLabel(value.duration)
  const participants = parsePositiveIntegerLabel(value.participants)
  const dayType = parseDayTypeLabel(value.day_type)
  if (!duration || !participants || !dayType) return undefined
  return { id: value.id, duration, participants, day_type: dayType, price: value.price }
}

function parseOptionImage(value: unknown): components['schemas']['OptionImageOut'] | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isSupportedAssetUrl(value.image_url) ||
    !isNonNegativeInteger(value.sort)) return undefined
  return { id: value.id, image_url: value.image_url, sort: value.sort }
}

function parsePositiveIntegerLabel(value: unknown): PositiveIntegerLabel | undefined {
  return isRecord(value) && isPositiveInteger(value.value) && isNonEmptyString(value.label)
    ? { value: value.value, label: value.label }
    : undefined
}

function parseDayTypeLabel(value: unknown): DayTypeLabel | undefined {
  return isRecord(value) && (value.value === 'weekday' || value.value === 'holiday') &&
    isNonEmptyString(value.label)
    ? { value: value.value, label: value.label }
    : undefined
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

function projectAdminProductListRequest(request: AdminProductListRequest): AdminProductListRequest {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.product_type == null ? {} : { product_type: request.product_type }),
    ...(request.status == null ? {} : { status: request.status }),
    ...(request.keyword == null ? {} : { keyword: request.keyword }),
    ...(request.include_deleted === undefined ? {} : { include_deleted: request.include_deleted }),
  }
}

function projectExperienceProductCreate(
  request: ExperienceProductCreateRequest,
): ExperienceProductCreateRequest {
  return {
    name: request.name,
    ...(request.description === undefined ? {} : { description: request.description }),
  }
}

function projectKitProductCreate(request: KitProductCreateRequest): KitProductCreateRequest {
  return {
    name: request.name,
    ...(request.description === undefined ? {} : { description: request.description }),
    price: request.price,
  }
}

function projectProductBasicInfoUpdate(
  request: ProductBasicInfoUpdateRequest,
): ProductBasicInfoUpdateRequest {
  return {
    ...(request.name === undefined ? {} : { name: request.name }),
    ...(request.description === undefined ? {} : { description: request.description }),
  }
}

function projectExperienceOptionCreate(
  request: ExperienceOptionCreateRequest,
): ExperienceOptionCreateRequest {
  return {
    duration_minutes: request.duration_minutes,
    participants: request.participants,
    day_type: request.day_type,
    price: request.price,
  }
}

function projectExperienceOptionUpdate(
  request: ExperienceOptionUpdateRequest,
): ExperienceOptionUpdateRequest {
  return {
    ...(request.duration_minutes === undefined ? {} : { duration_minutes: request.duration_minutes }),
    ...(request.participants === undefined ? {} : { participants: request.participants }),
    ...(request.day_type === undefined ? {} : { day_type: request.day_type }),
    ...(request.price === undefined ? {} : { price: request.price }),
  }
}

interface ProductCreateResultBase {
  readonly id: number
  readonly name: string
  readonly product_type: { readonly value: AdminProductType; readonly label: string }
  readonly status: { readonly value: 'draft'; readonly label: string }
}

function parseProductCreateResult(
  value: unknown,
  productType: AdminProductType,
): ProductCreateResultBase | undefined {
  if (!isRecord(value) || !isRecord(value.product_type) || !isRecord(value.status) ||
    !isPositiveInteger(value.id) || !isBoundedNonEmptyString(value.name, 100) ||
    value.product_type.value !== productType || !isNonEmptyString(value.product_type.label) ||
    value.status.value !== 'draft' || !isNonEmptyString(value.status.label)) return undefined
  return {
    id: value.id,
    name: value.name,
    product_type: { value: productType, label: value.product_type.label },
    status: { value: 'draft', label: value.status.label },
  }
}

function assertProductId(productId: number): void {
  if (!Number.isSafeInteger(productId) || productId <= 0) throw new Error('Product ID 必须是正安全整数')
}

function assertOptionId(optionId: number): void {
  if (!Number.isSafeInteger(optionId) || optionId <= 0) throw new Error('Option ID 必须是正安全整数')
}

function assertImageId(imageId: number): void {
  if (!Number.isSafeInteger(imageId) || imageId <= 0) throw new Error('Image ID 必须是正安全整数')
}

function assertFilePath(filePath: string): void {
  if (!filePath) throw new Error('上传文件路径不能为空')
}

function assertImageSort(sort: number | undefined): void {
  if (sort !== undefined && (!Number.isSafeInteger(sort) || sort < 0)) {
    throw new Error('图片排序必须是非负安全整数')
  }
}

function parseArray<T>(value: unknown, parser: (item: unknown) => T | undefined): T[] | undefined {
  if (!Array.isArray(value)) return undefined
  const parsed = value.map(parser)
  return parsed.some((item) => item === undefined) ? undefined : parsed as T[]
}

function sameValues<T extends string | number>(left: readonly T[], right: readonly T[]): boolean {
  const leftValues = new Set(left)
  const rightValues = new Set(right)
  return leftValues.size === rightValues.size && [...leftValues].every((value) => rightValues.has(value))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isProductType(value: unknown): value is AdminProductType {
  return value === 'experience' || value === 'kit'
}

function isProductStatus(value: unknown): value is 'draft' | 'online' | 'offline' {
  return value === 'draft' || value === 'online' || value === 'offline'
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isBoundedNonEmptyString(value: unknown, maxLength: number): value is string {
  return isNonEmptyString(value) && value.length <= maxLength
}

function isBoundedString(value: unknown, maxLength: number): value is string {
  return typeof value === 'string' && value.length <= maxLength
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
  return isNonEmptyString(value) && (value.startsWith('/') || /^https?:\/\//i.test(value))
}

function isNullableAssetUrl(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || isSupportedAssetUrl(value)
}

function isNullableMoney(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || isMoneyString(value)
}

function isMoneyString(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const match = /^(0|[1-9]\d{0,4})\.(\d{2})$/.exec(value)
  if (!match) return false
  const [, integer, decimal] = match
  return integer === '0' ? decimal !== '00' : integer !== '99999' || decimal === '00'
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' && UTC_DATETIME_PATTERN.test(value)
}
