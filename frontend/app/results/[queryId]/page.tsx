"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  FlaskConical,
  GitCompareArrows,
  ListOrdered,
  TriangleAlert,
} from "lucide-react";

import DashboardBackground from "@/components/dashboard-background";
import BookMasthead from "@/components/book-masthead";
import FindingsGrid from "@/components/findings-grid";
import PdfBackstop from "@/components/pdf-backstop";
import TocSidebar from "@/components/toc-sidebar";
import { PaperDoc, glassPanel } from "@/components/paper";
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
        className="inline-flex items-center gap-2 text-base font-semibold text-neutral-100"
      >
        <span
          aria-hidden="true"
          className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-neutral-100 text-[11px] font-bold text-neutral-900"
        >
          {index}
        </span>
        <Icon className="h-4 w-4 text-neutral-400" aria-hidden="true" />
        {title}
      </h2>
      {hint ? (
        <p className="mt-1 text-xs text-neutral-400">{hint}</p>
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
    <div className="min-h-screen bg-neutral-950 text-neutral-200">
      <DashboardBackground />

      <div className="relative z-10 mx-auto w-full max-w-7xl px-4 pt-5 sm:px-6">
        <BookMasthead
          initialQuery={query}
          isLoading={isLoading}
          onSearch={handleSearch}
        />
      </div>

      <div className="relative z-10 mx-auto flex w-full max-w-7xl items-start gap-6 px-4 py-6 sm:px-6">
        <TocSidebar className="hidden w-60 shrink-0 lg:sticky lg:top-24 lg:block" />

        <main className="min-w-0 flex-1 space-y-8 pb-16">
          {search?.warnings?.map((warning) => (
            <div
              key={warning.slice(0, 48)}
              role="status"
              className="flex items-start gap-2 rounded-2xl border border-amber-700/50 bg-amber-950/60 p-4 text-sm text-amber-200 backdrop-blur-lg"
            >
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{warning}</span>
            </div>
          ))}

          {error && !isLoading ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-2xl border border-amber-700/50 bg-amber-950/60 p-4 text-sm text-amber-200 backdrop-blur-lg"
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
                  className="mt-2 rounded-lg bg-amber-200 px-3 py-1.5 text-xs font-medium text-amber-950 hover:bg-amber-100"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : null}

          {/* ---- Collage board ---- */}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
            {/* Research question paper */}
            <section
              id="query-overview"
              aria-label="Query overview"
              className="scroll-mt-28 xl:col-span-7"
            >
              <PaperDoc staple tilt="left" className="p-6 sm:p-7">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-neutral-500">
                  Research question
                </p>
                <h1 className="mt-1 text-2xl font-bold leading-snug text-neutral-900">
                  {query || "Untitled question"}
                </h1>
                {search?.anchor_question ? (
                  <p className="mt-2 text-xs leading-relaxed text-neutral-600">
                    Effect directions are judged against: “
                    {search.anchor_question}” — “Positive” supports it,
                    “Negative” opposes it. Asking the question the other way
                    round mirrors the verdicts by design.
                  </p>
                ) : null}
              </PaperDoc>
            </section>

            {/* Key Contradiction Clusters paper */}
            <div
              id="evidence-graph"
              className="scroll-mt-28 xl:col-span-5 xl:-ml-2 xl:mt-10"
            >
              <PaperDoc tilt="right" className="p-5">
                <h2
                  id="section-graph"
                  className="text-base font-semibold text-neutral-900"
                >
                  Key Contradiction Clusters
                </h2>
                <div className="mt-3">
                  {isLoading ? (
                    <EvidenceGraphSkeleton />
                  ) : studies.length > 0 ? (
                    <EvidenceGraph
                      query={query}
                      clusters={comparison?.clusters ?? []}
                      studies={studies}
                      claims={claims}
                      contradictions={comparison?.contradictions ?? []}
                      tone="paper"
                      compact
                    />
                  ) : error ? null : (
                    <p role="status" className="text-sm text-neutral-500">
                      The evidence graph will appear here once studies are
                      retrieved.
                    </p>
                  )}
                </div>
                <p className="mt-2 text-center text-[11px] text-neutral-500">
                  Force snippets — red edges mark contradictions
                </p>
              </PaperDoc>
            </div>

            {/* Summary of Findings sheet */}
            <div className="xl:col-span-7 xl:-mt-2">
              <div className="rounded-[3px] bg-neutral-200/90 p-5 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.75)] xl:-rotate-[0.4deg]">
                <h2 className="text-base font-semibold text-neutral-900">
                  Summary of Findings
                </h2>
                <div className="mt-3">
                  {isLoading ? (
                    <div
                      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
                      aria-busy="true"
                      aria-label="Loading findings"
                    >
                      {Array.from({ length: 6 }).map((_, i) => (
                        <div
                          key={i}
                          className="h-36 animate-pulse rounded-[3px] bg-neutral-300"
                        />
                      ))}
                    </div>
                  ) : (
                    <FindingsGrid claims={claims} />
                  )}
                </div>
              </div>
            </div>

            {/* PDF Source Backstop */}
            <div className="xl:col-span-5 xl:mt-2 xl:rotate-[0.5deg]">
              {isLoading ? (
                <div
                  className="h-64 animate-pulse rounded-2xl border border-neutral-800 bg-neutral-900/70"
                  aria-busy="true"
                  aria-label="Loading PDF backstop"
                />
              ) : (
                <PdfBackstop claims={claims} studies={studies} />
              )}
            </div>

            {/* Evidence Overview paper */}
            <div className="xl:col-span-12 xl:-mt-2 xl:rotate-[0.25deg]">
              {isLoading ? (
                <EvidenceSummarySkeleton />
              ) : comparison ? (
                <EvidenceSummaryPanel
                  summary={comparison.summary}
                  studies={studies}
                />
              ) : error ? null : (
                <p role="status" className="text-sm text-neutral-400">
                  {studies.length > 0
                    ? "Fewer than two studies retrieved — comparison needs at least two."
                    : "No synthesis yet — comparison results will appear here."}
                </p>
              )}
            </div>
          </div>

          {/* ---- Detail sections ---- */}
          {/* Section 2: Contradiction Explorer (central feature) */}
          <section
            id="contradiction-explorer"
            aria-labelledby="section-contradictions"
            className="scroll-mt-28"
          >
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
              <div className={`${glassPanel} p-4 sm:p-5`}>
                <ContradictionExplorer
                  contradictions={comparison.contradictions ?? []}
                  studies={studies}
                  claims={claims}
                />
              </div>
            ) : error ? null : (
              <p role="status" className="text-sm text-neutral-400">
                Contradiction analysis will appear here once the corpus is compared.
              </p>
            )}
          </section>

          {/* Section 4: Corpus Research Gaps */}
          <section id="research-gaps" aria-labelledby="section-gaps" className="scroll-mt-28">
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
              <p role="status" className="text-sm text-neutral-400">
                Gap analysis will appear here once the corpus is compared.
              </p>
            )}
          </section>

          {/* Retrieved Papers & Sources */}
          <section
            id="retrieved-papers"
            aria-labelledby="section-papers"
            className="scroll-mt-28"
          >
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
                    className="h-44 animate-pulse rounded-[3px] bg-neutral-100"
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
              <p role="status" className="flex items-center gap-2 text-sm text-neutral-400">
                <FlaskConical className="h-4 w-4" aria-hidden="true" />
                No studies found for this question yet.
              </p>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
