import { useEffect, useRef } from "react";
import { WS_URL } from "../config/app";
import type { WsEvent } from "../types/download";

/**
 * Держит WebSocket-соединение живым и переподключается при обрыве.
 * onConnect зовётся при каждом успешном (пере)подключении — начальном и после обрыва —
 * чтобы вызывающий код мог досинхронизировать состояние (см. useDownloads: события,
 * произошедшие пока сокет был разорван, иначе теряются без следа).
 */
export function useWsEvents(onEvent: (event: WsEvent) => void, onConnect?: () => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const connectRef = useRef(onConnect);
  connectRef.current = onConnect;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => connectRef.current?.();
      socket.onmessage = (ev) => {
        try {
          handlerRef.current(JSON.parse(ev.data) as WsEvent);
        } catch {
          // игнорируем не-JSON сообщения
        }
      };
      socket.onclose = () => {
        if (!closed) retryTimer = setTimeout(connect, 1500);
      };
      socket.onerror = () => socket?.close();
    }

    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);
}
