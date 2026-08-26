import { FolderOpen, History as HistoryIcon, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import type { HistoryEntry } from "../../types/download";
import { useT } from "../../i18n/translations";

export function HistoryPage({ onRedownload }: { onRedownload: (url: string) => void }) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [query, setQuery] = useState("");
  const t = useT();

  useEffect(() => {
    let cancelled = false;
    function load(attempt = 0) {
      api
        .getHistory()
        .then((e) => {
          if (!cancelled) setEntries(e);
        })
        .catch(() => {
          // бэкенд ещё не поднялся — раньше это был unhandled rejection и пустая
          // история навсегда, без единой попытки перезапроса
          if (!cancelled && attempt < 5) setTimeout(() => load(attempt + 1), Math.min(500 * 2 ** attempt, 5000));
        });
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function clear() {
    await api.clearHistory();
    setEntries([]);
  }

  const filtered = entries.filter(
    (e) =>
      e.title.toLowerCase().includes(query.toLowerCase()) ||
      e.url.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-4 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text">{t("history.title")}</h1>
        {entries.length > 0 && (
          <button
            onClick={clear}
            className="flex items-center gap-1.5 text-xs text-text-faint hover:text-danger transition-colors"
          >
            <Trash2 size={13} />
            {t("history.clear")}
          </button>
        )}
      </div>

      {entries.length > 0 && (
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("history.search")}
          className="glass rounded-xl px-3.5 py-2 text-sm outline-none placeholder:text-text-faint"
        />
      )}

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-14 text-text-faint">
          <HistoryIcon size={22} />
          <p className="text-sm">{t("history.empty.title")}</p>
          <p className="text-xs">{t("history.empty.subtitle")}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {filtered.map((e, i) => (
            <div key={i} className="glass rounded-xl px-3.5 py-2.5 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-text truncate">{e.title}</p>
                <p className="text-xs text-text-faint truncate font-mono">
                  {formatMeta(e)}
                  {e.ru_dub === false ? " · без RU-дорожки" : ""}
                  {e.ru_dub === true ? " · RU" : ""}
                </p>
              </div>
              {e.path && (
                <button
                  onClick={() => api.reveal(e.path).catch(() => undefined)}
                  className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1.5 rounded-lg transition-colors shrink-0"
                  title={t("history.openFolder")}
                >
                  <FolderOpen size={12} />
                </button>
              )}
              <button
                onClick={() => onRedownload(e.url)}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1.5 rounded-lg transition-colors shrink-0"
              >
                <RotateCcw size={12} />
                {t("history.again")}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatMeta(e: HistoryEntry): string {
  const parts: string[] = [];
  if (e.finished_at) parts.push(new Date(e.finished_at * 1000).toLocaleString());
  if (e.size) parts.push(`${(e.size / 1024 / 1024).toFixed(1)} MB`);
  if (e.quality && !e.audio_only) parts.push(e.quality);
  if (e.audio_only) parts.push("audio");
  return parts.length ? parts.join(" · ") : e.url;
}
