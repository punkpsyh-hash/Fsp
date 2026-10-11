import { useEffect, useRef, useState } from "react";

// Пауза защищает показ вопроса в интерфейсе, но не останавливает срок попытки.
export function useExamMode(active: boolean) {
  const [paused, setPaused] = useState(false);
  const [away, setAway] = useState(false);
  const [fullscreenActive, setFullscreenActive] = useState(false);
  const [fullscreenMessage, setFullscreenMessage] = useState("");
  const windowBlurred = useRef(false);
  const requestedFullscreen = useRef(false);
  const enteredFullscreen = useRef(false);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    if (!active) {
      setPaused(false);
      setAway(false);
      setFullscreenActive(Boolean(document.fullscreenElement));
      setFullscreenMessage("");
      return;
    }
    const onVisibility = () => {
      const hidden = document.visibilityState === "hidden";
      setAway(hidden || windowBlurred.current);
      if (hidden) setPaused(true);
    };
    const onBlur = () => {
      windowBlurred.current = true;
      setAway(true);
      setPaused(true);
    };
    const onFocus = () => {
      windowBlurred.current = false;
      setAway(document.visibilityState === "hidden");
    };
    const onFullscreen = () => {
      if (!activeRef.current) return;
      const entered = Boolean(document.fullscreenElement);
      setFullscreenActive(entered);
      if (entered && requestedFullscreen.current) enteredFullscreen.current = true;
      if (!entered && enteredFullscreen.current) {
        enteredFullscreen.current = false;
        requestedFullscreen.current = false;
        setFullscreenMessage("Полноэкранный режим завершён. Продолжите оценку.");
        setPaused(true);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    document.addEventListener("fullscreenchange", onFullscreen);
    onVisibility();
    onFullscreen();
    return () => {
      activeRef.current = false;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("fullscreenchange", onFullscreen);
      const ownFullscreen = enteredFullscreen.current && document.fullscreenElement === document.documentElement;
      requestedFullscreen.current = false;
      enteredFullscreen.current = false;
      if (ownFullscreen && document.exitFullscreen) {
        try {
          void document.exitFullscreen().catch(() => {});
        } catch {
          // Выход может быть уже отклонён браузером; системный Esc остаётся доступен.
        }
      }
    };
  }, [active]);

  function resume() {
    if (document.visibilityState === "hidden" || windowBlurred.current) return;
    setPaused(false);
  }

  async function enterFullscreen() {
    if (!document.fullscreenEnabled || !document.documentElement.requestFullscreen) {
      setFullscreenMessage("Полноэкранный режим недоступен в этом браузере. Продолжайте в обычном окне.");
      return;
    }
    try {
      requestedFullscreen.current = true;
      await document.documentElement.requestFullscreen();
      if (!activeRef.current) {
        if (document.fullscreenElement === document.documentElement && document.exitFullscreen)
          await document.exitFullscreen().catch(() => {});
        return;
      }
      setFullscreenMessage("Полноэкранный режим включён. Для выхода нажмите Esc.");
    } catch {
      requestedFullscreen.current = false;
      if (activeRef.current)
        setFullscreenMessage("Браузер не разрешил полноэкранный режим. Продолжайте в обычном окне.");
    }
  }

  return { paused, away, fullscreenActive, fullscreenMessage, resume, enterFullscreen };
}
