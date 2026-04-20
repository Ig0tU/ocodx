"""
TeamAgent — Sovereign Liquid Matrix multi-agent swarm.

Decomposes a task into parallel specialist subtasks, spawns one CodingAgent
per specialist in a ThreadPoolExecutor, then optionally runs a synthesis step
where agents collaborate on each other's results.

SSE event shape: all standard CodingAgent events + "agent_id" field added.
Extra events emitted by TeamAgent:
  {"type": "team_plan",    "tasks": [...]}
  {"type": "team_start",   "agent_id": "ARC", "role": "...", "subtask": "..."}
  {"type": "team_done",    "agent_id": "ARC", "summary": "..."}
  {"type": "team_collab",  "synthesizer": "ARC", "task": "...", "inputs": [...]}
  {"type": "team_finish",  "summary": "..."}
"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Generator

from open_codex.agents.coding_agent import CodingAgent


# ── SLM Specialist Cluster Definitions ───────────────────────────────────────

SPECIALISTS = {
    "ARC": {
        "role": "Architecture & API Design",
        "focus": (
            "Structure, modularity, design patterns, state management, "
            "data flow, API contracts, component boundaries."
        ),
    },
    "LNG": {
        "role": "Language & Core Logic",
        "focus": (
            "Algorithms, game mechanics, physics, data structures, "
            "language-idiomatic patterns, performance of hot paths."
        ),
    },
    "QSP": {
        "role": "Quality, Visuals & Polish",
        "focus": (
            "Bug fixing, visual effects, CSS animations, UI feedback, "
            "error handling, edge cases, test coverage."
        ),
    },
    "OPS": {
        "role": "Build, Deploy & Tooling",
        "focus": (
            "Build scripts, CI config, environment setup, dependency management, "
            "caching, bundling, observability."
        ),
    },
    "AID": {
        "role": "AI & Intelligence Features",
        "focus": (
            "AI-powered features, procedural generation, adaptive difficulty, "
            "ML integration, data pipelines inside the project."
        ),
    },
}

# ── Decomposer prompt ─────────────────────────────────────────────────────────

DECOMPOSE_SYSTEM = """You are a task decomposer for a multi-agent coding swarm.
Given a user's request and the directory contents of a project, output a JSON
plan assigning subtasks to specialist agents from this roster:

  ARC — Architecture & API Design
  LNG — Language & Core Logic
  QSP — Quality, Visuals & Polish
  OPS — Build, Deploy & Tooling
  AID — AI & Intelligence Features

Rules:
- Only include agents whose speciality is clearly relevant to the task.
- Each agent MUST receive a unique, actionable subtask — not a copy of the original.
- files_hint: list of filenames that agent should focus on (can be empty []).
- collaborate: optional list of synthesis steps AFTER parallel work completes.
  Each step specifies which agent IDs have finished ("after") and which agent
  ("synthesizer") runs a final collaboration task given their combined summaries.
- Keep the JSON minimal and valid. No prose outside the JSON block.

