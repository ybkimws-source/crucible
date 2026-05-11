import os
import json
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from core.agents import load_agents, pick_meta_agent
from core.bridge import CLIBridge, BridgeResult
from core.state import CrucibleState
from core.config import LOGS_DIR, RESULTS_DIR, MAX_ROUNDS, BRIDGE_TIMEOUT
import core.prompts as prompts


def _detect_consensus(response: str) -> bool:
    """Check only the last non-empty line to avoid false positives from quoted text."""
    for line in reversed(response.splitlines()):
        line = line.strip()
        if not line:
            continue
        if line == "[RESULT: CONSENSUS]":
            return True
        if line == "[RESULT: DISAGREED]":
            return False
        return False
    return False


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _scan_context(directory: str, max_depth: int = 4) -> str:
    lines = [f"[Project scan: {directory}]"]
    exts = set()
    paths = []
    skip = ("__pycache__", ".git", "node_modules", "tmp", "output")
    base_depth = directory.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip]
        depth = root.count(os.sep) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        paths.append(root)
        for f in files:
            paths.append(os.path.join(root, f))
            ext = os.path.splitext(f)[1]
            if ext:
                exts.add(ext)
    lines.append("\n".join(paths))
    lines.append(f"\n[Extensions found]: {', '.join(sorted(exts))}")
    return "\n".join(lines)


