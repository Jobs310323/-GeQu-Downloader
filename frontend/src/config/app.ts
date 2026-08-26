export const APP_NAME = "NeoLoader";

/**
 * Адрес бэкенда.
 *
 * В собранном приложении страницу отдаёт сам uvicorn (см. api/server.py — статика
 * смонтирована на "/"), поэтому API живёт на ТОМ ЖЕ origin, что и страница. Это не
 * оптимизация, а обход реального ограничения: страница, открытая как file://, в
 * QtWebEngine не может делать fetch на http:// (LocalContentCanAccessRemoteUrls
 * выключен по умолчанию) — из браузера всё работало, а в окне приложения каждый
 * запрос молча падал, и интерфейс сообщал «фоновая служба не запущена» при живой службе.
 *
 * Порядок разрешения:
 *   1. `?api=<port>` — явное указание (dev-сервер, аварийный file://-режим);
 *   2. режим разработки (vite на 5173/5199) — бэкенд отдельно, на 8756;
 *   3. продакшен-сборка по http(s) — тот же origin, что и страница;
 *   4. иначе (file:// без параметра) — 127.0.0.1:8756 как последняя попытка.
 */
function resolveApiBase(): string {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get("api");
    const port = Number(fromQuery);
    if (Number.isInteger(port) && port > 0 && port < 65536) return `http://127.0.0.1:${port}`;
  } catch {
    // location недоступен (тесты) — идём дальше по цепочке
  }
  if (import.meta.env.DEV) return "http://127.0.0.1:8756";
  const protocol = typeof window !== "undefined" ? window.location.protocol : "";
  if (protocol === "http:" || protocol === "https:") return window.location.origin;
  return "http://127.0.0.1:8756";
}

export const API_BASE = resolveApiBase();
export const WS_URL = `${API_BASE.replace(/^http/, "ws")}/ws`;
