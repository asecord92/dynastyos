/**
 * "What uses your key" — the cost disclosure that sits under the API key field.
 *
 * Two reasons this exists in one place rather than as per-feature badges: the
 * AI surfaces already announce themselves *before* a key is set (each renders
 * `NeedsApiKey`), and that signal disappears the moment one is saved. And the
 * part people don't expect isn't which features are AI — it's the spend they
 * didn't click for. So the split below is by *who triggered it*, not by feature
 * area, and the free surfaces are named explicitly so nobody avoids the cap
 * planner thinking it costs them.
 *
 * KEEP IN SYNC with the `tool=` call sites of `get_ai_client_for_league` in
 * api/main.py — that function is the only thing that spends the owner's key.
 */
export function KeyUsageNote() {
  return (
    <div className="border-t border-gray-200 pt-4 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
        What uses your key
      </p>
      <ul className="space-y-2 text-xs text-gray-500 leading-relaxed">
        <li>
          <span className="font-medium text-gray-600">When you ask for it — </span>
          the trade analyzer, the trade target finder, and waiver add/drop advice.
        </li>
        <li>
          <span className="font-medium text-gray-600">On its own — </span>
          your dashboard widgets (news, start/sit, waivers, minors) regenerate
          every few hours as you use the app, and the daily digest sends each
          morning if you&apos;ve turned it on. That spend happens without you
          clicking anything.
        </li>
        <li>
          <span className="font-medium text-gray-600">Free — </span>
          the cap planner and dynasty roster page, category ranks, standings,
          the injury ticker, and trade history use no AI at all.
        </li>
      </ul>
    </div>
  );
}
