"""Pure domain enumerations. No IO, no framework imports.

These are the canonical vocabulary shared across the persistence, service, and
agent layers. They are stored in the database as portable strings (never native
DB enums) so the SQLite -> Postgres swap stays a config-only change.
"""

from __future__ import annotations

from enum import StrEnum


class SeniorityLevel(StrEnum):
    """Target seniority a candidate is interviewing for."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    LEAD = "lead"
    PRINCIPAL = "principal"

    @property
    def label(self) -> str:
        return {
            SeniorityLevel.INTERN: "Intern",
            SeniorityLevel.JUNIOR: "Junior",
            SeniorityLevel.MID: "Mid-level",
            SeniorityLevel.SENIOR: "Senior",
            SeniorityLevel.STAFF: "Staff",
            SeniorityLevel.LEAD: "Lead",
            SeniorityLevel.PRINCIPAL: "Principal",
        }[self]


class SessionStatus(StrEnum):
    """Lifecycle of the prep pipeline (research -> question generation).

    Surfaced directly in the UI as progress state.
    """

    PENDING = "pending"
    RESEARCHING = "researching"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (SessionStatus.READY, SessionStatus.FAILED)


class InterviewStatus(StrEnum):
    """Lifecycle of the live mock interview + evaluation."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"  # all questions asked, awaiting / running evaluation
    EVALUATING = "evaluating"
    EVALUATED = "evaluated"
    FAILED = "failed"


class QuestionCategory(StrEnum):
    """Buckets the Question Architect must fill."""

    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    COMPANY = "company"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class MessageRole(StrEnum):
    """Authors of a transcript turn."""

    SYSTEM = "system"
    INTERVIEWER = "interviewer"
    CANDIDATE = "candidate"


class LLMOperation(StrEnum):
    """Categories of LLM work, used for usage/cost accounting."""

    RESEARCH = "research"
    QUESTION_GENERATION = "question_generation"
    INTERVIEW_TURN = "interview_turn"
    EVALUATION = "evaluation"
    SMOKE = "smoke"


class AgentName(StrEnum):
    """Stable identifiers for each CrewAI agent (config + logging + usage)."""

    ROLE_RESEARCHER = "role_researcher"
    QUESTION_ARCHITECT = "question_architect"
    MOCK_INTERVIEWER = "mock_interviewer"
    EVALUATOR = "evaluator"
