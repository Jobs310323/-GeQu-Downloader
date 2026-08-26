export type DownloadStatus =
  | "queued"
  | "analyzing"
  | "resolving"
  | "starting"
  | "downloading"
  | "merging"
  | "converting"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type ErrorCode =
  | "FORMAT_UNAVAILABLE"
  | "NETWORK_ERROR"
  | "VIDEO_UNAVAILABLE"
  | "AGE_RESTRICTED"
  | "GEO_RESTRICTED"
  | "DISK_FULL"
  | "INVALID_URL"
  | "NO_TRANSCRIPT"
  | "SUMMARY_FAILED"
  | "UNKNOWN_ERROR";

export interface VideoInfo {
  is_playlist: boolean;
  title: string;
  uploader: string;
  thumbnail: string | null;
  duration: number | null;
  entries_count: number;
  webpage_url: string;
  has_ru_dub: boolean;
  ru_is_original?: boolean;
  audio_languages?: string[];
  has_transcript?: boolean;
}

export interface VideoSummary {
  summary: string;
  bullets: string[];
  engine: string;
  transcript_language?: string;
  transcript_chars?: number;
  fallback_reason?: string;
}

export const QUALITY_OPTIONS = ["4K", "2K", "1080p", "720p", "480p", "360p"] as const;
export type Quality = (typeof QUALITY_OPTIONS)[number];

export const AUDIO_FORMAT_OPTIONS = ["mp3", "m4a", "original"] as const;
export const AUDIO_BITRATE_OPTIONS = ["128", "192", "320"] as const;
export const VIDEO_CODEC_OPTIONS = ["any", "h264", "vp9", "av1"] as const;
export const AUDIO_CODEC_OPTIONS = ["any", "aac", "opus"] as const;
export const OUTPUT_CONTAINER_OPTIONS = ["mp4", "mkv"] as const;
export const SUMMARY_MODEL_OPTIONS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"] as const;
export const COOKIES_BROWSER_OPTIONS = [
  "none",
  "chrome",
  "firefox",
  "edge",
  "brave",
  "opera",
  "vivaldi",
] as const;

export interface QueueItemRequest {
  url: string;
  title?: string;
  quality?: Quality;
  audio_only?: boolean;
  audio_format?: string;
  audio_bitrate?: string;
  subtitles?: boolean;
  subtitle_langs?: string[];
  neuro_dub_ru?: boolean;
  video_codec?: string;
  audio_codec?: string;
  output_container?: string;
  output_folder?: string;
  is_playlist?: boolean;
  create_playlist_folder?: boolean;
  remove_after_download?: boolean;
}

export interface DownloadJob {
  id: string;
  url: string;
  title: string;
  thumbnail?: string | null;
  status: DownloadStatus;
  progress: number;
  speed: string;
  error?: { code: ErrorCode; message: string };
}

export interface HistoryEntry {
  url: string;
  title: string;
  path?: string;
  size?: number;
  finished_at?: number;
  audio_only?: boolean;
  quality?: string;
  /** null — русская дорожка не запрашивалась; false — запрошена, но не получена. */
  ru_dub?: boolean | null;
}

export interface Settings {
  theme: "dark" | "light";
  language: "ru" | "en";
  download_folder: string;
  auto_update_ytdlp: boolean;
  default_quality: string;
  audio_only: boolean;
  audio_format: string;
  audio_bitrate: string;
  create_playlist_folder: boolean;
  remove_after_download: boolean;
  concurrent_downloads: number;
  proxy: string;
  cookies_from_browser: string;
  filename_template: string;
  output_container: string;
  /** Сам ключ наружу не отдаётся — приходит пустой строкой; факт наличия в *_set. */
  summary_api_key: string;
  summary_api_key_set?: boolean;
  summary_model: string;
  history: HistoryEntry[];
}

export interface Diagnostics {
  ytdlp_version: string;
  ffmpeg_installed: boolean;
  frozen?: boolean;
  summary_api_key_set?: boolean;
}

export type WsEvent =
  | { type: "progress"; id: string; percent: number; speed: string }
  | { type: "status"; id: string; status: DownloadStatus }
  | { type: "log"; level: "info" | "success" | "warning" | "error"; text: string }
  | { type: "error"; id: string; code: ErrorCode; message: string }
  | { type: "finished"; id: string; meta: HistoryEntry };
