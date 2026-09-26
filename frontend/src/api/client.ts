/** 统一请求封装：拼后端地址、超时中断、抛带可读说明的错误，供页面渲染重试入口。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 默认 10 秒未响应即判定超时，避免页面一直停在加载中。 */
export const DEFAULT_TIMEOUT_MS = 10_000

export class RequestError extends Error {
  status: number | null
  constructor(message: string, status: number | null = null) {
    super(message)
    this.name = 'RequestError'
    this.status = status
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail.trim()
    }
  } catch {
    // 非 JSON 响应时回退到状态码说明
  }
  return `服务暂不可用（HTTP ${response.status}），请稍后重试`
}

export function request(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)

  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    signal: controller.signal,
    ...init,
  })
    .catch((error: unknown) => {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new RequestError(`请求超时（超过 ${Math.round(timeoutMs / 1000)} 秒未响应），请检查网络后重试`, null)
      }
      const detail = error instanceof Error ? error.message : '请求未送达'
      throw new RequestError(`接口请求失败：${detail}，请检查后端服务后重试`, null)
    })
    .then((response) => {
      window.clearTimeout(timer)
      if (!response.ok) {
        return readDetail(response).then((detail) => {
          throw new RequestError(detail, response.status)
        })
      }
      return response
    })
}

export async function fetchJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const response = await request(path, init)
  return (await response.json()) as T
}
