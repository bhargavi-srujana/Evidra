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

/** Abort hung requests instead of spinning forever on a dead backend. */
const REQUEST_TIMEOUT_MS = 45_000;

/**
 * Search + compare fan out to one paced LLM call per paper, so a
 * multi-paper corpus legitimately takes a while. Per-request timeouts
 * default to 45s to accommodate multi-paper LLM extraction.
 */
const LONG_REQUEST_TIMEOUT_MS = 45_000;

/** Short client cache so back/forward + re-searches skip the network. */
const CACHE_TTL_MS = 60_000;
const responseCache = new Map<string, { expires: number; data: unknown }>();
/** Coalesce concurrent identical requests into one fetch. */
const inflight = new Map<string, Promise<unknown>>();

/** Friendly message surfaced when our own per-request timeout fires. */
const TIMEOUT_MESSAGE = "Search request timed out. Please try again.";

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === "AbortError") ||
    (typeof err === "object" &&
      err !== null &&
      (err as { name?: unknown }).name === "AbortError")
  );
}

/**
 * Per-request timeout controller. Each request gets its own isolated
 * AbortController — never shared across coalesced callers or across
 * sequential search/compare phases.
 */
function createTimeoutController(ms: number): {
  controller: AbortController;
  timedOut: () => boolean;
  cleanup: () => void;
} {
  const controller = new AbortController();
  let didTimeout = false;
  const timer = setTimeout(() => {
    didTimeout = true;
    controller.abort(new Error(`Request timed out after ${ms}ms`));
  }, ms);
  // Avoid keeping a serverless function / dev server alive for the timer.
  if (typeof timer === "object" && "unref" in timer) {
    (timer as { unref: () => void }).unref?.();
  }
  return {
    controller,
    timedOut: () => didTimeout,
    cleanup: () => clearTimeout(timer),
  };
}

/**
 * Race a shared network promise against a single caller's AbortSignal so
 * coalesced callers can cancel individually without aborting each other.
 * Resolves/rejects with the network result unless the caller aborts first.
 */
function raceWithCallerSignal<T>(
  task: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      reject(
        signal.reason instanceof Error
          ? signal.reason
          : new DOMException(
              signal.reason !== undefined
                ? String(signal.reason)
                : "This operation was aborted",
              "AbortError",
            ),
      );
    };
    signal.addEventListener("abort", onAbort, { once: true });
    task.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve(value);
      },
      (err) => {
        signal.removeEventListener("abort", onAbort);
        reject(err);
      },
    );
  });
}

async function fetchJson<T>(
  path: string,
  init: RequestInit & { signal?: AbortSignal },
  cacheKey?: string,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  if (cacheKey) {
    const hit = responseCache.get(cacheKey);
    if (hit && hit.expires > Date.now()) return hit.data as T;
    // Coalesce concurrent identical requests into one network fetch, but
    // do NOT share the first caller's AbortSignal: each waiter races the
    // shared fetch against its own signal below.
    const ongoing = inflight.get(cacheKey);
    if (ongoing) {
      const shared = ongoing as Promise<T>;
      return init.signal
        ? raceWithCallerSignal(shared, init.signal)
        : shared;
    }
  }
  // Isolated network fetch: per-request AbortController + timeout only.
  // The caller's signal is never wired into this controller.
  const networkTask = (async (): Promise<T> => {
    const { controller, timedOut, cleanup } =
      createTimeoutController(timeoutMs);
    try {
      const { signal: _dropped, ...rest } = init;
      void _dropped;
      const res = await fetch(`${API_BASE_URL}${path}`, {
        ...rest,
        signal: controller.signal,
      });
      const data = await handleResponse<T>(res);
      if (cacheKey) {
        responseCache.set(cacheKey, {
          expires: Date.now() + CACHE_TTL_MS,
          data,
        });
      }
      return data;
    } catch (err) {
      // Our own timeout fired — translate Chrome's cryptic
      // "signal is aborted without reason" into a friendly message.
      if (timedOut() && isAbortError(err)) {
        throw new Error(TIMEOUT_MESSAGE);
      }
      throw err;
    } finally {
      cleanup();
      if (cacheKey) inflight.delete(cacheKey);
    }
  })();
  if (cacheKey) inflight.set(cacheKey, networkTask);
  // Per-request isolation for the originating caller as well.
  if (init.signal) {
    try {
      return await raceWithCallerSignal(networkTask, init.signal);
    } catch (err) {
      // Caller navigated away / unmounted: preserve abort semantics so
      // callers can stay silent instead of showing a timeout error.
      if (init.signal.aborted && isAbortError(err)) throw err;
      if (isAbortError(err)) throw new Error(TIMEOUT_MESSAGE);
      throw err;
    }
  }
  try {
    return await networkTask;
  } catch (err) {
    if (isAbortError(err)) throw new Error(TIMEOUT_MESSAGE);
    throw err;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const raw = await res.text().catch(() => res.statusText);
    let detail = raw;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        typeof (parsed as { detail?: unknown }).detail === "string"
      ) {
        detail = (parsed as { detail: string }).detail;
      }
    } catch {
      // Non-JSON body: use as-is.
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

/**
 * POST /api/v1/search — submit a natural-language research question.
 */
export async function searchQuestion(
  query: string,
  maxResults = 6,
  init?: { signal?: AbortSignal },
): Promise<SearchResponse> {
  return fetchJson<SearchResponse>(
    "/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, max_results: maxResults }),
      signal: init?.signal,
    },
    `search:${query}:${maxResults}`,
    LONG_REQUEST_TIMEOUT_MS,
  );
}

