import { uuid } from "./uuid";
import { useEffect, useRef, useState } from "react";
import { api, upload, downloadFile } from "./api";
import { navigate, useNavigationGuard } from "./routing";
import { specs } from "./product";
import { Pagination, usePagedItems } from "./pagination";
import { containDialogFocus } from "./dialog";

function taskCount(n: number) {
  const mod100 = n % 100,
    mod10 = n % 10;
  const word =
    mod100 >= 11 && mod100 <= 14
      ? "заданий"
      : mod10 === 1
        ? "задание"
        : mod10 >= 2 && mod10 <= 4
          ? "задания"
          : "заданий";
  return `${n} ${word}`;
}
function answerPresent(value: unknown) {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "string") return value.trim().length > 0;
  return value !== null && value !== undefined;
}

type TaskType =
  | "single_choice"
  | "multiple_choice"
  | "numeric"
  | "open_response"
  | "code";
type Check = { input: string; output: string; setup?: string };
type Task = {
  id: string;
  type: TaskType;
  title: string;
  prompt: string;
  skills: string[];
  weight: number;
  expected_minutes: number;
  options: { id: string; text: string }[];
  answer_key?: string[];
  partial_credit?: boolean;
  numeric_answer?: number | null;
  absolute_tolerance: number;
  relative_tolerance: number;
  unit: string;
  rubric: string;
  answer_limit: number;
  language: string;
  starter_code: string;
  examples: Check[];
  hidden_tests?: Check[];
  runtime_limits: { wall_seconds: number; memory_mb: number };
};
type Version = {
  id: string;
  bank_id: string;
  number: number;
  revision: number;
  state: string;
  title: string;
  specialization: string;
  grade: string;
  time_limit_minutes: number;
  tasks: Task[];
  validation_errors?: { path: string; message: string }[];
};
type PublicVersion = Version & { company_label: string; scope: string };
type Bank = {
  id: string;
  title: string;
  external_id: string;
  current_version: Version | null;
  versions: Version[];
};
type ImportResult = {
  id: string;
  valid: boolean;
  errors: { path: string; message: string }[];
  warnings?: string[];
  publication_errors?: { path: string; message: string }[];
  preview?: { title?: string; tasks?: Task[] };
  duplicate_bank_id?: string | null;
};
type Attempt = {
  id: string;
  version_id: string;
  revision: number;
  status: string;
  deadline: string;
  version: Version;
  answers: Record<string, unknown>;
  result?: Record<string, unknown> | null;
};
type Job = {
  id: string;
  status: string;
  task_id: string;
  result: {
    passed_tests: number;
    total_tests: number;
    score: number;
    runtime_version: string;
    status: string;
  } | null;
  error_code: string | null;
};
const labels: Record<TaskType, string> = {
  single_choice: "Один ответ",
  multiple_choice: "Несколько ответов",
  numeric: "Числовой ответ",
  open_response: "Открытый ответ",
  code: "Исполняемый код",
};
type TaskSuggestion = {
  task: Task;
  source: "llm" | "llm-mock";
  model: string;
  checks: string[];
  review_required: true;
};

