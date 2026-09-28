#!/usr/bin/env python3
"""Active workflow contracts (#762/#815/#817/#819), with in-memory negatives."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMPT = "prompts/backlog-loop-goal.md"
REVIEW = ".claude/skills/review-open-issues/SKILL.md"
DOCS = ("CLAUDE.md", "CODING_STANDARDS.md", "README.md", "NEXT_TASKS.md",
        ".claude/skills/protstruct-eval/SKILL.md", REVIEW, PROMPT)


def errors(documents: dict[str, str], workflow: str, python_version: str) -> list[str]:
    """Check only active routing docs, not historical scientific records."""
    failures = []
    config = yaml.safe_load(workflow)
    commands = [step.get("run", "") for step in config["jobs"]["validate"]["steps"]]
    sync = next(command for command in commands if command.startswith("uv sync "))
    gate = next(command for command in commands if "bash scripts/validate.sh" in command)
    for path, text in documents.items():
        if sync not in text or gate not in text:
            failures.append(f"{path}: CI sync/gate command drift")
        if f"Python {python_version}" not in text:
            failures.append(f"{path}: repository-selected interpreter absent")
        if "3.11" not in text or "skip" not in text or "no-extra" not in text:
            failures.append(f"{path}: reduced replay scope is not disclosed")
        if ("`bash scripts/validate.sh`" in text
                or "uv run --locked -- bash scripts/validate.sh" in text
                or re.search(r"(?m)^\s*bash scripts/validate\.sh", text)):
            failures.append(f"{path}: bare or no-extra required gate")
    prompt = documents[PROMPT]
    flat = re.sub(r"\\\n\s*", " ", prompt)
    if "there is no CI" in prompt:
        failures.append("prompt: false no-CI assertion")
    if re.search(r"/(?:Users|home)/[^/\s]+/", prompt):
        failures.append("prompt: personal checkout path")
    for kind in ("issue", "pr"):
        command = re.search(rf"gh {kind} list[^\n]+", flat)
        if not command or any(token not in command[0] for token in (
                "--repo CultureBotAI/protstruct_review", "--limit 5000", "--json")):
            failures.append(f"prompt: incomplete {kind} survey")
        if kind == "issue" and (not command or any(field not in command[0] for field in ("body", "comments"))):
            failures.append("prompt: title-only issue assessment")
    for path in (PROMPT, REVIEW):
        for field in ("issues.totalCount", "pullRequests.totalCount"):
            if field not in documents[path]:
                failures.append(f"{path}: missing {field} completeness check")
    for token in ("validate (ubuntu-latest)", "validate (macos-latest)", "SUCCESS",
                  "headRefOid", "--match-head-commit <reviewed-sha>", "closingIssuesReferences",
                  "planned squash message", "outstanding issues still open",
                  "Never negate a closing directive", "isolated scratch copy/fixture"):
        if token not in prompt:
            failures.append(f"prompt: missing safeguard {token}")
    if "PROVE IT — revert, watch it fail" in prompt:
        failures.append("prompt: review mutates active checkout")
    return failures


class WorkflowDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = {path: (ROOT / path).read_text() for path in DOCS}
        cls.workflow = (ROOT / ".github/workflows/validate.yml").read_text()
        cls.python_version = (ROOT / ".python-version").read_text().strip()

    def check(self, documents):
        return errors(documents, self.workflow, self.python_version)

    def test_active_documentation_matches_ci_and_workflow_contracts(self):
        self.assertEqual(self.check(self.documents), [])

    def test_each_active_document_cannot_drop_benchmark_extra(self):
        for path in DOCS:
            with self.subTest(path=path):
                changed = dict(self.documents)
                changed[path] = changed[path].replace("--extra benchmark ", "")
                self.assertTrue(self.check(changed))

    def test_claiming_any_supported_interpreter_is_equivalent_fails(self):
        for path in DOCS:
            changed = dict(self.documents)
            changed[path] = changed[path].replace(f"Python {self.python_version}", "any Python")
            with self.subTest(path=path):
                self.assertTrue(self.check(changed))

    def test_each_survey_must_name_repo_limit_and_evidence(self):
        for old, new in (
            ("--repo CultureBotAI/protstruct_review", ""), ("--limit 5000", ""),
            ("number,title,body,comments,labels,url", "number,title"),
            ("issues.totalCount", "issues.uncheckedCount"),
            ("pullRequests.totalCount", "pullRequests.uncheckedCount"),
        ):
            with self.subTest(old=old):
                changed = dict(self.documents)
                changed[PROMPT] = changed[PROMPT].replace(old, new)
                self.assertTrue(self.check(changed))

    def test_old_review_and_closure_failure_modes_are_detected(self):
        for addition in ("there is no CI", "PROVE IT — revert, watch it fail, restore."):
            changed = dict(self.documents)
            changed[PROMPT] += "\n" + addition
            self.assertTrue(self.check(changed))
        for token in ("closingIssuesReferences", "outstanding issues still open",
                      "Never negate a closing directive", "--match-head-commit <reviewed-sha>",
                      "isolated scratch copy/fixture", "validate (macos-latest)"):
            changed = dict(self.documents)
            changed[PROMPT] = changed[PROMPT].replace(token, "REMOVED")
            with self.subTest(token=token):
                self.assertTrue(self.check(changed))


if __name__ == "__main__":
    unittest.main()
