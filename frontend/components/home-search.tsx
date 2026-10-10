"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import QueryBar from "@/components/query-bar";

const RECENT_TOPICS = [
  "Does sleep improve memory consolidation?",
  "Do LLMs reduce cognitive load in tutoring?",
  "Does spaced repetition beat massed practice?",
  "Do explanations improve trust in AI decisions?",
];

/** Interactive island for the otherwise static homepage (RSC). */
export default function HomeSearch({
  topicsOnly = false,
  variant = "dark",
}: {
  topicsOnly?: boolean;
  /** "onPaper" renders light pills for use on the white hero sheets. */
  variant?: "dark" | "onPaper";
}) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  const handleSearch = useCallback(
    (query: string) => {
      if (isLoading) return;
      setIsLoading(true);
      try {
        router.push(`/results/${encodeURIComponent(query)}`);
      } catch {
        setIsLoading(false);
        return;
      }
      // Safety: if navigation fails and we stay mounted, don't stick on
      // "Searching…" forever.
      setTimeout(() => setIsLoading(false), 5000);
    },
    [router, isLoading],
  );

  return (
    <>
      {topicsOnly ? null : (
        <QueryBar onSearch={handleSearch} isLoading={isLoading} className="mt-8" />
      )}

      <section aria-label="Recent research topics" className="mt-5 w-full">
        <p
          className={
            variant === "onPaper"
              ? "text-[11px] font-bold uppercase tracking-[0.18em] text-neutral-700"
              : "text-xs font-medium uppercase tracking-widest text-neutral-400"
          }
        >
          Try a recent topic
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {RECENT_TOPICS.map((topic) => (
            <button
              key={topic}
              type="button"
              onClick={() => handleSearch(topic)}
              disabled={isLoading}
              className={
                variant === "onPaper"
                  ? "rounded-full border border-neutral-300 bg-white px-3.5 py-1.5 text-[13px] text-neutral-800 shadow-sm transition-colors hover:border-neutral-500 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-50"
                  : "rounded-full border border-neutral-700 bg-neutral-900/70 px-4 py-2 text-sm text-neutral-300 backdrop-blur-lg transition-colors hover:border-neutral-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              }
            >
              {topic}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
