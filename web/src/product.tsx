import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { Pagination, usePagedItems } from "./pagination";
import { WorkTasks, useSkillsWorkCatalog } from "./work-tasks";

export const specs: Record<string, { label: string; skills: string[] }> = {
  backend: { label: "Backend / Python", skills: ["python", "sql", "http"] },
  frontend: {
    label: "Frontend / JavaScript",
    skills: ["javascript", "html", "http"],
  },
  qa: { label: "QA / тестирование", skills: ["testing", "sql", "http"] },
  design: { label: "UI/UX дизайн", skills: ["ux", "ui", "html"] },
};
export type Resume = {
  declared_skills: string[];
  full_name: string;
  years_experience: number;
  roles: string[];
  soft_skills: string[];
  education: string;
  about: string;
};
export const blankResume: Resume = {
  declared_skills: [],
  full_name: "Синтетический кандидат",
  years_experience: 0,
  roles: [],
  soft_skills: [],
  education: "",
  about: "",
};
export const salary = (n: number) => new Intl.NumberFormat("ru-RU").format(n);
export const date = (value: string) => new Date(value).toLocaleString("ru-RU");
export function SpecSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label>
      Специализация
      <select
        aria-label="Специализация"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {Object.entries(specs).map(([id, s]) => (
          <option key={id} value={id}>
            {s.label}
          </option>
        ))}
      </select>
    </label>
  );
}
function Feedback({ error, message }: { error: string; message: string }) {
  return (
    <>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
    </>
  );
}
function useResource<T>(path: string, initial: T) {
  const [data, setData] = useState<T>(initial),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false),
    [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true);
    try {
      setData(await api<T>(path));
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  };
  async function reload() {
    setError("");
    try {
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void reload();
  }, [path]);
  async function run(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
      setMessage(success);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return { data, setData, error, message, busy, loaded, loading, run, load, reload };
}

type Company = {
  name: string;
  description: string;
  industry: string;
  contact: string;
};
export function CompanyEditor() {
  const state = useResource<Company | null>("/company/profile", null),
    c = state.data;
  return (
    <section>
      <h2>Профиль компании</h2>
      <p>
        Данные компании видны кандидату до принятия приглашения. Заполнение
        формы не означает проверку организации.
      </p>
      <Feedback {...state} />
      {c && (
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            void state.run(
              () =>
                api("/company/profile", "PUT", {
                  name: c.name,
                  description: c.description,
                  industry: c.industry,
                  contact: c.contact,
                }),
              "Компания сохранена",
            );
          }}
        >
          <label>
            Название компании
            <input
              required
              minLength={2}
              maxLength={120}
              value={c.name}
              onChange={(e) => state.setData({ ...c, name: e.target.value })}
            />
          </label>
          <label>
            Направление деятельности
            <input
              required
              minLength={2}
              maxLength={120}
              value={c.industry}
              onChange={(e) =>
                state.setData({ ...c, industry: e.target.value })
              }
            />
          </label>
          <label className="full">
            Описание команды
            <textarea
              required
              minLength={20}
              maxLength={4000}
              value={c.description}
              onChange={(e) =>
                state.setData({ ...c, description: e.target.value })
              }
            />
          </label>
          <label className="full">
            Контакт компании · example.invalid
            <input
              type="email"
              required
              value={c.contact}
              onChange={(e) => state.setData({ ...c, contact: e.target.value })}
            />
          </label>
          <button className="primary" disabled={state.busy}>
            Сохранить компанию
          </button>
        </form>
      )}
    </section>
  );
}

