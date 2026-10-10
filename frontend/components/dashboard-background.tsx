/**
 * Fixed backdrop for the Augmented Academic Dashboard: dark charcoal base
 * with a subtle translucent pattern of molecular structures and faint
 * academic text snippets. Purely decorative (aria-hidden, pointer-events-none).
 */
export default function DashboardBackground() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0">
      {/* Molecular lattice pattern */}
      <svg className="absolute inset-0 h-full w-full opacity-[0.055]">
        <defs>
          <pattern
            id="evidra-molecules"
            width="220"
            height="220"
            patternUnits="userSpaceOnUse"
          >
            {/* benzene-like ring */}
            <g
              fill="none"
              stroke="#a1a1aa"
              strokeWidth="1.2"
              opacity="0.9"
            >
              <polygon points="60,40 85,55 85,85 60,100 35,85 35,55" />
              <circle cx="60" cy="40" r="5" fill="#a1a1aa" stroke="none" />
              <circle cx="85" cy="85" r="5" fill="#a1a1aa" stroke="none" />
              <circle cx="35" cy="85" r="5" fill="#a1a1aa" stroke="none" />
              <line x1="85" y1="55" x2="130" y2="45" />
              <circle cx="130" cy="45" r="4" fill="#a1a1aa" stroke="none" />
              <line x1="60" y1="100" x2="60" y2="140" />
              <circle cx="60" cy="140" r="4" fill="#a1a1aa" stroke="none" />
              <line x1="60" y1="140" x2="100" y2="165" />
              <line x1="150" y1="150" x2="185" y2="130" />
              <circle cx="150" cy="150" r="6" fill="none" />
              <circle cx="185" cy="130" r="4" fill="#a1a1aa" stroke="none" />
            </g>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#evidra-molecules)" />
      </svg>

      {/* Faint academic text snippets + formulas, like the reference collage */}
      <div className="absolute inset-0 overflow-hidden opacity-[0.07]">
        {[
          "top-16 left-[6%] w-64 -rotate-3",
          "top-64 right-[4%] w-72 rotate-2",
          "bottom-40 left-[10%] w-80 rotate-1",
          "top-[45%] left-[45%] w-72 -rotate-1",
        ].map((pos) => (
          <div key={pos} className={`absolute ${pos} space-y-1.5`}>
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-1.5 rounded bg-neutral-400"
                style={{ width: `${92 - ((i * 13) % 30)}%` }}
              />
            ))}
          </div>
        ))}
        <p className="absolute right-[8%] top-[22%] rotate-3 font-mono text-xs text-neutral-300">
          CITATION 1 — Contradiction(0.82)
        </p>
        <p className="absolute bottom-[18%] left-[4%] -rotate-2 font-mono text-[11px] leading-relaxed text-neutral-300">
          OF — Contradiction Explorer, §
          <br />
          tibodies in the … villa of Evidence
        </p>
        <p className="absolute bottom-[24%] right-[10%] font-serif text-lg italic text-neutral-300">
          z = f(x) &nbsp;&nbsp; E = mc²
        </p>
        <p className="absolute right-[6%] top-[58%] font-serif text-sm italic text-neutral-300">
          d/dx ∫ π r² dx
        </p>
      </div>

      {/* Vignette to keep content legible */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_35%,rgba(0,0,0,0.55)_100%)]" />
    </div>
  );
}
