import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sidebar, type Page } from "./components/layout/Sidebar";
import { UrlInput } from "./components/download/UrlInput";
import { VideoPreview, VideoPreviewSkeleton } from "./components/download/VideoPreview";
import { FormatSelector, type FormatState } from "./components/download/FormatSelector";
import { DownloadButton } from "./components/download/DownloadButton";
import { DownloadQueue } from "./components/download/DownloadQueue";
import { ErrorModal } from "./components/modals/ErrorModal";
import { SummaryModal } from "./components/modals/SummaryModal";
import { ToastStack } from "./components/ui/Toast";
import { OfflineBanner } from "./components/ui/OfflineBanner";
import { HistoryPage } from "./components/history/HistoryList";
import { SettingsPage } from "./components/settings/Settings";
import { useDownloads } from "./hooks/useDownloads";
import { useSettings } from "./context/SettingsContext";
import { api, ApiError } from "./services/api";
import type { Quality, VideoInfo } from "./types/download";
import { useT } from "./i18n/translations";

const DEFAULT_FORMAT: FormatState = {
  quality: "1080p",
  audioOnly: false,
  audioFormat: "mp3",
  audioBitrate: "192",
  videoCodec: "any",
  audioCodec: "any",
  outputContainer: "mp4",
  subtitles: false,
  neuroDubRu: false,
};

