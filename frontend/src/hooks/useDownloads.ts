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

export function useDownloads() {
  const [jobs, setJobs] = useState<Record<string, DownloadJob>>({});
  const [logs, setLogs] = useState<LogLine[]>([]);
  const jobsRef = useRef(jobs);
  jobsRef.current = jobs;
  const { settings } = useSettings();
  // "Убирать из очереди после загрузки" раньше сохранялось в настройки и не влияло
  // ни на что: карточка всегда висела фиксированные 8 секунд.
  const removeAfterRef = useRef(false);
  removeAfterRef.current = settings?.remove_after_download ?? false;

  const handleEvent = useCallback((event: WsEvent) => {
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
          setTimeout(() => {
            setJobs((prev) => {
              if (!prev[id] || prev[id].status !== "completed") return prev;
              const next = { ...prev };
              delete next[id];
              return next;
            });
          }, removeAfterRef.current ? 400 : 8000);
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
      case "finished":
        break;
    }
  }, []);

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
          if (!next[q.id]) {
            next[q.id] = {
              id: q.id,
              url: q.url,
              title: q.title,
              status: q.status as DownloadJob["status"],
              progress: 0,
              speed: "",
            };
          }
        }
        return next;
      });
    } catch {
      // бэкенд ещё не поднялся (холодный старт) или временно недоступен —
      // следующая попытка WS-переподключения вызовет sync заново
    }
  }, []);

  useWsEvents(handleEvent, syncQueue);

  const addToQueue = useCallback(async (req: QueueItemRequest) => {
    const result = await api.addToQueue(req);
    setJobs((prev) => ({
      ...prev,
      [result.id]: {
        id: result.id,
        url: result.url,
        title: result.title,
        status: "queued",
        progress: 0,
        speed: "",
      },
    }));
    return result.id;
  }, []);

  const removeJob = useCallback((id: string) => {
    setJobs((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const pause = useCallback((id: string) => api.pauseItem(id), []);
  const resume = useCallback((id: string) => api.resumeItem(id), []);
  const cancel = useCallback(
    async (id: string) => {
      await api.cancelItem(id);
      removeJob(id);
    },
    [removeJob]
  );

  return {
    jobs: Object.values(jobs).sort((a, b) => (a.id > b.id ? 1 : -1)),
    logs,
    addToQueue,
    pause,
    resume,
    cancel,
    dismiss: removeJob,
  };
}
