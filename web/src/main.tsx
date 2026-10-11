import { uuid } from "./uuid";
import { startIntegrityMonitor, type IntegrityMonitor } from "./integrity";
import { useExamMode } from "./exam-mode";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, setCsrf, getCsrf, type Account } from "./api";
import logoUrl from "./assets/fsp-logo.svg";
import "./style.css";
import { BanksWorkspace, BankAssessment } from "./banks";
import { Pagination, usePagedItems } from "./pagination";
import { containDialogFocus } from "./dialog";
import { AssessmentReport, type Feedback } from "./assessment-report";
import { Comparison, RankingEvidence } from "./comparison";
import { Showcase } from "./showcase";
import { Messages, useUnreadMessages } from "./messages";
import { SkillEvidence, type SkillEvidenceData } from "./skill-evidence";
import { WorkTasks, WorkMatches, useSkillsWorkCatalog, type WorkMatch } from "./work-tasks";
import {
  navigate,
  useRoute,
  useNavigationGuard,
  flushNavigation,
} from "./routing";
import {
  specs,
  blankResume,
  SpecSelect,
  CompanyEditor,
  Needs,
  Vacancies,
  Applications,
  CandidateTasks,
  WeeklyTaskNotice,
  EmployerTasks,
  AssessmentHistory,
  type Resume,
  type NeedQuery,
} from "./product";

type Profile = {
  id: string;
  alias: string;
  specialization: string;
  claimed_grade: string;
  confirmed_grade: string | null;
  salary_min: number;
  formats: string[];
  contact: string;
  published: boolean;
  skills: string[];
  test_score: number;
  fsp_state: string;
  resume: Resume;
  fsp_member_id: string | null;
  fsp_evidence: {
    event: string;
    discipline: string;
    place: number;
    source: string;
    date: string;
    role: string;
  }[];
  contact_grants: { id: string; label: string }[];
  skill_evidence?: SkillEvidenceData | null;
  integrity_level?: "clean" | "review" | null;
};
type Row = Omit<
  Profile,
  | "contact"
  | "published"
  | "contact_grants"
  | "claimed_grade"
  | "resume"
  | "fsp_member_id"
> & {
  work_matches?: WorkMatch[];
  score?: number;
  matched?: string[];
  missing?: string[];
  fsp_bonus?: number;
  components?: { assessment: number; skills: number; fsp: number; freshness: number };
};
type Offer = {
  id: string;
  candidate_id: string;
  candidate_alias: string;
  company_id: string;
  company_name: string;
  company_contact: string;
  description: string;
  salary_from: number;
  salary_to: number;
  salary_basis: string;
  status: string;
  contact?: string;
  contact_revoked: boolean;
};
type Question = { id: string; title: string; skill: string; options: string[] };
type Attempt = {
  id: string;
  questions: Question[];
  grade: string;
  version?: string;
  specialization?: string;
  answers?: Record<string, string>;
  revision?: number;
  expires_at?: string;
  result?: Result | null;
  feedback?: Feedback | null;
};
type IntegritySummary = {
  level: "clean" | "review" | "flagged";
  signals: { code: string; level: string; value: number; message: string }[];
  hold: boolean;
  enforced: boolean;
};
type Result = {
  score: number;
  skills: string[];
  passed: boolean;
  confirmed?: boolean;
  borderline?: boolean;
  needs_confirmation?: boolean;
  stage?: number;
  stage_scores?: number[];
  integrity?: IntegritySummary;
  limitation: string;
};
const money = (value: number) => new Intl.NumberFormat("ru-RU").format(value);
const gradeName = (value: string | null) =>
  value === "middle"
    ? "Middle"
    : value === "junior"
      ? "Junior"
      : "Не подтверждён";
const fspNames: Record<string, string> = {
  none: "Не связан",
  "linked-empty": "История пуста",
  verified: "Демо-история подтверждена",
  unavailable: "Источник временно недоступен",
};
const offerNames: Record<string, string> = {
  sent: "Отправлено",
  viewed: "Просмотрено",
  accepted: "Принято",
  declined: "Отклонено",
  expired: "Истекло",
  withdrawn: "Отозвано",
};

function useAccessibleView() {
  const read = () => {
    try {
      return localStorage.getItem("fsp-view") === "accessible";
    } catch {
      return false;
    }
  };
  const [on, setOn] = useState(read);
  useLayoutEffect(() => {
    document.documentElement.dataset.view = on ? "accessible" : "standard";
    try {
      localStorage.setItem("fsp-view", on ? "accessible" : "standard");
    } catch {
      /* настройка просто не запомнится */
    }
  }, [on]);
  return [on, setOn] as const;
}

const JuryModeContext = React.createContext(false);

