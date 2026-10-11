import { useState, type CSSProperties } from "react";

type Signal = "assessment" | "skills" | "fsp" | "freshness";
type ExampleCandidate = {
  id: string;
  alias: string;
  assessment: number;
  skills: string[];
  fsp: number;
  freshness: number;
};

// Изолированный учебный пример. Это не API-выдача и не сохранённый поиск.
// Арифметика и правило must + desired соответствуют src/domain.py:rank.
const examples: ExampleCandidate[] = [
  {
    id: "example-a",
    alias: "Пример А",
    assessment: 84,
    skills: ["Python", "SQL", "API"],
    fsp: 0,
    freshness: 0.9,
  },
  {
    id: "example-b",
    alias: "Пример Б",
    assessment: 80,
    skills: ["Python", "SQL", "Тестирование"],
    fsp: 0.4,
    freshness: 0.8,
  },
];
const signals: { key: Signal; name: string; weight: number }[] = [
  { key: "assessment", name: "Оценка", weight: 45 },
  { key: "skills", name: "Навыки", weight: 35 },
  { key: "fsp", name: "ФСП", weight: 10 },
  { key: "freshness", name: "Актуальность", weight: 10 },
];
const number = (value: number) =>
  value.toLocaleString("ru-RU", { maximumFractionDigits: 3 });

