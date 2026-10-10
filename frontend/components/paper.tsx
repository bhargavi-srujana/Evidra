import type { ReactNode } from "react";
import { ArrowUp, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface PaperDocProps {
  children: ReactNode;
  className?: string;
  tilt?: "left" | "right" | "none";
  staple?: boolean;
}

/**
 * Overlapping paper document: light sheet with a subtle curled top-right
 * corner, a staple clipped on the top edge, a slight tilt, and one stacked
 * sheet behind.
 */
export function PaperDoc({
  children,
  className,
  tilt = "none",
  staple = false,
}: PaperDocProps) {
  return (
    <div
      className={cn(
        "relative",
        tilt === "left" && "-rotate-[0.4deg]",
        tilt === "right" && "rotate-[0.4deg]",
      )}
    >
      {/* single stacked sheet behind */}
      <div
        aria-hidden="true"
        className="absolute inset-0 translate-x-1 translate-y-1 rounded-[3px] bg-neutral-300/60"
      />
      <div
        className={cn(
          "relative overflow-hidden rounded-[3px] bg-neutral-100 text-neutral-900 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.75)]",
          className,
        )}
      >
        {/* curled top-right corner */}
        <div
          aria-hidden="true"
          className="absolute right-0 top-0 h-7 w-7"
          style={{
            background:
              "linear-gradient(to bottom left, #fafafa 46%, #d4d4d8 50%, #a1a1aa 100%)",
            clipPath: "polygon(100% 0, 0 0, 100% 100%)",
            filter: "drop-shadow(-1px 1px 1px rgba(0,0,0,0.3))",
          }}
        />
        {children}
      </div>
      {staple ? (
        <div
          aria-hidden="true"
          className="absolute -top-3 left-10 z-10 flex h-7 w-5 items-start justify-center rounded-[3px] bg-gradient-to-b from-neutral-300 via-neutral-400 to-neutral-500 shadow-[0_2px_4px_rgba(0,0,0,0.45)]"
        >
          <div className="mt-1.5 h-3.5 w-[3px] rounded-full bg-neutral-600/60" />
        </div>
      ) : null}
    </div>
  );
}

type GlyphDirection = "increases" | "decreases" | "no_effect" | "conditional" | "unclear" | string;

/**
 * Tiny direction glyph for finding snippets: green up arrow, yellow "C",
 * red X, grey "?" fallback.
 */
export function DirectionGlyph({ direction }: { direction: GlyphDirection }) {
  if (direction === "increases") {
    return (
      <span
        title="Positive"
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-green-600 text-white"
      >
        <ArrowUp className="h-3 w-3" aria-hidden="true" strokeWidth={3} />
      </span>
    );
  }
  if (direction === "decreases" || direction === "no_effect") {
    return (
      <span
        title={direction === "no_effect" ? "No effect" : "Negative"}
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-600 text-white"
      >
        <X className="h-3 w-3" aria-hidden="true" strokeWidth={3} />
      </span>
    );
  }
  if (direction === "conditional") {
    return (
      <span
        title="Conditional"
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-yellow-500 text-[11px] font-extrabold text-neutral-900"
      >
        C
      </span>
    );
  }
  return (
    <span
      title="Unclear"
      className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-neutral-400 text-[11px] font-extrabold text-neutral-800"
    >
      ?
    </span>
  );
}

/** Shared glass-panel style for major dashboard cards. */
export const glassPanel =
  "rounded-2xl border border-neutral-700/70 bg-neutral-900/70 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.75)] backdrop-blur-lg";