export default function App() {
  const [page, setPage] = useState<Page>("home");
  const [url, setUrl] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [format, setFormat] = useState<FormatState>(DEFAULT_FORMAT);
  const [summaryOpen, setSummaryOpen] = useState(false);

  const { jobs, logs, addToQueue, pause, resume, cancel, dismiss } = useDownloads();
  const { settings } = useSettings();
  const t = useT();

  // t читается внутри эффекта анализа, но НЕ должен быть его зависимостью: смена языка
  // не повод перекачивать метаданные, а любое лишнее срабатывание этого эффекта — это
  // новый 10-25-секундный запрос в YouTube.
  const tRef = useRef(t);
  tRef.current = t;

  // Значения по умолчанию для новой загрузки берутся из настроек. Раньше DEFAULT_FORMAT
  // был захардкожен, поэтому «качество по умолчанию», «только аудио» и «контейнер»
  // из настроек не влияли ни на что — их можно было менять сколько угодно без эффекта.
  const defaultFormat = useMemo<FormatState>(
    () => ({
      ...DEFAULT_FORMAT,
      quality: (settings?.default_quality as Quality) || DEFAULT_FORMAT.quality,
      audioOnly: settings?.audio_only ?? DEFAULT_FORMAT.audioOnly,
      audioFormat: settings?.audio_format || DEFAULT_FORMAT.audioFormat,
      audioBitrate: settings?.audio_bitrate || DEFAULT_FORMAT.audioBitrate,
      outputContainer: settings?.output_container || DEFAULT_FORMAT.outputContainer,
    }),
    [settings]
  );

  // Пока пользователь не начал крутить селекторы для конкретного видео, форма следует
  // за настройками; как только тронул — фиксируем его выбор до следующей загрузки.
  const formatTouched = useRef(false);
  useEffect(() => {
    if (!formatTouched.current) setFormat(defaultFormat);
  }, [defaultFormat]);

  const activeCount = useMemo(
    () => jobs.filter((j) => j.status !== "completed" && j.status !== "failed" && j.status !== "cancelled").length,
    [jobs]
  );

  const errorJob = jobs.find((j) => j.error);
  const [dismissedErrorId, setDismissedErrorId] = useState<string | null>(null);

  useEffect(() => {
    const target = url.trim();
    if (!target) {
      setInfo(null);
      setAnalyzeError(null);
      setAnalyzing(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    setAnalyzing(true);
    setAnalyzeError(null);

    // ApiError (сервер ответил, но с ошибкой — "видео недоступно" и т.п.) не ретраим,
    // это не транзиентная проблема. Но если fetch падает совсем (TypeError "Failed to
    // fetch") — почти всегда бэкенд ещё не успел подняться (холодный старт EXE) —
    // пара коротких ретраев вместо мгновенного "We couldn't analyze this link."
    // setAnalyzing(false) выставляется только когда серия попыток реально завершена
    // (успех, окончательная ошибка или исчерпаны ретраи), не после первой неудачи.
    async function analyzeWithRetry(attempt = 0): Promise<void> {
      try {
        const result = await api.analyze(target, controller.signal);
        if (!cancelled) {
          setInfo(result);
          setAnalyzing(false);
        }
      } catch (e) {
        if (cancelled || controller.signal.aborted) return;
        if (!(e instanceof ApiError) && attempt < 4) {
          setTimeout(() => analyzeWithRetry(attempt + 1), 800);
          return;
        }
        setInfo(null);
        setAnalyzeError(e instanceof ApiError ? e.message : tRef.current("app.analyzeUnreachable"));
        setAnalyzing(false);
      }
    }

    const handle = setTimeout(() => analyzeWithRetry(), 400);
    return () => {
      cancelled = true;
      clearTimeout(handle);
      controller.abort();
    };
    // Зависимость ТОЛЬКО от url. Любое другое значение здесь означает повторный
    // сетевой разбор ссылки на ровном месте — см. комментарий к useT.
  }, [url]);

  const handleDownload = useCallback(async () => {
    if (!info) return;
    await addToQueue({
      url,
      title: info.title,
      quality: format.quality,
      audio_only: format.audioOnly,
      audio_format: format.audioFormat,
      audio_bitrate: format.audioBitrate,
      video_codec: format.videoCodec,
      audio_codec: format.audioCodec,
      output_container: format.outputContainer,
      subtitles: format.subtitles,
      neuro_dub_ru: format.neuroDubRu && info.has_ru_dub,
      is_playlist: info.is_playlist,
      // Эти два флага живут в настройках, но раньше никогда не доезжали до задачи —
      // бэкенд подставлял свои дефолты, и переключатели в настройках ничего не меняли.
      create_playlist_folder: settings?.create_playlist_folder ?? true,
      remove_after_download: settings?.remove_after_download ?? false,
    });
    setUrl("");
    setInfo(null);
    formatTouched.current = false;
    setFormat(defaultFormat);
  }, [addToQueue, url, info, format, settings, defaultFormat]);

  const patchFormat = useCallback((p: Partial<FormatState>) => {
    formatTouched.current = true;
    setFormat((s) => ({ ...s, ...p }));
  }, []);

  const handleRedownload = useCallback((redownloadUrl: string) => {
    setPage("home");
    setUrl(redownloadUrl);
  }, []);

  return (
    <div className="flex h-full">
      <Sidebar page={page} onNavigate={setPage} activeCount={activeCount} />

      <main className="flex-1 overflow-y-auto px-8">
        <div className="max-w-2xl mx-auto pt-4 empty:hidden">
          <OfflineBanner />
        </div>
        {page === "home" && (
          <div className="max-w-2xl mx-auto flex flex-col gap-6 py-10">
            <div className="text-center">
              <h1 className="text-2xl font-semibold text-text tracking-tight">{t("app.tagline1")}</h1>
              <p className="text-text-muted mt-1">{t("app.tagline2")}</p>
            </div>

            <UrlInput value={url} onChange={setUrl} onSubmit={handleDownload} analyzing={analyzing} />

            {analyzing && <VideoPreviewSkeleton />}
            {!analyzing && analyzeError && (
              <p className="text-sm text-danger text-center">{analyzeError}</p>
            )}
            {!analyzing && info && (
              <VideoPreview info={info} onSummarize={() => setSummaryOpen(true)} />
            )}

            {info && (
              <>
                <FormatSelector state={format} onChange={patchFormat} ruDubAvailable={info.has_ru_dub} />
                <DownloadButton onClick={handleDownload} />
              </>
            )}

            <div className="pt-4">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-sm font-medium text-text-muted">{t("download.active")}</h2>
              </div>
              <DownloadQueue jobs={jobs} onPause={pause} onResume={resume} onCancel={cancel} onDismiss={dismiss} />
            </div>
          </div>
        )}

        {page === "history" && <HistoryPage onRedownload={handleRedownload} />}
        {page === "settings" && <SettingsPage />}
      </main>

      {errorJob && errorJob.error && errorJob.id !== dismissedErrorId && (
        <ErrorModal
          code={errorJob.error.code}
          message={errorJob.error.message}
          onClose={() => setDismissedErrorId(errorJob.id)}
        />
      )}

      {summaryOpen && info && (
        <SummaryModal
          url={url}
          title={info.title}
          duration={info.duration}
          onClose={() => setSummaryOpen(false)}
        />
      )}

      <ToastStack toasts={logs.filter((l) => l.level !== "info").slice(-3)} />
    </div>
  );
}
