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
}: {
  icon: typeof GitCompareArrows;
  index: string;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-3">
      <h2 className="inline-flex items-center gap-2 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-bold text-white dark:bg-zinc-50 dark:text-zinc-900">
          {index}
        </span>
        <Icon className="h-4 w-4" aria-hidden="true" />
        {title}
      </h2>
      {hint ? (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
      ) : null}
    </div>
  );
}

export default function ResultsPage() {
  const params = useParams<{ queryId: string }>();
  const router = useRouter();
  const rawQueryId = Array.isArray(params.queryId)
    ? params.queryId[0]
    : (params.queryId ?? "");
  // Next.js already decodes params once; a literal "%" in the question (e.g.
  // "100% sleep") makes a second decode throw URIError — fall back safely.
  let query: string;
  try {
    query = decodeURIComponent(rawQueryId ?? "");
  } catch {
    query = rawQueryId ?? "";
  }

  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [comparison, setComparison] = useState<ComparisonMatrix | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      if (!query) {
        setIsLoading(false);
        return;
      }
      setIsLoading(true);
      setError(null);
      try {
        const { search: searchRes, comparison: cmp } = await searchAndCompare(
          query,
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
  }, [query]);

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
      if (studyClaims.length > 0) map.set(studyId, studyClaims[0]);
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
        </div>

        {error ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              Backend unreachable ({error}). Showing layout placeholders until
              the API at <code>localhost:8000</code> is running.
            </span>
          </div>
        ) : null}

        {/* Section 1: Query & Evidence Overview */}
        <div>
          <SectionHeading
            icon={LineChart}
            index="1"
            title="Query & Evidence Overview"
            hint="Corpus-level finding counts plus year-by-year breakdown."
          />
          {isLoading ? (
            <EvidenceSummarySkeleton />
          ) : comparison ? (
            <EvidenceSummaryPanel summary={comparison.summary} studies={studies} />
          ) : (
            <p className="text-sm text-zinc-500">
              {studies.length > 0
                ? "Fewer than two studies retrieved — comparison needs at least two."
                : "No synthesis yet — comparison results will appear here."}
            </p>
          )}
        </div>

        {/* Section 2: Contradiction Explorer (central feature) */}
        <div>
          <SectionHeading
            icon={GitCompareArrows}
            index="2"
            title="Contradiction Explorer"
            hint="Opposing findings with PICO differences, observed facts, and cautious hypotheses."
          />
          {isLoading ? (
            <ContradictionExplorerSkeleton />
          ) : comparison ? (
            <ContradictionExplorer
              contradictions={comparison.contradictions}
              studies={studies}
              claims={claims}
            />
          ) : (
            <p className="text-sm text-zinc-500">
              Contradiction analysis will appear here once the corpus is compared.
            </p>
          )}
        </div>

        {/* Section 3: Interactive Evidence Graph */}
        <div>
          <SectionHeading
            icon={Network}
            index="3"
            title="Interactive Evidence Graph"
            hint="Question → topic clusters → studies. Dashed red edges mark contradictions."
          />
          {isLoading ? (
            <EvidenceGraphSkeleton />
          ) : (
            <EvidenceGraph
              query={query}
              clusters={comparison?.clusters ?? []}
              studies={studies}
              claims={claims}
              contradictions={comparison?.contradictions ?? []}
            />
          )}
        </div>

        {/* Section 4: Corpus Research Gaps */}
        <div>
          <SectionHeading
            icon={TriangleAlert}
            index="4"
            title="Corpus Research Gaps"
            hint="Missing or under-represented areas — scoped strictly to the retrieved corpus."
          />
          {isLoading ? (
            <ResearchGapsSkeleton />
          ) : comparison ? (
            <ResearchGaps gaps={comparison.gaps} />
          ) : (
            <p className="text-sm text-zinc-500">
              Gap analysis will appear here once the corpus is compared.
            </p>
          )}
        </div>

        {/* Section 5: Retrieved Papers & Sources */}
        <div>
          <SectionHeading
            icon={ListOrdered}
            index="5"
            title="Retrieved Papers & Sources"
            hint={`${studies.length} paper${studies.length === 1 ? "" : "s"} with extracted PICO design.`}
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
          ) : (
            <p className="flex items-center gap-2 text-sm text-zinc-500">
              <FlaskConical className="h-4 w-4" aria-hidden="true" />
              No studies found for this question yet.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