function TaskGenerator({ kind, disabled, generate, approve }: {
  kind: TaskType;
  disabled: boolean;
  generate: (brief: string, skills: string[]) => Promise<TaskSuggestion>;
  approve: (task: Task) => void;
}) {
  const [brief, setBrief] = useState(""),
    [skill, setSkill] = useState("python"),
    [suggestion, setSuggestion] = useState<TaskSuggestion | null>(null),
    [accepted, setAccepted] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [refine, setRefine] = useState(""),
    [notes, setNotes] = useState<string[]>([]);
  const MAX_ROUNDS = 5;
  function refineWithAi() {
    if (!suggestion) return;
    const history = [...notes, refine.trim()];
    // Модель не хранит контекст: прежний черновик и все правки автора передаются в кратком описании.
    const extra = `
Предыдущий черновик: «${suggestion.task.prompt.slice(0, 350)}». Правки автора: ${history.join("; ")}.`;
    const next = (brief.trim().slice(0, 1500 - extra.length) + extra).slice(0, 1500);
    setError(""); setAccepted(false); setLoading(true);
    void generate(next, [skill]).then(result => { setSuggestion(result); setNotes(history); setRefine(""); })
      .catch(e => setError((e as Error).message))
      .finally(() => setLoading(false));
  }
  return <fieldset disabled={disabled} className="set-settings">
    <legend>Черновик с ИИ</legend>
    {kind === "code" ? <p>Исполняемый код создаётся вручную: для ИИ-генерации нужен отдельный прогон эталонного решения в VM. Остальные четыре типа поддерживаются.</p> : <>
      <p>Модель предлагает одно задание. Вы проверяете условие и эталон, затем добавляете его в черновик. Публикация выполняется отдельно.</p>
      <label>Контекст задания для ИИ
        <textarea value={brief} minLength={10} maxLength={1500}
          onChange={e => { setBrief(e.target.value); setSuggestion(null); setAccepted(false); setNotes([]); }} />
      </label>
      <label>Навык для ИИ
        <select value={skill} onChange={e => { setSkill(e.target.value); setSuggestion(null); setAccepted(false); }}>
          {Object.entries({ python: "Python", sql: "SQL", javascript: "JavaScript", html: "HTML", testing: "Тестирование", http: "HTTP", ux: "UX (метрики)", ui: "UI (визуал, a11y)" }).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <p className="muted">Передавайте только описание задачи без контактов и персональных данных. Генерация использует подключённую модель; её качество и сложность задания нужно проверить.</p>
      <button type="button" disabled={brief.trim().length < 10}
        onClick={() => {
          setError(""); setSuggestion(null); setAccepted(false); setNotes([]); setRefine("");
          setLoading(true);
          void generate(brief.trim(), [skill]).then(setSuggestion)
            .catch(e => setError((e as Error).message))
            .finally(() => setLoading(false));
        }}>Предложить задание с ИИ</button>
      {loading && <p role="status">Модель готовит предложение. Дождитесь ответа перед сменой раздела.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {suggestion && <div aria-label="Предложение ИИ">
        <p role="status">{suggestion.source === "llm-mock" ? "Демонстрационный образец, без вызова модели" : `Предложение модели ${suggestion.model}`}</p>
        <h4>{suggestion.task.title}</h4>
        <p className="multiline">{suggestion.task.prompt}</p>
        {suggestion.task.options.length > 0 && <ol>{suggestion.task.options.map(o => <li key={o.id}>{o.id}: {o.text}</li>)}</ol>}
        {suggestion.task.answer_key && suggestion.task.answer_key.length > 0 && <p>Авторский ключ: {suggestion.task.answer_key.join(", ")}</p>}
        {suggestion.task.type === "numeric" && <p>Числовой эталон: {suggestion.task.numeric_answer} {suggestion.task.unit}</p>}
        {suggestion.task.type === "open_response" && <p className="multiline">Рубрика: {suggestion.task.rubric}</p>}
        <p>Структура проверена сервером. Правильность ответа, однозначность и сложность модельного задания не подтверждены этими проверками.</p>
        {notes.length > 0 && <ol aria-label="История уточнений">{notes.map((note, index) => <li key={index}>Уточнение {index + 1}: {note}</li>)}</ol>}
        {notes.length < MAX_ROUNDS ? <div className="refine">
          <label>Уточнение для ИИ (например: «сделай сложнее», «замени числа», «добавь неверный вариант про NULL»)
            <textarea value={refine} maxLength={300} onChange={e => setRefine(e.target.value)} />
          </label>
          <button type="button" disabled={refine.trim().length < 5 || loading} onClick={refineWithAi}>Уточнить с ИИ</button>
        </div> : <p className="muted">Достигнут предел уточнений ({MAX_ROUNDS}). Отредактируйте задание вручную или начните с нового описания.</p>}
        <label className="check"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />Я проверил условие и эталон или рубрику</label>
        <button type="button" disabled={!accepted} onClick={() => {
          approve(suggestion.task); setSuggestion(null); setAccepted(false);
        }}>Добавить предложение в черновик</button>
      </div>}
    </>}
  </fieldset>;
}
const states: Record<string, string> = {
  draft: "Черновик",
  published: "Опубликован",
  archived: "Архив",
  in_progress: "В работе",
  pending_review: "Ожидает проверки",
  completed: "Завершён",
  queued: "В очереди",
  running: "Выполняется",
  passed: "Пройдено",
  failed: "Не пройдено",
  timeout: "Лимит времени",
  error: "Ошибка выполнения",
  infrastructure_error: "Исполнитель недоступен",
  wrong_answer: "Ответ не совпал с проверкой",
  runtime_error: "Ошибка исполнения решения",
  system_error: "Среда выполнения временно недоступна. Код пока не оценён",
  runtime_unavailable: "Среда выполнения временно недоступна. Попробуйте снова",
  unsupported_language: "Этот язык недоступен в текущей среде",
  output_limit: "Превышен допустимый объём вывода",
  memory_limit: "Превышен лимит памяти",
};
function makeTask(type: TaskType): Task {
  return {
    id: uuid(),
    type,
    title: "Новое задание",
    prompt: "",
    skills: ["python"],
    weight: 1,
    expected_minutes: 5,
    options: [
      { id: "a", text: "Вариант А" },
      { id: "b", text: "Вариант Б" },
      { id: "c", text: "Вариант В" },
    ],
    answer_key: type === "multiple_choice" ? ["a", "b"] : ["a"],
    numeric_answer: 0,
    absolute_tolerance: 0,
    relative_tolerance: 0,
    unit: "",
    rubric: "0: ответ отсутствует или не относится к условию. 50: указан проверяемый подход, но обоснование неполно. 100: дан полный ответ с проверяемым обоснованием.",
    answer_limit: 5000,
    language: "python",
    starter_code: "",
    examples: [{ input: "1", output: "1" }],
    hidden_tests: [{ input: "2", output: "2" }],
    runtime_limits: { wall_seconds: 3, memory_mb: 512 },
  };
}
function Feedback({ error, message }: { error: string; message: string }) {
  return (
    <div className="feedback" aria-live="polite">
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
function WorkflowSteps({
  label,
  steps,
}: {
  label: string;
  steps: {
    title: string;
    detail: string;
    state: "current" | "done" | "upcoming";
  }[];
}) {
  return (
    <ol className="workflow-steps" aria-label={label}>
      {steps.map((step) => (
        <li
          key={step.title}
          data-state={step.state}
          aria-current={step.state === "current" ? "step" : undefined}
        >
          <div>
            <strong>{step.title}</strong>
            <small>{step.detail}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}
function download(data: unknown, filename: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function BanksWorkspace({ bankId }: { bankId?: string }) {
  const [banks, setBanks] = useState<Bank[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [title, setTitle] = useState(""),
    [mode, setMode] = useState("list");
  const bankPages = usePagedItems(banks, 8);
  async function load() {
    setLoading(true);
    try {
      setBanks(await api("/company/banks"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const bank = banks.find((b) => b.id === bankId);
  async function create() {
    setBusy(true);
    setError("");
    try {
      const b = await api<Bank>("/company/banks", "POST", {
        title,
        specialization: "backend",
        grade: "junior",
        tasks: [],
      });
      await load();
      bankPages.setPage(1);
      navigate("/employer/banks/" + b.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (bankId && !bank && !loading)
    return (
      <section>
        <h2>Набор недоступен</h2>
        <p role="alert" className="error">
          {error || "Проверьте адрес. Набор другой компании недоступен."}
        </p>
        <button onClick={() => navigate("/employer/banks")}>Мои наборы</button>
        <button onClick={() => void load()}>Повторить загрузку</button>
      </section>
    );
  if (bankId && bank)
    return <BankEditor key={bank.id} bank={bank} onChange={load} />;
  return (
    <section className="banks-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Библиотека оценки</p>
          <h2>Наборы заданий</h2>
        </div>
        <button onClick={() => void load()} disabled={loading}>
          Обновить наборы
        </button>
      </div>
      <p className="lead">
        От условия до проверяемого результата. Создайте свой набор или загрузите
        готовые задания.
      </p>
      <p className="muted">
        Это практика с обратной связью от автора. Подтверждённый грейд кандидата
        определяется отдельно, в разделе «Оценка».
      </p>
      <Feedback error={error} message={message} />
      <div className="tabs">
        <button aria-pressed={mode === "list"} onClick={() => setMode("list")}>
          Мои наборы
        </button>
        <button
          aria-pressed={mode === "import"}
          onClick={() => setMode("import")}
        >
          Импорт материалов
        </button>
      </div>
      {mode === "import" ? (
        <ImportWizard
          onImported={async (b) => {
            await load();
            setMessage("Импорт подтверждён. Набор сохранён как черновик");
            navigate("/employer/banks/" + b.id);
          }}
        />
      ) : (
        <>
          <form
            className="inline-create"
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <label>
              Название нового набора
              <input
                required
                minLength={2}
                maxLength={120}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Например, Backend: первый практический шаг"
              />
            </label>
            <button className="primary" disabled={busy}>
              Создать набор
            </button>
          </form>
          {loading ? (
            <p role="status">Загрузка библиотеки…</p>
          ) : banks.length === 0 ? (
            <div className="empty">
              <h3>Здесь начнётся ваша библиотека</h3>
              <p>
                Назовите первый набор. В конструкторе доступны пять типов
                заданий, предпросмотр и публикация.
              </p>
            </div>
          ) : (
            <div className="bank-list">
              {bankPages.visibleItems.map((b) => {
                const v = b.current_version || b.versions[0];
                return (
                  <article className="record-row" key={b.id}>
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">
                          {states[v?.state] || "Набор"} · версия{" "}
                          {v?.number || 1}
                        </p>
                        <h3>{b.title}</h3>
                        <p className="muted">
                          {specs[v?.specialization]?.label || "Backend"} ·{" "}
                          {v?.grade === "middle" ? "Middle" : "Junior"} ·{" "}
                          {taskCount(v?.tasks.length || 0)}
                        </p>
                      </div>
                      <button
                        onClick={() => navigate("/employer/banks/" + b.id)}
                      >
                        Открыть конструктор
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          <Pagination label="Наборы заданий работодателя" total={banks.length} page={bankPages.page} pages={bankPages.pages} start={bankPages.start} end={bankPages.end} onPageChange={bankPages.setPage} />
        </>
      )}
    </section>
  );
}

const csvColumns = [
  "id",
  "type",
  "title",
  "prompt",
  "skills",
  "options",
  "answer_key",
  "numeric_answer",
  "absolute_tolerance",
  "relative_tolerance",
  "unit",
  "weight",
  "partial_credit",
  "bank_title",
  "external_id",
  "specialization",
  "grade",
  "csv_escape",
];
function csvHeaders(text: string) {
  const headers: string[] = [];
  let value = "",
    quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') {
        value += '"';
        i++;
      } else quoted = !quoted;
    } else if (ch === "," && !quoted) {
      headers.push(value);
      value = "";
    } else if ((ch === "\n" || ch === "\r") && !quoted) {
      headers.push(value);
      return headers;
    } else value += ch;
  }
  headers.push(value);
  return headers;
}
function ImportWizard({
  onImported,
}: {
  onImported: (bank: Bank) => void | Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null),
    [headers, setHeaders] = useState<string[]>([]),
    [mapping, setMapping] = useState<Record<string, string>>({}),
    [result, setResult] = useState<ImportResult | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const importErrors = usePagedItems(result?.errors || [], 8);
  const importWarnings = usePagedItems(result?.warnings || [], 8);
  const importTasks = usePagedItems(result?.preview?.tasks || [], 8);
  const fileEpoch = useRef(0);
  async function check() {
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await upload(
          "/company/bank-imports/dry-run?filename=" +
            encodeURIComponent(file.name) +
            (headers.length
              ? "&column_mapping=" + encodeURIComponent(JSON.stringify(mapping))
              : ""),
          file,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!result) return;
    setBusy(true);
    try {
      await onImported(
        await api(
          "/company/bank-imports/" + result.id + "/confirm",
          "POST",
          {},
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="import-wizard">
      <h3>Сначала проверка, затем сохранение</h3>
      <WorkflowSteps
        label="Этапы импорта"
        steps={[
          {
            title: "Выберите источник",
            detail: "Файл и сопоставление колонок CSV",
            state: file ? "done" : "current",
          },
          {
            title: "Проверьте содержимое",
            detail: result?.valid
              ? "Проверка пройдена; публикация проверяется отдельно"
              : "Ошибки и предпросмотр до сохранения",
            state: result?.valid ? "done" : file ? "current" : "upcoming",
          },
          {
            title: "Сохраните черновик",
            detail: "Явное подтверждение; затем правка и публикация",
            state: result?.valid ? "current" : "upcoming",
          },
        ]}
      />
      <p>
        JSON — полный набор. CSV — выборы и числовые ответы. ZIP — manifest и
        текстовые fixtures. PDF/DOCX — только извлечение условий в черновик:
        ключи и критерии нужно задать вручную.
      </p>
      <p className="muted">
        Файл не публикуется автоматически. Не загружайте персональные данные и
        секреты. Файл — до 2 МиБ; содержимое ZIP — до 4 МиБ и 50 файлов.
      </p>
      <Feedback error={error} message="" />
      <form
        className="inline-create"
        onSubmit={(e) => {
          e.preventDefault();
          void check();
        }}
      >
        <label>
          Файл готовых заданий
          <input
            type="file"
            accept=".json,.csv,.zip,.pdf,.docx"
            required
            disabled={busy}
            onChange={(e) => {
              const epoch = ++fileEpoch.current;
              const chosen = e.target.files?.[0] || null;
              setFile(chosen);
              setResult(null);
              setHeaders([]);
              setMapping({});
              setError("");
              if (chosen && chosen.size > 2 * 1024 * 1024) {
                setError("Максимальный размер файла — 2 МБ");
                setFile(null);
                return;
              }
              if (chosen && /\.csv$/i.test(chosen.name))
                void chosen
                  .slice(0, 65536)
                  .text()
                  .then((text) => {
                    if (epoch !== fileEpoch.current) return;
                    const incoming = csvHeaders(text);
                    setHeaders(incoming);
                    setMapping(
                      Object.fromEntries(
                        incoming.map((h) => [
                          h,
                          csvColumns.includes(h) ? h : "",
                        ]),
                      ),
                    );
                  })
                  .catch(() => {
                    if (epoch === fileEpoch.current)
                      setError("Не удалось прочитать заголовки CSV");
                  });
            }}
          />
        </label>
        <button disabled={busy || !file} className="primary">
          Проверить файл
        </button>
      </form>
      {headers.length > 0 && (
        <div className="csv-mapping">
          <h4>Сопоставление колонок CSV</h4>
          <p className="muted">
            Обязательны id, type, title, prompt и skills. Несколько навыков
            разделяются точкой с запятой; options и answer_key содержат JSON.
            Строки и значения проверяет сервер.
          </p>
          <div className="form-grid">
            {headers.map((header, i) => (
              <label key={i}>
                Колонка: {header || "Без названия"}
                <select
                  aria-label={"Сопоставление: " + header}
                  disabled={busy}
                  value={mapping[header] || ""}
                  onChange={(e) => {
                    setMapping((m) => ({ ...m, [header]: e.target.value }));
                    setResult(null);
                  }}
                >
                  {["", ...csvColumns].map((target) => (
                    <option key={target} value={target}>
                      {target || "Пропустить колонку"}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </div>
      )}
      {busy && <p role="status">Обработка файла…</p>}
      {result && (
        <div className="result">
          <p className="eyebrow">Результат предварительной проверки</p>
          <h3>
            {result.valid
              ? "Можно сохранить черновик"
              : "Исправьте ошибки в источнике"}
          </h3>
          {result.errors.length > 0 && (
            <ul className="validation-list">
              {importErrors.visibleItems.map((e, i) => (
                <li key={i}>
                  <code>{e.path}</code> — {e.message}
                </li>
              ))}
            </ul>
          )}
          <Pagination label="Ошибки импорта заданий" total={result.errors.length} page={importErrors.page} pages={importErrors.pages} start={importErrors.start} end={importErrors.end} onPageChange={importErrors.setPage} />
          {importWarnings.visibleItems.map((warning, i) => (
            <p className="muted" key={i}>
              {warning}
            </p>
          ))}
          <Pagination label="Предупреждения импорта заданий" total={result.warnings?.length || 0} page={importWarnings.page} pages={importWarnings.pages} start={importWarnings.start} end={importWarnings.end} onPageChange={importWarnings.setPage} />
          {result.publication_errors &&
            result.publication_errors.length > 0 && (
              <p className="muted">
                Для публикации дополните {result.publication_errors.length}{" "}
                полей в конструкторе.
              </p>
            )}
          {result.preview && (
            <>
              <p>{result.preview.title}</p>
              <p>{taskCount(result.preview.tasks?.length || 0)}</p>
              {importTasks.visibleItems.map((t, i) => (
                <p key={t.id || i}>
                  {(importTasks.page - 1) * importTasks.pageSize + i + 1}. {t.title} · {labels[t.type]}
                </p>
              ))}
              <Pagination label="Предпросмотр импортируемых заданий" total={result.preview.tasks?.length || 0} page={importTasks.page} pages={importTasks.pages} start={importTasks.start} end={importTasks.end} onPageChange={importTasks.setPage} />
            </>
          )}
          {result.duplicate_bank_id && (
            <p>
              Этот источник уже импортирован. При подтверждении будет создана
              новая версия существующего набора. Повторное подтверждение этого
              импорта не создаёт дубликат.
            </p>
          )}
          <button
            className="primary"
            disabled={!result.valid || busy}
            onClick={() => void confirm()}
          >
            Подтвердить импорт
          </button>
        </div>
      )}
    </div>
  );
}

function BankEditor({
  bank,
  onChange,
}: {
  bank: Bank;
  onChange: () => Promise<void>;
}) {
  const latest = bank.current_version || bank.versions[0];
  const [version, setVersion] = useState<Version>(latest),
    [selected, setSelected] = useState(0),
    [type, setType] = useState<TaskType>("single_choice"),
    [tab, setTab] = useState("edit"),
    [previewVersion, setPreviewVersion] = useState<Version | null>(null),
    [navigating, setNavigating] = useState(false),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [generating, setGenerating] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const editable = version.state === "draft",
    task = version.tasks[selected];
  const taskPages = usePagedItems(version.tasks, 10);
  const previewTasks = (previewVersion || version).tasks;
  const previewPages = usePagedItems(previewTasks, 8);
  const validationErrors = version.validation_errors || [];
  const validationPages = usePagedItems(validationErrors, 8);
  const currentVersion = useRef(version);
  currentVersion.current = version;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const changeGeneration = useRef(0),
    pendingSave = useRef<Promise<Version> | null>(null);
  const change = (v: Version) => {
    changeGeneration.current++;
    setVersion(v);
    setDirty(true);
    setMessage("Есть несохранённые изменения");
  };
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current || pendingSave.current) {
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const path = `/company/banks/${bank.id}/versions/${version.id}`;
  async function save() {
    while (pendingSave.current) await pendingSave.current;
    const current = currentVersion.current,
      generation = changeGeneration.current;
    if (!dirtyRef.current) return current;
    const request = api<Version>(
      `/company/banks/${bank.id}/versions/${current.id}`,
      "PATCH",
      {
        revision: current.revision,
        title: current.title,
        specialization: current.specialization,
        grade: current.grade,
        time_limit_minutes: current.time_limit_minutes,
        tasks: current.tasks,
      },
    );
    pendingSave.current = request;
    try {
      const v = await request;
      if (generation === changeGeneration.current) {
        currentVersion.current = v;
        setVersion(v);
        dirtyRef.current = false;
        setDirty(false);
        setMessage("Черновик сохранён на сервере");
      } else {
        const updated = { ...currentVersion.current, revision: v.revision };
        currentVersion.current = updated;
        setVersion(updated);
      }
      return v;
    } finally {
      pendingSave.current = null;
    }
  }
  useEffect(() => {
    if (!dirty || !editable || busy || error) return;
    const timer = setTimeout(() => {
      void save().catch((e) => setError(e.message));
    }, 1500);
    return () => clearTimeout(timer);
  }, [version, dirty, busy]);
  useNavigationGuard(async () => {
    if (generating) {
      setMessage("Дождитесь ответа модели перед переходом в другой раздел.");
      return false;
    }
    setNavigating(true);
    try {
      do {
        await save();
      } while (dirtyRef.current && currentVersion.current.state === "draft");
      return true;
    } catch (e) {
      setError(
        (e as Error).message +
          ". Переход отменён, ваши правки остаются в форме.",
      );
      return false;
    } finally {
      setNavigating(false);
    }
  });
  async function run(fn: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setError("");
    try {
      await fn();
      if (success) setMessage(success);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function action(name: "publish" | "fork" | "archive") {
    let current = version;
    if (dirty && editable) current = await save();
    const v = await api<Version>(
      path + "/" + name,
      "POST",
      name === "publish" ? { revision: current.revision } : {},
    );
    setVersion(v);
    setDirty(false);
    await onChange();
  }
  function updateTask(t: Task) {
    change({
      ...version,
      tasks: version.tasks.map((value, i) => (i === selected ? t : value)),
    });
  }
  function move(delta: number) {
    const next = selected + delta;
    if (next < 0 || next >= version.tasks.length) return;
    const tasks = [...version.tasks];
    [tasks[selected], tasks[next]] = [tasks[next], tasks[selected]];
    change({ ...version, tasks });
    setSelected(next);
    taskPages.setPage(Math.floor(next / taskPages.pageSize) + 1);
    setMessage(`Задание перемещено на позицию ${next + 1}`);
  }
  async function suggest(brief: string, skills: string[]) {
    setBusy(true);
    setGenerating(true);
    try {
      const current = await save();
      const result = await api<TaskSuggestion>(
        `/company/banks/${bank.id}/versions/${current.id}/suggest-task`, "POST", {
          revision: current.revision, kind: type, specialization: current.specialization,
          grade: current.grade, skills, brief,
        });
      const latest = currentVersion.current;
      if (latest.id !== current.id || latest.state !== "draft" || latest.specialization !== current.specialization || latest.grade !== current.grade) {
        throw new Error("Параметры набора изменились. Повторите генерацию для актуального черновика");
      }
      return result;
    } finally { setBusy(false); setGenerating(false); }
  }
  return (
    <section className="bank-editor" aria-busy={busy || navigating}>
      <button
        className="text-action"
        onClick={() => {
          if (!dirty || window.confirm("Уйти без сохранения правок?"))
            navigate("/employer/banks");
        }}
      >
        Все наборы
      </button>
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            Конструктор · {states[version.state]} · версия {version.number}
          </p>
          <h2>{version.title}</h2>
        </div>
        <label>
          Открыть версию
          <select
            aria-label="Открыть версию"
            value={version.id}
            disabled={busy}
            onChange={(e) => {
              const id = e.target.value;
              void run(async () => {
                await save();
                changeGeneration.current++;
                const chosen = bank.versions.find((v) => v.id === id)!;
                currentVersion.current = chosen;
                setVersion(chosen);
                setDirty(false);
                setSelected(0);
                taskPages.setPage(1);
                previewPages.setPage(1);
                setPreviewVersion(null);
              });
            }}
          >
            {bank.versions.map((v) => (
              <option value={v.id} key={v.id}>
                {v.number} · {states[v.state]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {editable && (
        <WorkflowSteps
          label="Путь набора к публикации"
          steps={[
            {
              title: "Составьте задания",
              detail: "Условия, навыки, ответы и критерии",
              state: editable && tab === "edit" ? "current" : "upcoming",
            },
            {
              title: "Посмотрите как кандидат",
              detail: "Предпросмотр без ответов и скрытых тестов",
              state: editable && tab === "preview" ? "current" : "upcoming",
            },
            {
              title: "Опубликуйте версию",
              detail: editable
                ? "Проверка сервера; версия станет неизменяемой"
                : "Для изменений создайте новую черновую версию",
              state: editable ? "upcoming" : "done",
            },
          ]}
        />
      )}
      <Feedback error={error} message={message} />
      {editable &&
        version.validation_errors &&
        version.validation_errors.length > 0 && (
          <details className="publication-validation">
            <summary>
              До публикации: {version.validation_errors.length} полей требуют
              внимания
            </summary>
            <ul>
              {validationPages.visibleItems.map((e, i) => (
                <li key={i}>
                  {e.path}: {e.message}
                </li>
              ))}
            </ul>
            <Pagination label={`Ошибки проверки набора «${bank.title}»`} total={validationErrors.length} page={validationPages.page} pages={validationPages.pages} start={validationPages.start} end={validationPages.end} onPageChange={validationPages.setPage} />
          </details>
        )}
      <div className="editor-actions">
        <button
          disabled={!editable || busy || !dirty}
          onClick={() => void run(save)}
        >
          Сохранить черновик
        </button>
        <button
          disabled={!editable || busy || navigating}
          className="primary"
          onClick={() =>
            void run(
              () => action("publish"),
              "Версия опубликована. Её задания и ключи неизменяемы",
            )
          }
        >
          Опубликовать набор
        </button>
        <button
          disabled={busy}
          onClick={() =>
            void run(() => action("fork"), "Создана новая черновая версия")
          }
        >
          Копировать в новую версию
        </button>
        <button
          disabled={editable || busy || version.state === "archived"}
          onClick={() =>
            void run(() => action("archive"), "Версия архивирована")
          }
        >
          Архивировать
        </button>
        <button
          disabled={busy || dirty}
          onClick={() =>
            void run(async () =>
              download(
                await api(`/company/banks/${bank.id}/export`),
                "fsp-bank.json",
              ),
            )
          }
        >
          Экспорт JSON
        </button>
        <button
          disabled={busy || dirty}
          onClick={() =>
            void run(() =>
              downloadFile(
                `/company/banks/${bank.id}/export?format=csv`,
                "fsp-bank.csv",
              ),
            )
          }
        >
          Экспорт CSV
        </button>
        <button
          disabled={busy || dirty}
          onClick={() =>
            void run(() =>
              downloadFile(
                `/company/banks/${bank.id}/export?format=zip`,
                "fsp-bank.zip",
              ),
            )
          }
        >
          Экспорт ZIP
        </button>
      </div>
      <div className="tabs">
        <button aria-pressed={tab === "edit"} disabled={busy} onClick={() => setTab("edit")}>
          Редактор
        </button>
        <button
          aria-pressed={tab === "preview"}
          disabled={busy}
          onClick={() =>
            void run(async () => {
              if (dirty) await save();
              setPreviewVersion(await api<Version>(path + "/preview"));
              setTab("preview");
            })
          }
        >
          Предпросмотр кандидата
        </button>
        <button
          aria-pressed={tab === "review"}
          disabled={busy}
          onClick={() => setTab("review")}
        >
          Ручная проверка
        </button>
      </div>
      {tab === "review" ? (
        <ManualReview bankId={bank.id} />
      ) : tab === "preview" ? (
        <div className="task-preview">
          <h3>Так выглядит версия для кандидата</h3>
          <p className="muted">
            Ключи, числовые эталоны и скрытые проверки здесь не показываются.
          </p>
          {(previewVersion || version).tasks.length === 0 ? (
            <p>Добавьте первое задание в редакторе.</p>
          ) : (
            previewPages.visibleItems.map((t, i) => (
              <TaskAnswer
                key={t.id}
                task={t}
                index={(previewPages.page - 1) * previewPages.pageSize + i}
                value={undefined}
                onChange={() => {}}
                preview
              />
            ))
          )}
          <Pagination label={`Предпросмотр заданий набора «${bank.title}»`} total={previewTasks.length} page={previewPages.page} pages={previewPages.pages} start={previewPages.start} end={previewPages.end} onPageChange={previewPages.setPage} />
        </div>
      ) : (
        <>
          <fieldset
            disabled={!editable || busy || navigating}
            className="set-settings"
          >
            <legend>Параметры набора</legend>
            <div className="form-grid">
              <label>
                Название набора
                <input
                  required
                  maxLength={120}
                  value={version.title}
                  onChange={(e) =>
                    change({ ...version, title: e.target.value })
                  }
                />
              </label>
              <label>
                Направление набора
                <select
                  value={version.specialization}
                  onChange={(e) =>
                    change({ ...version, specialization: e.target.value })
                  }
                >
                  {Object.entries(specs).map(([id, s]) => (
                    <option key={id} value={id}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Уровень набора
                <select
                  value={version.grade}
                  onChange={(e) =>
                    change({ ...version, grade: e.target.value })
                  }
                >
                  <option value="junior">Junior</option>
                  <option value="middle">Middle</option>
                </select>
              </label>
              <label>
                Время набора, минут
                <input
                  type="number"
                  min={1}
                  max={240}
                  value={version.time_limit_minutes}
                  onChange={(e) =>
                    change({
                      ...version,
                      time_limit_minutes: Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
          </fieldset>
          <div className="constructor-grid">
            <aside className="task-outline">
              <h3>Структура</h3>
              <ol>
                {taskPages.visibleItems.map((t, i) => {
                  const taskIndex = (taskPages.page - 1) * taskPages.pageSize + i;
                  return (
                  <li key={t.id}>
                    <button
                      aria-pressed={selected === taskIndex}
                      onClick={() => setSelected(taskIndex)}
                    >
                      {taskIndex + 1}. {t.title}
                      <small>{labels[t.type]}</small>
                    </button>
                  </li>
                  );
                })}
              </ol>
              <Pagination label={`Структура заданий набора «${bank.title}»`} total={version.tasks.length} page={taskPages.page} pages={taskPages.pages} start={taskPages.start} end={taskPages.end} onPageChange={taskPages.setPage} />
              {editable && (
                <>
                  <label>
                    Тип нового задания
                    <select
                      value={type}
                      disabled={busy}
                      onChange={(e) => setType(e.target.value as TaskType)}
                    >
                      {Object.entries(labels).map(([id, label]) => (
                        <option value={id} key={id}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="muted">Выбор ответа и число проверяются автоматически. Открытый ответ оценивается автором по рубрике. Код выполняется в отдельной VM.</p>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => {
                      change({
                        ...version,
                        tasks: [...version.tasks, makeTask(type)],
                      });
                      setSelected(version.tasks.length);
                      taskPages.setPage(Math.floor(version.tasks.length / taskPages.pageSize) + 1);
                    }}
                  >
                    Добавить задание
                  </button>
                </>
              )}
            </aside>
            <div className="task-editor">
              {task ? (
                <>
                  <div className="section-heading">
                    <h3>
                      Задание {selected + 1} / {version.tasks.length}
                    </h3>
                    {editable && (
                      <div className="editor-actions">
                        <button
                          disabled={selected === 0}
                          onClick={() => move(-1)}
                        >
                          Выше
                        </button>
                        <button
                          disabled={selected === version.tasks.length - 1}
                          onClick={() => move(1)}
                        >
                          Ниже
                        </button>
                        <button
                          onClick={() => {
                            change({
                              ...version,
                              tasks: version.tasks.filter(
                                (_, i) => i !== selected,
                              ),
                            });
                            setSelected(Math.max(0, selected - 1));
                          }}
                        >
                          Убрать из черновика
                        </button>
                      </div>
                    )}
                  </div>
                  <fieldset disabled={!editable || busy || navigating}>
                    <TaskEditor task={task} onChange={updateTask} />
                  </fieldset>
                </>
              ) : (
                <div className="empty">
                  <h3>Первое задание задаёт тон</h3>
                  <p>
                    Выберите тип в структуре. Публикация проверяет условия,
                    ключи, навыки и кодовые проверки на сервере.
                  </p>
                </div>
              )}
            </div>
          </div>
          {editable && <TaskGenerator
            key={`${version.id}:${type}:${version.specialization}:${version.grade}`}
            kind={type} disabled={busy || navigating} generate={suggest}
            approve={generated => {
              const current = currentVersion.current;
              if (current.state !== "draft") return;
              const task = { ...generated, id: uuid() };
              change({ ...current, tasks: [...current.tasks, task] });
              setSelected(current.tasks.length);
              taskPages.setPage(Math.floor(current.tasks.length / taskPages.pageSize) + 1);
            }} />}
        </>
      )}
    </section>
  );
}
function TaskEditor({
  task: t,
  onChange,
}: {
  task: Task;
  onChange: (task: Task) => void;
}) {
  const change = <K extends keyof Task>(key: K, value: Task[K]) =>
    onChange({ ...t, [key]: value });
  return (
    <div className="form-grid task-fields">
      <label className="full">
        Название задания
        <input
          maxLength={120}
          value={t.title}
          onChange={(e) => change("title", e.target.value)}
        />
      </label>
      <label className="full">
        Условие задания
        <textarea
          rows={6}
          maxLength={12000}
          value={t.prompt}
          onChange={(e) => change("prompt", e.target.value)}
        />
      </label>
      <label>
        Проверяемые навыки
        <select
          multiple
          value={t.skills}
          onChange={(e) =>
            change(
              "skills",
              [...e.target.selectedOptions].map((o) => o.value),
            )
          }
        >
          {["python", "javascript", "html", "sql", "http", "testing", "ux", "ui"].map(
            (s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ),
          )}
        </select>
        <small>Ctrl / Command для нескольких навыков</small>
      </label>
      <label>
        Вес задания
        <input
          type="number"
          min={1}
          max={100}
          value={t.weight}
          onChange={(e) => change("weight", Number(e.target.value))}
        />
      </label>
      <label>
        Ожидаемое время, минут
        <input
          type="number"
          min={1}
          max={120}
          value={t.expected_minutes}
          onChange={(e) => change("expected_minutes", Number(e.target.value))}
        />
      </label>
      {(t.type === "single_choice" || t.type === "multiple_choice") && (
        <div className="full">
          <h4>Варианты и правильные ответы</h4>
          {t.type === "multiple_choice" && (
            <label className="check">
              <input
                type="checkbox"
                checked={t.partial_credit || false}
                onChange={(e) => change("partial_credit", e.target.checked)}
              />
              Частичный балл: правильные выборы минус ошибочные
            </label>
          )}
          <p className="muted">
            Без частичного балла требуется точное множество ответов.
          </p>
          {t.options.map((o, i) => (
            <div className="option-editor" key={o.id}>
              <input
                aria-label={`Текст варианта ${i + 1}`}
                value={o.text}
                onChange={(e) =>
                  change(
                    "options",
                    t.options.map((item, j) =>
                      j === i ? { ...item, text: e.target.value } : item,
                    ),
                  )
                }
              />
              <label className="check">
                <input
                  type={t.type === "single_choice" ? "radio" : "checkbox"}
                  name="author-key"
                  checked={t.answer_key?.includes(o.id) || false}
                  onChange={() =>
                    change(
                      "answer_key",
                      t.type === "single_choice"
                        ? [o.id]
                        : t.answer_key?.includes(o.id)
                          ? t.answer_key.filter((v) => v !== o.id)
                          : [...(t.answer_key || []), o.id],
                    )
                  }
                />
                Правильный {i + 1}
              </label>
              <button
                type="button"
                disabled={t.options.length <= 2}
                onClick={() =>
                  onChange({
                    ...t,
                    options: t.options.filter((_, j) => j !== i),
                    answer_key: t.answer_key?.filter((id) => id !== o.id),
                  })
                }
              >
                Убрать вариант {i + 1}
              </button>
            </div>
          ))}
          <button
            onClick={() =>
              change("options", [
                ...t.options,
                { id: uuid(), text: "" },
              ])
            }
          >
            Добавить вариант
          </button>
        </div>
      )}
      {t.type === "numeric" && (
        <>
          <label>
            Эталонное число
            <input
              type="number"
              step="any"
              value={t.numeric_answer ?? ""}
              onChange={(e) => change("numeric_answer", Number(e.target.value))}
            />
          </label>
          <label>
            Единица измерения
            <input
              value={t.unit}
              onChange={(e) => change("unit", e.target.value)}
            />
          </label>
          <label>
            Абсолютная погрешность
            <input
              type="number"
              min={0}
              step="any"
              value={t.absolute_tolerance}
              onChange={(e) =>
                change("absolute_tolerance", Number(e.target.value))
              }
            />
          </label>
          <label>
            Относительная погрешность
            <input
              type="number"
              min={0}
              max={1}
              step="any"
              value={t.relative_tolerance}
              onChange={(e) =>
                change("relative_tolerance", Number(e.target.value))
              }
            />
          </label>
        </>
      )}
      {t.type === "open_response" && (
        <>
          <label className="full">
            Рубрика ручной проверки
            <textarea
              rows={4}
              value={t.rubric}
              onChange={(e) => change("rubric", e.target.value)}
            />
          </label>
          <label>
            Лимит символов ответа
            <input
              type="number"
              min={100}
              max={16000}
              value={t.answer_limit}
              onChange={(e) => change("answer_limit", Number(e.target.value))}
            />
          </label>
        </>
      )}
      {t.type === "code" && (
        <>
          <label>
            Язык исполнения
            <select
              value={t.language}
              onChange={(e) => change("language", e.target.value)}
            >
              <option value="python">Python</option>
              <option value="javascript">JavaScript</option>
              <option value="sql">SQL</option>
            </select>
          </label>
          <label>
            Лимит выполнения, секунд
            <input
              type="number"
              min={1}
              max={3}
              value={t.runtime_limits.wall_seconds}
              onChange={(e) =>
                change("runtime_limits", {
                  ...t.runtime_limits,
                  wall_seconds: Number(e.target.value),
                })
              }
            />
          </label>
          <label className="full">
            Стартовый код
            <textarea
              className="code-editor"
              rows={7}
              spellCheck={false}
              value={t.starter_code}
              onChange={(e) => change("starter_code", e.target.value)}
            />
          </label>
          <div className="full">
            <Checks
              title="Открытые примеры"
              checks={t.examples}
              onChange={(v) => change("examples", v)}
            />
            <Checks
              title="Скрытые проверки"
              checks={t.hidden_tests || []}
              onChange={(v) => change("hidden_tests", v)}
            />
          </div>
          <p className="muted full">
            Python/JavaScript читают stdin и печатают stdout. SQL выполняет
            SELECT по fixtures; эталонный выход — JSON массив строк, например
            [[2]]. Скрытые проверки доступны только автору. Исполнение отделено
            от API.
          </p>
        </>
      )}
    </div>
  );
}
function Checks({
  title,
  checks,
  onChange,
}: {
  title: string;
  checks: Check[];
  onChange: (checks: Check[]) => void;
}) {
  return (
    <div className="checks-editor">
      <h4>{title}</h4>
      {checks.map((c, i) => (
        <div className="form-grid" key={i}>
          <label>
            {title}: вход {i + 1}
            <textarea
              className="code-editor"
              rows={2}
              value={c.input}
              onChange={(e) =>
                onChange(
                  checks.map((v, j) =>
                    i === j ? { ...v, input: e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <label>
            {title}: выход {i + 1}
            <textarea
              className="code-editor"
              rows={2}
              value={c.output}
              onChange={(e) =>
                onChange(
                  checks.map((v, j) =>
                    i === j ? { ...v, output: e.target.value } : v,
                  ),
                )
              }
            />
          </label>
          <label className="full">
            {title}: SQL fixtures {i + 1}
            <textarea
              className="code-editor"
              rows={3}
              value={c.setup || ""}
              onChange={(e) =>
                onChange(
                  checks.map((v, j) =>
                    i === j ? { ...v, setup: e.target.value } : v,
                  ),
                )
              }
            />
            <small>
              Для SQL — CREATE / INSERT в отдельной SQLite БД. Для
              Python/JavaScript оставьте пустым.
            </small>
          </label>
          <button onClick={() => onChange(checks.filter((_, j) => j !== i))}>
            Убрать проверку {i + 1}
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...checks, { input: "", output: "" }])}>
        Добавить: {title.toLowerCase()}
      </button>
    </div>
  );
}

export function BankAssessment({ attemptId }: { attemptId?: string }) {
  const [banks, setBanks] = useState<PublicVersion[]>([]),
    [history, setHistory] = useState<Attempt[]>([]),
    [attempt, setAttempt] = useState<Attempt | null>(null),
    [answers, setAnswers] = useState<Record<string, unknown>>({}),
    [loading, setLoading] = useState(true),
    [navigating, setNavigating] = useState(false),
    [busy, setBusy] = useState(false),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [jobs, setJobs] = useState<Record<string, Job>>({}),
    [remaining, setRemaining] = useState(0),
    [confirmFinish, setConfirmFinish] = useState(false),
    [unsentAnswers, setUnsentAnswers] = useState<Record<string, unknown> | null>(null);
  const historyPages = usePagedItems(history, 8);
  const publicBankPages = usePagedItems(banks, 8);
  const taskPages = usePagedItems(attempt?.version.tasks || [], 1);
  const generation = useRef(0),
    answersRef = useRef(answers);
  answersRef.current = answers;
  const attemptRef = useRef(attempt);
  attemptRef.current = attempt;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const pendingSave = useRef<Promise<Attempt> | null>(null);
  const routeEpoch = useRef(0),
    routeController = useRef<AbortController | null>(null),
    finishDialog = useRef<HTMLDialogElement | null>(null),
    finishTrigger = useRef<HTMLButtonElement | null>(null),
    taskPanel = useRef<HTMLFieldSetElement | null>(null);
  function closeFinish() {
    if (finishDialog.current?.open) finishDialog.current.close();
    setConfirmFinish(false);
    requestAnimationFrame(() => finishTrigger.current?.focus());
  }
  useEffect(() => {
    const dialog = finishDialog.current;
    if (confirmFinish && dialog && !dialog.open) dialog.showModal();
    if (!confirmFinish && dialog?.open) dialog.close();
  }, [confirmFinish]);
  useEffect(() => {
    const epoch = ++routeEpoch.current,
      controller = new AbortController();
    routeController.current = controller;
    const active = () =>
      routeEpoch.current === epoch && !controller.signal.aborted;
    setJobs({});
    setAnswers({});
    setDirty(false);
    setRemaining(0);
    setLoading(true);
    setAttempt(null);
    taskPages.setPage(1);
    closeFinish();
    setUnsentAnswers(null);
    setError("");
    if (attemptId) {
      void api<Attempt>(
        "/candidate/bank-attempts/" + attemptId,
        "GET",
        undefined,
        {},
        controller.signal,
      )
        .then((a) => {
          if (!active()) return;
          setAttempt(a);
          setAnswers(a.answers);
          setDirty(false);
        })
        .catch((e) => {
          if (active()) setError(e.message);
        })
        .finally(() => {
          if (active()) setLoading(false);
        });
    } else {
      void Promise.all([
        api<PublicVersion[]>(
          "/candidate/banks",
          "GET",
          undefined,
          {},
          controller.signal,
        ).then((v) => {
          if (active()) setBanks(v);
        }),
        api<Attempt[]>(
          "/candidate/bank-attempts",
          "GET",
          undefined,
          {},
          controller.signal,
        ).then((v) => {
          if (active()) setHistory(v);
        }),
      ])
        .catch((e) => {
          if (active()) setError(e.message);
        })
        .finally(() => {
          if (active()) setLoading(false);
        });
    }
    return () => controller.abort();
  }, [attemptId]);
  useEffect(() => {
    if (!attempt) return;
    const tick = () =>
      setRemaining(
        Math.max(
          0,
          Math.ceil((new Date(attempt.deadline).getTime() - Date.now()) / 1000),
        ),
      );
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [attempt?.deadline]);
  async function save() {
    while (pendingSave.current) await pendingSave.current;
    const current = attemptRef.current;
    if (!current || !dirtyRef.current || current.status !== "in_progress")
      return current;
    if (Date.now() >= new Date(current.deadline).getTime()) {
      setRemaining(0);
      return current;
    }
    const currentGeneration = generation.current;
    const request = api<Attempt>(
      "/candidate/bank-attempts/" + current.id,
      "PATCH",
      { revision: current.revision, answers: answersRef.current },
    );
    pendingSave.current = request;
    try {
      const a = await request;
      attemptRef.current = a;
      setAttempt(a);
      if (generation.current === currentGeneration) {
        dirtyRef.current = false;
        setDirty(false);
        setMessage("Ответы сохранены на сервере");
      }
      return a;
    } finally {
      pendingSave.current = null;
    }
  }
  useEffect(() => {
    if (!dirty || busy || remaining === 0 || error) return;
    const timer = setTimeout(() => {
      if (attempt && Date.now() >= new Date(attempt.deadline).getTime()) {
        setRemaining(0);
        return;
      }
      void save().catch((e) => setError((e as Error).message));
    }, 850);
    return () => clearTimeout(timer);
  }, [answers, dirty, busy, attempt?.revision]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirtyRef.current || pendingSave.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  useNavigationGuard(async () => {
    setNavigating(true);
    try {
      const expired = () => Boolean(attemptRef.current && Date.now() >= new Date(attemptRef.current.deadline).getTime());
      const leaveExpired = () => {
        const leave = window.confirm(
          "Время практики закончилось. Несохранённый локальный ответ не будет отправлен; серверный черновик останется в попытке. Перейти дальше?",
        );
        if (!leave) setError("Переход отменён. Ответ остаётся в открытой форме.");
        return leave;
      };
      if (expired() && dirtyRef.current) return leaveExpired();
      if (!expired())
        do {
          await save();
        } while (
          dirtyRef.current &&
          attemptRef.current?.status === "in_progress" &&
          !expired()
        );
      // Срок может закончиться, пока ждём предыдущий сетевой запрос.
      if (expired() && dirtyRef.current) return leaveExpired();
      return true;
    } catch (e) {
      setError(
        (e as Error).message + ". Переход отменён, ответы остаются в форме.",
      );
      return false;
    } finally {
      setNavigating(false);
    }
  });
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function start(v: PublicVersion) {
    const a = await api<Attempt>(
      `/candidate/banks/${v.bank_id}/attempts`,
      "POST",
      { version_id: v.id },
    );
    navigate("/candidate/practice/" + a.id);
  }
  async function submit() {
    if (!attempt) return;
    const expired = remaining === 0 || Date.now() >= new Date(attempt.deadline).getTime();
    const localUnsaved = expired && dirtyRef.current
      ? { ...answersRef.current }
      : null;
    const a = expired ? attemptRef.current || attempt : (await save()) || attemptRef.current || attempt;
    const completed = await api<Attempt>(
      `/candidate/bank-attempts/${a.id}/submit`,
      "POST",
      { revision: a.revision },
    );
    attemptRef.current = completed;
    setAttempt(completed);
    if (localUnsaved) {
      setUnsentAnswers(localUnsaved);
      setAnswers(completed.answers || a.answers);
      answersRef.current = completed.answers || a.answers;
    }
    dirtyRef.current = false;
    setDirty(false);
    closeFinish();
    setMessage("Ответы отправлены. Результат сохранён");
  }
  async function code(task: Task) {
    if (!attempt) return;
    const source = String(answersRef.current[task.id] ?? task.starter_code);
    if (answersRef.current[task.id] === undefined) {
      generation.current++;
      answersRef.current = { ...answersRef.current, [task.id]: source };
      setAnswers(answersRef.current);
      dirtyRef.current = true;
      setDirty(true);
    }
    const a = (await save()) || attempt;
    const j = await api<Job>(
      `/candidate/bank-attempts/${a.id}/code-jobs`,
      "POST",
      {
        task_id: task.id,
        source: String(answersRef.current[task.id] ?? task.starter_code),
      },
    );
    setJobs((jobs) => ({ ...jobs, [task.id]: j }));
  }
  useEffect(() => {
    if (
      !attempt ||
      !Object.values(jobs).some((j) => ["queued", "running"].includes(j.status))
    )
      return;
    const epoch = routeEpoch.current,
      controller = routeController.current;
    const timer = setInterval(() => {
      Object.entries(jobs)
        .filter(([, j]) => ["queued", "running"].includes(j.status))
        .forEach(([task, j]) => {
          void api<Job>(
            `/candidate/bank-attempts/${attempt.id}/code-jobs/${j.id}`,
            "GET",
            undefined,
            {},
            controller?.signal,
          )
            .then((v) => {
              if (epoch !== routeEpoch.current || controller?.signal.aborted)
                return;
              setJobs((jobs) =>
                jobs[task]?.id === v.id ? { ...jobs, [task]: v } : jobs,
              );
              if (
                attempt.status !== "in_progress" &&
                !["queued", "running"].includes(v.status)
              )
                void api<Attempt>(
                  "/candidate/bank-attempts/" + attempt.id,
                  "GET",
                  undefined,
                  {},
                  controller?.signal,
                )
                  .then((updated) => {
                    if (
                      epoch === routeEpoch.current &&
                      !controller?.signal.aborted
                    )
                      setAttempt(updated);
                  })
                  .catch((e) => {
                    if (
                      epoch === routeEpoch.current &&
                      !controller?.signal.aborted
                    )
                      setError(e.message);
                  });
            })
            .catch((e) => {
              if (epoch === routeEpoch.current && !controller?.signal.aborted)
                setError(e.message);
            });
        });
    }, 1000);
    return () => clearInterval(timer);
  }, [jobs, attempt?.id]);
  function answer(task: string, value: unknown) {
    generation.current++;
    if (attempt?.version.tasks.some((t) => t.id === task && t.type === "code"))
      setJobs((current) => {
        const next = { ...current };
        delete next[task];
        return next;
      });
    setAnswers((answers) => ({ ...answers, [task]: value }));
    setDirty(true);
    setMessage("Сохранение ответа…");
  }
  async function goTaskPage(page: number) {
    if (page === taskPages.page) return;
    setNavigating(true);
    try {
      if (attempt?.status === "in_progress" && remaining > 0) await save();
      taskPages.setPage(page);
      requestAnimationFrame(() => taskPanel.current?.focus());
    } catch (e) {
      setError((e as Error).message + ". Переход отменён, ответ сохранён в форме.");
    } finally {
      setNavigating(false);
    }
  }
  if (loading) return <p role="status">Загрузка заданий…</p>;
  if (!attempt)
    return (
      <section>
        <p className="eyebrow">Проверка через практику</p>
        <h2>Практические наборы</h2>
        <p className="lead">
          Сохранённые ответы, воспроизводимая версия и понятные критерии. Наборы
          компаний дают обратную связь и не заменяют оценку для подтверждения
          грейда.
        </p>
        <p className="muted">
          Практика не повышает подтверждённый грейд. Для категории в подборке
          работодателя используйте раздел «Оценка»; здесь можно тренироваться и
          получить обратную связь по конкретным заданиям.
        </p>
        <Feedback error={error} message={message} />
        {history.length > 0 && (
          <div className="attempt-history">
            <h3>Продолжить или посмотреть результат</h3>
            {historyPages.visibleItems.map((a) => (
              <div className="record-row" key={a.id}>
                <div className="section-heading">
                  <p>
                    {a.version.title} · {states[a.status]}
                  </p>
                  <button
                    onClick={() => navigate("/candidate/practice/" + a.id)}
                  >
                    {a.status === "in_progress"
                      ? "Продолжить попытку"
                      : "Открыть результат"}
                  </button>
                </div>
              </div>
            ))}
            <Pagination label="История практических попыток" total={history.length} page={historyPages.page} pages={historyPages.pages} start={historyPages.start} end={historyPages.end} onPageChange={historyPages.setPage} />
          </div>
        )}
        {banks.length === 0 ? (
          <div className="empty">
            <h3>Пока нет опубликованных наборов</h3>
            <p>
              Работодатель может создать и опубликовать набор в своём
              конструкторе.
            </p>
          </div>
        ) : (
          publicBankPages.visibleItems.map((v) => {
            return (
              <article className="record-row" key={v.id}>
                <div className="section-heading">
                  <div>
                    <h3>{v.title}</h3>
                    <p className="muted">
                      Автор: {v.company_label} ·{" "}
                      {v.scope === "platform"
                        ? "Платформенная демо-практика"
                        : "Практика компании"}
                    </p>
                    <p>
                      {specs[v?.specialization]?.label} ·{" "}
                      {taskCount(v?.tasks.length || 0)} ·{" "}
                      {v?.time_limit_minutes} минут
                    </p>
                  </div>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => void run(() => start(v))}
                  >
                    Пройти набор
                  </button>
                </div>
              </article>
            );
          })
        )}
        <Pagination label="Доступные практические наборы" total={banks.length} page={publicBankPages.page} pages={publicBankPages.pages} start={publicBankPages.start} end={publicBankPages.end} onPageChange={publicBankPages.setPage} />
      </section>
    );
  const locked = attempt.status !== "in_progress" || remaining === 0;
  const answeredOnServer = attempt.version.tasks.filter((t) => answerPresent(attempt.answers[t.id])).length;
  const locallyChanged = attempt.version.tasks.filter((t) => JSON.stringify(answers[t.id]) !== JSON.stringify(attempt.answers[t.id])).length;
  const unanswered = attempt.version.tasks.filter((t) => !answerPresent(answers[t.id]));
  return (
    <section className="assessment-workspace" aria-busy={busy || navigating}>
      <button
        className="text-action"
        onClick={() =>
          void run(async () => {
            await save();
            navigate("/candidate/practice");
          })
        }
      >
        Все практические наборы
      </button>
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            Версия {attempt.version.number} · {states[attempt.status]}
          </p>
          <h2>{attempt.version.title}</h2>
        </div>
        <div
          className="attempt-clock"
          role="timer"
          aria-label="Осталось времени"
        >
          {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, "0")}
          <small>осталось</small>
        </div>
      </div>
      <Feedback error={error} message={message} />
      {attempt.result && (
        <div className="result">
          <h3>
            {attempt.status === "pending_review"
              ? Array.isArray(attempt.result.tasks) &&
                (attempt.result.tasks as { status: string }[]).some(
                  (r) => r.status === "pending_review",
                )
                ? "Ожидается ручная проверка"
                : "Ожидается проверка кода"
              : "Результат набора"}
          </h3>
          <ResultSummary result={attempt.result} />
          {unsentAnswers && (
            <details className="unsent-answers">
              <summary>Локальные ответы, не вошедшие в результат</summary>
              <p className="muted">Эти изменения не были сохранены до дедлайна. Текст оставлен для копирования.</p>
              {attempt.version.tasks.filter((t) => answerPresent(unsentAnswers[t.id])).map((t) => (
                <div key={t.id}>
                  <h4>{t.title}</h4>
                  <pre className="review-answer">{Array.isArray(unsentAnswers[t.id]) ? JSON.stringify(unsentAnswers[t.id], null, 2) : String(unsentAnswers[t.id])}</pre>
                </div>
              ))}
            </details>
          )}
          <p className="muted">
            Сбой исполнителя не является неправильным ответом. Открытые ответы
            проверяет автор по рубрике; практика компании не меняет
            подтверждённый грейд.
          </p>
          <button
            onClick={() =>
              void run(async () => {
                const a = await api<Attempt>(
                  "/candidate/bank-attempts/" + attempt.id,
                );
                setAttempt(a);
              })
            }
          >
            Обновить результат
          </button>
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setConfirmFinish(true);
        }}
      >
        <p className="muted" role="status" aria-live="polite">
          Ответов заполнено {attempt.version.tasks.filter((t) => answerPresent(answers[t.id])).length} из {attempt.version.tasks.length} · без ответа {attempt.version.tasks.filter((t) => !answerPresent(answers[t.id])).length}
        </p>
        <Pagination
          label={`Задания попытки «${attempt.version.title}»`}
          total={attempt.version.tasks.length}
          page={taskPages.page}
          pages={taskPages.pages}
          start={taskPages.start}
          end={taskPages.end}
          onPageChange={(page) => void goTaskPage(page)}
          disabled={busy || navigating}
        />
        <fieldset ref={taskPanel} tabIndex={-1} className="attempt-fields">
          {taskPages.visibleItems.map((t, i) => (
            <div key={t.id} className="page-transition">
              <TaskAnswer
                task={t}
                index={(taskPages.page - 1) * taskPages.pageSize + i}
                value={answers[t.id]}
                onChange={(value) => answer(t.id, value)}
                disabled={locked || busy || navigating}
              />
              {t.type === "code" && (
                <div className="code-feedback">
                  <button
                    type="button"
                    disabled={
                      (locked &&
                        !(
                          attempt.status === "pending_review" &&
                          Array.isArray(attempt.result?.tasks) &&
                          (
                            attempt.result.tasks as {
                              task_id: string;
                              status: string;
                            }[]
                          ).some(
                            (r) =>
                              r.task_id === t.id && r.status === "pending_code",
                          )
                        )) ||
                      busy ||
                      ["queued", "running"].includes(jobs[t.id]?.status)
                    }
                    onClick={() => void run(() => code(t))}
                  >
                    Запустить проверки: {t.title}
                  </button>
                  {jobs[t.id] && (
                    <div role="status">
                      <p>{states[jobs[t.id].status] || jobs[t.id].status}</p>
                      <pre>
                        {jobs[t.id].result
                          ? `Пройдено ${jobs[t.id].result!.passed_tests} из ${jobs[t.id].result!.total_tests}. Балл: ${jobs[t.id].result!.score}. ${states[jobs[t.id].result!.status] || jobs[t.id].result!.status}`
                          : jobs[t.id].error_code
                            ? states[jobs[t.id].error_code!] ||
                              "Проверка временно недоступна. Повторите запуск"
                            : "Результат ожидается"}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </fieldset>
        {attempt.status === "in_progress" && (
          <div className="sticky-submit">
            <span className="muted">
              {remaining === 0 && dirty
                ? "Есть локальные изменения; после дедлайна они не сохраняются"
                : dirty
                  ? "Ответы ещё сохраняются"
                  : "Ответы сохранены"}
            </span>
            <button
              type="button"
              disabled={busy || !dirty || remaining === 0}
              onClick={() =>
                void run(async () => {
                  await save();
                })
              }
            >
              Сохранить ответы
            </button>
          <button ref={finishTrigger} type="button" className="primary" disabled={busy} onClick={() => setConfirmFinish(true)}>
              {remaining === 0 ? "Отправить сохранённые ответы" : "Завершить набор"}
            </button>
          </div>
        )}
        {confirmFinish && attempt.status === "in_progress" && (
          <dialog ref={finishDialog} className="confirmation-panel" onCancel={(e) => { e.preventDefault(); closeFinish(); }} onKeyDown={containDialogFocus} aria-labelledby="practice-finish-title" aria-describedby="practice-finish-summary">
            <h3 id="practice-finish-title">Проверьте ответы перед завершением</h3>
            <p id="practice-finish-summary">
              На сервере сохранено ответов: {answeredOnServer} из {attempt.version.tasks.length}. Локально изменено заданий: {locallyChanged}.
              {remaining === 0
                ? " После дедлайна в результат войдут только серверные ответы."
                : " Несохранённые ответы будут сохранены перед завершением."}
              {unanswered.length > 0 ? ` Не отвечено: ${unanswered.length}.` : " Все задания заполнены."}
            </p>
            {remaining === 0 && locallyChanged > 0 && (
              <details>
                <summary>Скопировать локальные изменения перед отправкой</summary>
                {attempt.version.tasks.filter((t) => JSON.stringify(answers[t.id]) !== JSON.stringify(attempt.answers[t.id])).map((t) => (
                  <div key={t.id}><h4>{t.title}</h4><pre className="review-answer">{Array.isArray(answers[t.id]) ? JSON.stringify(answers[t.id], null, 2) : String(answers[t.id] ?? "")}</pre></div>
                ))}
              </details>
            )}
            {unanswered[0] && (
              <p>
                Первый вопрос без ответа: {unanswered[0].title}{" "}
                <button autoFocus type="button" className="text-action" onClick={() => { const index = attempt.version.tasks.findIndex((item) => item.id === unanswered[0].id); closeFinish(); void goTaskPage(index + 1); }}>
                  Перейти к пропуску
                </button>
              </p>
            )}
            <div className="actions">
              <button autoFocus={unanswered.length === 0} type="button" onClick={closeFinish}>Вернуться к заданиям</button>
              <button type="button" className="primary" disabled={busy} onClick={() => void run(submit)}>
                Подтвердить завершение
              </button>
            </div>
          </dialog>
        )}
        {remaining === 0 && attempt.status === "in_progress" && (
          <p role="alert">
            Время закончилось. Можно отправить серверную сохранённую версию попытки. Локальные изменения ниже по странице в неё не попадут.
          </p>
        )}
      </form>
    </section>
  );
}
function TaskAnswer({
  task: t,
  index,
  value,
  onChange,
  preview = false,
  disabled = false,
}: {
  task: Task;
  index: number;
  value: unknown;
  onChange: (value: unknown) => void;
  preview?: boolean;
  disabled?: boolean;
}) {
  return (
    <fieldset className="answer-task" disabled={disabled}>
      <legend>
        {index + 1}. {t.title}
      </legend>
      <p className="task-prompt">{t.prompt}</p>
      <p className="muted">
        {labels[t.type]} · {t.skills.join(", ")} · вес {t.weight}
      </p>
      {(t.type === "single_choice" || t.type === "multiple_choice") &&
        t.options.map((o) => (
          <label className="check" key={o.id}>
            <input
              type={t.type === "single_choice" ? "radio" : "checkbox"}
              name={t.id}
              checked={
                t.type === "single_choice"
                  ? value === o.id
                  : Array.isArray(value) && value.includes(o.id)
              }
              onChange={() =>
                onChange(
                  t.type === "single_choice"
                    ? o.id
                    : Array.isArray(value) && value.includes(o.id)
                      ? value.filter((v) => v !== o.id)
                      : [...(Array.isArray(value) ? value : []), o.id],
                )
              }
            />
            {o.text}
          </label>
        ))}
      {t.type === "numeric" && (
        <label>
          Ваш числовой ответ{" "}
          {t.unit && <span id={t.id + "-unit"}>({t.unit})</span>}
          <input
            aria-label="Ваш числовой ответ"
            aria-describedby={t.unit ? t.id + "-unit" : undefined}
            type="number"
            step="any"
            value={
              typeof value === "number" || typeof value === "string"
                ? value
                : ""
            }
            onChange={(e) => onChange(e.target.value)}
          />
        </label>
      )}
      {t.type === "open_response" && (
        <label>
          Ваш ответ
          <textarea
            aria-label="Ваш ответ"
            aria-describedby={t.id + "-count " + t.id + "-rubric"}
            rows={7}
            maxLength={t.answer_limit}
            value={String(value || "")}
            onChange={(e) => onChange(e.target.value)}
          />
          <small id={t.id + "-count"}>
            {String(value || "").length} / {t.answer_limit} символов
          </small>
          <span className="muted" id={t.id + "-rubric"}>
            Рубрика: {t.rubric}
          </span>
        </label>
      )}
      {t.type === "code" && (
        <>
          <p className="muted">
            {t.language === "sql" ? "SQL (SQLite 3.46.1)" : t.language} · время
            исполнения до {t.runtime_limits.wall_seconds} с.{" "}
            {preview
              ? "В предпросмотре код не запускается."
              : "Введите решение, затем запустите проверки."}
          </p>
          {t.language === "sql" && (
            <p className="muted">
              SELECT выполняется в тестовой базе SQLite. Результат — JSON-массив
              строк, например [[1]].
            </p>
          )}
          {t.examples.map((c, i) => (
            <div className="code-example" key={i}>
              <span>Пример {i + 1}</span>
              <div>
                <pre>
                  Вход{`\n`}
                  {c.input}
                </pre>
                <pre>
                  Выход{`\n`}
                  {c.output}
                </pre>
              </div>
            </div>
          ))}
          <label>
            Код решения: {t.title}
            <textarea
              className="code-editor"
              aria-label={"Код решения: " + t.title}
              rows={10}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              value={String(value ?? t.starter_code)}
              onChange={(e) => onChange(e.target.value)}
            />
          </label>
        </>
      )}
    </fieldset>
  );
}
function ResultSummary({ result }: { result: Record<string, unknown> }) {
  const rows = Array.isArray(result.tasks)
    ? (result.tasks as {
        task_id: string;
        type: TaskType;
        score: number | null;
        status: string;
        feedback?: string;
      }[])
    : [];
  const pages = usePagedItems(rows, 8);
  return (
    <div>
      {Number(result.pending_count || 0) > 0 && (
        <p className="eyebrow">Предварительный балл · проверка продолжается</p>
      )}
      <p className="score">{String(result.score ?? 0)} / 100</p>
      <p>
        {Number(result.pending_count || 0) > 0
          ? `Ожидают проверки: ${result.pending_count}`
          : "Все задания проверены"}
      </p>
      {Number(result.pending_count || 0) > 0 && (
        <p className="muted">
          Итоговый балл будет определён после проверки оставшихся заданий.
          Ожидание исполнителя или автора не означает неправильный ответ.
        </p>
      )}
      <div className="result-task-list">
        {pages.visibleItems.map((row, i) => (
          <div className="record-row" key={row.task_id}>
            <p>
              {(pages.page - 1) * pages.pageSize + i + 1}. {labels[row.type]} ·{" "}
              {row.score === null
                ? row.status === "pending_code"
                  ? "Ожидается исполнение кода"
                  : "Ожидается авторская проверка"
                : `${row.score} / 100`}
            </p>
            {row.feedback && <p className="muted">{row.feedback}</p>}
          </div>
        ))}
      </div>
      <Pagination label="Проверки заданий попытки" total={rows.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
    </div>
  );
}

function ManualReview({ bankId }: { bankId: string }) {
  const [attempts, setAttempts] = useState<Attempt[]>([]),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [scores, setScores] = useState<Record<string, number>>({}),
    [feedback, setFeedback] = useState<Record<string, string>>({});
  const checks = attempts.flatMap((attempt) =>
    attempt.version.tasks
      .filter((task) => task.type === "open_response")
      .map((task) => ({ attempt, task })),
  );
  const pages = usePagedItems(checks, 8);
  const load = () =>
    api<Attempt[]>(`/company/banks/${bankId}/attempts`).then(setAttempts);
  useEffect(() => {
    void load()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [bankId]);
  async function hint(a: Attempt, task: Task) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<{ score: number; feedback: string; source: string }>(
        `/company/bank-attempts/${a.id}/review-suggestion`, "POST", { task_id: task.id });
      const key = `${a.id}:${task.id}`;
      setScores((old) => ({ ...old, [key]: result.score }));
      setFeedback((old) => ({ ...old, [key]: result.feedback }));
      setMessage(`Подсказка ИИ подставлена в форму (${result.source === "llm" ? "локальная модель" : "демо"}). Проверьте её и сохраните свою оценку`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function review(a: Attempt, task: Task, form: HTMLFormElement) {
    const values = new FormData(form);
    setBusy(true);
    setError("");
    try {
      await api(`/company/bank-attempts/${a.id}/review`, "POST", {
        task_id: task.id,
        score: Number(values.get("score")),
        feedback: values.get("feedback"),
      });
      await load();
      setMessage("Проверка сохранена. Результат доступен кандидату");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <h3>Ответы для ручной проверки</h3>
      <p>
        Автор оценивает открытые ответы по рубрике опубликованной версии. До
        завершения проверки результат остаётся предварительным.
      </p>
      <Feedback error={error} message={message} />
      <button
        disabled={busy}
        onClick={() => {
          setLoading(true);
          void load()
            .catch((e) => setError(e.message))
            .finally(() => setLoading(false));
        }}
      >
        Обновить ответы
      </button>
      {loading ? (
        <p role="status">Загрузка ответов…</p>
      ) : checks.length === 0 ? (
        <p className="empty">Пока нет ответов на этот набор.</p>
      ) : (
        pages.visibleItems.map(({ attempt: a, task: t }) => (
          <article className="record-row" key={`${a.id}:${t.id}`}>
            <p className="eyebrow">
              Попытка {a.id.slice(0, 8)} · {states[a.status]}
            </p>
                <div>
                  <h4>{t.title}</h4>
                  <p>Рубрика: {t.rubric}</p>
                  <pre className="review-answer">
                    {String(a.answers[t.id] || "Ответ не указан")}
                  </pre>
                  {a.status === "pending_review" && (
                    <form
                      className="form-grid"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void review(a, t, e.currentTarget);
                      }}
                    >
                      <label>
                        Оценка, от 0 до 100
                        <input
                          name="score"
                          required
                          type="number"
                          min={0}
                          max={100}
                          value={scores[`${a.id}:${t.id}`] ?? 0}
                          onChange={(e) => setScores({ ...scores, [`${a.id}:${t.id}`]: Number(e.target.value) })}
                        />
                      </label>
                      <label>
                        Обратная связь
                        <textarea
                          name="feedback"
                          required
                          minLength={3}
                          maxLength={4000}
                          rows={3}
                          value={feedback[`${a.id}:${t.id}`] || ""}
                          onChange={(e) => setFeedback({ ...feedback, [`${a.id}:${t.id}`]: e.target.value })}
                        />
                      </label>
                      <div className="actions">
                        <button type="button" disabled={busy} onClick={() => void hint(a, t)}>
                          Подсказка ИИ по рубрике
                        </button>
                        <button disabled={busy} className="primary">
                          Сохранить проверку
                        </button>
                      </div>
                    </form>
                  )}
                </div>
          </article>
        ))
      )}
      <Pagination label="Ответы на задания для ручной проверки" total={checks.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
    </div>
  );
}
