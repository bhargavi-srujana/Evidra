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
  /** "transparent" renders a clear bar that stays transparent in both color schemes. */
  tone?: "light" | "dark" | "transparent";
  /** Compact renders a smaller bar (shorter input/button, tighter padding). */
  compact?: boolean;
}

export default function QueryBar({
  initialQuery = "",
  isLoading = false,
  onSearch,
  className,
  tone = "light",
  compact = false,
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
  const transparent = tone === "transparent";
  return (
    <form
      onSubmit={handleSubmit}
      role="search"
      className={cn("w-full", className)}
    >
      <div
        className={cn(
          "flex w-full items-center gap-2 rounded-2xl border shadow-sm focus-within:ring-2",
          compact ? "p-1.5" : "p-2",
          transparent
            ? "border-neutral-400/60 bg-white/10 backdrop-blur-sm focus-within:border-neutral-500 focus-within:ring-neutral-500/20"
            : dark
              ? "border-neutral-700 bg-neutral-900 focus-within:border-neutral-500 focus-within:ring-neutral-500/30"
              : "border-zinc-200 bg-white focus-within:border-zinc-900 focus-within:ring-zinc-900/20 dark:border-zinc-800 dark:bg-zinc-950 dark:focus-within:border-zinc-100 dark:focus-within:ring-zinc-100/20",
        )}
      >
        <Search
          className={cn(
            "ml-2 shrink-0",
            compact ? "h-4 w-4" : "h-5 w-5",
            transparent
              ? "text-neutral-500"
              : dark
                ? "text-neutral-500"
                : "text-zinc-400",
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
            "w-full bg-transparent outline-none",
            compact ? "h-9 text-[13px]" : "h-11 text-sm",
            transparent
              ? "text-neutral-800 placeholder:text-neutral-500"
              : dark
                ? "text-neutral-100 placeholder:text-neutral-500"
                : "text-zinc-900 placeholder:text-zinc-400 dark:text-zinc-50",
          )}
        />
        <button
          type="submit"
          disabled={isLoading || query.trim().length === 0}
          className={cn(
            "inline-flex shrink-0 items-center gap-2 rounded-xl font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
            compact ? "h-9 px-4 text-[13px]" : "h-11 px-5 text-sm",
            transparent
              ? "border border-neutral-400/70 bg-transparent text-neutral-700 hover:bg-neutral-900/5"
              : dark
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
