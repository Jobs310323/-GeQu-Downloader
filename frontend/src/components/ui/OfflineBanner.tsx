import { AlertTriangle, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useSettings } from "../../context/SettingsContext";
import { useT } from "../../i18n/translations";

/**
 * Явный индикатор «бэкенда нет».
 *
 * Без него отказ фоновой службы выглядел как «приложение просто сломалось»:
 * страница настроек рендерила пустоту (`if (!settings) return null`), кнопки
 * ничего не делали, а единственное сообщение появлялось только если вставить
 * ссылку. Теперь состояние названо своим именем и видно сразу.
 */
export function OfflineBanner() {
  const { online, reload } = useSettings();
  const [checking, setChecking] = useState(false);
  const t = useT();

  if (online) return null;

  async function retry() {
    setChecking(true);
    try {
      await reload();
    } catch {
      // остаёмся офлайн — фоновый опрос в SettingsContext продолжит попытки
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="flex items-start gap-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3">
      <AlertTriangle size={16} className="text-danger mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text">{t("app.offline.title")}</p>
        <p className="text-xs text-text-muted mt-0.5">{t("app.offline.body")}</p>
      </div>
      <button
        onClick={retry}
        disabled={checking}
        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1.5 rounded-lg transition-colors shrink-0 disabled:opacity-50"
      >
        <RefreshCw size={12} className={checking ? "animate-spin" : ""} />
        {t("app.offline.retry")}
      </button>
    </div>
  );
}
