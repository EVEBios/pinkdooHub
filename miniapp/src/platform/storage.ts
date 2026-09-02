import Taro from '@tarojs/taro'

export interface StoragePort {
  get(key: string): Promise<unknown>
  set(key: string, value: unknown): Promise<void>
  remove(key: string): Promise<void>
}

export class TaroStorageAdapter implements StoragePort {
  async get(key: string): Promise<unknown> {
    try {
      const result = await Taro.getStorage({ key })
      return result.data
    } catch (cause) {
      if (isMissingKeyError(cause)) {
        return undefined
      }
      throw cause
    }
  }

  async set(key: string, value: unknown): Promise<void> {
    await Taro.setStorage({ key, data: value })
  }

  async remove(key: string): Promise<void> {
    try {
      await Taro.removeStorage({ key })
    } catch (cause) {
      if (!isMissingKeyError(cause)) {
        throw cause
      }
    }
  }
}

function isMissingKeyError(cause: unknown): boolean {
  if (typeof cause !== 'object' || cause === null || !('errMsg' in cause)) {
    return false
  }
  const message = String(cause.errMsg).toLowerCase()
  return message.includes('not found') || message.includes('data not found')
}
