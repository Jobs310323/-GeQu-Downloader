import { motion } from "framer-motion";
import { Download } from "lucide-react";
import { useT } from "../../i18n/translations";

export function DownloadButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  const t = useT();
  return (
    <motion.button
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center justify-center gap-2 rounded-xl py-3 font-medium text-background bg-gradient-to-r from-primary to-secondary disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
    >
      <Download size={17} />
      {t("download.button")}
      <kbd className="ml-1 text-xs opacity-60 font-mono">Ctrl+Enter</kbd>
    </motion.button>
  );
}
