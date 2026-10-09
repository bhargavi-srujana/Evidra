import { ExternalLink, Users, CalendarDays, FlaskConical } from "lucide-react";
import type { EffectDirection, Study } from "@/lib/types";
import { EFFECT_BADGE, formatEffectLabel } from "@/lib/effects";
import { cn } from "@/lib/utils";

interface StudyCardProps {
  study: Study;
  effectDirection?: EffectDirection | null;
  conclusion?: string | null;
  evidenceQuote?: string | null;
  className?: string;
}

/**
 * Resolve a safe external href from a study's url/doi, or null when there
 * is nothing usable. Only http(s) links are allowed: provider-controlled
 * values like `javascript:` (and relative/invalid URLs) are rejected so a
 * poisoned record can never become an executable link.
 */
export function toSafeExternalUrl(
  url: string | null | undefined,
  doi: string | null | undefined,
): string | null {
  const trimmedUrl = url?.trim() || "";
  const trimmedDoi = doi?.trim() || "";
  const raw = trimmedUrl || (trimmedDoi ? `https://doi.org/${trimmedDoi}` : "");
  if (!raw) return null;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  return parsed.href;
}

export default function StudyCard({
  study,
  effectDirection,
  conclusion,
  evidenceQuote,
  className,
}: StudyCardProps) {
  const authorNames = study.authors.map((a) => a.name).join(", ");
  const sourceUrl = toSafeExternalUrl(study.url, study.doi);
  const picoItems: Array<{ label: string; value: string | null }> = [
    { label: "Population", value: study.design.population },
    { label: "Intervention", value: study.design.intervention },
    { label: "Control", value: study.design.control },
    { label: "Outcome", value: study.design.measurement_metric },
  ];

  return (
    <article
      className={cn(
        "rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="max-w-[70%] text-base font-semibold leading-snug text-zinc-900 dark:text-zinc-50">
          {study.title}
        </h3>
        {effectDirection ? (
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-medium",
              EFFECT_BADGE[effectDirection],
            )}
          >
            {formatEffectLabel(effectDirection)}
          </span>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1">
          <Users className="h-3.5 w-3.5" aria-hidden="true" />
          {authorNames || "Unknown authors"}
        </span>
        <span className="inline-flex items-center gap-1">
          <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
          {study.year}
          {study.venue ? ` · ${study.venue}` : ""}
        </span>
        {study.design.study_type ? (
          <span className="inline-flex items-center gap-1">
            <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
            {study.design.study_type}
          </span>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
        {study.abstract}
      </p>

      {conclusion ? (
        <div className="mt-3 rounded-lg border-l-2 border-zinc-300 bg-zinc-50 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">
            Key finding
          </p>
          <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-200">
            {conclusion}
          </p>
          {evidenceQuote ? (
            <p className="mt-1 line-clamp-2 text-xs italic leading-relaxed text-zinc-500 dark:text-zinc-400">
              “{evidenceQuote}”
            </p>
          ) : null}
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
        {picoItems.map(({ label, value }) => (
          <div
            key={label}
            className="rounded-lg bg-zinc-50 px-2.5 py-2 dark:bg-zinc-900"
          >
            <dt className="font-medium uppercase tracking-wide text-zinc-400">
              {label}
            </dt>
            <dd className="mt-0.5 truncate text-zinc-700 dark:text-zinc-200">
              {value ?? "Not reported"}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="font-mono text-zinc-400">{study.study_id}</span>
        {sourceUrl ? (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-zinc-900 underline-offset-4 hover:underline dark:text-zinc-100"
          >
            Source
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : (
          <span className="text-zinc-400">No source link</span>
        )}
      </div>
    </article>
  );
}
