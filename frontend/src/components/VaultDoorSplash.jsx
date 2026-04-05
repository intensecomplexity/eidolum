import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * VaultDoorSplash — Luxury splash animation.
 *
 * Timeline (~4.9s):
 *  0–350ms   E fades in dim
 *  250–450   E dots brighten sequentially
 *  450–700   Dots fly outward to circle circumference
 *  700–1900  9 arc segments draw simultaneously (1.2s ease-in-out)
 *  1900–2700 E bars flicker independently to full brightness
 *  2200–2800 Gold pressure-wave ping (fires during late flicker)
 *  2200–2600 "Eidolum" text reveals (vertical clip from center)
 *  2400–2700 Tagline fades in
 *  2500–2800 Warm glow behind E fades in
 *  2700–4200 Reading hold (~1.5s)
 *  4200–4400 Text fades out
 *  4400–4700 Inner group scales to 0.9× and fades
 *  4600–4800 Background fades to transparent
 */

const GOLD = '#D4A843';

// Match the page background color for seamless transition
function getThemeBG() {
  const theme = localStorage.getItem('eidolum_theme') || document.documentElement.getAttribute('data-theme') || 'dark';
  return theme === 'light' ? '#f5f5f7' : '#0d0f13';
}
const BG = getThemeBG();

/* ── Easing ──────────────────────────────────────────────────── */
const easeInOut = t =>
  t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
const easeOut = t => 1 - Math.pow(1 - t, 3);

/* ── E Flicker keyframes per bar [ms, opacity] ───────────────── */
const FLICKER = [
  [0, 0], [30, 0.3], [110, 0.05], [150, 0.5],
  [250, 0.15], [310, 0.7], [390, 0.4], [430, 0.85], [490, 1.0],
];
function flickerAt(ms) {
  if (ms < 0) return 0.15; // pre-flicker: dim
  for (let i = FLICKER.length - 1; i >= 0; i--)
    if (ms >= FLICKER[i][0]) return FLICKER[i][1];
  return 0;
}

/* ── Geometry ────────────────────────────────────────────────── */
const CX = 150, CY = 150, R = 95;
const CIRC = 2 * Math.PI * R;   // ≈596.9
const SEG = CIRC / 9;            // ≈66.3
const ARC_DEG = 40;              // 360 / 9

// E logo: viewBox 40×48 scaled 1.25× and optically centered
// +3 SVG units rightward to compensate for left-heavy vertical spine
const ES = 1.25;
const EX = CX - (40 * ES) / 2 + 3;  // 128 (optically centered)
const EY = CY - (48 * ES) / 2;       // 120

// 9 dot source positions (E arm tips in splash SVG coords)
const SRC = [
  [EX + 30 * ES, EY + 6 * ES],    [EX + 34 * ES, EY + 6 * ES],    [EX + 37.5 * ES, EY + 6 * ES],
  [EX + 24 * ES, EY + 24 * ES],   [EX + 27.5 * ES, EY + 24 * ES], [EX + 30.5 * ES, EY + 24 * ES],
  [EX + 30 * ES, EY + 42 * ES],   [EX + 34 * ES, EY + 42 * ES],   [EX + 37.5 * ES, EY + 42 * ES],
];

// 9 target positions evenly spaced on circumference (clockwise from top)
const TGT = Array.from({ length: 9 }, (_, i) => {
  const a = -Math.PI / 2 + (i / 9) * Math.PI * 2;
  return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
});

/* ── Helpers ─────────────────────────────────────────────────── */
const clamp01 = v => Math.min(Math.max(v, 0), 1);
const prog = (ms, s, e) => clamp01((ms - s) / (e - s));
const lerp = (a, b, t) => a + (b - a) * t;

