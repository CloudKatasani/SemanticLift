// Records the SemanticLift demo walkthrough video by driving the real app with Playwright.
//
//   scripts/demo/record_demo.sh            (starts a throw-away server, records, converts to MP4)
//
// Env: BASE (default http://127.0.0.1:8799), OUT_DIR (where the raw .webm and chapters.json go),
//      BUNDLE (sample Cognos export), CONFIG (estate configuration name).
// The script creates a demo project, uploads the bundle, runs the pipeline, then walks every page
// with on-screen captions and a visible cursor. chapters.json records when each chapter starts.
import { createRequire } from 'node:module'
import { existsSync, readFileSync, writeFileSync, mkdirSync, renameSync } from 'node:fs'
import { basename, join } from 'node:path'

const { chromium } = createRequire(import.meta.url)('playwright')   // resolves a global install via NODE_PATH

const BASE = process.env.BASE || 'http://127.0.0.1:8799'
const OUT = process.env.OUT_DIR || 'demo-out'
const BUNDLE = process.env.BUNDLE || 'samples/Cognos Lineage Input.zip'
const CONFIG = process.env.CONFIG || 'energy_estate'
const W = 1440, H = 810
mkdirSync(OUT, { recursive: true })
// captions and voice-over lines; durations.json (from narrate.py speak) makes each caption last as long as its line
const N = JSON.parse(readFileSync(new URL('./narration.json', import.meta.url), 'utf8'))
const DUR = existsSync(join(OUT, 'durations.json')) ? JSON.parse(readFileSync(join(OUT, 'durations.json'), 'utf8')) : {}

async function api(path, opts = {}, project) {
  const headers = { ...(opts.headers || {}) }
  if (project) headers['X-SemLift-Project'] = project
  const r = await fetch(BASE + path, { ...opts, headers })
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return r.json()
}

// ---------------------------------------------------------------- demo data
const project = (await api('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Cognos wave 1', client: 'Northwind Energy', description: 'Demo project on the bundled sample estate', config: CONFIG }) })).id
const fd = new FormData()
fd.append('files', new Blob([readFileSync(BUNDLE)]), basename(BUNDLE))
await api('/api/uploads', { method: 'POST', body: fd }, project)
await api('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: CONFIG }) }, project)
console.log('demo project ready:', project)

// ---------------------------------------------------------------- browser + overlay
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT, size: { width: W, height: H } } })
await ctx.addInitScript((pid) => { try { localStorage.setItem('semlift_project', pid) } catch {} }, project)
const page = await ctx.newPage()
const t0 = Date.now()
const chapters = []
const segments = []          // {key, start}: when each narration line starts, relative to the video
let speechEnds = 0
const pause = (ms) => page.waitForTimeout(ms)

const OVERLAY = () => {
  if (document.getElementById('demo-cap')) return
  const st = document.createElement('style')
  st.textContent = `
    #demo-cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:980px;z-index:99999;
      background:rgba(11,20,36,.92);color:#fff;border-radius:14px;padding:14px 22px;font:15px/1.5 Inter,Segoe UI,sans-serif;
      box-shadow:0 10px 30px rgba(0,0,0,.35);transition:opacity .35s;opacity:0;pointer-events:none}
    #demo-cap b{display:block;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#8fb6ff;margin-bottom:2px}
    #demo-cursor{position:fixed;left:0;top:0;width:22px;height:22px;border-radius:50%;z-index:100000;pointer-events:none;
      background:rgba(47,111,222,.35);border:2px solid #2f6fde;transform:translate(700px,400px);transition:transform .7s cubic-bezier(.3,.7,.2,1)}
    #demo-cursor.click{animation:dc .35s}
    @keyframes dc{50%{box-shadow:0 0 0 12px rgba(47,111,222,.25)}}`
  document.head.appendChild(st)
  const c = document.createElement('div'); c.id = 'demo-cap'; document.body.appendChild(c)
  const k = document.createElement('div'); k.id = 'demo-cursor'; document.body.appendChild(k)
}

async function waitSpeech() {
  const left = speechEnds - Date.now()
  if (left > 0) await pause(left)
}

async function caption(key) {
  await waitSpeech()
  const { title, text } = N[key]
  segments.push({ key, start: Math.round((Date.now() - t0 + 300) / 100) / 10 })
  speechEnds = Date.now() + 300 + (DUR[key] || 0) * 1000 + 500
  await page.evaluate(OVERLAY)
  await page.evaluate(([t, x]) => {
    const c = document.getElementById('demo-cap')
    c.style.opacity = 0
    setTimeout(() => { c.innerHTML = `<b>${t}</b>${x}`; c.style.opacity = 1 }, 250)
  }, [title, text])
}

