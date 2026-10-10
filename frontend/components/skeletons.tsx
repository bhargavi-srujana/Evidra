import { cn } from "@/lib/utils";

/**
 * Lightweight loading placeholders for the heavy visualization modules
 * (`evidence-graph` pulls @xyflow/react, `evidence-summary` pulls recharts).
 * Kept in this dependency-free module so routes can `next/dynamic`-import
 * the charts without statically pulling those libraries into the page
 * bundle just for the skeletons.
 */
export function EvidenceGraphSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading evidence graph"
      className="h-[380px] w-full animate-pulse rounded-2xl border border-neutral-800 bg-neutral-900/70"
    />
  );
}

export function EvidenceSummarySkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading evidence overview"
      className={cn(
        "rounded-[3px] bg-neutral-100 p-5",
        className,
      )}
    >
      <div className="h-4 w-40 animate-pulse rounded bg-neutral-300" />
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-lg bg-neutral-200"
          />
        ))}
      </div>
      <div className="mt-3 h-44 animate-pulse rounded-xl bg-neutral-200" />
    </div>
  );
}