/**
 * GET /api/v1/studies/{study_id} — fetch a single study by ID.
 */
export async function getStudy(
  studyId: string,
  init?: { signal?: AbortSignal },
): Promise<Study> {
  return fetchJson<Study>(
    `/studies/${encodeURIComponent(studyId)}`,
    { method: "GET", signal: init?.signal },
    `study:${studyId}`,
  );
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
  const sorted = [...studyIds].sort();
  return fetchJson<ComparisonMatrix>(
    "/compare",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        claims ? { study_ids: studyIds, claims } : { study_ids: studyIds },
      ),
      signal: init?.signal,
    },
    // Claims payloads vary per search; key on IDs + claim count to stay safe.
    `compare:${sorted.join(",")}:${claims?.length ?? "stored"}`,
    LONG_REQUEST_TIMEOUT_MS,
  );
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
  maxResults = 6,
  init?: { signal?: AbortSignal },
): Promise<SearchAndCompareResult> {
  const parentSignal = init?.signal;
  if (parentSignal?.aborted) {
    throw parentSignal.reason instanceof Error
      ? parentSignal.reason
      : new DOMException("This operation was aborted", "AbortError");
  }
  // Phase 1 (search): isolated per-request AbortController. Linked to the
  // caller's signal for cancellation, but never shared with phase 2.
  const searchController = new AbortController();
  const onSearchAbort = () =>
    searchController.abort(parentSignal?.reason ?? new Error("Aborted"));
  parentSignal?.addEventListener("abort", onSearchAbort, { once: true });
  let search: SearchResponse;
  try {
    search = await searchQuestion(query, maxResults, {
      signal: searchController.signal,
    });
  } catch (err) {
    // Caller cancelled — preserve abort so UI stays silent.
    if (parentSignal?.aborted) throw err;
    if (isAbortError(err)) throw new Error(TIMEOUT_MESSAGE);
    throw err;
  } finally {
    parentSignal?.removeEventListener("abort", onSearchAbort);
  }
  const ids = search.results.map((s) => s.study_id).slice(0, MAX_COMPARE_IDS);
  if (ids.length < 2) {
    return { search, comparison: null };
  }
  if (parentSignal?.aborted) {
    throw parentSignal.reason instanceof Error
      ? parentSignal.reason
      : new DOMException("This operation was aborted", "AbortError");
  }
  // Phase 2 (compare): fresh isolated per-request AbortController.
  const compareController = new AbortController();
  const onCompareAbort = () =>
    compareController.abort(parentSignal?.reason ?? new Error("Aborted"));
  parentSignal?.addEventListener("abort", onCompareAbort, { once: true });
  try {
    const comparison = await compareStudies(ids, search.claims, {
      signal: compareController.signal,
    });
    return { search, comparison };
  } catch (err) {
    if (parentSignal?.aborted) throw err;
    if (isAbortError(err)) throw new Error(TIMEOUT_MESSAGE);
    throw err;
  } finally {
    parentSignal?.removeEventListener("abort", onCompareAbort);
  }
}

export { API_BASE_URL };
