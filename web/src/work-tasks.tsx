import { useEffect, useState } from "react";
import { api } from "./api";

export type WorkTask = {
  id: string;
  label: string;
  description: string;
  skills: string[];
  specialization: string;
};
export type SkillsWorkCatalog = {
  declared_skills: { id: string; label: string; specializations: string[] }[];
  work_tasks: WorkTask[];
  work_tasks_version: string;
};
export type WorkMatch = {
  id: string;
  label: string;
  required_skills: string[];
  matched_skills: string[];
  missing_skills: string[];
  status: "covered" | "partial" | "gap";
};
export function useSkillsWorkCatalog() {
  const [catalog, setCatalog] = useState<SkillsWorkCatalog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void api<SkillsWorkCatalog>("/catalog")
      .then((value) => {
        if (active) setCatalog(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  return { catalog, error };
}

export function WorkTasks({
  catalog,
  specialization,
  value,
  onChange,
}: {
  catalog: SkillsWorkCatalog | null;
  specialization: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const tasks = (catalog?.work_tasks || []).filter(
    (task) => task.specialization === specialization,
  );
  const mapped = [
    ...new Set(
      tasks
        .filter((task) => value.includes(task.id))
        .flatMap((task) => task.skills),
    ),
  ];
  return (
    <fieldset className="work-tasks">
      <legend>Задачи команды</legend>
      <p className="muted">
        Задачи добавляют навыки к желательным условиям подбора. Обязательные
        навыки выбирайте отдельно. Веса балла остаются 45/35/10/10.
      </p>
      {!catalog ? (
        <p>Загрузка задач…</p>
      ) : (
        tasks.map((task) => (
          <label className="check work-task" key={task.id}>
            <input
              type="checkbox"
              checked={value.includes(task.id)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...value, task.id]
                    : value.filter((id) => id !== task.id),
                )
              }
            />
            <span>
              <strong>{task.label}</strong>
              <span>{task.description}</span>
              <span className="muted">Навыки: {task.skills.join(", ")}</span>
            </span>
          </label>
        ))
      )}
      {mapped.length > 0 && (
        <p className="work-task-mapping">
          Желательные навыки задач: {mapped.join(", ")}
        </p>
      )}
      {catalog?.work_tasks_version && (
        <p className="muted">Каталог задач: {catalog.work_tasks_version}</p>
      )}
    </fieldset>
  );
}

export function WorkMatches({ matches }: { matches?: WorkMatch[] }) {
  if (!matches?.length) return null;
  return (
    <div className="work-matches">
      <h4>Навыки для задач команды</h4>
      <p className="muted">
        Покрытие основано на навыках оценки категории. Совпадение навыков не
        подтверждает готовность выполнить задачу. Обсудите рабочий контекст и
        результаты практики.
      </p>
      <dl>
        {matches.map((match) => (
          <div key={match.id}>
            <dt>
              {match.label} ·{" "}
              {match.status === "covered"
                ? "Навыки покрыты"
                : match.status === "partial"
                  ? "Частичное покрытие"
                  : "Есть пробелы"}
            </dt>
            <dd>
              Требуются: {match.required_skills.join(", ") || "не указаны"}.
              Совпали: {match.matched_skills.join(", ") || "нет"}. Не
              подтверждены:{" "}
              {match.missing_skills.join(", ") || "нет пробелов в навыках"}.
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
