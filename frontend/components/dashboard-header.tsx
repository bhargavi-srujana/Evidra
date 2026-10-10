"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import QueryBar from "@/components/query-bar";
import { cn } from "@/lib/utils";

interface DashboardHeaderProps {
  initialQuery?: string;
  isLoading?: boolean;
  onSearch?: (query: string) => void;
  className?: string;
}

/**
 * Professional dashboard header: light-grey glassmorphism bar with the
 * Evidra logo, the engine title, and the research-question search bar.
 */
export default function DashboardHeader({
  initialQuery = "",
  isLoading = false,
  onSearch,
  className,
}: DashboardHeaderProps) {
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
    <header
      className={cn(
        "sticky top-0 z-40 border-b border-neutral-500/40 bg-neutral-300/85 backdrop-blur-lg",
        className,
      )}
    >
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:gap-5">
        <Link href="/" className="flex shrink-0 items-center gap-3">
          <Image
            src="/logo.png"
            alt="Evidra logo"
            width={44}
            height={44}
            className="h-11 w-11 rounded-full object-cover ring-2 ring-neutral-500/50"
            priority
          />
          <span className="leading-tight">
            <span className="block text-sm font-extrabold tracking-[0.18em] text-neutral-900">
              EVIDRA
            </span>
            <span className="block text-[10px] font-semibold tracking-[0.14em] text-neutral-700">
              EVIDENCE &amp; CONTRADICTION ENGINE{" "}
              
            </span>
          </span>
        </Link>
        <div className="w-full lg:max-w-2xl">
          <QueryBar
            key={initialQuery}
            initialQuery={initialQuery}
            isLoading={busy}
            onSearch={handleSearch}
          />
        </div>
      </div>
    </header>
  );
}
