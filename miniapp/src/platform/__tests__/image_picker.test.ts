import Taro from '@tarojs/taro'

import { TaroImagePickerAdapter } from '../image_picker'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { chooseImage: jest.fn() },
}))

describe('TaroImagePickerAdapter', () => {
  afterEach(() => jest.clearAllMocks())

  it('只选择一张原图并投影路径、大小和可选 MIME', async () => {
    ;(Taro.chooseImage as jest.Mock).mockResolvedValue({
      tempFilePaths: ['wxfile://cover.png'],
      tempFiles: [{ path: 'wxfile://cover.png', size: 1_024, type: 'image/png' }],
      errMsg: 'chooseImage:ok',
    })
    await expect(new TaroImagePickerAdapter().pickOne()).resolves.toEqual({
      filePath: 'wxfile://cover.png',
      size: 1_024,
      mediaType: 'image/png',
    })
    expect(Taro.chooseImage).toHaveBeenCalledWith({
      count: 1,
      sizeType: ['original'],
      sourceType: ['album', 'camera'],
    })
  })

  it('用户取消选择时返回 undefined，其他平台错误继续抛出', async () => {
    ;(Taro.chooseImage as jest.Mock).mockRejectedValueOnce({ errMsg: 'chooseImage:fail cancel' })
    await expect(new TaroImagePickerAdapter().pickOne()).resolves.toBeUndefined()
    const error = { errMsg: 'chooseImage:fail permission denied' }
    ;(Taro.chooseImage as jest.Mock).mockRejectedValueOnce(error)
    await expect(new TaroImagePickerAdapter().pickOne()).rejects.toBe(error)
  })
})
