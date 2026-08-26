import {
  AUDIO_BITRATE_OPTIONS,
  AUDIO_CODEC_OPTIONS,
  AUDIO_FORMAT_OPTIONS,
  OUTPUT_CONTAINER_OPTIONS,
  QUALITY_OPTIONS,
  VIDEO_CODEC_OPTIONS,
  type Quality,
} from "../../types/download";

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

function Toggle({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`flex items-center gap-2 text-sm select-none ${disabled ? "text-text-faint opacity-50" : "text-text-muted cursor-pointer"}`}>
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
  return (
    <div className="glass rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Toggle
          label="Audio only"
          checked={state.audioOnly}
          onChange={(v) => onChange({ audioOnly: v })}
        />
        {!state.audioOnly && (
          <>
            <span className="text-xs text-text-faint">Quality</span>
            <Select value={state.quality} onChange={(v) => onChange({ quality: v as Quality })} options={QUALITY_OPTIONS} />
            <span className="text-xs text-text-faint">Video codec</span>
            <Select value={state.videoCodec} onChange={(v) => onChange({ videoCodec: v })} options={VIDEO_CODEC_OPTIONS} />
            <span className="text-xs text-text-faint">Container</span>
            <Select value={state.outputContainer} onChange={(v) => onChange({ outputContainer: v })} options={OUTPUT_CONTAINER_OPTIONS} />
          </>
        )}
        {state.audioOnly && (
          <>
            <span className="text-xs text-text-faint">Format</span>
            <Select value={state.audioFormat} onChange={(v) => onChange({ audioFormat: v })} options={AUDIO_FORMAT_OPTIONS} />
            <span className="text-xs text-text-faint">Bitrate</span>
            <Select value={state.audioBitrate} onChange={(v) => onChange({ audioBitrate: v })} options={AUDIO_BITRATE_OPTIONS} />
          </>
        )}
        <span className="text-xs text-text-faint">Audio codec</span>
        <Select value={state.audioCodec} onChange={(v) => onChange({ audioCodec: v })} options={AUDIO_CODEC_OPTIONS} />
      </div>

      <div className="flex items-center gap-4 pt-1 border-t border-border">
        <Toggle label="Subtitles (.srt)" checked={state.subtitles} onChange={(v) => onChange({ subtitles: v })} />
        <Toggle
          label={ruDubAvailable ? "Russian audio track" : "Russian audio track (unavailable)"}
          checked={state.neuroDubRu}
          disabled={!ruDubAvailable}
          onChange={(v) => onChange({ neuroDubRu: v })}
        />
      </div>
    </div>
  );
}
