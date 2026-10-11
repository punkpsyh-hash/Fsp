import { useEffect, useRef, useState } from "react";

let navigationGuard: (() => Promise<boolean>) | null = null;
let guardFlight: Promise<boolean> | null = null;
export function flushNavigation(): Promise<boolean> {
  if (!guardFlight)
    guardFlight = (
      navigationGuard ? navigationGuard() : Promise.resolve(true)
    ).finally(() => {
      guardFlight = null;
    });
  return guardFlight;
}
export function navigate(path: string) {
  window.location.hash = path;
}

export function useNavigationGuard(guard: () => Promise<boolean>) {
  const current = useRef(guard);
  current.current = guard;
  useEffect(() => {
    const call = () => current.current();
    navigationGuard = call;
    return () => {
      if (navigationGuard === call) navigationGuard = null;
    };
  }, []);
}

export function useRoute() {
  const [path, setPath] = useState(window.location.hash.slice(1));
  const acceptedPath = useRef(path);
  useEffect(() => {
    let request = 0;
    const update = async () => {
      const target = window.location.hash.slice(1),
        generation = ++request;
      const accepted = await flushNavigation();
      if (generation !== request) return;
      if (accepted) {
        acceptedPath.current = target;
        setPath(target);
      } else
        window.history.replaceState(
          null,
          "",
          window.location.pathname +
            window.location.search +
            "#" +
            acceptedPath.current,
        );
    };
    window.addEventListener("hashchange", update);
    return () => {
      request++;
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return path.split("/").filter(Boolean);
}
