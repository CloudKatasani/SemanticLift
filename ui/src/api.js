// Thin client for the SemanticLift FastAPI service.
// Every request carries the signed-in token (if any) and the selected client project.
const read = (k) => { try { return localStorage.getItem(k) } catch { return null } }
const token = () => read('semlift_token')
export const currentProject = () => read('semlift_project')
export function setProject(id) {
  try { id ? localStorage.setItem('semlift_project', id) : localStorage.removeItem('semlift_project') } catch { /* private mode */ }
}

function headers(extra) {
  const h = { ...(extra || {}) }
  if (token()) h.Authorization = `Bearer ${token()}`
  if (currentProject()) h['X-SemLift-Project'] = currentProject()
  return h
}

async function request(method, url, body, isForm) {
  const h = headers(body && !isForm ? { 'Content-Type': 'application/json' } : {})
  const res = await fetch(url, { method, headers: h, body: isForm ? body : body ? JSON.stringify(body) : undefined })
  const text = await res.text()
  let data
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!res.ok) {
    const err = new Error((data && data.detail) || res.statusText)
    err.status = res.status
    // permission and conflict errors are shown globally, so no page swallows them silently
    if (method !== 'GET' && [401, 403, 409].includes(res.status)) window.dispatchEvent(new CustomEvent('semlift:error', { detail: err.message }))
    throw err
  }
  return data
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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
    const res = await fetch(u, { headers: headers() })
    if (!res.ok) throw new Error(res.statusText)
    return res.text()
  },
  /** Download through fetch so the token and project header are sent (plain links cannot carry them). */
  download: async (u, filename) => {
    const res = await fetch(u, { headers: headers() })
    if (!res.ok) { window.dispatchEvent(new CustomEvent('semlift:error', { detail: `Download failed: ${res.statusText}` })); return }
    const a = document.createElement('a')
    a.href = URL.createObjectURL(await res.blob())
    a.download = filename || u.split('/').pop()
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 2000)
  },
  /** Submit a background pipeline run and wait for it; onTick receives the job while it runs. */
  runJob: async (kind, body, onTick) => {
    let job = await request('POST', `/api/jobs/${kind}`, body || {})
    while (job.status === 'queued' || job.status === 'running') {
      onTick && onTick(job)
      await sleep(1000)
      job = await request('GET', `/api/jobs/${job.id}`)
    }
    if (job.status === 'failed') throw new Error(job.error || 'run failed')
    return job.result
  },
}

export const enc = (id) => id.split('/').map(encodeURIComponent).join('/')
