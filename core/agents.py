import json
from dataclasses import dataclass
from core.config import AGENTS_FILE

REQUIRED_FIELDS = {"name", "session", "role", "system_skill"}


@dataclass
class AgentConfig:
    name: str
    session: str
    role: str
    system_skill: str
    system_prompt: str = ""


def load_agents(skills, lang: str = "en") -> dict[str, AgentConfig]:
    with open(AGENTS_FILE, encoding="utf-8") as f:
        defs = json.load(f)

    if not defs:
        raise ValueError("agents.json is empty")

    seen_names = set()
    agents = {}
    for d in defs:
        missing = REQUIRED_FIELDS - set(d.keys())
        if missing:
            raise ValueError(f"agents.json entry missing required fields: {missing} → {d}")
        if d["name"] in seen_names:
            raise ValueError(f"duplicate agent name in agents.json: '{d['name']}'")
        seen_names.add(d["name"])

        cfg = AgentConfig(
            name=d["name"],
            session=d["session"],
            role=d["role"],
            system_skill=d["system_skill"],
        )
        cfg.system_prompt = skills.load_system(d["system_skill"], lang)
        agents[d["name"]] = cfg
    return agents


def pick_meta_agent(agents: dict[str, AgentConfig], preferred: str = None) -> str:
    """Select meta-analysis agent: preferred > role=meta > first agent."""
    if preferred and preferred in agents:
        return preferred
    for name, cfg in agents.items():
        if cfg.role == "meta":
            return name
    return next(iter(agents))
