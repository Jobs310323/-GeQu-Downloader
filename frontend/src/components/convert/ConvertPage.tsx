import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileVideo, Loader2, Music, Plus, Zap } from "lucide-react";
import { api, ApiError } from "../../services/api";
import { useT } from "../../i18n/translations";
import { MediaJobList } from "./MediaJobList";
import type {
  MediaCapabilities,
  MediaJob,
  MediaJobKind,
  MediaJobRequest,
  MediaProbe,
} from "../../types/download";

const TABS: { id: MediaJobKind; key: string; single: boolean }[] = [
  { id: "remux", key: "convert.tab.remux", single: false },
  { id: "trim", key: "convert.tab.trim", single: true },
  { id: "replace_audio", key: "convert.tab.replaceAudio", single: true },
  { id: "extract_audio", key: "convert.tab.extractAudio", single: false },
  { id: "convert", key: "convert.tab.convert", single: false },
  { id: "gif", key: "convert.tab.gif", single: true },
  { id: "thumbnail", key: "convert.tab.frame", single: true },
];

const AUDIO_BITRATES = [96, 128, 192, 256, 320];
const HEIGHTS = [0, 2160, 1440, 1080, 720, 480, 360];

/** "1:02:03", "2:15" и "135" — всё это одно и то же поле ввода времени. */
function parseTime(value: string): number {
  const parts = value.trim().split(":").map((p) => Number(p.replace(",", ".")));
  if (parts.some((p) => Number.isNaN(p))) return NaN;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

function formatSize(bytes: number): string {
  const mb = bytes / 1024 / 1024;
  return mb >= 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(1)} MB`;
}

export function ConvertPage({
  jobs,
  onSubmit,
  onCancel,
  onClear,
}: {
  jobs: MediaJob[];
  onSubmit: (req: MediaJobRequest) => Promise<MediaJob>;
  onCancel: (id: string) => void;
  onClear: () => void;
}) {
  const t = useT();
  const [caps, setCaps] = useState<MediaCapabilities | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [probe, setProbe] = useState<MediaProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const [tab, setTab] = useState<MediaJobKind>("remux");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Параметры операций
  const [container, setContainer] = useState("mp4");
  const [audioContainer, setAudioContainer] = useState("mp3");
  const [audioBitrate, setAudioBitrate] = useState(192);
  const [start, setStart] = useState("0:00");
  const [end, setEnd] = useState("");
  const [lossless, setLossless] = useState(true);
  const [audioSource, setAudioSource] = useState("");
  const [keepOriginal, setKeepOriginal] = useState(false);
  const [trackLanguage, setTrackLanguage] = useState("rus");
  const [videoCodec, setVideoCodec] = useState("copy");
  const [convAudioCodec, setConvAudioCodec] = useState("copy");
  const [quality, setQuality] = useState(75);
  const [height, setHeight] = useState(0);
  const [gifStart, setGifStart] = useState("0:00");
  const [gifDuration, setGifDuration] = useState(5);
  const [gifFps, setGifFps] = useState(12);
  const [gifWidth, setGifWidth] = useState(480);
  const [frameAt, setFrameAt] = useState("0:05");
  const [frameFormat, setFrameFormat] = useState("png");

  useEffect(() => {
    let cancelled = false;
    api
      .mediaCapabilities()
      .then((c) => !cancelled && setCaps(c))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const videoContainers = useMemo(
    () => (caps?.containers ?? []).filter((c) => c.kind === "video"),
    [caps]
  );
  const audioContainers = useMemo(
    () => (caps?.containers ?? []).filter((c) => c.kind === "audio"),
    [caps]
  );
  const imageContainers = useMemo(
    () => (caps?.containers ?? []).filter((c) => c.kind === "image" && c.ext !== "gif"),
    [caps]
  );

  const loadProbe = useCallback(async (path: string) => {
    setProbing(true);
    setError(null);
    try {
      const info = await api.mediaProbe(path);
      setProbe(info);
      if (info.duration > 0) setEnd(formatTime(info.duration));
    } catch (e) {
      setProbe(null);
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  }, []);

  const pickFiles = useCallback(async () => {
    setError(null);
    try {
      const { paths } = await api.mediaPick({ multiple: true, title: t("convert.pickTitle") });
      if (paths.length === 0) return;
      setSources(paths);
      await loadProbe(paths[0]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [loadProbe, t]);

  const pickAudio = useCallback(async () => {
    try {
      const { paths } = await api.mediaPick({
        multiple: false,
        audio_only: true,
        title: t("convert.pickAudioTitle"),
      });
      if (paths[0]) setAudioSource(paths[0]);
    } catch {
      // отмена диалога — не ошибка
    }
  }, [t]);

  const multiple = sources.length > 1;
  const activeTab = TABS.find((x) => x.id === tab);
  const tabBlocked = Boolean(activeTab?.single && multiple);

  function buildRequest(source: string): MediaJobRequest {
    switch (tab) {
      case "remux":
        return { kind: "remux", source, container };
      case "trim":
        return {
          kind: "trim",
          source,
          start: parseTime(start) || 0,
          end: end ? parseTime(end) : undefined,
          lossless,
        };
      case "replace_audio":
        return {
          kind: "replace_audio",
          source,
          audio_source: audioSource,
          keep_original_audio: keepOriginal,
          language: trackLanguage,
        };
      case "extract_audio":
        return {
          kind: "extract_audio",
          source,
          container: audioContainer,
          bitrate: audioContainer === "original" ? undefined : audioBitrate,
        };
      case "convert":
        return {
          kind: "convert",
          source,
          container,
          video_codec: videoCodec,
          audio_codec: convAudioCodec,
          quality,
          audio_bitrate: audioBitrate,
          height: height || undefined,
        };
      case "gif":
        return {
          kind: "gif",
          source,
          start: parseTime(gifStart) || 0,
          duration: gifDuration,
          fps: gifFps,
          width: gifWidth,
        };
      case "thumbnail":
        return { kind: "thumbnail", source, container: frameFormat, at: parseTime(frameAt) || 0 };
    }
  }

  async function run() {
    if (sources.length === 0) return;
    if (tab === "replace_audio" && !audioSource) {
      setError(t("convert.needAudioFile"));
      return;
    }
    if (tab === "trim") {
      const from = parseTime(start);
      const to = end ? parseTime(end) : Infinity;
      if (Number.isNaN(from) || Number.isNaN(to) || to <= from) {
        setError(t("convert.badRange"));
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      // Одна операция на КАЖДЫЙ выбранный файл — так работает пакетная конвертация
      // папки: выбрал двадцать файлов, поставил формат, получил двадцать задач.
      const targets = activeTab?.single ? sources.slice(0, 1) : sources;
      for (const source of targets) {
        await onSubmit(buildRequest(source));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (caps && !caps.ffmpeg) {
    return (
      <div className="max-w-2xl mx-auto flex flex-col gap-4 py-10">
        <h1 className="text-lg font-semibold text-text">{t("convert.title")}</h1>
        <div className="glass rounded-2xl p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-danger shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-text">{t("convert.noFfmpeg")}</p>
            <p className="text-xs text-text-muted mt-1">{t("convert.noFfmpegHint")}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-5 py-8">
      <div>
        <h1 className="text-lg font-semibold text-text">{t("convert.title")}</h1>
        <p className="text-sm text-text-muted mt-0.5">{t("convert.subtitle")}</p>
      </div>

      {/* --- выбор файлов --- */}
      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={pickFiles}
            className="flex items-center gap-1.5 text-sm text-text bg-surface hover:bg-surface-elevated px-3 py-1.5 rounded-lg transition-colors"
          >
            <Plus size={14} />
            {t("convert.pickFiles")}
          </button>
          {sources.length > 0 && (
            <span className="text-xs text-text-faint">
              {t("convert.selected")}: {sources.length}
            </span>
          )}
          {probing && <Loader2 size={14} className="text-primary animate-spin" />}
        </div>

        {sources.length > 0 && (
          <div className="flex flex-col gap-1 max-h-28 overflow-y-auto">
            {sources.map((path) => (
              <button
                key={path}
                onClick={() => loadProbe(path)}
                title={path}
                className={`text-left text-xs font-mono truncate px-2 py-1 rounded-lg transition-colors ${
                  probe?.path === path
                    ? "bg-surface-elevated text-text"
                    : "text-text-faint hover:text-text-muted"
                }`}
              >
                {path.split(/[\\/]/).pop()}
              </button>
            ))}
          </div>
        )}

        {probe && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted border-t border-border pt-2">
            <span className="uppercase font-mono text-text-faint">{probe.container}</span>
            <span>{formatTime(probe.duration)}</span>
            <span>{formatSize(probe.size)}</span>
            {probe.streams
              .filter((s) => s.kind !== "subtitle")
              .map((s) => (
                <span key={s.index} className="flex items-center gap-1">
                  {s.kind === "video" ? <FileVideo size={11} /> : <Music size={11} />}
                  {s.codec}
                  {s.kind === "video" && s.height ? ` ${s.height}p` : ""}
                  {s.kind === "audio" && s.language ? ` (${s.language})` : ""}
                </span>
              ))}
          </div>
        )}
      </section>

      {sources.length > 0 && (
        <>
          {/* --- операции --- */}
          <section className="glass rounded-2xl p-4 flex flex-col gap-4">
            <div className="flex flex-wrap gap-1">
              {TABS.map((x) => (
                <button
                  key={x.id}
                  onClick={() => setTab(x.id)}
                  disabled={x.single && multiple}
                  className={`px-2.5 py-1 text-xs rounded-lg transition-colors ${
                    tab === x.id
                      ? "bg-surface-elevated text-text"
                      : "text-text-faint hover:text-text-muted disabled:opacity-40 disabled:hover:text-text-faint"
                  }`}
                >
                  {t(x.key as never)}
                </button>
              ))}
            </div>

            {tabBlocked && <p className="text-xs text-warning">{t("convert.singleFileOnly")}</p>}

            {tab === "remux" && (
              <div className="flex flex-col gap-2">
                <p className="text-xs text-text-muted">{t("convert.remuxHint")}</p>
                <Field label={t("convert.container")}>
                  <Select
                    value={container}
                    onChange={setContainer}
                    options={videoContainers.map((c) => ({ value: c.ext, label: c.label }))}
                  />
                </Field>
              </div>
            )}

            {tab === "trim" && (
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-3">
                  <Field label={t("convert.from")}>
                    <TimeInput value={start} onChange={setStart} />
                  </Field>
                  <Field label={t("convert.to")}>
                    <TimeInput value={end} onChange={setEnd} />
                  </Field>
                </div>
                <label className="flex items-center gap-2 text-sm text-text-muted cursor-pointer">
                  <input
                    type="checkbox"
                    checked={lossless}
                    onChange={(e) => setLossless(e.target.checked)}
                    className="accent-primary w-3.5 h-3.5"
                  />
                  {t("convert.losslessTrim")}
                </label>
                <p className="text-xs text-text-faint">
                  {lossless ? t("convert.trimFastHint") : t("convert.trimExactHint")}
                </p>
              </div>
            )}

            {tab === "replace_audio" && (
              <div className="flex flex-col gap-2">
                <p className="text-xs text-text-muted">{t("convert.replaceHint")}</p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={pickAudio}
                    className="flex items-center gap-1.5 text-xs text-text bg-surface hover:bg-surface-elevated px-2.5 py-1 rounded-lg transition-colors"
                  >
                    <Music size={12} />
                    {t("convert.pickAudio")}
                  </button>
                  {audioSource && (
                    <span className="text-xs font-mono text-text-faint truncate" title={audioSource}>
                      {audioSource.split(/[\\/]/).pop()}
                    </span>
                  )}
                </div>
                <label className="flex items-center gap-2 text-sm text-text-muted cursor-pointer">
                  <input
                    type="checkbox"
                    checked={keepOriginal}
                    onChange={(e) => setKeepOriginal(e.target.checked)}
                    className="accent-primary w-3.5 h-3.5"
                  />
                  {t("convert.keepOriginalTrack")}
                </label>
                <Field label={t("convert.trackLanguage")}>
                  <Select
                    value={trackLanguage}
                    onChange={setTrackLanguage}
                    options={[
                      { value: "rus", label: "rus" },
                      { value: "eng", label: "eng" },
                      { value: "", label: "—" },
                    ]}
                  />
                </Field>
              </div>
            )}

            {tab === "extract_audio" && (
              <div className="flex flex-wrap items-center gap-3">
                <Field label={t("convert.format")}>
                  <Select
                    value={audioContainer}
                    onChange={setAudioContainer}
                    options={[
                      { value: "original", label: t("convert.asIs") },
                      ...audioContainers.map((c) => ({ value: c.ext, label: c.label })),
                    ]}
                  />
                </Field>
                {audioContainer !== "original" && (
                  <Field label={t("convert.bitrate")}>
                    <Select
                      value={String(audioBitrate)}
                      onChange={(v) => setAudioBitrate(Number(v))}
                      options={AUDIO_BITRATES.map((b) => ({ value: String(b), label: `${b} kbps` }))}
                    />
                  </Field>
                )}
              </div>
            )}

            {tab === "convert" && (
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Field label={t("convert.container")}>
                    <Select
                      value={container}
                      onChange={setContainer}
                      options={[...videoContainers, ...audioContainers].map((c) => ({
                        value: c.ext,
                        label: c.label,
                      }))}
                    />
                  </Field>
                  <Field label={t("convert.videoCodec")}>
                    <Select
                      value={videoCodec}
                      onChange={setVideoCodec}
                      options={[
                        { value: "copy", label: t("convert.keepCodec") },
                        ...(caps?.video_codecs ?? []).map((c) => ({ value: c.id, label: c.label })),
                      ]}
                    />
                  </Field>
                  <Field label={t("convert.audioCodec")}>
                    <Select
                      value={convAudioCodec}
                      onChange={setConvAudioCodec}
                      options={[
                        { value: "copy", label: t("convert.keepCodec") },
                        ...(caps?.audio_codecs ?? []).map((c) => ({ value: c.id, label: c.label })),
                      ]}
                    />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Field label={t("convert.resolution")}>
                    <Select
                      value={String(height)}
                      onChange={(v) => setHeight(Number(v))}
                      options={HEIGHTS.map((h) => ({
                        value: String(h),
                        label: h === 0 ? t("convert.keepSize") : `${h}p`,
                      }))}
                    />
                  </Field>
                  <Field label={t("convert.audioBitrate")}>
                    <Select
                      value={String(audioBitrate)}
                      onChange={(v) => setAudioBitrate(Number(v))}
                      options={AUDIO_BITRATES.map((b) => ({ value: String(b), label: `${b} kbps` }))}
                    />
                  </Field>
                </div>
                {videoCodec !== "copy" && (
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-text-faint w-24 shrink-0">{t("convert.quality")}</span>
                    <input
                      type="range"
                      min={20}
                      max={100}
                      value={quality}
                      onChange={(e) => setQuality(Number(e.target.value))}
                      className="accent-primary flex-1"
                    />
                    <span className="text-xs font-mono text-text-muted w-8 text-right">{quality}</span>
                  </div>
                )}
                {videoCodec === "copy" && convAudioCodec === "copy" && (
                  <p className="flex items-center gap-1.5 text-xs text-success">
                    <Zap size={11} /> {t("convert.willBeLossless")}
                  </p>
                )}
              </div>
            )}

            {tab === "gif" && (
              <div className="flex flex-wrap items-center gap-3">
                <Field label={t("convert.from")}>
                  <TimeInput value={gifStart} onChange={setGifStart} />
                </Field>
                <Field label={t("convert.durationSec")}>
                  <NumberInput value={gifDuration} onChange={setGifDuration} min={1} max={30} />
                </Field>
                <Field label="FPS">
                  <NumberInput value={gifFps} onChange={setGifFps} min={5} max={30} />
                </Field>
                <Field label={t("convert.widthPx")}>
                  <NumberInput value={gifWidth} onChange={setGifWidth} min={120} max={1280} step={20} />
                </Field>
              </div>
            )}

            {tab === "thumbnail" && (
              <div className="flex flex-wrap items-center gap-3">
                <Field label={t("convert.atTime")}>
                  <TimeInput value={frameAt} onChange={setFrameAt} />
                </Field>
                <Field label={t("convert.format")}>
                  <Select
                    value={frameFormat}
                    onChange={setFrameFormat}
                    options={imageContainers.map((c) => ({ value: c.ext, label: c.label }))}
                  />
                </Field>
              </div>
            )}

            {error && <p className="text-xs text-danger">{error}</p>}

            <button
              onClick={run}
              disabled={busy || tabBlocked || sources.length === 0}
              className="self-start bg-primary text-background font-medium text-sm px-4 py-2 rounded-xl hover:opacity-90 transition-opacity disabled:opacity-40"
            >
              {busy ? t("convert.starting") : t("convert.start")}
              {!activeTab?.single && sources.length > 1 ? ` (${sources.length})` : ""}
            </button>
          </section>

          <MediaJobList jobs={jobs} onCancel={onCancel} onClear={onClear} />
        </>
      )}

      {sources.length === 0 && jobs.length > 0 && (
        <MediaJobList jobs={jobs} onCancel={onCancel} onClear={onClear} />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-xs text-text-faint">{label}</span>
      {children}
    </label>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-surface border border-border rounded-lg px-2 py-1 text-xs text-text outline-none focus:border-primary/50 cursor-pointer"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function TimeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="0:00"
      className="w-20 bg-surface border border-border rounded-lg px-2 py-1 text-xs text-text font-mono outline-none focus:border-primary/50"
    />
  );
}

function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
}: {
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value) || min)))}
      className="w-20 bg-surface border border-border rounded-lg px-2 py-1 text-xs text-text font-mono outline-none focus:border-primary/50"
    />
  );
}
