import { AnimatePresence } from "framer-motion";
import { Inbox } from "lucide-react";
import type { DownloadJob } from "../../types/download";
import { useT } from "../../i18n/translations";
import { DownloadCard } from "./DownloadCard";

export function DownloadQueue({
  jobs,
  onPause,
  onResume,
  onCancel,
  onDismiss,
}: {
  jobs: DownloadJob[];
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onCancel: (id: string) => void;
  onDismiss: (id: string) => void;
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

  return (
    <div className="flex flex-col gap-2">
      <AnimatePresence initial={false}>
        {jobs.map((job) => (
          <DownloadCard
            key={job.id}
            job={job}
            onPause={() => onPause(job.id)}
            onResume={() => onResume(job.id)}
            onCancel={() => onCancel(job.id)}
            onDismiss={() => onDismiss(job.id)}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
