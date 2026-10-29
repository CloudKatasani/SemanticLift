import React, { useEffect, useRef, useState } from 'react'

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

export default function Demo() {
  const video = useRef(null)
  const [meta, setMeta] = useState(null)
  const [missing, setMissing] = useState(false)
  const [now, setNow] = useState(0)

  useEffect(() => {
    fetch('/demo/chapters.json').then((r) => (r.ok ? r.json() : Promise.reject())).then(setMeta).catch(() => setMissing(true))
  }, [])

  const chapters = meta?.chapters || []
  const current = chapters.reduce((acc, c, i) => (now >= c.start ? i : acc), 0)
  const seek = (t) => {
    const v = video.current
    if (!v) return
    v.currentTime = t
    v.play().catch(() => {})
    v.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return (
    <div className="demo">
      <h1>Demo walkthrough</h1>
      <p className="lede">A {meta ? mmss(meta.duration) : 'two-minute'} tour of SemanticLift on the bundled sample Cognos estate: from the product overview and a client project, through the seven migration steps with real steward decisions, to design review, deployment and the audit trail. Click a chapter to jump to it.</p>
      {missing ? (
        <div className="empty">The demo video has not been generated in this installation. Run <span className="mono">scripts/demo/record_demo.sh</span> and rebuild the UI.</div>
      ) : (
        <div className="demo-grid">
          <div className="demo-player">
            <video ref={video} controls preload="metadata" poster="/demo/poster.jpg" onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}>
              <source src="/demo/semanticlift-demo.mp4" type="video/mp4" />
              Your browser cannot play this video. <a href="/demo/semanticlift-demo.mp4">Download it</a>.
            </video>
            {chapters[current] && (
              <div className="demo-now"><span className="flow-n">{current + 1}</span><div><b>{chapters[current].title}</b><div className="small muted">{chapters[current].text}</div></div></div>)}
          </div>
          <div className="card demo-chapters">
            <h4 style={{ marginTop: 0 }}>Chapters</h4>
            {chapters.map((c, i) => (
              <button key={c.title + i} className={`demo-ch ${i === current ? 'on' : ''}`} onClick={() => seek(c.start)}>
                <span className="mono">{mmss(c.start)}</span><span>{c.title}</span>
              </button>))}
          </div>
        </div>)}
      {!missing && chapters.length > 0 && (
        <section className="card" style={{ marginTop: 16 }}>
          <h2 style={{ marginTop: 0 }}>Transcript</h2>
          <ol className="demo-transcript">
            {chapters.map((c, i) => (
              <li key={c.title + i}><a href="#" onClick={(e) => { e.preventDefault(); seek(c.start) }}><b>{c.title}</b></a> <span className="muted small">{mmss(c.start)}</span><div>{c.text}</div></li>))}
          </ol>
          <p className="tiny muted">The video was recorded from this application on the bundled energy sample estate, with real decisions made on screen. Regenerate it after UI changes with <span className="mono">scripts/demo/record_demo.sh</span>.</p>
        </section>)}
    </div>
  )
}
