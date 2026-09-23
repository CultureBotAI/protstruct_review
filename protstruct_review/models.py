from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "None"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )

    @model_serializer(mode='wrap', when_used='unless-none')
    def treat_empty_lists_as_none(
            self, handler: SerializerFunctionWrapHandler,
            info: SerializationInfo) -> dict[str, Any]:
        if info.exclude_none:
            _instance = self.model_copy()
            for field, field_info in type(_instance).model_fields.items():
                if getattr(_instance, field) == [] and not(
                        field_info.is_required()):
                    setattr(_instance, field, None)
        else:
            _instance = self
        return handler(_instance, info)



class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'protstruct',
     'default_range': 'string',
     'description': 'LinkML schema for the protstruct_review harness. Models the '
                    'cross-tool oracle trust framework used to evaluate '
                    'agentically refined or generated protein structures: a static '
                    'catalog of routine structural-biology tasks (T01..T17), the '
                    'tools that perform them, the metrics those tools report, the '
                    "per-artifact evaluation runs that record each tool's reading, "
                    'and the per-structure Quality Data Sheet that snapshots the '
                    'cross-tool findings as a citable record.',
     'id': 'https://w3id.org/protstruct-review/schema',
     'imports': ['linkml:types'],
     'license': 'CC-BY-4.0',
     'name': 'protstruct_review',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'protstruct': {'prefix_prefix': 'protstruct',
                                 'prefix_reference': 'https://w3id.org/protstruct-review/schema/'},
                  'schema': {'prefix_prefix': 'schema',
                             'prefix_reference': 'http://schema.org/'}},
     'source_file': 'schemas/protstruct_review.yaml',
     'title': 'Protein Structure Review — oracles, measurements, evaluations, '
              'quality data sheets'} )

class CatalogTaskId(str, Enum):
    """
    Stable identifier for a row in the task catalog.
    """
    T01 = "T01"
    """
    Structure superposition + RMSD
    """
    T02 = "T02"
    """
    Per-residue structural comparison
    """
    T03 = "T03"
    """
    Reciprocal-space refinement (X-ray)
    """
    T04 = "T04"
    """
    Real-space refinement (map-based)
    """
    T05 = "T05"
    """
    Geometry validation
    """
    T06 = "T06"
    """
    Model-vs-data statistics
    """
    T07 = "T07"
    """
    Predicted-model processing
    """
    T08 = "T08"
    """
    Docking predicted/homology model into a map
    """
    T09 = "T09"
    """
    Molecular replacement
    """
    T10 = "T10"
    """
    Ligand fitting
    """
    T11 = "T11"
    """
    Loop / missing-region fitting
    """
    T12 = "T12"
    """
    Map quality assessment (cryo-EM)
    """
    T13 = "T13"
    """
    X-ray data quality assessment
    """
    T14 = "T14"
    """
    Hydrogen placement / protonation
    """
    T15 = "T15"
    """
    Structural/domain classification
    """
    T16 = "T16"
    """
    Interface and assembly quality
    """
    T17 = "T17"
    """
    NMR ensemble/restraint validation
    """


class ToolFamily(str, Enum):
    """
    Source code lineage of a tool. The trust model treats `non_cctbx` as genuinely independent from PHENIX; `cctbx` includes any tool that shares the cctbx/iotbx/mmtbx libraries (PHENIX, mmtbx.* CLI tools).
    """
    cctbx = "cctbx"
    non_cctbx = "non_cctbx"


class Stage(str, Enum):
    """
    Which stage of an artifact a measurement applies to.
    """
    start = "start"
    """
    Pre-refinement / starting model
    """
    intermediate = "intermediate"
    """
    Mid-refinement (round_N)
    """
    final = "final"
    """
    Post-refinement / converged model
    """
    all = "all"
    """
    Applies to the whole dataset (e.g. completeness across all reflections).
    """


class PassStatus(str, Enum):
    """
    Interpretation/status of a measurement: a criterion-bearing outcome, criterion inapplicability, or an informational observation.
    """
    pass_ = "pass"
    """
    Meets the criterion
    """
    fail_criterion = "fail_criterion"
    """
    Fails a declared criterion without asserting disagreement with an agent claim
    """
    fail_by_oracle = "fail_by_oracle"
    """
    Independent oracle disagrees with agent claim and criterion fails
    """
    pass_with_caveat = "pass_with_caveat"
    """
    Criterion passes but a related claim is wrong
    """
    pass_criterion_fail_headline = "pass_criterion_fail_headline"
    """
    Criterion passes but headline number is inaccurate
    """
    fail_by_oracle_within_cctbx = "fail_by_oracle_within_cctbx"
    """
    Two cctbx tools disagree with agent claim — needs a non-cctbx confirmation to harden
    """
    informational = "informational"
    """
    Reported without a declared criterion
    """
    criterion_inapplicable = "criterion_inapplicable"
    """
    A declared criterion cannot grade this row because at least one of its evidence-backed required preconditions is void or unknown.
    """


class CriterionPreconditionStatus(str, Enum):
    """
    Whether a load-bearing precondition for applying a pass criterion was demonstrated on this measurement.
    """
    satisfied = "satisfied"
    """
    The precondition was checked and holds for this row.
    """
    void = "void"
    """
    The precondition fails, so the criterion cannot grade this row.
    """
    unknown = "unknown"
    """
    Available evidence cannot establish the precondition.
    """


class RefinementMethod(str, Enum):
    """
    Experimental / computational method category for a structure.
    """
    xray = "xray"
    cryo_em = "cryo_em"
    predicted_model = "predicted_model"
    nmr = "nmr"


class QdsCoverageScope(str, Enum):
    """
    Whether a QDS is a cumulative sheet or an explicitly bounded partial update.
    """
    cumulative = "cumulative"
    """
    Combines all evaluation runs named in derived_from_evaluation_run_refs.
    """
    partial = "partial"
    """
    Covers only the tasks or measurements declared in scope_notes.
    """


class EvidenceCorrectionAction(str, Enum):
    """
    An append-only withdrawal or replacement of identified source evidence.
    """
    withdraw = "withdraw"
    replace = "replace"


class EvidenceCorrectionCollection(str, Enum):
    """
    Exact source collection or singleton addressed by a correction.
    """
    measurements = "measurements"
    headline_findings = "headline_findings"
    residue_outliers = "residue_outliers"
    density_peaks = "density_peaks"
    flagged_regions = "flagged_regions"
    per_residue_values = "per_residue_values"
    secondary_structure_assignments = "secondary_structure_assignments"
    domain_assignments = "domain_assignments"
    sites = "sites"
    ligands = "ligands"
    interface_qualities = "interface_qualities"
    prediction_ensemble_qualities = "prediction_ensemble_qualities"
    nmr_ensemble_qualities = "nmr_ensemble_qualities"
    pairwise_comparisons = "pairwise_comparisons"
    refinements = "refinements"
    assumptions = "assumptions"
    measurement_assumptions = "measurement_assumptions"
    headline_assumptions = "headline_assumptions"
    cross_tool_waivers = "cross_tool_waivers"
    headline_verdict = "headline_verdict"
    evaluation_run = "evaluation_run"
    tool_recommendations = "tool_recommendations"
    tool_assumptions = "tool_assumptions"


class StructureIdKind(str, Enum):
    """
    Which database scheme the structure id follows.
    """
    pdb = "pdb"
    emdb = "emdb"
    alphafold = "alphafold"


class RecommendationRole(str, Enum):
    """
    Role a tool fills for a given metric. `top_considered` reflects community / literature consensus on the best canonical tool; `top_performing` reflects empirical results within this harness (often the same tool, sometimes not). `alternative` is an acceptable second-line oracle; `deprecated` is kept only for historical reference.
    """
    top_considered = "top_considered"
    top_performing = "top_performing"
    alternative = "alternative"
    deprecated = "deprecated"


class PlddtDistributionShape(str, Enum):
    """
    Coarse classification of the per-residue pLDDT distribution shape. Mean pLDDT alone is insufficient — distribution tells you whether a model is uniformly confident or hides disordered regions.
    """
    bimodal_sharp = "bimodal_sharp"
    """
    Confident core + disordered tails.
    """
    broad = "broad"
    """
    Uncertain throughout (broad spread centred on mid-range).
    """
    narrow_high = "narrow_high"
    """
    Uniformly confident.
    """
    narrow_low = "narrow_low"
    """
    Uniformly uncertain (suspicious).
    """


class ReferenceKind(str, Enum):
    """
    What kind of reference the candidate is being compared against.
    """
    deposited = "deposited"
    """
    A PDB/EMDB deposited entry treated as the gold standard.
    """
    alphafold = "alphafold"
    """
    An AlphaFold/RoseTTAFold prediction used as reference.
    """
    starting_model = "starting_model"
    """
    The model the agent was given to refine.
    """
    ground_truth = "ground_truth"
    """
    A benchmark "truth" (e.g., ultra-high-res reference).
    """
    consensus = "consensus"
    """
    A multi-tool consensus or PDB-REDO style re-refinement.
    """


class DeltaBaseline(str, Enum):
    """
    Which baseline a Δ-metric is measured against.
    """
    starting_model = "starting_model"
    """
    Δ measured against the input / starting model.
    """
    reference_truth = "reference_truth"
    """
    Δ measured against an independent gold standard.
    """
    same_data_reference = "same_data_reference"
    """
    Δ measured against another model refined against the same data.
    """


class ResidueOutlierKind(str, Enum):
    """
    The validation category that flagged a residue. A single residue can have multiple outlier rows (one per kind).
    """
    ramachandran = "ramachandran"
    """
    Backbone φ,ψ outside the 99.95th percentile region (MolProbity Top8000).
    """
    rotamer = "rotamer"
    """
    Residue-specific rotamer OUTLIER classification reported by the validation tool. Allowed and Favored conformations are not outliers.
    """
    c_beta = "c_beta"
    """
    Cβ deviation > 0.25 Å from ideal.
    """
    clash = "clash"
    """
    Steric overlap ≥ 0.4 Å with another atom.
    """
    cablam = "cablam"
    """
    CaBLAM secondary-structure / backbone validation outlier.
    """
    cis_omega = "cis_omega"
    """
    Non-Pro cis-peptide bond.
    """
    bad_geometry = "bad_geometry"
    """
    Bond / angle / planarity outlier > 4σ.
    """
    density_misfit = "density_misfit"
    """
    High RSRZ / poor real-space density agreement.
    """


class FlaggedRegionKind(str, Enum):
    """
    Why a contiguous stretch of residues was flagged.
    """
    disordered = "disordered"
    poor_density = "poor_density"
    clash_dense = "clash_dense"
    loop_misfit = "loop_misfit"
    interface = "interface"
    missing = "missing"
    """
    Residues unmodelled in the deposited structure.
    """


