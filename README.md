# Crucible

Crucible is a CLI-based multi-agent LLM debate framework. It orchestrates Claude, Gemini, and Codex in separate persistent sessions, runs blind parallel openings, anonymized meta-analysis, objection loops, and final verdict generation.

Designed to reveal where AI systems genuinely disagree, where consensus is weak, and which assumptions need human verification.

Built entirely on CLI subscriptions — **$0 API cost**.

---

## Why

Asking a single AI a hard question has a known failure mode: it produces a confident, coherent answer shaped by its training priors, with no external pressure to surface its own blind spots.

The usual workaround — "argue both sides" or "steelman the opposite" — helps, but the model is still marking its own homework. It knows which position it started from.

Crucible puts three architecturally different models in separate sessions with no shared context, forces them to commit to independent positions before seeing each other, then runs structured debate rounds. The goal isn't to get a "better" answer — it's to find where genuine uncertainty and disagreement are concentrated, and make that visible.

---

## Design Decisions

**Blind parallel Phase 1**
All agents submit opening positions simultaneously without seeing each other. This eliminates anchoring bias from first-speaker advantage — a problem in any sequential debate format.

**Anonymized meta-analysis (Position A / B / C)**
The meta-agent synthesizes disagreements from anonymized inputs. Agents can't defer to authority ("Gemini said X, so it must be right") when they don't know who said what.

**Phase 1.6 objection loop**
After meta-analysis, each agent gets to flag distortions or missing points before debate begins. Prevents the synthesis step from quietly burying minority positions.

**Per-round user control**
After each debate round, the user decides whether to continue. The system doesn't assume more rounds are always better.

**$0 API cost**
All three agents run through their CLI tools (Claude Code, Gemini CLI, Codex CLI) via tmux sessions. The orchestrator communicates through a file-based bridge protocol — no API keys required beyond existing subscriptions.

---

## How It Works

```
Phase 1    Agents submit independent positions in parallel (blind)
Phase 1.5  Meta-agent extracts disagreements from anonymized inputs (Position A/B/C)
Phase 1.6  Each agent flags distortions or missing points
Phase 2    Parallel debate rounds — user decides when to stop
Phase 3    Sequential closing statements
Final      Meta-agent synthesizes consensus, remaining disputes, and recommendations
```

---

## Bring Your Own Prompts

Crucible does not assume that its default agents are the "right" agents.

The prompts are intentionally separated from the orchestration logic, so you can swap in your own agent behavior without touching the debate engine.

For example, my private Claude setup uses guidelines inspired by [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) for coding-heavy topics. You can do the same with your own Claude rules, Cursor rules, domain checklists, review rubrics, or research prompts.

Crucible is the harness. The agents are yours.

---

## Example Output

**Topic:** *Does a multi-agent AI debate system produce better insights than asking a single model?*

> **Bottom line:** Multi-agent debate is a useful technique under specific conditions, not a general epistemics upgrade. A well-designed single-model reflective workflow is competitive for most tasks; multi-agent debate earns its overhead primarily on open-ended, high-stakes questions with genuinely diverse agents.

Key finding the agents converged on: homogeneous models sharing similar training data don't produce genuine epistemic diversity — they amplify shared biases. Agent diversity (different model families, different architectures) is a requirement, not a bonus.

---

**Topic:** *Can an AI system meaningfully disagree with another AI, or is it always just simulating disagreement?*

> **Bottom line:** The right framing is not "real vs. simulated" but "substantive vs. staged" — and that distinction is empirically assessable. AI systems can meaningfully disagree in a functional and epistemic sense when divergence is reason-tracking, architecturally grounded, and consequential. It is not automatically meaningful from output divergence alone.

---

## Requirements

- Python 3.11+
- tmux
- [Claude Code CLI](https://github.com/anthropics/claude-code) (Claude Pro subscription)
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) (free tier available)
- [Codex CLI](https://github.com/openai/codex) (OpenAI subscription)

```bash
pip install rich python-dotenv
```

---

## Quickstart

### 1. Configure agents

Edit `agents.json` to match your tmux session names. Default:

```json
[
  { "name": "claude", "session": "crucible_claude", "role": "analyzer",  "system_skill": "claude" },
  { "name": "gemini", "session": "crucible_gemini", "role": "debater",   "system_skill": "gemini" },
  { "name": "codex",  "session": "crucible_codex",  "role": "debater",   "system_skill": "codex"  }
]
```

Set `"role": "meta"` on the agent you want to run meta-analysis and the final verdict.

### 2. Start sessions

```bash
bash scripts/bringup.sh
```

Follow the prompts to attach to each tmux session and accept permission warnings.

### 3. Run

```bash
python ui/app.py --debate
```

Enter your topic, press `Ctrl+D` to submit. After each round, choose whether to continue.

### 4. Options

```bash
python ui/app.py --debate --rounds 3          # max debate rounds (default: 2)
python ui/app.py --debate --lang ko           # Korean mode
python ui/app.py --debate --dir ./my_project  # include codebase context
python ui/app.py --mode full                  # analysis/verification mode (non-debate)
```

---

## Project Structure

```
crucible/
├── orchestrator.py       # debate flow controller
├── agents.json           # agent definitions
├── core/
│   ├── bridge.py         # tmux ↔ CLI file bridge
│   ├── agents.py         # agent loading
│   ├── prompts.py        # prompt builders
│   ├── state.py          # shared message history
│   └── config.py         # paths and timeouts
├── skills/
│   ├── agents/           # system prompts per agent (.en.md / .ko.md)
│   └── flows/            # phase prompts (analysis / rebuttal / final)
├── ui/
│   └── app.py            # Rich TUI
└── scripts/
    ├── bringup.sh        # start tmux sessions
    └── stop.sh           # kill sessions
```

---

## Bridge Protocol

Each agent runs as a persistent Claude/Gemini/Codex session inside a tmux window. The orchestrator sends prompts by pasting text into the tmux session, then polls a file for a sentinel line that signals the agent has finished writing its response.

```
orchestrator writes prompt file
→ pastes read instruction into tmux
→ agent writes response to output file ending with <<END:nonce>>
→ orchestrator detects sentinel, reads content
→ BridgeResult(ok, content, error, elapsed)
```

Errors are always isolated — a failed bridge call never injects error text into the debate.

---

## Limitations

- Agents share overlapping training data. Disagreements can reflect correlated priors rather than genuine epistemic diversity. (The agents themselves reached this conclusion when debating the system's own usefulness.)
- `sequential` debate mode is available but not recommended — it reintroduces anchoring bias. Use the default `blind_parallel`.
- Response time depends on CLI speed. Expect 30–90 seconds per agent per round.

---

## Status

Experimental prototype. The core architecture works, but the bridge protocol and agent prompts are still evolving.
