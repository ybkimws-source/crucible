import os
from dotenv import load_dotenv

load_dotenv()

MAX_ROUNDS = 2
BRIDGE_TIMEOUT = 180

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR      = os.path.join(_ROOT, "output/logs")
RESULTS_DIR   = os.path.join(_ROOT, "output/results")
TMP_DIR       = os.path.join(_ROOT, "tmp")
RESPONSES_DIR = os.path.join(_ROOT, "tmp/responses")
PROMPTS_DIR   = os.path.join(_ROOT, "tmp/prompts")
AGENTS_DIR    = os.path.join(_ROOT, "skills/agents")
FLOWS_DIR     = os.path.join(_ROOT, "skills/flows")
AGENTS_FILE   = os.path.join(_ROOT, "agents.json")
