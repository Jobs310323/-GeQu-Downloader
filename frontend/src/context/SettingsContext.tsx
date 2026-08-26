import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../services/api";
import { API_BASE } from "../config/app";
import type { Settings } from "../types/download";

interface SettingsCtxValue {
  settings: Settings | null;
  /** false, пока бэкенд не ответил ни разу или перестал отвечать. */
  online: boolean;
  patch: (p: Partial<Settings>) => Promise<Settings>;
  /** Перечитывает настройки с бэкенда — нужен там, где значение меняет НЕ фронтенд
   *  (например путь к папке, выбранный в нативном диалоге). */
  reload: () => Promise<void>;
}

const SettingsCtx = createContext<SettingsCtxValue | null>(null);

function applyTheme(theme: string | undefined) {
  document.documentElement.setAttribute("data-theme", theme === "light" ? "light" : "dark");
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [online, setOnline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    // Один неудачный fetch на старте (бэкенд ещё не поднялся — см. main.py про холодный
    // старт EXE) раньше блокировал страницу настроек навсегда: settings оставался null,
    // а SettingsPage рендерит пустоту при !settings и больше никогда не перезапрашивает.
    // Теперь это не разовая загрузка, а постоянный health-poll: пока бэкенд лежит,
    // интерфейс это ЗНАЕТ и говорит вслух, а как только поднялся — сам оживает.
    // console.* из QWebEngineView перехватывается и пишется в app.log
    // (см. ui/web_window.py::_LoggingPage). В собранном приложении devtools нет,
    // и это единственный способ увидеть постфактум, достучался ли интерфейс до
    // бэкенда вообще — раньше такое состояние приходилось угадывать.
    let announced = "";
    function announce(state: string, detail = "") {
      if (announced === state) return;
      announced = state;
      const line = `[neoloader] backend ${state} at ${API_BASE}${detail ? " :: " + detail : ""}`;
      if (state === "online") console.log(line);
      else console.warn(line);
    }

    async function load(attempt = 0): Promise<void> {
      try {
        const s = await api.getSettings();
        if (cancelled) return;
        setSettings(s);
        setOnline(true);
        applyTheme(s.theme);
        announce("online");
        // Дальше опрашиваем редко — только чтобы заметить, если бэкенд умрёт.
        timer = setTimeout(() => load(0), 10000);
      } catch (e) {
        if (cancelled) return;
        setOnline(false);
        announce("unreachable", e instanceof Error ? e.message : String(e));
        const delay = Math.min(500 * 2 ** attempt, 5000);
        timer = setTimeout(() => load(attempt + 1), delay);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  const patch = useCallback(async (p: Partial<Settings>) => {
    const updated = await api.updateSettings(p);
    setSettings(updated);
    setOnline(true);
    if (p.theme) applyTheme(updated.theme);
    return updated;
  }, []);

  const reload = useCallback(async () => {
    const s = await api.getSettings();
    setSettings(s);
    setOnline(true);
    applyTheme(s.theme);
  }, []);

  return (
    <SettingsCtx.Provider value={{ settings, online, patch, reload }}>{children}</SettingsCtx.Provider>
  );
}

export function useSettings() {
  const ctx = useContext(SettingsCtx);
  if (!ctx) throw new Error("useSettings must be used within SettingsProvider");
  return ctx;
}
