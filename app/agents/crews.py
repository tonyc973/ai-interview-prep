"""CrewAI wiring for the session-creation pipeline (research -> questions).

A sequential two-agent crew. Both agents use :class:`GatewayLLM`, so all traffic
flows through our gateway. This runs synchronously and MUST be invoked off the
event loop (``run.io_bound``). The live interview loop and evaluation do **not**
use a crew — see ``app/services/interview_service.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Disable CrewAI/OpenTelemetry phone-home before crewai builds anything.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from crewai import Agent, Crew, CrewOutput, Process, Task

from app.agents import prompts
from app.agents.crew_llm import GatewayLLM
from app.agents.gateway import CallContext, LLMGateway, UsageLedger
from app.agents.schemas import QuestionBank, ResearchBrief
from app.domain.enums import AgentName, LLMOperation, SeniorityLevel

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(slots=True)
class PrepResult:
    brief: ResearchBrief
    questions: QuestionBank
    ledger: UsageLedger


def _agent_llm(
    *,
    settings: Settings,
    gateway: LLMGateway,
    ledger: UsageLedger,
    agent: AgentName,
    operation: LLMOperation,
) -> GatewayLLM:
    return GatewayLLM(
        model=settings.model_for_agent(agent),
        gateway=gateway,
        ledger=ledger,
        context=CallContext(
            user_id=ledger.user_id,
            session_id=ledger.session_id,
            operation=operation,
            agent_name=agent.value,
        ),
        temperature=0.4,
    )


def _kickoff_single(crew: Crew) -> CrewOutput:
    output = crew.kickoff()
    if not isinstance(output, CrewOutput):
        raise TypeError("Crew returned a streaming output; expected CrewOutput")
    return output


def run_research_stage(
    *,
    settings: Settings,
    gateway: LLMGateway,
    ledger: UsageLedger,
    target_role: str,
    target_company: str,
    seniority: SeniorityLevel,
    job_description: str,
    cv_text: str | None,
) -> ResearchBrief:
    """Stage 1: produce the ResearchBrief. Runs synchronously (call off-loop)."""
    researcher = Agent(
        role=prompts.ROLE_RESEARCHER["role"],
        goal=prompts.ROLE_RESEARCHER["goal"],
        backstory=prompts.ROLE_RESEARCHER["backstory"],
        llm=_agent_llm(
            settings=settings,
            gateway=gateway,
            ledger=ledger,
            agent=AgentName.ROLE_RESEARCHER,
            operation=LLMOperation.RESEARCH,
        ),
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )
    description, expected = prompts.research_task_prompt(
        target_role=target_role,
        target_company=target_company,
        seniority=seniority,
        job_description=job_description,
        cv_text=cv_text,
    )
    task = Task(
        description=description,
        expected_output=expected,
        agent=researcher,
        output_pydantic=ResearchBrief,
    )
    crew = Crew(
        agents=[researcher], tasks=[task], process=Process.sequential, memory=False, cache=False
    )
    brief = _kickoff_single(crew).tasks_output[0].pydantic
    if not isinstance(brief, ResearchBrief):
        raise TypeError("Research stage did not return a ResearchBrief")
    return brief


def run_questions_stage(
    *,
    settings: Settings,
    gateway: LLMGateway,
    ledger: UsageLedger,
    target_role: str,
    target_company: str,
    seniority: SeniorityLevel,
    brief: ResearchBrief,
) -> QuestionBank:
    """Stage 2: produce the QuestionBank from the brief. Runs synchronously."""
    architect = Agent(
        role=prompts.QUESTION_ARCHITECT["role"],
        goal=prompts.QUESTION_ARCHITECT["goal"],
        backstory=prompts.QUESTION_ARCHITECT["backstory"],
        llm=_agent_llm(
            settings=settings,
            gateway=gateway,
            ledger=ledger,
            agent=AgentName.QUESTION_ARCHITECT,
            operation=LLMOperation.QUESTION_GENERATION,
        ),
        allow_delegation=False,
        verbose=False,
        max_iter=3,
    )
    description, expected = prompts.questions_task_prompt(
        target_role=target_role,
        target_company=target_company,
        seniority=seniority,
        brief_json=brief.model_dump_json(indent=2),
    )
    task = Task(
        description=description,
        expected_output=expected,
        agent=architect,
        output_pydantic=QuestionBank,
    )
    crew = Crew(
        agents=[architect], tasks=[task], process=Process.sequential, memory=False, cache=False
    )
    questions = _kickoff_single(crew).tasks_output[0].pydantic
    if not isinstance(questions, QuestionBank):
        raise TypeError("Questions stage did not return a QuestionBank")
    return questions


def run_prep_pipeline(
    *,
    settings: Settings,
    gateway: LLMGateway,
    ledger: UsageLedger,
    target_role: str,
    target_company: str,
    seniority: SeniorityLevel,
    job_description: str,
    cv_text: str | None,
) -> PrepResult:
    """Convenience: run both stages back-to-back (used by smoke/tests)."""
    brief = run_research_stage(
        settings=settings,
        gateway=gateway,
        ledger=ledger,
        target_role=target_role,
        target_company=target_company,
        seniority=seniority,
        job_description=job_description,
        cv_text=cv_text,
    )
    questions = run_questions_stage(
        settings=settings,
        gateway=gateway,
        ledger=ledger,
        target_role=target_role,
        target_company=target_company,
        seniority=seniority,
        brief=brief,
    )
    return PrepResult(brief=brief, questions=questions, ledger=ledger)
