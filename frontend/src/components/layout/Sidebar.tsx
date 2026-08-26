import { Download, History, Plus, Settings as SettingsIcon } from "lucide-react";
import { APP_NAME } from "../../config/app";
import { useT } from "../../i18n/translations";

export type Page = "home" | "history" | "settings";

export function Sidebar({
  page,
  onNavigate,
  activeCount,
}: {
  page: Page;
  onNavigate: (p: Page) => void;
  activeCount: number;
}) {
  const t = useT();
  const NAV: { id: Page; label: string; icon: typeof Download }[] = [
    { id: "home", label: t("nav.newDownload"), icon: Plus },
    { id: "history", label: t("nav.history"), icon: History },
  ];
  return (
    <aside className="w-56 shrink-0 h-full glass border-r border-border flex flex-col p-3">
      <div className="flex items-center gap-2 px-2 py-3">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center">
          <Download size={15} className="text-background" strokeWidth={2.5} />
        </div>
        <span className="font-semibold text-text tracking-tight">{APP_NAME}</span>
      </div>

      <nav className="flex flex-col gap-1 mt-4">
        {NAV.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => onNavigate(id)}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
              page === id
                ? "bg-surface-elevated text-text"
                : "text-text-muted hover:text-text hover:bg-surface"
            }`}
          >
            <Icon size={16} />
            {label}
            {id === "home" && activeCount > 0 && (
              <span className="ml-auto text-xs text-primary font-mono">{activeCount}</span>
            )}
          </button>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-1">
        <button
          onClick={() => onNavigate("settings")}
          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
            page === "settings"
              ? "bg-surface-elevated text-text"
              : "text-text-muted hover:text-text hover:bg-surface"
          }`}
        >
          <SettingsIcon size={16} />
          {t("nav.settings")}
        </button>
        <div className="px-3 pt-2 text-xs text-text-faint font-mono">v2.0.0</div>
      </div>
    </aside>
  );
}
