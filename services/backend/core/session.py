from dataclasses import dataclass, field
import asyncio
import uuid

@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    turn_id: int = 0
    current_task: asyncio.Task | None = None

    def next_turn(self) -> int:
        self.turn_id += 1
        return self.turn_id

    def cancel_current(self) -> None:
        if self.current_task and not self.current_task.done():
            self.current_task.cancel()
        self.current_task = None