class Severity(str, Enum):
    """
    Coarse severity bucket used by ResidueOutlier and FlaggedRegion. Detailed numeric values live on the associated MeasurementValue.
    """
    low = "low"
    moderate = "moderate"
    severe = "severe"


class AssumptionKind(str, Enum):
    """
    Whether an assumption is documented in the tool's docs / source (explicit) or arises from a default behaviour, threshold, or reference dataset that is not loudly advertised (implicit).
    """
    explicit = "explicit"
    implicit = "implicit"


class AssumptionScope(str, Enum):
    """
    Where the assumption operates: at the tool level (it shapes every number the tool produces); at a single measurement (it shaped this specific value); at the report level (the agent's narrative framing); at aggregation (combining many measurements into one verdict); at interpretation (deriving structural meaning from a number).
    """
    tool = "tool"
    measurement = "measurement"
    report = "report"
    aggregation = "aggregation"
    interpretation = "interpretation"


class AssumptionStatus(str, Enum):
    """
    Whether the assumption has been actively checked. `verified` = cross-tool confirmation showed the assumption holds for this case. `mitigated` = a workaround or independent check is in place. `unchecked` = the assumption is documented but no verification has been run. `known_violation` = the assumption is documented to be wrong for this case (and the affected number should not be taken at face value).
    """
    verified = "verified"
    mitigated = "mitigated"
    unchecked = "unchecked"
    known_violation = "known_violation"


class ContactKind(str, Enum):
    """
    Kind of atom-atom contact recorded by a CoordinationContact row.
    """
    inner_sphere = "inner_sphere"
    """
    Direct (first-shell) coordination contact for a metal ion.
    """
    outer_sphere = "outer_sphere"
    """
    Second-shell contact (water-bridged or longer).
    """
    hydrogen_bond = "hydrogen_bond"
    hydrophobic = "hydrophobic"
    pi_stack = "pi_stack"
    salt_bridge = "salt_bridge"
    van_der_waals = "van_der_waals"


class SiteKind(str, Enum):
    """
    Type of functional / structural site of interest.
    """
    active_site = "active_site"
    binding_site = "binding_site"
    interface = "interface"
    """
    Protein-protein or protein-nucleic acid interface.
    """
    catalytic_residue_set = "catalytic_residue_set"
    metal_coordination = "metal_coordination"
    allosteric_site = "allosteric_site"


class MeasurementScope(str, Enum):
    """
    The granularity at which a metric is measured. Used both on MetricDefinition (the canonical scope of a metric) and on MeasurementValue (the actual scope of a specific measurement — can override the canonical scope when the same metric is reported at a different level, e.g. clashscore restricted to a site's residues is `site`-scoped).
For `residue` and `atom` scope, store every value in the per-residue/per-atom slot and surface the summary statistics (mean, std_dev, min, max, count) on the corresponding scalar slot. The summary fields on TypedMeasurementValue exist for this purpose.
    """
    complex = "complex"
    """
    Whole asymmetric unit / biological assembly.
    """
    chain = "chain"
    """
    One polypeptide / nucleic-acid chain.
    """
    domain = "domain"
    """
    A named structural domain.
    """
    site = "site"
    """
    A named functional site (active site, interface, ...).
    """
    residue = "residue"
    atom = "atom"
    dataset = "dataset"
    """
    Diffraction data / cryo-EM map (not the model).
    """
    ligand = "ligand"
    interface = "interface"
    """
    A named chain-chain or molecule-molecule interface.
    """
    ensemble = "ensemble"
    """
    An NMR or prediction ensemble.
    """
    assembly = "assembly"
    """
    Biological assembly or multimeric complex.
    """
    cohort = "cohort"
    """
    A preregistered collection of structures aggregated into one measurement. Use scope_selector to name the exact cohort; do not use this scope for a result computed on one structure.
    """



class Container(ConfiguredBaseModel):
    """
    Tree root. A single YAML document can carry any subset of the catalog and per-run records. Nothing is required at this level — pass the sub-collections you have.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema', 'tree_root': True})

    catalog_tasks: Optional[list[CatalogTask]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    tools: Optional[list[Tool]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    metric_definitions: Optional[list[MetricDefinition]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    structures: Optional[list[Structure]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    experimental_data: Optional[list[ExperimentalData]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    agent_artifacts: Optional[list[AgentArtifact]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    evaluation_runs: Optional[list[EvaluationRun]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    quality_data_sheets: Optional[list[QualityDataSheet]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    qds_replay_pins: Optional[list[QdsReplayPin]] = Field(default=[], description="""Source-owned content pins for immutable QDS artifacts. Validation replays a retained emitter contract against source-owned snapshots and compares the result with a stable canonical byte projection, without reading the current emitter, catalog, or registries.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    qds_emission_contexts: Optional[list[QdsEmissionContext]] = Field(default=[], description="""Source-owned recipes for contract-3 partial-QDS identity, scope, and headline prose. These records prevent stale run-level summaries from being concatenated into a current partial sheet and are content-pinned alongside the replay boundary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    tool_recommendations: Optional[list[ToolRecommendation]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    pairwise_comparisons: Optional[list[PairwiseComparison]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'QualityDataSheet']} })
    residues: Optional[list[ResidueRef]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container']} })
    secondary_structure_assignments: Optional[list[SecondaryStructureAssignment]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })
    domain_assignments: Optional[list[DomainAssignment]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })
    sites: Optional[list[Site]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun']} })
    interface_qualities: Optional[list[InterfaceQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'InterfaceQualitySummary']} })
    nmr_ensemble_qualities: Optional[list[NmrEnsembleQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'NmrValidationSummary']} })
    prediction_ensemble_qualities: Optional[list[PredictionEnsembleQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'PredictionEnsembleSummary']} })
    ligands: Optional[list[Ligand]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun']} })
    assumptions: Optional[list[Assumption]] = Field(default=[], description="""Container-level Assumption catalog. Used as a lookup target when a Tool's assumptions[] block needs to reference a shared assumption rather than inline it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container',
                       'Tool',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun']} })


class Finding(ConfiguredBaseModel):
    """
    Shared shape between per-row measurements and headline collapses — both ultimately tie a (catalog_task, metric, oracle_tool) tuple to a number plus optional notes.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema', 'mixin': True})

    metric_definition_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    oracle_tool_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    oracle_family: ToolFamily = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class SourceRowLineage(ConfiguredBaseModel):
    """
    Exact EvaluationRun row copied into a nonlegacy QDS.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema', 'mixin': True})

    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class CatalogTask(ConfiguredBaseModel):
    """
    One row in the T01..T17 task catalog.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: CatalogTaskId = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    task_name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    phenix_tool_refs: Optional[list[str]] = Field(default=[], description="""PHENIX tools that primarily implement this task.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    phenix_doc_paths: Optional[list[str]] = Field(default=[], description="""Upstream PHENIX documentation routes, resolvable online or in the optional ignored local cache created by ref/download_phenix_docs.sh.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    oracle_tool_refs: Optional[list[str]] = Field(default=[], description="""Independent (typically non-cctbx) oracles the harness uses to grade this task.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    metric_definition_refs: Optional[list[str]] = Field(default=[], description="""Metrics this task is expected to produce.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    inputs_description: Optional[str] = Field(default=None, description="""Human prose describing typical inputs (file types, optional flags).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    gold_standard: Optional[str] = Field(default=None, description="""Source of truth (deposition, paper, cross-tool consensus).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })
    example_dataset: Optional[str] = Field(default=None, description="""A concrete dataset id (PDB/EMDB/MTZ) so a run is reproducible.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask']} })


class Tool(ConfiguredBaseModel):
    """
    A program executable — PHENIX entry point or external oracle.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""Canonical tool name (e.g. phenix.superpose_models, TMalign, gemmi, probe, reduce, servalcat).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    version: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Tool']} })
    install_path: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Tool']} })
    family: ToolFamily = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Tool']} })
    catalog_tasks_served: Optional[list[CatalogTaskId]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Tool']} })
    assumptions: Optional[list[Assumption]] = Field(default=[], description="""Implicit and explicit assumptions baked into this tool's default behaviour: reference distribution, scaling model, hyper-parameter defaults, etc. Surfaced into the QDS via measurement.oracle_tool_ref → tool.assumptions.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container',
                       'Tool',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun']} })


class MetricDefinition(ConfiguredBaseModel):
    """
    A named numeric deliverable that one or more tools can produce.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition']} })
    unit: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition', 'TypedMeasurementValue']} })
    description: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'Structure',
                       'IdentityBlock',
                       'Assumption',
                       'Site']} })
    applicable_task_refs: Optional[list[CatalogTaskId]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition']} })
    scope: Optional[MeasurementScope] = Field(default=None, description="""Canonical granularity for this metric. `complex` for whole-structure metrics like global R-free; `residue` for per-residue lDDT or RSRZ; `dataset` for crystallographic completeness and CC½; `chain` for per-chain lDDT means; `site` for site-restricted metrics; `ligand` for ligand quality. A specific MeasurementValue may override this.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })


class Structure(ConfiguredBaseModel):
    """
    A protein structure target (model only — see ExperimentalData for the data side).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""PDB id (e.g. 1sar), EMDB id (EMDB-11668), or AlphaFold accession (af-p00698-f1).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    id_kind: Optional[StructureIdKind] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure']} })
    method: Optional[RefinementMethod] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    resolution_a: Optional[float] = Field(default=None, description="""Best resolution in Ångström, where applicable.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    space_group: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    description: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'Structure',
                       'IdentityBlock',
                       'Assumption',
                       'Site']} })


class ExperimentalData(ConfiguredBaseModel):
    """
    Reflection data, half-maps, or similar — the data side of an experiment.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    kind: Optional[str] = Field(default=None, description="""One of mtz, half_maps, map.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData',
                       'FlaggedRegion',
                       'Assumption',
                       'CoordinationContact',
                       'Site']} })
    attached_to_structure_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData']} })
    file_paths: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData']} })


