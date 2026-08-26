import { motion } from "framer-motion";
import { FileText, ListVideo } from "lucide-react";
import type { VideoInfo } from "../../types/download";
import { useT } from "../../i18n/translations";

function formatDuration(seconds: number | null) {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function VideoPreviewSkeleton() {
  return (
    <div className="glass rounded-2xl p-4 flex gap-4 animate-pulse">
      <div className="w-40 h-24 rounded-lg bg-surface-elevated shrink-0" />
      <div className="flex-1 flex flex-col gap-2 py-1">
        <div className="h-4 w-3/4 rounded bg-surface-elevated" />
        <div className="h-3 w-1/3 rounded bg-surface-elevated" />
        <div className="h-3 w-1/4 rounded bg-surface-elevated" />
      </div>
    </div>
  );
}

export function VideoPreview({
  info,
  onSummarize,
}: {
  info: VideoInfo;
  onSummarize?: () => void;
}) {
  const t = useT();
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="glass rounded-2xl p-4 flex gap-4"
    >
      <div className="w-40 h-24 rounded-lg bg-surface-elevated shrink-0 overflow-hidden flex items-center justify-center">
        {info.thumbnail ? (
          <img src={info.thumbnail} alt="" className="w-full h-full object-cover" />
        ) : (
          <ListVideo size={24} className="text-text-faint" />
        )}
      </div>
      <div className="flex-1 min-w-0 flex flex-col justify-center gap-1">
        <p className="font-medium text-text truncate">{info.title}</p>
        {info.is_playlist ? (
          <p className="text-sm text-text-muted">Playlist · {info.entries_count} videos</p>
        ) : (
          <p className="text-sm text-text-muted">
            {info.uploader}
            {info.uploader && info.duration ? " · " : ""}
            {formatDuration(info.duration)}
          </p>
        )}
        {info.has_ru_dub && (
          <span className="text-xs text-secondary font-mono w-fit">
            {info.ru_is_original ? "RU (original audio)" : "RU audio track available"}
          </span>
        )}
      </div>
      {!info.is_playlist && info.has_transcript !== false && onSummarize && (
        <button
          onClick={onSummarize}
          className="self-center flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-3 py-2 rounded-lg transition-colors shrink-0"
        >
          <FileText size={13} />
          {t("summary.button")}
        </button>
      )}
    </motion.div>
  );
}
