import type { Claim, EffectDirection } from "./types";

/** Badge styling per effect direction (light + dark mode). */
export const EFFECT_BADGE: Record<EffectDirection, string> = {
  increases:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  decreases: "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
  no_effect: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  conditional:
    "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  unclear: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
};

/** Graph node border color per effect direction. */
export const EFFECT_NODE_COLOR: Record<EffectDirection, string> = {
  increases: "#10b981",
  decreases: "#f43f5e",
  no_effect: "#71717a",
  conditional: "#f59e0b",
  unclear: "#0ea5e9",
};

export function formatEffectLabel(direction: EffectDirection): string {
  switch (direction) {
    case "increases":
      return "Positive";
    case "decreases":
      return "Negative";
    case "no_effect":
      return "No effect";
    case "conditional":
      return "Conditional";
    case "unclear":
      return "Unclear";
    default:
      return "Unknown";
  }
}

/** Badge class with graceful fallback for unknown backend directions. */
export function effectBadge(direction: string): string {
  return (
    (EFFECT_BADGE as Record<string, string>)[direction] ??
    "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
  );
}

/** Graph node color with graceful fallback for unknown directions. */
export function effectNodeColor(direction: string): string {
  return (EFFECT_NODE_COLOR as Record<string, string>)[direction] ?? "#71717a";
}

/** Majority effect direction across claims; ties resolve to first-seen. */
export function dominantDirection(
  claims: Pick<Claim, "effect_direction">[],
): EffectDirection | null {
  if (claims.length === 0) return null;
  const counts = new Map<EffectDirection, number>();
  for (const claim of claims) {
    counts.set(claim.effect_direction, (counts.get(claim.effect_direction) ?? 0) + 1);
  }
  let best: EffectDirection | null = null;
  let bestCount = 0;
  for (const claim of claims) {
    const count = counts.get(claim.effect_direction) ?? 0;
    if (count > bestCount) {
      best = claim.effect_direction;
      bestCount = count;
    }
  }
  return best;
}

/** Dominant direction among the claims belonging to one study. */
export function effectForStudy(
  studyId: string,
  claims: Pick<Claim, "effect_direction" | "study_id">[],
): EffectDirection | null {
  return dominantDirection(claims.filter((c) => c.study_id === studyId));
}

/** Group claims by their parent study ID. */
export function claimsByStudy(claims: Claim[]): Map<string, Claim[]> {
  const map = new Map<string, Claim[]>();
  for (const claim of claims) {
    const list = map.get(claim.study_id) ?? [];
    list.push(claim);
    map.set(claim.study_id, list);
  }
  return map;
}
