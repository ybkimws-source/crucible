import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner

from orchestrator import Crucible
from core.config import MAX_ROUNDS

console = Console()

LOGO = """\
 ██████ ██████  ██   ██  ██████ ██████  ██████  ██████
██      ██   ██ ██   ██ ██      ██   ██ ██   ██ ██
██      ██████  ██   ██ ██      ██████  ██████  █████
██      ██   ██ ██   ██ ██      ██   ██ ██   ██ ██
 ██████ ██   ██  █████   ██████ ██████  ██████  ██████"""

COLORS = {
    "claude": "bright_cyan",
    "gemini": "bright_yellow",
    "codex":  "bright_magenta",
}
PHASE_LABELS = {
    "analysis":      "analysis",
    "verification":  "verification",
    "rebuttal":      "rebuttal",
    "final_verdict": "final verdict",
    "opening":       "opening position",
    "meta_analysis": "meta analysis",
    "debate":        "debate",
    "closing":       "closing statement",
    "meta_objection": "objection",
}


class _Handler:
    def __init__(self):
        self._live: Live = None

    def _stop(self):
        if self._live:
            self._live.stop()
            self._live = None

    def _spinner(self, agent: str):
        self._stop()
        color = COLORS.get(agent, "white")
        label = Text()
        label.append(f" {agent.upper()} ", style=f"bold {color}")
        label.append("thinking...", style="dim italic")
        self._live = Live(
            Spinner("dots", text=label),
            console=console,
            refresh_per_second=15,
            transient=True,
        )
        self._live.start()

    def __call__(self, event: str, data: dict):
        if event == "thinking":
            self._spinner(data["agent"])

        elif event == "response":
            self._stop()
            agent = data["agent"]
            color = COLORS.get(agent, "white")
            label = PHASE_LABELS.get(data["phase"], data["phase"])
            console.print(Panel(
                data["content"],
                title=f"[bold {color}]{agent.upper()}[/bold {color}]  [dim]{label}[/dim]",
                border_style=color,
            ))

        elif event == "start":
            self._stop()
            preview = data["problem"][:80] + ("…" if len(data["problem"]) > 80 else "")
            console.print(Rule(style="dim"))
            console.print(f"[dim]▶ {preview}[/dim]\n")

        elif event == "round":
            self._stop()
            console.print(Rule(
                f"[dim]Round {data['number']} / {data['total']}[/dim]",
                style="dim"
            ))

        elif event == "phase":
            self._stop()
            console.print(f"[dim]◆ {data['name']}[/dim]")

        elif event == "consensus":
            self._stop()
            console.print(Rule("[green]✅ consensus reached[/green]", style="green"))

        elif event == "verdict":
            self._stop()
            tag = "consensus verdict" if data["from_consensus"] else "final verdict"
            console.print(Panel(
                data["content"],
                title=f"[bold green]⬡ {tag}[/bold green]",
                border_style="green",
                padding=(1, 2),
            ))

        elif event == "error":
            self._stop()
            console.print(f"[red]❌ {data['message']}[/red]")

        elif event == "saved":
            console.print(f"[dim]↓ {data['result']}[/dim]")


def main():
    parser = argparse.ArgumentParser(description="Crucible")
    parser.add_argument("--lang",        choices=["ko", "en", "mixed"],             default="en")
    parser.add_argument("--mode",        choices=["summary", "full"],               default="summary")
    parser.add_argument("--rounds",      type=int,                                  default=MAX_ROUNDS)
    parser.add_argument("--dir",         type=str,                                  default=None)
    parser.add_argument("--debate",      action="store_true",                       help="debate mode")
    parser.add_argument("--debate-mode", choices=["sequential", "blind_parallel"],  default="blind_parallel",
                        dest="debate_mode", help="debate style (default: blind_parallel / sequential: legacy)")
    parser.add_argument("--meta-agent",  type=str,                                  default=None, dest="meta_agent")
    args = parser.parse_args()

    console.print(f"[bold cyan]{LOGO}[/bold cyan]")
    console.print("[dim]multi-agent debate system[/dim]\n", justify="center")
    mode_label = f"debate/{args.debate_mode}" if args.debate else args.mode
    console.print(
        f"[dim]lang:[/dim] [bold]{args.lang}[/bold]  "
        f"[dim]mode:[/dim] [bold]{mode_label}[/bold]  "
        f"[dim]rounds:[/dim] [bold]{args.rounds}[/bold]\n"
    )

    def _confirm(msg: str) -> bool:
        console.print(f"\n[bold]{msg}[/bold] [dim]\\[y/n][/dim] ", end="")
        try:
            ans = input().strip().lower()
            console.print()
            return ans != "n"
        except (EOFError, KeyboardInterrupt):
            console.print()
            return False

    handler = _Handler()
    arena = Crucible(lang=args.lang, mode=args.mode,
                     debate_mode=args.debate_mode, meta_agent=args.meta_agent,
                     quiet=True, on_event=handler, on_confirm=_confirm)

    with Live(Spinner("dots", text=" checking sessions..."), console=console,
              refresh_per_second=10, transient=True):
        ok = arena.setup()

    if not ok:
        console.print("[red]❌ setup failed — run ./scripts/bringup.sh first[/red]")
        return

    console.print("[green]✓ ready[/green]\n")

    while True:
        console.print("[bold]enter your topic[/bold] [dim](Enter: newline  Ctrl+D: submit)[/dim]")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        except KeyboardInterrupt:
            break

        problem = "\n".join(lines).strip()
        if not problem:
            console.print("[dim]no input, exiting[/dim]")
            break

        console.print()
        run_fn = arena.run_debate if args.debate else arena.run
        run_fn(problem, args.rounds, directory=args.dir)
        console.print()

        try:
            cont = input("next topic? [Enter to continue / q to quit]: ").strip().lower()
            if cont == "q":
                break
        except (EOFError, KeyboardInterrupt):
            break

    console.print("\n[dim]crucible done[/dim]")


if __name__ == "__main__":
    main()
