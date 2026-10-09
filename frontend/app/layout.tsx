import type { Metadata } from "next";
import { GeistSans as Geist } from "geist/font/sans";
import { GeistMono as Geist_Mono } from "geist/font/mono";
import "./globals.css";

const geistSans = Geist;
const geistMono = Geist_Mono;

// System font stacks used if the self-hosted Geist variables are unavailable.
const sansVariable = geistSans?.variable ?? "";
const monoVariable = geistMono?.variable ?? "";

export const metadata: Metadata = {
  title: "Evidra — Evidence Synthesis Engine",
  description:
    "Ask a research question and explore supporting, conditional, and contradicting evidence across studies.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${sansVariable} ${monoVariable} h-full antialiased`}
    >
      <body suppressHydrationWarning className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
