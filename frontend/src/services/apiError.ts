type PydanticError = {
  type?: string
  loc?: (string | number)[]
  msg?: string
  input?: unknown
  ctx?: Record<string, unknown>
  url?: string
}

type ApiErrorShape = {
  response?: {
    data?: {
      detail?: string | PydanticError[] | unknown
    }
  }
  message?: string
}

const formatPydanticError = (e: PydanticError): string => {
  const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
  const msg = e.msg ?? 'invalid value'
  return loc ? `${loc}: ${msg}` : msg
}

export function formatApiError(err: unknown, fallback = 'Request failed'): string {
  const e = err as ApiErrorShape
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => (d && typeof d === 'object' ? formatPydanticError(d as PydanticError) : String(d)))
    if (parts.length) return parts.join('; ')
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      // fall through
    }
  }
  if (typeof e?.message === 'string' && e.message) return e.message
  return fallback
}
