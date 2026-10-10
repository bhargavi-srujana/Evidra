import {
  GitCompareArrows,
  Network,
  Search,
  TriangleAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";

const TOC_ITEMS = [
  { n: 1, label: "Query Overview", href: "#query-overview", icon: Search },
  {
    n: 2,
    label: "Contradiction Explorer",
    href: "#contradiction-explorer",
    icon: GitCompareArrows,
  },
  { n: 3, label: "Evidence Graph", href: "#evidence-graph", icon: Network },
  {
    n: 4,
    label: "Research Gaps",
    href: "#research-gaps",
    icon: TriangleAlert,
  },
];

/**
 * Table of Contents sidebar: darker glassmorphism panel with anchor
 * navigation plus faint background print, like the reference board.
 */
export default function TocSidebar({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Table of Contents"
      className={cn(
        "rounded-2xl border border-neutral-800 bg-black/55 p-4 backdrop-blur-xl",
        className,
      )}
    >
      <p className="px-2 text-xs font-semibold uppercase tracking-[0.18em] text-neutral-400">
        Table of Contents
      </p>
      <ul className="mt-3 space-y-1">
        {TOC_ITEMS.map(({ n, label, href, icon: Icon }) => (
          <li key={href}>
            <a
              href={href}
              className="group flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm text-neutral-300 transition-colors hover:bg-neutral-800/70 hover:text-neutral-50"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-neutral-800 text-[11px] font-bold text-neutral-300 group-hover:bg-neutral-700 group-hover:text-white">
                {n}
              </span>
              <Icon
                className="h-4 w-4 shrink-0 text-neutral-500 group-hover:text-neutral-300"
                aria-hidden="true"
              />
              <span className="leading-tight">{label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
