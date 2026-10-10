"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import QueryBar from "@/components/query-bar";
import { cn } from "@/lib/utils";

interface BookMastheadProps {
  initialQuery?: string;
  isLoading?: boolean;
  onSearch?: (query: string) => void;
  className?: string;
}


/**
 * Open-book masthead: Evidra logo overlapping a paper book spread carrying
 * the engine title, a dark search pill, and faint printed index columns.
 */
export default function BookMasthead({
  initialQuery = "",
  isLoading = false,
  onSearch,
  className,
}: BookMastheadProps) {
  const router = useRouter();
  const [navigating, setNavigating] = useState(false);

  const handleSearch = useCallback(
    (query: string) => {
      if (onSearch) {
        onSearch(query);
        return;
      }
      if (navigating) return;
      setNavigating(true);
      try {
        router.push(`/results/${encodeURIComponent(query)}`);
      } catch {
        setNavigating(false);
        return;
      }
      setTimeout(() => setNavigating(false), 5000);
    },
    [router, navigating, onSearch],
  );

  const busy = isLoading || navigating;

  return (
    <div className={cn("relative", className)}>
      <div className="relative flex flex-col gap-3 sm:block">
       <Link
          href="/"
          aria-label="Evidra home"
          className="shrink-0 -ml-6 sm:absolute sm:left-0 sm:top-1/2 sm:z-20 sm:-translate-y-1/2  sm:-ml-12"
        >
          <Image
            src="/logo.png"
            alt="Evidra logo"
            width={64}
            height={64}
            className="h-30 w-30 object-cover "
            priority
          />
        </Link>

        {/* open book spread, centered exactly in the middle of the page */}
        <div className="relative mx-auto w-full max-w-3xl translate-x-4">
          {/* page thickness / side curl */}
          <div
            aria-hidden="true"
            className="absolute inset-y-1 -left-1.5 right-2 rounded-[4px] bg-neutral-400/50 blur-[1px]"
          />
          <div
            aria-hidden="true"
            className="absolute inset-y-2 -right-1.5 left-2 rounded-[4px] bg-neutral-500/40 blur-[1px]"
          />
          <div className="relative overflow-hidden rounded-[4px] bg-neutral-100 text-neutral-900 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.8)] ring-1 ring-black/20">
            {/* center spine */}
            <div
              aria-hidden="true"
              className="absolute inset-y-0 left-1/2 hidden w-8 -translate-x-1/2 bg-gradient-to-r from-transparent via-neutral-400/60 to-transparent sm:block"
            />
            <div
              aria-hidden="true"
              className="absolute inset-y-0 left-1/2 hidden w-px -translate-x-1/2 bg-neutral-500/60 sm:block"
            />
            {/* frosted glass sheen over the spread */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white/50 via-transparent to-neutral-900/10"
            />
            <div className="relative px-4 pb-3 pt-2.5 sm:px-8">
              <div className="text-center">
                <p className="inline-block rounded-full bg-neutral-900 px-4 py-1.5 text-[11px] font-bold tracking-[0.22em] text-white shadow-lg ring-1 ring-amber-300/60 sm:text-xs">
                  EVIDRA — EVIDENCE &amp; CONTRADICTION ENGINE
                </p>
              </div>
              {/* frosted search resting on the pages */}
              <div className="mx-auto mt-2 max-w-xl rounded-2xl border border-white/50 bg-neutral-300/40 p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_8px_24px_rgba(0,0,0,0.18)] backdrop-blur-md">
                <QueryBar
                  key={initialQuery}
                  initialQuery={initialQuery}
                  isLoading={busy}
                  onSearch={handleSearch}
                  tone="transparent"
                  compact
                />
              </div>

            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
