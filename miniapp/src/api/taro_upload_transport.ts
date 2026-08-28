import Taro from '@tarojs/taro'

import { NetworkError, RequestCancelledError, TimeoutError } from './errors'
import type {
  FileUploadTransport,
  FileUploadTransportRequest,
  TransportResponse,
} from './types'

function getFailureMessage(cause: unknown): string {
  if (typeof cause !== 'object' || cause === null || !('errMsg' in cause)) return ''
  return String(cause.errMsg).toLowerCase()
}

function parseUploadData(value: string): unknown {
  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

export class TaroFileUploadTransport implements FileUploadTransport {
  upload(request: FileUploadTransportRequest): Promise<TransportResponse> {
    return new Promise((resolve, reject) => {
      let settled = false
      const finish = (callback: () => void) => {
        if (settled) return
        settled = true
        request.signal?.removeEventListener('abort', abortUpload)
        callback()
      }
      const task = Taro.uploadFile({
        url: request.url,
        filePath: request.filePath,
        name: request.name,
        header: request.headers,
        formData: request.formData,
        timeout: request.timeoutMs,
        success: (response) => finish(() => resolve({
          statusCode: response.statusCode,
          data: parseUploadData(response.data),
          headers: response.header ?? {},
        })),
        fail: (cause) => finish(() => {
          const context = { operation: request.operation }
          if (getFailureMessage(cause).includes('timeout')) {
            reject(new TimeoutError(context, cause))
            return
          }
          reject(new NetworkError(context, cause))
        }),
      })

      function abortUpload() {
        task.abort()
        finish(() => reject(new RequestCancelledError({ operation: request.operation })))
      }

      if (request.signal?.aborted) {
        abortUpload()
        return
      }
      request.signal?.addEventListener('abort', abortUpload, { once: true })
    })
  }
}