function App() {
  const [accessible, setAccessible] = useAccessibleView();
  const [user, setUser] = useState<Account | null>(null),
    [accounts, setAccounts] = useState<Account[]>([]),
    [accountsReady, setAccountsReady] = useState(false),
    [juryMode, setJuryMode] = useState<boolean | null>(null),
    [authMode, setAuthMode] = useState<"local" | "shared-password" | "individual" | null>(null),
    [copyStatus, setCopyStatus] = useState(""),
    [ready, setReady] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function refresh() {
    try {
      const u = await api<Account>("/me");
      setCsrf(u.csrf || "");
      setUser(u);
      setCopyStatus("");
    } catch {
      setUser(null);
      setCsrf("");
      setCopyStatus("");
    } finally {
      setReady(true);
    }
  }
  useEffect(() => {
    void refresh();
    void fetch('/api/health', { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Не удалось проверить режим стенда');
        const health = await response.json();
        if (!['local-demo', 'jury-demo'].includes(health.mode)) throw new Error('Неизвестный режим стенда');
        if (!['local', 'shared-password', 'individual'].includes(health.auth_mode)) throw new Error('Неизвестный режим входа');
        setJuryMode(health.mode === 'jury-demo');
        setAuthMode(health.auth_mode);
        if (health.mode === 'jury-demo') {
          setAccounts([]);
        } else {
          await api<Account[]>("/auth/demo-accounts")
            .then(setAccounts)
            .catch(() => setAccounts([]));
        }
      })
      .catch((error: Error) => setError(error.message))
      .finally(() => setAccountsReady(true));
  }, []);
  async function login(id: string) {
    setBusy(true);
    setError("");
    try {
      const u = await api<Account>("/auth/demo-login", "POST", { user_id: id });
      setCsrf(u.csrf || "");
      setUser(u);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    setBusy(true);
    try {
      if (!(await flushNavigation())) return;
      await api("/auth/logout", "POST");
      setUser(null);
      setCsrf("");
      setCopyStatus("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <a
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
        className="skip-link"
      >
        Перейти к содержимому
      </a>
      <header>
        <a className="brand" href="/" aria-label="ФСП · Карьерный профиль, на главную">
          <img className="brand-logo" src={logoUrl} alt="" width="118" height="40" />
          <span className="brand-name">Карьерный профиль</span>
        </a>
        <div className="identity">
          <button
            type="button"
            className="view-toggle"
            aria-pressed={accessible}
            onClick={() => setAccessible(!accessible)}
          >
            Версия для слабовидящих
          </button>
          {user ? (
            <>
              <span>
                {user.label}
                {authMode === "individual" && user.email && (
                  <small className="generated-login">Логин: {user.email}</small>
                )}
              </span>
              {authMode === "individual" && user.email && (
                <button
                  type="button"
                  onClick={() => {
                    if (!navigator.clipboard) {
                      setCopyStatus("Скопируйте логин вручную");
                      return;
                    }
                    void navigator.clipboard.writeText(user.email || "").then(
                      () => setCopyStatus("Логин скопирован"),
                      () => setCopyStatus("Скопируйте логин вручную"),
                    );
                  }}
                >
                  Скопировать логин
                </button>
              )}
              <button disabled={busy} onClick={() => void logout()}>
                Выйти
              </button>
            </>
          ) : (
            <span>Конкурсный стенд</span>
          )}
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <div className="notice">
          <strong>{juryMode ? 'Тестовый стенд в России' : 'Локальная демонстрация'}</strong>
          <span>
            {juryMode
              ? authMode === "individual"
                ? 'Создайте отдельный синтетический аккаунт. Не вводите реальные ФИО, контакты и резюме. Почта не используется. Оценка не является профессиональной аттестацией.'
                : 'Только синтетические данные. Не вводите реальные ФИО, контакты и резюме. Доступ жюри — по паролю; почта и регистрация отключены. Оценка не является профессиональной аттестацией.'
              : 'Только синтетические данные. Почта и история ФСП — mock. Демо-оценка не является профессиональной аттестацией.'}
          </span>
        </div>
        {copyStatus && <p role="status">{copyStatus}</p>}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {!ready || juryMode === null ? (
          <p role="status">Загрузка сессии…</p>
        ) : user ? (
          <JuryModeContext.Provider value={juryMode === true}>
            <Dashboard key={user.id} user={user} />
          </JuryModeContext.Provider>
        ) : (
          <>
            <section className="hero">
              <div>
                <p className="eyebrow">Предложение до раскрытия контактов</p>
                <h1>
                  Сначала доказательства.
                  <br />
                  Потом знакомство.
                </h1>
                <p className="lead">
                  Кандидат показывает навыки. Работодатель предлагает условия.
                  Зарплата известна до знакомства, контакт — после решения
                  кандидата.
                </p>
                <div className="hero-actions">
                  {accounts.length > 0 && (
                    <button
                      className="primary"
                      onClick={() =>
                        document.getElementById("demo-cabinets")?.focus()
                      }
                    >
                      Выбрать тестовый кабинет
                    </button>
                  )}
                  <button
                    className={accounts.length > 0 || !accountsReady ? "text-action" : "primary"}
                    onClick={() =>
                      document.getElementById("own-account")?.focus()
                    }
                  >
                    Начать со своего аккаунта
                  </button>
                </div>
                <p className="hero-caption">
                  Backend · Frontend · QA · UI/UX / Junior и Middle
                </p>
              </div>
              <figure className="hero-artwork">
                <img
                  src="/artwork"
                  alt="Авторский бумажный коллаж пересекающихся путей"
                />
                <figcaption>От навыков — к предложению с условиями</figcaption>
              </figure>
            </section>
            <Showcase />
            <section
              className="role-paths"
              aria-label="Путь кандидата и работодателя"
            >
              <article>
                <p className="eyebrow">Кандидату</p>
                <h2>
                  Покажите навыки.
                  <br />
                  Выбирайте условия.
                </h2>
                <ol className="workflow-steps">
                  <li>
                    <strong>Заполните профиль</strong>
                    <small>
                      Укажите специализацию, желаемый уровень и свои условия.
                    </small>
                  </li>
                  <li>
                    <strong>Пройдите оценку</strong>
                    <small>
                      Результат определит категорию. Опубликуйте её в
                      «Приватности».
                    </small>
                  </li>
                  <li>
                    <strong>Получите предложение</strong>
                    <small>
                      Узнайте зарплату и задачи, затем решите, кому открыть
                      контакт.
                    </small>
                  </li>
                </ol>
              </article>
              <article>
                <p className="eyebrow">Работодателю</p>
                <h2>
                  Начните с потребности.
                  <br />
                  Пригласите человека.
                </h2>
                <ol className="workflow-steps">
                  <li>
                    <strong>Опишите потребность</strong>
                    <small>
                      Выберите специализацию, грейд, стек, формат и бюджет.
                    </small>
                  </li>
                  <li>
                    <strong>Сравните подборку</strong>
                    <small>
                      Категория, результат оценки и навыки объясняют порядок
                      выдачи.
                    </small>
                  </li>
                  <li>
                    <strong>Предложите условия</strong>
                    <small>
                      Приглашение с зарплатой не требует отдельной вакансии.
                    </small>
                  </li>
                </ol>
              </article>
            </section>
            <section
              className="product-principles"
              aria-label="Как работают оценка и доступ"
            >
              <div>
                <h3>Оценка определяет категорию</h3>
                <p>
                  Анкета описывает опыт. Категорию для поиска присваивает
                  отдельная оценочная форма.
                </p>
              </div>
              <div>
                <h3>Практика даёт свежий сигнал</h3>
                <p>
                  Наборы и короткие задачи показывают решение и обратную связь.
                  Они не повышают глобальный грейд.
                </p>
              </div>
              <div>
                <h3>Контакт открывается адресно</h3>
                <p>
                  После принятого приглашения или вашего отклика — только
                  выбранной компании. Доступ можно отозвать.
                </p>
              </div>
            </section>
            {accountsReady && accounts.length > 0 && (
            <section>
              <div className="section-heading">
                <h2 id="demo-cabinets" tabIndex={-1}>
                  Пройти сценарий
                </h2>
                <span className="muted">
                  Готовые тестовые профили и компании
                </span>
              </div>
              <p>
                Выберите тестовый кабинет. Для проверки приватности доступны два
                кандидата и две независимые компании.
              </p>
              <div className="account-list">
                {accounts.map((a) => (
                  <button
                    key={a.id}
                    disabled={busy}
                    onClick={() => void login(a.id)}
                  >
                    {a.label}
                    <span>
                      {a.role === "candidate" ? "Кандидат" : "Работодатель"}
                    </span>
                  </button>
                ))}
              </div>
            </section>
            )}
            <Auth
              blank={accountsReady && accounts.length === 0}
              passwordOnly={authMode === "shared-password"}
              individualRegistration={authMode === "individual"}
              onLogin={(u) => {
                setCsrf(u.csrf || "");
                setUser(u);
                setCopyStatus("");
              }}
            />
          </>
        )}
        <footer>
          <span>ФСП · Карьерный профиль / конкурсный стенд</span>
          <div className="footer-links">
            <a href="/legal/privacy">Политика данных тестового стенда</a>
            <a href="/legal/recommendations">Правила подбора</a>
            <a href="/api/docs" target="_blank" rel="noreferrer">
              Документация API
            </a>
            <a href="/api/openapi.json" target="_blank" rel="noreferrer">
              OpenAPI JSON
            </a>
          </div>
        </footer>
      </main>
    </>
  );
}

function Auth({ onLogin, blank = false, passwordOnly = false, individualRegistration = false }: {
  onLogin: (u: Account) => void;
  blank?: boolean;
  passwordOnly?: boolean;
  individualRegistration?: boolean;
}) {
  const [tab, setTab] = useState("register"),
    [email, setEmail] = useState("new-candidate@example.invalid"),
    [label, setLabel] = useState("Демо-кандидат"),
    [role, setRole] = useState("candidate"),
    [consent, setConsent] = useState(false),
    [password, setPassword] = useState(""),
    [passwordConfirmation, setPasswordConfirmation] = useState(""),
    [verification, setVerification] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [mails, setMails] = useState<
      { id: string; email: string; token: string; expires_at?: string }[]
    >([]);
  const orderedMails = [...mails].sort((a, b) =>
    Number(b.email === email) - Number(a.email === email) ||
    (b.expires_at || "").localeCompare(a.expires_at || ""),
  );
  const activeTab = passwordOnly ? 'password' : individualRegistration && tab !== "password" ? "jury-register" : tab;
  const mailPages = usePagedItems(orderedMails, 8);
  async function mailbox() {
    try {
      setMails(await api("/auth/mock-mail"));
    } catch {
      setMails([]);
      setMessage("Локальная почта отключена: ссылка отправлена на указанный адрес.");
    }
    mailPages.setPage(1);
  }
  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (activeTab === "jury-register") {
        if (password !== passwordConfirmation) throw new Error("Пароли не совпадают");
        const account = await api<Account>("/auth/jury-register", "POST", { role, password, consent });
        setPassword("");
        setPasswordConfirmation("");
        onLogin(account);
        return;
      }
      if (activeTab === "password") {
        onLogin(await api("/auth/password-login", "POST", { email, password }));
        setPassword("");
        return;
      }
      const sent = await api<{ delivery?: string; message?: string }>(
        activeTab === "register" ? "/auth/register" : "/auth/login",
        "POST",
        activeTab === "register"
          ? { email, label, role, consent, password }
          : { email },
      );
      setMessage(
        "Письмо помещено в локальную mock-почту. Подтвердите вход ниже.",
      );
      if (sent.delivery === "failed")
        setError(sent.message || "SMTP недоступен");
      await mailbox();
      setTab("mail");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function verify(token: string) {
    setBusy(true);
    try {
      onLogin(await api("/auth/verify", "POST", { token }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  // «Живой» режим без демо-входа: пустые поля, как на обычном сайте.
  useEffect(() => {
    if (blank) {
      setEmail("");
      setLabel("");
    }
  }, [blank]);
  return (
    <section className="auth">
      <h2 id="own-account" tabIndex={-1}>
        {passwordOnly ? 'Парольный доступ жюри' : individualRegistration ? 'Индивидуальный тестовый аккаунт' : 'Свой тестовый аккаунт'}
      </h2>
      {!passwordOnly && <div className="tabs">
        <button
          aria-pressed={tab === "password"}
          onClick={() => setTab("password")}
        >
          {individualRegistration ? "Войти" : "Вход с паролем"}
        </button>
        {!individualRegistration && <>
        <button
          aria-pressed={tab === "register"}
          onClick={() => setTab("register")}
        >
          Регистрация
        </button>
        <button aria-pressed={tab === "login"} onClick={() => setTab("login")}>
          Вход по почте
        </button>
        <button
          aria-pressed={tab === "mail"}
          onClick={() => {
            setTab("mail");
            void mailbox().catch((e) => setError(e.message));
          }}
        >
          Mock-почта
        </button>
        </>}
        {individualRegistration && (
          <button aria-pressed={activeTab === "jury-register"} onClick={() => setTab("register")}>
            Создать аккаунт
          </button>
        )}
      </div>}
      <p className="muted">
        {passwordOnly
          ? 'Тестовый стенд в России. Используйте выданный синтетический аккаунт и пароль. Регистрация и почта отключены. Не вводите реальные персональные данные.'
          : individualRegistration
            ? 'Стенд сам создаст синтетический логин. Сохраните его для повторного входа. Почта не требуется; не вводите данные реальных людей.'
          : 'Принимаются только адреса name@example.invalid. По умолчанию письма остаются в локальном ящике, доступном всем участникам этого стенда; SMTP требует отдельного включения администратором.'}
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {activeTab === "mail" ? (
        <div>
          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              void verify(verification);
            }}
          >
            <label>
              Код из письма
              <input
                required
                minLength={20}
                maxLength={128}
                autoComplete="off"
                value={verification}
                onChange={(e) => setVerification(e.target.value)}
              />
            </label>
            <button className="primary" disabled={busy}>
              Подтвердить код
            </button>
          </form>
          {mails.length === 0 ? (
            <p>Нет новых писем.</p>
          ) : (
            mailPages.visibleItems.map((m) => (
              <div className="mail-row" key={m.id}>
                <span>{m.email}</span>
                <button disabled={busy} onClick={() => void verify(m.token)}>
                  Подтвердить вход
                </button>
              </div>
            ))
          )}
          <Pagination
            label="Письма демонстрационного ящика"
            total={mails.length}
            page={mailPages.page}
            pages={mailPages.pages}
            start={mailPages.start}
            end={mailPages.end}
            onPageChange={mailPages.setPage}
            disabled={busy}
          />
        </div>
      ) : (
        <form onSubmit={(e) => void send(e)} className="form-grid">
          {activeTab !== "jury-register" && <label>
            Демонстрационная почта
            <input
              type="email"
              required
              placeholder="name@example.invalid"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>}
          {(activeTab === "register" || activeTab === "password" || activeTab === "jury-register") && (
            <label>
              Пароль
              <input
                type="password"
                aria-label="Пароль"
                aria-describedby="password-hint"
                required
                minLength={12}
                maxLength={128}
                autoComplete={
                  activeTab === "register" || activeTab === "jury-register" ? "new-password" : "current-password"
                }
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <span className="muted" id="password-hint">
                От 12 символов; пароль не сохраняется в браузере.
              </span>
            </label>
          )}
          {activeTab === "jury-register" && (
            <label>
              Повторите пароль
              <input
                type="password"
                aria-label="Повторите пароль"
                required
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
                value={passwordConfirmation}
                onChange={(e) => setPasswordConfirmation(e.target.value)}
              />
            </label>
          )}
          {activeTab === "register" && (
            <>
              <label>
                Имя тестового профиля или команды
                <input
                  required
                  minLength={2}
                  maxLength={120}
                  placeholder="Как вас назвать"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </label>
              <label>
                Кабинет
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="candidate">Кандидат</option>
                  <option value="employer">Работодатель</option>
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={consent}
                  required
                  onChange={(e) => setConsent(e.target.checked)}
                />
                Согласен на сохранение синтетических данных локального пилота
              </label>
            </>
          )}
          {activeTab === "jury-register" && (
            <>
              <label>
                Кабинет
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="candidate">Кандидат</option>
                  <option value="employer">Работодатель</option>
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={consent}
                  required
                  onChange={(e) => setConsent(e.target.checked)}
                />
                Использую только синтетические данные и не ввожу данные реальных людей
              </label>
            </>
          )}
          <div className="full">
            <button className="primary" disabled={busy}>
              {activeTab === "jury-register"
                ? "Создать отдельный аккаунт"
                : activeTab === "register"
                ? "Создать тестовый аккаунт"
                : activeTab === "password"
                  ? "Войти с паролем"
                  : "Получить ссылку входа"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function Dashboard({ user }: { user: Account }) {
  const candidate = user.role === "candidate";
  const tabs = candidate
    ? [
        ["profile", "Профиль"],
        ["assessment", "Оценка"],
        ["practice", "Практические наборы"],
        ["history", "История"],
        ["offers", "Входящие"],
        ["messages", "Сообщения"],
        ["vacancies", "Вакансии"],
        ["applications", "Мои отклики"],
        ["tasks", "Короткие задания"],
        ["privacy", "Приватность"],
      ]
    : [
        ["bank", "Банк кандидатов"],
        ["needs", "Потребности"],
        ["shortlist", "Мой список"],
        ["offers", "Отправленные"],
        ["messages", "Сообщения"],
        ["company", "Компания"],
        ["vacancies", "Вакансии"],
        ["applications", "Отклики"],
        ["tasks", "Задания"],
        ["banks", "Конструктор заданий"],
      ];
  const route = useRoute();
  const role = candidate ? "candidate" : "employer";
  const tab =
    route[0] === role && tabs.some(([id]) => id === route[1])
      ? route[1]
      : tabs[0][0];
  const setTab = (value: string) => navigate("/" + role + "/" + value);
  const navigationGroups = candidate
    ? [
        {
          title: "Профиль и категория",
          keys: ["profile", "assessment", "history"],
        },
        { title: "Предложения", keys: ["offers", "messages", "vacancies", "applications"] },
        { title: "Практика", keys: ["practice", "tasks"] },
        { title: "Доступ", keys: ["privacy"] },
      ]
    : [
        { title: "Подбор специалистов", keys: ["bank", "needs", "shortlist"] },
        {
          title: "Взаимодействие",
          keys: ["offers", "messages", "vacancies", "applications"],
        },
        { title: "Рабочее пространство", keys: ["company", "tasks", "banks"] },
      ];
  const descriptions: Record<string, string> = candidate
    ? {
        profile:
          "Сначала сохраните анкету и свои условия, затем пройдите оценку. Работодатель увидит подтверждённую категорию после вашей публикации.",
        assessment:
          "Эта оценка определяет категорию и грейд. Неудачная попытка не понижает ранее подтверждённый уровень; практика находится в отдельном разделе.",
        history:
          "Ваши формы, результаты и изменения категории. Прошлые оценки сохраняются, даже если задания или специализация изменились.",
        offers:
          "Компания начинает общение с задач и зарплаты. Примите подходящее предложение, чтобы разрешить контакт именно этой компании.",
        messages:
          "Переписка с компаниями, чей контакт вы открыли принятым предложением или откликом. Отозвав контакт, вы прекращаете новые сообщения; история остаётся.",
        vacancies:
          "Дополнительный путь к знакомству: самостоятельный отклик открывает ваш контакт выбранной компании. Основной сценарий — приглашение от работодателя.",
        applications:
          "Здесь видны ваши отклики и их статусы. Отзыв отклика и доступ к контакту проверяются для каждой компании отдельно.",
        practice:
          "Решите опубликованный набор и получите результат или обратную связь автора. Практика не меняет категорию и глобальный грейд.",
        tasks:
          "Короткие задачи от компаний помогают поддерживать профиль в актуальном состоянии. Автор проверяет открытый ответ и оставляет обратную связь.",
        privacy:
          "Публикация категории и разрешение контакта — разные действия. Управляйте видимостью профиля, получателями контакта и тестовой связью с ФСП.",
      }
    : {
        bank: "Сравните специалистов по подтверждённой категории, навыкам и объяснению подбора. Затем направьте персональное предложение с зарплатой.",
        needs:
          "Опишите, кого и для каких задач ищет команда. Специализация, навыки, формат и бюджет сформируют подборку; результаты поиска можно сохранить.",
        shortlist:
          "Сохранённые кандидаты для сравнения. Контакт появится после принятия вашего приглашения или самостоятельного отклика кандидата.",
        offers:
          "Условия отправлены конкретному кандидату. Следите за статусом: принятие открывает контакт вашей компании, отзыв кандидата прекращает доступ.",
        messages:
          "Диалог доступен с кандидатами, принявшими приглашение или откликнувшимися сами. Если кандидат отзовёт контакт, новые сообщения отправить нельзя.",
        company:
          "Описание и способ связи доступны вместе с вашим предложением. Заполните их, чтобы кандидат понимал, кто и с какой задачей приглашает его.",
        vacancies:
          "Опубликуйте задачи и зарплату для добровольных откликов. Для персонального приглашения отдельная вакансия не обязательна.",
        applications:
          "Кандидат сам выбрал вашу вакансию. Доступ к его контакту зависит от активного отклика или отдельно принятого приглашения.",
        tasks:
          "Короткое задание даёт свежий сигнал о подходе кандидата. Оцените ответ по рубрике и передайте содержательную обратную связь.",
        banks:
          "Создайте набор или загрузите готовые материалы. Проверьте кандидатский предпросмотр перед публикацией; открытые ответы оценивает автор.",
      };
  const nextAction = candidate
    ? tab === "history"
      ? { tab: "assessment", label: "Проверить условия новой оценки" }
      : tab === "offers" || tab === "applications"
        ? { tab: "privacy", label: "Кто видит мой контакт" }
        : null
    : tab === "shortlist"
      ? { tab: "bank", label: "Вернуться к подборке" }
      : tab === "offers"
        ? { tab: "bank", label: "Выбрать следующего кандидата" }
        : null;
  const [bankKey, setBankKey] = useState(0);
  const unreadMessages = useUnreadMessages(role);
  const heading = useRef<HTMLHeadingElement>(null);
  const priorTab = useRef(tab);
  useLayoutEffect(() => {
    window.scrollTo(0, 0);
  }, [user.id]);
  useEffect(() => {
    if (priorTab.current !== tab) {
      heading.current?.focus({ preventScroll: true });
      priorTab.current = tab;
    }
    document.title = `${tabs.find(([id]) => id === tab)?.[1]} — ФСП / Карьерный профиль`;
  }, [tab]);
  function fromNeed(q: NeedQuery) {
    const p = new URLSearchParams({
      spec: q.specialization,
      grade: q.grade,
      format: q.format,
      salary: String(q.salary_to),
      must: q.must_skills.join(","),
      desired: q.desired_skills.join(","),
      work_tasks: (q.work_tasks || []).join(","),
      fsp: q.fsp_only ? "1" : "0",
    });
    window.history.replaceState(null, "", "?" + p + window.location.hash);
    setBankKey(bankKey + 1);
    setTab("bank");
  }
  return (
    <div className="dashboard-layout">
      <aside className="workspace-sidebar">
        <p className="eyebrow">{candidate ? "Кандидат" : "Работодатель"}</p>
        <nav className="workspace-nav" aria-label="Разделы кабинета">
          {navigationGroups.map((group) => (
            <div className="nav-group" key={group.title}>
              <p className="nav-group-title">{group.title}</p>
              {group.keys.map((key) => (
                <button
                  key={key}
                  aria-pressed={tab === key}
                  aria-current={tab === key ? "page" : undefined}
                  onClick={() => setTab(key)}
                >
                  {tabs.find(([id]) => id === key)?.[1]}
                  {key === "messages" && unreadMessages > 0
                    ? ` (${unreadMessages})`
                    : ""}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <p className="sidebar-note">
          Навыки — открыто.
          <br />
          Контакты — по согласию.
        </p>
      </aside>
      <div className="workspace-body">
        <div className="page-heading">
          <p className="eyebrow">
            {candidate ? "Кабинет кандидата" : "Кабинет работодателя"}
          </p>
          <h1 className="workspace-heading" ref={heading} tabIndex={-1}>
            {tabs.find(([id]) => id === tab)?.[1]}
          </h1>
          <div className="page-context">
            <p>{descriptions[tab]}</p>
            {nextAction && (
              <button
                className="context-action"
                onClick={() => setTab(nextAction.tab)}
              >
                {nextAction.label}
              </button>
            )}
          </div>
        </div>
        <div className="page-transition" key={tab}>
          {tab === "banks" ? (
            <BanksWorkspace bankId={route[2]} />
          ) : tab === "practice" ? (
            <BankAssessment attemptId={route[2]} />
          ) : tab === "messages" ? (
            <Messages
              role={user.role}
              selected={route[2] ? decodeURIComponent(route[2]) : undefined}
            />
          ) : tab === "vacancies" ? (
            <Vacancies role={user.role} />
          ) : tab === "applications" ? (
            <Applications role={user.role} />
          ) : tab === "tasks" ? (
            candidate ? (
              <CandidateTasks />
            ) : (
              <EmployerTasks />
            )
          ) : candidate ? (
            tab === "profile" ? (
              <ProfileEditor />
            ) : tab === "assessment" ? (
              <Assessment attemptId={route[2]} />
            ) : tab === "history" ? (
              <AssessmentHistory onReview={(id) => navigate(`/candidate/assessment/${id}`)} />
            ) : tab === "privacy" ? (
              <Privacy />
            ) : (
              <Offers role="candidate" />
            )
          ) : tab === "company" ? (
            <CompanyEditor />
          ) : tab === "needs" ? (
            <Needs onSearch={fromNeed} />
          ) : tab === "offers" ? (
            <Offers role="employer" />
          ) : (
            <Bank key={tab + bankKey} shortlist={tab === "shortlist"} />
          )}
        </div>
      </div>
    </div>
  );
}

function ProfileEditor() {
  const juryMode = React.useContext(JuryModeContext);
  const { catalog, error: catalogError } = useSkillsWorkCatalog();
  const [profile, setProfile] = useState<Profile | null>(null),
    [nextReady, setNextReady] = useState(false),
    [imported, setImported] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const load = () =>
    api<Profile>("/candidate/profile").then((p) =>
      setProfile({ ...p, resume: { ...blankResume, ...p.resume } }),
    );
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setBusy(true);
    setError("");
    try {
      await api("/candidate/profile", "PUT", {
        industry: "it",
        specialization: profile.specialization,
        claimed_grade: profile.claimed_grade,
        salary_min: profile.salary_min,
        formats: profile.formats,
        contact: profile.contact,
        resume: profile.resume,
      });
      await load();
      setMessage(
        "Профиль сохранён. Заявленный уровень не меняет результат оценки.",
      );
      setNextReady(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function resume(patch: Partial<Resume>) {
    if (profile)
      setProfile({ ...profile, resume: { ...profile.resume, ...patch } });
  }
  return (
    <section>
      <div className="section-heading">
        <h2>Профиль и анкета</h2>
        <a href="/api/v1/candidate/profile.pdf">{juryMode ? 'Скачать тестовый профиль PDF' : 'Скачать свой PDF'}</a>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!profile ? (
        <p>Загрузка…</p>
      ) : (
        <>
          <p className="evidence">
            {specs[profile.specialization]?.label} /{" "}
            {gradeName(profile.confirmed_grade)} · оценка {profile.test_score}
            /100 · {profile.skills.join(", ") || "Навыки пока не подтверждены"}
          </p>
          <SkillEvidence evidence={profile.skill_evidence} />
          <WeeklyTaskNotice key={`${profile.specialization}:${profile.confirmed_grade}`} />
          {juryMode ? <p>Импорт PDF отключён в тестовом стенде жюри</p> : <label>
            Импорт текстового PDF · до 2 МБ
            <input
              type="file"
              accept="application/pdf"
              disabled={juryMode || busy || !catalog}
              aria-describedby={!catalog ? "resume-import-state" : undefined}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (juryMode || !file || !catalog) return;
                const declaredSkillIds = new Set(
                  catalog.declared_skills.map((skill) => skill.id),
                );
                const uploadStart = {
                  contact: profile.contact,
                  specialization: profile.specialization,
                  claimed_grade: profile.claimed_grade,
                  resume: {
                    ...profile.resume,
                    declared_skills: [...profile.resume.declared_skills],
                    roles: [...profile.resume.roles],
                    soft_skills: [...profile.resume.soft_skills],
                  },
                };
                setNextReady(false);
                setBusy(true);
                setError("");
                void fetch("/api/v1/candidate/resume-preview", {
                  method: "POST",
                  credentials: "same-origin",
                  headers: {
                    "Content-Type": "application/pdf",
                    "X-CSRF-Token": getCsrf(),
                  },
                  body: file,
                })
                  .then(async (response) => {
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.message);
                    const importedResume: Resume = {
                      ...blankResume,
                      ...(data.resume || {}),
                    };
                    const importedDeclaredSkills = Array.isArray(data.claimed_skills)
                      ? data.claimed_skills.filter(
                          (skill: unknown): skill is string =>
                            typeof skill === "string" && declaredSkillIds.has(skill),
                        )
                      : [];
                    setProfile((current) => {
                      if (!current) return current;
                      const unchanged = (value: unknown, initial: unknown) =>
                        Array.isArray(value) && Array.isArray(initial)
                          ? JSON.stringify(value) === JSON.stringify(initial)
                          : value === initial;
                      const importIfUnchanged = <K extends keyof Resume,>(key: K) =>
                        unchanged(current.resume[key], uploadStart.resume[key])
                          ? importedResume[key]
                          : current.resume[key];
                      const existingDeclaredSkills =
                        current.resume.declared_skills.filter((skill) =>
                          declaredSkillIds.has(skill),
                        );
                      return {
                        ...current,
                        resume: {
                          ...current.resume,
                          full_name: importIfUnchanged("full_name"),
                          years_experience: importIfUnchanged("years_experience"),
                          roles: importIfUnchanged("roles"),
                          soft_skills: importIfUnchanged("soft_skills"),
                          education: importIfUnchanged("education"),
                          about: importIfUnchanged("about"),
                          declared_skills: [
                            ...new Set([
                              ...existingDeclaredSkills,
                              ...importedDeclaredSkills,
                            ]),
                          ],
                        },
                        contact:
                          current.contact === uploadStart.contact && data.contact
                            ? data.contact
                            : current.contact,
                        specialization:
                          current.specialization === uploadStart.specialization
                            ? data.specialization
                            : current.specialization,
                        claimed_grade:
                          current.claimed_grade === uploadStart.claimed_grade
                            ? data.claimed_grade
                            : current.claimed_grade,
                      };
                    });
                    setImported(true);
                    setMessage(data.warnings.join(" "));
                  })
                  .catch((e) => setError(e.message))
                  .finally(() => setBusy(false));
              }}
            />
          </label>}
          {!juryMode && !catalog && (
            <p
              id="resume-import-state"
              className={catalogError ? "error" : "muted"}
            >
              {catalogError
                ? `Импорт PDF недоступен: ${catalogError}`
                : "Загрузка каталога технологий… Импорт PDF станет доступен после загрузки."}
            </p>
          )}
          {imported && (
            <p className="muted">
              Поля ниже — предложения из PDF. Проверьте их и нажмите «Сохранить
              профиль»; файл не сохраняется.
            </p>
          )}
          <form
            className="form-grid"
            onSubmit={(e) => void save(e)}
            onChangeCapture={() => setNextReady(false)}
          >
            <label>
              Отрасль
              <input value="Информационные технологии" readOnly />
            </label>
            <SpecSelect
              value={profile.specialization}
              onChange={(specialization) =>
                setProfile({ ...profile, specialization })
              }
            />
            <label>
              Заявленный уровень
              <select
                value={profile.claimed_grade}
                onChange={(e) =>
                  setProfile({ ...profile, claimed_grade: e.target.value })
                }
              >
                <option value="junior">Junior</option>
                <option value="middle">Middle</option>
              </select>
            </label>
            <label>
              Имя синтетического кандидата
              <input
                required
                minLength={2}
                maxLength={120}
                value={profile.resume.full_name}
                onChange={(e) => resume({ full_name: e.target.value })}
              />
            </label>
            <label>
              Стаж, лет
              <input
                type="number"
                min={0}
                max={60}
                required
                value={profile.resume.years_experience}
                onChange={(e) =>
                  resume({ years_experience: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Ожидаемая зарплата от, руб./мес.
              <input
                type="number"
                min={0}
                max={10000000}
                required
                value={profile.salary_min}
                onChange={(e) =>
                  setProfile({ ...profile, salary_min: Number(e.target.value) })
                }
              />
            </label>
            <label>
              Формат работы
              <select
                value={profile.formats[0]}
                onChange={(e) =>
                  setProfile({ ...profile, formats: [e.target.value] })
                }
              >
                <option value="remote">Удалённо</option>
                <option value="hybrid">Гибрид</option>
                <option value="office">В офисе</option>
              </select>
            </label>
            <label>
              Скрытый контакт · только example.invalid
              <input
                type="email"
                required
                value={profile.contact}
                onChange={(e) =>
                  setProfile({ ...profile, contact: e.target.value })
                }
              />
            </label>
            <fieldset className="full declared-skills">
              <legend>Заявленные технологии</legend>
              <p className="muted">Выберите технологии, с которыми работали. Это сведения анкеты: они не подтверждают навыки и не меняют категорию.</p>
              {catalogError && <p role="alert" className="error">{catalogError}</p>}
              {!catalog && !catalogError && <p>Загрузка технологий…</p>}
              {(catalog?.declared_skills || []).filter((skill) => skill.specializations.includes(profile.specialization) || profile.resume.declared_skills.includes(skill.id)).map((skill) => <label className="check" key={skill.id}>
                <input type="checkbox" checked={profile.resume.declared_skills.includes(skill.id)} onChange={(e) => resume({ declared_skills: e.target.checked ? [...profile.resume.declared_skills, skill.id] : profile.resume.declared_skills.filter((id) => id !== skill.id) })} />
                {skill.label}
              </label>)}
            </fieldset>
            <fieldset className="full">
              <legend>Заявленные роли</legend>
              {Object.entries({
                developer: "Разработчик",
                tester: "Тестировщик",
                "team-lead": "Руководитель команды",
                analyst: "Аналитик",
                designer: "Дизайнер",
              }).map(([key, title]) => (
                <label className="check" key={key}>
                  <input
                    type="checkbox"
                    checked={profile.resume.roles.includes(key)}
                    onChange={(e) =>
                      resume({
                        roles: e.target.checked
                          ? [...profile.resume.roles, key]
                          : profile.resume.roles.filter((x) => x !== key),
                      })
                    }
                  />
                  {title}
                </label>
              ))}
            </fieldset>
            <fieldset className="full">
              <legend>Заявленные софт-навыки</legend>
              {Object.entries({
                communication: "Коммуникация",
                teamwork: "Командная работа",
                planning: "Планирование",
                mentoring: "Наставничество",
              }).map(([key, title]) => (
                <label className="check" key={key}>
                  <input
                    type="checkbox"
                    checked={profile.resume.soft_skills.includes(key)}
                    onChange={(e) =>
                      resume({
                        soft_skills: e.target.checked
                          ? [...profile.resume.soft_skills, key]
                          : profile.resume.soft_skills.filter((x) => x !== key),
                      })
                    }
                  />
                  {title}
                </label>
              ))}
            </fieldset>
            <label className="full">
              Образование · синтетическое описание
              <textarea
                maxLength={1000}
                value={profile.resume.education}
                onChange={(e) => resume({ education: e.target.value })}
              />
            </label>
            <label className="full">
              О себе · скрыто до разрешения контакта
              <textarea
                maxLength={2000}
                value={profile.resume.about}
                onChange={(e) => resume({ about: e.target.value })}
              />
            </label>
            <div className="full">
              <button className="primary" disabled={busy}>
                Сохранить профиль
              </button>
            </div>
          </form>
          {message && <p role="status">{message}</p>}
          {nextReady && (
            <div className="next-step">
              <div>
                <p className="eyebrow">Следующий шаг</p>
                <p>
                  {profile.confirmed_grade
                    ? "Категория подтверждена. Вы решаете, публиковать ли профиль и кому разрешить контакт."
                    : "Анкета сохранена. Категория появится после оценки на заявленный уровень."}
                </p>
              </div>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  navigate(
                    profile.confirmed_grade
                      ? "/candidate/privacy"
                      : "/candidate/assessment",
                  )
                }
              >
                {profile.confirmed_grade
                  ? "Настроить видимость профиля"
                  : "Продолжить к оценке"}
              </button>
            </div>
          )}
          <p className="muted">
            Категорию определяет оценка, а не анкета. Смена специализации
            скрывает профиль до новой оценки или восстановления подтверждения
            этой специализации. Публикация и контакт — в «Приватности».
          </p>
        </>
      )}
    </section>
  );
}

function Assessment({ attemptId }: { attemptId?: string }) {
  const [grade, setGrade] = useState("junior"),
    [spec, setSpec] = useState("backend"),
    [vacancy, setVacancy] = useState(""),
    [vacancies, setVacancies] = useState<
      { id: string; title: string; specialization: string; grade: string }[]
    >([]),
    [attempt, setAttempt] = useState<Attempt | null>(null),
    [answers, setAnswers] = useState<Record<string, string>>({}),
    [result, setResult] = useState<Result | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false),
    [navigating, setNavigating] = useState(false),
    [draftStatus, setDraftStatus] = useState(""),
    [remaining, setRemaining] = useState(3600),
    [questionPage, setQuestionPage] = useState(1),
    [confirmFinish, setConfirmFinish] = useState(false);
  const answerGeneration = useRef(0),
    savedGeneration = useRef(0),
    answersRef = useRef(answers),
    attemptRef = useRef(attempt),
    finishDialog = useRef<HTMLDialogElement | null>(null),
    finishTrigger = useRef<HTMLButtonElement | null>(null),
    questionPanel = useRef<HTMLFieldSetElement | null>(null),
    attemptEpoch = useRef(0);
  attemptRef.current = attempt;
  answersRef.current = answers;
  const pendingSave = useRef<Promise<void> | null>(null);
  const monitor = useRef<IntegrityMonitor | null>(null);
  const examMode = useExamMode(Boolean(attempt?.id && !result && !attempt.result));
  useEffect(() => {
    if (!attempt?.id || result || attempt.result) return;
    const started = startIntegrityMonitor(attempt.id);
    monitor.current = started;
    return () => {
      started.stop();
      monitor.current = null;
    };
  }, [attempt?.id, Boolean(result), Boolean(attempt?.result)]);
  function replaceAnswers(next: Record<string, string>) {
    answersRef.current = next;
    setAnswers(next);
  }
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
    if (examMode.paused && confirmFinish) {
      finishDialog.current?.close();
      setConfirmFinish(false);
    }
  }, [examMode.paused, confirmFinish]);
  async function saveDraft() {
    while (pendingSave.current) await pendingSave.current;
    const current = attemptRef.current;
    if (
      !current ||
      answerGeneration.current === savedGeneration.current ||
      result
    )
      return;
    const epoch = attemptEpoch.current;
    const generation = answerGeneration.current;
    const snapshot = { ...answersRef.current };
    const request = api<Attempt>(
      `/assessments/attempts/${current.id}/draft`,
      "PUT",
      { answers: snapshot, expected_revision: current.revision || 0 },
    ).then((updated) => {
      if (attemptEpoch.current !== epoch || attemptRef.current?.id !== current.id)
        return;
      attemptRef.current = updated;
      setAttempt(updated);
      savedGeneration.current = generation;
      setDraftStatus("Ответы сохранены на сервере");
    });
    pendingSave.current = request;
    try {
      await request;
    } finally {
      if (pendingSave.current === request) pendingSave.current = null;
    }
  }
  async function flushDraft() {
    do {
      await saveDraft();
    } while (
      answerGeneration.current !== savedGeneration.current &&
      attemptRef.current &&
      !result
    );
  }
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (
        (attemptRef.current && !attemptRef.current.result && !result) ||
        pendingSave.current ||
        (answerGeneration.current !== savedGeneration.current && !result)
      )
        event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [result]);
  useNavigationGuard(async () => {
    const activeAttempt = Boolean(attemptRef.current && !attemptRef.current.result && !result);
    const expiredUnsaved = remaining === 0 && answerGeneration.current !== savedGeneration.current;
    if (activeAttempt) {
      const message = expiredUnsaved
        ? "Время оценки закончилось. Несохранённый ответ не будет отправлен; подтверждённый сервером черновик останется в истории. Покинуть оценку?"
        : remaining === 0
          ? "Время оценки закончилось. Сохранённые ответы останутся в истории. Покинуть оценку?"
          : "Покинуть оценку? Ответы сохраняются в черновике, а время попытки продолжит идти.";
      if (!window.confirm(message)) return false;
      if (expiredUnsaved) return true;
    }
    setNavigating(true);
    try {
      if (expiredUnsaved) {
        const leave = window.confirm(
          "Время оценки закончилось. Несохранённый ответ не будет отправлен; подтверждённый сервером черновик останется в истории. Перейти дальше?",
        );
        if (!leave) setError("Переход отменён. Ответ остаётся в открытой форме.");
        return leave;
      }
      await flushDraft();
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
  useEffect(() => {
    if (
      !attempt ||
      result ||
      busy ||
      answerGeneration.current === savedGeneration.current
    )
      return;
    const timer = setTimeout(() => {
      void saveDraft().catch((e) => {
        setError(e.message);
        setDraftStatus("Ответы не сохранены. Не закрывайте страницу");
      });
    }, 750);
    return () => clearTimeout(timer);
  }, [answers, busy, result, attempt?.revision]);
  useEffect(() => {
    if (!attempt?.expires_at) return;
    const tick = () =>
      setRemaining(
        Math.max(
          0,
          Math.ceil(
            (new Date(attempt.expires_at!).getTime() - Date.now()) / 1000,
          ),
        ),
      );
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [attempt?.expires_at]);
  useEffect(() => {
    let active = true;
    const epoch = ++attemptEpoch.current;
    setLoaded(false);
    setAttempt(null);
    attemptRef.current = null;
    replaceAnswers({});
    answerGeneration.current = 0;
    savedGeneration.current = 0;
    pendingSave.current = null;
    setResult(null);
    setQuestionPage(1);
    setConfirmFinish(false);
    setError("");
    void api<Attempt | null>(attemptId
      ? `/assessments/attempts/${attemptId}`
      : "/candidate/active-assessment")
      .then((a) => {
        if (active && attemptEpoch.current === epoch && a) {
          attemptRef.current = a;
          setAttempt(a);
          replaceAnswers(a.answers || {});
          setResult(a.result || null);
          if (a.specialization) setSpec(a.specialization);
          setGrade(a.grade);
          setDraftStatus(a.result ? "Результат сохранён" : "Продолжение сохранённой попытки");
        }
      })
      .catch((e) => { if (active && attemptEpoch.current === epoch) setError(e.message); })
      .finally(() => { if (active && attemptEpoch.current === epoch) setLoaded(true); });
    return () => { active = false; };
  }, [attemptId]);
  useEffect(() => {
    if (attemptId) return;
    let active = true;
    void api<Profile>("/candidate/profile")
      .then((p) => {
        if (active) {
          setSpec(p.specialization);
          setGrade(p.claimed_grade);
        }
      })
      .catch((e) => { if (active) setError(e.message); });
    void api<typeof vacancies>("/candidate/vacancies")
      .then((values) => { if (active) setVacancies(values); })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [attemptId]);
  async function start(confirmation?: { specialization: string; grade: string }) {
    setBusy(true);
    setError("");
    try {
      const started = await api<Attempt>("/assessments/attempts", "POST", {
          specialization: confirmation?.specialization ?? spec,
          grade: confirmation?.grade ?? grade,
          vacancy_id: confirmation ? null : vacancy || null,
        });
      setAttempt(started);
      attemptRef.current = started;
      attemptEpoch.current++;
      replaceAnswers(started.answers || {});
      answerGeneration.current = 0;
      savedGeneration.current = 0;
      setQuestionPage(1);
      setConfirmFinish(false);
      setDraftStatus(started.result ? "Результат сохранён" : started.answers && Object.keys(started.answers).length ? "Продолжение сохранённой попытки" : "Новая попытка сохранена");
      setResult(started.result || null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function submit() {
    if (!attempt) return;
    setBusy(true);
    setError("");
    try {
      await flushDraft();
      await monitor.current?.flush();
      setResult(
        await api(`/assessments/attempts/${attempt.id}/submit`, "POST", {
          answers: answersRef.current,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function goAssessmentPage(page: number) {
    if (page === questionPage) return;
    setNavigating(true);
    try {
      if (!result) await flushDraft();
      setQuestionPage(page);
      requestAnimationFrame(() => questionPanel.current?.focus());
    } catch (e) {
      setError((e as Error).message + ". Переход отменён; ответ остался в форме.");
      setDraftStatus("Ответ не сохранён. Не закрывайте страницу");
    } finally {
      setNavigating(false);
    }
  }
  return (
    <section aria-busy={busy || navigating}>
      <h2>{attempt?.version && !["scenarios-v5", "scenarios-v6"].includes(attempt.version) ? "Сохранённая оценка категории" : "Оценка на рабочих сценариях"}</h2>
      <p>
        {specs[spec]?.label}. Задания проверяют решения по навыкам специализации.
        Матрица и веса задаются версией формы. Балл считает сервер. Время —
        60 минут, повтор формы — через 14 суток, смена подтверждённого грейда —
        через 90 суток.
      </p>
      <p className="muted">
        Порог Junior 70, Middle 80. Это проверяемые правила продукта, но не
        независимая профессиональная аттестация. Независимой калибровки нет. Задания не запускают чужой код.
      </p>
      {attempt?.version && <p className="muted">Версия формы: {attempt.version}</p>}
      <p className="muted" id="integrity-notice">
        Во время теста фиксируются типы событий переключения вкладки, потери
        фокуса, копирования, сочетаний клавиш и время ответов; текст вопросов,
        ответов, содержимое буфера и экран не записываются.
        Единичные случаи ничего не меняют. Повторяющиеся признаки попадают в
        пометку «есть замечания» у подтверждённого профиля, а в режиме проверки
        подтверждение откладывается до повторной формы без ожидания 14 суток.
        При уходе со вкладки или из окна вопрос скрывается до вашего возвращения
        и нажатия «Продолжить». Отсчёт 60 минут продолжается. Браузер не может
        запретить другие вкладки, приложения или второе устройство.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!loaded ? (
        <p role="status">Проверяем сохранённую попытку…</p>
      ) : !attempt ? (
        <div className="toolbar">
          <label>
            Уровень
            <select
              value={grade}
              onChange={(e) => {
                setGrade(e.target.value);
                setVacancy("");
              }}
            >
              <option value="junior">Junior</option>
              <option value="middle">Middle</option>
            </select>
          </label>
          <label>
            Отметка вакансии в истории
            <select
              value={vacancy}
              onChange={(e) => setVacancy(e.target.value)}
            >
              <option value="">Без отметки вакансии</option>
              {vacancies
                .filter((v) => v.specialization === spec && v.grade === grade)
                .map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.title}
                  </option>
                ))}
            </select>
          </label>
          <p className="muted">Категорию подтверждает общая форма по специализации и грейду. Здесь вакансия связывается с результатом в истории; задания работодателя доступны отдельно.</p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void start()}
          >
            Начать оценку
          </button>
        </div>
      ) : result ? (
        <>
          <div aria-live="polite" className="result">
            <p className="eyebrow">Результат сохранён</p>
            <h3>
              {result.needs_confirmation
                ? "Результат близок к порогу: нужна подтверждающая форма"
                : result.passed
                  ? "Оценочная форма пройдена"
                  : "Уровень не подтверждён"}
            </h3>
            <p className="score">{result.score} / 100</p>
            <p>
              {result.needs_confirmation
                ? "Попытка не сгорает и ожидать не нужно: пройдите вторую форму с новыми заданиями в течение суток. Итог будет средним по двум формам."
                : result.passed
                  ? "Можно опубликовать профиль в «Приватности»."
                  : "Неудача не понижает ранее подтверждённый грейд."}
            </p>
            {result.stage === 2 && result.stage_scores && (
              <p className="muted">
                Две формы: {result.stage_scores[0]} и {result.stage_scores[1]}; итог — среднее {result.score}.
              </p>
            )}
            <p>{result.limitation}</p>
            {result.integrity && result.integrity.level !== "clean" && (
              <div role="status" className="integrity-note">
                <p>
                  <strong>Проверка добросовестности:</strong>{" "}
                  {result.integrity.hold
                    ? "подтверждение отложено — пройдите форму ещё раз сейчас"
                    : result.integrity.level === "flagged"
                      ? "есть существенные замечания (в этом режиме не блокируют)"
                      : "есть замечания"}
                </p>
                <ul>
                  {result.integrity.signals.map((signal) => (
                    <li key={signal.code}>
                      {signal.message}: {signal.value}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.needs_confirmation ? (
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  void start({ specialization: attempt.specialization || spec, grade: attempt.grade })
                }
              >
                Пройти подтверждающую форму
              </button>
            ) : (
              <button
                className="primary"
                onClick={() =>
                  navigate(
                    result.passed ? "/candidate/privacy" : "/candidate/profile",
                  )
                }
              >
                {result.passed
                  ? "Настроить видимость профиля"
                  : "Вернуться к заявленному уровню"}
              </button>
            )}
          </div>
          <AssessmentReport id={attempt.id} initial={attempt.feedback} />
          <AssessmentQuestion
            attempt={attempt}
            answers={answers}
            page={questionPage}
            onPageChange={setQuestionPage}
            readOnly
          />
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!examMode.paused && !examMode.away) setConfirmFinish(true);
          }}
        >
          <div className="assessment-toolbar">
            <p role="status">{draftStatus}</p>
            <p className="evidence">
              Осталось {Math.floor(remaining / 60)}:
              {String(remaining % 60).padStart(2, "0")}
            </p>
            {!examMode.fullscreenActive && (
              <button type="button" disabled={examMode.paused} onClick={() => void examMode.enterFullscreen()}>
                На весь экран
              </button>
            )}
          </div>
          {examMode.fullscreenMessage && <p role="status" className="muted">{examMode.fullscreenMessage}</p>}
          {remaining === 0 && (
            <div role="alert" className="error">
              <p>Время закончилось. Новые ответы не принимаются; последняя сохранённая сервером версия попытки останется в истории.</p>
              <button type="button" onClick={() => navigate("/candidate/history")}>Открыть историю</button>
            </div>
          )}
          {examMode.paused || examMode.away ? (
            <div className="integrity-note" role="status" aria-live="polite">
              <p>{remaining === 0
                ? "Время оценки истекло. Вопросы больше недоступны; сохранённые ответы смотрите в истории."
                : "Вопрос скрыт, пока оценка приостановлена на этом экране. Время попытки продолжает идти."}</p>
              {remaining > 0 && <>
                <button
                  type="button"
                  disabled={examMode.away}
                  onClick={() => {
                    examMode.resume();
                    requestAnimationFrame(() => questionPanel.current?.focus());
                  }}
                >
                  Продолжить оценку
                </button>
                {examMode.away && <p>Вернитесь к окну с оценкой, чтобы продолжить.</p>}
              </>}
            </div>
          ) : (
            <AssessmentQuestion
              attempt={attempt}
              answers={answers}
              page={questionPage}
              onPageChange={(page) => void goAssessmentPage(page)}
              questionPanelRef={questionPanel}
              disabled={busy || navigating || remaining === 0}
              onAnswer={(questionId, option) => {
                answerGeneration.current++;
                monitor.current?.answer(questionId);
                replaceAnswers({ ...answersRef.current, [questionId]: option });
                setDraftStatus("Сохранение ответа…");
              }}
            />
          )}
          <button
            ref={finishTrigger}
            type="button"
            className="primary"
            disabled={busy || remaining === 0 || examMode.paused || examMode.away}
            onClick={() => setConfirmFinish(true)}
          >
            Отправить ответы
          </button>
          {confirmFinish && (
            <dialog
              ref={finishDialog}
              className="confirmation-panel"
              onCancel={(e) => { e.preventDefault(); closeFinish(); }}
              onKeyDown={containDialogFocus}
              aria-labelledby="assessment-finish-title"
              aria-describedby="assessment-finish-summary"
            >
              <h3 id="assessment-finish-title">Проверка перед отправкой</h3>
              <p id="assessment-finish-summary">
                Отвечено {attempt.questions.filter((q) => Boolean(answers[q.id])).length} из {attempt.questions.length}. Без ответа: {attempt.questions.filter((q) => !answers[q.id]).length}.
              </p>
              {attempt.questions.some((q) => !answers[q.id]) ? (
                <>
                  <p>Заполните все вопросы. Первый пропуск: «{attempt.questions.find((q) => !answers[q.id])?.title}».</p>
                  <div className="actions">
                    <button autoFocus type="button" onClick={() => { const missing = attempt.questions.findIndex((q) => !answers[q.id]) + 1; closeFinish(); void goAssessmentPage(missing); }}>Перейти к пропуску</button>
                    <button type="button" onClick={closeFinish}>Вернуться к ответам</button>
                  </div>
                </>
              ) : (
                <div className="actions">
                  <button autoFocus type="button" onClick={closeFinish}>Вернуться к ответам</button>
                  <button type="button" className="primary" disabled={busy} onClick={() => { closeFinish(); void submit(); }}>Подтвердить отправку</button>
                </div>
              )}
            </dialog>
          )}
        </form>
      )}
    </section>
  );
}

// Едва заметная метка с коротким номером попытки: утёкший скриншот ведёт к источнику.
const watermark = (attemptId: string) => Array(60).fill("ФСП " + attemptId.slice(0, 8)).join("   ");

function AssessmentQuestion({
  attempt,
  answers,
  page,
  onPageChange,
  onAnswer,
  disabled = false,
  readOnly = false,
  questionPanelRef,
}: {
  attempt: Attempt;
  answers: Record<string, string>;
  page: number;
  onPageChange: (page: number) => void;
  onAnswer?: (questionId: string, option: string) => void;
  disabled?: boolean;
  readOnly?: boolean;
  questionPanelRef?: React.Ref<HTMLFieldSetElement>;
}) {
  const currentPage = Math.min(Math.max(1, page), attempt.questions.length);
  const question = attempt.questions[currentPage - 1];
  const answered = attempt.questions.filter((q) => Boolean(answers[q.id])).length;
  if (!question) return null;
  // Формы заданий: последняя строка — вопрос, предыдущие — код или данные (показываем моноширинно).
  const titleLines = question.title.split("\n");
  const questionPrompt = titleLines[titleLines.length - 1];
  const questionCode = titleLines.length > 1 ? titleLines.slice(0, -1).join("\n") : "";
  return (
    <div
      className={"assessment-question" + (readOnly ? "" : " watermarked")}
      data-wm={readOnly ? undefined : watermark(attempt.id)}
    >
      <p className="muted" role="status" aria-live="polite">
        Отвечено {answered} из {attempt.questions.length} · без ответа {attempt.questions.length - answered}
        {readOnly ? " · просмотр результата" : ""}
      </p>
      <Pagination
        label="Вопросы оценки"
        total={attempt.questions.length}
        page={currentPage}
        pages={attempt.questions.length}
        start={currentPage}
        end={currentPage}
        onPageChange={onPageChange}
        disabled={disabled && !readOnly}
      />
      <fieldset ref={questionPanelRef} tabIndex={-1} disabled={disabled || readOnly}>
        <legend>
          {currentPage}. {questionPrompt}
        </legend>
        {questionCode && (
          <pre className="code-sample" tabIndex={0} aria-label="Фрагмент кода или данных к вопросу">
            {questionCode}
          </pre>
        )}
        {question.options.map((option) => (
          <label className="check" key={option}>
            <input
              type="radio"
              name={question.id}
              required={!readOnly}
              checked={answers[question.id] === option}
              onChange={() => onAnswer?.(question.id, option)}
            />
            {option}
          </label>
        ))}
      </fieldset>
    </div>
  );
}

function Privacy() {
  const juryMode = React.useContext(JuryModeContext);
  const [profile, setProfile] = useState<Profile | null>(null),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const recipients = usePagedItems(profile?.contact_grants || [], 8);
  const load = () => api<Profile>("/candidate/profile").then(setProfile);
  useEffect(() => {
    void load().catch((e) => setError(e.message));
    const outcome = new URLSearchParams(window.location.search).get("fsp");
    const notes: Record<string, string> = {
      linked: "ФСП ID подключён: достижения получены из демо-реестра",
      empty: "ФСП ID подключён, истории участия в реестре нет",
      unavailable: "Реестр ФСП временно недоступен: прежняя история сохранена",
      taken: "Этот ФСП ID уже подключён к другому профилю",
      failed: "Вход через ФСП ID не завершён. Повторите попытку",
    };
    if (outcome && notes[outcome]) {
      setMessage(notes[outcome]);
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
  }, []);
  async function update(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      setMessage(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h2>Видимость и контакты</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {profile && (
        <>
          <div className="privacy-row privacy-publication">
            <div>
              <h3>
                {profile.published ? "Профиль опубликован" : "Профиль скрыт"}
              </h3>
              <p>
                Публикация открывает категорию и доказательства, но не контакт.
                Отзыв убирает профиль из новых поисков и списков; уже
                разрешённые контакты отзываются отдельно.
              </p>
            </div>
            <button
              disabled={busy}
              onClick={() =>
                void update(
                  () =>
                    api("/candidate/consents", "POST", {
                      published: !profile.published,
                      text_version: "demo-consent-v1",
                    }),
                  profile.published ? "Профиль скрыт" : "Профиль опубликован",
                )
              }
            >
              {profile.published ? "Скрыть профиль" : "Опубликовать профиль"}
            </button>
          </div>
          <div className="privacy-recipients">
            <h3>Получатели контакта</h3>
            <p>
              Принятие приглашения или самостоятельный отклик разрешает контакт
              конкретной компании. Отзыв прекращает будущий доступ; уже
              прочитанное технически невозможно удалить у получателя.
            </p>
            {profile.contact_grants.length === 0 ? (
              <p className="muted">Нет разрешённых получателей.</p>
            ) : (
              recipients.visibleItems.map((g) => (
                <div key={g.id} className="mail-row">
                  <span>{g.label}</span>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void update(
                        () => api(`/candidate/contacts/${g.id}`, "DELETE"),
                        "Доступ к контакту отозван",
                      )
                    }
                  >
                    Отозвать контакт
                  </button>
                </div>
              ))
            )}
            <Pagination
              label="Получатели контакта"
              total={profile.contact_grants.length}
              page={recipients.page}
              pages={recipients.pages}
              start={recipients.start}
              end={recipients.end}
              onPageChange={recipients.setPage}
            />
          </div>
          <h3>Связь ФСП · mock</h3>
          {profile.fsp_member_id ? (
            <>
              <p>
                Подключён ФСП ID <strong>{profile.fsp_member_id}</strong> ·{" "}
                {fspNames[profile.fsp_state]}
              </p>
              {profile.fsp_evidence.length === 0 ? (
                <p className="muted">
                  В реестре нет истории участия. Это не мешает подбору: бонус ФСП равен нулю.
                </p>
              ) : (
                profile.fsp_evidence.map((e, i) => (
                  <p className="muted" key={i}>
                    {e.event} · {e.role} · место {e.place} · {e.date} · {e.source}
                  </p>
                ))
              )}
              <button
                disabled={busy}
                onClick={() =>
                  void update(() => api("/candidate/fsp-link", "DELETE"), "ФСП ID отвязан")
                }
              >
                Отвязать ФСП ID
              </button>
            </>
          ) : (
            <>
              <p>
                Достижения подтягиваются из реестра ФСП ID, а не вводятся вручную.
                Это имитация протокола OIDC (код + PKCE); реального запроса в ФСП нет.
                Демо-участники и пароли показаны на форме входа.
              </p>
              <button
                className="primary"
                disabled={juryMode || busy}
                onClick={() => window.location.assign("/api/v1/candidate/fsp-id/start")}
              >
                {juryMode ? 'ФСП ID mock отключён в показе жюри' : 'Войти через ФСП ID (демо)'}
              </button>
            </>
          )}
        </>
      )}
    </section>
  );
}

function Bank({ shortlist }: { shortlist: boolean }) {
  const { catalog, error: catalogError } = useSkillsWorkCatalog();
  const mounted = useRef(true);
  const initial = new URLSearchParams(location.search),
    [spec, setSpec] = useState(initial.get("spec") || "backend"),
    [grade, setGrade] = useState(initial.get("grade") || "junior"),
    [format, setFormat] = useState(initial.get("format") || "remote"),
    [salary, setSalary] = useState(Number(initial.get("salary") || 200000)),
    [must, setMust] = useState(
      initial.has("must")
        ? (initial.get("must") || "").split(",").filter(Boolean)
        : [specs[initial.get("spec") || "backend"]?.skills[0] || "python"],
    ),
    [desired, setDesired] = useState(
      initial.has("desired")
        ? (initial.get("desired") || "").split(",").filter(Boolean)
        : ["sql"],
    ),
    [workTasks, setWorkTasks] = useState((initial.get("work_tasks") || "").split(",").filter(Boolean)),
    [fspOnly, setFspOnly] = useState(initial.get("fsp") === "1"),
    [rows, setRows] = useState<Row[]>([]),
    [searchId, setSearchId] = useState(""),
    [explanations, setExplanations] = useState<Record<string, { text: string; source: string; model: string | null }>>({}),
    [comparisonIds, setComparisonIds] = useState<string[]>([]),
    [history, setHistory] = useState<{ id: string; query: NeedQuery }[]>([]),
    [historyPage, setHistoryPage] = useState(1),
    [historyTotal, setHistoryTotal] = useState(0),
    [categories, setCategories] = useState<
      { specialization: string; grade: string; count: number }[]
    >([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [selected, setSelected] = useState<Row | null>(null),
    [message, setMessage] = useState("");
  const query: NeedQuery = {
    specialization: spec,
    grade,
    format,
    salary_to: salary,
    must_skills: must,
    desired_skills: desired,
    work_tasks: workTasks,
    fsp_only: fspOnly,
  };
  const resultPages = usePagedItems(rows, 8);
  useEffect(() => { setComparisonIds([]); }, [rows]);
  const comparedRows = rows.filter((row) => comparisonIds.includes(row.id));
  const historyPageSize = 8;
  const historyPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
  async function loadHistory(page: number) {
    const load = (number: number) => api<{
      items: { id: string; query: NeedQuery }[];
      total: number;
      offset: number;
      limit: number;
    }>(`/company/searches/page?offset=${(number - 1) * historyPageSize}&limit=${historyPageSize}`);
    let response = await load(page);
    const finalPage = Math.min(
      page,
      Math.max(1, Math.ceil(response.total / historyPageSize)),
    );
    if (finalPage !== page) response = await load(finalPage);
    setHistory(response.items);
    setHistoryTotal(response.total);
    setHistoryPage(finalPage);
  }
  async function changeHistoryPage(page: number) {
    setBusy(true);
    setError("");
    try {
      await loadHistory(Math.min(Math.max(1, page), historyPages));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function url(q: NeedQuery) {
    if (!mounted.current) return;
    window.history.replaceState(
      null,
      "",
      "?" +
        new URLSearchParams({
          spec: q.specialization,
          grade: q.grade,
          format: q.format,
          salary: String(q.salary_to),
          must: q.must_skills.join(","),
          desired: q.desired_skills.join(","),
          work_tasks: (q.work_tasks || []).join(","),
          fsp: q.fsp_only ? "1" : "0",
        }) +
        window.location.hash,
    );
  }
  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<{ id: string; rows: Row[] }>("/company/searches", "POST", query);
      setRows(created.rows);
      setSearchId(created.id);
      setExplanations({});
      resultPages.setPage(1);
      url(query);
      await loadHistory(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function explain(candidateId: string) {
    setError("");
    try {
      const result = await api<{ text: string; source: string; model: string | null }>(
        `/company/searches/${searchId}/candidates/${candidateId}/explanation`,
        "POST",
      );
      setExplanations((current) => ({ ...current, [candidateId]: result }));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function restore(id: string) {
    setBusy(true);
    setError("");
    try {
      const saved = await api<{ rows: Row[]; query: NeedQuery }>(
          `/company/searches/${id}`,
        ),
        q = saved.query;
      setRows(saved.rows);
      setSearchId(id);
      setExplanations({});
      resultPages.setPage(1);
      setSpec(q.specialization);
      setGrade(q.grade);
      setFormat(q.format);
      setSalary(q.salary_to);
      setMust(q.must_skills);
      setDesired(q.desired_skills);
      setWorkTasks(q.work_tasks || []);
      setFspOnly(q.fsp_only || false);
      url(q);
      setMessage(
        "Сохранённая подборка восстановлена. Отозванные публикации не отображаются.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void api<typeof categories>("/company/categories")
      .then(setCategories)
      .catch((e) => setError(e.message));
    if (shortlist)
      void api<Row[]>("/company/shortlist")
        .then(setRows)
        .catch((e) => setError(e.message));
    else void search();
    return () => {
      mounted.current = false;
    };
  }, []);
  async function save(row: Row) {
    try {
      await api(`/company/shortlist/${row.id}`, shortlist ? "DELETE" : "PUT");
      if (shortlist) setRows((current) => current.filter((r) => r.id !== row.id));
      setMessage(
        shortlist ? "Кандидат убран из списка" : "Кандидат сохранён в списке",
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <section>
      <div className="section-heading">
        <h2>{shortlist ? "Мой список" : "Банк кандидатов"}</h2>
        <span className="muted">
          Подтверждённые категории · синтетические профили
        </span>
      </div>
      {!shortlist && (
        <>
          <p className="muted">
            Категории:{" "}
            {categories
              .filter((c) => c.count > 0)
              .map(
                (c) =>
                  `${specs[c.specialization]?.label} / ${gradeName(c.grade)}: ${c.count}`,
              )
              .join(" · ") || "Опубликованных категорий пока нет"}
          </p>
          <form
            className="toolbar bank-search"
            onSubmit={(e) => void search(e)}
          >
            <SpecSelect
              value={spec}
              onChange={(s) => {
                setSpec(s);
                setWorkTasks([]);
                setMust([specs[s].skills[0]]);
                setDesired(specs[s].skills.slice(1));
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
              Формат
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              >
                <option value="remote">Удалённо</option>
                <option value="hybrid">Гибрид</option>
                <option value="office">В офисе</option>
              </select>
            </label>
            <label>
              Бюджет до, руб.
              <input
                required
                type="number"
                min={1}
                max={10000000}
                value={salary}
                onChange={(e) => setSalary(Number(e.target.value))}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={fspOnly}
                onChange={(e) => setFspOnly(e.target.checked)}
              />
              Только с достижениями ФСП · mock
            </label>
            <fieldset>
              <legend>Обязательные навыки</legend>
              {specs[spec]?.skills.map((skill) => (
                <label className="check" key={skill}>
                  <input
                    type="checkbox"
                    checked={must.includes(skill)}
                    onChange={(e) =>
                      setMust(
                        e.target.checked
                          ? [...must, skill]
                          : must.filter((x) => x !== skill),
                      )
                    }
                  />
                  {skill}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend>Желательные навыки</legend>
              {specs[spec]?.skills.map((skill) => (
                <label className="check" key={skill}>
                  <input
                    type="checkbox"
                    checked={desired.includes(skill)}
                    onChange={(e) =>
                      setDesired(
                        e.target.checked
                          ? [...desired, skill]
                          : desired.filter((x) => x !== skill),
                      )
                    }
                  />
                  {skill}
                </label>
              ))}
            </fieldset>
            {catalogError && <p role="alert" className="error">{catalogError}</p>}
            <WorkTasks catalog={catalog} specialization={spec} value={workTasks} onChange={setWorkTasks} />
            <button className="primary" disabled={busy}>
              Найти
            </button>
          </form>
          {history.length > 0 && (
            <div className="history">
              <label>
                Сохранённые подборки
                <select
                  value=""
                  disabled={busy}
                  onChange={(e) => {
                    if (e.target.value) void restore(e.target.value);
                  }}
                >
                  <option value="">Восстановить подборку</option>
                {history.map((h) => (
                    <option key={h.id} value={h.id}>
                      {specs[h.query.specialization]?.label} /{" "}
                      {gradeName(h.query.grade)} / {money(h.query.salary_to)} руб.
                    </option>
                  ))}
                </select>
              </label>
              <Pagination
                label="История подборок"
                total={historyTotal}
                page={historyPage}
                pages={historyPages}
                start={historyTotal ? (historyPage - 1) * historyPageSize + 1 : 0}
                end={Math.min(historyPage * historyPageSize, historyTotal)}
                onPageChange={(page) => void changeHistoryPage(page)}
                disabled={busy}
              />
            </div>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <p className="muted">
        {rows.length} профилей. Score соответствует потребности, не означает
        вероятность найма. Веса: оценка 45%, навыки 35%, ФСП 10%, актуальность
        10%. Контакты не входят в поиск.
      </p>
      <details className="ranking-guide">
        <summary>Как читать балл подбора</summary>
        <p>
          Сначала применяются обязательные условия: категория, обязательные
          навыки, формат и бюджет. Затем кандидаты сравниваются внутри
          подходящей выдачи.
        </p>
        <dl>
          <div>
            <dt>45% · оценка</dt>
            <dd>Результат отдельной оценки грейда.</dd>
          </div>
          <div>
            <dt>35% · навыки</dt>
            <dd>Совпадение подтверждённых навыков с запросом.</dd>
          </div>
          <div>
            <dt>10% · ФСП</dt>
            <dd>
              Дополнительный сигнал соревнований; на стенде используется явно
              обозначенный mock.
            </dd>
          </div>
          <div>
            <dt>10% · актуальность</dt>
            <dd>Дата последней оценки или результата короткой задачи.</dd>
          </div>
        </dl>
        <p className="muted">
          Это объяснимый порядок подбора на тестовых данных, а не вероятность
          найма и не независимая аттестация. В сохранённой подборке баллы
          относятся к моменту поиска; текущий доступ к профилю проверяется
          заново.
        </p>
      </details>
      <Comparison rows={comparedRows}
        remove={(id) => setComparisonIds((ids) => ids.filter((item) => item !== id))}
        clear={() => setComparisonIds([])} invite={(id) => setSelected(rows.find((row) => row.id === id) || null)} />
      <div className="candidate-list">
        {resultPages.visibleItems.map((row) => (
          <article className="candidate-row" key={row.id}>
            <div>
              <h3>{row.alias}</h3>
              <p className="evidence">
                {specs[row.specialization]?.label} /{" "}
                {gradeName(row.confirmed_grade)}
              </p>
              <a href={`/api/v1/company/candidates/${row.id}/profile.pdf`}>
                PDF разрешённой проекции
              </a>
            </div>
            <div>
              <p>
                {row.skills.join(", ")} · оценка {row.test_score}/100
              </p>
              <p className="muted">{fspNames[row.fsp_state]} · mock</p>
              {row.integrity_level && (
                <p className="muted">
                  Добросовестность при тесте:{" "}
                  {row.integrity_level === "clean" ? "без замечаний" : "есть замечания"}
                </p>
              )}
              <p className="muted">
                {row.missing === undefined
                  ? "Сохранённый профиль"
                  : row.missing.length
                    ? "Не подтверждено: " + row.missing.join(", ")
                    : "Нужные навыки покрыты"}{" "}
                · от {money(row.salary_min)} руб.
              </p>
              <details className="candidate-skill-details"><summary>Источники навыков и задачи команды</summary><SkillEvidence evidence={row.skill_evidence} /><WorkMatches matches={row.work_matches} /></details>
              {row.fsp_evidence?.map((e, i) => (
                <p className="muted" key={i}>
                  {e.event} · {e.role} · место {e.place} · {e.date} · {e.source}
                </p>
              ))}
            </div>
            <div className="ranking">
              {row.score !== undefined && (
                <>
                  <strong>{row.score.toFixed(1)}</strong>
                  <span>Score подбора</span>
                  <span>Бонус ФСП: {row.fsp_bonus || 0} / 10</span>
                  <details><summary>Из чего сложился балл</summary><RankingEvidence row={row} /></details>
                  {searchId && (
                    <button type="button" onClick={() => void explain(row.id)}>
                      Объяснить словами
                    </button>
                  )}
                  {explanations[row.id] && (
                    <p className="muted" role="status">
                      {explanations[row.id].text}
                      <br />
                      <em>
                        {explanations[row.id].source === "template"
                          ? "Шаблон по данным подбора"
                          : `ИИ-помощник (${explanations[row.id].model}), числа и навыки проверены по данным подбора`}
                      </em>
                    </p>
                  )}
                </>
              )}
            </div>
            <div className="row-actions">
              <button aria-pressed={comparisonIds.includes(row.id)}
                disabled={!comparisonIds.includes(row.id) && comparisonIds.length >= 3}
                onClick={() => setComparisonIds((ids) => ids.includes(row.id) ? ids.filter((id) => id !== row.id) : [...ids, row.id])}>
                {comparisonIds.includes(row.id) ? "Убрать из сравнения" : "Сравнить"}
              </button>
              <button onClick={() => setSelected(row)}>Пригласить</button>
              <button onClick={() => void save(row)}>
                {shortlist ? "Убрать из списка" : "В мой список"}
              </button>
            </div>
          </article>
        ))}
      </div>
      <Pagination
        label={shortlist ? "Короткий список кандидатов" : "Результаты подбора"}
        total={rows.length}
        page={resultPages.page}
        pages={resultPages.pages}
        start={resultPages.start}
        end={resultPages.end}
        onPageChange={resultPages.setPage}
      />
      {rows.length === 0 && !busy && (
        <p className="empty">
          Нет подходящих профилей. Уточните категорию, навыки, формат и бюджет.
        </p>
      )}
      {selected && (
        <Invite
          row={selected}
          onClose={() => setSelected(null)}
          onSent={() => {
            setSelected(null);
            setMessage(
              "Предложение отправлено в кабинет кандидата. Контакт остаётся скрытым.",
            );
          }}
        />
      )}
    </section>
  );
}

function Invite({
  row,
  onClose,
  onSent,
}: {
  row: Row;
  onClose: () => void;
  onSent: () => void;
}) {
  const [low, setLow] = useState(120000),
    [high, setHigh] = useState(180000),
    [basis, setBasis] = useState("gross"),
    [description, setDescription] = useState(
      "Разработка API на Python и PostgreSQL. Удалённая работа в демонстрационной команде.",
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [key] = useState(() => uuid());
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/company/invitations",
        "POST",
        {
          candidate_id: row.id,
          description,
          salary_from: low,
          salary_to: high,
          salary_basis: basis,
        },
        { "Idempotency-Key": key },
      );
      onSent();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-labelledby="invite-title"
      className="modal"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h2 id="invite-title">Предложение кандидату</h2>
      <p>
        {row.alias} · вакансия не обязательна. Контакт будет доступен вашей
        компании только после принятия.
      </p>
      <form onSubmit={(e) => void submit(e)} className="form-grid">
        <label>
          Зарплата от, руб./мес.
          <input
            type="number"
            min={1}
            max={10000000}
            required
            value={low}
            onChange={(e) => setLow(Number(e.target.value))}
          />
        </label>
        <label>
          Зарплата до, руб./мес.
          <input
            type="number"
            min={1}
            max={10000000}
            required
            value={high}
            onChange={(e) => setHigh(Number(e.target.value))}
          />
        </label>
        <label>
          Расчёт
          <select value={basis} onChange={(e) => setBasis(e.target.value)}>
            <option value="gross">До вычета налогов</option>
            <option value="net">На руки</option>
          </select>
        </label>
        <label className="full">
          Условия и задачи
          <textarea
            required
            minLength={20}
            maxLength={4000}
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="error full">
            {error}
          </p>
        )}
        <div className="actions full">
          <button type="button" disabled={busy} onClick={onClose}>
            Отмена
          </button>
          <button className="primary" disabled={busy}>
            Отправить предложение
          </button>
        </div>
      </form>
    </dialog>
  );
}

function Offers({ role }: { role: "candidate" | "employer" }) {
  const [rows, setRows] = useState<Offer[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const pages = usePagedItems(rows, 8);
  const load = () =>
    api<Offer[]>(
      `/${role === "candidate" ? "candidate" : "company"}/invitations`,
    ).then(setRows);
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  async function change(offer: Offer, decision: string) {
    setBusy(true);
    setError("");
    try {
      await api(
        role === "candidate"
          ? `/candidate/invitations/${offer.id}/${decision === "viewed" ? "view" : "decision"}`
          : `/company/invitations/${offer.id}/withdraw`,
        "POST",
        role === "candidate" && decision !== "viewed"
          ? { decision }
          : undefined,
      );
      await load();
      setMessage(
        decision === "viewed"
          ? "Просмотр предложения отмечен"
          : decision === "accepted"
            ? "Разрешён контакт только компании-отправителю"
            : decision === "declined"
              ? "Предложение отклонено; контакт скрыт"
              : "Приглашение отозвано",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <div className="section-heading">
        <h2>
          {role === "candidate"
            ? "Входящие предложения"
            : "Отправленные предложения"}
        </h2>
        <button
          disabled={busy}
          onClick={() => void load().catch((e) => setError(e.message))}
        >
          Обновить
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {rows.length === 0 ? (
        <p className="empty">Предложений пока нет.</p>
      ) : (
        pages.visibleItems.map((o) => (
          <article className="offer-row" key={o.id}>
            <div className="section-heading">
              <h3>
                {role === "candidate" ? o.company_name : o.candidate_alias}
              </h3>
              <span className="evidence">{offerNames[o.status]}</span>
            </div>
            <p className="salary">
              {money(o.salary_from)}–{money(o.salary_to)} руб./мес.
            </p>
            <p className="muted">
              {o.salary_basis === "gross" ? "До вычета налогов" : "На руки"} ·
              компания не проверена
            </p>
            <p>{o.description}</p>
            <p>Контакт компании: {o.company_contact}</p>
            {role === "employer" && (
              <p className="contact">
                {o.contact
                  ? "Разрешённый контакт: " + o.contact
                  : o.contact_revoked
                    ? "Контакт отозван кандидатом"
                    : "Контакт кандидата скрыт"}
              </p>
            )}
            {o.status === "accepted" && !o.contact_revoked && (
              <div className="actions">
                <button
                  className="primary"
                  onClick={() =>
                    navigate(
                      `/${role}/messages/${encodeURIComponent(role === "candidate" ? o.company_id : o.candidate_id)}`,
                    )
                  }
                >
                  Написать сообщение
                </button>
              </div>
            )}
            {["sent", "viewed"].includes(o.status) && (
              <div className="actions">
                {role === "candidate" ? (
                  <>
                    {o.status === "sent" && (
                      <button
                        disabled={busy}
                        onClick={() => void change(o, "viewed")}
                      >
                        Отметить просмотр
                      </button>
                    )}
                    <button
                      disabled={busy}
                      onClick={() => void change(o, "declined")}
                    >
                      Отклонить
                    </button>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => void change(o, "accepted")}
                    >
                      Принять и открыть контакт
                    </button>
                  </>
                ) : (
                  <button
                    disabled={busy}
                    onClick={() => void change(o, "withdrawn")}
                  >
                    Отозвать приглашение
                  </button>
                )}
              </div>
            )}
          </article>
        ))
      )}
      <Pagination
        label={role === "candidate" ? "Входящие предложения" : "Отправленные предложения"}
        total={rows.length}
        page={pages.page}
        pages={pages.pages}
        start={pages.start}
        end={pages.end}
        onPageChange={pages.setPage}
      />
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
