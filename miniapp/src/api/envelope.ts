import { ContractError } from './errors'
import type { ApiEnvelope, TransportResponse } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseEnvelope(
  response: TransportResponse,
  operation: string,
): ApiEnvelope<unknown> {
  const value = response.data
  if (
    !isRecord(value) ||
    typeof value.code !== 'number' ||
    typeof value.message !== 'string' ||
    !Object.prototype.hasOwnProperty.call(value, 'data')
  ) {
    throw new ContractError({ operation, statusCode: response.statusCode })
  }

  return {
    code: value.code,
    message: value.message,
    data: value.data,
  }
}
