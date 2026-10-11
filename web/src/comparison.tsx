import { SkillEvidence, type SkillEvidenceData } from "./skill-evidence";
import { WorkMatches, type WorkMatch } from "./work-tasks";
export type Comparable = {
  id: string; alias: string; skills: string[]; test_score: number;
  salary_min: number; fsp_state: string; confirmed_grade: string | null;
  specialization: string; score?: number; missing?: string[];
  skill_evidence?: SkillEvidenceData | null; work_matches?: WorkMatch[];
  components?: { assessment: number; skills: number; fsp: number; freshness: number };
};
const labels: Record<string, string> = { backend: "Backend", frontend: "Frontend", qa: "QA", design: "UI/UX" };
const money = (value: number) => new Intl.NumberFormat("ru-RU").format(value);
const signals = [
  ["assessment", "Оценка", 45], ["skills", "Совпадение навыков", 35],
  ["fsp", "Достижения ФСП · mock", 10], ["freshness", "Актуальность", 10],
] as const;

export function RankingEvidence({ row }: { row: Comparable }) {
  if (!row.components) return <p className="muted">Баллы подбора для этой записи не сохранены. Выполните поиск по потребности.</p>;
  return <dl className="rank-contributions">{signals.map(([key, label, limit]) => <div key={key}>
    <dt>{label}</dt><dd><span>{row.components![key].toFixed(2)} / {limit}</span>
      <progress aria-label={`${row.alias}: ${label}`} max={limit} value={row.components![key]} /></dd>
  </div>)}</dl>;
}

export function Comparison({ rows, remove, clear, invite }: {
  rows: Comparable[]; remove: (id: string) => void; clear: () => void; invite: (id: string) => void;
}) {
  if (!rows.length) return null;
  return <section className="comparison" aria-label="Сравнение кандидатов">
    <div className="section-heading"><h3>Сравнение кандидатов · {rows.length}/3</h3><button onClick={clear}>Очистить сравнение</button></div>
    <p className="muted">Сравнение использует данные текущей подборки. Баллы описывают соответствие запросу, а не вероятность найма. Контакт открывается после решения кандидата.</p>
    <div className="comparison-grid">{rows.map((row) => <article key={row.id} className="comparison-profile">
      <h4>{row.alias}</h4><p>{labels[row.specialization]} / {row.confirmed_grade === "middle" ? "Middle" : row.confirmed_grade === "junior" ? "Junior" : "Не подтверждён"}</p>
      <p className="comparison-score">{row.score === undefined ? "Нет балла подбора" : `${row.score.toFixed(1)} / 100`}</p>
      <RankingEvidence row={row} />
      <p>Подтверждено: {row.skills.join(", ") || "нет навыков"}.</p>
      <p>Не подтверждено в запросе: {row.missing === undefined ? "данные не сохранены" : row.missing.join(", ") || "все навыки покрыты"}.</p>
      <SkillEvidence evidence={row.skill_evidence} /><WorkMatches matches={row.work_matches} />
      <p>Ожидания: от {money(row.salary_min)} руб.</p>
      <div className="actions"><button className="primary" onClick={() => invite(row.id)}>Пригласить {row.alias}</button>
        <button onClick={() => remove(row.id)}>Убрать {row.alias} из сравнения</button></div>
    </article>)}</div>
  </section>;
}
