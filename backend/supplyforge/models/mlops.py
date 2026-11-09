import uuid

from django.db import models
from .user import Workspace
from .ingestion_session import IngestionSession


class TenantFeatureSnapshot(models.Model):
    """Immutable feature state with the lineage needed for safe model training."""

    LABEL_UNLABELED = 'UNLABELED'
    LABEL_OPERATIONAL_OUTCOME = 'OPERATIONAL_OUTCOME'
    LABEL_FROZEN_GROUND_TRUTH = 'FROZEN_GROUND_TRUTH'
    LABEL_EXPERT_ANNOTATION = 'EXPERT_ANNOTATION'
    LABEL_MERCHANT_FEEDBACK = 'MERCHANT_FEEDBACK'
    LABEL_HEURISTIC = 'HEURISTIC'
    LABEL_SOURCE_CHOICES = [
        (LABEL_UNLABELED, 'Unlabeled'),
        (LABEL_OPERATIONAL_OUTCOME, 'Operational outcome'),
        (LABEL_FROZEN_GROUND_TRUTH, 'Frozen ground truth'),
        (LABEL_EXPERT_ANNOTATION, 'Expert annotation'),
        (LABEL_MERCHANT_FEEDBACK, 'Merchant feedback'),
        (LABEL_HEURISTIC, 'Heuristic only'),
    ]

    QUALITY_UNLABELED = 'UNLABELED'
    QUALITY_GOLD = 'GOLD'
    QUALITY_SILVER = 'SILVER'
    QUALITY_BRONZE = 'BRONZE'
    QUALITY_COPPER = 'COPPER'
    LABEL_QUALITY_CHOICES = [
        (QUALITY_UNLABELED, 'Unlabeled'),
        (QUALITY_GOLD, 'Gold'),
        (QUALITY_SILVER, 'Silver'),
        (QUALITY_BRONZE, 'Bronze'),
        (QUALITY_COPPER, 'Copper'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    sku_id = models.CharField(max_length=128, db_index=True)
    feature_vector_json = models.JSONField()

    # A stable key makes materialization idempotent without overwriting history.
    snapshot_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    dataset_version = models.ForeignKey(
        'supplyforge.DatasetVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='feature_snapshots',
    )
    session = models.ForeignKey(IngestionSession, on_delete=models.SET_NULL, null=True)
    feature_schema_version = models.CharField(max_length=64, default='risk-features-v1')
    model_version = models.CharField(max_length=64, blank=True, default='')
    source_event_time = models.DateTimeField(null=True, blank=True)
    source_lineage_json = models.JSONField(default=dict, blank=True)
    outcome_observation_ends_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True, null=True)
    computed_at = models.DateTimeField(auto_now=True)

    actual_risk_level = models.CharField(max_length=32, null=True, blank=True)
    label_source = models.CharField(
        max_length=32,
        choices=LABEL_SOURCE_CHOICES,
        default=LABEL_UNLABELED,
    )
    label_quality = models.CharField(
        max_length=16,
        choices=LABEL_QUALITY_CHOICES,
        default=QUALITY_UNLABELED,
    )
    label_observed_at = models.DateTimeField(null=True, blank=True)
    label_frozen_at = models.DateTimeField(null=True, blank=True)
    training_eligible = models.BooleanField(default=False)

    class Meta:
        db_table = 'tenant_feature_snapshots'
        indexes = [
            models.Index(fields=['computed_at']),
            models.Index(fields=['label_quality']),
            models.Index(
                fields=['workspace', 'dataset_version', 'source_event_time'],
                name='tenant_snap_ws_data_idx',
            ),
            models.Index(
                fields=['workspace', 'training_eligible', 'label_observed_at'],
                name='tenant_snap_ws_elig_idx',
            ),
        ]


class TemporalShadowPrediction(models.Model):
    """Immutable temporal-candidate prediction retained until its outcome matures.

    This table is deliberately separate from generic feature snapshots. It is
    the audit cohort for SHADOW/CANARY demand-risk candidates, rather than a
    training label or an assertion about physical inventory.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='temporal_shadow_predictions',
    )
    canonical_sku = models.CharField(max_length=255, db_index=True)
    model_version = models.CharField(max_length=128, db_index=True)
    serving_state = models.CharField(max_length=16)
    operating_mode = models.CharField(max_length=64, default='balanced')
    feature_schema_version = models.CharField(max_length=64)
    ground_truth_schema_version = models.CharField(max_length=128, blank=True, default='')
    ground_truth_thresholds_json = models.JSONField(default=dict, blank=True)

    decision_cutoff = models.DateTimeField()
    outcome_observation_ends_at = models.DateTimeField(db_index=True)
    predicted_risk_class = models.CharField(max_length=20)
    high_risk_probability = models.FloatField()
    raw_high_risk_probability = models.FloatField()
    class_probabilities_json = models.JSONField(default=dict, blank=True)
    feature_vector_json = models.JSONField(default=dict, blank=True)
    source_lineage_json = models.JSONField(default=dict, blank=True)

    actual_risk_class = models.CharField(max_length=20, null=True, blank=True)
    actual_future_fulfilled_quantity = models.FloatField(null=True, blank=True)
    outcome_observed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'temporal_shadow_predictions'
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'canonical_sku', 'model_version', 'decision_cutoff'],
                name='temporal_shadow_prediction_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'model_version', 'outcome_observation_ends_at'],
                name='temporal_shadow_maturity_idx',
            ),
            models.Index(
                fields=['workspace', 'model_version', 'decision_cutoff'],
                name='temporal_shadow_cohort_idx',
            ),
        ]


class TemporalDemandSourceImport(models.Model):
    """Immutable lineage for the source currently used by runtime temporal features.

    The feature service reads normalized ORM events rather than an archive.  This
    record binds those events to the exact source checksum used in a parity
    evaluation, so an operator cannot attest parity against a different export.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='temporal_demand_source_imports',
    )
    source_sha256 = models.CharField(max_length=64, db_index=True)
    source_name = models.CharField(max_length=255)
    feature_contract_sha256 = models.CharField(max_length=64)
    retained_orders = models.PositiveIntegerField(default=0)
    retained_items = models.PositiveIntegerField(default=0)
    skipped_orders = models.PositiveIntegerField(default=0)
    skipped_items = models.PositiveIntegerField(default=0)
    imported_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'temporal_demand_source_imports'
        indexes = [
            models.Index(
                fields=['workspace', 'is_current', '-imported_at'],
                name='temporal_source_current_idx',
            ),
        ]


