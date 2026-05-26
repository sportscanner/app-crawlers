"""
SportScanner Agent Eval Demo
============================

Run with:   python -m sportscanner.agents.evals.demo

Demonstrates three scenarios for the LLM agents & evals talk:

  CASE 1 — HAPPY PATH
    Well-formed query: full postcode, specific sport, clear time window.
    Shows a clean trajectory and high judge scores.

  CASE 2 — FAILURE CASE
    Ambiguous query that the agent cannot answer well.
    Shows sparse/missing tool calls and low judge scores.

  CASE 3 — GUARDRAIL FIRES
    Query with a bare outcode (EC2M) instead of a full postcode.
    The guardrail detects the invalid postcode, resolves it, and the
    tool call succeeds.  `_guardrail_fired` shows in the trajectory.

Together the three cases tell the narrative arc:
  observation → problem identified → guardrail prevents it → eval confirms the fix.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sportscanner.agents.evals.judge import judge_agent_response
from sportscanner.agents.evals.trajectory import AgentTrajectory, trajectory_to_readable_text
from sportscanner.agents.sportscanner_chat_agent import AgentTurn, sportscanner_chat_agent

console = Console(highlight=False)

# ---------------------------------------------------------------------------
# Demo query set
# ---------------------------------------------------------------------------

CASES: list[dict[str, Any]] = [
    {
        "label": "CASE 1 — HAPPY PATH",
        "description": (
            "Full postcode, clear sport, specific time window.\n"
            "The agent should resolve the location, search availability,\n"
            "and return a clean venue table."
        ),
        "query": "Find badminton courts within 3 miles of EC2M 6SD this Saturday after 5pm",
        "expect": "high scores across all dimensions",
    },
    {
        "label": "CASE 2 — FAILURE CASE",
        "description": (
            "No location, no sport, no date — pure ambiguity.\n"
            "The agent should ask a clarifying question rather than invent results.\n"
            "Watch how many tools get called (should be zero)."
        ),
        "query": "Find courts for this evening",
        "expect": "low completeness; gap_handling should be high if agent admits uncertainty",
    },
    {
        "label": "CASE 3 — GUARDRAIL FIRES",
        "description": (
            "EC2M is an outcode, not a full postcode.  Without a guardrail the\n"
            "agent passes it to the search API and gets a 400 error.\n"
            "The guardrail resolves EC2M → full postcode before the tool is called.\n"
            "Look for _guardrail_fired: true in the trajectory."
        ),
        "query": "Find badminton courts near EC2M this Saturday after 5pm",
        "expect": "guardrail fires; scores similar to happy path",
    },
]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _bar(score: float, max_score: float = 5.0, width: int = 20) -> str:
    filled = round((score / max_score) * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    colour = "green" if score >= 4 else ("yellow" if score >= 2.5 else "red")
    return f"[{colour}]{bar}[/{colour}] {score:.1f}/{max_score:.0f}"


def _render_judge_table(judge: dict[str, Any]) -> Table:
    t = Table(box=None, show_header=False, padding=(0, 1))
    t.add_column("Dimension", style="bold")
    t.add_column("Score", min_width=28)

    dims = [
        ("Response correctness", "response_correctness"),
        ("Tool efficiency", "tool_efficiency"),
        ("Gap handling", "gap_handling"),
        ("Completeness", "completeness"),
    ]
    for label, key in dims:
        t.add_row(label, _bar(float(judge.get(key, 0))))

    t.add_section()
    t.add_row("[bold]OVERALL[/bold]", _bar(float(judge.get("overall", 0))))
    return t


def _render_trajectory(trajectory: AgentTrajectory) -> str:
    if not trajectory.tool_calls:
        return "[dim](no tools called)[/dim]"

    lines: list[str] = []
    for i, call in enumerate(trajectory.tool_calls, 1):
        guardrail_tag = " [bold red][GUARDRAIL FIRED][/bold red]" if call.guardrail_fired else ""
        error_tag = f" [red]→ ERROR: {call.error}[/red]" if call.error else ""
        lines.append(
            f"[cyan]{i}.[/cyan] [bold]{call.tool}[/bold]{guardrail_tag}{error_tag}"
        )

        if call.guardrail_fired and call.guardrail_original_input:
            orig = json.dumps(call.guardrail_original_input, default=str)
            patched = json.dumps(call.input, default=str)
            lines.append(f"   [dim]original:[/dim] {orig[:120]}")
            lines.append(f"   [yellow]patched: [/yellow] {patched[:120]}")
        else:
            inp = json.dumps(call.input, default=str)
            lines.append(f"   [dim]input:[/dim]   {inp[:160]}")

        lines.append(f"   [dim]time:[/dim]    {call.duration_ms:.0f} ms")

    lines.append(f"\n[dim]Total agent time: {trajectory.total_duration_ms:.0f} ms[/dim]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

async def run_case(case: dict[str, Any]) -> None:
    console.print()
    console.print(Rule(f"[bold]{case['label']}[/bold]", style="blue"))
    console.print(Panel(case["description"], border_style="dim", expand=False))
    console.print(f"[bold]Query:[/bold] {case['query']}")
    console.print(f"[dim]Expected: {case['expect']}[/dim]")
    console.print()

    console.print("[yellow]Running agent...[/yellow]")
    try:
        result = await sportscanner_chat_agent.chat(
            turns=[AgentTurn(role="user", content=case["query"])]
        )
    except Exception as exc:
        console.print(f"[red bold]Agent error:[/red bold] {exc}")
        return

    trajectory = result.trajectory
    if trajectory is None:
        from sportscanner.agents.evals.trajectory import AgentTrajectory as _AT
        trajectory = _AT(query=case["query"], final_reply=result.reply)

    console.print("[yellow]Running LLM judge...[/yellow]")
    judge = await judge_agent_response(
        query=case["query"],
        trajectory=trajectory,
        final_response=result.reply,
    )

    # --- Trajectory panel ---
    traj_text = _render_trajectory(trajectory)
    console.print(
        Panel(
            traj_text,
            title="[bold]Tool trajectory[/bold]",
            border_style="cyan",
            expand=True,
        )
    )

    # --- Agent response panel ---
    reply_preview = result.reply[:800] + ("…" if len(result.reply) > 800 else "")
    console.print(
        Panel(
            reply_preview,
            title="[bold]Agent response[/bold]",
            border_style="green",
            expand=True,
        )
    )

    # --- Judge scores ---
    console.print(
        Panel(
            _render_judge_table(judge),
            title="[bold]LLM-as-judge scores[/bold]",
            border_style="magenta",
            expand=False,
        )
    )
    reason = judge.get("reason", "")
    if reason:
        console.print(f"[dim]Reason: {reason}[/dim]")

    if judge.get("error"):
        console.print(f"[red]Judge error:[/red] {judge['error']}")


# ---------------------------------------------------------------------------
# Side-by-side comparison helper  (called after all cases)
# ---------------------------------------------------------------------------

_SCORE_KEYS = ["response_correctness", "tool_efficiency", "gap_handling", "completeness", "overall"]


async def run_comparison(cases: list[dict[str, Any]], scores: list[dict[str, Any]]) -> None:
    console.print()
    console.print(Rule("[bold]SIDE-BY-SIDE COMPARISON[/bold]", style="bold blue"))

    t = Table(show_header=True, header_style="bold")
    t.add_column("Dimension", style="bold", min_width=22)
    for case in cases:
        t.add_column(case["label"].split("—")[1].strip(), min_width=14, justify="center")

    dim_labels = {
        "response_correctness": "Response correctness",
        "tool_efficiency": "Tool efficiency",
        "gap_handling": "Gap handling",
        "completeness": "Completeness",
        "overall": "OVERALL",
    }
    for key in _SCORE_KEYS:
        row_cells = [dim_labels[key]]
        for score_dict in scores:
            val = float(score_dict.get(key, 0))
            colour = "green" if val >= 4 else ("yellow" if val >= 2.5 else "red")
            row_cells.append(f"[{colour}]{val:.1f}[/{colour}]")
        if key == "overall":
            t.add_section()
        t.add_row(*row_cells)

    console.print(t)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SportScanner Agent Evals Demo")
    parser.add_argument(
        "-q", "--query",
        metavar="QUERY",
        help="Evaluate a single ad-hoc query instead of running the full demo suite.",
    )
    args = parser.parse_args()

    if args.query:
        await run_case({
            "label": "AD-HOC QUERY",
            "description": "Single query passed via --query / -q flag.",
            "query": args.query,
            "expect": "n/a",
        })
        return

    console.print()
    console.print(
        Panel(
            "[bold]SportScanner Agent · LLM Evals Demo[/bold]\n\n"
            "Demonstrates: tool trajectory logging · LLM-as-judge · input guardrails\n"
            "Three cases: happy path → deliberate failure → guardrail saves the day",
            border_style="bold green",
            expand=False,
        )
    )

    all_scores: list[dict[str, Any]] = []
    for case in CASES:
        try:
            result = await sportscanner_chat_agent.chat(
                turns=[AgentTurn(role="user", content=case["query"])]
            )
        except Exception as exc:
            console.print(f"\n[red]Agent error for '{case['label']}':[/red] {exc}")
            all_scores.append({})
            continue

        trajectory = result.trajectory
        if trajectory is None:
            from sportscanner.agents.evals.trajectory import AgentTrajectory as _AT
            trajectory = _AT(query=case["query"], final_reply=result.reply)

        judge = await judge_agent_response(
            query=case["query"],
            trajectory=trajectory,
            final_response=result.reply,
        )
        all_scores.append(judge)

        console.print()
        console.print(Rule(f"[bold]{case['label']}[/bold]", style="blue"))
        console.print(Panel(case["description"], border_style="dim", expand=False))
        console.print(f"[bold]Query:[/bold] {case['query']}")
        console.print()

        traj_text = _render_trajectory(trajectory)
        console.print(
            Panel(traj_text, title="[bold]Tool trajectory[/bold]", border_style="cyan")
        )

        reply_preview = result.reply[:600] + ("…" if len(result.reply) > 600 else "")
        console.print(
            Panel(reply_preview, title="[bold]Agent response[/bold]", border_style="green")
        )

        console.print(
            Panel(
                _render_judge_table(judge),
                title="[bold]LLM-as-judge scores[/bold]",
                border_style="magenta",
                expand=False,
            )
        )
        reason = judge.get("reason", "")
        if reason:
            console.print(f"[dim]  Reason: {reason}[/dim]")

    await run_comparison(CASES, all_scores)

    console.print()
    console.print(
        Panel(
            "[bold]Key takeaways for the talk[/bold]\n\n"
            "1. [cyan]Trajectory logging[/cyan]  — without it you have no idea what the agent actually did.\n"
            "2. [magenta]LLM-as-judge[/magenta]      — human eval doesn't scale; judge gives consistent, repeatable scores.\n"
            "3. [yellow]Guardrails[/yellow]        — catch bad inputs at the tool boundary, not after the fact.\n"
            "4. [green]CI gate[/green]           — run POST /chat/eval in your test suite; fail if overall < 3.5.",
            border_style="bold green",
            expand=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
