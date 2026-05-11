import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    agent: str
    phase: str
    content: str
    round_num: int


@dataclass
class CrucibleState:
    problem: str
    messages: list[Message] = field(default_factory=list)
    round: int = 0
    consensus: bool = False
    final_verdict: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, agent: str, phase: str, content: str):
        with self._lock:
            self.messages.append(Message(agent, phase, content, self.round))

    def last(self, agent: str, phase: str = None) -> str:
        for m in reversed(self.messages):
            if m.agent == agent and (phase is None or m.phase == phase):
                return m.content
        return ""

    def history(self, phase: str = None) -> str:
        parts = []
        for m in self.messages:
            if phase and m.phase != phase:
                continue
            parts.append(f"[{m.agent} · Round {m.round_num} · {m.phase}]\n{m.content}")
        return "\n\n".join(parts)
