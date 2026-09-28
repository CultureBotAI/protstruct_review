"""Recount retained T14 aggregates; no scientific tools or fresh measurements."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECORD = REPO / "ref/research/data/round48_flip_sets.json"


def recount(path: Path = RECORD) -> dict:
    raw = path.read_bytes()
    record = json.loads(raw)
    rows = record["rows"]
    if len({row["pdb_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate retained model identities")
    for row in rows:
        for count, values in (("n_reduce2_confident_conflicts", "reduce2_confident_conflicts"),
                              ("n_reduce2_decision_disagreements", "reduce2_disagreements")):
            if row[count] != len(row[values]):
                raise ValueError(f"{row['pdb_id']}: retained count/list mismatch: {count}")
        if not 0 <= row["n_reduce2_confident_conflicts"] <= row["n_reduce2_decision_disagreements"] <= row["n_reduce2_shared"]:
            raise ValueError(f"{row['pdb_id']}: invalid retained numerator/denominator")
        if row["n_h_standalone"] <= 0:
            raise ValueError(f"{row['pdb_id']}: missing standalone H-count denominator")
    denominator = sum(row["n_reduce2_shared"] for row in rows)
    confident = sum(row["n_reduce2_confident_conflicts"] for row in rows)
    disagreements = sum(row["n_reduce2_decision_disagreements"] for row in rows)
    h_gaps = [(row["pdb_id"], 100 * (row["n_h_phenix"] - row["n_h_standalone"]) / row["n_h_standalone"])
              for row in rows]
    return {
        "record_sha256": hashlib.sha256(raw).hexdigest(),
        "models": len(rows),
        "skipped": record["skipped"],
        "eligible_shared_residues": denominator,
        "confident_conflicts": confident,
        "confident_conflict_percent": 100 * confident / denominator,
        "raw_disagreements": disagreements,
        "raw_disagreement_percent": 100 * disagreements / denominator,
        "phenix_standalone_shared_residues": sum(row["n_shared"] for row in rows),
        "phenix_only_residues": sum(row["n_only_phenix"] for row in rows),
        "standalone_only_residues": sum(row["n_only_standalone"] for row in rows),
        "phenix_standalone_decision_disagreements": sum(row["n_decision_disagreements"] for row in rows),
        "maximum_absolute_h_count_gap_percent": max(h_gaps, key=lambda item: abs(item[1])),
    }


if __name__ == "__main__":
    print(json.dumps(recount(), indent=2))
