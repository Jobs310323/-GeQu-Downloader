import { CheckCircle2, Check, FolderOpen, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import { useSettings } from "../../context/SettingsContext";
import { useT } from "../../i18n/translations";
import {
  AUDIO_BITRATE_OPTIONS,
  AUDIO_CODEC_OPTIONS,
  AUDIO_FORMAT_OPTIONS,
  COOKIES_BROWSER_OPTIONS,
  LOSSLESS_AUDIO_FORMATS,
  OUTPUT_CONTAINER_OPTIONS,
  QUALITY_OPTIONS,
  SUMMARY_MODEL_OPTIONS,
  VIDEO_CODEC_OPTIONS,
  type Diagnostics,
  type Settings as SettingsType,
} from "../../types/download";

export function SettingsPage() {
  const { settings, online, patch: contextPatch, reload } = useSettings();
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [updating, setUpdating] = useState(false);
  const [updateNote, setUpdateNote] = useState<string | null>(null);
  const [pickingFolder, setPickingFolder] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const t = useT();

  useEffect(() => {
    let cancelled = false;
    // Диагностика раньше вызывалась без .catch — на холодном старте (бэкенд ещё не
    // поднялся) промис отваливался в unhandled rejection, а блок «System status»
    // навсегда оставался пустым. Ретраим, как и загрузку настроек.
    function load(attempt = 0) {
      api
        .diagnostics()
        .then((d) => {
          if (!cancelled) setDiagnostics(d);
        })
        .catch(() => {
          if (!cancelled && attempt < 5) {
            setTimeout(() => load(attempt + 1), Math.min(500 * 2 ** attempt, 5000));
          }
        });
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(
    () => () => {
      if (flashTimer.current) clearTimeout(flashTimer.current);
    },
    []
  );

  // Раньше здесь был `return null` — при неподнявшемся бэкенде страница настроек
  // была просто пустой, без единого слова о причине. Это и читалось как
  // «не работают кнопки настройки».
  if (!settings) {
    return (
      <div className="max-w-xl mx-auto flex flex-col gap-3 py-10">
        <h1 className="text-lg font-semibold text-text">{t("settings.title")}</h1>
        <p className="text-sm text-text-muted">
          {online ? t("summary.loading") : t("app.offline.body")}
        </p>
      </div>
    );
  }

  async function patch(p: Partial<SettingsType>) {
    await contextPatch(p);
    setSavedFlash(true);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setSavedFlash(false), 1500);
  }

  async function chooseFolder() {
    setPickingFolder(true);
    try {
      const result = await api.chooseFolder(settings?.download_folder);
      if (result.ok) {
        await reload();
        setSavedFlash(true);
        if (flashTimer.current) clearTimeout(flashTimer.current);
        flashTimer.current = setTimeout(() => setSavedFlash(false), 1500);
      }
    } finally {
      setPickingFolder(false);
    }
  }

  async function updateYtdlp() {
    setUpdating(true);
    setUpdateNote(null);
    try {
      const result = await api.updateYtdlp();
      const d = await api.diagnostics();
      setDiagnostics(d);
      if (result.restart_required) setUpdateNote(t("settings.restartNeeded"));
    } catch (e) {
      setUpdateNote(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto flex flex-col gap-6 py-8">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-text">{t("settings.title")}</h1>
        <span
          className={`flex items-center gap-1 text-xs text-success transition-opacity duration-300 ${
            savedFlash ? "opacity-100" : "opacity-0"
          }`}
        >
          <Check size={13} />
          {t("settings.saved")}
        </span>
      </div>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.general")}</h2>
        <Row label={t("settings.theme")}>
          <SegButtons
            value={settings.theme}
            options={["dark", "light"]}
            onChange={(v) => patch({ theme: v as SettingsType["theme"] })}
          />
        </Row>
        <Row label={t("settings.language")}>
          <SegButtons
            value={settings.language}
            options={["ru", "en"]}
            onChange={(v) => patch({ language: v as SettingsType["language"] })}
          />
        </Row>
      </section>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.downloads")}</h2>
        <Row label={t("settings.defaultFolder")}>
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate max-w-[200px] text-xs text-text-faint font-mono" title={settings.download_folder}>
              {settings.download_folder}
            </span>
            <button
              onClick={chooseFolder}
              disabled={pickingFolder}
              className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1 rounded-lg transition-colors shrink-0 disabled:opacity-50"
            >
              {pickingFolder ? <Loader2 size={12} className="animate-spin" /> : <FolderOpen size={12} />}
              {t("settings.change")}
            </button>
            <button
              onClick={() => api.reveal(settings.download_folder).catch(() => undefined)}
              className="text-xs text-text-faint hover:text-text px-2 py-1 rounded-lg transition-colors shrink-0"
            >
              {t("settings.open")}
            </button>
          </div>
        </Row>
        <Row label={t("settings.playlistSubfolders")}>
          <input
            type="checkbox"
            checked={settings.create_playlist_folder}
            onChange={(e) => patch({ create_playlist_folder: e.target.checked })}
            className="accent-primary w-4 h-4"
          />
        </Row>
        <Row label={t("settings.removeAfter")}>
          <input
            type="checkbox"
            checked={settings.remove_after_download}
            onChange={(e) => patch({ remove_after_download: e.target.checked })}
            className="accent-primary w-4 h-4"
          />
        </Row>
        <Row label={t("settings.container")}>
          <SegButtons
            value={settings.output_container}
            options={[...OUTPUT_CONTAINER_OPTIONS]}
            onChange={(v) => patch({ output_container: v })}
          />
        </Row>
        <Row label={t("settings.concurrent")}>
          <input
            type="number"
            min={1}
            max={5}
            value={settings.concurrent_downloads}
            onChange={(e) =>
              patch({ concurrent_downloads: Math.min(5, Math.max(1, Number(e.target.value) || 1)) })
            }
            className="w-16 bg-surface rounded-lg px-2 py-1 text-xs text-text text-right"
          />
        </Row>
        <Row label={t("settings.filenameTemplate")}>
          <TextField
            defaultValue={settings.filename_template}
            onCommit={(v) => patch({ filename_template: v || "%(title)s.%(ext)s" })}
            placeholder="%(title)s.%(ext)s"
          />
        </Row>
      </section>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.defaults")}</h2>
        <Row label={t("settings.defaultQuality")}>
          <Dropdown
            value={settings.default_quality}
            options={[...QUALITY_OPTIONS]}
            onChange={(v) => patch({ default_quality: v })}
          />
        </Row>
        <Row label={t("settings.audioOnly")}>
          <input
            type="checkbox"
            checked={settings.audio_only}
            onChange={(e) => patch({ audio_only: e.target.checked })}
            className="accent-primary w-4 h-4"
          />
        </Row>
        <Row label={t("settings.audioFormat")}>
          <Dropdown
            value={settings.audio_format}
            options={[...AUDIO_FORMAT_OPTIONS]}
            onChange={(v) => patch({ audio_format: v })}
          />
        </Row>
        {/* У FLAC/WAV/ALAC и у режима «как есть» битрейта не существует —
            селектор в этом случае обещал бы настройку, которая ничего не меняет. */}
        {!LOSSLESS_AUDIO_FORMATS.includes(settings.audio_format) && (
          <Row label={t("settings.audioBitrate")}>
            <Dropdown
              value={settings.audio_bitrate}
              options={[...AUDIO_BITRATE_OPTIONS]}
              onChange={(v) => patch({ audio_bitrate: v })}
            />
          </Row>
        )}
        <Row label={t("settings.defaultVideoCodec")}>
          <Dropdown
            value={settings.default_video_codec ?? "any"}
            options={[...VIDEO_CODEC_OPTIONS]}
            onChange={(v) => patch({ default_video_codec: v })}
          />
        </Row>
        <Row label={t("settings.defaultAudioCodec")}>
          <Dropdown
            value={settings.default_audio_codec ?? "any"}
            options={[...AUDIO_CODEC_OPTIONS]}
            onChange={(v) => patch({ default_audio_codec: v })}
          />
        </Row>
      </section>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.summary")}</h2>
        <Row label={t("settings.apiKey")}>
          <div className="flex items-center gap-2">
            {settings.summary_api_key_set && (
              <span className="text-xs text-success">{t("settings.apiKeySet")}</span>
            )}
            <TextField
              defaultValue=""
              type="password"
              onCommit={(v) => patch({ summary_api_key: v })}
              placeholder="sk-ant-..."
            />
          </div>
        </Row>
        <p className="text-xs text-text-faint -mt-1">{t("settings.apiKeyHint")}</p>
        <Row label={t("settings.summaryModel")}>
          <Dropdown
            value={settings.summary_model}
            options={[...SUMMARY_MODEL_OPTIONS]}
            onChange={(v) => patch({ summary_model: v })}
          />
        </Row>
      </section>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.network")}</h2>
        <Row label={t("settings.proxy")}>
          <TextField
            defaultValue={settings.proxy}
            onCommit={(v) => patch({ proxy: v })}
            placeholder="socks5://127.0.0.1:1080"
          />
        </Row>
        <Row label={t("settings.cookies")}>
          <select
            value={settings.cookies_from_browser}
            onChange={(e) => patch({ cookies_from_browser: e.target.value })}
            className="bg-surface rounded-lg px-2 py-1 text-xs text-text capitalize"
          >
            {COOKIES_BROWSER_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </Row>
      </section>

      <section className="glass rounded-2xl p-4 flex flex-col gap-3">
        <h2 className="text-sm font-medium text-text-muted">{t("settings.status")}</h2>
        <Row label="yt-dlp">
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-text-faint">{diagnostics?.ytdlp_version}</span>
            {!diagnostics?.frozen && (
              <button
                onClick={updateYtdlp}
                disabled={updating}
                className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text bg-surface hover:bg-surface-elevated px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50"
              >
                <RefreshCw size={12} className={updating ? "animate-spin" : ""} />
                {updating ? t("settings.updating") : t("settings.update")}
              </button>
            )}
          </div>
        </Row>
        {updateNote && <p className="text-xs text-warning -mt-1">{updateNote}</p>}
        <Row label="FFmpeg">
          {diagnostics?.ffmpeg_installed ? (
            <span className="flex items-center gap-1.5 text-xs text-success">
              <CheckCircle2 size={13} /> {t("settings.installed")}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-danger">
              <XCircle size={13} /> {t("settings.notFound")}
            </span>
          )}
        </Row>
      </section>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-text shrink-0">{label}</span>
      {children}
    </div>
  );
}

function Dropdown({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-surface rounded-lg px-2 py-1 text-xs text-text"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function TextField({
  defaultValue,
  onCommit,
  placeholder,
  type = "text",
}: {
  defaultValue: string;
  onCommit: (v: string) => void;
  placeholder?: string;
  type?: "text" | "password";
}) {
  const [value, setValue] = useState(defaultValue);
  useEffect(() => setValue(defaultValue), [defaultValue]);
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => value !== defaultValue && onCommit(value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      className="w-44 bg-surface rounded-lg px-2 py-1 text-xs text-text font-mono placeholder:text-text-faint"
    />
  );
}

function SegButtons({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex bg-surface rounded-lg p-0.5 gap-0.5">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-2.5 py-1 text-xs rounded-md capitalize transition-colors ${
            value === o ? "bg-surface-elevated text-text" : "text-text-faint hover:text-text-muted"
          }`}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
