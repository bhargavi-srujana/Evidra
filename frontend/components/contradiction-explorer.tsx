"use client";

import { useMemo, useState } from "react";
import {
  ChevronDown,
  FlaskConical,
  GitCompareArrows,
  Lightbulb,
  Microscope,
} from "lucide-react";
import type {
  Claim,
  ImpactLevel,
  PairwiseContradiction,
  Study,
} from "@/lib/types";
import { EFFECT_BADGE, effectForStudy, formatEffectLabel } from "@/lib/effects";
import { cn } from "@/lib/utils";

interface ContradictionExplorerProps {
  contradictions: PairwiseContradiction[];
  studies: Study[];
  claims: Claim[];
  className?: string;
}

const IMPACT_STYLES: Record<ImpactLevel, string> = {
  HIGH: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  MEDIUM: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  LOW: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
};

/** Fixed display order for PICO rows; extras from the backend append after. */
const DIMENSION_ORDER = [
  "Population",
  "Task Type",
  "Measurement Metric",
  "Sample Size",
  "Study Duration",
  "Intervention",
  "Control Group",
  "Study Type / Setting",
];

function StudyMiniCard({
  study,
  claims,
}: {
  study: Study;
  claims: Claim[];
}) {
  const direction = effectForStudy(study.study_id, claims);
  return (
    <div className="flex-1 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="text-sm font-semibold leading-snug text-zinc-900 dark:text-zinc-50">
          {study.title}
        </h4>
        {direction ? (
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
              EFFECT_BADGE[direction],
            )}
          >
            {formatEffectLabel(direction)}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        {study.authors.map((a) => a.name).join(", ") || "Unknown authors"} ·{" "}
        {study.year}
        {study.venue ? ` · ${study.venue}` : ""}
      </p>
      {claims.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {claims.map((claim) => (
            <li
              key={claim.claim_id}
              className="rounded-lg bg-zinc-50 px-2 py-1.5 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300"
            >
              {claim.text}
              <span className="ml-1 font-mono text-[10px] text-zinc-400">
                {(claim.confidence_score * 100).toFixed(0)}%
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ContradictionItem({
  contradiction,
  studyA,
  studyB,
  claimsA,
  claimsB,
  open,
  onToggle,
}: {
  contradiction: PairwiseContradiction;
  studyA: Study | undefined;
  studyB: Study | undefined;
  claimsA: Claim[];
  claimsB: Claim[];
  open: boolean;
  onToggle: () => void;
}) {
  const orderedDiffs = useMemo(() => {
    const rank = (dim: string) => {
      const i = DIMENSION_ORDER.indexOf(dim);
      return i === -1 ? DIMENSION_ORDER.length : i;
    };
    return [...contradiction.method_differences].sort(
      (a, b) => rank(a.dimension) - rank(b.dimension),
    );
  }, [contradiction]);

  const highCount = contradiction.method_differences.filter(
    (d) => d.impact_level === "HIGH",
  ).length;

  return (
    <li className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 bg-zinc-50 px-4 py-3 text-left text-sm font-medium text-zinc-900 hover:bg-zinc-100 dark:bg-zinc-900 dark:text-zinc-50 dark:hover:bg-zinc-800"
      >
        <GitCompareArrows
          className="h-4 w-4 shrink-0 text-zinc-500"
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate">
          {contradiction.study_a_id} ↔ {contradiction.study_b_id}
        </span>
        {highCount > 0 ? (
          <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-300">
            {highCount} HIGH
          </span>
        ) : null}
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-zinc-400 transition-transform",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>

      {open ? (
        <div className="space-y-4 bg-white p-4 dark:bg-zinc-950">
          <div className="flex flex-col gap-3 md:flex-row">
            {studyA ? (
              <StudyMiniCard study={studyA} claims={claimsA} />
            ) : (
              <p className="text-xs text-zinc-500">
                Study {contradiction.study_a_id} not in retrieved set.
              </p>
            )}
            {studyB ? (
              <StudyMiniCard study={studyB} claims={claimsB} />
            ) : (
              <p className="text-xs text-zinc-500">
                Study {contradiction.study_b_id} not in retrieved set.
              </p>
            )}
          </div>

          {orderedDiffs.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-xs">
                <caption className="pb-2 text-left font-medium text-zinc-500 dark:text-zinc-400">
                  <span className="inline-flex items-center gap-1.5">
                    <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
                    PICO differences
                  </span>
                </caption>
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <th scope="col" className="py-1.5 pr-2 font-medium">
                      Dimension
                    </th>
                    <th scope="col" className="py-1.5 pr-2 font-medium">
                      Study A
                    </th>
                    <th scope="col" className="py-1.5 pr-2 font-medium">
                      Study B
                    </th>
                    <th scope="col" className="py-1.5 font-medium">
                      Impact
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {orderedDiffs.map((d) => (
                    <tr
                      key={d.dimension}
                      className="border-b border-zinc-100 last:border-0 dark:border-zinc-900"
                    >
                      <td className="py-1.5 pr-2 font-medium text-zinc-900 dark:text-zinc-100">
                        {d.dimension}
                      </td>
                      <td className="py-1.5 pr-2 text-zinc-600 dark:text-zinc-300">
                        {d.study_a_value ?? "Not reported"}
                      </td>
                      <td className="py-1.5 pr-2 text-zinc-600 dark:text-zinc-300">
                        {d.study_b_value ?? "Not reported"}
                      </td>
                      <td className="py-1.5">
                        <span
                          className={cn(
                            "inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold",
                            IMPACT_STYLES[d.impact_level],
                          )}
                        >
                          {d.impact_level}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 dark:border-sky-900 dark:bg-sky-950">
            <h4 className="inline-flex items-center gap-1.5 text-xs font-semibold text-sky-900 dark:text-sky-200">
              <Microscope className="h-3.5 w-3.5" aria-hidden="true" />
              Observed facts
            </h4>
            <p className="mt-1 text-sm leading-relaxed text-sky-900 dark:text-sky-100">
              {contradiction.observed_difference}
            </p>
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950">
            <h4 className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-900 dark:text-amber-200">
              <Lightbulb className="h-3.5 w-3.5" aria-hidden="true" />
              Possible explanation
            </h4>
            <p className="mt-1 text-sm leading-relaxed text-amber-900 dark:text-amber-100">
              {contradiction.hypothesized_explanation}
            </p>
          </div>
        </div>
      ) : null}
    </li>
  );
}

export function ContradictionExplorerSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading contradictions" className="space-y-2">
      {Array.from({ length: 2 }).map((_, i) => (
        <div
          key={i}
          className="h-24 animate-pulse rounded-xl bg-zinc-100 dark:bg-zinc-900"
        />
      ))}
    </div>
  );
}

export default function ContradictionExplorer({
  contradictions,
  studies,
  claims,
  className,
}: ContradictionExplorerProps) {
  const [openIds, setOpenIds] = useState<Set<string>>(
    () =>
      new Set(
        contradictions.length > 0
          ? [`${contradictions[0].study_a_id}-${contradictions[0].study_b_id}-0`]
          : [],
      ),
  );

  const studyById = useMemo(
    () => new Map(studies.map((s) => [s.study_id, s])),
    [studies],
  );
  const claimsFor = useMemo(() => {
    const map = new Map<string, Claim[]>();
    for (const claim of claims) {
      const list = map.get(claim.study_id) ?? [];
      list.push(claim);
      map.set(claim.study_id, list);
    }
    return map;
  }, [claims]);

  const toggle = (id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (contradictions.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No contradictions detected — the retrieved claims do not oppose each
        other on a shared topic.
      </p>
    );
  }

  return (
    <ul className={cn("space-y-3", className)}>
      {contradictions.map((contradiction, i) => {
        const id = `${contradiction.study_a_id}-${contradiction.study_b_id}-${i}`;
        return (
          <ContradictionItem
            key={id}
            contradiction={contradiction}
            studyA={studyById.get(contradiction.study_a_id)}
            studyB={studyById.get(contradiction.study_b_id)}
            claimsA={claimsFor.get(contradiction.study_a_id) ?? []}
            claimsB={claimsFor.get(contradiction.study_b_id) ?? []}
            open={openIds.has(id)}
            onToggle={() => toggle(id)}
          />
        );
      })}
    </ul>
  );
}
