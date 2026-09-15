import { createApiClient } from '@/api'
import { AttentionApi, type AttentionSummary } from '@/api/endpoints/attention'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let api: AttentionApi | undefined
export function getAttentionApi(): AttentionApi {
  api ??= new AttentionApi(createApiClient(getDefaultAuthRuntime().session))
  return api
}

export interface AttentionState {
  readonly identity?: string
  readonly summary?: AttentionSummary
  readonly error?: string
}

/** 跨入口复用同一份汇总；账号切换使旧请求立即失效。 */
export class AttentionStore {
  state: AttentionState = {}
  private listeners = new Set<() => void>()
  private generation = 0
  private active?: Promise<void>

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  setIdentity(identity?: string): void {
    if (identity === this.state.identity) return
    this.generation += 1
    this.active = undefined
    this.state = { identity }
    this.emit()
  }

  refresh = (admin: boolean, source?: Pick<AttentionApi, 'summary'>): Promise<void> => {
    if (!this.state.identity) return Promise.resolve()
    if (this.active) return this.active
    const generation = this.generation
    const request = Promise.resolve().then(() => (source ?? getAttentionApi()).summary(admin)).then((summary) => {
      if (generation !== this.generation) return
      this.state = { identity: this.state.identity, summary }
      this.emit()
    }).catch(() => {
      if (generation !== this.generation) return
      this.state = { ...this.state, error: this.state.summary ? '提醒更新失败，当前为上次数据' : '提醒暂不可用，请稍后刷新' }
      this.emit()
    }).finally(() => { if (this.active === request) this.active = undefined })
    this.active = request
    return request
  }

  invalidate(admin: boolean): void {
    this.generation += 1
    this.active = undefined
    void this.refresh(admin)
  }

  private emit(): void { this.listeners.forEach((listener) => listener()) }
}

export const attentionStore = new AttentionStore()
