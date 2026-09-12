import Taro from '@tarojs/taro'

export interface PickedImage {
  readonly filePath: string
  readonly size: number
  readonly mediaType?: string
}

export interface ImagePickerPort {
  pickOne(): Promise<PickedImage | undefined>
}

export class TaroImagePickerAdapter implements ImagePickerPort {
  async pickOne(): Promise<PickedImage | undefined> {
    try {
      const result = await Taro.chooseImage({
        count: 1,
        sizeType: ['original'],
        sourceType: ['album', 'camera'],
      })
      const file = result.tempFiles[0]
      const filePath = file?.path ?? result.tempFilePaths[0]
      if (!filePath) return undefined
      return {
        filePath,
        size: file?.size ?? 0,
        ...(file?.type ? { mediaType: file.type } : {}),
      }
    } catch (cause) {
      if (isCancellation(cause)) return undefined
      throw cause
    }
  }
}

function isCancellation(cause: unknown): boolean {
  return typeof cause === 'object' && cause !== null && 'errMsg' in cause &&
    String(cause.errMsg).toLowerCase().includes('cancel')
}
