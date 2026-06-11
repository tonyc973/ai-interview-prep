"""Unit tests for the LLM output schemas (validation + helpers)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.schemas import CompetencyScore, EvaluationReport
from tests.fakes import make_question_bank, make_report


def test_competency_score_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        CompetencyScore(competency="X", score=6, evidence=["q"], rationale="r")
    with pytest.raises(ValidationError):
        CompetencyScore(competency="X", score=0, evidence=["q"], rationale="r")


def test_competency_score_accepts_in_range() -> None:
    cs = CompetencyScore(competency="X", score=3, evidence=["q"], rationale="r")
    assert cs.score == 3


def test_overall_score_clamped_range_and_rounding() -> None:
    with pytest.raises(ValidationError):
        make_report_with_overall(5.5)
    report = make_report_with_overall(3.456)
    assert report.overall_score == 3.5  # rounded to 1 decimal


def test_question_bank_all_questions_and_counts() -> None:
    qb = make_question_bank()
    assert len(qb.all_questions()) == len(qb.technical) + len(qb.behavioral) + len(qb.company)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        CompetencyScore.model_validate(
            {
                "competency": "X",
                "score": 3,
                "evidence": ["q"],
                "rationale": "r",
                "surprise": "nope",
            }
        )


def test_radar_series_alignment() -> None:
    report = make_report()
    labels, values = report.radar_series()
    assert len(labels) == len(values) == len(report.competency_scores)
    assert values == [c.score for c in report.competency_scores]


def make_report_with_overall(value: float) -> EvaluationReport:
    data = make_report().model_dump()
    data["overall_score"] = value
    return EvaluationReport.model_validate(data)
