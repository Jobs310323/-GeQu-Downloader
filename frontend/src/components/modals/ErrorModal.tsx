import { motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import type { ErrorCode } from "../../types/download";

const ERROR_COPY: Record<ErrorCode, { title: string; body: string }> = {
  FORMAT_UNAVAILABLE: {
    title: "Couldn't use the selected format",
    body: "The selected quality isn't available for this video. NeoLoader already tried the closest compatible alternatives.",
  },
  NETWORK_ERROR: {
    title: "Connection problem",
    body: "Couldn't reach the video. NeoLoader will keep retrying automatically once your connection is back.",
  },
  VIDEO_UNAVAILABLE: {
    title: "Video unavailable",
    body: "This video was removed, made private, or never existed.",
  },
  AGE_RESTRICTED: {
    title: "Age-restricted video",
    body: "This video requires sign-in to confirm age and can't be downloaded without authentication.",
  },
  GEO_RESTRICTED: {
    title: "Not available in your region",
    body: "YouTube is blocking this video for your location.",
  },
  DISK_FULL: {
    title: "Not enough disk space",
    body: "Free up space or choose a different download folder in Settings.",
  },
  INVALID_URL: {
    title: "That link doesn't look right",
    body: "Paste a valid YouTube or Rutube video/playlist URL.",
  },
  NO_TRANSCRIPT: {
    title: "No subtitles for this video",
    body: "Summaries are built from subtitles, and this video has none.",
  },
  SUMMARY_FAILED: {
    title: "Couldn't build the summary",
    body: "Reading the subtitles or summarizing them failed. Check the details below.",
  },
  UNKNOWN_ERROR: {
    title: "Couldn't complete the download",
    body: "Something unexpected happened.",
  },
};

export function ErrorModal({
  code,
  message,
  onClose,
}: {
  code: ErrorCode;
  message: string;
  onClose: () => void;
}) {
  const copy = ERROR_COPY[code] ?? ERROR_COPY.UNKNOWN_ERROR;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.18 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-elevated rounded-2xl p-5 w-[420px] max-w-[90vw]"
      >
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-full bg-danger/15 flex items-center justify-center shrink-0">
            <AlertTriangle size={16} className="text-danger" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-text">{copy.title}</h3>
            <p className="text-sm text-text-muted mt-1">{copy.body}</p>

            <details className="mt-3">
              <summary className="text-xs text-text-faint font-mono cursor-pointer select-none">
                Technical details
              </summary>
              <p className="text-xs text-text-faint font-mono mt-1.5 break-words">
                {code}: {message}
              </p>
            </details>
          </div>
          <button onClick={onClose} className="text-text-faint hover:text-text shrink-0">
            <X size={16} />
          </button>
        </div>
      </motion.div>
    </div>
  );
}
