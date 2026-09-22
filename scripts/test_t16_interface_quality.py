#!/usr/bin/env python3
"""Network-free tests for t16_interface_quality (no DockQ binary needed).

These cover pure logic and replay the retained 1SAR DockQ and BSA evidence
against their tracked inputs, without invoking DockQ or another scientific binary.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import json
import math
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t16_interface_quality as t16  # noqa: E402
import qds_emit  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL  {msg}")
        raise SystemExit(1)
    print(f"PASS  {msg}")


def _dockq_result(
    score: float,
    mapping: str = "AB:AB",
    model: str = "model.pdb",
    native: str = "native.pdb",
) -> dict:
    """Minimal valid DockQ JSON for one two-chain comparison."""
    interface_name = mapping.split(":", 1)[1]
    model_chains, native_chains = mapping.split(":", 1)
    chain_map = dict(zip(model_chains, native_chains, strict=True))
    # Give all three standard DockQ terms the requested value so that the
    # synthetic score is independently reproducible from the retained fields.
    if math.isfinite(score) and 0.0 < score <= 1.0:
        scaled_rmsd = math.sqrt(1.0 / score - 1.0)
        fnat = score
        irmsd = 1.5 * scaled_rmsd
        lrmsd = 8.5 * scaled_rmsd
    else:
        # These cases are intentionally rejected from the score field before
        # component consistency is considered.
        fnat, irmsd, lrmsd = 0.5, 1.5, 8.5
    return {
        "model": model,
        "native": native,
        "GlobalDockQ": score,
        "best_dockq": score,
        "best_mapping": chain_map,
        "best_mapping_str": mapping,
        "best_result": {
            interface_name: {
                "DockQ": score,
                "iRMSD": irmsd,
                "LRMSD": lrmsd,
                "fnat": fnat,
                "chain_map": chain_map,
            }
        },
    }


def _bsa_result(value: float = 437.8) -> dict:
    """Minimal internally consistent Biotite result for wrapper unit tests."""
    complex_sasa = 1000.0
    separated_sasa = complex_sasa + value
    return {
        "bsa": value,
        "chains": ["A", "B"],
        "complex_sasa": round(complex_sasa, 1),
        "complex_sasa_unrounded": complex_sasa,
        "separated_sasa_unrounded": separated_sasa,
        "bsa_unrounded": value,
    }


def test_capri_bands() -> None:
    # Boundaries from Basu & Wallner 2016: High>=0.80, Medium[0.49,0.80),
    # Acceptable[0.23,0.49), Incorrect<0.23.
    cases = {
        1.0: "High", 0.80: "High", 0.799: "Medium", 0.49: "Medium",
        0.489: "Acceptable", 0.23: "Acceptable", 0.229: "Incorrect", 0.0: "Incorrect",
    }
    for score, expected in cases.items():
        got = t16.capri_class(score)
        _check(got == expected, f"DockQ {score} -> {expected} (got {got})")


def test_extract() -> None:
    s = t16.extract(_dockq_result(0.5123), "AB:AB")
    _check(s["dockq"] == 0.5123, f"extract global DockQ (got {s['dockq']})")
    _check(s["capri"] == "Medium", f"extract derives CAPRI class (got {s['capri']})")
    _check(s["mapping"] == "AB:AB" and "AB" in s["interfaces"],
           "extract carries mapping + per-interface breakdown")
    for retained, removed in (
        ("GlobalDockQ", "best_dockq"),
        ("best_dockq", "GlobalDockQ"),
    ):
        single_alias = _dockq_result(0.5123)
        single_alias.pop(removed)
        _check(
            t16.extract(single_alias, "AB:AB")["dockq"] == 0.5123,
            f"extract accepts the documented {retained}-only score form",
        )


def test_extract_classifies_the_emitted_score() -> None:
    cases = {
        0.79996: "Medium",
        0.48996: "Acceptable",
        0.22996: "Incorrect",
    }
    for raw, label in cases.items():
        summary = t16.extract(_dockq_result(raw), "AB:AB")
        _check(
            (summary["dockq"], summary["capri"]) == (raw, label),
            f"raw DockQ {raw} retains precision and the correct {label} class",
        )


def test_extract_rejects_unusable_or_mismatched_output() -> None:
    invalid_cases = [
        (_dockq_result(0.9, "AB:BA"), "reported mapping"),
        ({
            **_dockq_result(0.9, "AB:AB"),
            "best_result": {},
        },
         "scored interface"),
        ({**_dockq_result(0.9), "GlobalDockQ": "0.9"}, "must be numeric"),
        (_dockq_result(float("nan")), "must be finite"),
        (_dockq_result(1.1), "must be in [0, 1]"),
    ]
    for result, fragment in invalid_cases:
        try:
            t16.extract(result, "AB:AB")
        except SystemExit as exc:
            rejected = fragment in str(exc)
        else:
            rejected = False
        _check(rejected, f"invalid DockQ output is rejected ({fragment})")


def test_extract_binds_dockq_inputs_and_all_mapping_representations() -> None:
    subject = "artifact:test#model.pdb"
    reference = "repo:data/native.pdb#sha256=" + "b" * 64
    result = _dockq_result(0.9)
    result["_protstruct_input_provenance"] = {
        "model": {
            "invocation_path": "model.pdb",
            "subject_ref": subject,
            "sha256": "a" * 64,
        },
        "native": {
            "invocation_path": "native.pdb",
            "subject_ref": reference,
            "sha256": "b" * 64,
        },
        "mapping": "AB:AB",
        "tool": {"id": "DockQ", "version": "2.1.3"},
    }

    def rejects(mutated: dict, fragment: str) -> bool:
        try:
            t16.extract(
                mutated,
                "AB:AB",
                expected_subject_ref=subject,
                expected_reference_subject_ref=reference,
                expected_model_sha256="a" * 64,
                expected_native_sha256="b" * 64,
                expected_dockq_version="2.1.3",
            )
        except SystemExit as exc:
            return fragment in str(exc)
        return False

    valid = t16.extract(
        result,
        "AB:AB",
        expected_subject_ref=subject,
        expected_reference_subject_ref=reference,
        expected_model_sha256="a" * 64,
        expected_native_sha256="b" * 64,
        expected_dockq_version="2.1.3",
    )
    _check(valid["dockq"] == 0.9, "fully bound DockQ evidence is accepted")
    for label, mutate, fragment in (
        (
            "candidate digest",
            lambda row: row["_protstruct_input_provenance"]["model"].__setitem__(
                "sha256", "c" * 64
            ),
            "model.sha256",
        ),
        (
            "reference digest",
            lambda row: row["_protstruct_input_provenance"]["native"].__setitem__(
                "sha256", "c" * 64
            ),
            "native.sha256",
        ),
        (
            "DockQ version",
            lambda row: row["_protstruct_input_provenance"]["tool"].__setitem__(
                "version", "9.9.9"
            ),
            "tool.version",
        ),
        (
            "best mapping object",
            lambda row: row.__setitem__("best_mapping", {"A": "B", "B": "A"}),
            "best_mapping",
        ),
        (
            "interface chain map",
            lambda row: row["best_result"]["AB"].__setitem__(
                "chain_map", {"A": "B", "B": "A"}
            ),
            "chain_map",
        ),
        (
            "best/global score agreement",
            lambda row: row.__setitem__("best_dockq", 0.8),
            "GlobalDockQ and best_dockq disagree",
        ),
        (
            "standard score formula components",
            lambda row: row["best_result"]["AB"].__setitem__("fnat", 0.2),
            "standard DockQ formula",
        ),
    ):
        mutated = json.loads(json.dumps(result))
        mutate(mutated)
        _check(rejects(mutated, fragment), f"DockQ rejects mutated {label}")


def test_committed_1sar_dockq_evidence_matches_eval() -> None:
    evidence_dir = REPO / "data/coscientists/openscientist"
    eval_path = evidence_dir / "EVAL_1sar_cdba2c07_2026-09-21.yaml"
    eval_doc = yaml.safe_load(eval_path.read_text())
    evaluation = eval_doc["evaluation_runs"][0]
    interface_quality_rows = evaluation["interface_qualities"]
    interface_rows = {
        row["model_to_native_chain_mapping"]: row for row in interface_quality_rows
    }
    _check(
        len(interface_quality_rows) == len(interface_rows) == 2
        and set(interface_rows) == {"AB:AB", "AB:BA"},
        "1SAR retains exactly one InterfaceQuality row for each tested mapping",
    )
    evidence_paths = {
        "AB:AB": evidence_dir
        / "EVIDENCE_1sar_cdba2c07_2026-09-21_dockq_AB_AB.json",
        "AB:BA": evidence_dir
        / "EVIDENCE_1sar_cdba2c07_2026-09-21_dockq_AB_BA.json",
    }
    extracted = {}
    bsa_evidence = json.loads(
        (evidence_dir / "EVIDENCE_1sar_cdba2c07_2026-09-21_bsa.json").read_text()
    )
    archive = REPO / bsa_evidence["source_archive"]
    member = bsa_evidence["source_member"]
    _check(
        archive.relative_to(REPO).as_posix()
        == "data/coscientists/openscientist/"
        "cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip"
        and member == "data/1sar_final.pdb",
        "DockQ candidate provenance names the tracked source archive member",
    )
    with zipfile.ZipFile(archive) as source_zip:
        candidate_sha256 = hashlib.sha256(source_zip.read(member)).hexdigest()
    native = REPO / "data/pdb_mtz/1sar_deposited.pdb"
    native_sha256 = hashlib.sha256(native.read_bytes()).hexdigest()
    candidate_subject = bsa_evidence["subject_ref"]
    reference_subject = (
        f"repo:{native.relative_to(REPO).as_posix()}#sha256={native_sha256}"
    )
    dockq_version = next(
        str(tool["version"])
        for tool in eval_doc["tools"]
        if tool["id"] == "DockQ"
    )
    _check(dockq_version == "2.1.3", "1SAR replay pins DockQ 2.1.3")
    for mapping, path in evidence_paths.items():
        summary = t16.extract(
            json.loads(path.read_text()),
            mapping,
            expected_subject_ref=candidate_subject,
            expected_reference_subject_ref=reference_subject,
            expected_model_sha256=candidate_sha256,
            expected_native_sha256=native_sha256,
            expected_dockq_version=dockq_version,
        )
        row = interface_rows[mapping]
        extracted[mapping] = summary
        _check(summary["mapping"] == row["model_to_native_chain_mapping"],
               f"{mapping} retained mapping matches InterfaceQuality")
        _check(summary["dockq"] == row["dockq_score"]["value_numeric"],
               f"{mapping} rounded DockQ matches InterfaceQuality")
        _check(summary["capri"] == row["capri_quality_class"]["value_text"],
               f"{mapping} CAPRI class matches InterfaceQuality")
        relative_evidence = path.relative_to(REPO).as_posix()
        _check(relative_evidence in row["evidence_refs"],
               f"{mapping} InterfaceQuality cites the replayed evidence")

    identity_row = interface_rows["AB:AB"]
    selected_rows = [
        row
        for row in evaluation["measurements"]
        if row.get("scope_selector") == identity_row["id"]
        and row.get("metric_definition_ref")
        in {"T16_interface_dockq_score", "T16_capri_interface_quality_class"}
    ]
    selected_measurements = {
        row["metric_definition_ref"]: row
        for row in selected_rows
    }
    _check(
        len(selected_rows) == len(selected_measurements) == 2
        and set(selected_measurements)
        == {"T16_interface_dockq_score", "T16_capri_interface_quality_class"},
        "AB:AB has exactly the two selected DockQ/CAPRI scalar metric kinds",
    )
    dockq_measurement = selected_measurements["T16_interface_dockq_score"]
    capri_measurement = selected_measurements["T16_capri_interface_quality_class"]
    _check(
        dockq_measurement["oracle_measure"]["value_numeric"]
        == extracted["AB:AB"]["dockq"]
        == identity_row["dockq_score"]["value_numeric"],
        "selected AB:AB DockQ scalar matches evidence and InterfaceQuality",
    )
    _check(
        capri_measurement["oracle_measure"]["value_text"]
        == extracted["AB:AB"]["capri"]
        == identity_row["capri_quality_class"]["value_text"],
        "selected AB:AB CAPRI scalar matches evidence and InterfaceQuality",
    )


def test_committed_1sar_bsa_evidence_replays_from_tracked_input() -> None:
    evidence_dir = REPO / "data/coscientists/openscientist"
    evidence_path = evidence_dir / "EVIDENCE_1sar_cdba2c07_2026-09-21_bsa.json"
    evidence = json.loads(evidence_path.read_text())
    archive = REPO / evidence["source_archive"]
    with zipfile.ZipFile(archive) as source_zip:
        source_bytes = source_zip.read(evidence["source_member"])
    _check(
        hashlib.sha256(source_bytes).hexdigest() == evidence["input_sha256"],
        "committed BSA evidence binds the actual packaged model bytes",
    )
    _check(
        evidence["tool"] == "biotite SASA"
        and evidence["tool_version"] == "1.7.1",
        "committed BSA evidence binds the pinned biotite implementation",
    )
    _check(
        evidence["algorithm"] == "Shrake-Rupley"
        and evidence["parameters"]
        == {
            "chains": ["A", "B"],
            "selection": "protein atoms only",
            "probe_radius_a": 1.4,
            "point_number": 1000,
        },
        "committed BSA evidence pins the complete selection and SASA parameters",
    )
    try:
        installed_biotite = importlib.metadata.version("biotite")
    except importlib.metadata.PackageNotFoundError:
        installed_biotite = None
    if installed_biotite == evidence["tool_version"]:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = Path(tmpdir) / Path(evidence["source_member"]).name
            model.write_bytes(source_bytes)
            replayed = t16.run_biotite_bsa(model, ("A", "B"))
        _check(
            replayed["chains"] == evidence["parameters"]["chains"]
            and replayed["bsa"] == evidence["buried_surface_area_a2_reported"]
            and math.isclose(
                replayed["complex_sasa_unrounded"],
                evidence["complex_sasa_a2"],
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            and math.isclose(
                replayed["separated_sasa_unrounded"],
                evidence["separated_sasa_a2"],
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            and math.isclose(
                replayed["bsa_unrounded"],
                evidence["buried_surface_area_a2_unrounded"],
                rel_tol=0.0,
                abs_tol=1e-6,
            ),
            "tracked packaged model replays the committed unrounded and reported BSA",
        )
    else:
        print(
            "SKIP  exact BSA numeric replay requires optional biotite "
            f"{evidence['tool_version']} (installed: {installed_biotite or 'absent'})"
        )
    unrounded = evidence["separated_sasa_a2"] - evidence["complex_sasa_a2"]
    _check(
        unrounded == evidence["buried_surface_area_a2_unrounded"]
        and t16.buried_surface_area(
            evidence["complex_sasa_a2"], evidence["separated_sasa_a2"]
        )
        == evidence["buried_surface_area_a2_reported"],
        "committed BSA arithmetic reproduces the retained unrounded and reported values",
    )

    eval_doc = yaml.safe_load(
        (evidence_dir / "EVAL_1sar_cdba2c07_2026-09-21.yaml").read_text()
    )
    evaluation = eval_doc["evaluation_runs"][0]
    bsa_measurements = [
        row
        for row in evaluation["measurements"]
        if row["metric_definition_ref"] == "T16_interface_buried_surface_area"
    ]
    relative_evidence = evidence_path.relative_to(REPO).as_posix()
    _check(
        len(bsa_measurements) == 1
        and bsa_measurements[0]["oracle_measure"]["value_numeric"]
        == evidence["buried_surface_area_a2_reported"]
        and bsa_measurements[0]["subject_ref"] == evidence["subject_ref"]
        and bsa_measurements[0]["evidence_refs"] == [relative_evidence],
        "EvaluationRun BSA scalar is exactly linked to the retained evidence",
    )
    interface = next(
        row
        for row in evaluation["interface_qualities"]
        if row["id"] == bsa_measurements[0]["scope_selector"]
    )
    _check(
        interface["buried_surface_area"]["value_numeric"]
        == evidence["buried_surface_area_a2_reported"]
        and relative_evidence in interface["evidence_refs"],
        "structured InterfaceQuality retains the same BSA value and evidence",
    )
    qds = yaml.safe_load(
        (evidence_dir / "QDS_1sar_cdba2c07_2026-09-21.yaml").read_text()
    )["quality_data_sheets"][0]
    qds_bsa = qds["interface_quality_summary"]["interface_buried_surface_area"]
    _check(
        qds_bsa["value_numeric"] == evidence["buried_surface_area_a2_reported"]
        and qds_bsa["evidence_refs"] == [relative_evidence],
        "QDS BSA projection preserves the retained value and evidence link",
    )


def test_buried_surface_area() -> None:
    # BSA = ΣSASA(chains) − SASA(complex); burial reduces exposed area.
    _check(t16.buried_surface_area(10804.5, 11241.7) == 437.2,
           f"BSA = separated − complex (got {t16.buried_surface_area(10804.5, 11241.7)})")
    _check(t16.buried_surface_area(5000.0, 5000.0) == 0.0, "no burial -> BSA 0")


def test_render_keeps_comparison_provenance() -> None:
    summary = {
        "dockq": 0.9445,
        "capri": "High",
        "mapping": "AB:AB",
        "interfaces": {"AB": {"dockq": 0.9445}},
    }
    rows = yaml.safe_load(t16.render_yaml(
        summary,
        "EVAL_x",
        "EVAL_x_IFACE_AB_IDENTITY",
        "artifact:x#model.pdb",
        "pdb:1abc",
        "data/evidence/model_AB_AB.dockq.json",
    ))
    _check(len({row["id"] for row in rows}) == 2, "DockQ and CAPRI row ids are unique")
    for row in rows:
        _check(row["scope_selector"] == "EVAL_x_IFACE_AB_IDENTITY",
               "measurement selects the declared interface row")
        _check(row["subject_ref"] == "artifact:x#model.pdb",
               "candidate subject survives rendering")
        _check(row["reference_subject_ref"] == "pdb:1abc",
               "native/reference subject survives rendering")
        _check(row["evidence_refs"] == ["data/evidence/model_AB_AB.dockq.json"],
               "retained raw DockQ evidence survives rendering")
        _check("mapping AB:AB" in row["notes"], "mapping survives rendering")


def test_bsa_selects_declared_interface() -> None:
    evidence_ref = "data/evidence/model_AB.bsa.json"
    fragment = yaml.safe_load(t16.render_bsa_yaml(
        _bsa_result(),
        "EVAL_x",
        "EVAL_x_IFACE_AB_IDENTITY",
        "artifact:x#model.pdb",
        "synth",
        evidence_ref,
    ))
    rows = fragment["measurements"]
    _check(rows[0]["scope_selector"] == "EVAL_x_IFACE_AB_IDENTITY",
           "BSA selects the declared interface row")
    _check(rows[0]["id"].endswith("EVAL_x_IFACE_AB_IDENTITY"),
           "BSA measurement id includes its interface selector")
    context = fragment["interface_qualities"][0]
    _check(
        context["id"] == rows[0]["scope_selector"]
        and context["buried_surface_area"] == rows[0]["oracle_measure"]
        and rows[0]["evidence_refs"] == context["evidence_refs"] == [evidence_ref]
        and context["tool_ref"] == "biotite SASA",
        "BSA-only output includes truthful tool and retained evidence context",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "eval.yaml"
        path.write_text(yaml.safe_dump({
            "structures": [{"id": "synth", "method": "xray"}],
            "evaluation_runs": [{
                "id": "EVAL_x",
                "structure_ref": "synth",
                "run_date": "2026-09-22",
                "catalog_tasks_applied": ["T16"],
                **fragment,
            }],
        }, sort_keys=False))
        qds = qds_emit.emit_qds(
            [path],
            qds_id="QDS_bsa_only",
            structure_id="synth",
            subject_ref="artifact:x#model.pdb",
            coverage_scope="partial",
            scope_notes="BSA-only wrapper integration fixture.",
            issued_at="2026-09-22T10:00:00+00:00",
            emitter_contract_version="2",
        )
    _check(
        qds["interface_quality_summary"]["interface_buried_surface_area"]
        ["value_numeric"] == 437.8,
        "BSA-only wrapper fragment is accepted by QDS emission",
    )


def test_bsa_only_main_retains_content_bound_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model.write_text("END\n")
        evidence_path = root / "evidence" / "bsa.json"
        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(t16, "run_biotite_bsa", return_value=_bsa_result()),
            mock.patch.object(
                t16, "measured_biotite_version", return_value="1.7.1"
            ),
            mock.patch.object(
                t16, "run_dockq", side_effect=AssertionError("DockQ must not run")
            ),
            contextlib.redirect_stdout(stdout),
        ):
            t16.main(
                [
                    str(model),
                    "--chains",
                    "A:B",
                    "--structure-id",
                    "synth",
                    "--subject-ref",
                    "artifact:model",
                    "--bsa-evidence",
                    str(evidence_path),
                ]
            )

        evidence = json.loads(evidence_path.read_text())
        fragment = yaml.safe_load(stdout.getvalue())
        bsa_row = fragment["measurements"][0]
        context = fragment["interface_qualities"][0]
        _check(
            evidence["input_sha256"]
            == hashlib.sha256(model.read_bytes()).hexdigest()
            and evidence["tool_version"] == "1.7.1"
            and evidence["parameters"]
            == {
                "chains": ["A", "B"],
                "selection": "protein atoms only",
                "probe_radius_a": 1.4,
                "point_number": 1000,
            }
            and evidence["buried_surface_area_a2_unrounded"] == 437.8,
            "BSA-only wrapper retains input, tool, parameters, and raw arithmetic",
        )
        _check(
            bsa_row["evidence_refs"]
            == context["evidence_refs"]
            == ["evidence/bsa.json"],
            "BSA-only scalar and structured row cite the retained evidence",
        )


def test_sequence_equivalent_mapping_controls() -> None:
    same = {"A": ("ALA", "GLY"), "B": ("ALA", "GLY")}
    expected = t16._sequence_equivalent_mappings(same, ("A", "B"), ("A", "B"))
    _check(expected == {"AB:AB", "AB:BA"},
           "same-sequence two-chain contact requires identity and swapped controls")
    hetero_native = {"A": ("ALA",), "B": ("GLY",)}
    expected = t16._sequence_equivalent_mappings(
        hetero_native, ("A", "B"), ("A", "B")
    )
    _check(expected == {"AB:AB"}, "heteromer has only its explicit native mapping")


def test_imperfect_candidate_native_pairs_are_accepted() -> None:
    native_sequences = {
        "A": ("ALA", "GLY", "SER"),
        "B": ("VAL", "THR", "LEU"),
    }
    imperfect_candidates = {
        "missing residue": {
            "A": ("ALA", "SER"),
            "B": ("VAL", "THR", "LEU"),
        },
        "point mutation": {
            "A": ("ALA", "ASP", "SER"),
            "B": ("VAL", "THR", "LEU"),
        },
    }
    for label, model_sequences in imperfect_candidates.items():
        with mock.patch.object(
            t16,
            "_protein_chain_sequences",
            side_effect=[model_sequences, native_sequences],
        ):
            pair = t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB"],
                ("A", "B"), ("A", "B"),
            )
        _check(
            pair == ("A", "B"),
            f"explicit heteromer mapping accepts an ordinary candidate {label}",
        )


def test_native_homomer_controls_survive_candidate_imperfections() -> None:
    model_sequences = {
        "A": ("ALA",),
        "B": ("ASP", "GLY"),
    }
    native_sequences = {
        "A": ("ALA", "GLY"),
        "B": ("ALA", "GLY"),
    }
    with mock.patch.object(
        t16,
        "_protein_chain_sequences",
        side_effect=[model_sequences, native_sequences],
    ):
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB"],
                ("A", "B"), ("A", "B"),
            )
        except SystemExit as exc:
            incomplete = "missing=['AB:BA']" in str(exc)
        else:
            incomplete = False
    _check(
        incomplete,
        "equivalent native partners still require a swapped control when the candidate is imperfect",
    )
    with mock.patch.object(
        t16,
        "_protein_chain_sequences",
        side_effect=[model_sequences, native_sequences],
    ):
        pair = t16._validate_mapping_controls(
            Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"],
            ("A", "B"), ("A", "B"),
        )
    _check(
        pair == ("A", "B"),
        "complete homomer controls accept missing-residue/mutation candidate differences",
    )


def test_mapping_controls_are_complete_and_match_bsa_chains() -> None:
    sequences = {"A": ("ALA",), "B": ("ALA",)}
    with mock.patch.object(t16, "_protein_chain_sequences", return_value=sequences):
        pair = t16._validate_mapping_controls(
            Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"],
            ("A", "B"), ("A", "B"),
        )
        _check(pair == ("A", "B"), "complete controls return the bound BSA chain pair")
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB"],
                ("A", "B"), ("A", "B"),
            )
        except SystemExit as exc:
            incomplete = "missing=['AB:BA']" in str(exc)
        else:
            incomplete = False
        _check(incomplete, "omitting a sequence-equivalent mapping fails loudly")
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"],
                ("C", "D"), ("A", "B"),
            )
        except SystemExit as exc:
            mismatch = "does not match mapping candidate chains" in str(exc)
        else:
            mismatch = False
        _check(mismatch, "BSA chain selection must match DockQ candidate chains")

    model_sequences = {"A": ("ALA",), "B": ("ALA",)}
    native_sequences = {
        "A": ("ALA",), "B": ("ALA",), "C": ("ALA",),
    }
    with mock.patch.object(
        t16, "_protein_chain_sequences",
        side_effect=[model_sequences, native_sequences],
    ):
        pair = t16._validate_mapping_controls(
            Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"],
            ("A", "B"), ("A", "B"),
        )
    _check(
        pair == ("A", "B"),
        "an extra identical native chain stays outside the explicitly selected interface",
    )
    with mock.patch.object(
        t16, "_protein_chain_sequences",
        side_effect=[model_sequences, native_sequences],
    ):
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:AC"],
                ("A", "B"), ("A", "B"),
            )
        except SystemExit as exc:
            escaped = "explicitly selected native interface" in str(exc)
        else:
            escaped = False
    _check(
        escaped,
        "a mapping cannot silently widen the selected native interface to an identical chain",
    )


def test_missing_native_emits_no_partial_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        model = Path(tmpdir) / "model.pdb"
        model.write_text("END\n")
        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", Path(tmpdir)),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                t16.main([
                    str(model), "--native", str(Path(tmpdir) / "missing.pdb"),
                    "--structure-id", "synth",
                    "--subject-ref", "artifact:model", "--reference-subject-ref", "pdb:native",
                    "--bsa-evidence", str(Path(tmpdir) / "bsa.json"),
                    "--native-chains", "A:B",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_AB",
                    "--raw-json", str(Path(tmpdir) / "raw.json"),
                    "--headline-interface-id", "IFACE_AB",
                ])
            except SystemExit as exc:
                failed = "file not found" in str(exc)
            else:
                failed = False
        _check(failed and stdout.getvalue() == "",
               "native preflight fails before printing a valid-looking BSA prefix")


def test_dockq_failure_leaves_no_partial_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        target = root / "evidence.json"

        seen: list[list[str]] = []

        def failed_run(arguments):
            seen.append(arguments)
            Path(arguments[arguments.index("--json") + 1]).write_text("{partial")
            return SimpleNamespace(returncode=2, stdout="", stderr="failed")

        with (
            mock.patch.object(t16, "measured_dockq_version", return_value="2.1.3"),
            mock.patch.object(t16, "run_capture", side_effect=failed_run),
        ):
            try:
                t16.run_dockq(root / "model.pdb", root / "native.pdb", "AB:AB", target)
            except SystemExit:
                pass
        leftovers = list(root.glob(".*evidence.json.*.tmp"))
        _check(not target.exists() and not leftovers,
               "failed DockQ removes its temporary/partial JSON and leaves target reusable")
        _check(
            bool(seen) and seen[0][:3] == [sys.executable, "-m", "DockQ"],
            "DockQ runs through the wrapper interpreter, not an unrelated PATH script",
        )


def test_repeated_mappings_publish_as_one_group() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        finals = [root / "identity.json", root / "swapped.json"]
        calls = 0

        def fail_second(_model, _native, mapping, destination):
            nonlocal calls
            calls += 1
            destination.write_text('{"complete": true}')
            if calls == 2:
                raise SystemExit("second mapping failed")
            return {
                **_dockq_result(0.9, mapping, str(_model), str(_native)),
            }

        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(t16, "_validate_mapping_controls", return_value=("A", "B")),
            mock.patch.object(
                t16,
                "run_biotite_bsa",
                return_value=_bsa_result(1.0),
            ),
            mock.patch.object(t16, "measured_biotite_version", return_value="1.7.1"),
            mock.patch.object(t16, "run_dockq", side_effect=fail_second),
            mock.patch.object(t16, "measured_dockq_version", return_value="2.1.3"),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                t16.main([
                    str(model), "--native", str(native),
                    "--structure-id", "synth",
                    "--subject-ref", "artifact:model",
                    "--reference-subject-ref", "artifact:native",
                    "--bsa-evidence", str(root / "bsa.json"),
                    "--native-chains", "A:B",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_ID",
                    "--raw-json", str(finals[0]),
                    "--mapping", "AB:BA", "--interface-id", "IFACE_SWAP",
                    "--raw-json", str(finals[1]),
                    "--headline-interface-id", "IFACE_ID",
                ])
            except SystemExit:
                pass
        leftovers = list(root.glob(".*.group.*.json"))
        _check(
            not any(path.exists() for path in finals)
            and not (root / "bsa.json").exists()
            and not leftovers
            and stdout.getvalue() == "",
            "a later mapping failure publishes no DockQ/BSA evidence or YAML",
        )


def test_evidence_publication_failure_rolls_back_whole_group() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        bsa_final = root / "bsa.json"
        dockq_final = root / "dockq.json"

        def successful_run(_model, _native, mapping, destination):
            destination.write_text('{"complete": true}')
            return _dockq_result(0.9, mapping, str(_model), str(_native))

        real_link = t16.os.link
        link_calls = 0

        def fail_second_link(source, destination):
            nonlocal link_calls
            link_calls += 1
            if link_calls == 2:
                raise OSError("simulated publication failure")
            return real_link(source, destination)

        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(
                t16, "_validate_mapping_controls", return_value=("A", "B")
            ),
            mock.patch.object(t16, "run_biotite_bsa", return_value=_bsa_result()),
            mock.patch.object(
                t16, "measured_biotite_version", return_value="1.7.1"
            ),
            mock.patch.object(t16, "run_dockq", side_effect=successful_run),
            mock.patch.object(
                t16, "measured_dockq_version", return_value="2.1.3"
            ),
            mock.patch.object(t16.os, "link", side_effect=fail_second_link),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                t16.main(
                    [
                        str(model),
                        "--native",
                        str(native),
                        "--structure-id",
                        "synth",
                        "--subject-ref",
                        "artifact:model",
                        "--reference-subject-ref",
                        "artifact:native",
                        "--bsa-evidence",
                        str(bsa_final),
                        "--native-chains",
                        "A:B",
                        "--mapping",
                        "AB:AB",
                        "--interface-id",
                        "IFACE_ID",
                        "--raw-json",
                        str(dockq_final),
                        "--headline-interface-id",
                        "IFACE_ID",
                    ]
                )
            except OSError as exc:
                failed = "simulated publication failure" in str(exc)
            else:
                failed = False
        _check(
            failed
            and not bsa_final.exists()
            and not dockq_final.exists()
            and not list(root.glob(".*.group.*.json"))
            and stdout.getvalue() == "",
            "a publication failure rolls back the complete DockQ/BSA evidence group",
        )


def test_native_interface_selection_is_required() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        with mock.patch.object(t16, "REPO", root):
            try:
                t16.main([
                    str(model), "--native", str(native),
                    "--structure-id", "synth",
                    "--subject-ref", "artifact:model",
                    "--reference-subject-ref", "artifact:native",
                    "--bsa-evidence", str(root / "bsa.json"),
                    "--headline-interface-id", "IFACE_ID",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_ID",
                    "--raw-json", str(root / "raw.json"),
                ])
            except SystemExit as exc:
                rejected = "requires --native-chains" in str(exc)
            else:
                rejected = False
        _check(
            rejected,
            "DockQ scoring cannot infer its native interface from the first mapping",
        )


def test_nested_evidence_parent_is_created_before_staging() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        final = root / "new" / "evidence" / "identity.json"

        def successful_run(_model, _native, mapping, destination):
            destination.write_text('{"complete": true}')
            return _dockq_result(0.9, mapping, str(_model), str(_native))

        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(t16, "_validate_mapping_controls", return_value=("A", "B")),
            mock.patch.object(
                t16,
                "run_biotite_bsa",
                return_value=_bsa_result(1.0),
            ),
            mock.patch.object(t16, "measured_biotite_version", return_value="1.7.1"),
            mock.patch.object(t16, "run_dockq", side_effect=successful_run),
            mock.patch.object(t16, "measured_dockq_version", return_value="2.1.3"),
            contextlib.redirect_stdout(stdout),
        ):
            t16.main([
                str(model), "--native", str(native),
                "--structure-id", "synth",
                "--subject-ref", "artifact:model",
                "--reference-subject-ref", "artifact:native",
                "--bsa-evidence", str(root / "new" / "evidence" / "bsa.json"),
                "--native-chains", "A:B",
                "--mapping", "AB:AB", "--interface-id", "IFACE_ID",
                "--raw-json", str(final),
                "--headline-interface-id", "IFACE_ID",
            ])
        _check(
            final.is_file()
            and (root / "new" / "evidence" / "bsa.json").is_file()
            and "T16_interface_dockq_score" in stdout.getvalue(),
            "a new nested directory atomically publishes DockQ and BSA evidence",
        )


def test_headline_interface_selection_is_required() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        with mock.patch.object(t16, "REPO", root):
            try:
                t16.main([
                    str(model), "--native", str(native),
                    "--structure-id", "synth",
                    "--subject-ref", "artifact:model",
                    "--reference-subject-ref", "artifact:native",
                    "--bsa-evidence", str(root / "bsa.json"),
                    "--native-chains", "A:B",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_ID",
                    "--raw-json", str(root / "raw.json"),
                ])
            except SystemExit as exc:
                rejected = "requires --headline-interface-id" in str(exc)
            else:
                rejected = False
        _check(
            rejected,
            "DockQ scoring requires an explicit headline interface instead of argument order",
        )


def test_headline_selection_is_order_independent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")

        def successful_run(_model, _native, mapping, destination):
            destination.write_text('{"complete": true}')
            return _dockq_result(
                0.9 if mapping == "AB:AB" else 0.1,
                mapping,
                str(_model),
                str(_native),
            )

        def run_with_order(label: str, order: list[tuple[str, str]]) -> str:
            arguments = [
                str(model), "--native", str(native),
                "--structure-id", "synth",
                "--subject-ref", "artifact:model",
                "--reference-subject-ref", "artifact:native",
                "--bsa-evidence", str(root / label / "bsa.json"),
                "--native-chains", "A:B",
                "--headline-interface-id", "IFACE_IDENTITY",
            ]
            for mapping, interface_id in order:
                arguments.extend([
                    "--mapping", mapping,
                    "--interface-id", interface_id,
                    "--raw-json", str(root / label / f"{interface_id}.json"),
                ])
            stdout = io.StringIO()
            with (
                mock.patch.object(t16, "REPO", root),
                mock.patch.object(
                    t16, "_validate_mapping_controls", return_value=("A", "B")
                ),
                mock.patch.object(
                    t16,
                    "run_biotite_bsa",
                    return_value=_bsa_result(1.0),
                ),
                mock.patch.object(
                    t16, "measured_biotite_version", return_value="1.7.1"
                ),
                mock.patch.object(t16, "run_dockq", side_effect=successful_run),
                mock.patch.object(
                    t16, "measured_dockq_version", return_value="2.1.3"
                ),
                contextlib.redirect_stdout(stdout),
            ):
                t16.main(arguments)
            fragment = yaml.safe_load(stdout.getvalue())
            rows = fragment["measurements"]
            bsa = next(
                row
                for row in rows
                if row["metric_definition_ref"] == "T16_interface_buried_surface_area"
            )
            headline_rows = [
                row
                for row in rows
                if row["metric_definition_ref"]
                in {"T16_interface_dockq_score", "T16_capri_interface_quality_class"}
            ]
            _check(
                len(headline_rows) == 2
                and {row["scope_selector"] for row in headline_rows}
                == {"IFACE_IDENTITY"},
                "only the explicit headline mapping emits DockQ/CAPRI scalar rows",
            )
            _check(
                {
                    row["model_to_native_chain_mapping"]
                    for row in fragment["interface_qualities"]
                }
                == {"AB:AB", "AB:BA"},
                "every scored mapping is retained as InterfaceQuality",
            )
            return bsa["scope_selector"]

        identity_first = run_with_order(
            "identity-first",
            [("AB:AB", "IFACE_IDENTITY"), ("AB:BA", "IFACE_SWAPPED")],
        )
        identity_second = run_with_order(
            "identity-second",
            [("AB:BA", "IFACE_SWAPPED"), ("AB:AB", "IFACE_IDENTITY")],
        )
        _check(
            identity_first == identity_second == "IFACE_IDENTITY",
            "reordering mapping triples cannot change the explicit headline interface",
        )


def test_multimapping_fragment_is_qds_emittable() -> None:
    """The wrapper must produce the one-headline/many-controls QDS model."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")

        def successful_run(_model, _native, mapping, destination):
            destination.write_text('{"complete": true}')
            return _dockq_result(
                0.9 if mapping == "AB:AB" else 0.1,
                mapping,
                str(_model),
                str(_native),
            )

        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(
                t16, "_validate_mapping_controls", return_value=("A", "B")
            ),
            mock.patch.object(
                t16,
                "run_biotite_bsa",
                return_value=_bsa_result(),
            ),
            mock.patch.object(t16, "measured_biotite_version", return_value="1.7.1"),
            mock.patch.object(t16, "run_dockq", side_effect=successful_run),
            mock.patch.object(t16, "measured_dockq_version", return_value="2.1.3"),
            contextlib.redirect_stdout(stdout),
        ):
            t16.main(
                [
                    str(model),
                    "--native",
                    str(native),
                    "--structure-id",
                    "synth",
                    "--eval-id",
                    "EVAL_t16_fragment",
                    "--subject-ref",
                    "artifact:model",
                    "--reference-subject-ref",
                    "artifact:native",
                    "--bsa-evidence",
                    str(root / "bsa.json"),
                    "--native-chains",
                    "A:B",
                    "--headline-interface-id",
                    "IFACE_IDENTITY",
                    "--mapping",
                    "AB:AB",
                    "--interface-id",
                    "IFACE_IDENTITY",
                    "--raw-json",
                    str(root / "identity.json"),
                    "--mapping",
                    "AB:BA",
                    "--interface-id",
                    "IFACE_SWAPPED",
                    "--raw-json",
                    str(root / "swapped.json"),
                ]
            )

        fragment = yaml.safe_load(stdout.getvalue())
        eval_doc = {
            "structures": [
                {"id": "synth", "method": "xray", "description": "synthetic"}
            ],
            "evaluation_runs": [
                {
                    "id": "EVAL_t16_fragment",
                    "structure_ref": "synth",
                    "run_date": "2026-09-22",
                    "catalog_tasks_applied": ["T16"],
                    "measurements": fragment["measurements"],
                    "interface_qualities": fragment["interface_qualities"],
                }
            ],
        }
        eval_path = root / "eval.yaml"
        eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
        qds = qds_emit.emit_qds(
            [eval_path],
            qds_id="QDS_t16_fragment",
            structure_id="synth",
            subject_ref="artifact:model",
            coverage_scope="partial",
            scope_notes="T16 wrapper integration fixture.",
            issued_at="2026-09-22T10:00:00+00:00",
            emitter_contract_version="2",
        )
        summary = qds["interface_quality_summary"]
        _check(
            summary["interface_dockq_score"]["scope_selector"]
            == "IFACE_IDENTITY",
            "multi-mapping wrapper output emits one selected DockQ headline",
        )
        _check(
            len(summary["interface_qualities"]) == 2,
            "multi-mapping wrapper output survives QDS emission with both controls",
        )
        headline_context = next(
            row
            for row in fragment["interface_qualities"]
            if row["id"] == "IFACE_IDENTITY"
        )
        control_context = next(
            row
            for row in fragment["interface_qualities"]
            if row["id"] == "IFACE_SWAPPED"
        )
        bsa_row = next(
            row
            for row in fragment["measurements"]
            if row["metric_definition_ref"] == "T16_interface_buried_surface_area"
        )
        _check(
            "tool_ref" not in headline_context
            and set(headline_context["evidence_refs"])
            == {"identity.json", "bsa.json"}
            and bsa_row["evidence_refs"] == ["bsa.json"],
            "mixed headline context avoids false single-tool attribution and cites BSA",
        )
        _check(
            control_context["tool_ref"] == "DockQ"
            and control_context["evidence_refs"] == ["swapped.json"],
            "DockQ-only mapping control keeps its truthful single-tool attribution",
        )


