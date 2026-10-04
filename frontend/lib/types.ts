/**
 * TypeScript contracts mirroring backend Pydantic models.
 * Backend source of truth:
 * - backend/app/models/study.py      -> StudyDesign, Author, Study
 * - backend/app/models/claim.py       -> EffectDirection, Claim
 * - backend/app/models/comparison.py  -> ClaimCluster, ComparisonMatrix,
 *   MethodologicalDifference, PairwiseContradiction, EvidenceSummary
 */

export interface StudyDesign {
  population: string | null;
  sample_size: string | null;
  intervention: string | null;
  control: string | null;
  task_type: string | null;
  measurement_metric: string | null;
  study_duration: string | null;
  study_type: string | null;
}

export interface Author {
  name: string;
  affiliation: string | null;
}

export interface Study {
  study_id: string;
  title: string;
  authors: Author[];
  year: number;
  venue: string | null;
  doi: string | null;
  abstract: string;
  url: string | null;
  design: StudyDesign;
}

export type EffectDirection =
  | "increases"
  | "decreases"
  | "no_effect"
  | "conditional"
  | "unclear";

export interface Claim {
  claim_id: string;
  study_id: string;
  text: string;
  effect_direction: EffectDirection;
  confidence_score: number;
  evidence_span: string | null;
}

export type ImpactLevel = "HIGH" | "MEDIUM" | "LOW";

export interface MethodologicalDifference {
  dimension: string;
  study_a_value: string | null;
  study_b_value: string | null;
  impact_level: ImpactLevel;
}

export interface PairwiseContradiction {
  study_a_id: string;
  study_b_id: string;
  observed_difference: string;
  hypothesized_explanation: string;
  method_differences: MethodologicalDifference[];
}

export interface EvidenceSummary {
  total_studies: number;
  positive_count: number;
  conditional_count: number;
  negative_count: number;
  key_gaps: string[];
}

export interface ClaimCluster {
  cluster_id: string;
  topic: string;
  claim_ids: string[];
  dominant_direction: EffectDirection | null;
}

export interface ComparisonMatrix {
  clusters: ClaimCluster[];
  contradictions: PairwiseContradiction[];
  summary: EvidenceSummary;
  gaps: string[];
}

// ---------------------------------------------------------------------------
// API request / response shapes (mirror backend route schemas)
// ---------------------------------------------------------------------------

export interface SearchRequest {
  query: string;
  max_results?: number;
}

export interface SearchResponse {
  query: string;
  results: Study[];
  claims: Claim[];
}

export interface CompareRequest {
  study_ids: string[];
  claims?: Claim[];
}

export type CompareResponse = ComparisonMatrix;

/** Combined Phase 4 payload: retrieval + comparison in one call. */
export interface SearchAndCompareResult {
  search: SearchResponse;
  comparison: ComparisonMatrix | null;
}

/** Legacy alias: compare endpoint historically discussed in terms of claims. */
export interface CompareClaimsRequest {
  claim_ids: string[];
}
