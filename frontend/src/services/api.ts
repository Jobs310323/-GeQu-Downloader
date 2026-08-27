import { API_BASE } from "../config/app";
import type {
  Diagnostics,
  HistoryEntry,
  MediaCapabilities,
  MediaJob,
  MediaJobRequest,
  MediaProbe,
  PlaylistData,
  QueueItemRequest,
  QueueRow,
  Settings,
  VideoInfo,
  VideoSummary,
} from "../types/download";

export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    if (detail && typeof detail === "object") {
      throw new ApiError(detail.code ?? "UNKNOWN_ERROR", detail.message ?? res.statusText);
    }
    throw new ApiError("UNKNOWN_ERROR", detail ?? res.statusText);
  }
  return res.json();
}

export const api = {
  analyze: (url: string, signal?: AbortSignal) =>
    request<VideoInfo>("/api/analyze", { method: "POST", body: JSON.stringify({ url }), signal }),

  summarize: (url: string, title: string, duration: number | null, signal?: AbortSignal) =>
    request<VideoSummary>("/api/summary", {
      method: "POST",
      body: JSON.stringify({ url, title, duration }),
      signal,
    }),

  playlist: (url: string, limit = 500, signal?: AbortSignal) =>
    request<PlaylistData>("/api/playlist", {
      method: "POST",
      body: JSON.stringify({ url, limit }),
      signal,
    }),

  addToQueue: (item: QueueItemRequest) =>
    request<{ id: string; url: string; title: string; status: string }>("/api/queue", {
      method: "POST",
      body: JSON.stringify(item),
    }),

  // Один запрос на весь пакет: 200 отдельных POST'ов из React — это 200 круговых
  // задержек и 200 перерисовок очереди подряд.
  addBatch: (items: QueueItemRequest[]) =>
    request<{ id: string; url: string; title: string; status: string }[]>("/api/queue/batch", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  getQueue: () => request<QueueRow[]>("/api/queue"),

  pauseItem: (id: string) => request(`/api/queue/${id}/pause`, { method: "POST" }),
  resumeItem: (id: string) => request(`/api/queue/${id}/resume`, { method: "POST" }),
  cancelItem: (id: string) => request(`/api/queue/${id}/cancel`, { method: "POST" }),
  removeItem: (id: string) => request(`/api/queue/${id}`, { method: "DELETE" }),
  moveItem: (id: string, delta: number) =>
    request<{ ok: boolean; queue: QueueRow[] }>(`/api/queue/${id}/move`, {
      method: "POST",
      body: JSON.stringify({ delta }),
    }),
  pauseAll: () => request<{ affected: number }>("/api/queue/pause_all", { method: "POST" }),
  resumeAll: () => request<{ affected: number }>("/api/queue/resume_all", { method: "POST" }),
  clearQueue: () => request<{ removed: number }>("/api/queue", { method: "DELETE" }),

  getHistory: () => request<HistoryEntry[]>("/api/history"),
  clearHistory: () => request("/api/history", { method: "DELETE" }),

  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (patch: Partial<Settings>) =>
    request<Settings>("/api/settings", { method: "POST", body: JSON.stringify(patch) }),

  chooseFolder: (start?: string) =>
    request<{ ok: boolean; download_folder: string }>("/api/settings/folder", {
      method: "POST",
      body: JSON.stringify({ start: start ?? "" }),
    }),

  reveal: (path?: string) =>
    request<{ ok: boolean }>("/api/reveal", {
      method: "POST",
      body: JSON.stringify({ path: path ?? "" }),
    }),

  mediaCapabilities: () => request<MediaCapabilities>("/api/media/capabilities"),
  mediaPick: (opts?: { start?: string; multiple?: boolean; audio_only?: boolean; title?: string }) =>
    request<{ paths: string[] }>("/api/media/pick", {
      method: "POST",
      body: JSON.stringify({
        start: opts?.start ?? "",
        multiple: opts?.multiple ?? true,
        audio_only: opts?.audio_only ?? false,
        title: opts?.title ?? "",
      }),
    }),
  mediaProbe: (path: string) =>
    request<MediaProbe>("/api/media/probe", { method: "POST", body: JSON.stringify({ path }) }),
  mediaJobs: () => request<MediaJob[]>("/api/media/jobs"),
  mediaSubmit: (job: MediaJobRequest) =>
    request<MediaJob>("/api/media/jobs", { method: "POST", body: JSON.stringify(job) }),
  mediaCancel: (id: string) => request(`/api/media/jobs/${id}/cancel`, { method: "POST" }),
  mediaClear: () => request<{ removed: number }>("/api/media/jobs", { method: "DELETE" }),

  diagnostics: () => request<Diagnostics>("/api/diagnostics"),
  updateYtdlp: () =>
    request<{ ok: boolean; version: string; restart_required: boolean }>("/api/ytdlp/update", {
      method: "POST",
    }),
};
