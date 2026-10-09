import { BookOpenCheck, Network, Scale, FlaskConical } from "lucide-react";
import HomeSearch from "@/components/home-search";

const ENGINE_STEPS = [
  {
    icon: BookOpenCheck,
    title: "Retrieve",
    text: "Search and normalize study metadata (PICO, design, venue).",
  },
  {
    icon: FlaskConical,
    title: "Extract claims",
    text: "Pull atomic claims with effect direction and confidence.",
  },
  {
    icon: Scale,
    title: "Compare",
    text: "Detect contradictions and methodological differences.",
  },
  {
    icon: Network,
    title: "Synthesize",
    text: "Graph claims across papers and summarize the evidence.",
  },
];

// Server component by design: everything here is static markup + icons,
// so no client JS ships for the hero. Interactivity lives in <HomeSearch />.
export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 dark:bg-black">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <span className="text-lg font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          Evidra
        </span>
        <span className="rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
          Phase 1 · Frontend scaffold
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center px-6 pt-16 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-zinc-900 sm:text-5xl dark:text-zinc-50">
          What does the evidence say?
        </h1>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-zinc-600 dark:text-zinc-400">
          Ask a research question. Evidra retrieves studies, extracts claims,
          and maps agreements and contradictions.
        </p>

        <HomeSearch />

        <section
          aria-label="Engine overview"
          className="mt-14 grid w-full grid-cols-1 gap-3 pb-20 text-left sm:grid-cols-2"
        >
          {ENGINE_STEPS.map(({ icon: Icon, title, text }) => (
            <div
              key={title}
              className="rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-950"
            >
              <Icon
                className="h-5 w-5 text-zinc-900 dark:text-zinc-100"
                aria-hidden="true"
              />
              <h2 className="mt-2 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                {title}
              </h2>
              <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                {text}
              </p>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
