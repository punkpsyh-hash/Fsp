import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { navigate } from "./routing";

type Thread = {
  counterpart_id: string;
  counterpart_name: string;
  can_send: boolean;
  unread: number;
  last_body: string | null;
  last_at: string | null;
  last_sender_role: string | null;
};
type Message = {
  id: string;
  sender_role: string;
  body: string;
  created_at: string;
  read: boolean;
  mine: boolean;
};

const POLL_MS = 15000;
const MAX_BODY = 2000;

function when(value: string) {
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Переписка доступна только при открытом контакте; после его отзыва история остаётся для чтения. */
export function Messages({
  role,
  selected,
}: {
  role: "candidate" | "employer";
  selected?: string;
}) {
  const base = role === "candidate" ? "/candidate/chats" : "/company/chats";
  const [threads, setThreads] = useState<Thread[]>([]),
    [messages, setMessages] = useState<Message[]>([]),
    [draft, setDraft] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const current = threads.find((t) => t.counterpart_id === selected);

  const loadThreads = useCallback(
    () => api<Thread[]>(base).then(setThreads),
    [base],
  );
  const loadMessages = useCallback(
    async (id: string) => {
      const rows = await api<Message[]>(`${base}/${id}/messages`);
      setMessages(rows);
      if (rows.some((m) => !m.mine && !m.read)) {
        await api(`${base}/${id}/read`, "POST");
        await loadThreads();
      }
    },
    [base, loadThreads],
  );

  useEffect(() => {
    let alive = true;
    loadThreads()
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [loadThreads]);

  useEffect(() => {
    setMessages([]);
    setDraft("");
    if (!selected) return;
    let alive = true;
    const refresh = () => {
      if (document.hidden) return;
      loadMessages(selected).catch((e) => alive && setError(e.message));
    };
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [selected, loadMessages]);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight });
  }, [messages.length]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !draft.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api<Message>(`${base}/${selected}/messages`, "POST", {
        body: draft,
      });
      setDraft("");
      await loadMessages(selected);
      await loadThreads();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const open = (id: string) =>
    navigate(`/${role}/messages/${encodeURIComponent(id)}`);

  return (
    <section className="chat-layout">
      <div className="chat-threads">
        <div className="section-heading">
          <h2>Диалоги</h2>
          <button
            disabled={busy}
            onClick={() => void loadThreads().catch((e) => setError(e.message))}
          >
            Обновить
          </button>
        </div>
        {loaded && threads.length === 0 && (
          <p className="empty">
            Диалогов пока нет. Они появляются после принятого приглашения или
            самостоятельного отклика — когда контакт открыт.
          </p>
        )}
        <ul className="chat-thread-list">
          {threads.map((t) => (
            <li key={t.counterpart_id}>
              <button
                className="chat-thread"
                aria-current={t.counterpart_id === selected ? "true" : undefined}
                onClick={() => open(t.counterpart_id)}
              >
                <span className="chat-thread-name">
                  {t.counterpart_name}
                  {t.unread > 0 && (
                    <span className="evidence"> · новых: {t.unread}</span>
                  )}
                </span>
                <span className="muted chat-thread-last">
                  {t.last_body ?? "Сообщений пока нет"}
                </span>
                {!t.can_send && (
                  <span className="muted">Контакт закрыт — только чтение</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="chat-pane">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!selected ? (
          <p className="empty">Выберите диалог слева.</p>
        ) : (
          <>
            <div className="section-heading">
              <h2>{current?.counterpart_name ?? "Диалог"}</h2>
            </div>
            <div
              className="chat-log"
              ref={log}
              role="log"
              aria-live="polite"
              aria-label="История сообщений"
              tabIndex={0}
            >
              {messages.length === 0 ? (
                <p className="empty">Напишите первое сообщение.</p>
              ) : (
                messages.map((m) => (
                  <div
                    key={m.id}
                    className={"chat-message " + (m.mine ? "mine" : "theirs")}
                  >
                    <p className="chat-body">{m.body}</p>
                    <p className="muted chat-meta">
                      {m.mine ? "Вы" : current?.counterpart_name} ·{" "}
                      {when(m.created_at)}
                      {m.mine && m.read ? " · прочитано" : ""}
                    </p>
                  </div>
                ))
              )}
            </div>
            {current && !current.can_send ? (
              <p className="muted" role="status">
                Контакт отозван или закрыт: новые сообщения отправить нельзя,
                история доступна для чтения.
              </p>
            ) : (
              <form className="chat-form" onSubmit={(e) => void send(e)}>
                <label htmlFor="chat-draft">Сообщение</label>
                <textarea
                  id="chat-draft"
                  value={draft}
                  maxLength={MAX_BODY}
                  rows={3}
                  onChange={(e) => setDraft(e.target.value)}
                />
                <div className="actions">
                  <span className="muted">
                    {draft.length}/{MAX_BODY} · не более 20 сообщений в час
                  </span>
                  <button className="primary" disabled={busy || !draft.trim()}>
                    Отправить
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </section>
  );
}

/** Число непрочитанных входящих сообщений для отметки в навигации; опрос раз в 30 секунд, пока вкладка видима. */
export function useUnreadMessages(role: "candidate" | "employer") {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const base = role === "candidate" ? "/candidate/chats" : "/company/chats";
    const refresh = () => {
      if (document.hidden) return;
      api<Thread[]>(base)
        .then((rows) => alive && setCount(rows.reduce((sum, t) => sum + t.unread, 0)))
        .catch(() => alive && setCount(0));
    };
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [role]);
  return count;
}
