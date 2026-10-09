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
export default function HomeSearch() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  const handleSearch = useCallback(
    (query: string) => {
      if (isLoading) return;
      setIsLoading(true);
      router.push(`/results/${encodeURIComponent(query)}`);
    },
    [router, isLoading],
  );

  return (
    <>
      <QueryBar onSearch={handleSearch} isLoading={isLoading} className="mt-8" />

      <section aria-label="Recent research topics" className="mt-8 w-full">
        <p className="text-xs font-medium uppercase tracking-widest text-zinc-400">
          Try a recent topic
        </p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {RECENT_TOPICS.map((topic) => (
            <button
              key={topic}
              type="button"
              onClick={() => handleSearch(topic)}
              disabled={isLoading}
              className="rounded-full border border-zinc-200 bg-white px-4 py-2 text-sm text-zinc-700 transition-colors hover:border-zinc-400 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300"
            >
              {topic}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
