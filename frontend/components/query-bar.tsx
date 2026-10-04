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
}

export default function QueryBar({
  initialQuery = "",
  isLoading = false,
  onSearch,
  className,
}: QueryBarProps) {
  const [query, setQuery] = useState(initialQuery);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    void onSearch(trimmed);
  };

  return (
    <form
      onSubmit={handleSubmit}
      role="search"
      className={cn("w-full", className)}
    >
      <div className="flex w-full items-center gap-2 rounded-2xl border border-zinc-200 bg-white p-2 shadow-sm focus-within:border-zinc-400 focus-within:ring-2 focus-within:ring-zinc-100 dark:border-zinc-800 dark:bg-zinc-950">
        <Search
          className="ml-2 h-5 w-5 shrink-0 text-zinc-400"
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
          placeholder="Ask a research question, e.g. Does sleep improve memory consolidation?"
          className="h-11 w-full bg-transparent text-sm text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-50"
        />
        <button
          type="submit"
          disabled={isLoading || query.trim().length === 0}
          className="inline-flex h-11 shrink-0 items-center gap-2 rounded-xl bg-zinc-900 px-5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
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
