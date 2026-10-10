"use client";

import { useMemo } from "react";
import { FileText } from "lucide-react";
import type { Claim, Study } from "@/lib/types";
import { glassPanel } from "@/components/paper";
import { cn } from "@/lib/utils";

interface PdfBackstopProps {
  claims: Claim[];
  studies: Study[];
  className?: string;
}

interface Snippet {
  key: string;
  source: string;
  quote: string;
}

/**
 * PDF Source Backstop: shows the verbatim evidence spans grounding the top
 * claims as highlighted excerpts on faux PDF page thumbnails. Parsing is
 * done with PyMuPDF on the backend (see search_serp.fetch_pdf_text).
 */
export default function PdfBackstop({ claims, studies, className }: PdfBackstopProps) {
  const snippets: Snippet[] = useMemo(() => {
    const studyById = new Map(studies.map((s) => [s.study_id, s]));
    return [...claims]
      .sort((a, b) => b.confidence_score - a.confidence_score)
      .map((c) => ({
        key: c.claim_id,
        source: studyById.get(c.study_id)?.title ?? c.study_id,
        quote: (c.verbatim_evidence_quote || c.evidence_span || "").trim(),
      }))
      .filter((s) => s.quote.length > 0)
      .slice(0, 2);
  }, [claims, studies]);

  return (
    <div className={cn(glassPanel, "p-5", className)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-neutral-100">
          PDF Source Backstop
        </h3>
        <span
          title="Open-access PDFs are parsed with PyMuPDF; extracts ground the LLM payload"
          className="inline-flex items-center gap-1.5 rounded-lg bg-neutral-800 px-2.5 py-1 text-xs font-semibold text-neutral-200"
        >
          <FileText className="h-3.5 w-3.5 text-red-400" aria-hidden="true" />
          PyMuPDF
        </span>
      </div>

      {snippets.length === 0 ? (
        <p role="status" className="mt-3 text-sm text-neutral-400">
          No PDF extracts grounded this run — snippets will appear here when
          open-access PDFs back the evidence.
        </p>
      ) : (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {snippets.map((snippet) => (
            <figure
              key={snippet.key}
              className="overflow-hidden rounded-md bg-neutral-100 text-neutral-900 shadow-lg"
            >
              <div className="border-b border-neutral-200 bg-neutral-200/70 px-3 py-1.5">
                <p className="truncate text-[10px] font-medium text-neutral-600" title={snippet.source}>
                  {snippet.source}
                </p>
              </div>
              <div className="space-y-1.5 p-3" aria-label={`Highlighted PDF excerpt for ${snippet.source}`}>
                {/* faux surrounding page text */}
                <div className="h-1 rounded bg-neutral-300/80" style={{ width: "96%" }} />
                <div className="h-1 rounded bg-neutral-300/80" style={{ width: "88%" }} />
                <blockquote className="rounded-sm bg-yellow-200/90 px-1.5 py-1 text-[10px] font-medium leading-snug text-neutral-900">
                  “{snippet.quote.length > 220 ? `${snippet.quote.slice(0, 220)}…` : snippet.quote}”
                </blockquote>
                <div className="h-1 rounded bg-neutral-300/80" style={{ width: "93%" }} />
                <div className="h-1 rounded bg-neutral-300/80" style={{ width: "76%" }} />
                <div className="h-1 rounded bg-neutral-300/80" style={{ width: "84%" }} />
              </div>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
