"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  FlaskConical,
  GitCompareArrows,
  LineChart,
  ListOrdered,
  Network,
  TriangleAlert,
} from "lucide-react";

import QueryBar from "@/components/query-bar";
import StudyCard from "@/components/study-card";
import {
  EvidenceGraphSkeleton,
  EvidenceSummarySkeleton,
} from "@/components/skeletons";
import ContradictionExplorer, {
  ContradictionExplorerSkeleton,
} from "@/components/contradiction-explorer";
import ResearchGaps, { ResearchGapsSkeleton } from "@/components/research-gaps";
import { searchAndCompare } from "@/lib/api";
import { claimsByStudy, dominantDirection } from "@/lib/effects";
import type { ComparisonMatrix, SearchResponse } from "@/lib/types";

// Split the two heaviest deps (@xyflow/react, recharts) out of the results
// page bundle: skeletons paint instantly while the charts stream in.
const EvidenceGraph = dynamic(
  () => import("@/components/evidence-graph").then((m) => m.default),
  { ssr: false, loading: () => <EvidenceGraphSkeleton /> },
);
const EvidenceSummaryPanel = dynamic(
  () => import("@/components/evidence-summary").then((m) => m.default),
  { ssr: false, loading: () => <EvidenceSummarySkeleton /> },
);

function SectionHeading({
  icon: Icon,
  index,
  title,
  hint,
  headingId,
}: {
  icon: typeof GitCompareArrows;
  index: string;
  title: string;
  hint?: string;
  headingId: string;
}) {
  return (
    <div className="mb-3">
      <h2
        id={headingId}
        className="inline-flex items-center gap-2 text-base font-semibold text-zinc-900 dark:text-zinc-50"
      >
        <span
          aria-hidden="true"
          className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-bold text-white dark:bg-zinc-50 dark:text-zinc-900"
        >
          {index}
        </span>
        <Icon className="h-4 w-4" aria-hidden="true" />
        {title}
      </h2>
      {hint ? (
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">{hint}</p>
      ) : null}
    </div>
  );
}