Output format (strict JSON, no markdown fences):
{
  "tasks": [
    {"id": "ARC", "subtask": "...", "files_hint": ["file.js"]},
    {"id": "LNG", "subtask": "...", "files_hint": ["game.js", "physics.js"]}
  ],
  "collaborate": [
    {
      "after": ["ARC", "LNG"],
      "synthesizer": "ARC",
      "task": "Review all changes, ensure architectural consistency, fix any conflicts."
    }
  ]
}
"""


def _decompose(
    llm_caller: Callable[[list], str],
    prompt: str,
    dir_listing: str,
) -> dict:
    """Ask the LLM to decompose the task. Returns parsed plan dict."""
    messages = [
        {"role": "system", "content": DECOMPOSE_SYSTEM},
        {
            "role": "user",
            "content": (
                f"USER REQUEST: {prompt}\n\n"
                f"PROJECT FILES:\n{dir_listing}"
            ),
        },
    ]
    raw = llm_caller(messages)
    # Strip any accidental markdown fences
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: single LNG agent handles everything
        return {
            "tasks": [{"id": "LNG", "subtask": prompt, "files_hint": []}],
            "collaborate": [],
        }


def _build_agent_prompt(specialist: dict, subtask: str, files_hint: list[str]) -> str:
    hint = ""
    if files_hint:
        hint = f"\nFocus primarily on these files: {', '.join(files_hint)}"
    return (
        f"You are the {specialist['role']} specialist.\n"
        f"Your focus: {specialist['focus']}\n"
        f"Your assigned subtask: {subtask}{hint}\n\n"
        "Execute this subtask completely and autonomously. "
        "Do not do work outside your subtask — other agents handle the rest."
    )


def _build_collab_prompt(
    task: str,
    summaries: dict[str, str],  # agent_id -> summary
) -> str:
    parts = "\n\n".join(
        f"=== {aid} completed ===\n{summary}" for aid, summary in summaries.items()
    )
    return (
        f"You are the synthesis agent. The following parallel agents have finished:\n\n"
        f"{parts}\n\n"
        f"Your collaboration task: {task}\n"
        "Review the work done, resolve any conflicts, ensure consistency, "
        "and apply any final improvements."
    )


# ── TeamAgent ─────────────────────────────────────────────────────────────────

class TeamAgent:
    """
    Orchestrates a swarm of CodingAgent instances running in parallel.
    Yields SSE-style event dicts (same shape as CodingAgent + agent_id).
    """

    def __init__(self, llm_caller: Callable[[list], str], max_workers: int = 4):
        self.llm_caller = llm_caller
        self.max_workers = max_workers

    def run(
        self,
        prompt: str,
        project_dir: str,
        max_steps: int = 30,
    ) -> Generator[dict, None, None]:
        from open_codex.tools import file_tools
        import os

        project_dir = os.path.realpath(os.path.abspath(project_dir))

        # 1. Get directory listing for decomposition
        dir_listing = file_tools.list_directory(".", project_dir)

        yield {"type": "team_decomposing", "msg": "Decomposing task across specialist agents..."}

        # 2. Decompose task into parallel subtasks
        try:
            plan = _decompose(self.llm_caller, prompt, dir_listing)
        except Exception as e:
            yield {"type": "error", "content": f"Decomposition failed: {e}"}
            return

        tasks = plan.get("tasks", [])
        collabs = plan.get("collaborate", [])

        if not tasks:
            yield {"type": "error", "content": "Decomposer returned no tasks."}
            return

        yield {"type": "team_plan", "tasks": tasks, "collaborate": collabs}

        # 3. Run agents in parallel threads
        # Each agent gets tagged events via a thread-safe queue
        summaries: dict[str, str] = {}
        event_lock = threading.Lock()
        all_events: list[dict] = []

        def run_agent(task: dict) -> list[dict]:
            agent_id = task["id"]
            subtask = task["subtask"]
            files_hint = task.get("files_hint", [])
            spec = SPECIALISTS.get(agent_id, {"role": agent_id, "focus": ""})

            agent_prompt = _build_agent_prompt(spec, subtask, files_hint)
            agent = CodingAgent(self.llm_caller)
            events = []

            for ev in agent.run(agent_prompt, project_dir, max_steps=max_steps):
                tagged = {**ev, "agent_id": agent_id}
                events.append(tagged)

                # Capture summary
                if ev.get("type") == "message":
                    summaries[agent_id] = ev.get("content", "")

            return events

        # Submit all tasks
        futures = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for task in tasks:
                agent_id = task["id"]
                spec = SPECIALISTS.get(agent_id, {"role": agent_id, "focus": ""})
                yield {
                    "type": "team_start",
                    "agent_id": agent_id,
                    "role": spec["role"],
                    "subtask": task["subtask"],
                    "files_hint": task.get("files_hint", []),
                }
                futures[pool.submit(run_agent, task)] = agent_id

            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    events = future.result()
                    for ev in events:
                        yield ev
                    yield {"type": "team_done", "agent_id": agent_id,
                           "summary": summaries.get(agent_id, "")}
                except Exception as e:
                    yield {"type": "error", "agent_id": agent_id,
                           "content": f"Agent {agent_id} failed: {e} — continuing with other agents."}

        # 4. Collaboration / synthesis steps
        for collab in collabs:
            after_ids = collab.get("after", [])
            synthesizer_id = collab.get("synthesizer", "ARC")
            collab_task = collab.get("task", "Review and integrate all changes.")

            # Only include summaries from agents that were actually in this collab step
            relevant_summaries = {
                aid: summaries[aid] for aid in after_ids if aid in summaries
            }

            yield {
                "type": "team_collab",
                "synthesizer": synthesizer_id,
                "task": collab_task,
                "inputs": list(relevant_summaries.keys()),
            }

            collab_prompt = _build_collab_prompt(collab_task, relevant_summaries)
            synth_agent = CodingAgent(self.llm_caller)
            for ev in synth_agent.run(collab_prompt, project_dir, max_steps=max_steps):
                yield {**ev, "agent_id": synthesizer_id + "_SYNTH"}

        # 5. Final summary
        combined = "; ".join(
            f"{aid}: {s[:120]}" for aid, s in summaries.items() if s
        )
        yield {"type": "team_finish", "summary": combined or "Team complete."}
        yield {"type": "done", "stats": {"files_changed": [], "team_mode": True}}
