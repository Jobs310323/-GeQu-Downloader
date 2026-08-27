import { useCallback, useRef, useState } from "react";
import { api } from "../services/api";
import { useSettings } from "../context/SettingsContext";
import { useWsEvents } from "../services/ws";
import type { DownloadJob, QueueItemRequest, WsEvent } from "../types/download";

export interface LogLine {
  id: number;
  level: "info" | "success" | "warning" | "error";
  text: string;
}

let logCounter = 0;
let seqCounter = 0;

/** Порядковый номер задачи в списке.
 *
 *  Раньше сортировка шла по job.id (uuid) — то есть порядок карточек был случайным
 *  и не совпадал ни с очередью на бэкенде, ни с порядком добавления. С кнопками
 *  «вверх/вниз» это стало прямой ложью: переставил задачу, а список не изменился.
 *  Теперь: активные и ожидающие идут в порядке очереди бэкенда, завершённые уходят
 *  вниз в порядке появления. */
function rank(job: DownloadJob & { seq: number }): number {
  if (["completed", "failed", "cancelled"].includes(job.status)) return 2e9 + job.seq;
  if (job.position === undefined) return 1e9 + job.seq;
  return job.position;
}

type StoredJob = DownloadJob & { seq: number };

export function useDownloads() {
  const [jobs, setJobs] = useState<Record<string, StoredJob>>({});
  const [logs, setLogs] = useState<LogLine[]>([]);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;
  const { settings } = useSettings();
  // "Убирать из очереди после загрузки" раньше сохранялось в настройки и не влияло
  // ни на что: карточка всегда висела фиксированные 8 секунд.
  const removeAfterRef = useRef(false);
  removeAfterRef.current = settings?.remove_after_download ?? false;

  // Событие о задаче, которой в локальном списке нет, означает одно: наш снимок
  // очереди устарел (задачу добавили из другого окна/браузера, или бэкенд
  // перезапустился, пока сокет висел открытым). Раньше такие события просто
  // игнорировались, и очередь молча показывала «нет активных загрузок» при живой
  // загрузке. Ресинк дебаунсится: пакет из 50 роликов иначе дал бы 50 запросов.
  const resyncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleResync = useCallback(() => {
    if (resyncTimer.current) return;
    resyncTimer.current = setTimeout(() => {
      resyncTimer.current = null;
      void syncQueueRef.current?.();
    }, 300);
  }, []);
  const syncQueueRef = useRef<(() => Promise<void>) | null>(null);

  const handleEvent = useCallback((event: WsEvent) => {
    if ((event.type === "status" || event.type === "progress") && !jobsRef.current[event.id]) {
      scheduleResync();
      return;
    }
    switch (event.type) {
      case "progress":
        setJobs((prev) =>
          prev[event.id]
            ? { ...prev, [event.id]: { ...prev[event.id], progress: event.percent, speed: event.speed } }
            : prev
        );
        break;
      case "status":
        setJobs((prev) =>
          prev[event.id] ? { ...prev, [event.id]: { ...prev[event.id], status: event.status } } : prev
        );
        if (event.status === "completed") {
          const id = event.id;
          setTimeout(
            () => {
              setJobs((prev) => {
                if (!prev[id] || prev[id].status !== "completed") return prev;
                const next = { ...prev };
                delete next[id];
                return next;
              });
            },
            removeAfterRef.current ? 400 : 8000
          );
        }
        break;
      case "error":
        setJobs((prev) =>
          prev[event.id]
            ? { ...prev, [event.id]: { ...prev[event.id], error: { code: event.code, message: event.message } } }
            : prev
        );
        break;
      case "log":
        setLogs((prev) => [...prev.slice(-199), { id: logCounter++, level: event.level, text: event.text }]);
        break;
      default:
        break;
    }
  }, [scheduleResync]);

  // При монтировании (и при каждом переподключении WS — см. useWsEvents) подтягиваем
  // реальное состояние очереди с бэкенда: без этого перезагрузка страницы/окна не видела
  // уже идущие загрузки (jobs жил только в памяти компонента, а WS игнорирует события
  // для неизвестных id). Бэкенд теперь хранит в очереди только активные/ожидающие задачи
  // (завершённые убираются сразу — см. DownloadManager._run_item), так что всё пришедшее
  // отсюда безопасно показывать как активное.
  const syncQueue = useCallback(async () => {
    try {
      const queue = await api.getQueue();
      setJobs((prev) => {
        const next = { ...prev };
        for (const q of queue) {
          next[q.id] = next[q.id]
            ? { ...next[q.id], status: q.status, position: q.position }
            : {
                id: q.id,
                url: q.url,
                title: q.title,
                status: q.status,
                position: q.position,
                progress: 0,
                speed: "",
                seq: seqCounter++,
              };
        }
        return next;
      });
    } catch {
      // бэкенд ещё не поднялся (холодный старт) или временно недоступен —
      // следующая попытка WS-переподключения вызовет sync заново
    }
  }, []);
  syncQueueRef.current = syncQueue;

  useWsEvents(handleEvent, syncQueue);

  const register = useCallback((rows: { id: string; url: string; title: string }[]) => {
    setJobs((prev) => {
      const next = { ...prev };
      for (const r of rows) {
        next[r.id] = {
          id: r.id,
          url: r.url,
          title: r.title,
          status: "queued",
          progress: 0,
          speed: "",
          seq: seqCounter++,
        };
      }
      return next;
    });
  }, []);

  const addToQueue = useCallback(
    async (req: QueueItemRequest) => {
      const result = await api.addToQueue(req);
      register([result]);
      return result.id;
    },
    [register]
  );

  /** Пакетная постановка (плейлист/канал) — один запрос вместо N. */
  const addBatch = useCallback(
    async (items: QueueItemRequest[]) => {
      const rows = await api.addBatch(items);
      register(rows);
      return rows.map((r) => r.id);
    },
    [register]
  );

  const removeJob = useCallback((id: string) => {
    setJobs((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const pause = useCallback((id: string) => api.pauseItem(id).catch(() => undefined), []);
  const resume = useCallback((id: string) => api.resumeItem(id).catch(() => undefined), []);
  const cancel = useCallback(
    async (id: string) => {
      await api.cancelItem(id).catch(() => undefined);
      removeJob(id);
    },
    [removeJob]
  );

  const move = useCallback(
    async (id: string, delta: number) => {
      try {
        const result = await api.moveItem(id, delta);
        // Порядок берём из ответа бэкенда, а не пересчитываем локально: очередь могла
        // измениться между кликом и ответом (задача стартовала, другая завершилась).
        setJobs((prev) => {
          const next = { ...prev };
          for (const row of result.queue) {
            if (next[row.id]) next[row.id] = { ...next[row.id], position: row.position };
          }
          return next;
        });
      } catch {
        void syncQueue();
      }
    },
    [syncQueue]
  );

  const pauseAll = useCallback(async () => {
    await api.pauseAll().catch(() => undefined);
    await syncQueue();
  }, [syncQueue]);

  const resumeAll = useCallback(async () => {
    await api.resumeAll().catch(() => undefined);
    await syncQueue();
  }, [syncQueue]);

  const clearPending = useCallback(async () => {
    await api.clearQueue().catch(() => undefined);
    setJobs((prev) =>
      Object.fromEntries(
        Object.entries(prev).filter(([, j]) => j.status !== "queued" && j.status !== "paused")
      )
    );
    await syncQueue();
  }, [syncQueue]);

  return {
    jobs: Object.values(jobs).sort((a, b) => rank(a) - rank(b)) as DownloadJob[],
    logs,
    addToQueue,
    addBatch,
    pause,
    resume,
    cancel,
    move,
    pauseAll,
    resumeAll,
    clearPending,
    dismiss: removeJob,
  };
}
