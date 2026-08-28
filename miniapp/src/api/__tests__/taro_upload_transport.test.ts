import Taro from '@tarojs/taro'

import { RequestCancelledError, TimeoutError } from '../errors'
import { TaroFileUploadTransport } from '../taro_upload_transport'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { uploadFile: jest.fn() },
}))

describe('TaroFileUploadTransport', () => {
  afterEach(() => jest.clearAllMocks())

  it('把 uploadFile 字符串响应解析为统一 TransportResponse', async () => {
    ;(Taro.uploadFile as jest.Mock).mockImplementation((options) => {
      options.success({
        statusCode: 201,
        data: JSON.stringify({ code: 0, message: 'success', data: { id: 31 } }),
        header: { 'content-type': 'application/json' },
        errMsg: 'uploadFile:ok',
      })
      return { abort: jest.fn() }
    })
    const transport = new TaroFileUploadTransport()
    await expect(transport.upload(request())).resolves.toEqual({
      statusCode: 201,
      data: { code: 0, message: 'success', data: { id: 31 } },
      headers: { 'content-type': 'application/json' },
    })
    expect(Taro.uploadFile).toHaveBeenCalledWith(expect.objectContaining({
      url: 'https://api.example.com/api/v1/admin/products/7/images',
      filePath: 'wxfile://cover.png',
      name: 'file',
      formData: { is_cover: 'true' },
    }))
  })

  it('把平台 timeout 分类为 TimeoutError', async () => {
    ;(Taro.uploadFile as jest.Mock).mockImplementation((options) => {
      options.fail({ errMsg: 'uploadFile:fail timeout' })
      return { abort: jest.fn() }
    })
    await expect(new TaroFileUploadTransport().upload(request()))
      .rejects.toBeInstanceOf(TimeoutError)
  })

  it('AbortSignal 只中止当前上传并返回 RequestCancelledError', async () => {
    const abort = jest.fn()
    ;(Taro.uploadFile as jest.Mock).mockReturnValue({ abort })
    const controller = new AbortController()
    const promise = new TaroFileUploadTransport().upload({ ...request(), signal: controller.signal })
    controller.abort()
    await expect(promise).rejects.toBeInstanceOf(RequestCancelledError)
    expect(abort).toHaveBeenCalledTimes(1)
  })
})

function request() {
  return {
    operation: 'uploadProductImage',
    url: 'https://api.example.com/api/v1/admin/products/7/images',
    filePath: 'wxfile://cover.png',
    name: 'file',
    headers: { Authorization: 'Bearer token' },
    formData: { is_cover: 'true' },
    timeoutMs: 15_000,
  }
}
