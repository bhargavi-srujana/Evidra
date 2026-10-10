"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3 } from "lucide-react";
import type { EvidenceSummary, Study } from "@/lib/types";
import { cn } from "@/lib/utils";

interface EvidenceSummaryProps {
  summary: EvidenceSummary;
  studies: Study[];
  className?: string;
}

const BAR_COLORS = ["#22c55e", "#eab308", "#ef4444", "#9ca3af"];

// Defined in the lightweight skeletons module so routes can show the
// placeholder without statically pulling recharts into their bundle.
// NOTE: import it from "@/components/skeletons" to keep the code-split;
// this alias only preserves backwards compatibility.
export { EvidenceSummarySkeleton } from "./skeletons";

export default function EvidenceSummaryPanel({
  summary,
  studies,
  className,
}: EvidenceSummaryProps) {
  const directionData = useMemo(
    () => [
      { name: "Positive", count: summary.positive_count },
      { name: "Conditional", count: summary.conditional_count },
      { name: "Negative", count: summary.negative_count },
      { name: "Unclear", count: summary.unclear_count ?? 0 },
    ],
    [summary],
  );

  const yearData = useMemo(() => {
    const counts = new Map<number, number>();
    for (const study of studies) {
      if (typeof study.year !== "number") continue;
      counts.set(study.year, (counts.get(study.year) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort(([a], [b]) => a - b)
      .map(([year, count]) => ({ year: String(year), count }));
  }, [studies]);

  const cards = [
    { label: "Total Studies Analyzed", value: summary.total_studies },
    { label: "Positive Effects", value: summary.positive_count },
    { label: "Mixed / Conditional", value: summary.conditional_count },
    { label: "No Effect / Negative", value: summary.negative_count },
    { label: "Unclear / Unstated", value: summary.unclear_count ?? 0 },
  ];

  return (
    <section
      aria-label="Evidence overview"
      className={cn(
        "relative overflow-hidden rounded-[3px] bg-neutral-100 p-5 text-neutral-900 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.75)]",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <h2 className="text-sm font-semibold text-neutral-900">
          Evidence Overview
        </h2>
        <p className="text-right leading-tight">
          <span className="block text-4xl font-extrabold text-neutral-900">
            {summary.total_studies}
          </span>
          <span className="block text-[11px] font-medium text-neutral-500">
            Total Studies Analyzed
          </span>
        </p>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-5">
        {cards.map(({ label, value }) => (
          <div
            key={label}
            className="rounded-xl border border-neutral-200 bg-white p-3"
          >
            <dt className="text-xs text-neutral-500">{label}</dt>
            <dd className="mt-1 text-2xl font-bold text-neutral-900">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="inline-flex items-center gap-1.5 text-xs font-medium text-neutral-500">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
            Findings by direction
          </h3>
          <div className="mt-2 h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={directionData}>
                <XAxis dataKey="name" fontSize={12} tick={{ fill: "#52525b" }} />
                <YAxis allowDecimals={false} fontSize={12} tick={{ fill: "#52525b" }} />
                <Tooltip />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {directionData.map((entry, i) => (
                    <Cell key={entry.name} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div>
          <h3 className="inline-flex items-center gap-1.5 text-xs font-medium text-neutral-500">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
            Studies by year
          </h3>
          {yearData.length > 0 ? (
            <div className="mt-2 h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={yearData}>
                  <XAxis dataKey="year" fontSize={12} tick={{ fill: "#52525b" }} />
                  <YAxis allowDecimals={false} fontSize={12} tick={{ fill: "#52525b" }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#3b82f6" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-2 text-sm text-neutral-500">
              No year metadata available for this corpus.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
