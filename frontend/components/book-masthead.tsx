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
      <div className="flex items-start gap-0">
        <Link
          href="/"
          aria-label="Evidra home"
          className="relative z-20 mt-0 shrink-0 -mr-7"
        >
          <Image
            src="/logo.png"
            alt="Evidra logo"
            width={64}
            height={64}
            className="h-14 w-14 rounded-full object-cover ring-[3px] ring-amber-300 shadow-[0_10px_30px_rgba(0,0,0,0.65)] sm:h-[68px] sm:w-[68px]"
            priority
          />
        </Link>

        {/* open book spread */}
        <div className="relative min-w-0 flex-1">
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
              <p className="text-center text-[11px] font-bold tracking-[0.22em] text-neutral-800 sm:text-[13px]">
                EVIDRA — EVIDENCE &amp; CONTRADICTION ENGINE
              </p>
              {/* frosted search resting on the pages */}
              <div className="mx-auto mt-2 max-w-3xl rounded-2xl border border-white/50 bg-neutral-300/40 p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_8px_24px_rgba(0,0,0,0.18)] backdrop-blur-md">
                <QueryBar
                  key={initialQuery}
                  initialQuery={initialQuery}
                  isLoading={busy}
                  onSearch={handleSearch}
                />
              </div>

            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
