import { useCallback, useEffect, useState } from "react";
import { api } from "../services/api";
import { useWsEvents } from "../services/ws";
import type { MediaJob, MediaJobRequest, WsEvent } from "../types/download";

/**
 * Состояние очереди локальных ffmpeg-операций.
 *
 * Живёт на уровне App, а не страницы конвертера: перекодирование часового видео идёт
 * минутами, и пользователь всё это время не обязан сидеть на одной вкладке. Если бы
 * состояние умирало вместе со страницей, уход в «Историю» и обратно показывал бы
 * пустой список при работающем в фоне ffmpeg.
 */
export function useMediaJobs() {
  const [jobs, setJobs] = useState<Record<string, MediaJob>>({});

  const sync = useCallback(async () => {
    try {
      const list = await api.mediaJobs();
      setJobs(Object.fromEntries(list.map((j) => [j.id, j])));
    } catch {
      // бэкенд ещё не поднялся — следующее подключение WS позовёт sync снова
    }
  }, []);

  const handleEvent = useCallback((event: WsEvent) => {
    if (event.type !== "media") return;
    setJobs((prev) => ({ ...prev, [event.job.id]: event.job }));
  }, []);

  useWsEvents(handleEvent, sync);
  useEffect(() => {
    void sync();
  }, [sync]);

  const submit = useCallback(async (req: MediaJobRequest) => {
    const job = await api.mediaSubmit(req);
    setJobs((prev) => ({ ...prev, [job.id]: job }));
    return job;
  }, []);

  const cancel = useCallback(async (id: string) => {
    await api.mediaCancel(id);
  }, []);

  const clearFinished = useCallback(async () => {
    await api.mediaClear();
    await sync();
  }, [sync]);

  const list = Object.values(jobs).sort((a, b) => b.created_at - a.created_at);
  const activeCount = list.filter((j) => j.status === "queued" || j.status === "running").length;

  return { jobs: list, activeCount, submit, cancel, clearFinished, refresh: sync };
}
