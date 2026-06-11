"""Validated Pydantic output schemas for every LLM-producing step.

These are the contract between the agents layer and the rest of the app. CrewAI
tasks declare them via ``output_pydantic=...`` and the gateway parses direct
calls into them via the OpenAI structured-output API. Nothing downstream ever
parses free text.

Schema design rules (see docs/INTERNAL_API_NOTES.md): all fields are required
(no defaults) for OpenAI strict structured output; numeric ranges are enforced
with ``field_validator`` (which runs after parse) and described in field text so
the model complies, rather than with ``Field(ge=/le=)`` which can trip the strict
JSON-schema generator.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Difficulty, QuestionCategory

SCORE_MIN = 1
SCORE_MAX = 5


class _Strict(BaseModel):
    """Base for all LLM output models: forbid extras, validate on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- #
# Research
# --------------------------------------------------------------------------- #
class ResearchBrief(_Strict):
    """Synthesis of the job description + company into an interview brief."""

    role_summary: str = Field(description="2-4 sentence summary of the role and its scope.")
    key_competencies: list[str] = Field(
        description="5-10 competencies this interview will most likely probe."
    )
    likely_interview_format: str = Field(
        description="The probable interview structure and rounds, given the inputs."
    )
    company_values: list[str] = Field(
        description="Company values / cultural signals inferred from the inputs."
    )
    signals_to_emphasize: list[str] = Field(
        description="What a strong candidate should emphasize for this role/company."
    )
    inferred_assumptions: list[str] = Field(
        description=(
            "Claims that are INFERENCES not stated in the inputs, each explicitly "
            "phrased as an assumption (no external/web facts allowed)."
        )
    )


# --------------------------------------------------------------------------- #
# Question bank
# --------------------------------------------------------------------------- #
class InterviewQuestion(_Strict):
    """A single prepared question with its grading rubric."""

    id: str = Field(description="Stable id, e.g. 'tech-1', 'beh-3', 'comp-2'.")
    category: QuestionCategory
    question: str
    difficulty: Difficulty
    target_competency: str = Field(description="The competency this question measures.")
    rubric: str = Field(
        description="What a strong answer must cover; the model-answer grading rubric."
    )


class QuestionBank(_Strict):
    """The full prepared question set plus a study plan."""

    technical: list[InterviewQuestion] = Field(description="~10 technical questions.")
    behavioral: list[InterviewQuestion] = Field(
        description="~8 behavioral questions, STAR-targeted."
    )
    company: list[InterviewQuestion] = Field(description="~5 company / values questions.")
    study_plan: list[str] = Field(
        description="Ordered, actionable study steps tailored to the gaps."
    )

    def all_questions(self) -> list[InterviewQuestion]:
        return [*self.technical, *self.behavioral, *self.company]


# --------------------------------------------------------------------------- #
# Live interview turn
# --------------------------------------------------------------------------- #
class InterviewTurn(_Strict):
    """One interviewer utterance produced per turn by the Mock Interviewer."""

    question: str = Field(description="The single question to ask the candidate now.")
    covers_competency: str = Field(description="Competency this turn targets.")
    is_followup: bool = Field(description="True if this digs into the candidate's previous answer.")
    rationale: str = Field(
        description="Internal note on why this question/follow-up was chosen (not shown)."
    )
    closing: bool = Field(
        description="True only on the final turn, which should thank and wrap up."
    )


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
class CompetencyScore(_Strict):
    """Score for one competency, with mandatory transcript evidence."""

    competency: str
    score: int = Field(description="Integer 1-5 (1 weak, 5 excellent).")
    evidence: list[str] = Field(
        description="Direct short quotes from the candidate's transcript answers."
    )
    rationale: str = Field(description="Why this score, grounded in the evidence.")

    @field_validator("score")
    @classmethod
    def _score_in_range(cls, v: int) -> int:
        if not SCORE_MIN <= v <= SCORE_MAX:
            raise ValueError(f"score must be between {SCORE_MIN} and {SCORE_MAX}")
        return v


class ModelAnswer(_Strict):
    """An exemplar answer to a question the candidate handled weakly."""

    question: str
    strong_answer: str = Field(description="A concise model answer a strong candidate gives.")


class ImprovementItem(_Strict):
    """A single prioritized improvement action."""

    priority: int = Field(description="1 = highest priority. Lower number = more urgent.")
    focus_area: str
    action: str = Field(description="Concrete, specific action the candidate should take.")

    @field_validator("priority")
    @classmethod
    def _priority_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("priority must be >= 1")
        return v


class EvaluationReport(_Strict):
    """The final structured feedback report for a completed mock interview."""

    overall_score: float = Field(
        description="Overall performance 1.0-5.0 (one decimal), aligned to per-competency scores."
    )
    summary: str = Field(description="3-5 sentence honest, specific summary. No generic praise.")
    competency_scores: list[CompetencyScore] = Field(
        description="One entry per competency assessed, each with transcript evidence."
    )
    strengths: list[str] = Field(description="Specific strengths, each tied to something said.")
    gaps: list[str] = Field(description="Specific gaps/weaknesses observed.")
    model_answers: list[ModelAnswer] = Field(
        description="Model answers for the questions handled least well."
    )
    improvement_plan: list[ImprovementItem] = Field(
        description="Prioritized, actionable improvement plan (priority 1 first)."
    )
    next_steps: list[str] = Field(description="Immediate next steps before the real interview.")

    @field_validator("overall_score")
    @classmethod
    def _overall_in_range(cls, v: float) -> float:
        if not float(SCORE_MIN) <= v <= float(SCORE_MAX):
            raise ValueError(f"overall_score must be between {SCORE_MIN} and {SCORE_MAX}")
        return round(v, 1)

    def radar_series(self) -> tuple[list[str], list[int]]:
        """Return (competency labels, scores) for the UI radar chart."""
        labels = [c.competency for c in self.competency_scores]
        values = [c.score for c in self.competency_scores]
        return labels, values
