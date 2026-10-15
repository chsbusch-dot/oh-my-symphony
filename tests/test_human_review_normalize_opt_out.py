"""A hook that parks a Done card in Human Review must stay there.

Regression: on a file board whose `after_done` hook runs `symphony board mv
<ID> "Human Review"` (the PR it opened needs a person), the next tick's
legacy normalizer (`_auto_normalize_legacy_human_review_done`) moved the
card straight back to Done, because the card had an `## As-Is -> To-Be
Report` and no intervention marker. `tracker.normalize_legacy_human_review:
false` turns that sweep off for boards where Human Review always means "a
person decides"; the default keeps the upstream behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from symphony.cli import board as board_cli
from symphony.errors import ConfigValidationError
from symphony.orchestrator import Orchestrator
from symphony.trackers.file import parse_ticket_file
from symphony.workflow import WorkflowState, build_service_config, parse_workflow_text

_CARD = """---
id: LP-9
title: docs card
state: Done
---
## As-Is -> To-Be Report

As-Is: no section. To-Be: the README has the section.

## Pull Request
https://github.com/example/repo/pull/1

## Auto-merge
NOT merged: the factory token cannot read the PR's CI. The PR stays open for a human; card moved to Human Review.
"""


def _workflow(tmp_path: Path, tracker_extra: str = "") -> Path:
    path = tmp_path / "WORKFLOW.md"
    path.write_text(
        "---\n"
        "tracker:\n"
        "  kind: file\n"
        "  board_root: ./kanban\n"
        "  active_states: [Todo, In Progress]\n"
        '  terminal_states: ["Human Review", Done]\n'
        f"{tracker_extra}"
        "---\n"
        "prompt\n",
        encoding="utf-8",
    )
    (tmp_path / "kanban").mkdir()
    (tmp_path / "kanban" / "LP-9.md").write_text(_CARD, encoding="utf-8")
    return path


async def _hook_parks_card_then_tick(workflow_path: Path) -> str:
    cfg = build_service_config(
        parse_workflow_text(workflow_path.read_text(), workflow_path)
    )
    # What factory-pr.py does from inside after_done.
    assert (
        board_cli.main(["mv", "LP-9", "Human Review", "--workflow", str(workflow_path)])
        == 0
    )
    orch = Orchestrator(WorkflowState(workflow_path))
    # The per-tick sweep, three ticks' worth.
    for _ in range(3):
        await orch._auto_normalize_legacy_human_review_done(cfg)
    assert cfg.tracker.board_root is not None
    front, _body = parse_ticket_file(cfg.tracker.board_root / "LP-9.md")
    return str(front["state"])


@pytest.mark.asyncio
async def test_opt_out_keeps_hook_parked_card_in_human_review(tmp_path: Path) -> None:
    workflow_path = _workflow(tmp_path, "  normalize_legacy_human_review: false\n")
    assert await _hook_parks_card_then_tick(workflow_path) == "Human Review"


@pytest.mark.asyncio
async def test_default_still_normalizes_legacy_human_review(tmp_path: Path) -> None:
    workflow_path = _workflow(tmp_path)
    assert await _hook_parks_card_then_tick(workflow_path) == "Done"


def test_opt_out_rejects_non_boolean(tmp_path: Path) -> None:
    workflow_path = _workflow(tmp_path, '  normalize_legacy_human_review: "no"\n')
    with pytest.raises(ConfigValidationError):
        build_service_config(
            parse_workflow_text(workflow_path.read_text(), workflow_path)
        )