async function chapter(key, hash, holdMs = 3500) {
  await waitSpeech()
  chapters.push({ title: N[key].title, start: Math.max(0, Math.round((Date.now() - t0) / 100) / 10), text: N[key].text })
  await page.goto(`${BASE}/#/${hash}`)
  await page.waitForLoadState('networkidle').catch(() => {})
  await pause(700)
  await caption(key)
  await pause(holdMs)
}

async function point(selector, { click = false, nth = 0 } = {}) {
  try {
    const el = page.locator(selector).nth(nth)
    await el.scrollIntoViewIfNeeded({ timeout: 4000 })
    const box = await el.boundingBox()
    if (!box) return false
    await page.evaluate(([x, y]) => { document.getElementById('demo-cursor').style.transform = `translate(${x}px,${y}px)` },
      [box.x + Math.min(box.width / 2, 60), box.y + box.height / 2])
    await pause(800)
    if (click) {
      await page.evaluate(() => { const k = document.getElementById('demo-cursor'); k.classList.remove('click'); void k.offsetWidth; k.classList.add('click') })
      await el.click({ timeout: 4000 })
      await pause(900)
    }
    return true
  } catch (e) {
    console.warn('skip', selector, e.message.split('\n')[0])
    return false
  }
}

async function scroll(px, steps = 6) {
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, px / steps); await pause(180) }
  await pause(600)
}

// ---------------------------------------------------------------- the walkthrough
await page.goto(`${BASE}/#/home`)
await page.waitForSelector('.home-hero')
await chapter('intro', 'home', 2500)
await scroll(800, 6)
await caption('problem')
await pause(2500)
await scroll(650, 5)
await caption('how')
await pause(2500)
await scroll(550, 5)
await caption('numbers')
await pause(2500)

await chapter('projects', 'projects', 2500)

await chapter('ingest', 'ingest', 2000)
await scroll(700, 5)

await chapter('strategy', 'strategy', 2000)
await scroll(900, 6)

await chapter('rationalization', 'rationalization', 1500)
await point('select >> nth=2')
await page.locator('select').nth(2).selectOption('Review').catch(() => {})
await pause(1200)
await point('table:has(th:has-text("Consolidate into")) tbody tr', { click: true, nth: 0 })
await caption('decide')
await point('.detail button:has-text("Keep")', { click: true })
await pause(1500)

await chapter('kpi_lineage', 'kpi-lineage', 1500)
await point('.obj', { click: true, nth: 2 })
await pause(2000)

await chapter('common_kpis', 'common-kpis', 1500)
await point('input[type=radio]', { click: true, nth: 0 })
await point('button:has-text("Approve selected definition")', { click: true })
await pause(1500)

await chapter('sources', 'sources', 3000)

await chapter('ldm', 'ldm', 3000)

await chapter('products', 'products', 1500)
await point('.prod-card', { click: true, nth: 1 })
await scroll(700, 5)
await caption('apply')
await scroll(-700, 4)
await point('button:has-text("Apply decisions")', { click: true })
await page.waitForSelector('.banner', { state: 'detached', timeout: 60000 }).catch(() => {})
await pause(1000)
await point('button.tab:has-text("Aggregated views")', { click: true })
await caption('aggregates')
await pause(2500)

await chapter('objects', 'objects/CORE.FCT_BILLING', 3500)

await chapter('review', 'review/CORE.DIM_DATE', 1500)
await point('button:has-text("Approve")', { click: true })
await pause(1500)

await chapter('deploy', 'deploy', 3000)

await chapter('audit', 'audit', 3000)

await chapter('outro', 'home', 1000)
await scroll(5000, 10)
await waitSpeech()
await pause(2000)

const total = Math.round((Date.now() - t0) / 100) / 10
const video = page.video()
await ctx.close()
await browser.close()
renameSync(await video.path(), join(OUT, 'semanticlift-demo.webm'))
writeFileSync(join(OUT, 'chapters.json'), JSON.stringify({ duration: total, project, chapters }, null, 2))
writeFileSync(join(OUT, 'segments.json'), JSON.stringify(segments, null, 2))
console.log(`recorded ${total}s, ${chapters.length} chapters`)
