import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface ResearchGapsProps {
  gaps: string[];
  className?: string;
}

export function ResearchGapsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading research gaps" className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="h-12 animate-pulse rounded-xl border border-neutral-800 bg-neutral-900/70"
        />
      ))}
    </div>
  );
}

/**
 * Corpus research gaps as neutral glass info cards (informational — not
 * warnings, so no alert styling).
 */
export default function ResearchGaps({ gaps, className }: ResearchGapsProps) {
  if (gaps.length === 0) {
    return (
      <div
        className={cn(
          "flex items-start gap-2 rounded-2xl border border-neutral-700/70 bg-neutral-900/70 p-4 text-sm text-neutral-300 backdrop-blur-lg",
          className,
        )}
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" aria-hidden="true" />
        <span>
          No evidence gaps flagged for this corpus — coverage looks reasonably
          broad.
        </span>
      </div>
    );
  }

  return (
    <ul className={cn("space-y-2", className)}>
      {gaps.map((gap, i) => (
        <li
          key={`${i}-${gap.length}-${gap.slice(0, 48)}`}
          className="flex items-start gap-2.5 rounded-xl border border-neutral-700/70 bg-neutral-900/70 p-3.5 text-sm leading-relaxed text-neutral-300 backdrop-blur-lg"
        >
          <Info
            className="mt-0.5 h-4 w-4 shrink-0 text-sky-400"
            aria-hidden="true"
          />
          <span>{gap}</span>
        </li>
      ))}
    </ul>
  );
}