class Crucible:
    def __init__(self, lang: str = "en", mode: str = "summary",
                 debate_mode: str = "blind_parallel",
                 meta_agent: str = None,
                 quiet: bool = False, on_event: Callable = None,
                 on_confirm: Callable = None):
        self.lang = lang
        self.mode = mode
        self.debate_mode = debate_mode
        self.quiet = quiet
        self.on_event = on_event
        self.agents = load_agents(prompts, lang)
        self.bridges: dict[str, CLIBridge] = {
            name: CLIBridge(cfg, lang) for name, cfg in self.agents.items()
        }
        self.meta_agent = pick_meta_agent(self.agents, meta_agent)
        self.on_confirm = on_confirm

    def _log(self, msg: str):
        if not self.quiet:
            print(msg)

    def _confirm(self, msg: str) -> bool:
        if self.on_confirm:
            return self.on_confirm(msg)
        return True

    def _emit(self, event: str, **data):
        if self.on_event:
            self.on_event(event, data)

    @staticmethod
    def _last_round_history(state: CrucibleState, phase: str) -> str:
        """Return only the most recent round's messages to save tokens."""
        msgs = [m for m in state.messages if m.phase == phase]
        if not msgs:
            return ""
        last_round = max(m.round_num for m in msgs)
        recent = [m for m in msgs if m.round_num == last_round]
        return "\n\n".join(f"[{m.agent}]\n{m.content}" for m in recent)

    def _send(self, agent_name: str, prompt: str,
              timeout: int = BRIDGE_TIMEOUT) -> BridgeResult:
        result = self.bridges[agent_name].send(prompt, timeout)
        if not result.ok:
            self._log(f"\n[{agent_name}] error: {result.error}")
            self._emit("error", agent=agent_name, message=result.error)
        return result

    def setup(self) -> bool:
        for name, bridge in self.bridges.items():
            if not bridge.check_session():
                self._log(f"[Crucible] error: tmux session '{bridge.session}' not found")
                self._log(f"  run: tmux new-session -d -s {bridge.session}")
                self._emit("error", message=f"session not found: {bridge.session}")
                return False
        with ThreadPoolExecutor(max_workers=len(self.bridges)) as ex:
            results = list(ex.map(lambda b: b.inject_system_prompt(), self.bridges.values()))
        if not all(results):
            self._emit("error", message="system prompt injection failed — aborting")
            return False
        self._emit("ready")
        return True

    # ── analysis/verification mode ─────────────────────────────────

    def run(self, problem: str, max_rounds: int = MAX_ROUNDS,
            directory: str = None) -> CrucibleState:
        state = CrucibleState(problem=problem)
        lang = self.lang

        self._log(f"\n{'='*50}")
        self._log(f"Crucible — {max_rounds} rounds  [lang: {lang}] [mode: {self.mode}]")
        self._log(f"{'='*50}")
        self._emit("start", lang=lang, mode=self.mode, rounds=max_rounds, problem=problem)

        context = ""
        if directory and os.path.isdir(directory):
            self._log(f"\n[Phase 0] scanning directory: {directory}")
            context = _scan_context(directory)
            self._log(context)
            self._emit("phase", name="Phase 0", detail=context)

        state.round = 1
        self._log("\n[Phase 1] claude analyzing...")
        self._emit("phase", name="Phase 1 — analysis")
        self._emit("thinking", agent="claude")

        result = self._send("claude", prompts.build_analysis_prompt(state, lang, context=context))
        if not result:
            return state
        state.add("claude", "analysis", result.content)
        self._log(f"\n[Claude]\n{result.content}")
        self._emit("response", agent="claude", phase="analysis", content=result.content)

        for round_num in range(1, max_rounds + 1):
            state.round = round_num
            self._log(f"\n{'='*50}\nRound {round_num} / {max_rounds}\n{'='*50}")
            self._emit("round", number=round_num, total=max_rounds)

            self._log("\n[Gemini] verifying...")
            self._emit("thinking", agent="gemini")
            result = self._send("gemini", prompts.build_verification_prompt(
                state, lang, mode=self.mode, directory=directory))
            if not result:
                break
            state.add("gemini", "verification", result.content)
            self._log(f"\n[Gemini]\n{result.content}")
            self._emit("response", agent="gemini", phase="verification", content=result.content)

            if _detect_consensus(result.content):
                self._log("\n[Crucible] consensus detected")
                state.consensus = True
                self._emit("consensus")
                break

            if round_num < max_rounds:
                self._log("\n[Claude] rebutting...")
                self._emit("thinking", agent="claude")
                result = self._send("claude", prompts.build_rebuttal_prompt(state, lang))
                if not result:
                    break
                state.add("claude", "rebuttal", result.content)
                self._log(f"\n[Claude]\n{result.content}")
                self._emit("response", agent="claude", phase="rebuttal", content=result.content)

        if state.consensus:
            self._log("\n[Phase 3] consensus reached — adopting last gemini response as verdict")
            state.final_verdict = state.last("gemini")
            self._emit("verdict", content=state.final_verdict, from_consensus=True)
        else:
            self._log("\n[Phase 3] gemini final verdict...")
            self._emit("phase", name="Phase 3 — final verdict")
            self._emit("thinking", agent="gemini")
            result = self._send("gemini", prompts.build_final_prompt(state, lang))
            if result:
                state.add("gemini", "final_verdict", result.content)
                state.final_verdict = result.content
                self._log(f"\n[Gemini final]\n{result.content}")
                self._emit("verdict", content=result.content, from_consensus=False)

        self._save(state)
        return state

    # ── debate mode ────────────────────────────────────────────────

    def run_debate(self, problem: str, max_rounds: int = MAX_ROUNDS,
                   directory: str = None) -> CrucibleState:
        if self.debate_mode == "sequential":
            return self._run_debate_sequential(problem, max_rounds, directory)
        return self._run_debate_blind_parallel(problem, max_rounds, directory)

    def _run_debate_sequential(self, problem: str, max_rounds: int,
                                directory: str = None) -> CrucibleState:
        state = CrucibleState(problem=problem)
        lang = self.lang
        order = list(self.bridges.keys())

        self._log(f"\n{'='*50}")
        self._log(f"Crucible DEBATE [sequential] — {max_rounds} rounds  [lang: {lang}]")
        self._log(f"participants: {', '.join(order)}")
        self._log(f"{'='*50}")
        self._emit("start", lang=lang, mode="sequential", rounds=max_rounds, problem=problem)

        context = ""
        if directory and os.path.isdir(directory):
            context = _scan_context(directory)

        opening = f"[Topic]\n{problem}"
        if context:
            opening = f"[Project context]\n{context}\n\n{opening}"

        for round_num in range(1, max_rounds + 1):
            state.round = round_num
            self._log(f"\n{'='*50}\nRound {round_num} / {max_rounds}\n{'='*50}")
            self._emit("round", number=round_num, total=max_rounds)

            for agent_name in order:
                history = state.history()
                if history:
                    prompt = (
                        f"{opening}\n\n[Debate so far]\n{history}\n\n"
                        "Read the debate above and agree, rebut, or supplement. "
                        "End with [RESULT: CONSENSUS] if converged, otherwise [RESULT: DISAGREED]."
                    )
                else:
                    prompt = (
                        f"{opening}\n\nAs the first speaker, state your position. "
                        "End with [RESULT: DISAGREED]."
                    )

                self._log(f"\n[{agent_name}] speaking...")
                self._emit("thinking", agent=agent_name)
                result = self._send(agent_name, prompt)
                if not result:
                    continue
                state.add(agent_name, "debate", result.content)
                self._log(f"\n[{agent_name}]\n{result.content}")
                self._emit("response", agent=agent_name, phase="debate", content=result.content)

                round_speakers = {m.agent for m in state.messages if m.round_num == round_num}
                if round_speakers >= set(order) and _detect_consensus(result.content):
                    self._log(f"\n[Crucible] consensus reached — {agent_name} final declaration")
                    state.consensus = True
                    state.final_verdict = result.content
                    self._emit("consensus")
                    self._save(state)
                    return state

        state.final_verdict = state.last(order[-1]) or state.history()
        self._emit("verdict", content=state.final_verdict, from_consensus=False)
        self._save(state)
        return state

    def _run_debate_blind_parallel(self, problem: str, max_rounds: int,
                                    directory: str = None) -> CrucibleState:
        state = CrucibleState(problem=problem)
        lang = self.lang
        order = list(self.bridges.keys())

        self._log(f"\n{'='*50}")
        self._log(f"Crucible DEBATE [blind_parallel] — {max_rounds} rounds  [lang: {lang}]")
        self._log(f"participants: {', '.join(order)}  |  meta: {self.meta_agent}")
        self._log(f"{'='*50}")
        self._emit("start", lang=lang, mode="blind_parallel", rounds=max_rounds, problem=problem)

        context = ""
        if directory and os.path.isdir(directory):
            self._log(f"\n[Phase 0] scanning directory: {directory}")
            context = _scan_context(directory)
            self._log(context)

        opening = f"[Topic]\n{problem}"
        if context:
            opening = f"[Project context]\n{context}\n\n{opening}"

        # Phase 1: blind parallel opening positions
        self._log(f"\n{'='*50}\n[Phase 1] collecting independent positions (blind)\n{'='*50}")
        self._emit("phase", name="Phase 1 — opening positions")
        state.round = 0

        opening_prompt = (
            f"{opening}\n\n"
            "Before seeing other participants' views, write your independent position on this topic. "
            "Be specific and include your reasoning. End with [RESULT: DISAGREED]."
        )
        openings = self._send_parallel(opening_prompt, order)
        for agent_name in order:
            res = openings[agent_name]
            if not res.ok:
                self._log(f"\n[{agent_name}] Phase 1 failed — aborting debate")
                self._save(state)
                return state
            state.add(agent_name, "opening", res.content)
            self._log(f"\n[{agent_name} · opening]\n{res.content}")
            self._emit("response", agent=agent_name, phase="opening", content=res.content)

        # Phase 1.5: meta-analysis (anonymized input)
        self._log(f"\n{'='*50}\n[Phase 1.5] extracting disagreements ({self.meta_agent})\n{'='*50}")
        self._emit("phase", name="Phase 1.5 — meta analysis")
        meta = self._extract_disagreements(state, opening)
        state.add(self.meta_agent, "meta_analysis", json.dumps(meta, ensure_ascii=False, indent=2))
        self._log(f"\n[meta analysis]\n{json.dumps(meta, ensure_ascii=False, indent=2)}")
        self._emit("response", agent=self.meta_agent, phase="meta_analysis",
                   content=json.dumps(meta, ensure_ascii=False, indent=2))

        if not meta.get("has_disagreement"):
            self._log("\n[Crucible] consensus already reached in Phase 1 — done")
            state.consensus = True
            state.final_verdict = "\n\n".join(
                f"[{a}]\n{openings[a].content}" for a in order
            )
            self._emit("consensus")
            self._save(state)
            return state

        disagreement_summary = (
            "Key disagreements:\n" + "\n".join(f"- {d}" for d in meta.get("disagreements", [])) +
            ("\n\nMissing issues:\n" + "\n".join(f"- {i}" for i in meta.get("missing_issues", []))
             if meta.get("missing_issues") else "")
        )

        # Phase 1.6: meta-analysis verification — participant objections
        self._log(f"\n{'='*50}\n[Phase 1.6] meta-analysis verification\n{'='*50}")
        self._emit("phase", name="Phase 1.6 — meta verification")
        objections = []
        for agent_name in order:
            prompt = (
                f"{opening}\n\n"
                f"[Your opening position]\n{state.last(agent_name, phase='opening')}\n\n"
                f"[Meta-analysis result]\n{disagreement_summary}\n\n"
                "Does this meta-analysis accurately reflect your position? "
                "If something is missing or distorted, flag it in one sentence. "
                "If accurate, reply only with 'no objection'."
            )
            self._emit("thinking", agent=agent_name)
            result = self._send(agent_name, prompt)
            if not result:
                continue
            content = result.content.strip()
            self._log(f"\n[{agent_name} · objection] {content}")
            self._emit("response", agent=agent_name, phase="meta_objection", content=content)
            if "no objection" not in content.lower():
                objections.append(f"[{agent_name}] {content}")

        if objections:
            self._log(f"\n[Phase 1.6] {len(objections)} objection(s) — appending to disagreement summary")
            disagreement_summary += "\n\n[Participant objections]\n" + "\n".join(f"- {o}" for o in objections)

        # Phase 2: parallel debate rounds
        stopped_early = False
        for round_num in range(1, max_rounds + 1):
            state.round = round_num
            self._log(f"\n{'='*50}\n[Phase 2] debate round {round_num} / {max_rounds}\n{'='*50}")
            self._emit("round", number=round_num, total=max_rounds)

            recent_debate = self._last_round_history(state, "debate")
            prompt = (
                f"{opening}\n\n"
                f"[Key disagreements to focus on]\n{disagreement_summary}\n\n"
                f"[Previous round]\n{recent_debate or '(first debate round)'}\n\n"
                "Focus on the disagreements above and rebut or revise your position. "
                "End with [RESULT: CONSENSUS] if converged, otherwise [RESULT: DISAGREED]."
            )
            self._log(f"[prompt length: {len(prompt):,} chars]")

            for name in order:
                self._emit("thinking", agent=name)
            results = self._send_parallel(prompt, order)

            consensus_count = 0
            for agent_name in order:
                res = results[agent_name]
                if not res.ok:
                    self._log(f"\n[{agent_name}] error: {res.error}")
                    self._emit("error", agent=agent_name, message=res.error)
                    continue
                state.add(agent_name, "debate", res.content)
                self._log(f"\n[{agent_name}] [{len(res.content):,} chars]\n{res.content}")
                self._emit("response", agent=agent_name, phase="debate", content=res.content,
                           prompt_len=len(prompt), response_len=len(res.content))
                if _detect_consensus(res.content):
                    consensus_count += 1

            if consensus_count == len(order):
                self._log("\n[Crucible] unanimous consensus reached")
                state.consensus = True
                self._emit("consensus")
                break

            if not self._confirm("continue to next round?"):
                stopped_early = True
                break

        # Phase 3: sequential closing statements (when rounds exhausted)
        if not state.consensus and not stopped_early:
            self._log(f"\n{'='*50}\n[Phase 3] closing statements (sequential)\n{'='*50}")
            self._emit("phase", name="Phase 3 — closing statements")
            state.round = max_rounds + 1
            for agent_name in order:
                full_debate = state.history(phase="debate")
                prompt = (
                    f"{opening}\n\n"
                    f"[Disagreement summary]\n{disagreement_summary}\n\n"
                    f"[Full debate]\n{full_debate}\n\n"
                    "Based on the debate, state your final position. "
                    "Clearly distinguish what changed and what you still maintain."
                )
                self._log(f"\n[{agent_name}] writing closing statement...")
                self._emit("thinking", agent=agent_name)
                result = self._send(agent_name, prompt)
                if not result:
                    continue
                state.add(agent_name, "closing", result.content)
                self._log(f"\n[{agent_name}]\n{result.content}")
                self._emit("response", agent=agent_name, phase="closing", content=result.content)

        # Final verdict (meta_agent)
        verdict_agent = self.meta_agent
        self._log(f"\n{'='*50}\n[Final] {verdict_agent} verdict\n{'='*50}")
        self._emit("phase", name=f"Final — {verdict_agent} verdict")
        self._emit("thinking", agent=verdict_agent)
        closing_src = "closing" if state.history(phase="closing") else "debate"
        final_prompt = (
            f"{opening}\n\n"
            f"[Disagreement summary]\n{disagreement_summary}\n\n"
            f"[Final positions]\n{state.history(phase=closing_src)}\n\n"
            "Synthesize all positions into a final verdict. "
            "Include: points of consensus, remaining disputes, and recommendations."
        )
        result = self._send(verdict_agent, final_prompt)
        if result:
            state.add(verdict_agent, "final_verdict", result.content)
            state.final_verdict = result.content
            self._log(f"\n[{verdict_agent} final]\n{result.content}")
            self._emit("verdict", content=result.content, from_consensus=state.consensus)

        self._save(state)
        return state

    # ── helpers ────────────────────────────────────────────────────

    def _send_parallel(self, prompt: str,
                       agents: list[str]) -> dict[str, BridgeResult]:
        def _send(name: str) -> tuple[str, BridgeResult]:
            return name, self.bridges[name].send(prompt, BRIDGE_TIMEOUT)

        for name in agents:
            self._emit("thinking", agent=name)

        results = {}
        with ThreadPoolExecutor(max_workers=len(agents)) as executor:
            futures = {executor.submit(_send, name): name for name in agents}
            for future in as_completed(futures):
                name, result = future.result()
                results[name] = result
        return results

    @staticmethod
    def _anonymize_openings(state: CrucibleState) -> str:
        """Anonymize agent names to Position A/B/C to reduce authority bias."""
        msgs = [m for m in state.messages if m.phase == "opening"]
        labels = {m.agent: f"Position {chr(65+i)}" for i, m in enumerate(msgs)}
        parts = [f"[{labels[m.agent]}]\n{m.content}" for m in msgs]
        return "\n\n".join(parts)

    def _extract_disagreements(self, state: CrucibleState, opening: str) -> dict:
        anon = self._anonymize_openings(state)
        meta_prompt = (
            f"{opening}\n\n"
            f"[Independent positions]\n{anon}\n\n"
            "Analyze the positions above and output only the following JSON. No explanations.\n"
            "{\n"
            '  "common_points": ["shared agreements"],\n'
            '  "disagreements": ["key points of disagreement"],\n'
            '  "missing_issues": ["important issues not raised"],\n'
            '  "has_disagreement": true\n'
            "}\n"
            "If there are no disagreements, set disagreements to [] and has_disagreement to false."
        )
        result = self._send(self.meta_agent, meta_prompt)
        if not result.ok:
            return {"common_points": [], "disagreements": [], "missing_issues": [],
                    "has_disagreement": False, "error": result.error}
        try:
            return json.loads(_strip_code_fence(result.content))
        except Exception:
            return {
                "common_points": [],
                "disagreements": [result.content],
                "missing_issues": [],
                "has_disagreement": True,
                "raw": result.content,
            }

    def _save(self, state: CrucibleState):
        os.makedirs(LOGS_DIR, exist_ok=True)
        os.makedirs(RESULTS_DIR, exist_ok=True)
        ts = state.started_at

        log_path = os.path.join(LOGS_DIR, f"crucible_{ts}.md")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Crucible — {ts}  [lang: {self.lang}] [mode: {self.mode}]\n\n")
            f.write(f"## Topic\n\n{state.problem}\n\n")
            for m in state.messages:
                f.write(f"## [{m.agent}] Round {m.round_num} · {m.phase}\n\n{m.content}\n\n")

            agents_in_opening = {m.agent for m in state.messages if m.phase == "opening"}
            if agents_in_opening:
                f.write("## Position Changes\n\n")
                for agent in agents_in_opening:
                    initial = state.last(agent, phase="opening")
                    final = state.last(agent, phase="debate")
                    changed = bool(final) and initial != final
                    f.write(f"### {agent}: {'changed' if changed else 'maintained'}\n\n")
                    if changed:
                        f.write(f"**Initial**\n{initial[:300]}...\n\n")
                        f.write(f"**Final**\n{final[:300]}...\n\n")

        result_path = os.path.join(RESULTS_DIR, f"result_{ts}.md")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(state.final_verdict)

        self._log(f"\n[Crucible] log → {log_path}")
        self._log(f"\n[Crucible] result → {result_path}")
        self._emit("saved", log=log_path, result=result_path)


