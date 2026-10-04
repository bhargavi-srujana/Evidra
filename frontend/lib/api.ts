import type {
  Claim,
  ComparisonMatrix,
  SearchAndCompareResult,
  SearchResponse,
  Study,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/** Backend accepts up to 20 study IDs per compare request. */
const MAX_COMPARE_IDS = 20;

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

/**
 * POST /api/v1/search — submit a natural-language research question.
 */
export async function searchQuestion(
  query: string,
  maxResults = 10,
  init?: { signal?: AbortSignal },
): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE_URL}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_results: maxResults }),
    signal: init?.signal,
  });
  return handleResponse<SearchResponse>(res);
}

/**
 * GET /api/v1/studies/{study_id} — fetch a single study by ID.
 */
export async function getStudy(
  studyId: string,
  init?: { signal?: AbortSignal },
): Promise<Study> {
  const res = await fetch(
    `${API_BASE_URL}/studies/${encodeURIComponent(studyId)}`,
    { method: "GET", signal: init?.signal },
  );
  return handleResponse<Study>(res);
}

/**
 * POST /api/v1/compare — methodology-aware contradiction analysis.
 *
 * Pass the `study_ids` from search plus the extracted `claims` so the
 * backend can cluster and contrast without an extra Mongo round-trip.
 * When `claims` is omitted, the backend resolves them from its store.
 */
export async function compareStudies(
  studyIds: string[],
  claims?: Claim[],
  init?: { signal?: AbortSignal },
): Promise<ComparisonMatrix> {
  const res = await fetch(`${API_BASE_URL}/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      claims ? { study_ids: studyIds, claims } : { study_ids: studyIds },
    ),
    signal: init?.signal,
  });
  return handleResponse<ComparisonMatrix>(res);
}

/** @deprecated Use `compareStudies` — claim IDs no longer alias study IDs. */
export async function compareClaims(
  studyIds: string[],
  init?: { signal?: AbortSignal },
): Promise<ComparisonMatrix> {
  return compareStudies(studyIds, undefined, init);
}

/**
 * Phase 4 orchestrator: search, then compare the retrieved corpus.
 *
 * 1. POST /api/v1/search with the research question.
 * 2. Extract retrieved `study_ids` and `claims`.
 * 3. POST /api/v1/compare with those IDs + claims (< 2 studies → skip).
 * 4. Return the combined result.
 */
export async function searchAndCompare(
  query: string,
  maxResults = 10,
  init?: { signal?: AbortSignal },
): Promise<SearchAndCompareResult> {
  const search = await searchQuestion(query, maxResults, init);
  const ids = search.results.map((s) => s.study_id).slice(0, MAX_COMPARE_IDS);
  if (ids.length < 2) {
    return { search, comparison: null };
  }
  const comparison = await compareStudies(ids, search.claims, init);
  return { search, comparison };
}

export { API_BASE_URL };
