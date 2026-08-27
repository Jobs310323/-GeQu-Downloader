import { Music } from "lucide-react";
import {
  AUDIO_BITRATE_OPTIONS,
  AUDIO_CODEC_OPTIONS,
  AUDIO_FORMAT_OPTIONS,
  LOSSLESS_AUDIO_FORMATS,
  OUTPUT_CONTAINER_OPTIONS,
  QUALITY_OPTIONS,
  VIDEO_CODEC_OPTIONS,
  type Quality,
} from "../../types/download";
import { useT } from "../../i18n/translations";

export interface FormatState {
  quality: Quality;
  audioOnly: boolean;
  audioFormat: string;
  audioBitrate: string;
  videoCodec: string;
  audioCodec: string;
  outputContainer: string;
  subtitles: boolean;
  neuroDubRu: boolean;
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: readonly string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-surface border border-border rounded-lg px-2.5 py-1.5 text-sm text-text outline-none focus:border-primary/50 cursor-pointer"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

function Toggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label
      className={`flex items-center gap-2 text-sm select-none ${
        disabled ? "text-text-faint opacity-50" : "text-text-muted cursor-pointer"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-primary w-3.5 h-3.5"
      />
      {label}
    </label>
  );
}

export function FormatSelector({
  state,
  onChange,
  ruDubAvailable,
}: {
  state: FormatState;
  onChange: (patch: Partial<FormatState>) => void;
  ruDubAvailable: boolean;
}) {
  const t = useT();
  // У FLAC/WAV/ALAC и у режима «как есть» битрейта не существует — показывать его
  // значит предлагать настройку, которая ничего не меняет.
  const showBitrate = !LOSSLESS_AUDIO_FORMATS.includes(state.audioFormat);
  const isMp3Preset = state.audioOnly && state.audioFormat === "mp3" && state.audioBitrate === "320";

  return (
    <div className="glass rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Toggle
          label={t("format.audioOnly")}
          checked={state.audioOnly}
          onChange={(v) => onChange({ audioOnly: v })}
        />
        {/* Кнопка «в один клик» — стандарт для таких программ: чаще всего от режима
            «только аудио» хотят ровно mp3 320, а не поход по трём селекторам. */}
        <button
          onClick={() =>
            onChange({ audioOnly: true, audioFormat: "mp3", audioBitrate: "320" })
          }
          className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg transition-colors ${
            isMp3Preset
              ? "bg-primary/15 text-primary"
              : "bg-surface text-text-muted hover:text-text hover:bg-surface-elevated"
          }`}
        >
          <Music size={12} />
          {t("format.mp3Preset")}
        </button>

        {!state.audioOnly && (
          <>
            <span className="text-xs text-text-faint">{t("format.quality")}</span>
            <Select
              value={state.quality}
              onChange={(v) => onChange({ quality: v as Quality })}
              options={QUALITY_OPTIONS}
            />
            <span className="text-xs text-text-faint">{t("format.videoCodec")}</span>
            <Select
              value={state.videoCodec}
              onChange={(v) => onChange({ videoCodec: v })}
              options={VIDEO_CODEC_OPTIONS}
            />
            <span className="text-xs text-text-faint">{t("format.container")}</span>
            <Select
              value={state.outputContainer}
              onChange={(v) => onChange({ outputContainer: v })}
              options={OUTPUT_CONTAINER_OPTIONS}
            />
          </>
        )}
        {state.audioOnly && (
          <>
            <span className="text-xs text-text-faint">{t("format.format")}</span>
            <Select
              value={state.audioFormat}
              onChange={(v) => onChange({ audioFormat: v })}
              options={AUDIO_FORMAT_OPTIONS}
            />
            {showBitrate && (
              <>
                <span className="text-xs text-text-faint">{t("format.bitrate")}</span>
                <Select
                  value={state.audioBitrate}
                  onChange={(v) => onChange({ audioBitrate: v })}
                  options={AUDIO_BITRATE_OPTIONS}
                />
              </>
            )}
          </>
        )}
        {!state.audioOnly && (
          <>
            <span className="text-xs text-text-faint">{t("format.audioCodec")}</span>
            <Select
              value={state.audioCodec}
              onChange={(v) => onChange({ audioCodec: v })}
              options={AUDIO_CODEC_OPTIONS}
            />
          </>
        )}
      </div>

      {state.audioOnly && state.audioFormat === "original" && (
        <p className="text-xs text-text-faint">{t("format.originalHint")}</p>
      )}

      <div className="flex items-center gap-4 pt-1 border-t border-border">
        <Toggle
          label={t("format.subtitles")}
          checked={state.subtitles}
          onChange={(v) => onChange({ subtitles: v })}
        />
        <Toggle
          label={ruDubAvailable ? t("format.ruDub") : t("format.ruDubUnavailable")}
          checked={state.neuroDubRu}
          disabled={!ruDubAvailable}
          onChange={(v) => onChange({ neuroDubRu: v })}
        />
      </div>
    </div>
  );
}
