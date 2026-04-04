import { useState, useEffect, useRef } from 'react';

/**
 * VaultDoorSplash — Premium splash screen animation.
 *
 * Sequence (~3.5s):
 * 1. Faint E outline appears, dots visible
 * 2. Dots illuminate one by one
 * 3. Dots detach and trace a circular vault ring
 * 4. Circle completes, E flickers to full brightness
 * 5. Gold ping expands, "Eidolum" + tagline fade in
 * 6. Everything fades out, page revealed
 */
export default function VaultDoorSplash({ onComplete }) {
  const [stage, setStage] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const canvasRef = useRef(null);
  const rafRef = useRef(null);

  // Skip splash if already seen this session
  useEffect(() => {
    if (sessionStorage.getItem('eidolum_splash_seen')) {
      setDismissed(true);
      onComplete?.();
      return;
    }

    // Progress through stages
    const timers = [
      setTimeout(() => setStage(1), 100),   // E appears
      setTimeout(() => setStage(2), 500),   // Dots light up
      setTimeout(() => setStage(3), 800),   // Dots trace circle
      setTimeout(() => setStage(4), 1800),  // Circle complete, E flickers
      setTimeout(() => setStage(5), 2500),  // Ping + text
      setTimeout(() => setStage(6), 3000),  // Fade out
      setTimeout(() => {
        setDismissed(true);
        sessionStorage.setItem('eidolum_splash_seen', '1');
        onComplete?.();
      }, 3500),
    ];

    return () => timers.forEach(clearTimeout);
  }, []);

  // Canvas animation for dot trails
  useEffect(() => {
    if (stage < 3 || stage > 4 || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const size = 280;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const radius = 95;
    const gold = '#D4A843';

    // 9 dots from the E (3 per arm × 3 arms)
    const dotAngles = [
      -Math.PI * 0.4,  // top arm dots
      -Math.PI * 0.25,
      -Math.PI * 0.1,
      Math.PI * 0.05,  // middle arm dots
      Math.PI * 0.2,
      Math.PI * 0.35,
      Math.PI * 0.55,  // bottom arm dots
      Math.PI * 0.7,
      Math.PI * 0.85,
    ];

    let startTime = null;
    const duration = 1000; // 1s to trace the full circle

    function draw(timestamp) {
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;
      const progress = Math.min(elapsed / duration, 1);

      ctx.clearRect(0, 0, size, size);

      // Draw completed trail segments
      ctx.strokeStyle = gold;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.8;

      const trailProgress = progress;
      const fullCircle = Math.PI * 2;

      // Each dot traces a portion of the circle
      for (let i = 0; i < dotAngles.length; i++) {
        const dotProgress = Math.max(0, Math.min(1, (trailProgress - i * 0.05) / 0.6));
        if (dotProgress <= 0) continue;

        const startAngle = dotAngles[i];
        const arcLength = (fullCircle / dotAngles.length) * dotProgress;

        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, startAngle + arcLength);
        ctx.stroke();

        // Draw the dot at the leading edge
        if (dotProgress < 1) {
          const dotAngle = startAngle + arcLength;
          const dx = cx + radius * Math.cos(dotAngle);
          const dy = cy + radius * Math.sin(dotAngle);
          ctx.beginPath();
          ctx.arc(dx, dy, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = gold;
          ctx.globalAlpha = 1;
          ctx.fill();
          ctx.globalAlpha = 0.8;
        }
      }

      // If circle is complete, draw full ring
      if (progress >= 1) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.stroke();

        // Inner decorative ring
        ctx.globalAlpha = 0.15;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.arc(cx, cy, radius - 8, 0, Math.PI * 2);
        ctx.stroke();
      }

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(draw);
      }
    }

    rafRef.current = requestAnimationFrame(draw);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [stage]);

  if (dismissed) return null;

  // E flicker keyframes for stage 4
  const eOpacity = stage < 1 ? 0
    : stage < 4 ? 0.1
    : stage >= 5 ? 1
    : undefined; // Stage 4 uses CSS animation

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center"
      style={{
        backgroundColor: '#0d0f13',
        opacity: stage >= 6 ? 0 : 1,
        transform: stage >= 6 ? 'scale(0.95)' : 'scale(1)',
        transition: stage >= 6 ? 'opacity 0.5s ease-out, transform 0.5s ease-out' : 'none',
        pointerEvents: stage >= 6 ? 'none' : 'auto',
      }}
      onClick={() => {
        setDismissed(true);
        sessionStorage.setItem('eidolum_splash_seen', '1');
        onComplete?.();
      }}
    >
      <div className="flex flex-col items-center">
        {/* Canvas for dot trails + circle */}
        <div className="relative" style={{ width: 280, height: 280 }}>
          <canvas
            ref={canvasRef}
            style={{ width: 280, height: 280, position: 'absolute', top: 0, left: 0 }}
          />

          {/* E logo centered in the circle */}
          <div className="absolute inset-0 flex items-center justify-center">
            <svg
              viewBox="0 0 40 48"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              width={52}
              height={62}
              style={{
                opacity: eOpacity,
                animation: stage === 4 ? 'eFlicker 0.7s steps(1) forwards' : 'none',
              }}
            >
              {/* Vertical spine */}
              <line x1="5" y1="6" x2="5" y2="42" stroke="#D4A843" strokeWidth="4" strokeLinecap="round"/>
              {/* Top arm */}
              <line x1="5" y1="6" x2="26" y2="6" stroke="#D4A843" strokeWidth="4" strokeLinecap="round"/>
              {/* Middle arm */}
              <line x1="5" y1="24" x2="20" y2="24" stroke="#D4A843" strokeWidth="4" strokeLinecap="round"/>
              {/* Bottom arm */}
              <line x1="5" y1="42" x2="26" y2="42" stroke="#D4A843" strokeWidth="4" strokeLinecap="round"/>

              {/* Dots — visible in stages 1-2, hidden after */}
              {stage <= 2 && (
                <>
                  <circle cx="30" cy="6" r="2.2" fill="#D4A843" opacity={stage >= 2 ? 1 : 0.4} style={{ transition: 'opacity 0.1s' }}/>
                  <circle cx="34" cy="6" r="1.6" fill="#D4A843" opacity={stage >= 2 ? 0.8 : 0.2} style={{ transition: 'opacity 0.15s 0.05s' }}/>
                  <circle cx="37.5" cy="6" r="1.1" fill="#D4A843" opacity={stage >= 2 ? 0.5 : 0.1} style={{ transition: 'opacity 0.15s 0.1s' }}/>
                  <circle cx="24" cy="24" r="2.2" fill="#D4A843" opacity={stage >= 2 ? 1 : 0.4} style={{ transition: 'opacity 0.1s 0.1s' }}/>
                  <circle cx="27.5" cy="24" r="1.6" fill="#D4A843" opacity={stage >= 2 ? 0.8 : 0.2} style={{ transition: 'opacity 0.15s 0.15s' }}/>
                  <circle cx="30.5" cy="24" r="1.1" fill="#D4A843" opacity={stage >= 2 ? 0.5 : 0.1} style={{ transition: 'opacity 0.15s 0.2s' }}/>
                  <circle cx="30" cy="42" r="2.2" fill="#D4A843" opacity={stage >= 2 ? 1 : 0.4} style={{ transition: 'opacity 0.1s 0.2s' }}/>
                  <circle cx="34" cy="42" r="1.6" fill="#D4A843" opacity={stage >= 2 ? 0.8 : 0.2} style={{ transition: 'opacity 0.15s 0.25s' }}/>
                  <circle cx="37.5" cy="42" r="1.1" fill="#D4A843" opacity={stage >= 2 ? 0.5 : 0.1} style={{ transition: 'opacity 0.15s 0.3s' }}/>
                </>
              )}
            </svg>
          </div>

          {/* Gold ping ring — stage 5 */}
          {stage >= 5 && (
            <div
              className="absolute inset-0 flex items-center justify-center pointer-events-none"
              style={{ animation: 'goldPing 0.8s ease-out forwards' }}
            >
              <div style={{
                width: 190, height: 190, borderRadius: '50%',
                border: '1px solid #D4A843', opacity: 0,
              }} />
            </div>
          )}
        </div>

        {/* Text */}
        <div className="flex flex-col items-center mt-4" style={{
          opacity: stage >= 5 ? 1 : 0,
          transform: stage >= 5 ? 'translateY(0)' : 'translateY(8px)',
          transition: 'opacity 0.4s ease-out, transform 0.4s ease-out',
        }}>
          <span className="font-serif text-2xl" style={{ color: '#D4A843' }}>Eidolum</span>
          <span className="text-sm italic mt-1" style={{ color: '#D4A843', opacity: 0.6 }}>
            Truth is the only currency.
          </span>
        </div>
      </div>

      {/* CSS keyframes */}
      <style>{`
        @keyframes eFlicker {
          0% { opacity: 0.1; }
          10% { opacity: 0.4; }
          20% { opacity: 0.1; }
          30% { opacity: 0.6; }
          40% { opacity: 0.2; }
          55% { opacity: 0.8; }
          65% { opacity: 0.3; }
          80% { opacity: 0.9; }
          100% { opacity: 1; }
        }
        @keyframes goldPing {
          0% { transform: scale(1); opacity: 0.3; }
          100% { transform: scale(1.8); opacity: 0; }
        }
      `}</style>
    </div>
  );
}
