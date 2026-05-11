from __future__ import annotations
import os
from functools import lru_cache
from typing import TYPE_CHECKING
from core.config import AGENTS_DIR, FLOWS_DIR

if TYPE_CHECKING:
    from core.state import CrucibleState


@lru_cache(maxsize=64)
def _load_agent(name: str, lang: str) -> str:
    path = os.path.join(AGENTS_DIR, f"{name}.{lang}.md")
    if not os.path.exists(path):
        path = os.path.join(AGENTS_DIR, f"{name}.en.md")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


@lru_cache(maxsize=64)
def _load_flow(name: str, lang: str) -> str:
    path = os.path.join(FLOWS_DIR, f"{name}.{lang}.md")
    if not os.path.exists(path):
        path = os.path.join(FLOWS_DIR, f"{name}.en.md")
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def load_system(skill: str, lang: str) -> str:
    effective = "en" if lang == "mixed" else lang
    return _load_agent(skill, effective)


def build_analysis_prompt(state: CrucibleState, lang: str = "en", context: str = "") -> str:
    effective = "en" if lang == "mixed" else lang
    base = _load_flow("analysis", effective).format(problem=state.problem)
    if context:
        prefix = "[Project context]\n"
        return f"{prefix}{context}\n\n{base}"
    return base


def build_verification_prompt(state: CrucibleState, lang: str = "en",
                               mode: str = "summary", directory: str = None) -> str:
    effective = "en" if lang == "mixed" else lang
    base = _load_flow("verification", effective).format(
        problem=state.problem,
        history=state.history(),
    )
    if mode == "full" and directory:
        note = f"\n\nYou may explore the codebase at '{directory}' directly (grep, read files) to verify claims independently."
        return base + note
    return base


def build_rebuttal_prompt(state: CrucibleState, lang: str = "en") -> str:
    effective = "en" if lang == "mixed" else lang
    last_verifier = next(
        (m.content for m in reversed(state.messages) if m.agent != "claude"), ""
    )
    return _load_flow("rebuttal", effective).format(last_verifier=last_verifier)


def build_final_prompt(state: CrucibleState, lang: str = "en") -> str:
    effective = lang if lang in ("ko", "en", "mixed") else "en"
    return _load_flow("final", effective).format(history=state.history())
