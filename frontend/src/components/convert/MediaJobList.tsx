import { CheckCircle2, FolderOpen, Loader2, X, XCircle, Zap } from "lucide-react";
import { api } from "../../services/api";
import { useT } from "../../i18n/translations";
import type { MediaJob } from "../../types/download";

const KIND_LABELS: Record<string, string> = {
  remux: "container",
  trim: "trim",
  replace_audio: "audio",
  extract_audio: "extract",
  convert: "convert",
  gif: "gif",
  thumbnail: "frame",
};

function formatSize(bytes: number): string {
  if (!bytes) return "";
  const mb = bytes / 1024 / 1024;
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

export function MediaJobList({
  jobs,
  onCancel,
  onClear,
}: {
  jobs: MediaJob[];
  onCancel: (id: string) => void;
  onClear: () => void;
}) {
  const t = useT();
  if (jobs.length === 0) return null;

  const finished = jobs.filter((j) => j.status !== "queued" && j.status !== "running").length;

  return (
    <section className="glass rounded-2xl p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-text-muted">{t("convert.jobs")}</h2>
        {finished > 0 && (
          <button onClick={onClear} className="text-xs text-text-faint hover:text-text transition-colors">
            {t("convert.clearFinished")}
          </button>
        )}
      </div>

      {jobs.map((job) => {
        const running = job.status === "running" || job.status === "queued";
        return (
          <div key={job.id} className="bg-surface rounded-xl px-3 py-2 flex flex-col gap-1.5">
            <div className="flex items-center gap-2 min-w-0">
              {job.status === "completed" && <CheckCircle2 size={14} className="text-success shrink-0" />}
              {(job.status === "failed" || job.status === "cancelled") && (
                <XCircle size={14} className="text-danger shrink-0" />
              )}
              {running && <Loader2 size={14} className="text-primary shrink-0 animate-spin" />}

              <span className="text-sm text-text truncate" title={job.output || job.source}>
                {job.output_name || job.source_name}
              </span>
              <span className="text-[10px] uppercase tracking-wide text-text-faint bg-surface-elevated px-1.5 py-0.5 rounded shrink-0">
                {KIND_LABELS[job.kind] ?? job.kind}
              </span>

              {/* Главный вопрос про любую операцию — потерялось ли качество.
                  Ответ виден до, во время и после, а не прячется в логах. */}
              {job.lossless === true && (
                <span
                  className="flex items-center gap-1 text-[10px] text-success shrink-0"
                  title={t("convert.losslessHint")}
                >
                  <Zap size={10} /> {t("convert.lossless")}
                </span>
              )}
              {job.lossless === false && (
                <span className="text-[10px] text-warning shrink-0">{t("convert.reencode")}</span>
              )}

              <div className="ml-auto flex items-center gap-2 shrink-0">
                {job.size > 0 && <span className="text-xs text-text-faint font-mono">{formatSize(job.size)}</span>}
                {job.status === "completed" && job.output && (
                  <button
                    onClick={() => api.reveal(job.output).catch(() => undefined)}
                    className="text-text-faint hover:text-text transition-colors"
                    title={t("history.openFolder")}
                  >
                    <FolderOpen size={14} />
                  </button>
                )}
                {running && (
                  <button
                    onClick={() => onCancel(job.id)}
                    className="text-text-faint hover:text-danger transition-colors"
                    title={t("convert.cancel")}
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>

            {running && (
              <div className="h-1 bg-surface-elevated rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-[width] duration-200"
                  style={{ width: `${Math.max(2, job.progress)}%` }}
                />
              </div>
            )}

            {job.notes.length > 0 && (
              <p className="text-[11px] text-text-faint leading-snug">{job.notes.join(" · ")}</p>
            )}
            {job.error && <p className="text-[11px] text-danger leading-snug break-words">{job.error}</p>}
          </div>
        );
      })}
    </section>
  );
}