def _read_problem() -> str:
    print("\nEnter your topic (Ctrl+D to submit):\n")
    lines = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        pass
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crucible")
    parser.add_argument("--rounds", type=int, default=MAX_ROUNDS)
    parser.add_argument("--lang", choices=["ko", "en", "mixed"], default="en")
    parser.add_argument("--mode", choices=["summary", "full"], default="summary")
    parser.add_argument("--debate", action="store_true", help="debate mode")
    parser.add_argument("--debate-mode", choices=["sequential", "blind_parallel"],
                        default="blind_parallel", dest="debate_mode",
                        help="debate style (default: blind_parallel / sequential: legacy)")
    parser.add_argument("--meta-agent", type=str, default=None, dest="meta_agent",
                        help="agent for meta-analysis and final verdict (default: role=meta or first agent)")
    parser.add_argument("--dir", type=str, default=None)
    parser.add_argument("--problem", type=str, default=None)
    args = parser.parse_args()

    crucible = Crucible(lang=args.lang, mode=args.mode,
                        debate_mode=args.debate_mode, meta_agent=args.meta_agent)
    if not crucible.setup():
        exit(1)

    run_fn = crucible.run_debate if args.debate else crucible.run

    if args.problem:
        run_fn(args.problem, args.rounds, directory=args.dir)
        exit(0)

    while True:
        problem = _read_problem()
        if not problem.strip():
            print("[Crucible] no input, exiting")
            break
        run_fn(problem, args.rounds, directory=args.dir)
        print("\n" + "="*50)
        try:
            cont = input("next topic? [Enter to continue / q to quit]: ").strip().lower()
        except EOFError:
            break
        if cont == "q":
            break
