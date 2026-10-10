import { BookOpenCheck, Network, Scale, FlaskConical, Paperclip } from "lucide-react";
import HomeSearch from "@/components/home-search";
import DashboardBackground from "@/components/dashboard-background";
import BookMasthead from "@/components/book-masthead";

const ENGINE_STEPS = [
  {
    icon: BookOpenCheck,
    title: "Retrieve",
    text: "Search and normalize study metadata (PICO, design, venue).",
    art: "doc" as const,
  },
  {
    icon: FlaskConical,
    title: "Extract claims",
    text: "Pull atomic claims with effect direction and confidence.",
    art: "flask" as const,
  },
  {
    icon: Scale,
    title: "Compare",
    text: "Detect contradictions and methodological differences.",
    art: "graph" as const,
  },
  {
    icon: Network,
    title: "Synthesize",
    text: "Graph claims across papers and summarize the evidence.",
    art: "spark" as const,
  },
];

/** Jagged torn-paper edges for the hero stack. */
const TORN_TOP =
  "polygon(0% 4%, 4% 1.5%, 8% 3.5%, 13% 1%, 18% 3%, 24% 1.2%, 30% 3.2%, 36% 1%, 42% 3%, 48% 1.4%, 54% 3.4%, 60% 1%, 66% 3%, 72% 1.3%, 78% 3.3%, 84% 1%, 89% 3%, 94% 1.4%, 98% 3%, 100% 1.8%, 100% 98%, 96% 100%, 91% 97.5%, 85% 99.5%, 79% 97.8%, 72% 99.6%, 65% 97.6%, 58% 99.4%, 51% 97.7%, 44% 99.5%, 37% 97.8%, 30% 99.4%, 23% 97.6%, 16% 99.3%, 10% 97.7%, 5% 99.2%, 0% 97.5%)";

