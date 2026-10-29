// Records the SemanticLift demo walkthrough video by driving the real app with Playwright.
//
//   scripts/demo/record_demo.sh            (starts a throw-away server, records, converts to MP4)
//
// Env: BASE (default http://127.0.0.1:8799), OUT_DIR (where the raw .webm and chapters.json go),
//      BUNDLE (sample Cognos export), CONFIG (estate configuration name).
// The script creates a demo project, uploads the bundle, runs the pipeline, then walks every page
// with on-screen captions and a visible cursor. chapters.json records when each chapter starts.
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'node:fs'
import { basename, join } from 'node:path'

const { chromium } = createRequire(import.meta.url)('playwright')   // resolves a global install via NODE_PATH

const BASE = process.env.BASE || 'http://127.0.0.1:8799'
const OUT = process.env.OUT_DIR || 'demo-out'
const BUNDLE = process.env.BUNDLE || 'samples/Cognos Lineage Input.zip'
const CONFIG = process.env.CONFIG || 'energy_estate'
const W = 1440, H = 810
mkdirSync(OUT, { recursive: true })

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

async function caption(title, text) {
  await page.evaluate(OVERLAY)
  await page.evaluate(([t, x]) => {
    const c = document.getElementById('demo-cap')
    c.style.opacity = 0
    setTimeout(() => { c.innerHTML = `<b>${t}</b>${x}`; c.style.opacity = 1 }, 250)
  }, [title, text])
}

async function chapter(title, hash, text, holdMs = 3500) {
  chapters.push({ title, start: Math.max(0, Math.round((Date.now() - t0) / 100) / 10), text })
  await page.goto(`${BASE}/#/${hash}`)
  await page.waitForLoadState('networkidle').catch(() => {})
  await pause(700)
  await caption(title, text)
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
await chapter('Meet SemanticLift', 'home',
  'Decades of Cognos reports hide a semantic layer. SemanticLift lifts it out onto the cloud data platform.', 4500)
await scroll(800, 6)
await caption('The problem', 'Report sprawl, business logic trapped in the BI tool, the same KPI with different numbers, unknown lineage.')
await pause(3500)
await scroll(650, 5)
await caption('How it works', 'Eight steps from estate to production: the tool does the analysis and generation, people make the decisions.')
await pause(3500)
await scroll(550, 5)
await caption('The lift, in numbers', 'Figures from the open project: 588 reports analysed, 85% fewer to migrate, 70 KPI conflicts surfaced before build.')
await pause(4000)

await chapter('Client projects', 'projects', 'Each client engagement is an isolated project, with its progress, roles and an audit trail.', 4000)

await chapter('Upload & run', 'ingest', 'Upload one Cognos export. Every file is detected and parsed, and stated counts are reconciled.', 3000)
await scroll(700, 5)
await pause(2000)

await chapter('Strategy & approach', 'strategy', 'The playbook: for each step why it matters, what SemanticLift does, the team guideline, the outcome and this project\u2019s figures.', 3500)
await scroll(900, 6)
await pause(1500)

await chapter('1. Report rationalization', 'rationalization', 'Every report gets Keep, Review, Consolidate or Retire, with the rule and evidence behind it.', 3000)
await point('select >> nth=2')
await page.locator('select').nth(2).selectOption('Review').catch(() => {})
await pause(1200)
await point('table:has(th:has-text("Consolidate into")) tbody tr', { click: true, nth: 0 })
await caption('1. Report rationalization', 'The steward reviews the evidence and decides: this one is kept. The decision is saved and audited.')
await point('.detail button:has-text("Keep")', { click: true })
await pause(2500)

await chapter('2. KPI lineage', 'kpi-lineage', 'Trace any KPI: KPI → Framework Manager item → reports → database → schema → table.', 2500)
await point('.obj', { click: true, nth: 2 })
await pause(3000)

await chapter('3. Common KPIs', 'common-kpis', 'KPIs that reports calculate differently are surfaced up front, and a steward approves the correct definition.', 3000)
await point('input[type=radio]', { click: true, nth: 0 })
await point('button:has-text("Approve selected definition")', { click: true })
await pause(2000)

await chapter('4. Databases & tables', 'sources', 'Only the tables surviving reports really read are in scope; tables used only by Review reports are flagged.', 4000)

await chapter('5. Logical data model', 'ldm', 'A conformed model of facts and dimensions, with join-path risks diagnosed.', 4500)

await chapter('6. Data products & semantic layer', 'products', 'Business logic leaves Cognos: semantic views, aggregated views, policies and data-product contracts.', 2500)
await point('.prod-card', { click: true, nth: 1 })
await scroll(700, 5)
await caption('Apply decisions', 'Saved decisions reach the design with one click: the pipeline re-runs in the background.')
await scroll(-700, 4)
await point('button:has-text("Apply decisions")', { click: true })
await page.waitForSelector('.banner', { state: 'detached', timeout: 60000 }).catch(() => {})
await pause(1500)
await point('button.tab:has-text("Aggregated views")', { click: true })
await caption('Aggregated views', 'A few pre-summarised tables answer the busiest reports from hundreds of rows instead of millions.')
await pause(3500)

await chapter('7. Object lineage', 'objects/CORE.FCT_BILLING', 'Every platform object traced: its sources, the semantic objects it feeds and the reports it serves.', 5000)

await chapter('Design review', 'review/CORE.DIM_DATE', 'Nothing deploys without a person. Approvers see the generated DDL next to the Cognos source.', 2500)
await point('button:has-text("Approve")', { click: true })
await pause(1500)

await chapter('Deploy & validate', 'deploy', 'Approved objects are committed to Git and deployed by CI; parity SQL proves the numbers still match.', 4000)

await chapter('Audit trail', 'audit', 'Every upload, run and decision, attributed to a person, ready for the client’s governance team.', 4000)

await chapter('Lift the meaning', 'home', 'SemanticLift: fewer reports, one truth per KPI, a governed semantic layer, proven.', 1500)
await scroll(5000, 10)
await pause(3500)

const total = Math.round((Date.now() - t0) / 100) / 10
const video = page.video()
await ctx.close()
await browser.close()
renameSync(await video.path(), join(OUT, 'semanticlift-demo.webm'))
writeFileSync(join(OUT, 'chapters.json'), JSON.stringify({ duration: total, project, chapters }, null, 2))
console.log(`recorded ${total}s, ${chapters.length} chapters`)
