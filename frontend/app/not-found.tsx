import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center px-6 text-center">
      <p className="text-xs font-medium uppercase tracking-widest text-zinc-500">
        404
      </p>
      <h1 className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
        Page not found
      </h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        The page you requested does not exist. Try a research question from the
        home page.
      </p>
      <Link
        href="/"
        className="mt-4 rounded-xl bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-zinc-700 dark:bg-zinc-50 dark:text-zinc-900"
      >
        Home
      </Link>
    </main>
  );
}
