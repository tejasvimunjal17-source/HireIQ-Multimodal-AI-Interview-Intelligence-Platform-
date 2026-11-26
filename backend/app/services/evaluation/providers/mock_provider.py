"""Deterministic offline provider for development and tests. Makes NO network call.

It answers through the same path as a real model: it returns JSON TEXT that the engine parses and
validates. Criteria and the score scale come from the prompt (i.e. from the YAML rubric); quotes are real
word windows of the transcript, so the evidence check passes. Same input => same output. The scores are
obviously fake and say nothing about the candidate.
"""

import json

from app.schemas.evaluation import MIN_QUOTE_WORDS
from app.services.evaluation.prompt_builder import EvaluationPrompt
from app.services.evaluation.providers.base import EvaluationProvider, ProviderOutput

MOCK_MODEL = "mock-evaluator-1"
_BASE_FRACTION = 0.7  # fake performance level: 70% of the scale


class MockEvaluationProvider(EvaluationProvider):
    name = "mock"
    model = MOCK_MODEL

    def evaluate(self, prompt: EvaluationPrompt) -> ProviderOutput:
        context = prompt.context
        low, high = context.score_min, context.score_max
        base = low + round((high - low) * _BASE_FRACTION)
        words = [w for w in context.transcript.split() if any(ch.isalnum() for ch in w)]
        window = min(len(words), max(MIN_QUOTE_WORDS, 6))

        criteria, scores = [], []
        for index, key in enumerate(context.criteria_keys):
            score = max(low, base - (index % 2))  # alternate so weighting is visible
            start = (index * window) % max(1, len(words) - window + 1)
            quote = " ".join(words[start:start + window])
            scores.append(score)
            criteria.append({
                "criterion_key": key,
                "score": score,
                "explanation": f"Mock evaluation for {key.replace('_', ' ')}: fixed score for testing only.",
                "evidence_quotes": [quote],
            })
        mean = sum(scores) / len(scores)
        fraction = (mean - low) / (high - low)
        recommendation = "proceed" if fraction >= 0.7 else "hold" if fraction >= 0.4 else "reject"
        body = {
            "overall_score": round(mean, 2),
            "criteria_scores": criteria,
            "strengths": ["Mock strength"],
            "areas_for_improvement": ["Mock improvement"],
            "summary": "Mock evaluation produced without any model call.",
            "recommendation": recommendation,
        }
        return ProviderOutput(raw_text=json.dumps(body), provider=self.name, model=self.model)
