"use client";

/** Tailwind classes for a verdict pill, by its leading word. */
export function verdictColor(verdict: string): string {
  const word = verdict.split(/[\s—–-]/)[0].toUpperCase();
  if (word === "ACCEPT") return "bg-green-50 border-green-500/30 text-green-900";
  if (word === "DECLINE") return "bg-red-50 border-red-500/30 text-red-900";
  return "bg-amber-50 border-amber-500/30 text-amber-900";
}

/** Renders a trade analysis into its VERDICT / ANALYSIS / COUNTER OFFER cards. */
export function AnalysisRenderer({ text }: { text: string }) {
  const sections = {
    verdict: "",
    analysis: "",
    counter: "",
  };

  const verdictMatch = text.match(/VERDICT\s*([\s\S]*?)(?=ANALYSIS|$)/i);
  const analysisMatch = text.match(/ANALYSIS\s*([\s\S]*?)(?=COUNTER OFFER|$)/i);
  const counterMatch = text.match(/COUNTER OFFER\s*([\s\S]*?)$/i);

  if (verdictMatch) sections.verdict = verdictMatch[1].trim();
  if (analysisMatch) sections.analysis = analysisMatch[1].trim();
  if (counterMatch) sections.counter = counterMatch[1].trim();

  return (
    <div className="space-y-4">
      {sections.verdict && (
        <div className={`border rounded-2xl p-5 ${verdictColor(sections.verdict)}`}>
          <div className="text-xs font-semibold uppercase tracking-widest mb-1 opacity-60">
            Verdict
          </div>
          <p className="font-semibold text-lg leading-snug">{sections.verdict}</p>
        </div>
      )}

      {sections.analysis && (
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Analysis
          </div>
          <div className="space-y-3">
            {sections.analysis.split("\n\n").map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed">
                {para.trim()}
              </p>
            ))}
          </div>
        </div>
      )}

      {sections.counter && (
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Counter Offer
          </div>
          <div className="space-y-3">
            {sections.counter.split("\n\n").map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed">
                {para.trim()}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
