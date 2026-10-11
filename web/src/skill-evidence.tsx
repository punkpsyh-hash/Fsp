export type SkillEvidenceData = {
  declared: string[];
  assessment: {
    skill: string;
    score: number | null;
    correct: number | null;
    total: number | null;
    version: string | null;
    assessed_at: string | null;
    source: "assessment" | "legacy-assessment";
  }[];
  practice: {
    skill: string;
    score: number;
    tasks: number;
    total_tasks: number;
    completed_at: string | null;
    source: "platform-practice" | "employer-practice";
  }[];
  limitations: string[];
};
const date = (value: string | null) =>
  value ? new Date(value).toLocaleDateString("ru-RU") : "дата не сохранена";

export function SkillEvidence({
  evidence,
}: {
  evidence?: SkillEvidenceData | null;
}) {
  if (!evidence)
    return (
      <div className="skill-evidence">
        <h4>Источники навыков</h4>
        <p className="muted">
          В этой записи источники навыков не сохранены. Общий список навыков не
          позволяет восстановить задания, версию формы или результаты практики.
          Для проверки источников нужна актуальная проекция профиля.
        </p>
      </div>
    );
  return (
    <div className="skill-evidence">
      <h4>Источники навыков</h4>
      <dl>
        <div>
          <dt>Заявлено кандидатом</dt>
          <dd>
            {evidence.declared.join(", ") || "Нет заявленных технологий"}.
            Анкета не подтверждает навыки и не меняет грейд.
          </dd>
        </div>
        <div>
          <dt>Оценка категории</dt>
          <dd>
            {evidence.assessment.length ? (
              <ul>
                {evidence.assessment.map((item, i) => (
                  <li key={`${item.skill}-${i}`}>
                    <strong>{item.skill}</strong> ·{" "}
                    {item.score === null
                      ? "балл по навыку не сохранён"
                      : `${item.score}/100`}
                    {item.correct !== null && item.total !== null
                      ? ` · ${item.correct} из ${item.total} ответов`
                      : " · детализация ответов не сохранена"}
                    {` · ${item.version || "версия не сохранена"} · ${date(item.assessed_at)}`}
                    {item.source === "legacy-assessment" &&
                      " · историческая оценка"}
                  </li>
                ))}
              </ul>
            ) : (
              "Нет результатов оценки навыков"
            )}
          </dd>
        </div>
        <div>
          <dt>Практика</dt>
          <dd>
            {evidence.practice.length ? (
              <ul>
                {evidence.practice.map((item, i) => (
                  <li key={`${item.skill}-${i}`}>
                    <strong>{item.skill}</strong> · {item.score}/100 ·{" "}
                    задач ≥50% / всего оценённых: {item.tasks}/{item.total_tasks} ·{" "}
                    {item.source === "employer-practice"
                      ? "практика работодателя"
                      : "практика платформы"}{" "}
                    · {date(item.completed_at)}
                  </li>
                ))}
              </ul>
            ) : (
              "Нет результатов практики"
            )}
            <p className="muted">
              Практика даёт отдельный сигнал и не повышает глобальный грейд.
            </p>
          </dd>
        </div>
      </dl>
      {evidence.limitations.length > 0 && (
        <ul className="muted">
          {evidence.limitations.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