/* ── Component ───────────────────────────────────────────────── */
export default function VaultDoorSplash({ onComplete }) {
  const [gone, setGone] = useState(false);
  const r = useRef({ bars: [], arcs: [], eDots: [], dots: [] });
  const raf = useRef(null);
  const t0 = useRef(null);

  const finish = useCallback(() => {
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = null;
    setGone(true);
    sessionStorage.setItem('eidolum_splash_seen', '1');
    onComplete?.();
  }, [onComplete]);

  useEffect(() => {
    if (sessionStorage.getItem('eidolum_splash_seen')) { finish(); return; }

    // Skip for reduced-motion preference
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) { finish(); return; }

    t0.current = performance.now();
    const tick = now => {
      const ms = now - t0.current;
      render(ms, r.current);
      if (ms < 4900) raf.current = requestAnimationFrame(tick);
      else finish();
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [finish]);

  if (gone) return null;

  const dotR = i => [2.8, 2.0, 1.4][i % 3];
  const dotOp = i => [0.5, 0.3, 0.15][i % 3];

  return (
    <div
      ref={el => (r.current.bg = el)}
      onClick={finish}
      aria-hidden="true"
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        backgroundColor: BG,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', overflow: 'hidden',
      }}
    >
      <div
        ref={el => (r.current.inner = el)}
        style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          willChange: 'transform, opacity',
        }}
      >
        {/* ── Main SVG canvas ── */}
        <svg
          viewBox="0 0 300 300"
          style={{ width: 'min(280px, 75vw)', height: 'min(280px, 75vw)' }}
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <radialGradient id="eidolum-splash-glow">
              <stop offset="0%" stopColor={GOLD} stopOpacity="0.05" />
              <stop offset="100%" stopColor={GOLD} stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Warm glow behind E */}
          <circle
            ref={el => (r.current.glow = el)}
            cx={CX} cy={CY} r={55}
            fill="url(#eidolum-splash-glow)" opacity={0}
          />

          {/* 9 ring arc segments — same cx/cy/r guarantees zero-gap circle */}
          {Array.from({ length: 9 }, (_, i) => (
            <circle
              key={`arc-${i}`}
              ref={el => (r.current.arcs[i] = el)}
              cx={CX} cy={CY} r={R}
              stroke={GOLD} strokeWidth={2} fill="none"
              strokeDasharray={`${SEG} ${CIRC - SEG}`}
              strokeDashoffset={SEG}
              transform={`rotate(${-90 + i * ARC_DEG} ${CX} ${CY})`}
              opacity={0}
            />
          ))}

          {/* Decorative inner ring */}
          <circle
            ref={el => (r.current.decor = el)}
            cx={CX} cy={CY} r={R - 8}
            stroke={GOLD} strokeWidth={0.5} fill="none" opacity={0}
          />

          {/* E logo bars */}
          <g
            ref={el => (r.current.eGroup = el)}
            transform={`translate(${EX} ${EY}) scale(${ES})`}
            opacity={0}
          >
            <line ref={el => (r.current.bars[0] = el)} x1="5" y1="6" x2="5" y2="42" stroke={GOLD} strokeWidth="4" strokeLinecap="round" />
            <line ref={el => (r.current.bars[1] = el)} x1="5" y1="6" x2="26" y2="6" stroke={GOLD} strokeWidth="4" strokeLinecap="round" />
            <line ref={el => (r.current.bars[2] = el)} x1="5" y1="24" x2="20" y2="24" stroke={GOLD} strokeWidth="4" strokeLinecap="round" />
            <line ref={el => (r.current.bars[3] = el)} x1="5" y1="42" x2="26" y2="42" stroke={GOLD} strokeWidth="4" strokeLinecap="round" />
          </g>

          {/* E dots (visible before flight) */}
          <g ref={el => (r.current.eDotG = el)} opacity={0}>
            {SRC.map(([x, y], i) => (
              <circle
                key={`ed-${i}`}
                ref={el => (r.current.eDots[i] = el)}
                cx={x} cy={y} r={dotR(i)} fill={GOLD} opacity={dotOp(i)}
              />
            ))}
          </g>

          {/* Flying / circumference dots */}
          {SRC.map(([x, y], i) => (
            <circle
              key={`fd-${i}`}
              ref={el => (r.current.dots[i] = el)}
              cx={x} cy={y} r={2.5} fill={GOLD} opacity={0}
            />
          ))}

          {/* Ping ring — thick, pressure-wave feel */}
          <circle
            ref={el => (r.current.ping = el)}
            cx={CX} cy={CY} r={R}
            stroke={GOLD} strokeWidth={3.5} fill="none" opacity={0}
          />
        </svg>

        {/* ── Text ── */}
        <div
          ref={el => (r.current.text = el)}
          className="font-serif"
          style={{
            marginTop: 16, fontSize: 28, color: GOLD,
            letterSpacing: '0.04em',
            clipPath: 'inset(50% 0 50% 0)',
            opacity: 0,
            willChange: 'clip-path, opacity',
          }}
        >
          Eidolum
        </div>
        <div
          ref={el => (r.current.tag = el)}
          style={{
            marginTop: 6, fontStyle: 'italic', fontSize: 14, color: GOLD,
            opacity: 0, willChange: 'opacity',
          }}
        >
          Truth is the only currency.
        </div>
      </div>
    </div>
  );
}

