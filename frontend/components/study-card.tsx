import { ExternalLink, Users, CalendarDays, FlaskConical } from "lucide-react";
import type { EffectDirection, Study } from "@/lib/types";
import { effectBadge, formatEffectLabel } from "@/lib/effects";
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
        "rounded-[3px] border border-neutral-200 bg-white p-5 text-neutral-900 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.75)] transition-shadow hover:shadow-md",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="max-w-[70%] text-base font-semibold leading-snug text-neutral-900">
          {study.title}
        </h3>
        <span className="inline-flex shrink-0 items-center gap-1.5">
          {study.is_fallback ? (
            <span
              title="Heuristic verdict — the LLM did not analyze this paper (quota limits or thin snippet)"
              className="inline-flex shrink-0 items-center rounded-full bg-neutral-200 px-2.5 py-1 text-xs font-medium text-neutral-600"
            >
              Heuristic
            </span>
          ) : null}
          {effectDirection ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-medium",
                effectBadge(effectDirection),
              )}
            >
              {formatEffectLabel(effectDirection)}
            </span>
          ) : null}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500">
        <span className="inline-flex items-center gap-1">
          <Users className="h-3.5 w-3.5" aria-hidden="true" />
          {authorNames || "Unknown authors"}
        </span>
        <span className="inline-flex items-center gap-1">
          <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
          {study.year ?? "Year unknown"}
          {study.venue ? ` · ${study.venue}` : ""}
        </span>
        {study.design.study_type ? (
          <span className="inline-flex items-center gap-1">
            <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
            {study.design.study_type}
          </span>
        ) : null}
      </div>

      <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-neutral-600">
        {study.abstract?.trim() || "Abstract not reported."}
      </p>

      {conclusion ? (
        <div className="mt-3 rounded-lg border-l-2 border-neutral-300 bg-neutral-100 px-3 py-2">
          <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">
            Key finding
          </p>
          <p className="mt-1 text-sm leading-relaxed text-neutral-700">
            {conclusion}
          </p>
          {evidenceQuote ? (
            <p className="mt-1 line-clamp-2 text-xs italic leading-relaxed text-neutral-500">
              “{evidenceQuote}”
            </p>
          ) : null}
        </div>
      ) : null}

      <dl className="mt-4 grid grid-cols-2 gap-2 text-xs">
        {picoItems.map(({ label, value }) => (
          <div
            key={label}
            className="rounded-lg bg-neutral-100 px-2.5 py-2"
          >
            <dt className="font-medium uppercase tracking-wide text-neutral-500">
              {label}
            </dt>
            <dd className="mt-0.5 truncate text-neutral-700" title={value ?? "Not reported"}>
              {value ?? "Not reported"}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="font-mono text-neutral-400">{study.study_id}</span>
        {sourceUrl ? (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium text-neutral-900 underline-offset-4 hover:underline"
          >
            Source
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        ) : (
          <span className="text-neutral-400">No source link</span>
        )}
      </div>
    </article>
  );
}
