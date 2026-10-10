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
 * Open-book masthead: logo + wordmark on the left, open-book spread
 * carrying the engine title and a transparent search bar on the right.
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
    <div className="flex w-screen flex-col items-center gap-7 bg-neutral-300/85  lg:flex-row lg:items-center  ">
      <div className="top-0 left-2.5 flex items-center gap-2 sm:w-44 sm:gap-2.5 px-14 py-3">
        <Link href="/" aria-label="Evidra home" className="shrink-0 flex items-center  gap-3">
          <Image
            src="/logo.png"
            alt="Evidra logo"
            width={442}
            height={403}
            className="top-0 flex h-12 w-auto sm:h-16  "
          />
        </Link>
        <div className="text-lg font-extrabold tracking-[0.14em] text-neutral-100 sm:text-xl">EVIDRA</div>

      </div>
       
       <div className="px-34 scale-120" >
     
      {/* brand row: logo + wordmark in the left top corner */}
     

      
        
        {/* open book spread, centered and big: top of the pages pinned
            visible, excess bottom clipped — title and search sit on
            the pages */}
        <div className="relative min-w-0 flex-1 aspect-[7/1] min-h-[116px] overflow-hidden rounded-md sm:min-h-[126px]">
          <Image
            src="/openbook4.png"
            alt=""
            aria-hidden="true"
            fill
            sizes="(max-width: 768px) 100vw, 1024px"
            className="object-cover object-top"
            priority
          />
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2  sm:gap-2.5 ">
            <p className="rounded-full border border-amber-900/15 bg-white/75  py-1 text-center text-[9px] font-extrabold tracking-[0.16em] text-neutral-900 shadow-sm  sm:text-[12px] sm:tracking-[0.2em]">
              EVIDRA — EVIDENCE &amp; CONTRADICTION ENGINE
            </p>
            <QueryBar
              key={initialQuery}
              initialQuery={initialQuery}
              isLoading={busy}
              onSearch={handleSearch}
              tone="transparent"
              className="w-full max-w-2xl"
            />
          </div>
        </div>
    </div>
    </div>
   
  );
}
