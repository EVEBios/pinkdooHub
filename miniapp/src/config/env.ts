/**
 * 环境配置：统一读取 Taro 编译期注入的环境变量。
 *
 * APP_ENV 与 TARO_ENV 是两个独立维度：
 * - TARO_APP_APP_ENV：development / testing / production（业务环境）；
 * - TARO_ENV：weapp / alipay / tt / h5（目标平台，由 Taro 构建时注入）。
 *
 * 注意：Taro 通过 webpack DefinePlugin 只替换代码中“字面量”形式的
 * `process.env.TARO_APP_*` / `process.env.TARO_ENV`，因此默认路径必须直接书写
 * 这些字面量，不能经由参数间接访问（Spike 实测结论）。
 * source 参数仅用于 Jest 显式注入。
 */

export type AppEnv = 'development' | 'testing' | 'production'

export type Platform = 'weapp' | 'alipay' | 'tt' | 'h5' | (string & {})
export type AuthMode = 'password' | 'wechat'

export interface AppEnvironment {
  appEnv: AppEnv
  platform: Platform
  apiOrigin: string
  authMode: AuthMode
}

export type EnvSource = Partial<NodeJS.ProcessEnv>

const APP_ENV_VALUES: readonly AppEnv[] = ['development', 'testing', 'production']
const ORIGIN_PATTERN = /^(https?):\/\/(\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::([0-9]{1,5}))?$/i
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '[::1]'])

export class AppConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AppConfigError'
  }
}

export function resolveEnv(source?: EnvSource): AppEnvironment {
  const appEnv = parseAppEnv(source?.TARO_APP_APP_ENV ?? process.env.TARO_APP_APP_ENV)
  return {
    appEnv,
    platform: source?.TARO_ENV ?? process.env.TARO_ENV ?? 'unknown',
    apiOrigin: parseApiOrigin(source?.TARO_APP_API_ORIGIN ?? process.env.TARO_APP_API_ORIGIN, appEnv),
    authMode: parseAuthMode(
      source?.TARO_APP_AUTH_MODE ?? process.env.TARO_APP_AUTH_MODE,
    ),
  }
}

function parseAuthMode(raw: string | undefined): AuthMode {
  if (raw === 'password' || raw === 'wechat') {
    return raw
  }
  throw new AppConfigError('TARO_APP_AUTH_MODE 必须为 password 或 wechat')
}

function parseAppEnv(raw: string | undefined): AppEnv {
  if (raw && (APP_ENV_VALUES as readonly string[]).includes(raw)) {
    return raw as AppEnv
  }
  throw new AppConfigError('TARO_APP_APP_ENV 未配置或取值非法')
}

function parseApiOrigin(raw: string | undefined, appEnv: AppEnv): string {
  if (!raw) {
    throw new AppConfigError('TARO_APP_API_ORIGIN 未配置')
  }
  const origin = raw.replace(/\/+$/, '')
  const match = ORIGIN_PATTERN.exec(origin)
  if (!match) {
    throw new AppConfigError('TARO_APP_API_ORIGIN 必须是无路径、无凭据的 HTTP(S) Origin')
  }
  const [, scheme, hostname, port] = match
  if (port && Number(port) > 65_535) {
    throw new AppConfigError('TARO_APP_API_ORIGIN 端口超出有效范围')
  }
  if (appEnv === 'production' && scheme.toLowerCase() !== 'https') {
    throw new AppConfigError('生产环境必须使用 HTTPS API Origin')
  }
  if (appEnv === 'production' && LOCAL_HOSTS.has(hostname.toLowerCase())) {
    throw new AppConfigError('生产环境禁止使用本机 API Origin')
  }
  return origin
}
