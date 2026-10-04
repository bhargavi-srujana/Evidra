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

const BAR_COLORS = ["#10b981", "#f59e0b", "#f43f5e"];

export function EvidenceSummarySkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading evidence overview"
      className={cn(
        "rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950",
        className,
      )}
    >
      <div className="h-4 w-40 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-900"
          />
        ))}
      </div>
      <div className="mt-3 h-44 animate-pulse rounded-xl bg-zinc-100 dark:bg-zinc-900" />
    </div>
  );
}

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
    ],
    [summary],
  );

  const yearData = useMemo(() => {
    const counts = new Map<number, number>();
    for (const study of studies) {
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
  ];

  return (
    <section
      aria-label="Evidence overview"
      className={cn(
        "rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950",
        className,
      )}
    >
      <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        Evidence Overview
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {cards.map(({ label, value }) => (
          <div
            key={label}
            className="rounded-xl bg-zinc-50 p-3 dark:bg-zinc-900"
          >
            <dt className="text-xs text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className="mt-1 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
            Findings by direction
          </h3>
          <div className="mt-2 h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={directionData}>
                <XAxis dataKey="name" fontSize={12} />
                <YAxis allowDecimals={false} fontSize={12} />
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
          <h3 className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            <BarChart3 className="h-3.5 w-3.5" aria-hidden="true" />
            Studies by year
          </h3>
          {yearData.length > 0 ? (
            <div className="mt-2 h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={yearData}>
                  <XAxis dataKey="year" fontSize={12} />
                  <YAxis allowDecimals={false} fontSize={12} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#2563eb" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">
              No year metadata available for this corpus.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
