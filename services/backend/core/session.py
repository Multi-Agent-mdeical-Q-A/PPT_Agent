from dataclasses import dataclass, field
import asyncio
import uuid
from datetime import datetime, date

def _utc_iso(ts: float | None = None) -> str:
    # ISO8601 with Z suffix
    dt = datetime.utcnow() if ts is None else datetime.utcfromtimestamp(ts)
    return dt.isoformat(timespec="milliseconds") + "Z"

@dataclass
class TurnMetrics:
    session_id: str
    turn_id: int
    # perf_counter timestamps (monotonic)
    t0: float
    t_first_delta: float | None = None
    t_first_audio: float | None = None
    t_done: float | None = None
    t_interrupt_recv: float | None = None
    t_interrupt_done: float | None = None
    outcome: str = "ok"  # ok|cancelled|error
    err_type: str | None = None
    err_repr: str | None = None

    def to_record(self) -> dict:
        def ms(a: float | None, b: float | None) -> int | None:
            if a is None or b is None:
                return None
            return int(round((b - a) * 1000))

        return {
            "ts": _utc_iso(),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "t_first_delta_ms": ms(self.t0, self.t_first_delta),
            "t_first_audio_ms": ms(self.t0, self.t_first_audio),
            "t_total_ms": ms(self.t0, self.t_done),
            "t_interrupt_ms": ms(self.t_interrupt_recv, self.t_interrupt_done),
            "outcome": self.outcome,
            "err_type": self.err_type,
            "err": self.err_repr,
        }

@dataclass
class SessionState:
    turn_id: int = 0
    workflow_task: asyncio.Task | None = None
    cancel_event: asyncio.Event | None = None
    session_id: str = ""
    metrics: dict[int, TurnMetrics] | None = None