export function Showcase() {
  const [need, setNeed] = useState<"API" | "Тестирование">("API");
  const [testingRequired, setTestingRequired] = useState(false);
  const [selected, setSelected] = useState("example-a");
  const must = ["Python", "SQL", ...(testingRequired ? ["Тестирование"] : [])];
  const desired = [...new Set([...must, need])];
  const rows = examples.map((candidate) => {
    const matched = desired.filter((skill) => candidate.skills.includes(skill));
    const missing = desired.filter(
      (skill) => !candidate.skills.includes(skill),
    );
    const eligible = must.every((skill) => candidate.skills.includes(skill));
    const components = {
      assessment: (45 * candidate.assessment) / 100,
      skills: (35 * matched.length) / desired.length,
      fsp: 10 * candidate.fsp,
      freshness: 10 * candidate.freshness,
    };
    const score =
      Math.round(
        Object.values(components).reduce((sum, value) => sum + value, 0) * 1000,
      ) / 1000;
    return { ...candidate, components, score, eligible, matched, missing };
  });
  const ranked = rows
    .filter((row) => row.eligible)
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
  const excluded = rows.filter((row) => !row.eligible);
  const inspected = rows.find((row) => row.id === selected) ?? rows[0];

  return (
    <section className="showcase" aria-labelledby="showcase-title">
      <div className="showcase-heading">
        <div>
          <p className="eyebrow">Логика обратного подбора</p>
          <h2 id="showcase-title">
            Один профиль.
            <br />
            Разные потребности.
          </h2>
        </div>
        <p>
          Измените запрос и сравните доказательства. Соответствие зависит от
          потребности команды; score не означает вероятность найма.
        </p>
      </div>
      <p className="showcase-disclosure">
        <strong>Интерактивная иллюстрация</strong>
        <span>
          Два вымышленных профиля. Расчёт в браузере по правилам подбора; это не
          выдача API.
        </span>
      </p>
      <div className="showcase-layout">
        <div className="showcase-query">
          <p className="eyebrow">01 / Потребность команды</p>
          <h3>Backend / Middle</h3>
          <p className="showcase-meta">Удалённо · Python и SQL обязательны</p>
          <div
            className="showcase-choice"
            role="group"
            aria-label="Желательный навык для примера подбора"
          >
            <button
              type="button"
              aria-pressed={need === "API"}
              onClick={() => setNeed("API")}
            >
              Разработка API
            </button>
            <button
              type="button"
              aria-pressed={need === "Тестирование"}
              onClick={() => setNeed("Тестирование")}
            >
              Тестирование
            </button>
          </div>
          <label className="check showcase-required">
            <input
              type="checkbox"
              checked={testingRequired}
              onChange={(event) => setTestingRequired(event.target.checked)}
            />
            Тестирование обязательно
          </label>
          <p className="showcase-query-note">
            Обязательный навык — фильтр до расчёта. Если его нет, профиль не
            попадает в подборку даже с высоким результатом оценки.
          </p>
          <dl className="showcase-weights" aria-label="Веса сигналов подбора">
            {signals.map((signal) => (
              <div key={signal.key}>
                <dt>{signal.name}</dt>
                <dd>{signal.weight}%</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="showcase-results">
          <div className="showcase-results-heading">
            <p className="eyebrow">02 / Объяснимая подборка</p>
            <p className="showcase-meta">Контакты скрыты</p>
          </div>
          <p className="showcase-result-status" role="status">
            {ranked.length === 2
              ? `Первым показан ${ranked[0].alias.toLowerCase()}: лучше соответствует запросу.`
              : "Один профиль проходит обязательные навыки. Второй исключён до ранжирования."}
          </p>
          <ol
            className="showcase-ranked"
            aria-label="Порядок вымышленных профилей"
          >
            {ranked.map((row, index) => (
              <li key={row.id} data-selected={row.id === selected}>
                <button
                  type="button"
                  className="showcase-row"
                  aria-pressed={row.id === selected}
                  aria-label={`${row.alias}, место ${index + 1}, соответствие ${number(row.score)}. Показать объяснение`}
                  onClick={() => setSelected(row.id)}
                >
                  <span className="showcase-position">0{index + 1}</span>
                  <span className="showcase-person">
                    <strong>{row.alias}</strong>
                    <span>{row.skills.join(" · ")}</span>
                  </span>
                  <span className="showcase-score">
                    <strong>{number(row.score)}</strong>
                    <span>score / 100</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {excluded.map((row) => (
            <div className="showcase-excluded" key={row.id}>
              <strong>{row.alias} · исключён</strong>
              <span>Не подтверждён обязательный навык «Тестирование».</span>
              <button
                type="button"
                className="text-action"
                aria-pressed={row.id === selected}
                onClick={() => setSelected(row.id)}
              >
                Посмотреть доказательства
              </button>
            </div>
          ))}
          <div
            className="showcase-evidence"
            aria-labelledby="showcase-evidence-title"
          >
            <div className="showcase-evidence-heading">
              <h3 id="showcase-evidence-title">
                {inspected.alias}: из чего складывается score
              </h3>
              <span>
                {inspected.eligible
                  ? "Проходит фильтры"
                  : "Не проходит фильтры"}
              </span>
            </div>
            <div
              className="showcase-breakdown"
              key={`${need}-${testingRequired}-${selected}`}
            >
              {signals.map((signal) => (
                <div className="showcase-signal" key={signal.key}>
                  <span>{signal.name}</span>
                  <div className="showcase-meter" aria-hidden="true">
                    <span
                      style={
                        {
                          "--signal-fill": `${(inspected.components[signal.key] / signal.weight) * 100}%`,
                        } as CSSProperties
                      }
                    />
                  </div>
                  <strong>
                    {number(inspected.components[signal.key])} / {signal.weight}
                  </strong>
                </div>
              ))}
            </div>
            <dl className="showcase-proof">
              <div>
                <dt>Оценка</dt>
                <dd>
                  {inspected.assessment} из 100 × 45%. Балл учебного профиля, не
                  профессиональная аттестация.
                </dd>
              </div>
              <div>
                <dt>Навыки</dt>
                <dd>
                  Совпало {inspected.matched.length} из {desired.length}:{" "}
                  {inspected.matched.join(", ")}.
                  {inspected.missing.length > 0
                    ? ` Не совпало: ${inspected.missing.join(", ")}.`
                    : " Все навыки запроса совпали."}
                </dd>
              </div>
              <div>
                <dt>ФСП / актуальность</dt>
                <dd>
                  Синтетические сигналы {number(inspected.fsp)} и{" "}
                  {number(inspected.freshness)} из 1. Каждый умножается на 10;
                  внешнего реестра в этом примере нет.
                </dd>
              </div>
            </dl>
            {!inspected.eligible && (
              <p className="showcase-filter-note">
                Компоненты приведены для объяснения. Итоговый score исключённому
                профилю не присваивается в подборке.
              </p>
            )}
          </div>
        </div>
      </div>
      <div className="showcase-privacy">
        <p className="eyebrow">03 / Решение остаётся у кандидата</p>
        <ol>
          <li>
            <strong>Подборка</strong>
            <span>Навыки и категория видны. Контакт скрыт.</span>
          </li>
          <li>
            <strong>Предложение</strong>
            <span>Компания, задачи и зарплата известны до принятия.</span>
          </li>
          <li>
            <strong>Разрешение</strong>
            <span>
              Контакт получает отправитель после принятия; дальнейший доступ
              можно отозвать.
            </span>
          </li>
        </ol>
        <p>
          Иллюстрация ничего не публикует и не отправляет. Реальный поиск,
          сохранение потребности и приглашения доступны в кабинете работодателя.
        </p>
      </div>
    </section>
  );
}
