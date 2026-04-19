"""
Tests for CodingAgent (open_codex/agents/coding_agent.py)

Uses a fake llm_caller so no real LLM is invoked.
"""
import os
import json
import pytest
from open_codex.agents.coding_agent import CodingAgent, ACTION_RE, DONE_RE


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_caller(*responses):
    """Return a llm_caller that cycles through the given strings."""
    responses = list(responses)
    idx = [0]
    def caller(messages):
        r = responses[idx[0]]
        if idx[0] < len(responses) - 1:
            idx[0] += 1
        if isinstance(r, Exception):
            raise r
        return r
    return caller


def collect(agent, prompt, project_dir, **kwargs):
    return list(agent.run(prompt, project_dir, **kwargs))


# ── Regex sanity ──────────────────────────────────────────────────────────────

class TestRegexPatterns:
    def test_action_re_matches_json(self):
        line = 'ACTION: {"tool": "read_file", "args": {"path": "a.py"}}'
        m = ACTION_RE.search(line)
        assert m is not None

    def test_done_re_matches_summary(self):
        line = "DONE: Updated main.py with new logic"
        m = DONE_RE.search(line)
        assert m is not None
        assert "Updated" in m.group(1)

    def test_action_re_does_not_match_plain_text(self):
        assert ACTION_RE.search("Just some output") is None

    def test_done_re_does_not_match_action(self):
        assert DONE_RE.search('ACTION: {"tool":"x","args":{}}') is None


# ── Event types ───────────────────────────────────────────────────────────────

class TestCodingAgentEvents:
    def test_always_emits_start(self, tmp_project):
        caller = make_caller("DONE: finished")
        agent = CodingAgent(caller)
        events = collect(agent, "hello", tmp_project)
        types = [e["type"] for e in events]
        assert "start" in types

    def test_emits_done_on_done_response(self, tmp_project):
        caller = make_caller("DONE: all good")
        agent = CodingAgent(caller)
        events = collect(agent, "do something", tmp_project)
        types = [e["type"] for e in events]
        assert "done" in types

    def test_emits_message_content(self, tmp_project):
        caller = make_caller("DONE: wrote the file")
        agent = CodingAgent(caller)
        events = collect(agent, "q", tmp_project)
        msg = next(e for e in events if e["type"] == "message")
        assert "wrote" in msg["content"]

    def test_emits_error_on_llm_exception(self, tmp_project):
        caller = make_caller(ConnectionError("LLM error: something failed"))
        agent = CodingAgent(caller)
        events = collect(agent, "q", tmp_project)
        types = [e["type"] for e in events]
        assert "error" in types

    def test_unstructured_response_treated_as_message(self, tmp_project):
        caller = make_caller("Here is my answer without any tool calls.")
        agent = CodingAgent(caller)
        events = collect(agent, "q", tmp_project)
        types = [e["type"] for e in events]
        assert "message" in types
        assert "done" in types


# ── Tool dispatch via LLM ─────────────────────────────────────────────────────

class TestCodingAgentToolLoop:
    def test_list_directory_tool_called(self, tmp_project):
        action = json.dumps({
            "tool": "list_directory",
            "args": {"path": "."}
        })
        caller = make_caller(f"ACTION: {action}", "DONE: listed")
        agent = CodingAgent(caller)
        events = collect(agent, "list the files", tmp_project)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert any(tc["tool"] == "list_directory" for tc in tool_calls)

    def test_read_file_tool_called(self, tmp_project):
        action = json.dumps({"tool": "read_file", "args": {"path": "main.py"}})
        caller = make_caller(f"ACTION: {action}", "DONE: read it")
        agent = CodingAgent(caller)
        events = collect(agent, "read main.py", tmp_project)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert any(tc["tool"] == "read_file" for tc in tool_calls)

    def test_write_file_emits_file_changed(self, tmp_project):
        action = json.dumps({
            "tool": "write_file",
            "args": {"path": "out.py", "content": "x = 1\n"}
        })
        caller = make_caller(f"ACTION: {action}", "DONE: wrote")
        agent = CodingAgent(caller)
        events = collect(agent, "write a file", tmp_project)
        changed = [e for e in events if e["type"] == "file_changed"]
        assert any(fc["path"] == "out.py" for fc in changed)
        assert os.path.exists(os.path.join(tmp_project, "out.py"))

    def test_unknown_tool_returns_error_result(self, tmp_project):
        action = json.dumps({"tool": "nuke_everything", "args": {}})
        caller = make_caller(f"ACTION: {action}", "DONE: ok")
        agent = CodingAgent(caller)
        events = collect(agent, "q", tmp_project)
        results = [e for e in events if e["type"] == "tool_result"]
        assert any("Unknown tool" in r["result"] for r in results)

    def test_malformed_action_json_yields_error(self, tmp_project):
        caller = make_caller('ACTION: {bad json!!!}')
        agent = CodingAgent(caller)
        events = collect(agent, "q", tmp_project)
        types = [e["type"] for e in events]
        assert "error" in types

    def test_max_steps_terminates(self, tmp_project):
        """Agent should stop after MAX_STEPS even if LLM never says DONE."""
        always_action = json.dumps({"tool": "list_directory", "args": {"path": "."}})
        def infinite_caller(messages):
            return f"ACTION: {always_action}"
        agent = CodingAgent(infinite_caller)
        events = collect(agent, "loop forever", tmp_project)
        error_events = [e for e in events if e["type"] == "error"]
        assert any("max steps" in e["content"].lower() for e in error_events)
        assert any("(25)" in e["content"] for e in error_events)

    def test_custom_max_steps(self, tmp_project):
        """Agent should respect custom max_steps parameter."""
        always_action = json.dumps({"tool": "list_directory", "args": {"path": "."}})
        def infinite_caller(messages):
            return f"ACTION: {always_action}"
        agent = CodingAgent(infinite_caller)
        events = collect(agent, "loop forever", tmp_project, max_steps=5)
        error_events = [e for e in events if e["type"] == "error"]
        assert any("max steps" in e["content"].lower() for e in error_events)
        assert any("(5)" in e["content"] for e in error_events)
        # Should have 5 tool_call events
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) == 5

    def test_unlimited_steps(self, tmp_project):
        """Agent should not emit max steps error if max_steps is 0 (though we stop it manually in test)."""
        responses = [
            'ACTION: {"tool": "list_directory", "args": {"path": "."}}'
        ] * 10 + ["DONE: finally done"]

        idx = [0]
        def caller(messages):
            r = responses[idx[0]]
            idx[0] += 1
            return r

        agent = CodingAgent(caller)
        events = collect(agent, "loop long", tmp_project, max_steps=0)

        types = [e["type"] for e in events]
        assert "done" in types
        assert "error" not in [e["type"] for e in events if "max steps" in str(e.get("content", ""))]
        assert idx[0] == 11


# ── _run_command ──────────────────────────────────────────────────────────────

class TestRunCommand:
    def test_runs_simple_command(self, tmp_project):
        agent = CodingAgent(make_caller("DONE: x"))
        result = agent._run_command("echo hello", tmp_project)
        assert "hello" in result

    def test_empty_command_returns_error(self, tmp_project):
        agent = CodingAgent(make_caller("DONE: x"))
        result = agent._run_command("   ", tmp_project)
        assert result.startswith("ERROR")

    def test_failed_command_shows_exit_code(self, tmp_project):
        agent = CodingAgent(make_caller("DONE: x"))
        result = agent._run_command("exit 1", tmp_project)
        assert "[exit 1]" in result or "exit" in result.lower()
