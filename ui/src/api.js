// Thin client for the SemanticLift FastAPI service.
const token = () => localStorage.getItem('semlift_token')

async function request(method, url, body, isForm) {
  const headers = {}
  if (token()) headers.Authorization = `Bearer ${token()}`
  if (body && !isForm) headers['Content-Type'] = 'application/json'
  const res = await fetch(url, { method, headers, body: isForm ? body : body ? JSON.stringify(body) : undefined })
  const text = await res.text()
  let data
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const err = new Error((data && data.detail) || res.statusText)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  get: (u) => request('GET', u),
  post: (u, b) => request('POST', u, b || {}),
  patch: (u, b) => request('PATCH', u, b),
  put: (u, b) => request('PUT', u, b),
  del: (u) => request('DELETE', u),
  upload: (files, reset) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f, f.name)
    return request('POST', `/api/uploads${reset ? '?reset=true' : ''}`, fd, true)
  },
  text: async (u) => {
    const res = await fetch(u, { headers: token() ? { Authorization: `Bearer ${token()}` } : {} })
    if (!res.ok) throw new Error(res.statusText)
    return res.text()
  },
}

export const enc = (id) => id.split('/').map(encodeURIComponent).join('/')