class AgentArtifact(ConfiguredBaseModel):
    """
    A bundle of files an agent produced for one structure.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""Full UUID of the agent run, or any other stable id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    short_id: Optional[str] = Field(default=None, description="""First 8 hex chars of the UUID (matches eval-naming convention).""", json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact']} })
    structure_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    agent_provider: Optional[str] = Field(default=None, description="""e.g. coscientists.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact']} })
    agent_system: Optional[str] = Field(default=None, description="""e.g. openscientist.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact']} })
    output_files: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact']} })


class Refinement(ConfiguredBaseModel):
    """
    One round of model improvement. Carries the per-round metrics (R-work/R-free/gap/clashscore/Rama outliers/waters/mean B) that a multi-round refinement campaign produces. The QDS does not surface every round directly; it surfaces the trajectory and the final-round numbers via the geometry / refinement summaries.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    round_number: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    stage_label: Optional[str] = Field(default=None, description="""Optional human label for this round (\"start\", \"round_2\", \"round_3_clean\", \"final\") — useful when round_number is not contiguous.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    model_file: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    mtz_file: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    evaluation_run_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    r_work: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    r_free: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    r_free_gap: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    clashscore: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    ramachandran_outliers_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    ramachandran_favored_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    rotamer_outliers_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    molprobity_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    waters_count: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    mean_b_factor: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'SiteQuality']} })
    total_atoms: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })
    key_change: Optional[str] = Field(default=None, description="""One-line summary of what changed in this round (e.g. \"+ Ca²⁺\", \"NQH flips\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement']} })


class MeasurementProvenance(ConfiguredBaseModel):
    """
    Audit trail for a measurement (optional at v0).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    command: Optional[str] = Field(default=None, description="""Exact CLI invocation (excluding interactive arguments).""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementProvenance']} })
    tool_version: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementProvenance']} })
    input_sha256: Optional[list[str]] = Field(default=[], description="""SHA-256 of each input file, in invocation order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementProvenance']} })
    run_at: Optional[datetime ] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementProvenance']} })


class CriterionPreconditionCheck(ConfiguredBaseModel):
    """
    One evidence-backed check of a threshold-registry precondition. Binding definitions name required ids. A verdict row must satisfy each one; criterion_inapplicable instead retains all checks and marks at least one required check void or unknown.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    status: CriterionPreconditionStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck', 'Assumption']} })
    evidence_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class MeasurementValue(Finding):
    """
    One oracle's reading of one metric at one stage on one artifact.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['Finding']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    catalog_task_ref: CatalogTaskId = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    stage: Stage = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    scope: Optional[MeasurementScope] = Field(default=None, description="""Granularity of this specific measurement. Optional override of the canonical `scope` on the referenced MetricDefinition. When set, the `agent_claim` / `oracle_measure` may be a summary (mean+SD over a residue/chain/site array) — see TypedMeasurementValue.mean / std_dev / count. `cohort` means that the value aggregates an explicitly named preregistered collection of structures rather than measuring one structure.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    scope_selector: Optional[str] = Field(default=None, description="""When `scope` is `chain`, `site`, `residue`, `atom`, or `ligand`, this is a free-text selector identifying what was measured (e.g. \"chain A residues 30-45\", \"active site 1\", \"Asn A 39\"). Site / residue selectors should also have a structured ResidueRef / Site reference where appropriate. For `site` and `ligand` scope this value is the exact declared Site or Ligand id; put comparison qualifiers and human-readable detail in `notes`. For `cohort` scope it is required and names the exact preregistered cohort.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    subject_ref: Optional[str] = Field(default=None, description="""Stable identifier for the concrete model, dataset, assembly, or cohort measured. This is distinct from scope_selector: the subject identifies the artefact, while the selector identifies a chain, interface mapping, site, or other subset within it. QDS emission uses an exact subject match ahead of legacy rows where this field is absent and excludes explicit non-matches.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, description="""Stable identifier for the native/reference artefact used by a comparative measurement. Required by the T16 wrapper whenever DockQ is reported.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    metric_definition_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    oracle_tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    oracle_family: Optional[ToolFamily] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    agent_claim: Optional[TypedMeasurementValue] = Field(default=None, description="""Value reported by the agent.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'HeadlineFinding']} })
    oracle_measure: Optional[TypedMeasurementValue] = Field(default=None, description="""Value the independent oracle returned.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'HeadlineFinding']} })
    delta: Optional[TypedMeasurementValue] = Field(default=None, description="""Optional pre-computed difference. Unless delta_from_measurement_ref is present, this is oracle − agent or post − pre. When delta_from_measurement_ref is present, this is this row's oracle_measure minus the referenced MeasurementValue's oracle_measure.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    delta_from_measurement_ref: Optional[str] = Field(default=None, description="""Same-EvaluationRun comparison row used for an oracle-versus-oracle delta. The two rows must share task, metric, stage, subject, reference subject, scope, and selector; delta equals this row's oracle_measure minus the referenced row's oracle_measure.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    derived_from_measurement_refs: Optional[list[str]] = Field(default=[], description="""Same-EvaluationRun source measurements used to compute a composite measurement in the same subject, reference-subject, stage, scope, and selector context. These typed lineage refs identify every contributing row; they do not replace retained raw evidence.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    pass_criterion: Optional[str] = Field(default=None, description="""Complete normalized display snapshot of the authoritative table cell selected by pass_criterion_ref. Numeric threshold authority remains in ref/thresholds_and_standards.md. Retain this snapshot both for a verdict and when criterion_inapplicable documents why the declared rule could not grade the row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    pass_criterion_ref: Optional[str] = Field(default=None, description="""PassCriterionBinding id in ref/structural_criteria.yaml. For a verdict row the binding's metric and structured applicability must match the measurement. The binding points to the canonical threshold registry; it does not duplicate threshold values into the catalog.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    criterion_preconditions: Optional[list[CriterionPreconditionCheck]] = Field(default=[], description="""Structured applicability checks required by pass_criterion_ref. A verdict is valid only when every precondition required by the binding is present exactly once, marked satisfied, and backed by non-circular retained evidence. criterion_inapplicable instead requires at least one required check to be evidence-backed void or unknown.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    pass_status: Optional[PassStatus] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    provenance_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue']} })
    bundle_ref: Optional[str] = Field(default=None, description="""Stable invocation/bundle id shared by coupled measurements that must be selected and interpreted together.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    evidence_refs: Optional[list[str]] = Field(default=[], description="""Retained raw outputs or EvaluationRun ids supporting this measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    assumptions: Optional[list[Assumption]] = Field(default=[], description="""Assumptions specific to this measurement (parameter choices that differ from tool defaults, interpretive flags, etc.). Tool-level assumptions are NOT duplicated here; the QDS report aggregates both via the oracle_tool_ref join.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container',
                       'Tool',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun']} })


class TypedMeasurementValue(ConfiguredBaseModel):
    """
    A typed carrier for one measurement value. Exactly one of {value_numeric, value_text, is_not_applicable=true} should be set — enforced semantically by the loader, not by a LinkML rule (LinkML `rules:` for cross-slot constraints are not honoured by all validators in 1.9; see scripts/tsv_to_records.py for the canonical cell parser that always produces a valid combination). On source MeasurementValue.agent_claim/oracle_measure/delta, QDS lineage and verdict attributes from this reusable class are forbidden; those remain on the parent source row.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    value_numeric: Optional[float] = Field(default=None, description="""Numeric value when the cell is a clean number.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    value_text: Optional[str] = Field(default=None, description="""Non-numeric textual value (ranges like \"49.97 → 2.50\", counts with annotation like \"1 (Asn A 39)\", percentages, or any cell that is not a clean number).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    unit: Optional[str] = Field(default=None, description="""Unit string (Å, °, %, σ, count). Optional.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition', 'TypedMeasurementValue']} })
    is_not_applicable: Optional[bool] = Field(default=None, description="""True when the source cell is \"n/a\" or otherwise has no measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    percentile: Optional[float] = Field(default=None, description="""Optional rank against a reference distribution (e.g., wwPDB archive percentile for clashscore at this resolution; CASP ranking for TM-score). Range 0-100. Cite the source dataset in `notes` on the parent measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    mean: Optional[float] = Field(default=None, description="""Mean across an array of values. Populated when the measurement summarises a per-residue / per-atom / per-chain distribution. The full array of underlying values lives in a sibling list slot (e.g. PerResidueQuality.lddt_per_residue).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    std_dev: Optional[float] = Field(default=None, description="""Standard deviation paired with `mean`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    min_value: Optional[float] = Field(default=None, description="""Minimum across the array (paired with `mean`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    max_value: Optional[float] = Field(default=None, description="""Maximum across the array (paired with `mean`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    count: Optional[int] = Field(default=None, description="""Number of observations underlying this value (for example, the eligible denominator for a count or rate, or the values summarised by `mean`/`std_dev`). Required when `mean` is set.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue']} })
    source_measurement_ref: Optional[str] = Field(default=None, description="""MeasurementValue id from which this QDS scalar was selected.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue', 'MeasurementEvidenceOrigin']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun id containing source_measurement_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    metric_definition_ref: Optional[str] = Field(default=None, description="""Canonical metric carried through when a QDS wraps a measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    oracle_tool_ref: Optional[str] = Field(default=None, description="""Tool that produced the selected QDS scalar.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    oracle_family: Optional[ToolFamily] = Field(default=None, description="""Independent-family classification of oracle_tool_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    pass_status: Optional[PassStatus] = Field(default=None, description="""Interpretation assigned by the source measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    pass_criterion: Optional[str] = Field(default=None, description="""Display snapshot of the source criterion, when any. Resolve source_measurement_ref to obtain its PassCriterionBinding and the source row's full verdict context.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete measured subject carried through from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, description="""Native/reference subject carried through from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    stage: Optional[Stage] = Field(default=None, description="""Measurement stage carried through from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    scope: Optional[MeasurementScope] = Field(default=None, description="""Measurement scope carried through from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    scope_selector: Optional[str] = Field(default=None, description="""Subset or comparison selector carried through from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    evidence_refs: Optional[list[str]] = Field(default=[], description="""Retained raw outputs or EvaluationRun ids carried from the source row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    bundle_ref: Optional[str] = Field(default=None, description="""Coupled source-measurement bundle id carried through verbatim.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'TypedMeasurementValue']} })
    notes: Optional[str] = Field(default=None, description="""Source caveats and interpretation carried through verbatim.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class HeadlineFinding(Finding):
    """
    A collapsed top-level finding for one EvaluationRun — typically one row per major metric, picking the strongest oracle (most independent) and pointing back at the supporting per-row MeasurementValues.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['Finding']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    catalog_task_refs: list[CatalogTaskId] = Field(default=..., description="""One or more catalog tasks this finding spans (e.g. T03 + T06 for R-factor).""", json_schema_extra = { "linkml_meta": {'domain_of': ['HeadlineFinding']} })
    metric_definition_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    oracle_tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    oracle_family: Optional[ToolFamily] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding']} })
    agent_claim: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'HeadlineFinding']} })
    oracle_measure: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue', 'HeadlineFinding']} })
    verdict_label: Optional[str] = Field(default=None, description="""Free-text label such as \"confirms\", \"off_by_0.015\", \"fails_<_0.05_criterion\". Not an enum at v0 — the label space is still settling.""", json_schema_extra = { "linkml_meta": {'domain_of': ['HeadlineFinding']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    supporting_measurement_refs: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['HeadlineFinding']} })
    assumptions: Optional[list[Assumption]] = Field(default=[], description="""Explicit validity assumptions carried by this headline finding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container',
                       'Tool',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun']} })


class EvaluationRun(ConfiguredBaseModel):
    """
    One full evaluation pass over one AgentArtifact.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""Unconstrained string. The eval_naming.md filename convention (EVAL_<structure>_<artifact-short-id>_<YYYY-MM-DD>) lives on eval_filename_stem, not here.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    eval_filename_stem: Optional[str] = Field(default=None, description="""Filename stem matching ref/eval_naming.md.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    artifact_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    run_date: date = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    catalog_tasks_applied: list[CatalogTaskId] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    measurements: Optional[list[MeasurementValue]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    corrections: Optional[list[EvidenceCorrection]] = Field(default=[], description="""Append-only corrections to identified evidence in earlier source runs. Contract 4 projects these operations before selection, coverage and presentation; historical source carriers are never rewritten.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    cross_tool_waivers: Optional[list[CrossToolWaiver]] = Field(default=[], description="""Claim-scoped exceptions to the no-cctbx-only invariant (#315), declared here so the admission travels with the evidence it excuses. A task-only legacy waiver is unambiguous only when exactly one claim for that task is gated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'QualityDataSheet']} })
    headline_findings: Optional[list[HeadlineFinding]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    residue_outliers: Optional[list[ResidueOutlier]] = Field(default=[], description="""Per-residue outlier rows for this eval. The QDS emitter aggregates these into PerResidueQuality.outliers[]. When this list is non-empty, the QDS MUST surface a PerResidueQuality block.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    density_peaks: Optional[list[DensityPeak]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'PerResidueQuality']} })
    flagged_regions: Optional[list[FlaggedRegion]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'PerResidueQuality']} })
    per_residue_values: Optional[list[PerResidueValue]] = Field(default=[], description="""Per-residue scalars (lDDT, displacement, RSRZ, ...). The metric_definition_ref attached to the underlying value determines which PerResidueQuality slot they feed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    secondary_structure_assignments: Optional[list[SecondaryStructureAssignment]] = Field(default=[], description="""DSSP/STRIDE-style secondary-structure assignment rows. When an eval reports scope=domain/classification content, these rows make the assignment explicit instead of burying it in prose.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })
    domain_assignments: Optional[list[DomainAssignment]] = Field(default=[], description="""Domain and fold-classification rows from CATH/SCOPe/ECOD or equivalent tools. Domain-scoped measurements should point at one of these via scope_selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })
    sites: Optional[list[Site]] = Field(default=[], description="""Functional sites declared on this eval's structure. Site- scoped measurements (scope=site) reference these via scope_selector. When the eval has scope=site measurements but no Site declared here, the emitter fails-hard.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun']} })
    ligands: Optional[list[Ligand]] = Field(default=[], description="""Ligands referenced by sites. Same fail-hard contract as sites: scope=ligand measurement implies a Ligand row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun']} })
    interface_qualities: Optional[list[InterfaceQuality]] = Field(default=[], description="""Interface/assembly rows. Interface-scoped measurements should identify one of these rows via scope_selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'InterfaceQualitySummary']} })
    nmr_ensemble_qualities: Optional[list[NmrEnsembleQuality]] = Field(default=[], description="""NMR ensemble/restraint validation rows. Ensemble-scoped NMR measurements should identify one of these rows via scope_selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'NmrValidationSummary']} })
    prediction_ensemble_qualities: Optional[list[PredictionEnsembleQuality]] = Field(default=[], description="""Prediction ensemble convergence rows for AlphaFold/ColabFold/ RoseTTAFold-style replicate ensembles. Ensemble-scoped predicted-model measurements should identify one of these rows via scope_selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'PredictionEnsembleSummary']} })
    pairwise_comparisons: Optional[list[PairwiseComparison]] = Field(default=[], description="""Pair comparisons against reference structures (deposited / starting / AlphaFold / truth). The QDS surfaces these unchanged via QualityDataSheet.pairwise_comparisons.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'QualityDataSheet']} })
    refinements: Optional[list[Refinement]] = Field(default=[], description="""Per-round refinement trajectory. One Refinement record per round (start / round_1 / round_2 / ... / final). Carries the per-round R-factors, geometry, water count, mean B etc. so the agent's per-round table can be independently re-measured and stored in canonical form.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    criteria_met_count: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    criteria_total: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    assumptions: Optional[list[Assumption]] = Field(default=[], description="""Run-level assumptions — typically the agentic-framework's reporting / interpretation / aggregation conventions (e.g. \"R-factors read from refine in-run log, not re-derived\"). The QDS surfaces these alongside tool and measurement assumptions in assumptions_report[].""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container',
                       'Tool',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun']} })
    superseded_assumption_refs: Optional[list[str]] = Field(default=[], description="""Assumption ids from earlier input EvaluationRuns that this run explicitly withdraws. The QDS emitter omits those ids from a cumulative assumptions_report; the superseding run's own evidence and headline must explain why.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun']} })
    headline_verdict: Optional[str] = Field(default=None, description="""One-paragraph human summary of the eval outcome.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'QdsEmissionContext', 'QualityDataSheet']} })


