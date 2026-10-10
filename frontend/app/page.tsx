import { Paperclip } from "lucide-react";
import Image from "next/image";
import HomeSearch from "@/components/home-search";
import DashboardBackground from "@/components/dashboard-background";
import BookMasthead from "@/components/book-masthead";

const ENGINE_STEPS = [
  {
    title: "Retrieve",
    text: "Search and normalize study metadata (PICO, design, venue).",
    img: "/researchpaper.png",
    imgAlt: "Stack of research papers with a results chart",
    imgClassName: "h-28 w-auto",
  },
  {
    title: "Extract claims",
    text: "Pull atomic claims with effect direction and confidence.",
    img: "/glass.png",
    imgAlt: "Magnifying glass",
    imgClassName: "h-24 w-auto",
  },
  {
    title: "Compare",
    text: "Detect contradictions and methodological differences.",
    img: "/compare.png",
    imgAlt: "Balance scale weighing two sides",
    imgClassName: "h-20 w-auto",
  },
  {
    title: "Synthesize",
    text: "Graph claims across papers and summarize the evidence.",
    img: "/synthesis.png",
    imgAlt: "Diagram funneling multiple sources into one summary",
    imgClassName: "h-24 w-auto",
  },
];

/** Jagged torn-paper edges for the hero stack. */
const TORN_TOP =
  "polygon(0% 4%, 4% 1.5%, 8% 3.5%, 13% 1%, 18% 3%, 24% 1.2%, 30% 3.2%, 36% 1%, 42% 3%, 48% 1.4%, 54% 3.4%, 60% 1%, 66% 3%, 72% 1.3%, 78% 3.3%, 84% 1%, 89% 3%, 94% 1.4%, 98% 3%, 100% 1.8%, 100% 98%, 96% 100%, 91% 97.5%, 85% 99.5%, 79% 97.8%, 72% 99.6%, 65% 97.6%, 58% 99.4%, 51% 97.7%, 44% 99.5%, 37% 97.8%, 30% 99.4%, 23% 97.6%, 16% 99.3%, 10% 97.7%, 5% 99.2%, 0% 97.5%)";

// Server component by design: everything here is static markup + icons,
// so no client JS ships for the hero. Interactivity lives in
// <BookMasthead /> (search) and <HomeSearch /> (topics).
export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-[rgb(35,39,42)] text-neutral-200">
      <DashboardBackground />

      <div className="relative z-10 mx-auto  flex-1 flex-col pt-5 ">
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
            {ENGINE_STEPS.map(({ title, text, img, imgAlt, imgClassName }) => (
              <div
                key={title}
                className="relative flex items-center gap-4 overflow-hidden rounded-2xl border border-white/10 bg-white/[0.05] p-5 shadow-[0_18px_45px_-12px_rgba(0,0,0,0.8)] backdrop-blur-xl"
              >
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-neutral-50">
                    {title}
                  </h2>
                  <p className="mt-1 text-sm leading-relaxed text-neutral-400">
                    {text}
                  </p>
                </div>
                <Image
                  src={img}
                  alt={imgAlt}
                  width={160}
                  height={160}
                  className={`pointer-events-none shrink-0 object-contain mix-blend-screen ${imgClassName}`}
                />
              </div>
            ))}
          </section>
        </main>
      </div>
    </div>
  );
}
