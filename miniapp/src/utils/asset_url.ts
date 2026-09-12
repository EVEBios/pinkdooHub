import { resolveEnv } from '@/config/env'

/** 将后端允许的绝对图片 URL 或以 / 开头的开发期路径解析为可展示地址。 */
export function resolveAssetUrl(assetUrl: string, apiOrigin = resolveEnv().apiOrigin): string {
  if (/^https?:\/\//i.test(assetUrl)) {
    return assetUrl
  }
  if (assetUrl.startsWith('/')) {
    return `${apiOrigin.replace(/\/+$/, '')}${assetUrl}`
  }
  throw new Error('图片地址必须是 HTTP(S) URL 或以 / 开头的路径')
}
