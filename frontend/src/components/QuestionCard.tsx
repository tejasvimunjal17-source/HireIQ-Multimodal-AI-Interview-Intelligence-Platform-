import type { Question } from "../types/interview";

interface QuestionCardProps {
  question: Question;
  number: number;
  answered: boolean;
}

export function QuestionCard({ question, number, answered }: QuestionCardProps) {
  return (
    <section className="card question-card" aria-labelledby="question-heading">
      <div className="question-meta">
        <span className={`badge badge-${question.question_type}`}>
          {question.question_type === "technical" ? "Technical" : "Behavioral"}
        </span>
        {answered && <span className="badge badge-done">Answered</span>}
      </div>
      <h2 id="question-heading" className="question-text">
        <span className="question-number">{number}.</span> {question.text}
      </h2>
    </section>
  );
}
