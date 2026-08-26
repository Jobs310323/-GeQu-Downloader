import { motion } from "framer-motion";
import { Check, Copy, FileText, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../services/api";
import type { VideoSummary } from "../../types/download";
import { useT } from "../../i18n/translations";

export function SummaryModal({
  url,
  title,
  duration,
  onClose,
}: {
  url: string;
  title: string;
  duration: number | null;
  onClose: () => void;
}) {
  const [data, setData] = useState<VideoSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const t = useT();

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    api
      .summarize(url, title, duration, controller.signal)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e) => {
        if (cancelled || controller.signal.aborted) return;
        if (e instanceof ApiError && e.code === "NO_TRANSCRIPT") setError(t("summary.unavailable"));
        else setError(e instanceof ApiError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [url, title, duration, t]);

  async function copy() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.summary);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // буфер обмена может быть недоступен — текст всё равно виден и выделяем мышью
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.18 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-elevated rounded-2xl p-5 w-[560px] max-w-[92vw] max-h-[80vh] flex flex-col"
      >
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-full bg-primary/15 flex items-center justify-center shrink-0">
            <FileText size={16} className="text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-text">{t("summary.title")}</h3>
            <p className="text-xs text-text-faint truncate">{title}</p>
          </div>
          {data && (
            <button
              onClick={copy}
              className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1.5 rounded-lg transition-colors shrink-0"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? t("summary.copied") : t("summary.copy")}
            </button>
          )}
          <button onClick={onClose} className="text-text-faint hover:text-text shrink-0 p-1">
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 overflow-y-auto min-h-[80px]">
          {!data && !error && (
            <p className="flex items-center gap-2 text-sm text-text-muted">
              <Loader2 size={14} className="animate-spin" />
              {t("summary.loading")}
            </p>
          )}
          {error && <p className="text-sm text-danger">{error}</p>}
          {data && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-text leading-relaxed whitespace-pre-wrap">{data.summary}</p>
              {data.engine === "local" && (
                <p className="text-xs text-text-faint border-t border-border pt-2">
                  {t("summary.local")}
                  {data.fallback_reason ? ` · ${data.fallback_reason}` : ""}
                </p>
              )}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
