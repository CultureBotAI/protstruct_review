#!/usr/bin/env python3
"""Retained 128-case round-5 ancestry probe; synthetic data, no tool runs.

Enumerate all 64 six-hop nested-assumption/whole-headline replacement patterns
against both relevant and foreign ancestry. Foreign-ancestry cases deliberately
retain a selected-subject measurement in the terminal correction owner: its
substantive evidence must not relabel another model's correction ancestry.
"""
from __future__ import annotations

import copy
import itertools
import unittest

import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256
from test_qds_contract_v4 import QDS, fixture


def ancestry_documents(pattern: tuple[str, ...], relevant: bool) -> list[dict]:
    """Reproduce the original in-memory review matrix without filesystem writes."""
    documents = fixture()
    old = documents[0]["evaluation_runs"][0]
    new = documents[-1]["evaluation_runs"][0]
    old["run_date"] = "2026-09-17"
    middle = [
        {"id": f"EVAL_chain_{day}", "run_date": f"2026-09-{day}",
         "structure_ref": "synth4", "measurements": []}
        for day in range(18, 23)
    ]
    runs = [old, *middle, new]
    for index, run in enumerate(runs):
        run["headline_findings"] = [{
            "id": f"F_{index}", "catalog_task_refs": ["T05"], "assumptions": [{
                "id": f"A_{index}", "kind": "implicit", "scope": "tool",
                "title": "Synthetic", "description": "Chain assumption", "status": "unchecked",
            }],
        }]
    if relevant:
        # Only the original measured run anchors the correction-only descendants.
        new["measurements"] = []
    else:
        old["measurements"][0]["subject_ref"] = "other-model"
        # fixture() supplies NEW/M_new for the selected subject; keep it as the
        # substantive terminal control that exposed earlier ancestry leakage.
    template = copy.deepcopy(new["corrections"][0])
    for index, kind in enumerate(pattern):
        target = runs[index]["headline_findings"][0]
        successor = runs[index + 1]["headline_findings"][0]
        if kind == "nested":
            target = target["assumptions"][0]
            successor = successor["assumptions"][0]
        runs[index + 1]["corrections"] = [{
            **template, "id": f"C_{index}",
            "target_collection": "headline_findings" if kind == "whole" else "headline_assumptions",
            "target_evaluation_run_ref": runs[index]["id"], "target_ref": target["id"],
            "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"],
        }]
    documents[0]["evaluation_runs"] = runs[:-1]
    documents[-1]["qds_emission_contexts"][0]["source_evaluation_run_refs"] = [run["id"] for run in runs]
    return documents


class AncestryMatrixTests(unittest.TestCase):
    def test_all_128_six_hop_whole_nested_subject_ancestry_cases(self) -> None:
        cases = 0
        for pattern in itertools.product(("nested", "whole"), repeat=6):
            for relevant in (True, False):
                with self.subTest(pattern=pattern, relevant=relevant):
                    documents = ancestry_documents(pattern, relevant)
                    before = copy.deepcopy(documents)
                    projection = v4.prepare_projection(documents, QDS, "synth4")
                    qds = v4.emit_projection(projection)
                    self.assertEqual(
                        [row["id"] for row in qds.get("assumptions_report", [])],
                        ["A_6"] if relevant else [],
                    )
                    self.assertEqual(len(qds["applied_corrections"]), 6)
                    self.assertEqual(len(qds["derived_from_evaluation_run_refs"]), 7)
                    self.assertEqual(documents, before)
                    cases += 1
        self.assertEqual(cases, 128)


if __name__ == "__main__":
    unittest.main()
