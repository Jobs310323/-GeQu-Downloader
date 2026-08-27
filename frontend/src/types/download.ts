export type DownloadStatus =
  | "queued"
  | "analyzing"
  | "resolving"
  | "starting"
  | "downloading"
  | "merging"
  | "converting"
  | "paused"
  | "reconnecting"
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

export type LinkType = "video" | "playlist" | "channel" | "short" | "invalid";

export interface VideoInfo {
  is_playlist: boolean;
  link_type?: LinkType;
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

/** "original" = не запускать перекодировку вообще: поток остаётся таким, как его отдал YouTube. */
export const AUDIO_FORMAT_OPTIONS = ["mp3", "m4a", "opus", "vorbis", "flac", "wav", "aac", "alac", "original"] as const;
export const AUDIO_BITRATE_OPTIONS = ["96", "128", "192", "256", "320"] as const;
export const VIDEO_CODEC_OPTIONS = ["any", "h264", "vp9", "av1"] as const;
export const AUDIO_CODEC_OPTIONS = ["any", "aac", "opus"] as const;
export const OUTPUT_CONTAINER_OPTIONS = ["mp4", "mkv", "webm", "mov"] as const;
/** Битрейты без потерь бессмысленны — у этих форматов его просто нет. */
export const LOSSLESS_AUDIO_FORMATS = ["flac", "wav", "alac", "original"];
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
  /** Позиция в очереди бэкенда; нужна, чтобы кнопки «вверх/вниз» не врали. */
  position?: number;
  error?: { code: ErrorCode; message: string };
}

export interface QueueRow {
  id: string;
  url: string;
  title: string;
  status: DownloadStatus;
  position: number;
  quality?: string;
  audio_only?: boolean;
  is_playlist?: boolean;
  neuro_dub_ru?: boolean;
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

export interface PlaylistEntry {
  index: number;
  id: string;
  title: string;
  duration: number | null;
  uploader: string;
  url: string;
  thumbnail: string | null;
}

export interface PlaylistData {
  title: string;
  uploader: string;
  webpage_url: string;
  entries: PlaylistEntry[];
  entries_count: number;
  truncated: boolean;
}

export type MediaJobKind =
  | "remux"
  | "trim"
  | "replace_audio"
  | "extract_audio"
  | "convert"
  | "gif"
  | "thumbnail";

export interface MediaJob {
  id: string;
  kind: MediaJobKind;
  source: string;
  source_name: string;
  params: Record<string, unknown>;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  output: string;
  output_name: string;
  size: number;
  error: string;
  /** null пока операция не спланирована; дальше — честный ответ, теряется ли качество. */
  lossless: boolean | null;
  notes: string[];
  created_at: number;
  finished_at: number;
}

export interface MediaJobRequest {
  kind: MediaJobKind;
  source: string;
  container?: string;
  output_folder?: string;
  start?: number;
  end?: number;
  lossless?: boolean;
  audio_source?: string;
  keep_original_audio?: boolean;
  language?: string;
  bitrate?: number;
  stream_index?: number;
  video_codec?: string;
  audio_codec?: string;
  quality?: number;
  video_bitrate?: number;
  audio_bitrate?: number;
  height?: number;
  fps?: number;
  duration?: number;
  width?: number;
  at?: number;
}

export interface MediaStreamInfo {
  index: number;
  kind: "video" | "audio" | "subtitle";
  codec: string;
  language: string;
  title: string;
  width: number;
  height: number;
  fps: number;
  channels: number;
  sample_rate: number;
  bitrate: number;
  is_default: boolean;
}

export interface MediaProbe {
  path: string;
  filename: string;
  container: string;
  duration: number;
  size: number;
  bitrate: number;
  streams: MediaStreamInfo[];
}

export interface MediaContainer {
  ext: string;
  label: string;
  kind: "video" | "audio" | "image";
  video: string[];
  audio: string[];
  default_video: string;
  default_audio: string;
}

export interface MediaCapabilities {
  ffmpeg: boolean;
  ffmpeg_path: string;
  ffprobe: boolean;
  containers: MediaContainer[];
  video_codecs: { id: string; label: string; encoder: string | null }[];
  audio_codecs: { id: string; label: string; encoder: string | null }[];
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
  default_video_codec: string;
  default_audio_codec: string;
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
  video_encoders?: string[];
  audio_encoders?: string[];
}

export type WsEvent =
  | { type: "progress"; id: string; percent: number; speed: string }
  | { type: "status"; id: string; status: DownloadStatus }
  | { type: "log"; level: "info" | "success" | "warning" | "error"; text: string }
  | { type: "error"; id: string; code: ErrorCode; message: string }
  | { type: "finished"; id: string; meta: HistoryEntry }
  | { type: "media"; job: MediaJob };