/* ── requestAnimationFrame render loop ───────────────────────── */
function render(ms, r) {
  if (!r.bg) return;

  /* ═══ Phase 1: E appears dim (0 → 350ms) ═══ */
  const dimOp = lerp(0, 0.15, easeOut(prog(ms, 0, 350)));

  // During flicker (≥1900) eGroup is controlled by flicker logic
  if (ms < 1900) r.eGroup?.setAttribute('opacity', String(dimOp));
  if (ms < 450)  r.eDotG?.setAttribute('opacity', String(dimOp));

  /* ═══ Phase 2: E dots brighten (250 → 450ms) ═══ */
  if (ms >= 250 && ms < 450) {
    const p = prog(ms, 250, 450);
    for (let i = 0; i < 9; i++) {
      const dp = clamp01((p - i * 0.06) / 0.35);
      const base = [0.5, 0.3, 0.15][i % 3];
      r.eDots[i]?.setAttribute('opacity', String(lerp(base, 1, easeOut(dp))));
    }
  }

  /* ═══ Phase 3: Dots fly to circumference (450 → 700ms) ═══ */
  if (ms >= 450 && ms < 700) {
    r.eDotG?.setAttribute('opacity', '0');
    const p = easeInOut(prog(ms, 450, 700));
    for (let i = 0; i < 9; i++) {
      const d = r.dots[i]; if (!d) continue;
      d.setAttribute('cx', String(lerp(SRC[i][0], TGT[i][0], p)));
      d.setAttribute('cy', String(lerp(SRC[i][1], TGT[i][1], p)));
      d.setAttribute('opacity', '1');
    }
  }

  /* ═══ Phase 4: Ring draws (700 → 1900ms, 1.2s ease-in-out) ═══ */
  if (ms >= 700) {
    const p = easeInOut(prog(ms, 700, 1900));

    // Reveal arc segments (9 circles, same geometry → perfect ring)
    for (let i = 0; i < 9; i++) {
      const arc = r.arcs[i]; if (!arc) continue;
      arc.setAttribute('opacity', '1');
      arc.setAttribute('stroke-dashoffset', String(SEG * (1 - p)));
    }

    // Dots ride the leading edge of their arc segment
    if (ms < 1900) {
      for (let i = 0; i < 9; i++) {
        const d = r.dots[i]; if (!d) continue;
        const a0 = -Math.PI / 2 + (i / 9) * Math.PI * 2;
        const angle = a0 + p * (Math.PI * 2 / 9);
        d.setAttribute('cx', String(CX + R * Math.cos(angle)));
        d.setAttribute('cy', String(CY + R * Math.sin(angle)));
      }
    }
  }

  // Dots fade after ring completes
  if (ms >= 1900 && ms < 2100) {
    const fade = clamp01((ms - 1900) / 200);
    for (const d of r.dots) d?.setAttribute('opacity', String(1 - fade));
  } else if (ms >= 2100) {
    for (const d of r.dots) d?.setAttribute('opacity', '0');
  }

  // Decorative inner ring fades in
  if (ms >= 1900) {
    r.decor?.setAttribute('opacity', String(lerp(0, 0.15, easeOut(prog(ms, 1900, 2200)))));
  }

  /* ═══ Phase 5: E flicker (1900 → 2700ms, 0.8s) ═══ */
  if (ms >= 1900) {
    r.eGroup?.setAttribute('opacity', '1');
    const base = ms - 1900;
    for (let i = 0; i < 4; i++) {
      const op = ms >= 2700 ? 1 : flickerAt(base - i * 40);
      r.bars[i]?.setAttribute('opacity', String(op));
    }
  }

  // Warm glow behind E
  if (ms >= 2500) {
    r.glow?.setAttribute('opacity', String(easeOut(prog(ms, 2500, 2800))));
  }

  /* ═══ Phase 6: Ping + text (2200ms — fires during late flicker) ═══ */
  if (ms >= 2200 && ms < 2900) {
    const p = easeOut(prog(ms, 2200, 2800));
    if (r.ping) {
      r.ping.setAttribute('r', String(R * lerp(1, 1.8, p)));
      r.ping.setAttribute('opacity', String(lerp(0.5, 0, p)));
      r.ping.setAttribute('stroke-width', String(lerp(3.5, 1.5, p)));
    }
  }

  // "Eidolum" — vertical clip reveal from center
  if (r.text && ms >= 2200) {
    r.text.style.opacity = '1';
    const inset = lerp(50, 0, easeOut(prog(ms, 2200, 2600)));
    r.text.style.clipPath = `inset(${inset}% 0 ${inset}% 0)`;
  }

  // Tagline
  if (r.tag && ms >= 2400) {
    r.tag.style.opacity = String(lerp(0, 0.6, easeOut(prog(ms, 2400, 2700))));
  }

  /* ═══ Phase 7: Staggered fadeout (after 1.5s reading hold) ═══ */

  // Text fades first (4200 → 4400ms)
  if (ms >= 4200) {
    const p = prog(ms, 4200, 4400);
    if (r.text) r.text.style.opacity = String(1 - p);
    if (r.tag)  r.tag.style.opacity = String(0.6 * (1 - p));
  }

  // Circle + E scale to 0.9× and fade (4400 → 4700ms)
  if (r.inner && ms >= 4400) {
    const p = easeOut(prog(ms, 4400, 4700));
    r.inner.style.transform = `scale(${lerp(1, 0.9, p)})`;
    r.inner.style.opacity = String(1 - p);
  }

  // Background fades to transparent (4600 → 4800ms)
  if (r.bg && ms >= 4600) {
    const p = prog(ms, 4600, 4800);
    r.bg.style.opacity = String(1 - p);
    if (p >= 1) r.bg.style.pointerEvents = 'none';
  }
}