class TemporalCandidatePromotionApproval(models.Model):
    """Accountable approval for a specific temporal candidate promotion.

    Approval is deliberately a database record rather than a command-line
    switch.  It binds mature SHADOW evidence to the exact benchmark, policy,
    source and feature contract, and can be revoked without modifying model
    artifacts in place.
    """

    STATUS_APPROVED = 'APPROVED'
    STATUS_REVOKED = 'REVOKED'
    STATUS_CHOICES = [
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REVOKED, 'Revoked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='temporal_candidate_promotion_approvals',
    )
    model_version = models.CharField(max_length=128, db_index=True)
    selected_model = models.CharField(max_length=128)
    benchmark_manifest_sha256 = models.CharField(max_length=64)
    source_sha256 = models.CharField(max_length=64)
    feature_contract_sha256 = models.CharField(max_length=64)
    promotion_policy_sha256 = models.CharField(max_length=64)
    shadow_report_sha256 = models.CharField(max_length=64)
    shadow_quality_json = models.JSONField(default=dict)
    approved_by = models.CharField(max_length=128)
    approval_reference = models.CharField(max_length=255)
    approved_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_APPROVED, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.CharField(max_length=128, blank=True, default='')
    revoke_reference = models.CharField(max_length=255, blank=True, default='')
    revoke_reason = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'temporal_candidate_promotion_approvals'
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'model_version', 'benchmark_manifest_sha256'],
                name='temporal_promotion_approval_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'model_version', 'status'],
                name='temporal_prom_ws_model_idx',
            ),
        ]


