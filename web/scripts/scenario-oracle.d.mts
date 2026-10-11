export type ScenarioQuestion = {
  id: string;
  title: string;
  options: string[];
};
export function scenarioAnswer(question: ScenarioQuestion, grade?: string): string;