class EvidenceCorrection(ConfiguredBaseModel):
    """
    A typed, content-addressed operation owned by a later EvaluationRun. target_collection plus target_evaluation_run_ref and target_ref identifies one exact raw source value. Replacement evidence is a separately declared row of the same class owned by the correcting run; withdrawals have no replacement_ref. A correction never changes the original source bytes. A MeasurementValue replacement corrects existing evidence and inherits its exact oldest target's declared run date for recency; publication is not a new measurement. Record genuinely new execution as a new standalone MeasurementValue, optionally withdrawing obsolete evidence separately.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    action: EvidenceCorrectionAction = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    target_collection: EvidenceCorrectionCollection = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    target_evaluation_run_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    target_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    target_sha256: str = Field(default=..., description="""Canonical SHA-256 of the exact raw source target, before projection.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    replacement_ref: Optional[str] = Field(default=None, description="""Required only for replace; resolves in the correcting source run.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection']} })
    reason: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection', 'CrossToolWaiver']} })
    evidence_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })

    @field_validator('target_sha256')
    def pattern_target_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid target_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid target_sha256 format: {v}"
            raise ValueError(err_msg)
        return v


class MeasurementEvidenceOrigin(ConfiguredBaseModel):
    """
    Contract-4 derived audit lineage for one active MeasurementValue, whether or not selected as a summary scalar. Original ownership follows the exact validated measurement-replacement chain, including withdrawn predecessors. The correcting row keeps its new source identity. The original run's declared date governs evidence recency and original ownership also governs coupled-bundle coherence; it is not proof of the actual execution date.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    source_evaluation_run_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_measurement_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['TypedMeasurementValue', 'MeasurementEvidenceOrigin']} })
    origin_evaluation_run_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementEvidenceOrigin']} })
    origin_measurement_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementEvidenceOrigin']} })
    origin_run_date: date = Field(default=..., description="""Original owning EvaluationRun.run_date, not the correction date or a verified tool-execution timestamp. A non-replacement row is its own origin. Optional unresolved MeasurementProvenance.run_at does not override this source-record ordering proxy.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementEvidenceOrigin']} })


class ModelDatasetAssociation(ConfiguredBaseModel):
    """
    Explicit evidence-backed admission of dataset measurements to a model-subject QDS without relabelling the measured subject. Contract 4 admits only T13, stage all, scope dataset rows from the named owning source run, with an exact scope selector listed here. The retained repository-relative MTZ path must match dataset_sha256 and the mtz:sha256:<digest> dataset subject.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    model_subject_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation']} })
    dataset_subject_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation']} })
    dataset_path: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation']} })
    dataset_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation']} })
    owner_evaluation_run_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation', 'QdsEmissionContext']} })
    catalog_task_ref: CatalogTaskId = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    stage: Stage = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    scope: MeasurementScope = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    scope_selectors: list[str] = Field(default=..., description="""Exact admitted column selector or all-input-reflections selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation']} })
    evidence_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })

    @field_validator('dataset_sha256')
    def pattern_dataset_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid dataset_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid dataset_sha256 format: {v}"
            raise ValueError(err_msg)
        return v


class QdsEmissionContext(ConfiguredBaseModel):
    """
    Source-owned, QDS-specific presentation and scope recipe. It binds one immutable sheet to the exact ordered EvaluationRuns, structure, subject, issue time, coverage boundary, identity description, and headline used by emitter contract 3 (partial sheets) or 4 (all sheets). Contract 4 also names the snapshot owner, corrected sheets and dataset associations; source evidence changes only through typed EvidenceCorrection operations.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    qds_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QdsReplayPin']} })
    owner_evaluation_run_ref: str = Field(default=..., description="""The one EvaluationRun whose canonical source document owns this context.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ModelDatasetAssociation', 'QdsEmissionContext']} })
    snapshot_owner_evaluation_run_ref: Optional[str] = Field(default=None, description="""Required by contract 4 and equal to owner_evaluation_run_ref. Its source carrier owns the complete Structure, Tool, recommendation and assumption snapshots used to interpret all declared source runs, including history.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext']} })
    corrected_qds_refs: Optional[list[str]] = Field(default=[], description="""Earlier immutable sheets explicitly corrected by this new sheet.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    dataset_associations: Optional[list[ModelDatasetAssociation]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    subject_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    source_evaluation_run_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QdsReplayPin']} })
    issued_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    coverage_scope: QdsCoverageScope = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    scope_notes: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    identity_description: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext']} })
    headline_verdict: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'QdsEmissionContext', 'QualityDataSheet']} })


class QdsReplayPin(ConfiguredBaseModel):
    """
    Content-addressed replay boundary stored with the source EvaluationRun. The output hash is authoritative for canonical bytes. The remaining hashes bind the retained emitter implementation and source-owned Tool, recommendation, and assumption snapshots used for deterministic replay; live registries and the live catalog are deliberately excluded.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    qds_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QdsReplayPin']} })
    source_evaluation_run_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QdsReplayPin']} })
    qds_emission_context_ref: Optional[str] = Field(default=None, description="""Required for partial contract-3 and every contract-4 replay boundary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    emitter_contract_version: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin', 'QualityDataSheet']} })
    canonical_qds_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    emitter_source_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_tools_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_tool_recommendations_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_tool_assumptions_sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_qds_emission_context_sha256: Optional[str] = Field(default=None, description="""Canonical digest of the source-owned QdsEmissionContext snapshot. Required for partial contract-3 and every contract-4 replay boundary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_evaluation_runs_sha256: Optional[str] = Field(default=None, description="""Required by contract 4; binds all raw source runs, including withdrawn evidence.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })
    source_structures_sha256: Optional[str] = Field(default=None, description="""Required by contract 4; binds the source-owned Structure snapshot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin']} })

    @field_validator('canonical_qds_sha256')
    def pattern_canonical_qds_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid canonical_qds_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid canonical_qds_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('emitter_source_sha256')
    def pattern_emitter_source_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid emitter_source_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid emitter_source_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_tools_sha256')
    def pattern_source_tools_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_tools_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_tools_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_tool_recommendations_sha256')
    def pattern_source_tool_recommendations_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_tool_recommendations_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_tool_recommendations_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_tool_assumptions_sha256')
    def pattern_source_tool_assumptions_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_tool_assumptions_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_tool_assumptions_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_qds_emission_context_sha256')
    def pattern_source_qds_emission_context_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_qds_emission_context_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_qds_emission_context_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_evaluation_runs_sha256')
    def pattern_source_evaluation_runs_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_evaluation_runs_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_evaluation_runs_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('source_structures_sha256')
    def pattern_source_structures_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid source_structures_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid source_structures_sha256 format: {v}"
            raise ValueError(err_msg)
        return v


class QualityDataSheet(ConfiguredBaseModel):
    """
    Per-structure citable snapshot of cross-tool findings. Generated from one or more EvaluationRun records by scripts/qds_emit.py and treated as immutable: when oracles change or new measurements arrive, emit a new QDS (different id / issued_at), don't mutate the old one.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""e.g. QDS_1sar_cdba2c07_2026-04-24""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact summarized by the selected scalar values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    derived_from_evaluation_run_refs: list[str] = Field(default=..., description="""Complete ordered audit lineage, including withdrawn and correction-only runs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    active_evaluation_run_refs: Optional[list[str]] = Field(default=[], description="""Contract-4 subset of audit inputs with subject-eligible active evidence.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    applied_corrections: Optional[list[EvidenceCorrection]] = Field(default=[], description="""Exact source-owned correction operations applied by contract 4.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    measurement_evidence_origins: Optional[list[MeasurementEvidenceOrigin]] = Field(default=[], description="""Exact derived origin and declared source-record date for every active scalar measurement in contract 4. Distinguishes an observation's original record from its current correction carrier without claiming a new scientific execution.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    dataset_associations: Optional[list[ModelDatasetAssociation]] = Field(default=[], description="""Exact validated source-context associations used for contract-4 admission.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    corrected_qds_refs: Optional[list[str]] = Field(default=[], description="""Earlier immutable sheets named in the source-owned contract-4 context.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    emission_context_ref: Optional[str] = Field(default=None, description="""Source-owned recipe required by partial contract 3 and every contract-4 sheet.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    coverage_scope: Optional[QdsCoverageScope] = Field(default=None, description="""Cumulative sheet or explicitly bounded partial update.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    scope_notes: Optional[str] = Field(default=None, description="""Human-readable boundary or carry-forward statement for coverage_scope.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    issued_at: datetime  = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['QdsEmissionContext', 'QualityDataSheet']} })
    emitter_contract_version: Optional[str] = Field(default=None, description="""Versioned qds_emit selection/routing contract used to build this immutable sheet. Modern committed sheets must declare a supported version so later emitter changes cannot silently redefine replay.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QdsReplayPin', 'QualityDataSheet']} })
    identity_block: Optional[IdentityBlock] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    geometry_summary: Optional[GeometrySummary] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    refinement_summary: Optional[RefinementSummary] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    map_summary: Optional[MapSummary] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    data_quality_summary: Optional[DataQualitySummary] = Field(default=None, description="""X-ray data quality (completeness, ⟨I/σ⟩, CC½). Optional; omit for cryo-EM and predicted models.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    predicted_confidence_summary: Optional[PredictedConfidenceSummary] = Field(default=None, description="""AlphaFold/RoseTTAFold confidence (pLDDT distribution, PAE). Optional; only for predicted models.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    packing_summary: Optional[PackingSummary] = Field(default=None, description="""Optional packing and buried-H-bond diagnostics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    classification_summary: Optional[ClassificationSummary] = Field(default=None, description="""Optional secondary-structure/domain/fold classification snapshot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    interface_quality_summary: Optional[InterfaceQualitySummary] = Field(default=None, description="""Optional interface and assembly-quality snapshot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    prediction_ensemble_summary: Optional[PredictionEnsembleSummary] = Field(default=None, description="""Optional prediction ensemble convergence snapshot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    nmr_validation_summary: Optional[NmrValidationSummary] = Field(default=None, description="""Optional NMR restraint and ensemble validation snapshot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    pairwise_comparisons: Optional[list[PairwiseComparison]] = Field(default=[], description="""One per relevant reference (deposited / starting / AlphaFold / truth). Empty when no reference comparison applies.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'QualityDataSheet']} })
    per_residue_quality: Optional[PerResidueQuality] = Field(default=None, description="""Residue-scoped local quality (per-residue lDDT/displacement, outlier residues, density-difference peaks, flagged regions). Required when the trust model needs evidence that local regions — especially active sites and interfaces — are not worse than the global average.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    site_qualities: Optional[list[SiteQuality]] = Field(default=[], description="""One per active site / binding site / interface / metal site on this structure. Each carries the site-scoped metrics (site RMSD to reference, mean per-residue lDDT, ligand quality if a ligand is bound). Empty when the structure has no functional site of record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    cross_tool_waivers: Optional[list[CrossToolWaiver]] = Field(default=[], description="""Claim-scoped waivers inherited from the source evals (#315), surfaced so a QDS reader sees each admission next to the one coverage row it excuses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'QualityDataSheet']} })
    cross_tool_coverage: Optional[CrossToolCoverage] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    tool_recommendations_applied: Optional[list[ToolRecommendation]] = Field(default=[], description="""Snapshot of which recommendations were active at issue time. The QDS is immutable; recommendations evolve, so this captures the recommendations as-of issued_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    assumptions_report: Optional[list[Assumption]] = Field(default=[], description="""Aggregated tool / measurement / framework assumptions that shaped this QDS. Built by qds_emit.py from tool.assumptions[] (joined via measurement.oracle_tool_ref) + measurement.assumptions[] + eval_run.assumptions[]. Anyone citing this QDS sees the full inferential basis without having to dig into per-tool docs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['QualityDataSheet']} })
    headline_verdict: Optional[str] = Field(default=None, description="""One-paragraph pinned summary as of issued_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'QdsEmissionContext', 'QualityDataSheet']} })


class IdentityBlock(ConfiguredBaseModel):
    """
    Identity facts about the structure being evaluated.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    pdb_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['IdentityBlock']} })
    emdb_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['IdentityBlock']} })
    alphafold_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['IdentityBlock']} })
    method: Optional[RefinementMethod] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    resolution_a: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    space_group: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Structure', 'IdentityBlock']} })
    description: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'Structure',
                       'IdentityBlock',
                       'Assumption',
                       'Site']} })


class GeometrySummary(ConfiguredBaseModel):
    """
    Headline geometry numbers as of QDS issue date.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    clashscore: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    ramachandran_outliers_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    ramachandran_favored_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    rotamer_outliers_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    molprobity_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'GeometrySummary']} })
    bond_rmsd_a: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    angle_rmsd_deg: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    bond_rmsz: Optional[TypedMeasurementValue] = Field(default=None, description="""Bond-length RMSZ (Z-score against restraint targets). Over- refinement diagnostic — a model with small absolute RMSD can still be a high-Z outlier relative to its restraints. See ref/quality_reporting.md §1.2.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    angle_rmsz: Optional[TypedMeasurementValue] = Field(default=None, description="""Bond-angle RMSZ (Z-score against restraint targets). Same over-refinement diagnostic as bond_rmsz.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    cbeta_deviations_count: Optional[TypedMeasurementValue] = Field(default=None, description="""Number of Cβ-deviation outliers (> 0.25 Å from ideal).""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    ramachandran_z_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Ramachandran-Z distribution score against a high-resolution reference.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary']} })
    packing_z_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Packing-quality Z-score against a structural reference distribution.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary', 'PackingSummary']} })
    unsatisfied_buried_hbond_count: Optional[TypedMeasurementValue] = Field(default=None, description="""Count of buried polar groups lacking a satisfying hydrogen bond.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary', 'PackingSummary']} })


class RefinementSummary(ConfiguredBaseModel):
    """
    Headline R-factors as of QDS issue date (X-ray refinement only).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    r_work: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    r_free: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    r_free_gap: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'RefinementSummary']} })
    r_free_trajectory_stability: Optional[TypedMeasurementValue] = Field(default=None, description="""Stability of the R-free trajectory across refinement rounds.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RefinementSummary']} })
    diffraction_precision_index: Optional[TypedMeasurementValue] = Field(default=None, description="""Diffraction precision index estimate of coordinate precision.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RefinementSummary']} })


class MapSummary(ConfiguredBaseModel):
    """
    Headline map quality numbers as of QDS issue date (cryo-EM only). Tracks the metrics ref/quality_reporting.md §1.4 calls out as load-bearing: CC family, model-map FSC, EMRinger / Q-score, and local-resolution spread. Per the EMDataResource 2019 challenge consensus, ≥ 3 metrics from different families should be reported (e.g. CC_mask + EMRinger + d_FSC_model).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    cc_mask: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    cc_box: Optional[TypedMeasurementValue] = Field(default=None, description="""Map-model correlation in the full box. If much lower than cc_mask, suspect over-sharpening or artifacts outside the molecule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    cc_volume: Optional[TypedMeasurementValue] = Field(default=None, description="""Map-model correlation in the high-density volume envelope.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    emringer_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Side-chain–density agreement metric (Barad et al. 2015). Resolution-sensitive; > 1.5 is good at high resolution.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    mean_q_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Mean atom-resolvability Q-score (Pintilie 2020). Per-atom by construction; surface the mean here and the per-residue array via PerResidueQuality.q_score_per_residue when available.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    d_fsc_model_a: Optional[TypedMeasurementValue] = Field(default=None, description="""Resolution at which model-map FSC = 0.5.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    global_fsc_0143_a: Optional[TypedMeasurementValue] = Field(default=None, description="""Global FSC resolution at 0.143 (gold-standard half-map FSC). Compare to d_fsc_model_a — if d_fsc_model >> global_fsc the model is under-fitting; if << it's noise-fitting.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    local_resolution_mean_a: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    local_resolution_std_a: Optional[TypedMeasurementValue] = Field(default=None, description="""Standard deviation of local-resolution distribution.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    directional_resolution_anisotropy: Optional[TypedMeasurementValue] = Field(default=None, description="""Directional resolution anisotropy from 3DFSC-style analysis.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    local_model_map_fsc_q: Optional[TypedMeasurementValue] = Field(default=None, description="""Local FSC-Q or equivalent per-model-map agreement summary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })
    rscc_outlier_fraction: Optional[TypedMeasurementValue] = Field(default=None, description="""Informational fraction below an explicitly stated RSCC reporting cutoff, with limiting-radius convention and denominator recorded. The legacy name does not imply significant outliers or a quality verdict; see the threshold registry's real-space density-fit rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MapSummary']} })


class CrossToolCoverage(ConfiguredBaseModel):
    """
    Per-metric/context summary of which tool families confirmed each claim. The point of the QDS is to make it obvious where the trust model is strong (cctbx + non-cctbx agree) vs weak (cctbx only).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    task_coverage: Optional[list[TaskCoverage]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['CrossToolCoverage']} })


class TaskCoverage(ConfiguredBaseModel):
    """
    One claim-level row in CrossToolCoverage. Coverage is keyed by metric and comparison context; an unrelated oracle on the same task cannot close it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    catalog_task_ref: CatalogTaskId = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    metric_definition_ref: Optional[str] = Field(default=None, description="""Metric whose claim-level oracle coverage is summarized.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete subject whose coverage is summarized.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, description="""Native/reference subject whose comparison coverage is summarized.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    stage: Optional[Stage] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    scope: Optional[MeasurementScope] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    scope_selector: Optional[str] = Field(default=None, description="""Comparison subset whose coverage is summarized.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    cctbx_oracles: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['TaskCoverage']} })
    non_cctbx_oracles: Optional[list[str]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['TaskCoverage']} })
    gap_status: Optional[str] = Field(default=None, description="""Free-text (e.g. \"closed\", \"closed at clashscore\", \"open — needs standalone Rama-Z\"). Settling into an enum once we see more data.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TaskCoverage']} })


class CrossToolWaiver(ConfiguredBaseModel):
    """
    A machine-readable, claim-scoped exception to the trust-model invariant that no gradeable applied task may rest on cctbx-only evidence (#315). Declared on the EvaluationRun and surfaced verbatim in the QDS; the emitter fails hard on a cctbx-only or unclassifiable coverage row with no unambiguous matching waiver. Legacy task-only waivers are accepted only when the task has one gated claim. A waiver is a named, dated admission — not a pass.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    catalog_task_ref: CatalogTaskId = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    metric_definition_ref: Optional[str] = Field(default=None, description="""Metric waived; required when a task has multiple gated claims.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    subject_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    stage: Optional[Stage] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    scope: Optional[MeasurementScope] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    scope_selector: Optional[str] = Field(default=None, description="""Comparison subset waived.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver']} })
    reason: str = Field(default=..., description="""Why no non-cctbx oracle ran — name the missing tool or the documented no-equivalent gap, not a restatement of the fact.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvidenceCorrection', 'CrossToolWaiver']} })
    as_of_date: date = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CrossToolWaiver', 'ToolRecommendation', 'Assumption']} })


class DataQualitySummary(ConfiguredBaseModel):
    """
    X-ray data-quality numbers — bound the model quality from below. Live in the QDS for X-ray structures; absent for cryo-EM and predicted. Sources: data-processing log, phenix.xtriage, CCP4 aimless, gemmi.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    diagnostics: Optional[list[TypedMeasurementValue]] = Field(default=[], description="""Contract-4 T13 diagnostics retained with exact source measurement, original dataset subject, stage, scope, selector, status and evidence. Dataset association admits these values without relabelling them as model measurements or interpreting informational diagnostics as grades.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    completeness_overall_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    completeness_outer_shell_pct: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    mean_i_over_sigma_outer: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    cc_half_outer: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    r_merge: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    r_meas: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })
    wilson_b: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DataQualitySummary']} })


class PredictedConfidenceSummary(ConfiguredBaseModel):
    """
    AlphaFold/RoseTTAFold confidence summary. Mean pLDDT alone is insufficient — distribution shape is what tells you whether a model is uniformly confident or hides disordered regions.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    predictor: Optional[str] = Field(default=None, description="""e.g. AlphaFold2, AlphaFold3, RoseTTAFold, ESMFold.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    predictor_version: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    mean_plddt: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    plddt_distribution_shape: Optional[PlddtDistributionShape] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    pae_max_a: Optional[TypedMeasurementValue] = Field(default=None, description="""Maximum PAE in Å across the matrix.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    pae_multimer_block_min_a: Optional[TypedMeasurementValue] = Field(default=None, description="""For multimers — the minimum PAE in the off-diagonal block between subunits. Low values indicate confident inter-subunit placement; > 15 Å typically unreliable.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    predicted_tm_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Predicted TM-score (pTM) for the model.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    interface_predicted_tm_score: Optional[TypedMeasurementValue] = Field(default=None, description="""Interface predicted TM-score (ipTM) for multimers.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary']} })
    prediction_ensemble_convergence: Optional[TypedMeasurementValue] = Field(default=None, description="""Convergence score across prediction ensemble replicates.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary', 'PredictionEnsembleSummary']} })


class PackingSummary(ConfiguredBaseModel):
    """
    Packing and buried-H-bond diagnostics that complement generic geometry.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    packing_z_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary', 'PackingSummary']} })
    unsatisfied_buried_hbond_count: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['GeometrySummary', 'PackingSummary']} })
    b_factor_outlier_z: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PackingSummary']} })


class ClassificationSummary(ConfiguredBaseModel):
    """
    Secondary-structure, domain, and fold-classification assignments.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    secondary_structure_agreement: Optional[TypedMeasurementValue] = Field(default=None, description="""Fraction of residues on which two independent secondary-structure assigners agree (three-state). Currently informational for the oracle pair pending exact-denominator recalibration.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ClassificationSummary']} })
    secondary_structure_content: Optional[TypedMeasurementValue] = Field(default=None, description="""Fraction of DSSP-scored residues assigned helix or strand (H+E).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ClassificationSummary']} })
    secondary_structure_assignment: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ClassificationSummary']} })
    structural_domain_assignment: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ClassificationSummary']} })
    fold_classification: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ClassificationSummary']} })
    secondary_structure_assignments: Optional[list[SecondaryStructureAssignment]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })
    domain_assignments: Optional[list[DomainAssignment]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'ClassificationSummary']} })


class InterfaceQualitySummary(ConfiguredBaseModel):
    """
    Interface and biological-assembly quality summary.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    interface_buried_surface_area: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQualitySummary']} })
    interface_dockq_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQualitySummary']} })
    capri_interface_quality_class: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQualitySummary']} })
    interface_qualities: Optional[list[InterfaceQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'InterfaceQualitySummary']} })


class PredictionEnsembleSummary(ConfiguredBaseModel):
    """
    Prediction ensemble convergence and replicate quality.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    prediction_ensemble_convergence: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictedConfidenceSummary', 'PredictionEnsembleSummary']} })
    prediction_ensemble_qualities: Optional[list[PredictionEnsembleQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'PredictionEnsembleSummary']} })


class NmrValidationSummary(ConfiguredBaseModel):
    """
    NMR restraint and ensemble validation summary.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    nmr_restraint_violation_summary: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrValidationSummary']} })
    nmr_ensemble_precision_rmsd: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrValidationSummary']} })
    nmr_ensemble_qualities: Optional[list[NmrEnsembleQuality]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['Container', 'EvaluationRun', 'NmrValidationSummary']} })


class PairwiseComparison(SourceRowLineage):
    """
    Candidate vs reference structure comparison. Modern default per ref/quality_reporting.md is to report TM-score AND lDDT as a mandatory pair (CASP15+ consensus, Mariani et al. 2013); CA RMSD is reported additionally for legibility but is not the basis of the verdict on its own.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete candidate artefact compared by this row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, description="""Concrete reference artefact used by this comparison.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    candidate_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    reference_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    reference_kind: ReferenceKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    alignment_method: str = Field(default=..., description="""Tool used for the alignment that backs every metric in this row (e.g. \"TMalign\", \"phenix.superpose_models\", \"gemmi align\", \"ChimeraX matchmaker\"). State exactly one — different tools give subtly different alignments.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    atoms_aligned: Optional[str] = Field(default=None, description="""e.g. \"Cα\", \"all-atom\", \"main-chain\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    residues_aligned: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    tm_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    lddt: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    gdt_ts: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    gdt_ha: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    ca_rmsd_a: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    per_residue_max_displacement_a: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    delta_r_free: Optional[TypedMeasurementValue] = Field(default=None, description="""ΔR-free (candidate − baseline). Always quote `delta_baseline`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    delta_cc_mask: Optional[TypedMeasurementValue] = Field(default=None, description="""ΔCC_mask for cryo-EM, same baseline rules as delta_r_free.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    delta_baseline: Optional[DeltaBaseline] = Field(default=None, description="""Required when any delta_* slot is populated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    verdict: Optional[str] = Field(default=None, description="""improved / equivalent / worse / incomparable, with rationale.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PairwiseComparison']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class ToolRecommendation(ConfiguredBaseModel):
    """
    A ranked recommendation tying a Tool to a (MetricDefinition, role) pair. `top_considered` reflects literature/community consensus (\"the canonical tool for this metric\"); `top_performing` reflects empirical results within this harness (\"the tool that has done best on this metric in our evaluations\"). Often the same tool fills both roles; when they differ, both rows exist and a downstream consumer can compare. Stable across evaluations until the recommendation is consciously updated; bump `as_of_date` when that happens, don't mutate in place.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    metric_definition_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    tool_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    role: RecommendationRole = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation']} })
    rank: Optional[int] = Field(default=None, description="""1 = primary recommendation, 2+ = alternatives in order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation']} })
    justification: Optional[str] = Field(default=None, description="""One-line rationale (\"CASP gold standard for fold similarity\"; \"matches PHENIX within 0.03 Å on 1SAR eval\"). Cite the source paper or the EvaluationRun id that supplies the evidence.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation']} })
    evidence_refs: Optional[list[str]] = Field(default=[], description="""Citation keys (e.g. \"Zhang2004\", \"Williams2018\") and/or EvaluationRun ids that support this recommendation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    as_of_date: Optional[date] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CrossToolWaiver', 'ToolRecommendation', 'Assumption']} })
    effective_at: Optional[datetime ] = Field(default=None, description="""Exact timezone-qualified activation instant used for immutable QDS time slicing. Required for canonical registry rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation', 'Assumption']} })
    supersedes_recommendation_ref: Optional[str] = Field(default=None, description="""Earlier dated recommendation revision retired by this row. Keep the predecessor in the registry so older immutable QDS snapshots remain reproducible; emission selects the newest active lineage member.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class ResidueRef(ConfiguredBaseModel):
    """
    A pointer to a specific residue in a specific chain. Used by ResidueOutlier, PerResidueValue, and Site.member_residue_refs. Identifier composes the structure id + chain id + residue number so a given residue is identifiable across runs.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""e.g. \"1sar:A:33\" (structure_ref:chain_id:residue_number).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    chain_id: str = Field(default=..., description="""PDB chain identifier (typically a single letter).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'Ligand']} })
    residue_number: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef', 'Ligand']} })
    residue_name: Optional[str] = Field(default=None, description="""Three-letter code (ASN, TYR, HIS, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef']} })
    insertion_code: Optional[str] = Field(default=None, description="""PDB insertion code where present (rare).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef']} })


class ResidueOutlier(SourceRowLineage):
    """
    One residue flagged by a validation tool. A residue can have multiple ResidueOutlier rows (e.g. both a Ramachandran and a rotamer outlier). The bare existence of this row is the assertion; the numeric magnitude lives on `metric_value`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact on which this outlier was measured.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    residue_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier', 'PerResidueValue']} })
    outlier_kind: ResidueOutlierKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier']} })
    severity: Optional[Severity] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier', 'FlaggedRegion']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    metric_value: Optional[TypedMeasurementValue] = Field(default=None, description="""Numeric magnitude of the outlier (e.g. clash overlap in Å, rotamer χ deviation in degrees, RSRZ z-score). The kind determines the unit; cite it on the MeasurementValue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier']} })
    details: Optional[str] = Field(default=None, description="""Free-text annotation (e.g. \"ω = 8.91° non-Pro cis\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class DensityPeak(SourceRowLineage):
    """
    A difference-density (mFo−DFc) peak that is not explained by the modelled atoms. Positive peaks = unmodelled mass; negative peaks = modelled atoms with no density support. The driving example includes peaks > 4σ as a critical eval signal.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or map artefact in which this peak was measured.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    sigma_level: float = Field(default=..., description="""Signed peak height in σ (positive blob, negative hole).""", json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak']} })
    coordinates_xyz: Optional[list[float]] = Field(default=[], description="""Cartesian coordinates [x, y, z] in Å.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak', 'Ligand']} })
    nearest_atom_residue_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak']} })
    nearest_atom_distance_a: Optional[float] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak']} })
    interpretation: Optional[str] = Field(default=None, description="""Free-text classification by the agent or harness: \"unmodelled water\", \"Ca²⁺ ion\", \"side-chain alt conf\", \"noise\", \"unmodelled solvent\", etc.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak']} })
    tool_ref: Optional[str] = Field(default=None, description="""Tool that produced the peak list (e.g. phenix.find_peaks_holes).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class FlaggedRegion(SourceRowLineage):
    """
    A contiguous stretch of residues with an issue (disordered loop, poor-density region, dense clash region, ...). Useful when the problem is a region rather than a single residue.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact containing this flagged region.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    chain_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'Ligand']} })
    residue_start: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    residue_end: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    kind: FlaggedRegionKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData',
                       'FlaggedRegion',
                       'Assumption',
                       'CoordinationContact',
                       'Site']} })
    severity: Optional[Severity] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier', 'FlaggedRegion']} })
    summary: Optional[str] = Field(default=None, description="""One-line human description of why the region is flagged.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class PerResidueValue(SourceRowLineage):
    """
    A scalar paired with a residue ref. Used by PerResidueQuality. `metric_definition_ref` is required so the QDS emitter can route each value to the correct per-residue array (lDDT vs displacement vs RSRZ vs Ramachandran-Z) without substring heuristics.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact on which this value was measured.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    residue_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueOutlier', 'PerResidueValue']} })
    metric_definition_ref: str = Field(default=..., description="""Catalog metric this value measures. Routing in the QDS emitter uses this id (not a name or substring) to pick the per-residue slot (lddt_per_residue, displacement_per_residue_a, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'ToolRecommendation',
                       'PerResidueValue']} })
    value: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueValue']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class PerResidueQuality(ConfiguredBaseModel):
    """
    Local-quality block for one structure: per-residue lDDT or displacement, outlier residues, density-difference peaks, and flagged regions. Lives on QualityDataSheet.per_residue_quality.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    lddt_per_residue: Optional[list[PerResidueValue]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    displacement_per_residue_a: Optional[list[PerResidueValue]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    ramachandran_z_per_residue: Optional[list[PerResidueValue]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    rsrz_per_residue: Optional[list[PerResidueValue]] = Field(default=[], description="""Real-space R-factor Z-score per residue (wwPDB validation). RSRZ > 2 flags poor real-space density agreement for that residue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    rscc_per_residue: Optional[list[PerResidueValue]] = Field(default=[], description="""Per-residue real-space correlation coefficient.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    b_factor_z_per_residue: Optional[list[PerResidueValue]] = Field(default=[], description="""Per-residue B-factor Z-score against local/model distribution.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    secondary_structure_per_residue: Optional[list[PerResidueValue]] = Field(default=[], description="""Per-residue secondary-structure labels encoded as measurement values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    fsc_q_per_residue: Optional[list[PerResidueValue]] = Field(default=[], description="""Per-residue FSC-Q or equivalent local model-map agreement values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    outliers: Optional[list[ResidueOutlier]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['PerResidueQuality']} })
    density_peaks: Optional[list[DensityPeak]] = Field(default=[], description="""Δρ peaks above the configured σ threshold (typically > 4σ).""", json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'PerResidueQuality']} })
    flagged_regions: Optional[list[FlaggedRegion]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['EvaluationRun', 'PerResidueQuality']} })


class SecondaryStructureAssignment(SourceRowLineage):
    """
    DSSP/STRIDE-style assignment for a residue range.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact receiving this assignment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    chain_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'Ligand']} })
    residue_start: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    residue_end: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    assignment: str = Field(default=..., description="""Secondary-structure label or code (e.g. helix, sheet, coil, H, E).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SecondaryStructureAssignment']} })
    confidence: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SecondaryStructureAssignment', 'DomainAssignment']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class DomainAssignment(SourceRowLineage):
    """
    Structural domain and fold-classification assignment.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact receiving this domain assignment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    chain_id: Optional[str] = Field(default=None, description="""Chain containing the assigned domain.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'Ligand']} })
    residue_start: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    residue_end: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment']} })
    classification_scheme: Optional[str] = Field(default=None, description="""CATH, SCOPe, ECOD, or another named scheme.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DomainAssignment']} })
    classification_id: Optional[str] = Field(default=None, description="""Scheme-specific identifier.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DomainAssignment']} })
    fold_name: Optional[str] = Field(default=None, description="""Human-readable fold/class name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DomainAssignment']} })
    domain_label: Optional[str] = Field(default=None, description="""Local stable label for this domain assignment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DomainAssignment']} })
    confidence: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SecondaryStructureAssignment', 'DomainAssignment']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class InterfaceQuality(SourceRowLineage):
    """
    Structured quality record for one interface or assembly contact.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or assembly on which this interface was measured.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    reference_subject_ref: Optional[str] = Field(default=None, description="""Concrete native/reference model against which DockQ was measured.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'InterfaceQuality']} })
    interface_label: Optional[str] = Field(default=None, description="""Stable local label for the interface.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    chain_id_1: Optional[str] = Field(default=None, description="""First partner chain or component selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    chain_id_2: Optional[str] = Field(default=None, description="""Second partner chain or component selector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    model_to_native_chain_mapping: Optional[str] = Field(default=None, description="""Explicit DockQ mapping in MODELCHAINS:NATIVECHAINS form.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    partner_1_selector: Optional[str] = Field(default=None, description="""Free-text selector for partner 1 when a chain id is insufficient.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    partner_2_selector: Optional[str] = Field(default=None, description="""Free-text selector for partner 2 when a chain id is insufficient.""", json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    buried_surface_area: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    dockq_score: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    capri_quality_class: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['InterfaceQuality']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    evidence_refs: Optional[list[str]] = Field(default=[], description="""Retained raw outputs supporting the interface scores and mapping.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class NmrEnsembleQuality(SourceRowLineage):
    """
    Structured NMR ensemble/restraint validation record.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete NMR ensemble artefact summarized by this row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    ensemble_label: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality', 'PredictionEnsembleQuality']} })
    model_count: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality', 'PredictionEnsembleQuality']} })
    restraint_violation_summary: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality']} })
    ensemble_precision_rmsd: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class PredictionEnsembleQuality(SourceRowLineage):
    """
    Structured predicted-model ensemble convergence record.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema',
         'mixins': ['SourceRowLineage']})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete prediction-ensemble artefact summarized by this row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    ensemble_label: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality', 'PredictionEnsembleQuality']} })
    model_count: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NmrEnsembleQuality', 'PredictionEnsembleQuality']} })
    convergence: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictionEnsembleQuality']} })
    diversity: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['PredictionEnsembleQuality']} })
    tool_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })
    source_evaluation_run_ref: Optional[str] = Field(default=None, description="""EvaluationRun that owns source_row_ref.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage',
                       'TypedMeasurementValue',
                       'MeasurementEvidenceOrigin']} })
    source_row_ref: Optional[str] = Field(default=None, description="""Id of the structured source row copied into the QDS.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRowLineage']} })


class Ligand(ConfiguredBaseModel):
    """
    A non-protein component of the structure: small-molecule ligand, ion, cofactor, or covalent modification. Identified by chemical component dictionary (CCD) code where possible. Coordinates and B-factor make every claim about a specific ion / ligand position independently verifiable.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., description="""e.g. \"1sar:A:Ca33\" (structure:chain:CCD+resnum).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact containing this ligand.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    pdb_chemical_id: Optional[str] = Field(default=None, description="""CCD three-letter code (ATP, FAD, CA for calcium, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ligand']} })
    smiles: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Ligand']} })
    chain_id: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'Ligand']} })
    residue_number: Optional[int] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ResidueRef', 'Ligand']} })
    partial_occupancy: Optional[bool] = Field(default=None, description="""True when the ligand is modelled at occupancy < 1.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ligand']} })
    coordinates_xyz: Optional[list[float]] = Field(default=[], description="""Cartesian coordinates of the ligand centre (or the metal-ion atom for ions) in Å. A list of three floats [x, y, z]. Lets a downstream consumer cross-check the agent's stated position against the deposited PDB coordinates.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DensityPeak', 'Ligand']} })
    b_factor: Optional[TypedMeasurementValue] = Field(default=None, description="""Atomic B-factor (Å²) of the ligand or its central atom. For ions this is the single-atom B; for molecules it is the mean over the ligand atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ligand']} })
    coordination_contacts: Optional[list[CoordinationContact]] = Field(default=[], description="""Inner-sphere / outer-sphere atom-atom contacts that define the coordination geometry for ions and the H-bond network for organic ligands. Each row is one atom-atom distance measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ligand']} })


class LigandQuality(ConfiguredBaseModel):
    """
    Real-space and geometric quality metrics for a bound ligand. Catalog T10 (ligand fitting) defines these; the QDS surfaces them so a downstream consumer can verify the binding site is not misfit. Required when a ligand is present and the structure claims biological relevance for it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    ligand_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality', 'CoordinationContact', 'Site']} })
    rscc: Optional[TypedMeasurementValue] = Field(default=None, description="""Real-space correlation coefficient. Informational corroboration only; comparisons require a matched limiting-radius convention. No fixed quality cutoff; see the threshold registry's real-space density-fit rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    rsr: Optional[TypedMeasurementValue] = Field(default=None, description="""Real-space R-factor. Informational diagnostic without a fixed quality cutoff; assess significance using available RSZD/RSZO evidence under the threshold registry's real-space density-fit rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    ligand_b_factor_mean: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    ligand_b_factor_vs_surroundings: Optional[TypedMeasurementValue] = Field(default=None, description="""Ratio of ligand mean B to surrounding-protein mean B. > 1.5 can indicate partial occupancy or weak binding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    protein_ligand_hbond_count: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    pose_rmsd_to_deposited_a: Optional[TypedMeasurementValue] = Field(default=None, description="""RMSD of the ligand pose to a deposited reference complex.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })
    element_identity: Optional[TypedMeasurementValue] = Field(default=None, description="""Oracle assessment of the modelled chemical element. Candidate-specific numeric evidence remains in the source EvaluationRun; this field carries the citable ligand-level conclusion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality']} })


class Assumption(ConfiguredBaseModel):
    """
    One documented assumption that affects how a measurement, tool, or report should be interpreted. Assumptions are first-class because they're the inferential basis the QDS rests on — a number paired with its assumption set is reproducible; a number alone is not. See ref/quality_reporting.md and the skill's \"Tool assumptions\" / \"Agentic-framework assumptions\" sections for the canonical catalog.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    as_of_date: Optional[date] = Field(default=None, description="""Date this registry assumption became active. Required for rows in ref/tool_assumptions.yaml so immutable QDS emission can exclude assumptions introduced after the sheet was issued; embedded measurement/run assumptions are already pinned by their source EVAL.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CrossToolWaiver', 'ToolRecommendation', 'Assumption']} })
    effective_at: Optional[datetime ] = Field(default=None, description="""Exact timezone-qualified activation instant for rows in ref/tool_assumptions.yaml. Embedded EVAL assumptions do not need it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation', 'Assumption']} })
    supersedes_assumption_ref: Optional[str] = Field(default=None, description="""Earlier dated registry assumption revision retired by this row. The predecessor remains available to QDS snapshots issued before this row became active.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Assumption']} })
    kind: AssumptionKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData',
                       'FlaggedRegion',
                       'Assumption',
                       'CoordinationContact',
                       'Site']} })
    scope: AssumptionScope = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'ModelDatasetAssociation',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'Assumption']} })
    title: str = Field(default=..., description="""One-line label for the assumption (used in QDS table headers).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Assumption']} })
    description: str = Field(default=..., description="""What the assumption is, in prose.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'Structure',
                       'IdentityBlock',
                       'Assumption',
                       'Site']} })
    consequences: Optional[str] = Field(default=None, description="""What can go wrong if the assumption is violated — the mechanism by which the affected number could be misleading.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Assumption']} })
    mitigation: Optional[str] = Field(default=None, description="""What check, cross-tool comparison, or follow-up oracle would catch a violation. Should be runnable.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Assumption']} })
    status: Optional[AssumptionStatus] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck', 'Assumption']} })
    tool_ref: Optional[str] = Field(default=None, description="""When the assumption is tool-level, point at the tool.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ToolRecommendation',
                       'ResidueOutlier',
                       'DensityPeak',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption']} })
    measurement_ref: Optional[str] = Field(default=None, description="""When the assumption is measurement-level, point at the measurement.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Assumption']} })
    evidence_refs: Optional[list[str]] = Field(default=[], description="""Citations or EvaluationRun ids supporting the assumption's presence (e.g. cite the paper documenting the tool's default, or the eval that observed a violation).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'ToolRecommendation',
                       'InterfaceQuality',
                       'Assumption']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class CoordinationContact(ConfiguredBaseModel):
    """
    One atom-atom distance recorded at a coordination / contact site. Ions carry these as Ligand.coordination_contacts[]; the list of contacts plus their distances is exactly what defines the metal coordination geometry.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    atom1_residue_ref: Optional[str] = Field(default=None, description="""Residue containing the first atom (None for ligand-side).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CoordinationContact']} })
    atom1_atom_name: Optional[str] = Field(default=None, description="""PDB atom name (e.g. \"OD2\", \"CA\", \"O\", \"ZN\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['CoordinationContact']} })
    atom2_residue_ref: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CoordinationContact']} })
    atom2_atom_name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CoordinationContact']} })
    ligand_ref: Optional[str] = Field(default=None, description="""Set when one side of the contact is the ion / ligand itself.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality', 'CoordinationContact', 'Site']} })
    distance_a: Optional[TypedMeasurementValue] = Field(default=None, description="""Distance in Å.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CoordinationContact']} })
    kind: Optional[ContactKind] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData',
                       'FlaggedRegion',
                       'Assumption',
                       'CoordinationContact',
                       'Site']} })
    notes: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Finding',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'TypedMeasurementValue',
                       'HeadlineFinding',
                       'ToolRecommendation',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Assumption',
                       'CoordinationContact']} })


