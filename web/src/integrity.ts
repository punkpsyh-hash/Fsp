// Сигналы добросовестности при тесте. Передаются только тип события, время и номер
// вопроса: текст вопросов, ответы, содержимое буфера и экран не собираются.
// Сбой передачи никогда не мешает проходить тест.
import { getCsrf } from "./api";

type IntegrityEvent = { type: string; t: number; d?: number; q?: string };

const FLUSH_MS = 10_000;
const HEARTBEAT_MS = 15_000;
const MAX_QUEUE = 300;
const SHORTCUT_KEYS = new Set(["c", "x", "a", "u", "p", "s"]);

export type IntegrityMonitor = { answer: (questionId: string) => void; flush: () => Promise<void>; stop: () => void };

export function startIntegrityMonitor(attemptId: string): IntegrityMonitor {
  const started = performance.now();
  const now = () => Math.round(performance.now() - started);
  let queue: IntegrityEvent[] = [];
  let hiddenAt: number | null = null;
  let stopped = false;
  let sawFullscreen = Boolean(document.fullscreenElement);
  let sending: Promise<boolean> | null = null;

  const push = (event: Omit<IntegrityEvent, "t">) => {
    if (stopped) return;
    queue.push({ ...event, t: now() });
    if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
  };

  const flush = async (urgent = false): Promise<void> => {
    // Не допускаем гонку submit с периодической отправкой. Очередь ограничена,
    // а сбой сети завершает ожидание и сохраняет события для следующей попытки.
    for (let sent = 0; sent < MAX_QUEUE / 100; sent++) {
      if (sending) {
        if (!await sending) return;
        sent--;
        continue;
      }
      if (!queue.length) return;
      const batch = queue.slice(0, 100);
      queue = queue.slice(batch.length);
      sending = fetch(`/api/v1/assessments/attempts/${attemptId}/integrity`, {
      method: "POST",
      credentials: "same-origin",
      keepalive: urgent,
      signal: AbortSignal.timeout(5_000),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
      body: JSON.stringify({ events: batch }),
    })
      .then((response) => {
        if (!response.ok && response.status !== 409) {
          queue = [...batch, ...queue].slice(-MAX_QUEUE);
          return false;
        }
        return true;
      })
      .catch(() => {
        queue = [...batch, ...queue].slice(-MAX_QUEUE);
        return false;
      }).finally(() => { sending = null; });
      if (!await sending) return;
    }
  };

  const inQuestion = (target: EventTarget | null) =>
    target instanceof Node && Boolean((target instanceof Element ? target : target.parentElement)?.closest(".assessment-question"));

  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      hiddenAt = now();
      push({ type: "hidden" });
      flush(true);
    } else {
      const away = hiddenAt === null ? 0 : now() - hiddenAt;
      hiddenAt = null;
      push({ type: "visible", d: Math.min(away, 3_600_000) });
    }
  };
  const onBlur = () => push({ type: "blur" });
  const onFocus = () => push({ type: "focus" });
  const onCopy = (event: ClipboardEvent) => {
    if (!inQuestion(event.target)) return;
    push({ type: event.type === "cut" ? "cut" : "copy" });
    event.preventDefault();
  };
  const onPaste = () => push({ type: "paste" });
  const onContext = (event: MouseEvent) => {
    if (!inQuestion(event.target)) return;
    push({ type: "contextmenu" });
    event.preventDefault();
  };
  const onKey = (event: KeyboardEvent) => {
    const combo = (event.ctrlKey || event.metaKey) && SHORTCUT_KEYS.has(event.key.toLowerCase());
    if (combo || event.key === "F12" || event.key === "PrintScreen") push({ type: "shortcut" });
  };
  const onFullscreen = () => {
    if (document.fullscreenElement) sawFullscreen = true;
    else if (sawFullscreen) {
      push({ type: "fullscreen_exit" });
      sawFullscreen = false;
    }
  };

  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", onBlur);
  window.addEventListener("focus", onFocus);
  document.addEventListener("copy", onCopy);
  document.addEventListener("cut", onCopy);
  document.addEventListener("paste", onPaste);
  document.addEventListener("contextmenu", onContext);
  document.addEventListener("keydown", onKey);
  document.addEventListener("fullscreenchange", onFullscreen);
  const beat = setInterval(() => push({ type: "heartbeat" }), HEARTBEAT_MS);
  const sender = setInterval(() => flush(), FLUSH_MS);
  push({ type: "heartbeat" });

  return {
    answer: (questionId) => push({ type: "answer", q: questionId.slice(0, 80) }),
    flush: () => flush(),
    stop: () => {
      if (stopped) return;
      flush(true);
      stopped = true;
      clearInterval(beat);
      clearInterval(sender);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("copy", onCopy);
      document.removeEventListener("cut", onCopy);
      document.removeEventListener("paste", onPaste);
      document.removeEventListener("contextmenu", onContext);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFullscreen);
    },
  };
}
