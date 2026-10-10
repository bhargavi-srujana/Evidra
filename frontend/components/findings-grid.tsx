"use client";

import { useMemo } from "react";
import type { Claim } from "@/lib/types";
import { DirectionGlyph, PaperDoc } from "@/components/paper";
import { cn } from "@/lib/utils";

interface FindingsGridProps {
  claims: Claim[];
  className?: string;
}

/**
 * Summary of Findings: top claims rendered as small overlapping paper
 * snippets, each with a tiny direction glyph.
 */
export default function FindingsGrid({ claims, className }: FindingsGridProps) {
  const top = useMemo(
    () =>
      [...claims]
        .sort((a, b) => b.confidence_score - a.confidence_score)
        .slice(0, 6),
    [claims],
  );

  if (top.length === 0) {
    return (
      <p role="status" className="text-sm text-neutral-400">
        No findings extracted yet — claim snippets will appear here.
      </p>
    );
  }

  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 xl:grid-cols-3", className)}>
      {top.map((claim, i) => (
        <PaperDoc
          key={claim.claim_id}
          tilt={i % 2 === 0 ? "left" : "right"}
          className="p-3.5"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
              Finding {i + 1}
            </p>
            <DirectionGlyph direction={claim.effect_direction} />
          </div>
          <p className="mt-1.5 line-clamp-4 text-[13px] leading-snug text-neutral-800">
            {claim.conclusion && claim.conclusion !== "Unspecified in provided text"
              ? claim.conclusion
              : claim.text}
          </p>
          <p className="mt-2 flex items-center justify-between text-[11px] text-neutral-500">
            <span className="truncate font-mono" title={claim.study_id}>
              {claim.study_id.slice(0, 14)}…
            </span>
            <span className="shrink-0 font-semibold">
              {Number.isFinite(claim.confidence_score)
                ? `${Math.round(claim.confidence_score * 100)}%`
                : "—"}
            </span>
          </p>
        </PaperDoc>
      ))}
    </div>
  );
}