export type NeedQuery = {
  specialization: string;
  grade: string;
  format: string;
  salary_to: number;
  must_skills: string[];
  desired_skills: string[];
  work_tasks: string[];
  fsp_only: boolean;
};
type Need = {
  id: string;
  title: string;
  description: string;
  query: NeedQuery;
};
export function Needs({ onSearch }: { onSearch: (query: NeedQuery) => void }) {
  const { catalog, error: catalogError } = useSkillsWorkCatalog();
  const [workTasks, setWorkTasks] = useState<string[]>([]);
  const state = useResource<Need[]>("/company/needs", []),
    [title, setTitle] = useState("Разработка API"),
    [description, setDescription] = useState(
      "Синтетическая команда развивает внутренний API и ищет разработчика.",
    ),
    [spec, setSpec] = useState("backend"),
    [grade, setGrade] = useState("junior"),
    [budget, setBudget] = useState(180000),
    [format, setFormat] = useState("remote"),
    [mustSkills, setMustSkills] = useState<string[]>([specs.backend.skills[0]]),
    [desiredSkills, setDesiredSkills] = useState<string[]>(
      specs.backend.skills.slice(1),
    );
  const pages = usePagedItems(state.data, 10);
  const query: NeedQuery = {
    specialization: spec,
    grade,
    format,
    salary_to: budget,
    must_skills: mustSkills,
    desired_skills: desiredSkills,
    work_tasks: workTasks,
    fsp_only: false,
  };
  return (
    <section>
      <h2>Потребности команды</h2>
      <p className="eyebrow">
        Потребность → подборка → предложение → решение кандидата
      </p>
      <p>
        Потребность не обязана быть публичной вакансией. В подборке участвуют
        подтверждённые категории и навыки.
      </p>
      <Feedback {...state} />
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          void state.run(
            () =>
              api("/company/needs", "POST", { ...query, title, description }),
            "Потребность сохранена",
          );
        }}
      >
        <label>
          Название потребности
          <input
            required
            minLength={3}
            maxLength={120}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <SpecSelect
          value={spec}
          onChange={(next) => {
            setSpec(next);
            setWorkTasks([]);
            setMustSkills([specs[next].skills[0]]);
            setDesiredSkills(specs[next].skills.slice(1));
          }}
        />
        <label>
          Грейд
          <select value={grade} onChange={(e) => setGrade(e.target.value)}>
            <option value="junior">Junior</option>
            <option value="middle">Middle</option>
          </select>
        </label>
        <label>
          Бюджет до, руб.
          <input
            required
            type="number"
            min={1}
            max={10000000}
            value={budget}
            onChange={(e) => setBudget(Number(e.target.value))}
          />
        </label>
        <label>
          Формат
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="remote">Удалённо</option>
            <option value="hybrid">Гибрид</option>
            <option value="office">В офисе</option>
          </select>
        </label>
        <label className="full">
          Чем занимается команда
          <textarea
            required
            minLength={20}
            maxLength={4000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <fieldset className="full">
          <legend>Стек для подбора</legend>
          <p className="muted">
            Обязательные навыки отсекают неподходящие профили. Желательные
            помогают ранжировать подборку.
          </p>
          <div className="form-grid">
            {specs[spec].skills.map((skill) => (
              <label key={skill}>
                {skill}
                <select
                  aria-label={"Важность навыка: " + skill}
                  value={
                    mustSkills.includes(skill)
                      ? "must"
                      : desiredSkills.includes(skill)
                        ? "desired"
                        : "unused"
                  }
                  onChange={(e) => {
                    const importance = e.target.value;
                    setMustSkills((current) => [
                      ...current.filter((s) => s !== skill),
                      ...(importance === "must" ? [skill] : []),
                    ]);
                    setDesiredSkills((current) => [
                      ...current.filter((s) => s !== skill),
                      ...(importance === "desired" ? [skill] : []),
                    ]);
                  }}
                >
                  <option value="must">Обязательный</option>
                  <option value="desired">Желательный</option>
                  <option value="unused">Не учитывать</option>
                </select>
              </label>
            ))}
          </div>
        </fieldset>
        {catalogError && <p role="alert" className="error full">{catalogError}</p>}
        <WorkTasks catalog={catalog} specialization={spec} value={workTasks} onChange={setWorkTasks} />
        <button className="primary" disabled={state.busy}>
          Сохранить потребность
        </button>
      </form>
      <div className="record-list">
        {pages.visibleItems.map((n) => (
          <article className="record-row" key={n.id}>
            <h3>{n.title}</h3>
            <p>{n.description}</p>
            <p className="muted">
              {specs[n.query.specialization]?.label} / {n.query.grade} · до{" "}
              {salary(n.query.salary_to)} руб.
            </p>
            <p className="muted">
              Обязательные: {n.query.must_skills.join(", ") || "не заданы"}.
              Желательные: {n.query.desired_skills.join(", ") || "не заданы"}.
            </p>
            <p className="muted">Задачи: {(n.query.work_tasks || []).map((id) => catalog?.work_tasks?.find((task) => task.id === id)?.label || id).join(", ") || "не выбраны"}.</p>
            <button onClick={() => onSearch(n.query)}>
              Подобрать кандидатов
            </button>
          </article>
        ))}
      </div>
      <Pagination label="Потребности команды" total={state.data.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
    </section>
  );
}