def main() -> int:
    test_capri_bands()
    test_extract()
    test_extract_classifies_the_emitted_score()
    test_extract_rejects_unusable_or_mismatched_output()
    test_extract_binds_dockq_inputs_and_all_mapping_representations()
    test_committed_1sar_dockq_evidence_matches_eval()
    test_committed_1sar_bsa_evidence_replays_from_tracked_input()
    test_buried_surface_area()
    test_render_keeps_comparison_provenance()
    test_bsa_selects_declared_interface()
    test_bsa_only_main_retains_content_bound_evidence()
    test_sequence_equivalent_mapping_controls()
    test_imperfect_candidate_native_pairs_are_accepted()
    test_native_homomer_controls_survive_candidate_imperfections()
    test_mapping_controls_are_complete_and_match_bsa_chains()
    test_missing_native_emits_no_partial_yaml()
    test_dockq_failure_leaves_no_partial_evidence()
    test_repeated_mappings_publish_as_one_group()
    test_evidence_publication_failure_rolls_back_whole_group()
    test_native_interface_selection_is_required()
    test_nested_evidence_parent_is_created_before_staging()
    test_headline_interface_selection_is_required()
    test_headline_selection_is_order_independent()
    test_multimapping_fragment_is_qds_emittable()
    print("\nall t16_interface_quality unit tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
