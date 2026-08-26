import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { LogLine } from "../../hooks/useDownloads";

const AUTO_DISMISS_MS = 6000;

const ICONS = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertTriangle,
  info: Info,
};

const COLORS = {
  success: "text-success border-success/30",
  warning: "text-warning border-warning/30",
  error: "text-danger border-danger/30",
  info: "text-text-muted border-border",
};

export function ToastStack({ toasts }: { toasts: LogLine[] }) {
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  useEffect(() => {
    const timers = toasts
      .filter((t) => !dismissed.has(t.id))
      .map((t) => setTimeout(() => setDismissed((prev) => new Set(prev).add(t.id)), AUTO_DISMISS_MS));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toasts]);

  const visible = toasts.filter((t) => !dismissed.has(t.id));

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80">
      <AnimatePresence initial={false}>
        {visible.map((t) => {
          const Icon = ICONS[t.level];
          return (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 12, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.2 }}
              className={`glass-elevated rounded-xl px-3.5 py-2.5 flex items-start gap-2.5 border ${COLORS[t.level]}`}
            >
              <Icon size={16} className="mt-0.5 shrink-0" />
              <p className="text-sm text-text leading-snug flex-1">{t.text}</p>
              <button
                onClick={() => setDismissed((prev) => new Set(prev).add(t.id))}
                className="text-text-faint hover:text-text transition-colors shrink-0"
                aria-label="Dismiss"
              >
                <X size={14} />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
