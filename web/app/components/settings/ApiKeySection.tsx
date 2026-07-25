"use client";

import { useCallback, useEffect, useState } from "react";
import { authedFetch } from "../../lib/useDashboardWidget";
import { KeyUsageNote } from "./KeyUsageNote";

async function readDetail(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    return "Something went wrong.";
  }
}

/**
 * The BYOK Anthropic key card (Settings). Self-contained: loads status on
 * mount, saves/removes via /api/settings/api-key. `onSaved` fires after a
 * successful save/remove so the page can show its toast.
 */
export function ApiKeySection({ onSaved }: { onSaved?: () => void }) {
  const [keySet, setKeySet] = useState<boolean | null>(null);
  const [keyLast4, setKeyLast4] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [keyVisible, setKeyVisible] = useState(false);
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);

  const loadKeyStatus = useCallback(async () => {
    try {
      const res = await authedFetch("/api/settings/api-key");
      if (res.ok) {
        const j = await res.json();
        setKeySet(!!j.set);
        setKeyLast4(j.last4 ?? null);
      }
    } catch {
      /* leave status unknown */
    }
  }, []);

  useEffect(() => {
    loadKeyStatus();
  }, [loadKeyStatus]);

  async function saveKey() {
    const key = keyInput.trim();
    if (!key) return;
    setKeyBusy(true);
    setKeyError(null);
    try {
      const res = await authedFetch("/api/settings/api-key", {
        method: "PUT",
        body: JSON.stringify({ key }),
      });
      if (!res.ok) throw new Error(await readDetail(res));
      const j = await res.json();
      setKeySet(true);
      setKeyLast4(j.last4 ?? null);
      setKeyInput("");
      onSaved?.();
    } catch (e: unknown) {
      setKeyError(e instanceof Error ? e.message : "Couldn't save your key.");
    } finally {
      setKeyBusy(false);
    }
  }

  async function removeKey() {
    setKeyBusy(true);
    setKeyError(null);
    try {
      const res = await authedFetch("/api/settings/api-key", { method: "DELETE" });
      if (!res.ok) throw new Error(await readDetail(res));
      setKeySet(false);
      setKeyLast4(null);
      onSaved?.();
    } catch (e: unknown) {
      setKeyError(e instanceof Error ? e.message : "Couldn't remove your key.");
    } finally {
      setKeyBusy(false);
    }
  }

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">Anthropic API Key</h3>
        {keySet === true && (
          <span className="text-xs bg-green-100 text-green-700 px-2.5 py-0.5 rounded-full font-medium">
            Connected ••••{keyLast4}
          </span>
        )}
        {keySet === false && (
          <span className="text-xs bg-amber-100 text-amber-700 px-2.5 py-0.5 rounded-full font-medium">
            Not set
          </span>
        )}
      </div>
      <p className="text-sm text-gray-500">
        Create one at{" "}
        <a
          href="https://console.anthropic.com/settings/keys"
          target="_blank"
          rel="noopener noreferrer"
          className="text-violet-600 underline"
        >
          console.anthropic.com
        </a>
        . It should start with <code className="text-gray-600">sk-ant-</code>.
      </p>
      <div className="relative">
        <input
          type={keyVisible ? "text" : "password"}
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          placeholder={keySet ? "Enter a new key to replace the current one" : "sk-ant-..."}
          autoComplete="off"
          className="w-full px-3 py-2 pr-16 rounded-xl border border-gray-200 bg-gray-50 text-sm font-mono outline-none focus:border-gray-400"
        />
        {keyInput && (
          <button
            type="button"
            onClick={() => setKeyVisible((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 rounded-lg text-xs text-gray-400 hover:text-gray-600 transition"
          >
            {keyVisible ? "Hide" : "Show"}
          </button>
        )}
      </div>
      <div className="flex gap-2">
        <button
          onClick={saveKey}
          disabled={keyBusy || !keyInput.trim()}
          className="px-4 py-2 rounded-xl bg-violet-600 text-white disabled:opacity-40 text-sm"
        >
          {keyBusy ? "Verifying…" : keySet ? "Update Key" : "Save Key"}
        </button>
        {keySet && (
          <button
            onClick={removeKey}
            disabled={keyBusy}
            className="px-4 py-2 rounded-xl border border-gray-200 text-gray-600 hover:border-red-300 hover:text-red-500 disabled:opacity-40 text-sm transition"
          >
            Remove
          </button>
        )}
      </div>
      {keyError && (
        <div className="text-sm text-red-500 bg-red-50 border border-red-500/30 rounded-xl p-3">
          {keyError}
        </div>
      )}
      <KeyUsageNote />
    </div>
  );
}
