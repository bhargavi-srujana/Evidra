"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Search, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface QueryBarProps {
  initialQuery?: string;
  isLoading?: boolean;
  onSearch: (query: string) => void | Promise<void>;
  className?: string;
  /** "dark" renders a charcoal pill for use on light paper mastheads. */
  tone?: "light" | "dark";
}

export default function QueryBar({
  initialQuery = "",
  isLoading = false,
  onSearch,
  className,
  tone = "light",
}: QueryBarProps) {
  // State initializes from initialQuery on mount. Parents navigating
  // query-to-query pass key={query} so the header remounts instead of
  // showing a stale input — no sync effect needed.
  const [query, setQuery] = useState(initialQuery);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    void onSearch(trimmed);
  };

  const dark = tone === "dark";
  return (
    <form
      onSubmit={handleSubmit}
      role="search"
      className={cn("w-full", className)}
    >
      <div
        className={cn(
          "flex w-full items-center gap-2 rounded-2xl border p-2 shadow-sm focus-within:ring-2",
          dark
            ? "border-neutral-700 bg-neutral-900 focus-within:border-neutral-500 focus-within:ring-neutral-500/30"
            : "border-zinc-200 bg-white focus-within:border-zinc-900 focus-within:ring-zinc-900/20 dark:border-zinc-800 dark:bg-zinc-950 dark:focus-within:border-zinc-100 dark:focus-within:ring-zinc-100/20",
        )}
      >
        <Search
          className={cn(
            "ml-2 h-5 w-5 shrink-0",
            dark ? "text-neutral-500" : "text-zinc-400",
          )}
          aria-hidden="true"
        />
        <label htmlFor="research-question" className="sr-only">
          Research question
        </label>
        <input
          id="research-question"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Evidra — ask a research question…"
          className={cn(
            "h-11 w-full bg-transparent text-sm outline-none",
            dark
              ? "text-neutral-100 placeholder:text-neutral-500"
              : "text-zinc-900 placeholder:text-zinc-400 dark:text-zinc-50",
          )}
        />
        <button
          type="submit"
          disabled={isLoading || query.trim().length === 0}
          className={cn(
            "inline-flex h-11 shrink-0 items-center gap-2 rounded-xl px-5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
            dark
              ? "bg-neutral-100 text-neutral-900 hover:bg-white"
              : "bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200",
          )}
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Searching…
            </>
          ) : (
            "Search"
          )}
        </button>
      </div>
    </form>
  );
}