function CardArt({ kind }: { kind: "doc" | "flask" | "graph" | "spark" }) {
  if (kind === "doc") {
    return (
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-3 top-1/2 hidden h-28 w-28 -translate-y-1/2 rotate-3 rounded-[3px] bg-gradient-to-b from-neutral-200 to-neutral-400 p-2 opacity-25 shadow-lg sm:block"
      >
        <div className="space-y-1">
          {["90%", "75%", "85%", "60%", "80%", "70%"].map((w, i) => (
            <div key={i} className="h-1 rounded bg-neutral-600" style={{ width: w }} />
          ))}
        </div>
      </div>
    );
  }
  if (kind === "graph") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 100 100"
        className="pointer-events-none absolute -right-2 top-1/2 hidden h-28 w-28 -translate-y-1/2 text-neutral-400 opacity-30 sm:block"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="20" cy="70" r="5" fill="currentColor" stroke="none" />
        <circle cx="50" cy="40" r="5" fill="currentColor" stroke="none" />
        <circle cx="80" cy="65" r="5" fill="currentColor" stroke="none" />
        <circle cx="65" cy="20" r="4" fill="currentColor" stroke="none" />
        <circle cx="35" cy="85" r="4" fill="currentColor" stroke="none" />
        <line x1="20" y1="70" x2="50" y2="40" />
        <line x1="50" y1="40" x2="80" y2="65" />
        <line x1="50" y1="40" x2="65" y2="20" />
        <line x1="20" y1="70" x2="35" y2="85" />
      </svg>
    );
  }
  if (kind === "spark") {
    return (
      <svg
        aria-hidden="true"
        viewBox="0 0 100 100"
        className="pointer-events-none absolute -right-1 top-1/2 hidden h-24 w-24 -translate-y-1/2 text-neutral-300 opacity-25 sm:block"
        fill="currentColor"
      >
        <path d="M50 5 C52 35 65 48 95 50 C65 52 52 65 50 95 C48 65 35 52 5 50 C35 48 48 35 50 5 Z" />
      </svg>
    );
  }
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute -right-3 top-1/2 hidden h-28 w-20 -translate-y-1/2 space-y-1 opacity-20 sm:block"
    >
      {[70, 45, 85, 60, 75, 50, 65].map((w, i) => (
        <div key={i} className="h-1 rounded bg-neutral-300" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

// Server component by design: everything here is static markup + icons,
// so no client JS ships for the hero. Interactivity lives in
// <BookMasthead /> (search) and <HomeSearch /> (topics).
export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-[#0a0d10] text-neutral-200">
      <DashboardBackground />

      <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 pt-5 sm:px-6">
        <BookMasthead />

        {/* ---- torn paper stack hero ---- */}
        <main className="flex flex-col items-center">
          <div className="relative mt-8 w-full max-w-3xl">
            {/* sheets behind */}
            <div
              aria-hidden="true"
              className="absolute inset-0 -rotate-3 rounded-[3px] bg-neutral-300/90 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.8)]"
              style={{ clipPath: TORN_TOP }}
            />
            <div
              aria-hidden="true"
              className="absolute inset-0 rotate-[1.8deg] rounded-[3px] bg-neutral-200 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.8)]"
              style={{ clipPath: TORN_TOP }}
            />
            {/* top sheet */}
            <div
              className="relative overflow-hidden bg-neutral-50 text-neutral-900 shadow-[0_24px_60px_-12px_rgba(0,0,0,0.85)]"
              style={{ clipPath: TORN_TOP }}
            >
              {/* curled corner */}
              <div
                aria-hidden="true"
                className="absolute right-0 top-0 h-8 w-8"
                style={{
                  background:
                    "linear-gradient(to bottom left, #fafafa 46%, #d4d4d8 50%, #71717a 100%)",
                  clipPath: "polygon(100% 0, 0 0, 100% 100%)",
                }}
              />
              {/* ruled lines peeking on the right, like the reference */}
              <div aria-hidden="true" className="absolute right-6 top-24 hidden w-40 space-y-1.5 opacity-30 sm:block">
                {[95, 88, 92, 80, 86, 74].map((w, i) => (
                  <div key={i} className="h-1 rounded bg-neutral-400" style={{ width: `${w}%` }} />
                ))}
              </div>
              <div className="relative px-6 pb-10 pt-10 text-center sm:px-12">
                <h1 className="text-3xl font-extrabold tracking-tight text-neutral-950 sm:text-[42px] sm:leading-[1.1]">
                  What does the evidence say?
                </h1>
                <p className="mx-auto mt-3 max-w-xl text-[15px] leading-relaxed text-neutral-700">
                  Ask a research question. Evidra retrieves studies, extracts
                  claims, and maps agreements and contradictions.
                </p>
                <HomeSearch topicsOnly variant="onPaper" />
              </div>
            </div>
            {/* paperclip */}
            <Paperclip
              aria-hidden="true"
              className="absolute -top-4 left-8 z-10 h-8 w-8 -rotate-12 text-neutral-400 drop-shadow-[0_2px_3px_rgba(0,0,0,0.5)]"
            />
          </div>

          <section
            aria-label="Engine overview"
            className="grid w-full max-w-3xl grid-cols-1 gap-3 pb-20 pt-8 text-left sm:grid-cols-2"
          >
            {ENGINE_STEPS.map(({ icon: Icon, title, text, art }) => (
              <div
                key={title}
                className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.05] p-5 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.8)] backdrop-blur-xl"
              >
                <CardArt kind={art} />
                <Icon className="h-5 w-5 text-neutral-100" aria-hidden="true" />
                <h2 className="mt-2 text-sm font-semibold text-neutral-50">
                  {title}
                </h2>
                <p className="mt-1 max-w-[85%] text-sm leading-relaxed text-neutral-400">
                  {text}
                </p>
              </div>
            ))}
          </section>
        </main>
      </div>
    </div>
  );
}
