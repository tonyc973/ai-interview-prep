"""Seed a demo database with rich, realistic content for screenshots/demos.

NO OpenAI calls — content is hand-authored and validated through the real
schemas. Usage:
    APP_DATABASE_URL=sqlite+aiosqlite:///./data/demo.db uv run python -m scripts.seed_demo
Prints the demo login + session URLs.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from app.agents.schemas import (
    CompetencyScore,
    EvaluationReport,
    ImprovementItem,
    InterviewQuestion,
    ModelAnswer,
    QuestionBank,
    ResearchBrief,
)
from app.db.base import session_scope
from app.db.bootstrap import init_database
from app.db.models import EvaluationRow, PrepSession
from app.db.repositories import TranscriptRepository, UserRepository
from app.domain.enums import (
    Difficulty,
    InterviewStatus,
    MessageRole,
    QuestionCategory,
    SeniorityLevel,
    SessionStatus,
)
from app.services import security

DEMO_EMAIL = "alex.candidate@example.com"
DEMO_PASSWORD = "northwind-rocket-stew-2031"  # noqa: S105 — demo seed only

SID_EVALUATED = uuid.UUID("11111111-1111-4111-8111-111111111111")
SID_IN_PROGRESS = uuid.UUID("22222222-2222-4222-8222-222222222222")
SID_READY = uuid.UUID("33333333-3333-4333-8333-333333333333")


def _brief() -> ResearchBrief:
    return ResearchBrief(
        role_summary=(
            "A Senior Backend Engineer at Northwind Labs owning the reliability and scale of "
            "the payments platform — designing distributed services, leading technical "
            "direction, and mentoring mid-level engineers."
        ),
        key_competencies=[
            "Distributed systems design",
            "Reliability & observability",
            "API & data modeling",
            "Communication & influence",
            "Ownership & pragmatism",
        ],
        likely_interview_format=(
            "Recruiter screen → technical phone screen (coding) → virtual onsite: system "
            "design, two coding rounds, and a behavioral/values interview."
        ),
        company_values=[
            "Customer obsession",
            "Bias for ownership",
            "Operational excellence",
            "Disagree and commit",
        ],
        signals_to_emphasize=[
            "Concrete scale numbers (QPS, data size, latency budgets)",
            "Incident ownership and what changed afterward",
            "Trade-off reasoning over buzzwords",
        ],
        inferred_assumptions=[
            "Assumed the stack is Python/Go on AWS (not stated in the posting).",
            "Assumed an on-call rotation given the reliability emphasis.",
        ],
    )


def _q(
    qid: str, cat: QuestionCategory, diff: Difficulty, comp: str, q: str, rub: str
) -> InterviewQuestion:
    return InterviewQuestion(
        id=qid, category=cat, question=q, difficulty=diff, target_competency=comp, rubric=rub
    )


def _questions() -> QuestionBank:
    t, b, c = QuestionCategory.TECHNICAL, QuestionCategory.BEHAVIORAL, QuestionCategory.COMPANY
    hard, med = Difficulty.HARD, Difficulty.MEDIUM
    return QuestionBank(
        technical=[
            _q(
                "tech-1",
                t,
                hard,
                "Distributed systems design",
                "Design a globally-distributed idempotent payments API. How do you guarantee "
                "exactly-once charge semantics?",
                "Covers idempotency keys, a dedup store, retries, and failure windows.",
            ),
            _q(
                "tech-2",
                t,
                hard,
                "Reliability & observability",
                "A service's p99 latency tripled overnight with no deploy. Walk me through your "
                "investigation.",
                "Structured triage: dashboards, infra changes, dependency latency, saturation.",
            ),
            _q(
                "tech-3",
                t,
                med,
                "API & data modeling",
                "Model the schema for a ledger supporting refunds, disputes, and audits.",
                "Append-only entries, double-entry accounting, immutability, reconciliation.",
            ),
            _q(
                "tech-4",
                t,
                med,
                "Distributed systems design",
                "How would you shard a 50TB Postgres table growing 2TB/month?",
                "Shard key choice, hot partitions, online migration, cross-shard queries.",
            ),
            _q(
                "tech-5",
                t,
                hard,
                "Reliability & observability",
                "Design an alerting strategy that pages on symptoms, not causes.",
                "SLOs, error budgets, multi-window burn-rate alerts, noise reduction.",
            ),
            _q(
                "tech-6",
                t,
                med,
                "API & data modeling",
                "Design a rate limiter for 1M users with per-tenant quotas.",
                "Token bucket, distributed counters, fairness, clock skew.",
            ),
        ],
        behavioral=[
            _q(
                "beh-1",
                b,
                med,
                "Ownership & pragmatism",
                "Tell me about a production incident you owned end to end.",
                "STAR: clear role, blast radius, mitigation, durable fix, follow-through.",
            ),
            _q(
                "beh-2",
                b,
                med,
                "Communication & influence",
                "Describe a time you changed a team's technical direction.",
                "Evidence-based persuasion, stakeholder mapping, measurable outcome.",
            ),
            _q(
                "beh-3",
                b,
                med,
                "Ownership & pragmatism",
                "When did you ship something imperfect to hit a deadline? What did you trade?",
                "Explicit trade-offs, risk management, debt paid down later.",
            ),
            _q(
                "beh-4",
                b,
                hard,
                "Communication & influence",
                "Tell me about a disagreement with a senior engineer. How did it resolve?",
                "Disagree-and-commit, data over ego, relationship preserved.",
            ),
            _q(
                "beh-5",
                b,
                med,
                "Ownership & pragmatism",
                "How do you mentor mid-level engineers without becoming a bottleneck?",
                "Delegation, code-review culture, growth framing.",
            ),
        ],
        company=[
            _q(
                "comp-1",
                c,
                med,
                "Customer obsession",
                "Northwind values 'customer obsession.' Give a concrete example from your work.",
                "Real customer impact, a metric moved, not a slogan.",
            ),
            _q(
                "comp-2",
                c,
                med,
                "Operational excellence",
                "What does operational excellence mean to you on a payments team?",
                "Runbooks, SLOs, blameless postmortems, automation.",
            ),
            _q(
                "comp-3",
                c,
                hard,
                "Bias for ownership",
                "Tell me about something broken that wasn't your job — and what you did.",
                "Proactive ownership beyond mandate, measurable result.",
            ),
        ],
        study_plan=[
            "Re-derive idempotency + exactly-once patterns; write a one-pager.",
            "Prepare two incident STAR stories with crisp metrics.",
            "Drill system design: payments ledger, rate limiter, sharding.",
            "Map three answers to Northwind's stated values with real evidence.",
        ],
    )


def _report() -> EvaluationReport:
    return EvaluationReport(
        overall_score=4.2,
        summary=(
            "A strong senior candidate: distributed-systems answers were concrete and "
            "trade-off driven, and incident ownership came through clearly. The main gap was "
            "crispness under follow-up — a few answers buried the key decision. Tighten the lead "
            "sentence of each story and this is a confident hire-level performance."
        ),
        competency_scores=[
            CompetencyScore(
                competency="Distributed systems design",
                score=5,
                evidence=["I used idempotency keys with a 24h dedup store keyed by request id."],
                rationale="Reached exactly-once reasoning quickly and handled the retry window.",
            ),
            CompetencyScore(
                competency="Reliability & observability",
                score=4,
                evidence=["First I'd check burn-rate alerts and recent dependency latency."],
                rationale="Symptom-first triage; could have quantified SLOs.",
            ),
            CompetencyScore(
                competency="API & data modeling",
                score=4,
                evidence=["I'd make the ledger append-only with double-entry rows."],
                rationale="Solid immutability instincts; reconciliation was light.",
            ),
            CompetencyScore(
                competency="Communication & influence",
                score=4,
                evidence=["I wrote a one-pager with latency data and let the numbers argue."],
                rationale="Evidence-based persuasion; the story meandered before the point.",
            ),
            CompetencyScore(
                competency="Ownership & pragmatism",
                score=4,
                evidence=["I paged myself, mitigated in 12 minutes, then wrote the postmortem."],
                rationale="Clear end-to-end ownership and durable follow-through.",
            ),
        ],
        strengths=[
            "Concrete, metric-rich incident ownership.",
            "Exactly-once / idempotency reasoning was fast and correct.",
            "Comfortable with trade-offs instead of buzzwords.",
        ],
        gaps=[
            "Answers sometimes bury the key decision in the middle.",
            "Reliability answers lacked explicit SLO / error-budget numbers.",
        ],
        model_answers=[
            ModelAnswer(
                question="Design a globally-distributed idempotent payments API.",
                strong_answer=(
                    "Lead with the contract: every charge carries a client-supplied idempotency "
                    "key; a dedup store records (key → result) with a TTL longer than the max "
                    "retry window. Writes are conditional on the key being unseen, so concurrent "
                    "retries collapse to one charge. Cross-region, route by key to a home region "
                    "and replicate the dedup record before acking."
                ),
            ),
        ],
        improvement_plan=[
            ImprovementItem(
                priority=1,
                focus_area="Answer structure",
                action="Open every story with a one-sentence decision + outcome.",
            ),
            ImprovementItem(
                priority=2,
                focus_area="Reliability rigor",
                action="Attach SLOs and error-budget numbers to reliability answers.",
            ),
            ImprovementItem(
                priority=3,
                focus_area="Reconciliation",
                action="Practice the ledger reconciliation + dispute flow out loud.",
            ),
        ],
        next_steps=[
            "Record yourself answering two STAR stories; cut each to 90 seconds.",
            "Do one mock system-design on the payments ledger this week.",
        ],
    )


_TRANSCRIPT = [
    (
        MessageRole.INTERVIEWER,
        "Thanks for joining. To start: design a globally-distributed, "
        "idempotent payments API. How do you guarantee exactly-once charge semantics?",
    ),
    (
        MessageRole.CANDIDATE,
        "I'd make every charge carry a client-supplied idempotency key. A dedup store "
        "records the key with the result and a TTL longer than our max retry window, so "
        "concurrent retries collapse to a single charge.",
    ),
    (
        MessageRole.INTERVIEWER,
        "Good. What happens if the dedup write succeeds but the charge fails midway?",
    ),
    (
        MessageRole.CANDIDATE,
        "I store the key in a 'pending' state first, then transition to "
        "'succeeded' or 'failed' atomically with the charge. A retry on a 'pending' key re-drives "
        "the same operation rather than starting a new one.",
    ),
    (MessageRole.INTERVIEWER, "Tell me about a production incident you owned end to end."),
    (
        MessageRole.CANDIDATE,
        "Our settlement job silently fell behind during a region failover. I "
        "paged myself, mitigated in about 12 minutes by failing over the queue, then wrote the "
        "postmortem and added a burn-rate alert so we'd catch it in 2 minutes next time.",
    ),
    (MessageRole.INTERVIEWER, "Northwind values 'customer obsession.' Give a concrete example."),
    (
        MessageRole.CANDIDATE,
        "I noticed refunds took 5 days for a segment of users, dug in, and found a "
        "batch window we could shorten. We cut it to same-day, which dropped related "
        "support tickets by about 30%.",
    ),
]


def _make_session(
    sid: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role: str,
    company: str,
    seniority: SeniorityLevel,
    interview_status: InterviewStatus,
    total: int,
    current: int,
    brief_json: dict[str, object],
    questions_json: dict[str, object],
) -> PrepSession:
    return PrepSession(
        id=sid,
        user_id=user_id,
        target_role=role,
        target_company=company,
        seniority=seniority,
        job_description=f"Own and scale the {role} charter at {company}…",
        cv_text=None,
        status=SessionStatus.READY,
        research_brief=brief_json,
        question_bank=questions_json,
        interview_status=interview_status,
        interview_total_questions=total,
        interview_current_index=current,
    )


async def seed() -> None:
    url = os.environ.get("APP_DATABASE_URL", "sqlite+aiosqlite:///./data/demo.db")
    await init_database(url)

    brief_json = _brief().model_dump(mode="json")
    questions_json = _questions().model_dump(mode="json")
    report = _report()

    async with session_scope() as session:
        user = await UserRepository(session).create(
            email=DEMO_EMAIL, password_hash=security.hash_password(DEMO_PASSWORD)
        )
        user.dark_mode = True

        session.add(
            _make_session(
                SID_EVALUATED,
                user.id,
                role="Senior Backend Engineer",
                company="Northwind Labs",
                seniority=SeniorityLevel.SENIOR,
                interview_status=InterviewStatus.EVALUATED,
                total=4,
                current=4,
                brief_json=brief_json,
                questions_json=questions_json,
            )
        )
        session.add(
            _make_session(
                SID_IN_PROGRESS,
                user.id,
                role="Product Designer",
                company="Lumina",
                seniority=SeniorityLevel.MID,
                interview_status=InterviewStatus.IN_PROGRESS,
                total=6,
                current=2,
                brief_json=brief_json,
                questions_json=questions_json,
            )
        )
        session.add(
            _make_session(
                SID_READY,
                user.id,
                role="Data Scientist",
                company="Helix Bio",
                seniority=SeniorityLevel.SENIOR,
                interview_status=InterviewStatus.NOT_STARTED,
                total=8,
                current=0,
                brief_json=brief_json,
                questions_json=questions_json,
            )
        )
        await session.flush()

        session.add(
            EvaluationRow(
                session_id=SID_EVALUATED,
                overall_score=report.overall_score,
                summary=report.summary,
                report=report.model_dump(mode="json"),
            )
        )

        transcripts = TranscriptRepository(session)
        for i, (role, content) in enumerate(_TRANSCRIPT):
            await transcripts.add_turn(
                session_id=SID_EVALUATED,
                turn_index=i,
                role=role,
                content=content,
                question_index=(i // 2 + 1) if role == MessageRole.INTERVIEWER else None,
            )
        for i, (role, content) in enumerate(_TRANSCRIPT[:3]):
            await transcripts.add_turn(
                session_id=SID_IN_PROGRESS,
                turn_index=i,
                role=role,
                content=content,
                question_index=(i // 2 + 1) if role == MessageRole.INTERVIEWER else None,
            )

    print(f"Seeded demo data into {url}")
    print(f"  login: {DEMO_EMAIL}  /  {DEMO_PASSWORD}")
    print(f"  evaluated  : /session/{SID_EVALUATED}")
    print(f"  in-progress: /session/{SID_IN_PROGRESS}/interview")
    print(f"  ready      : /session/{SID_READY}")


if __name__ == "__main__":
    asyncio.run(seed())