const API_DISPLAY_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export default function ResultsPage() {
  const params = useParams<{ queryId: string }>();
  const router = useRouter();
  const rawParam = params.queryId;
  const rawQueryId =
    typeof rawParam === "string" ? rawParam : (rawParam?.[0] ?? "");
  // Next.js already decodes params once; a literal "%" in the question (e.g.
  // "100% sleep") makes a second decode throw URIError — fall back safely.
  let query: string;
  try {
    query = decodeURIComponent(rawQueryId ?? "");
  } catch {
    query = rawQueryId ?? "";
  }
  const trimmedQuery = query.trim();
  const [reloadNonce, setReloadNonce] = useState(0);

  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [comparison, setComparison] = useState<ComparisonMatrix | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      // Whitespace-only URLs (e.g. /results/%20) never hit the backend.
      if (!trimmedQuery) {
        setIsLoading(false);
        setError("Please enter a research question to search.");
        return;
      }
      setIsLoading(true);
      setError(null);
      try {
        const { search: searchRes, comparison: cmp } = await searchAndCompare(
          trimmedQuery,
          6,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        setSearch(searchRes);
        setComparison(cmp);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load evidence. Is the backend running?",
        );
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [trimmedQuery, reloadNonce]);

  const handleSearch = (nextQuery: string) => {
    router.push(`/results/${encodeURIComponent(nextQuery)}`);
  };

  const studies = useMemo(() => search?.results ?? [], [search]);
  const claims = useMemo(() => search?.claims ?? [], [search]);

  // Group once per response instead of re-filtering claims per study on
  // every render (O(S*C) in StudyCard list + graph + explorer).
  const effectByStudy = useMemo(() => {
    const grouped = claimsByStudy(claims);
    const map = new Map<string, ReturnType<typeof dominantDirection>>();
    for (const [studyId, studyClaims] of grouped) {
      map.set(studyId, dominantDirection(studyClaims));
    }
    return map;
  }, [claims]);

  // Primary finding per study (first claim = main finding) so every card
  // shows its extracted conclusion, not just studies with counted directions.
  const primaryClaimByStudy = useMemo(() => {
    const grouped = claimsByStudy(claims);
    const map = new Map<string, (typeof claims)[number]>();
    for (const [studyId, studyClaims] of grouped) {
      const first = studyClaims.at(0);
      if (first !== undefined) map.set(studyId, first);
    }
    return map;
  }, [claims]);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mx-auto flex w-full max-w-6xl items-center gap-4 px-6 py-4">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Home
          </button>
          <QueryBar
            key={query}
            initialQuery={query}
            isLoading={isLoading}
            onSearch={handleSearch}
            className="max-w-2xl"
          />
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl space-y-8 px-6 py-8">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-zinc-400">
            Research question
          </p>
          <h1 className="mt-1 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
            {query || "Untitled question"}
          </h1>
          {search?.anchor_question ? (
            <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">
              Effect directions are judged against: “{search.anchor_question}”
              — “Positive” supports it, “Negative” opposes it. Asking the
              question the other way round mirrors the verdicts by design.
            </p>
          ) : null}
        </div>

        {error && !isLoading ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p>
                Request failed ({error}). The API at{" "}
                <code className="break-all">{API_DISPLAY_URL}</code> may be down.
              </p>
              <button
                type="button"
                onClick={() => setReloadNonce((n) => n + 1)}
                className="mt-2 rounded-lg bg-amber-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-800 dark:bg-amber-200 dark:text-amber-950"
              >
                Retry
              </button>
            </div>
          </div>
        ) : null}

        {/* Section 1: Query & Evidence Overview */}
        <section aria-labelledby="section-overview">
          <SectionHeading
            icon={LineChart}
            index="1"
            title="Query & Evidence Overview"
            hint="Corpus-level finding counts plus year-by-year breakdown."
            headingId="section-overview"
          />
          {isLoading ? (
            <EvidenceSummarySkeleton />
          ) : comparison ? (
            <EvidenceSummaryPanel summary={comparison.summary} studies={studies} />
          ) : error ? null : (
            <p role="status" className="text-sm text-zinc-600">
              {studies.length > 0
                ? "Fewer than two studies retrieved — comparison needs at least two."
                : "No synthesis yet — comparison results will appear here."}
            </p>
          )}
        </section>

        {/* Section 2: Contradiction Explorer (central feature) */}
        <section aria-labelledby="section-contradictions">
          <SectionHeading
            icon={GitCompareArrows}
            index="2"
            title="Contradiction Explorer"
            hint="Opposing findings with PICO differences, observed facts, and cautious hypotheses."
            headingId="section-contradictions"
          />
          {isLoading ? (
            <ContradictionExplorerSkeleton />
          ) : comparison ? (
            <ContradictionExplorer
              contradictions={comparison.contradictions ?? []}
              studies={studies}
              claims={claims}
            />
          ) : error ? null : (
            <p role="status" className="text-sm text-zinc-600">
              Contradiction analysis will appear here once the corpus is compared.
            </p>
          )}
        </section>

        {/* Section 3: Interactive Evidence Graph */}
        <section aria-labelledby="section-graph">
          <SectionHeading
            icon={Network}
            index="3"
            title="Interactive Evidence Graph"
            hint="Question → topic clusters → studies. Dashed red edges mark contradictions."
            headingId="section-graph"
          />
          {isLoading ? (
            <EvidenceGraphSkeleton />
          ) : studies.length > 0 ? (
            <EvidenceGraph
              query={query}
              clusters={comparison?.clusters ?? []}
              studies={studies}
              claims={claims}
              contradictions={comparison?.contradictions ?? []}
            />
          ) : error ? null : (
            <p role="status" className="text-sm text-zinc-600">
              The evidence graph will appear here once studies are retrieved.
            </p>
          )}
        </section>

        {/* Section 4: Corpus Research Gaps */}
        <section aria-labelledby="section-gaps">
          <SectionHeading
            icon={TriangleAlert}
            index="4"
            title="Corpus Research Gaps"
            hint="Missing or under-represented areas — scoped strictly to the retrieved corpus."
            headingId="section-gaps"
          />
          {isLoading ? (
            <ResearchGapsSkeleton />
          ) : comparison ? (
            <ResearchGaps gaps={comparison.gaps ?? []} />
          ) : error ? null : (
            <p role="status" className="text-sm text-zinc-600">
              Gap analysis will appear here once the corpus is compared.
            </p>
          )}
        </section>

        {/* Section 5: Retrieved Papers & Sources */}
        <section aria-labelledby="section-papers">
          <SectionHeading
            icon={ListOrdered}
            index="5"
            title="Retrieved Papers & Sources"
            hint={`${studies.length} paper${studies.length === 1 ? "" : "s"} with extracted PICO design.`}
            headingId="section-papers"
          />
          {isLoading ? (
            <div className="space-y-3" aria-busy="true" aria-label="Loading studies">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="h-44 animate-pulse rounded-2xl bg-zinc-100 dark:bg-zinc-900"
                />
              ))}
            </div>
          ) : studies.length > 0 ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {studies.map((study) => (
                <StudyCard
                  key={study.study_id}
                  study={study}
                  effectDirection={effectByStudy.get(study.study_id) ?? null}
                  conclusion={
                    primaryClaimByStudy.get(study.study_id)?.conclusion ??
                    primaryClaimByStudy.get(study.study_id)?.text ??
                    null
                  }
                  evidenceQuote={
                    primaryClaimByStudy.get(study.study_id)
                      ?.verbatim_evidence_quote ??
                    primaryClaimByStudy.get(study.study_id)?.evidence_span ??
                    null
                  }
                />
              ))}
            </div>
          ) : error ? null : (
            <p role="status" className="flex items-center gap-2 text-sm text-zinc-600">
              <FlaskConical className="h-4 w-4" aria-hidden="true" />
              No studies found for this question yet.
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
