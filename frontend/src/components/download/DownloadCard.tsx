import { motion } from "framer-motion";
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, Pause, Play, VideoIcon, X } from "lucide-react";
import type { DownloadJob } from "../../types/download";

const STATUS_LABEL: Record<string, string> = {
  queued: "Queued",
  analyzing: "Analyzing...",
  resolving: "Resolving format...",
  starting: "Starting...",
  downloading: "Downloading...",
  merging: "Merging...",
  converting: "Converting...",
  paused: "Paused",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STATUS_COLOR: Record<string, string> = {
  queued: "text-text-faint",
  analyzing: "text-secondary",
  resolving: "text-secondary",
  starting: "text-primary",
  downloading: "text-primary",
  merging: "text-primary",
  converting: "text-primary",
  paused: "text-warning",
  completed: "text-success",
  failed: "text-danger",
  cancelled: "text-text-faint",
};

export function DownloadCard({
  job,
  onPause,
  onResume,
  onCancel,
  onDismiss,
  onMove,
  canMoveUp,
  canMoveDown,
}: {
  job: DownloadJob;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onDismiss: () => void;
  onMove?: (delta: number) => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
}) {
  const finished = job.status === "completed";
  const terminal = ["completed", "failed", "cancelled"].includes(job.status);
  // Пауза доступна не только качающейся задаче, но и ожидающей: иначе «придержать
  // очередь» невозможно — остановишь текущую, и тут же стартует следующая.
  const pausable = !terminal;
  // Переставлять имеет смысл только то, что ещё не начало качаться.
  const reorderable = job.status === "queued" || job.status === "paused";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.2 }}
      className="glass rounded-xl p-3.5 flex items-center gap-3"
    >
      <div className="w-16 h-10 rounded-md bg-surface-elevated shrink-0 flex items-center justify-center overflow-hidden">
        {job.thumbnail ? (
          <img src={job.thumbnail} className="w-full h-full object-cover" />
        ) : (
          <VideoIcon size={16} className="text-text-faint" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm text-text truncate">{job.title || job.url}</p>
        <div className="flex items-center gap-2 mt-1">
          {job.status === "downloading" && (
            <div className="flex-1 h-1.5 rounded-full bg-surface-elevated overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-primary to-secondary"
                animate={{ width: `${job.progress}%` }}
                transition={{ duration: 0.2 }}
              />
            </div>
          )}
          <span className={`text-xs font-mono shrink-0 ${STATUS_COLOR[job.status] ?? "text-text-faint"}`}>
            {job.status === "downloading" && job.progress > 0
              ? `${job.progress.toFixed(0)}%`
              : STATUS_LABEL[job.status] ?? job.status}
            {job.status === "downloading" && job.speed ? ` · ${job.speed}` : ""}
          </span>
        </div>
        {job.error && (
          <p className="flex items-center gap-1 text-xs text-danger mt-1">
            <AlertCircle size={12} />
            {job.error.message}
          </p>
        )}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        {finished && <CheckCircle2 size={16} className="text-success" />}
        {reorderable && onMove && (
          <>
            <button
              onClick={() => onMove(-1)}
              disabled={!canMoveUp}
              className="p-1 rounded-lg text-text-faint hover:text-text hover:bg-surface-elevated transition-colors disabled:opacity-30 disabled:hover:text-text-faint"
              aria-label="Move up"
            >
              <ArrowUp size={13} />
            </button>
            <button
              onClick={() => onMove(1)}
              disabled={!canMoveDown}
              className="p-1 rounded-lg text-text-faint hover:text-text hover:bg-surface-elevated transition-colors disabled:opacity-30 disabled:hover:text-text-faint"
              aria-label="Move down"
            >
              <ArrowDown size={13} />
            </button>
          </>
        )}
        {pausable && (
          <button
            onClick={job.status === "paused" ? onResume : onPause}
            className="p-1.5 rounded-lg text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
            aria-label={job.status === "paused" ? "Resume" : "Pause"}
          >
            {job.status === "paused" ? <Play size={14} /> : <Pause size={14} />}
          </button>
        )}
        {!terminal && (
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg text-text-muted hover:text-danger hover:bg-surface-elevated transition-colors"
            aria-label="Cancel"
          >
            <X size={14} />
          </button>
        )}
        {terminal && (
          <button
            onClick={onDismiss}
            className="p-1.5 rounded-lg text-text-faint hover:text-text hover:bg-surface-elevated transition-colors"
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        )}
      </div>
    </motion.div>
  );
}
