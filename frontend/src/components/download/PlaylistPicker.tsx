import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckSquare, ListVideo, Loader2, Square } from "lucide-react";
import { api, ApiError } from "../../services/api";
import { useT } from "../../i18n/translations";
import type { PlaylistData } from "../../types/download";

function formatDuration(seconds: number | null): string {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Выбор конкретных видео из плейлиста или канала.
 *
 * Раньше плейлист был одной непрозрачной задачей «скачай всё»: ни выбрать три ролика
 * из сорока, ни отменить один из них было нельзя, а падение любого видео (приватное,
 * удалённое, с региональной блокировкой) роняло всю загрузку целиком.
 */
export function PlaylistPicker({
  url,
  onDownload,
}: {
  url: string;
  onDownload: (urls: { url: string; title: string }[]) => Promise<void>;
}) {
  const t = useT();
  const [data, setData] = useState<PlaylistData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    setSelected(new Set());

    api
      .playlist(url, 500, controller.signal)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        // По умолчанию выбрано всё: «скачать плейлист целиком» — самый частый сценарий,
        // и требовать ради него 40 кликов было бы издевательством.
        setSelected(new Set(result.entries.map((e) => e.url).filter(Boolean)));
      })
      .catch((e) => {
        if (cancelled || controller.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [url]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return data.entries;
    return data.entries.filter((e) => e.title.toLowerCase().includes(q));
  }, [data, query]);

  const toggle = useCallback((entryUrl: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(entryUrl)) next.delete(entryUrl);
      else next.add(entryUrl);
      return next;
    });
  }, []);

  const allFilteredSelected = filtered.length > 0 && filtered.every((e) => selected.has(e.url));

  const toggleAll = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      // Кнопка действует на ТО, ЧТО ВИДНО: при активном поиске «выделить все» не должно
      // молча цеплять сотни отфильтрованных строк, которых пользователь не видит.
      if (filtered.every((e) => next.has(e.url))) filtered.forEach((e) => next.delete(e.url));
      else filtered.forEach((e) => next.add(e.url));
      return next;
    });
  }, [filtered]);

  async function start() {
    if (!data || selected.size === 0) return;
    setBusy(true);
    try {
      await onDownload(
        data.entries.filter((e) => selected.has(e.url)).map((e) => ({ url: e.url, title: e.title }))
      );
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="glass rounded-2xl p-4 flex items-center gap-2 text-sm text-text-muted">
        <Loader2 size={14} className="animate-spin text-primary" />
        {t("playlist.loading")}
      </div>
    );
  }

  if (error) return <p className="text-sm text-danger text-center">{error}</p>;
  if (!data) return null;

  return (
    <div className="glass rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <ListVideo size={16} className="text-primary shrink-0" />
        <span className="text-sm font-medium text-text truncate" title={data.title}>
          {data.title}
        </span>
        <span className="text-xs text-text-faint shrink-0">
          {selected.size}/{data.entries_count}
        </span>
      </div>

      {data.truncated && <p className="text-xs text-warning">{t("playlist.truncated")}</p>}

      <div className="flex items-center gap-2">
        <button
          onClick={toggleAll}
          className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1 rounded-lg transition-colors shrink-0"
        >
          {allFilteredSelected ? <CheckSquare size={12} /> : <Square size={12} />}
          {allFilteredSelected ? t("playlist.deselectAll") : t("playlist.selectAll")}
        </button>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("playlist.search")}
          className="flex-1 min-w-0 bg-surface border border-border rounded-lg px-2.5 py-1 text-xs text-text outline-none focus:border-primary/50 placeholder:text-text-faint"
        />
      </div>

      <div className="flex flex-col gap-0.5 max-h-72 overflow-y-auto">
        {filtered.map((entry) => {
          const checked = selected.has(entry.url);
          return (
            <button
              key={entry.id || entry.url || entry.index}
              onClick={() => toggle(entry.url)}
              disabled={!entry.url}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${
                checked ? "bg-surface" : "hover:bg-surface/60"
              } disabled:opacity-40`}
            >
              {checked ? (
                <CheckSquare size={13} className="text-primary shrink-0" />
              ) : (
                <Square size={13} className="text-text-faint shrink-0" />
              )}
              <span className="text-xs text-text-faint font-mono w-7 shrink-0">{entry.index}</span>
              <span className="text-sm text-text truncate flex-1" title={entry.title}>
                {entry.title}
              </span>
              <span className="text-xs text-text-faint font-mono shrink-0">
                {formatDuration(entry.duration)}
              </span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <p className="text-xs text-text-faint py-3 text-center">{t("playlist.noMatches")}</p>
        )}
      </div>

      <button
        onClick={start}
        disabled={busy || selected.size === 0}
        className="bg-primary text-background font-medium text-sm px-4 py-2.5 rounded-xl hover:opacity-90 transition-opacity disabled:opacity-40"
      >
        {busy ? t("playlist.adding") : `${t("playlist.download")} (${selected.size})`}
      </button>
    </div>
  );
}
