const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

const TOKEN_KEY = 'agent_token'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

async function parseError(res, fallback) {
  try {
    const data = await res.json()
    if (data && data.detail) return data.detail
  } catch {
    // 响应体不是 JSON，沿用默认提示
  }
  return fallback
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    // token 失效时清理，上层据此退回登录页
    if (res.status === 401) setToken(null)
    throw new ApiError(await parseError(res, `请求失败（${res.status}）`), res.status)
  }
  return res.json()
}

export function register(username, password) {
  return request('/register', { method: 'POST', body: { username, password } })
}

export async function login(username, password) {
  // FastAPI 的 OAuth2PasswordRequestForm 只接受 form-data
  const form = new URLSearchParams()
  form.set('username', username)
  form.set('password', password)

  const res = await fetch(`${BASE_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  })

  if (!res.ok) {
    throw new ApiError(await parseError(res, '登录失败'), res.status)
  }

  const data = await res.json()
  setToken(data.access_token)
  return data
}

export function fetchMe() {
  return request('/me')
}

export function clearSession(sessionId) {
  return request(`/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/**
 * 读取后端 SSE 流，每收到一个事件回调一次。
 * 用 fetch 而非 EventSource，因为后者无法携带 Authorization 头。
 */
export async function chatStream({ message, sessionId, onEvent, signal }) {
  const res = await fetch(`${BASE_URL}/agent/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  })

  if (!res.ok) {
    if (res.status === 401) setToken(null)
    throw new ApiError(await parseError(res, `请求失败（${res.status}）`), res.status)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6)
      if (payload === '[DONE]') continue
      try {
        onEvent(JSON.parse(payload))
      } catch {
        // 忽略无法解析的片段
      }
    }
  }
}
