import { useEffect, useRef } from "react";
import { WS_URL } from "../config/app";
import type { WsEvent } from "../types/download";

/**
 * ОДИН WebSocket на всё приложение, с набором подписчиков.
 *
 * Раньше хук открывал собственное соединение на каждый вызов. Пока подписчик был
 * один (очередь загрузок), это не было заметно; со второй подпиской (задачи
 * конвертера) приложение начало держать два сокета к своему же бэкенду, а каждый
 * broadcast сервер отправлял дважды. Соединение живёт в модуле, переподключается
 * само и закрывается, когда отписался последний слушатель.
 */

type Listener = { onEvent: (event: WsEvent) => void; onConnect?: () => void };

const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let wantOpen = false;

function connect() {
  if (!wantOpen || (socket && socket.readyState <= WebSocket.OPEN)) return;
  socket = new WebSocket(WS_URL);
  socket.onopen = () => {
    for (const l of listeners) l.onConnect?.();
  };
  socket.onmessage = (ev) => {
    let parsed: WsEvent;
    try {
      parsed = JSON.parse(ev.data) as WsEvent;
    } catch {
      return; // не-JSON сообщения игнорируем
    }
    for (const l of listeners) l.onEvent(parsed);
  };
  socket.onclose = () => {
    socket = null;
    if (wantOpen) retryTimer = setTimeout(connect, 1500);
  };
  socket.onerror = () => socket?.close();
}

/**
 * Подписка на события бэкенда. onConnect зовётся при каждом успешном (пере)подключении
 * и сразу при подписке к уже открытому сокету — чтобы подписчик мог досинхронизировать
 * состояние: события, произошедшие до его появления, иначе теряются без следа.
 */
export function useWsEvents(onEvent: (event: WsEvent) => void, onConnect?: () => void) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const connectRef = useRef(onConnect);
  connectRef.current = onConnect;

  useEffect(() => {
    const listener: Listener = {
      onEvent: (e) => handlerRef.current(e),
      onConnect: () => connectRef.current?.(),
    };
    listeners.add(listener);
    wantOpen = true;
    if (socket?.readyState === WebSocket.OPEN) listener.onConnect?.();
    else connect();

    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) {
        wantOpen = false;
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = null;
        socket?.close();
        socket = null;
      }
    };
  }, []);
}
