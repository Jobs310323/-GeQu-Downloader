import { AnimatePresence } from "framer-motion";
import { Inbox, Pause, Play, Trash2 } from "lucide-react";
import type { DownloadJob } from "../../types/download";
import { useT } from "../../i18n/translations";
import { DownloadCard } from "./DownloadCard";

export function DownloadQueue({
  jobs,
  onPause,
  onResume,
  onCancel,
  onDismiss,
  onMove,
  onPauseAll,
  onResumeAll,
  onClear,
}: {
  jobs: DownloadJob[];
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onDismiss: (id: string) => void;
  onMove?: (id: string, delta: number) => void;
  onPauseAll?: () => void;
  onResumeAll?: () => void;
  onClear?: () => void;
}) {
  const t = useT();

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-text-faint">
        <Inbox size={22} />
        <p className="text-sm">{t("download.empty.title")}</p>
        <p className="text-xs">{t("download.empty.subtitle")}</p>
      </div>
    );
  }

  const pending = jobs.filter((j) => j.status === "queued" || j.status === "paused");
  const anyActive = jobs.some((j) => !["completed", "failed", "cancelled", "paused"].includes(j.status));

  return (
    <div className="flex flex-col gap-2">
      {jobs.length > 1 && (
        <div className="flex items-center gap-2 pb-1">
          {anyActive && onPauseAll && (
            <QueueAction icon={<Pause size={12} />} label={t("queue.pauseAll")} onClick={onPauseAll} />
          )}
          {pending.length > 0 && onResumeAll && (
            <QueueAction icon={<Play size={12} />} label={t("queue.resumeAll")} onClick={onResumeAll} />
          )}
          {pending.length > 0 && onClear && (
            <QueueAction
              icon={<Trash2 size={12} />}
              label={`${t("queue.clearPending")} (${pending.length})`}
              onClick={onClear}
              danger
            />
          )}
        </div>
      )}

      <AnimatePresence initial={false}>
        {jobs.map((job, index) => (
          <DownloadCard
            key={job.id}
            job={job}
            onPause={() => onPause(job.id)}
            onResume={() => onResume(job.id)}
            onCancel={() => onCancel(job.id)}
            onDismiss={() => onDismiss(job.id)}
            onMove={onMove ? (delta) => onMove(job.id, delta) : undefined}
            canMoveUp={index > 0}
            canMoveDown={index < jobs.length - 1}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

function QueueAction({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-surface hover:bg-surface-elevated transition-colors ${
        danger ? "text-text-faint hover:text-danger" : "text-text-muted hover:text-text"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
