import { useEffect, useState } from "react";
import { api } from "./api";
import { Pagination, usePagedItems } from "./pagination";
import { navigate } from "./routing";

export type Feedback = {
  threshold: number; correct: number; total: number; needed_correct: number;
  skills: { skill: string; correct: number; total: number; score: number;
    status: "strong" | "review"; topics: string[]; recommendation: string }[];
  questions: { id: string; skill: string; status: "correct" | "incorrect" | "unanswered";
    selected_answer: string | null; correct_answer: string; explanation: string }[];
};
const statusNames = { correct: "Верно", incorrect: "Нужно повторить", unanswered: "Без ответа" };

export function AssessmentReport({ id, initial }: { id: string; initial?: Feedback | null }) {
  const [report, setReport] = useState<Feedback | null>(initial || null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const pages = usePagedItems(report?.questions || [], 4);
  useEffect(() => {
    let current = true;
    setError("");
    setReport(initial || null);
    if (!initial) void api<{ feedback?: Feedback | null }>(`/assessments/attempts/${id}`)
      .then((data) => { if (current) {
        if (data.feedback) setReport(data.feedback);
        else setError("Разбор ещё не доступен. Результат оценки сохранён.");
      } })
      .catch(() => { if (current) setError("Не удалось загрузить разбор. Результат оценки сохранён."); });
    return () => { current = false; };
  }, [id, initial, retry]);
  if (!report) return <section aria-label="Разбор оценки">
    <h3>Разбор оценки</h3>
    {error ? <><p role="alert">{error}</p><button onClick={() => setRetry((value) => value + 1)}>Повторить загрузку разбора</button></>
      : <p role="status">Загрузка разбора по навыкам…</p>}
  </section>;
  return <section className="assessment-report" aria-label="Разбор оценки">
    <div className="section-heading"><h3>Ваши навыки и следующий шаг</h3><span className="evidence">{report.correct} из {report.total} верно</span></div>
    <p>Порог этой формы — {report.threshold}/100, минимум {report.needed_correct} правильных ответов из {report.total}.
      {report.correct < report.needed_correct ? ` До порога не хватает ${report.needed_correct - report.correct}.` : " Порог достигнут."}</p>
    <div className="skill-report-list">{report.skills.map((skill) => <article key={skill.skill} className="skill-report-row">
      <div><h4>{skill.skill}</h4><p className="evidence">{skill.correct}/{skill.total} · {skill.score}/100</p>
        <progress aria-label={`Результат по навыку ${skill.skill}`} max={100} value={skill.score} />
        <p>{skill.status === "strong" ? "Сильная сторона этой формы" : "Зона для повторения"}</p></div>
      <div><p>{skill.recommendation}</p><p className="muted">Темы: {skill.topics.join("; ")}</p></div>
    </article>)}</div>
    <p className="muted">Рекомендации основаны на ответах этой формы. Практика помогает закрепить материал и не меняет глобальный грейд.</p>
    <button onClick={() => navigate("/candidate/practice")}>Перейти к практике</button>
    <h4>Почему засчитан ответ</h4>
    <p className="muted">Эталоны доступны только вам после завершения. Разбор опирается на сохранённую форму.</p>
    {pages.visibleItems.map((question) => <details className="answer-explanation" key={question.id}>
      <summary>{question.id} · {question.skill} · {statusNames[question.status]}</summary>
      <p>Ваш ответ: {question.selected_answer ?? "не указан"}. Эталон сохранённой формы: {question.correct_answer}.</p>
      <p>{question.explanation}</p>
    </details>)}
    <Pagination label="Разбор заданий" total={report.questions.length} page={pages.page} pages={pages.pages}
      start={pages.start} end={pages.end} onPageChange={pages.setPage} />
  </section>;
}
