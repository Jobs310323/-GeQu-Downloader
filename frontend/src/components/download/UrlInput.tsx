import { motion } from "framer-motion";
import { Clipboard, Link2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../../i18n/translations";

export function UrlInput({
  value,
  onChange,
  onSubmit,
  analyzing,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  analyzing: boolean;
}) {
  const [dragOver, setDragOver] = useState(false);
  const t = useT();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onSubmit();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function handlePaste() {
    try {
      const text = await navigator.clipboard.readText();
      onChange(text.trim());
    } catch {
      // доступ к буферу обмена может быть запрещён — пользователь вставит вручную (Ctrl+V)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const text = e.dataTransfer.getData("text/plain");
        if (text) onChange(text.trim());
      }}
      className={`glass rounded-2xl flex items-center gap-2 px-4 py-3.5 transition-colors ${
        dragOver ? "border-primary/60 bg-primary/5" : ""
      }`}
    >
      <Link2 size={18} className="text-text-faint shrink-0" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onSubmit()}
        placeholder={dragOver ? t("url.placeholderDrop") : t("url.placeholder")}
        className="flex-1 bg-transparent outline-none text-[15px] placeholder:text-text-faint"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          className="text-text-faint hover:text-text transition-colors p-1"
          aria-label="Clear"
        >
          <X size={16} />
        </button>
      )}
      <button
        onClick={handlePaste}
        className="flex items-center gap-1.5 text-sm text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-3 py-1.5 rounded-lg transition-colors shrink-0"
      >
        <Clipboard size={14} />
        {t("url.paste")}
      </button>
      {analyzing && (
        <span className="text-xs text-primary font-mono animate-pulse shrink-0">{t("url.analyzing")}</span>
      )}
    </motion.div>
  );
}