class Site(ConfiguredBaseModel):
    """
    A named region of biological / structural interest — active site, binding site, protein-protein interface, metal-coordination sphere. Defined by an explicit set of member residues so quality metrics can be computed per-site rather than per-whole-structure.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    subject_ref: Optional[str] = Field(default=None, description="""Concrete model or artefact containing this site.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MeasurementValue',
                       'TypedMeasurementValue',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'PairwiseComparison',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    structure_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AgentArtifact',
                       'EvaluationRun',
                       'QdsEmissionContext',
                       'QualityDataSheet',
                       'ResidueRef',
                       'FlaggedRegion',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'Site']} })
    kind: SiteKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ExperimentalData',
                       'FlaggedRegion',
                       'Assumption',
                       'CoordinationContact',
                       'Site']} })
    member_residue_refs: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Site']} })
    ligand_ref: Optional[str] = Field(default=None, description="""Ligand bound at this site, if any.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LigandQuality', 'CoordinationContact', 'Site']} })
    description: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['MetricDefinition',
                       'Structure',
                       'IdentityBlock',
                       'Assumption',
                       'Site']} })


class SiteQuality(ConfiguredBaseModel):
    """
    Site-scoped quality metrics. Lives on QualityDataSheet.site_qualities[]. The fields are deliberately overlapping with GeometrySummary so the consumer can compare the site to the global average — a structure with great global geometry but a wrecked active site is still a bad model for its intended function.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/protstruct-review/schema'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CatalogTask',
                       'Tool',
                       'MetricDefinition',
                       'Structure',
                       'ExperimentalData',
                       'AgentArtifact',
                       'Refinement',
                       'MeasurementProvenance',
                       'CriterionPreconditionCheck',
                       'MeasurementValue',
                       'HeadlineFinding',
                       'EvaluationRun',
                       'EvidenceCorrection',
                       'ModelDatasetAssociation',
                       'QdsEmissionContext',
                       'QdsReplayPin',
                       'QualityDataSheet',
                       'IdentityBlock',
                       'GeometrySummary',
                       'RefinementSummary',
                       'MapSummary',
                       'CrossToolCoverage',
                       'TaskCoverage',
                       'CrossToolWaiver',
                       'DataQualitySummary',
                       'PredictedConfidenceSummary',
                       'PackingSummary',
                       'ClassificationSummary',
                       'InterfaceQualitySummary',
                       'PredictionEnsembleSummary',
                       'NmrValidationSummary',
                       'PairwiseComparison',
                       'ToolRecommendation',
                       'ResidueRef',
                       'ResidueOutlier',
                       'DensityPeak',
                       'FlaggedRegion',
                       'PerResidueValue',
                       'PerResidueQuality',
                       'SecondaryStructureAssignment',
                       'DomainAssignment',
                       'InterfaceQuality',
                       'NmrEnsembleQuality',
                       'PredictionEnsembleQuality',
                       'Ligand',
                       'LigandQuality',
                       'Assumption',
                       'CoordinationContact',
                       'Site',
                       'SiteQuality']} })
    site_ref: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    site_rmsd_to_reference_a: Optional[TypedMeasurementValue] = Field(default=None, description="""RMSD over member_residue_refs vs the reference structure's same site.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    mean_per_residue_lddt: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    mean_b_factor: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Refinement', 'SiteQuality']} })
    site_clashscore: Optional[TypedMeasurementValue] = Field(default=None, description="""Clashscore restricted to atoms within the site's member residues.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    site_ramachandran_outlier_count: Optional[TypedMeasurementValue] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    site_density_peaks: Optional[list[DensityPeak]] = Field(default=[], json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })
    ligand_quality: Optional[LigandQuality] = Field(default=None, description="""Required when site.ligand_ref is set.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SiteQuality']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Container.model_rebuild()
Finding.model_rebuild()
SourceRowLineage.model_rebuild()
CatalogTask.model_rebuild()
Tool.model_rebuild()
MetricDefinition.model_rebuild()
Structure.model_rebuild()
ExperimentalData.model_rebuild()
AgentArtifact.model_rebuild()
Refinement.model_rebuild()
MeasurementProvenance.model_rebuild()
CriterionPreconditionCheck.model_rebuild()
MeasurementValue.model_rebuild()
TypedMeasurementValue.model_rebuild()
HeadlineFinding.model_rebuild()
EvaluationRun.model_rebuild()
EvidenceCorrection.model_rebuild()
MeasurementEvidenceOrigin.model_rebuild()
ModelDatasetAssociation.model_rebuild()
QdsEmissionContext.model_rebuild()
QdsReplayPin.model_rebuild()
QualityDataSheet.model_rebuild()
IdentityBlock.model_rebuild()
GeometrySummary.model_rebuild()
RefinementSummary.model_rebuild()
MapSummary.model_rebuild()
CrossToolCoverage.model_rebuild()
TaskCoverage.model_rebuild()
CrossToolWaiver.model_rebuild()
DataQualitySummary.model_rebuild()
PredictedConfidenceSummary.model_rebuild()
PackingSummary.model_rebuild()
ClassificationSummary.model_rebuild()
InterfaceQualitySummary.model_rebuild()
PredictionEnsembleSummary.model_rebuild()
NmrValidationSummary.model_rebuild()
PairwiseComparison.model_rebuild()
ToolRecommendation.model_rebuild()
ResidueRef.model_rebuild()
ResidueOutlier.model_rebuild()
DensityPeak.model_rebuild()
FlaggedRegion.model_rebuild()
PerResidueValue.model_rebuild()
PerResidueQuality.model_rebuild()
SecondaryStructureAssignment.model_rebuild()
DomainAssignment.model_rebuild()
InterfaceQuality.model_rebuild()
NmrEnsembleQuality.model_rebuild()
PredictionEnsembleQuality.model_rebuild()
Ligand.model_rebuild()
LigandQuality.model_rebuild()
Assumption.model_rebuild()
CoordinationContact.model_rebuild()
Site.model_rebuild()
SiteQuality.model_rebuild()