type Vacancy = {
  id: string;
  company_id: string;
  company: { name: string; description: string; contact: string };
  title: string;
  description: string;
  specialization: string;
  grade: string;
  skills: string[];
  format: string;
  salary_from: number;
  salary_to: number;
  salary_basis: string;
  status: string;
  version: number;
};
const blankVacancy = {
  title: "Разработчик продукта",
  description:
    "Синтетическая вакансия: работа над интерфейсом и API, согласованные задачи команды.",
  specialization: "backend",
  grade: "junior",
  skills: ["python", "sql", "http"],
  format: "remote",
  salary_from: 100000,
  salary_to: 180000,
  salary_basis: "gross",
  status: "draft",
};
export function Vacancies({ role }: { role: "candidate" | "employer" }) {
  const employer = role === "employer",
    state = useResource<Vacancy[]>(
      employer ? "/company/vacancies" : "/candidate/vacancies",
      [],
    ),
    [form, setForm] = useState(blankVacancy),
    [editing, setEditing] = useState<Vacancy | null>(null);
  const pages = usePagedItems(state.data, 8);
  function edit(v: Vacancy) {
    setEditing(v);
    setForm({
      title: v.title,
      description: v.description,
      specialization: v.specialization,
      grade: v.grade,
      skills: v.skills,
      format: v.format,
      salary_from: v.salary_from,
      salary_to: v.salary_to,
      salary_basis: v.salary_basis,
      status: v.status,
    });
  }
  function save(e: FormEvent) {
    e.preventDefault();
    void state.run(async () => {
      await api(
        editing ? `/company/vacancies/${editing.id}` : "/company/vacancies",
        editing ? "PUT" : "POST",
        { ...form, ...(editing ? { expected_version: editing.version } : {}) },
      );
      setEditing(null);
      setForm(blankVacancy);
    }, "Вакансия сохранена");
  }
  return (
    <section>
      <h2>{employer ? "Вакансии компании" : "Открытые вакансии"}</h2>
      <p>
        {employer
          ? "Публикация вакансии дополняет основной путь приглашения. Зарплата обязательна."
          : "Отклик добровольно открывает контакт этой компании. Можно отозвать отклик или отдельно отозвать контакт в «Приватности»."}
      </p>
      <Feedback {...state} />
      {employer && (
        <form className="form-grid" onSubmit={save}>
          <label>
            Название вакансии
            <input
              required
              minLength={3}
              maxLength={120}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </label>
          <SpecSelect
            value={form.specialization}
            onChange={(value) =>
              setForm({
                ...form,
                specialization: value,
                skills: specs[value].skills,
              })
            }
          />
          <label>
            Грейд
            <select
              value={form.grade}
              onChange={(e) => setForm({ ...form, grade: e.target.value })}
            >
              <option value="junior">Junior</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label>
            Формат
            <select
              value={form.format}
              onChange={(e) => setForm({ ...form, format: e.target.value })}
            >
              <option value="remote">Удалённо</option>
              <option value="hybrid">Гибрид</option>
              <option value="office">В офисе</option>
            </select>
          </label>
          <label>
            Зарплата от, руб.
            <input
              required
              type="number"
              min={1}
              max={10000000}
              value={form.salary_from}
              onChange={(e) =>
                setForm({ ...form, salary_from: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Зарплата до, руб.
            <input
              required
              type="number"
              min={1}
              max={10000000}
              value={form.salary_to}
              onChange={(e) =>
                setForm({ ...form, salary_to: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Расчёт
            <select
              value={form.salary_basis}
              onChange={(e) =>
                setForm({ ...form, salary_basis: e.target.value })
              }
            >
              <option value="gross">До вычета налогов</option>
              <option value="net">На руки</option>
            </select>
          </label>
          <label>
            Состояние вакансии
            <select
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
            >
              <option value="draft">Черновик</option>
              <option value="published">Опубликована</option>
              <option value="closed">Закрыта</option>
            </select>
          </label>
          <label className="full">
            Описание вакансии
            <textarea
              required
              minLength={20}
              maxLength={4000}
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </label>
          <div className="actions full">
            <button className="primary" disabled={state.busy}>
              {editing ? "Сохранить изменения вакансии" : "Создать вакансию"}
            </button>
            {editing && (
              <button
                type="button"
                onClick={() => {
                  setEditing(null);
                  setForm(blankVacancy);
                }}
              >
                Отменить редактирование
              </button>
            )}
          </div>
        </form>
      )}
      <div className="record-list">
        {pages.visibleItems.map((v) => (
          <article className="record-row" key={v.id}>
            <h3>{v.title}</h3>
            <p className="evidence">
              {v.company.name} · {specs[v.specialization]?.label} / {v.grade}
            </p>
            <p className="salary">
              {salary(v.salary_from)}–{salary(v.salary_to)} руб./мес.
            </p>
            <p className="muted">
              {v.salary_basis === "gross" ? "До вычета налогов" : "На руки"} ·{" "}
              {v.format} · {employer ? v.status : "Компания не проверена"}
            </p>
            <p>{v.description}</p>
            <p>Стек: {v.skills.join(", ")}</p>
            {employer ? (
              <button disabled={state.busy} onClick={() => edit(v)}>
                Редактировать вакансию
              </button>
            ) : (
              <button
                className="primary"
                disabled={state.busy}
                onClick={() =>
                  void state.run(
                    () => api(`/candidate/vacancies/${v.id}/apply`, "POST"),
                    "Отклик отправлен. Контакт разрешён только этой компании",
                  )
                }
              >
                Откликнуться и разрешить контакт
              </button>
            )}
          </article>
        ))}
      </div>
      <Pagination label={employer ? "Вакансии компании" : "Открытые вакансии"} total={state.data.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
      {state.data.length === 0 && <p>Опубликованных вакансий пока нет.</p>}
    </section>
  );
}

type Application = {
  id: string;
  candidate_alias: string;
  contact?: string;
  status: string;
  contact_revoked: boolean;
  snapshot: Vacancy;
  created_at: string;
};
const appStatuses: Record<string, string> = {
  sent: "Отправлен",
  viewed: "Просмотрен",
  accepted: "Принят",
  declined: "Отклонён",
  withdrawn: "Отозван",
};
export function Applications({ role }: { role: "candidate" | "employer" }) {
  const employer = role === "employer",
    state = useResource<Application[]>(
      employer ? "/company/applications" : "/candidate/applications",
      [],
    );
  const pages = usePagedItems(state.data, 8);
  return (
    <section>
      <div className="section-heading">
        <h2>{employer ? "Отклики на вакансии" : "Мои отклики"}</h2>
        <button
          disabled={state.busy}
          onClick={() => void state.run(async () => {}, "Состояния обновлены")}
        >
          Обновить отклики
        </button>
      </div>
      <Feedback {...state} />
      {state.data.length === 0 ? (
        <p>Откликов пока нет.</p>
      ) : (
        pages.visibleItems.map((a) => (
          <article className="record-row" key={a.id}>
            <h3>{a.snapshot.title}</h3>
            <p>
              {employer ? a.candidate_alias : a.snapshot.company.name} ·{" "}
              {appStatuses[a.status]}
            </p>
            <p className="salary">
              {salary(a.snapshot.salary_from)}–{salary(a.snapshot.salary_to)}{" "}
              руб.
            </p>
            <p className="muted">
              Условия в момент отклика · {date(a.created_at)}
            </p>
            {employer && (
              <p>
                {a.contact
                  ? "Разрешённый контакт: " + a.contact
                  : "Контакт недоступен или отозван"}
              </p>
            )}
            <div className="actions">
              {employer
                ? ["sent", "viewed"].includes(a.status) &&
                  ["viewed", "accepted", "declined"].map((status) => (
                    <button
                      key={status}
                      disabled={state.busy}
                      onClick={() =>
                        void state.run(
                          () =>
                            api(
                              `/company/applications/${a.id}/decision`,
                              "POST",
                              { status },
                            ),
                          "Статус отклика изменён",
                        )
                      }
                    >
                      {status === "viewed"
                        ? "Отметить просмотр"
                        : status === "accepted"
                          ? "Принять отклик"
                          : "Отклонить отклик"}
                    </button>
                  ))
                : a.status !== "withdrawn" && (
                    <button
                      disabled={state.busy}
                      onClick={() =>
                        void state.run(
                          () =>
                            api(
                              `/candidate/applications/${a.id}/withdraw`,
                              "POST",
                            ),
                          "Отклик отозван",
                        )
                      }
                    >
                      Отозвать отклик
                    </button>
                  )}
            </div>
          </article>
        ))
      )}
      <Pagination label={employer ? "Отклики на вакансии" : "Мои отклики"} total={state.data.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
    </section>
  );
}

type Task = {
  id: string;
  title: string;
  description: string;
  rubric: string;
  specialization: string;
  grade: string;
  published: boolean;
  company: { name: string };
};
type TaskResponse = {
  id: string;
  task: Task;
  candidate_alias: string;
  answer: string;
  score: number | null;
  feedback: string | null;
  submitted_at: string;
};
type WeeklyTask = {
  id: string;
  task: Task;
  period_starts_at: string;
  next_period_at: string;
};
type SuggestedTasks = {
  available: Task[];
  next_at: string;
  responses: TaskResponse[];
  recommendation: WeeklyTask | null;
  recommendation_state: "offered" | "no-grade" | "cooldown" | "no-tasks";
};
const emptyTasks: SuggestedTasks = {
  available: [], next_at: "", responses: [], recommendation: null,
  recommendation_state: "no-tasks",
};

export function WeeklyTaskNotice() {
  const state = useResource<SuggestedTasks>("/candidate/tasks", emptyTasks);
  const offer = state.data.recommendation;
  if (!offer) return null;
  return <section className="record-row" aria-label="Предложение задания на неделю">
    <h2>Предложено вам на эту неделю</h2>
    <h3>{offer.task.title}</h3>
    <p>{offer.task.company.name} · до 15 минут · ответ оценивает компания</p>
    <p className="muted">Подобрано по вашей подтверждённой категории. Участие добровольное;
      результат не меняет глобальный грейд. Предложение формируется при открытии кабинета,
      новая неделя начинается {date(offer.next_period_at)}.</p>
    <button onClick={() => { window.location.hash = "#/candidate/tasks"; }}>
      Открыть предложенное задание
    </button>
  </section>;
}
export function CandidateTasks() {
  const state = useResource<SuggestedTasks>("/candidate/tasks", emptyTasks),
    [answers, setAnswers] = useState<Record<string, string>>({});
  const recommendedId = state.data.recommendation?.task.id;
  const available = recommendedId ? [
    ...state.data.available.filter((task) => task.id === recommendedId),
    ...state.data.available.filter((task) => task.id !== recommendedId),
  ] : state.data.available;
  const availablePages = usePagedItems(available, 8);
  const responsePages = usePagedItems(state.data.responses, 8);
  return (
    <section>
      <h2>Короткие задания работодателей</h2>
      <p>
        Не чаще раза в семь суток, до 15 минут на задание. Ответ оценивает
        компания по заранее опубликованной рубрике. Он обновляет сигнал
        актуальности, но не меняет подтверждённый грейд.
      </p>
      <Feedback {...state} />
      {!state.loaded && !state.error && <p role="status">Загрузка коротких заданий…</p>}
      {state.error && <button type="button" disabled={state.loading} onClick={() => void state.reload()}>
        Повторить загрузку заданий
      </button>}
      {state.loaded && <>
      {state.data.recommendation && <p className="notice">
        Предложение этой недели: <strong>{state.data.recommendation.task.title}</strong>.
        Выполните его или выберите другое доступное задание. Ответ и рубрику проверяет компания.
      </p>}
      {availablePages.visibleItems.map((t) => (
        <article className="record-row" key={t.id}>
          <h3>{t.title}</h3>
          <p>{t.company.name} · компания не проверена</p>
          <p>{t.description}</p>
          <p className="muted">Рубрика: {t.rubric}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void state.run(
                () =>
                  api(`/candidate/tasks/${t.id}/submit`, "POST", {
                    answer: answers[t.id],
                  }),
                "Ответ передан компании",
              );
            }}
          >
            <label>
              Ваш подход
              <textarea
                required
                minLength={20}
                maxLength={4000}
                value={answers[t.id] || ""}
                onChange={(e) =>
                  setAnswers({ ...answers, [t.id]: e.target.value })
                }
              />
            </label>
            <button className="primary" disabled={state.busy}>
              Отправить подход
            </button>
          </form>
        </article>
      ))}
      <Pagination label="Доступные короткие задания" total={state.data.available.length} page={availablePages.page} pages={availablePages.pages} start={availablePages.start} end={availablePages.end} onPageChange={availablePages.setPage} />
      {state.data.available.length === 0 && (
        <p>{state.data.recommendation_state === "no-grade"
          ? "Для получения задач подтвердите грейд выбранной специализации."
          : state.data.recommendation_state === "cooldown"
            ? `Следующее короткое задание станет доступно ${date(state.data.next_at)}.`
            : "Сейчас нет опубликованных заданий вашей подтверждённой категории."}</p>
      )}
      <h3>История коротких заданий</h3>
      {responsePages.visibleItems.map((r) => (
        <article className="record-row" key={r.id}>
          <h3>{r.task.title}</h3>
          <p>{r.answer}</p>
          <p>
            {r.score === null
              ? "Ожидает оценки компании"
              : `Оценка компании: ${r.score}/100`}
          </p>
          {r.feedback && <p>Обратная связь: {r.feedback}</p>}
        </article>
      ))}
      <Pagination label="История коротких заданий" total={state.data.responses.length} page={responsePages.page} pages={responsePages.pages} start={responsePages.start} end={responsePages.end} onPageChange={responsePages.setPage} />
      </>}
    </section>
  );
}

export function EmployerTasks() {
  const state = useResource<Task[]>("/company/tasks", []),
    reviews = useResource<TaskResponse[]>("/company/task-responses", []),
    [form, setForm] = useState({
      title: "Проверка доступа к профилю",
      description:
        "Предложите план проверки разграничения контактов двух независимых компаний.",
      rubric:
        "Назовите владельца, отрицательные проверки, сценарий отзыва и повторного принятия.",
      specialization: "backend",
      grade: "junior",
      published: true,
    }),
    [scores, setScores] = useState<Record<string, number>>({}),
    [feedback, setFeedback] = useState<Record<string, string>>({});
  const taskPages = usePagedItems(state.data, 10);
  const reviewPages = usePagedItems(reviews.data, 8);
  return (
    <section>
      <h2>Короткие задания и обратная связь</h2>
      <p>
        Только небольшие синтетические упражнения. Не размещайте задания с
        production-данными или полезной бесплатной работой.
      </p>
      <Feedback {...state} />
      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          void state.run(
            () => api("/company/tasks", "POST", form),
            "Короткое задание опубликовано",
          );
        }}
      >
        <label>
          Название задания
          <input
            required
            minLength={3}
            maxLength={120}
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </label>
        <SpecSelect
          value={form.specialization}
          onChange={(v) => setForm({ ...form, specialization: v })}
        />
        <label>
          Грейд
          <select
            value={form.grade}
            onChange={(e) => setForm({ ...form, grade: e.target.value })}
          >
            <option value="junior">Junior</option>
            <option value="middle">Middle</option>
          </select>
        </label>
        <label className="full">
          Короткая задача
          <textarea
            required
            minLength={20}
            maxLength={2000}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <label className="full">
          Рубрика оценки
          <textarea
            required
            minLength={20}
            maxLength={2000}
            value={form.rubric}
            onChange={(e) => setForm({ ...form, rubric: e.target.value })}
          />
        </label>
        <button className="primary" disabled={state.busy}>
          Опубликовать короткое задание
        </button>
      </form>
      <h3>Опубликованные задания</h3>
      {taskPages.visibleItems.map((t) => (
        <p key={t.id}>
          {t.title} · {specs[t.specialization]?.label} / {t.grade}
        </p>
      ))}
      <Pagination label="Опубликованные короткие задания" total={state.data.length} page={taskPages.page} pages={taskPages.pages} start={taskPages.start} end={taskPages.end} onPageChange={taskPages.setPage} />
      <div className="section-heading">
        <h3>Ответы кандидатов</h3>
        <button
          disabled={reviews.busy}
          onClick={() => void reviews.run(async () => {}, "Ответы обновлены")}
        >
          Обновить ответы
        </button>
      </div>
      <Feedback {...reviews} />
      {reviewPages.visibleItems.map((r) => (
        <article className="record-row" key={r.id}>
          <h3>
            {r.task.title} · {r.candidate_alias}
          </h3>
          <p>{r.answer}</p>
          {r.score === null ? (
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                void reviews.run(
                  () =>
                    api(`/company/task-responses/${r.id}/review`, "POST", {
                      score: scores[r.id] ?? 70,
                      feedback: feedback[r.id] || "",
                    }),
                  "Обратная связь сохранена",
                );
              }}
            >
              <label>
                Балл компании, 0–100
                <input
                  type="number"
                  required
                  min={0}
                  max={100}
                  value={scores[r.id] ?? 70}
                  onChange={(e) =>
                    setScores({ ...scores, [r.id]: Number(e.target.value) })
                  }
                />
              </label>
              <label className="full">
                Обратная связь
                <textarea
                  required
                  minLength={20}
                  maxLength={2000}
                  value={feedback[r.id] || ""}
                  onChange={(e) =>
                    setFeedback({ ...feedback, [r.id]: e.target.value })
                  }
                />
              </label>
              <button className="primary" disabled={reviews.busy}>
                Сохранить оценку задачи
              </button>
            </form>
          ) : (
            <p>
              Оценка: {r.score}/100 · {r.feedback}
            </p>
          )}
        </article>
      ))}
      <Pagination label="Ответы кандидатов на задания" total={reviews.data.length} page={reviewPages.page} pages={reviewPages.pages} start={reviewPages.start} end={reviewPages.end} onPageChange={reviewPages.setPage} />
    </section>
  );
}

export function AssessmentHistory({ onReview }: { onReview: (id: string) => void }) {
  const state = useResource<{
    attempts: {
      id: string;
      specialization: string;
      grade: string;
      created_at: string;
      submitted_at: string | null;
      version: string;
      result: { score: number; passed: boolean } | null;
    }[];
  }>("/candidate/assessment-history", { attempts: [] });
  const pages = usePagedItems(state.data.attempts, 8);
  return (
    <section>
      <h2>История оценок</h2>
      <p className="muted">
        Здесь — оценка, определяющая категорию для подбора. Результаты
        практических наборов и коротких заданий хранятся в своих разделах и не
        меняют подтверждённый грейд.
      </p>
      <Feedback {...state} />
      {state.data.attempts.length === 0 ? (
        <p>
          Оценок пока нет. Предустановленный seed-профиль не считается
          пройденным человеком тестом.
        </p>
      ) : (
        pages.visibleItems.map((a) => (
          <article className="record-row" key={a.id}>
            <h3>
              {specs[a.specialization]?.label} / {a.grade}
            </h3>
            <p>
              {date(a.created_at)} · {a.version}
            </p>
            {a.submitted_at && a.result && (
              <button type="button" onClick={() => onReview(a.id)}>
                Просмотреть вопросы и ответы
              </button>
            )}
            <p>
              {a.result
                ? `${a.result.score}/100 · ${a.result.passed ? "Пройдено" : "Не пройдено"}`
                : "Не отправлено"}
            </p>
          </article>
        ))
      )}
      <Pagination label="История оценок" total={state.data.attempts.length} page={pages.page} pages={pages.pages} start={pages.start} end={pages.end} onPageChange={pages.setPage} />
    </section>
  );
}