class TrainingDatasetManifest(models.Model):
    """Frozen, reproducible training selection without storing millions of IDs in JSON."""

    STATUS_FROZEN = 'FROZEN'
    STATUS_CHOICES = [(STATUS_FROZEN, 'Frozen')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='training_manifests',
    )
    cutoff_at = models.DateTimeField()
    frozen_at = models.DateTimeField()
    feature_schema_version = models.CharField(max_length=64)
    include_cross_tenant = models.BooleanField(default=False)
    snapshot_count = models.BigIntegerField(default=0)
    label_distribution_json = models.JSONField(default=dict, blank=True)
    selection_criteria_json = models.JSONField(default=dict, blank=True)
    snapshot_checksum = models.CharField(max_length=71)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_FROZEN)
    created_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'training_dataset_manifests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workspace', 'created_at'], name='training_man_ws_created_idx'),
            models.Index(fields=['workspace', 'cutoff_at'], name='training_man_ws_cutoff_idx'),
        ]


class ModelVersion(models.Model):
    """Model version tracking with full governance and audit trail."""

    STATUS_CHOICES = [
        ('TRAINING', 'Đang train'),
        ('EVALUATING', 'Đang đánh giá offline'),
        ('REGRESSION_GATE', 'Đang chạy ML Regression Gate'),
        ('SHADOW', 'Shadow mode (chạy song song)'),
        ('CANARY', 'Canary rollout'),
        ('PROMOTION_REVIEW', 'Chờ admin approve'),
        ('ACTIVE', 'Đang sử dụng (production)'),
        ('RETIRED', 'Đã ngừng'),
        ('REJECTED', 'Bị từ chối (gate failed)'),
        ('FAILED', 'Train thất bại'),
    ]

    version = models.CharField(max_length=32, unique=True)       # risk-v1.3.0
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='model_versions',
    )
    model_type = models.CharField(max_length=64)                 # XGBClassifier
    artifact_dir = models.CharField(max_length=512)              # models/risk-v1.3.0/
    artifact_sha256 = models.CharField(max_length=64)
    artifact_uri = models.CharField(max_length=1024, blank=True, default='')
    sagemaker_model_arn = models.CharField(max_length=1024, blank=True, default='')
    sagemaker_model_package_arn = models.CharField(max_length=1024, blank=True, default='')
    feature_schema_version = models.CharField(max_length=64, default='risk-features-v1')

    # Metrics
    macro_f1 = models.FloatField(null=True, blank=True)
    weighted_f1 = models.FloatField(null=True, blank=True)
    high_risk_recall = models.FloatField(null=True, blank=True)
    balanced_accuracy = models.FloatField(null=True, blank=True)
    ece = models.FloatField(null=True, blank=True)

    # Governance & Reproducibility
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='TRAINING')
    training_dataset_version = models.CharField(max_length=64, default='v1.0')
    validation_dataset_version = models.CharField(max_length=64, default='v1.0')
    training_cutoff = models.DateField(null=True, blank=True)
    threshold_version = models.CharField(max_length=32, default='TH-1.0')
    calibration_version = models.CharField(max_length=32, default='CAL-1.0')
    code_commit_sha = models.CharField(max_length=64, blank=True, default='')
    training_manifest = models.ForeignKey(
        TrainingDatasetManifest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='model_versions',
    )
    dataset_manifest_json = models.JSONField(default=dict, blank=True)
    evaluation_metrics_json = models.JSONField(default=dict, blank=True)
    quality_gate_result_json = models.JSONField(default=dict, blank=True)
    governance_audit_json = models.JSONField(default=list, blank=True)
    is_cross_tenant_training = models.BooleanField(default=False)

    # Promotion audit trail
    promoted_by = models.CharField(max_length=128, null=True, blank=True)
    promotion_reason = models.TextField(null=True, blank=True)
    promotion_gate_result_json = models.JSONField(null=True, blank=True)
    approved_by = models.CharField(max_length=128, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.CharField(max_length=128, null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    shadow_started_at = models.DateTimeField(null=True, blank=True)
    canary_started_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    drift_status = models.CharField(max_length=20, default='UNKNOWN')
    drift_metrics_json = models.JSONField(default=dict, blank=True)
    rollback_target = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rollback_successors',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'model_versions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.version} [{self.status}]"
