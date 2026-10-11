export type Account = {
  id: string;
  label: string;
  role: "candidate" | "employer";
  email?: string;
  csrf?: string;
};
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  headers: Record<string, string> = {},
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    signal,
    credentials: "same-origin",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-CSRF-Token": csrf } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      message: `Сервер недоступен (${response.status}). Повторите запрос.`,
    }));
    throw new Error(
      (error.message || error.detail || `Ошибка запроса (${response.status})`) +
        (error.details
          ? " · " +
            error.details.map((d: { message: string }) => d.message).join("; ")
          : ""),
    );
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export async function upload<T>(path: string, file: File): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-CSRF-Token": csrf,
    },
    body: file,
  });
  const data = await response
    .json()
    .catch(() => ({ message: "Не удалось прочитать ответ сервера" }));
  if (!response.ok)
    throw new Error(
      data.message || data.detail || `Ошибка загрузки (${response.status})`,
    );
  return data as T;
}

export function getCsrf() {
  return csrf;
}

export async function downloadFile(path: string, filename: string) {
  const response = await fetch("/api/v1" + path, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ message: "Экспорт недоступен" }));
    throw new Error(error.message || error.detail || "Экспорт недоступен");
  }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
