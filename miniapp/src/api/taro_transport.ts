import Taro from '@tarojs/taro'

import { NetworkError, RequestCancelledError, TimeoutError } from './errors'
import type { HttpTransport, TransportRequest, TransportResponse } from './types'

function getFailureMessage(cause: unknown): string {
  if (typeof cause !== 'object' || cause === null || !('errMsg' in cause)) {
    return ''
  }
  return String(cause.errMsg).toLowerCase()
}

export class TaroHttpTransport implements HttpTransport {
  request(request: TransportRequest): Promise<TransportResponse> {
    return new Promise((resolve, reject) => {
      let settled = false

      const finish = (callback: () => void) => {
        if (settled) {
          return
        }
        settled = true
        request.signal?.removeEventListener('abort', abortRequest)
        callback()
      }

      const requestOptions: Taro.request.Option<unknown> = {
        url: request.url,
        method: request.method,
        header: request.headers,
        timeout: request.timeoutMs,
        success: (response) => {
          finish(() => {
            resolve({
              statusCode: response.statusCode,
              data: response.data,
              headers: response.header,
            })
          })
        },
        fail: (cause) => {
          finish(() => {
            const context = { operation: request.operation }
            if (getFailureMessage(cause).includes('timeout')) {
              reject(new TimeoutError(context, cause))
              return
            }
            reject(new NetworkError(context, cause))
          })
        },
      }
      if (request.body !== undefined) {
        requestOptions.data = request.body
      }
      const task = Taro.request<unknown>(requestOptions)

      function abortRequest() {
        task.abort()
        finish(() => reject(new RequestCancelledError({ operation: request.operation })))
      }

      if (request.signal?.aborted) {
        abortRequest()
        return
      }
      request.signal?.addEventListener('abort', abortRequest, { once: true })
    })
  }
}
