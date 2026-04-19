from __future__ import annotations

from datetime import datetime

from models.agent import AgentRun, AgentStatus


def finalize_run_success(run: AgentRun, result: dict, success_note: str) -> None:
    run.output_artifact = result
    run.status = AgentStatus.COMPLETED
    run.completed_at = datetime.utcnow()
    run.latency_ms = _compute_latency_ms(run)
    run.error_message = None
    run.error_kind = None
    run.log_entries.append(f"[{run.completed_at.isoformat()}] {success_note}")


def finalize_run_failure(run: AgentRun, exc: Exception, failure_note: str, trace: str) -> None:
    run.status = AgentStatus.FAILED
    run.completed_at = datetime.utcnow()
    run.latency_ms = _compute_latency_ms(run)
    run.error_message = str(exc)
    kind = getattr(exc, "kind", None)
    retry_count = getattr(exc, "retry_count", None)
    if isinstance(kind, str):
        run.error_kind = kind
    else:
        run.error_kind = run.error_kind or "runtime_error"
    if isinstance(retry_count, int):
        run.retry_count = max(run.retry_count, retry_count)
    run.log_entries.append(f"[{run.completed_at.isoformat()}] {failure_note}: {exc}")
    run.log_entries.append(trace)


def _compute_latency_ms(run: AgentRun) -> int | None:
    if not run.started_at or not run.completed_at:
        return None
    return int((run.completed_at - run.started_at).total_seconds() * 1000)
