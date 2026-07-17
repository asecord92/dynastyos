"use client";

import { MarkdownContent } from "../../lib/format";

/** Tailwind classes for a verdict pill, by its leading word. */
export function verdictColor(verdict: string): string {
  const word = verdict.replace(/\*/g, "").trim().split(/[\s—–-]/)[0].toUpperCase();
  if (word === "ACCEPT") return "bg-green-50 border-green-500/30 text-green-900";
  if (word === "DECLINE") return "bg-red-50 border-red-500/30 text-red-900";
  return "bg-amber-50 border-amber-500/30 text-amber-900";
}

// Section headers are matched case-SENSITIVELY: the model writes them in caps,
// while its prose says things like "before giving my verdict." — a
// case-insensitive match latches onto that prose word and shreds the sections.
const SECTIONS = {
  verdict: /\bVERDICT\b\s*([\s\S]*?)(?=\bANALYSIS\b|$)/,
  analysis: /\bANALYSIS\b\s*([\s\S]*?)(?=\bCOUNTER OFFER\b|$)/,
  counter: /\bCOUNTER OFFER\b\s*([\s\S]*?)$/,
};

/** A section body, minus any bold markers / colons glued to the header. */
function section(text: string, re: RegExp): string {
  const m = text.match(re);
  return m ? m[1].replace(/^[*:\s]+/, "").trim() : "";
}

/** Renders a trade analysis into its VERDICT / ANALYSIS / COUNTER OFFER cards. */
export function AnalysisRenderer({ text }: { text: string }) {
  const verdict = section(text, SECTIONS.verdict);
  const analysis = section(text, SECTIONS.analysis);
  const counter = section(text, SECTIONS.counter);

  return (
    <div className="space-y-4">
      {verdict && (
        <div className={`border rounded-2xl p-5 ${verdictColor(verdict)}`}>
          <div className="text-xs font-semibold uppercase tracking-widest mb-1 opacity-60">
            Verdict
          </div>
          <p className="font-semibold text-lg leading-snug">
            {verdict.replace(/\*\*/g, "")}
          </p>
        </div>
      )}

      {analysis && (
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Analysis
          </div>
          <MarkdownContent text={analysis} />
        </div>
      )}

      {counter && (
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Counter Offer
          </div>
          <MarkdownContent text={counter} />
        </div>
      )}
    </div>
  );
}
