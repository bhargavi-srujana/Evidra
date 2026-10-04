import { Info, TriangleAlert } from "lucide-react";
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
          className="h-12 animate-pulse rounded-xl bg-zinc-100 dark:bg-zinc-900"
        />
      ))}
    </div>
  );
}

export default function ResearchGaps({ gaps, className }: ResearchGapsProps) {
  if (gaps.length === 0) {
    return (
      <div
        className={cn(
          "flex items-start gap-2 rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300",
          className,
        )}
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
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
          key={`${i}-${gap.slice(0, 24)}`}
          className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100"
        >
          <TriangleAlert
            className="mt-0.5 h-4 w-4 shrink-0"
            aria-hidden="true"
          />
          <span>{gap}</span>
        </li>
      ))}
    </ul>
  );
}
