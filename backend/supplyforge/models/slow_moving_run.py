"""Durable operational runs for merchant-facing slow-moving assessments."""

import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class SlowMovingAssessmentRun(models.Model):
    """One immutable, source-bound slow-moving calculation.

    Risk rows from different imports must never be combined in a merchant
    dashboard.  A run pins the calculation to the exact dataset version and
    retains its policy and source freshness evidence for later review.
    """

    SOURCE_CSV = 'CSV'
    SOURCE_ODOO = 'ODOO'
    SOURCE_CHOICES = [(SOURCE_CSV, 'CSV'), (SOURCE_ODOO, 'Odoo')]

    STATUS_BUILDING = 'BUILDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_BUILDING, 'Building'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_assessment_runs'
    )
    source_type = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    # ``CSV`` for the active CSV source and ``ODOO:<connection-id>`` for an
    # ERP source.  This makes the uniqueness rule unambiguous across sources.
    source_key = models.CharField(max_length=128)
    dataset_version = models.ForeignKey(
        'supplyforge.DatasetVersion', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='slow_moving_assessment_runs',
    )
    integration_connection = models.ForeignKey(
        'supplyforge.IntegrationConnection', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='slow_moving_assessment_runs',
    )
    analysis_as_of = models.DateTimeField()
    source_freshness = models.JSONField(default=dict, blank=True)
    # An assessment can be reproduced only when demand and stock use the same
    # declared source scope. The digest is indexed so quality cohorts never
    # aggregate a replacement import or another warehouse by accident.
    source_scope = models.JSONField(default=dict, blank=True)
    source_scope_fingerprint = models.CharField(max_length=64, blank=True, default='', db_index=True)
    # A deterministic digest of the exact source facts that produced this
    # run. Source scope says *where* the facts came from; this says *which*
    # snapshot was assessed and makes provider retry handling idempotent.
    source_snapshot_fingerprint = models.CharField(max_length=64, blank=True, default='', db_index=True)
    policy_version = models.CharField(max_length=64)
    policy_checksum = models.CharField(max_length=64)
    summary = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_BUILDING, db_index=True)
    # Only a successfully published run can be current.  The conditional
    # uniqueness constraint lets historical runs remain immutable.
    is_current = models.BooleanField(default=False, db_index=True)
    failure_reason = models.CharField(max_length=512, blank=True, default='')
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'slow_moving_assessment_runs'
        ordering = ['-completed_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source_key'],
                condition=Q(is_current=True),
                name='slow_moving_one_current_source_run',
            ),
        ]
        indexes = [
            models.Index(fields=['workspace', 'source_type', 'status'], name='slow_run_ws_source_status_idx'),
            models.Index(fields=['workspace', 'source_key', '-completed_at'], name='slow_run_ws_key_completed_idx'),
            models.Index(fields=['dataset_version'], name='slow_run_dataset_idx'),
        ]

    def __str__(self):
        return f'{self.workspace_id}:{self.source_key}:{self.status}:{self.analysis_as_of.date()}'


class SlowMovingAlertState(models.Model):
    """Lifecycle state for one merchant-facing slow-moving alert."""

    STATUS_CANDIDATE = 'CANDIDATE'
    STATUS_OPEN = 'OPEN'
    STATUS_ACKNOWLEDGED = 'ACKNOWLEDGED'
    STATUS_SNOOZED = 'SNOOZED'
    STATUS_RESOLVED = 'RESOLVED'
    STATUS_DATA_BLOCKED = 'DATA_BLOCKED'
    STATUS_CHOICES = [
        (STATUS_CANDIDATE, 'Awaiting confirmation'),
        (STATUS_OPEN, 'Open'),
        (STATUS_ACKNOWLEDGED, 'Acknowledged'),
        (STATUS_SNOOZED, 'Snoozed'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_DATA_BLOCKED, 'Data blocked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_alert_states'
    )
    source_type = models.CharField(max_length=16, choices=SlowMovingAssessmentRun.SOURCE_CHOICES)
    source_key = models.CharField(max_length=128)
    canonical_sku = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CANDIDATE, db_index=True)
    consecutive_eligible_runs = models.PositiveSmallIntegerField(default=0)
    first_detected_at = models.DateTimeField(default=timezone.now)
    last_detected_at = models.DateTimeField(default=timezone.now)
    last_assessment_run = models.ForeignKey(
        SlowMovingAssessmentRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alert_states',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=500, blank=True, default='')
    # A resolved alert must not be silently reopened by a later identical
    # calculation. These fields retain the exact operational facts that last
    # changed the merchant's attention state.
    owner_label = models.CharField(max_length=128, blank=True, default='')
    next_review_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_signal_snapshot = models.JSONField(default=dict, blank=True)
    last_signal_fingerprint = models.CharField(max_length=64, blank=True, default='')
    last_material_change_at = models.DateTimeField(null=True, blank=True)
    feedback = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'slow_moving_alert_states'
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source_key', 'canonical_sku'],
                name='slow_moving_alert_source_sku_uq',
            ),
        ]
        indexes = [
            models.Index(fields=['workspace', 'status', '-last_detected_at'], name='slow_alert_ws_status_seen_idx'),
            models.Index(fields=['source_key', 'canonical_sku'], name='slow_alert_source_sku_idx'),
        ]

    def __str__(self):
        return f'{self.workspace_id}:{self.canonical_sku}:{self.status}'


class SlowMovingSkuContext(models.Model):
    """Effective-dated merchant context for a SKU's saleability.

    This model is append-only in normal use. A newer declaration can supersede
    a former one by narrowing its effective end date, while old declarations
    remain available for audit. It deliberately does not infer bundle or
    successor conversion from product names.
    """

    AVAILABILITY_SELLABLE = 'SELLABLE'
    AVAILABILITY_HELD = 'HELD'
    AVAILABILITY_DAMAGED = 'DAMAGED'
    AVAILABILITY_PREORDER = 'PREORDER'
    AVAILABILITY_CONSIGNMENT = 'CONSIGNMENT'
    AVAILABILITY_UNKNOWN = 'UNKNOWN'
    AVAILABILITY_CHOICES = [
        (AVAILABILITY_SELLABLE, 'Có thể bán'),
        (AVAILABILITY_HELD, 'Đang giữ chỗ'),
        (AVAILABILITY_DAMAGED, 'Hàng hỏng hoặc kiểm kê'),
        (AVAILABILITY_PREORDER, 'Hàng đặt trước'),
        (AVAILABILITY_CONSIGNMENT, 'Hàng ký gửi'),
        (AVAILABILITY_UNKNOWN, 'Chưa xác nhận khả năng bán'),
    ]

    ROLE_STANDALONE = 'STANDALONE'
    ROLE_VARIANT = 'VARIANT'
    ROLE_PARENT = 'PARENT'
    ROLE_BUNDLE = 'BUNDLE'
    ROLE_COMPONENT = 'COMPONENT'
    ROLE_REPLACEMENT = 'REPLACEMENT'
    ROLE_SEASONAL = 'SEASONAL'
    ROLE_NEW_LAUNCH = 'NEW_LAUNCH'
    ROLE_END_OF_LIFE = 'END_OF_LIFE'
    ROLE_UNKNOWN = 'UNKNOWN'
    ROLE_CHOICES = [
        (ROLE_STANDALONE, 'SKU độc lập'),
        (ROLE_VARIANT, 'Biến thể'),
        (ROLE_PARENT, 'Sản phẩm cha'),
        (ROLE_BUNDLE, 'Sản phẩm bán theo gói'),
        (ROLE_COMPONENT, 'Linh kiện của gói'),
        (ROLE_REPLACEMENT, 'SKU thay thế'),
        (ROLE_SEASONAL, 'Sản phẩm theo mùa'),
        (ROLE_NEW_LAUNCH, 'Sản phẩm mới mở bán'),
        (ROLE_END_OF_LIFE, 'Sản phẩm ngừng bán'),
        (ROLE_UNKNOWN, 'Chưa xác nhận loại sản phẩm'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_sku_contexts'
    )
    canonical_sku = models.CharField(max_length=255, db_index=True)
    # Blank source/warehouse/channel deliberately means "all current scopes".
    source_key = models.CharField(max_length=128, blank=True, default='')
    warehouse_code = models.CharField(max_length=128, blank=True, default='')
    channel = models.CharField(max_length=128, blank=True, default='')
    availability = models.CharField(max_length=24, choices=AVAILABILITY_CHOICES)
    catalog_role = models.CharField(max_length=24, choices=ROLE_CHOICES, default=ROLE_STANDALONE)
    related_canonical_sku = models.CharField(max_length=255, blank=True, default='')
    conversion_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    effective_from = models.DateTimeField(default=timezone.now, db_index=True)
    effective_to = models.DateTimeField(null=True, blank=True, db_index=True)
    evidence_reference = models.CharField(max_length=512, blank=True, default='')
    provenance_json = models.JSONField(default=dict, blank=True)
    declared_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slow_moving_sku_contexts'
        indexes = [
            models.Index(
                fields=['workspace', 'canonical_sku', 'source_key', 'effective_from'],
                name='slow_ctx_ws_sku_source_idx',
            ),
            models.Index(
                fields=['workspace', 'warehouse_code', 'effective_from'],
                name='slow_ctx_ws_wh_time_idx',
            ),
        ]


class SlowMovingAlertPassport(models.Model):
    """Immutable merchant-facing explanation for one alert state in one run."""

    EVENT_OPENED = 'OPENED'
    EVENT_WORSENED = 'WORSENED'
    EVENT_REOPENED = 'REOPENED'
    EVENT_DATA_BLOCKED = 'DATA_BLOCKED'
    EVENT_RECHECK = 'RECHECK'
    EVENT_CHOICES = [
        (EVENT_OPENED, 'Mở cảnh báo'),
        (EVENT_WORSENED, 'Cảnh báo xấu đi'),
        (EVENT_REOPENED, 'Mở lại cảnh báo'),
        (EVENT_DATA_BLOCKED, 'Cần kiểm tra dữ liệu'),
        (EVENT_RECHECK, 'Kiểm tra lại'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_alert_passports'
    )
    alert_state = models.ForeignKey(
        SlowMovingAlertState, on_delete=models.CASCADE, related_name='passports'
    )
    assessment_run = models.ForeignKey(
        SlowMovingAssessmentRun, on_delete=models.CASCADE, related_name='alert_passports'
    )
    assessment = models.ForeignKey(
        'supplyforge.SlowMovingRiskAssessment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='alert_passports',
    )
    event_type = models.CharField(max_length=24, choices=EVENT_CHOICES)
    source_scope_fingerprint = models.CharField(max_length=64, db_index=True)
    previous_facts_json = models.JSONField(default=dict, blank=True)
    current_facts_json = models.JSONField(default=dict, blank=True)
    changed_facts_json = models.JSONField(default=list, blank=True)
    title = models.CharField(max_length=255)
    summary = models.CharField(max_length=800)
    safe_next_step = models.CharField(max_length=500, blank=True, default='')
    recheck_condition = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slow_moving_alert_passports'
        constraints = [
            models.UniqueConstraint(
                fields=['alert_state', 'assessment_run'],
                name='slow_passport_alert_run_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'alert_state', '-created_at'],
                name='slow_passport_ws_alert_at_idx',
            ),
            models.Index(
                fields=['workspace', 'source_scope_fingerprint', '-created_at'],
                name='slow_passport_ws_scope_at_idx',
            ),
        ]


class SlowMovingAlertAttentionEvent(models.Model):
    """Append-only attention lifecycle event; never inferred from mutable state."""

    TYPE_OPENED = 'OPENED'
    TYPE_WORSENED = 'WORSENED'
    TYPE_REOPENED = 'REOPENED'
    TYPE_ACKNOWLEDGED = 'ACKNOWLEDGED'
    TYPE_SNOOZED = 'SNOOZED'
    TYPE_RESOLVED = 'RESOLVED'
    TYPE_DATA_BLOCKED = 'DATA_BLOCKED'
    TYPE_CHOICES = [
        (TYPE_OPENED, 'Mở cảnh báo'),
        (TYPE_WORSENED, 'Cảnh báo xấu đi'),
        (TYPE_REOPENED, 'Mở lại cảnh báo'),
        (TYPE_ACKNOWLEDGED, 'Đã tiếp nhận'),
        (TYPE_SNOOZED, 'Tạm ẩn'),
        (TYPE_RESOLVED, 'Đã xử lý'),
        (TYPE_DATA_BLOCKED, 'Cần kiểm tra dữ liệu'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_attention_events'
    )
    alert_state = models.ForeignKey(
        SlowMovingAlertState, on_delete=models.CASCADE, related_name='attention_events'
    )
    assessment_run = models.ForeignKey(
        SlowMovingAssessmentRun, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attention_events',
    )
    passport = models.ForeignKey(
        SlowMovingAlertPassport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attention_events',
    )
    event_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    reason_codes = models.JSONField(default=list, blank=True)
    note = models.CharField(max_length=500, blank=True, default='')
    actor = models.CharField(max_length=128, blank=True, default='')
    policy_version = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slow_moving_alert_attention_events'
        indexes = [
            models.Index(
                fields=['workspace', 'alert_state', '-created_at'],
                name='slow_attention_ws_alert_at_idx',
            ),
            models.Index(
                fields=['workspace', 'event_type', '-created_at'],
                name='slow_attention_ws_type_at_idx',
            ),
        ]


class SlowMovingAlertDigestDelivery(models.Model):
    """Idempotency ledger for in-app/email attention digests."""

    STATUS_QUEUED = 'QUEUED'
    STATUS_DELIVERED = 'DELIVERED'
    STATUS_SKIPPED = 'SKIPPED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Đã xếp hàng'),
        (STATUS_DELIVERED, 'Đã gửi'),
        (STATUS_SKIPPED, 'Không gửi'),
        (STATUS_FAILED, 'Gửi thất bại'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_alert_digest_deliveries'
    )
    source_key = models.CharField(max_length=128)
    owner_label = models.CharField(max_length=128, blank=True, default='')
    delivery_date = models.DateField(db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    alert_ids_json = models.JSONField(default=list, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'slow_moving_alert_digest_deliveries'
        indexes = [
            models.Index(
                fields=['workspace', 'source_key', 'delivery_date'],
                name='slow_digest_ws_source_day_idx',
            ),
        ]


class SlowMovingOutcomeCohort(models.Model):
    """Immutable decision cohort used to measure slow-moving alert quality.

    A row is created for every eligible SKU in a completed operational run so
    recall has a truthful denominator. ``opened_alert`` distinguishes the
    subset that the merchant actually saw after lifecycle confirmation.
    """

    STATUS_PENDING = 'PENDING'
    STATUS_MATURED = 'MATURED'
    STATUS_DATA_BLOCKED = 'DATA_BLOCKED'
    STATUS_CONFOUNDED = 'CONFOUNDED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Awaiting outcome'),
        (STATUS_MATURED, '60-day outcome mature'),
        (STATUS_DATA_BLOCKED, 'Outcome data incomplete'),
        (STATUS_CONFOUNDED, 'Outcome confounded by an operational event'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_outcome_cohorts'
    )
    assessment_run = models.ForeignKey(
        SlowMovingAssessmentRun, on_delete=models.CASCADE, related_name='outcome_cohorts'
    )
    assessment = models.OneToOneField(
        'supplyforge.SlowMovingRiskAssessment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='outcome_cohort',
    )
    integration_assessment = models.OneToOneField(
        'supplyforge.IntegrationOperationalRiskAssessment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='outcome_cohort',
    )
    alert_state = models.ForeignKey(
        SlowMovingAlertState, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='outcome_cohorts',
    )
    source_type = models.CharField(max_length=16, choices=SlowMovingAssessmentRun.SOURCE_CHOICES)
    source_key = models.CharField(max_length=128)
    source_scope = models.JSONField(default=dict, blank=True)
    source_scope_fingerprint = models.CharField(max_length=64, db_index=True)
    policy_version = models.CharField(max_length=64)
    policy_checksum = models.CharField(max_length=64, db_index=True)
    # ``assessment`` records for the current Odoo read model are deliberately
    # replaced on every refresh. This immutable source key keeps an outcome
    # cohort reproducible after that technical row is removed.
    source_assessment_key = models.CharField(max_length=192)
    source_sku = models.CharField(max_length=255, db_index=True)
    canonical_sku = models.CharField(max_length=255, db_index=True)
    decision_cutoff = models.DateTimeField()
    predicted_risk_class = models.CharField(max_length=20)
    opened_alert = models.BooleanField(default=False, db_index=True)
    opening_stock_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    opening_inventory_verified = models.BooleanField(default=False)
    # This is a cutoff-time weighting for future-demand precision. It is not
    # evidence that capital remained tied up at the outcome horizon.
    opening_capital_exposure = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    outcome_30_ends_at = models.DateTimeField()
    outcome_60_ends_at = models.DateTimeField()
    outcome_90_ends_at = models.DateTimeField()
    maturity_eligible_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    block_reason = models.CharField(max_length=128, blank=True, default='')
    confounder_types = models.JSONField(default=list, blank=True)
    # Decision-time evidence is frozen separately from the mutable current
    # assessment read model so model/rule comparisons remain time-aware.
    rule_snapshot_json = models.JSONField(default=dict, blank=True)
    segment_json = models.JSONField(default=dict, blank=True)
    model_diagnostic_json = models.JSONField(default=dict, blank=True)

    future_net_fulfilled_units_30 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    future_net_fulfilled_units_60 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    future_net_fulfilled_units_90 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    outcome_30_observed_at = models.DateTimeField(null=True, blank=True)
    outcome_60_observed_at = models.DateTimeField(null=True, blank=True)
    outcome_90_observed_at = models.DateTimeField(null=True, blank=True)
    label_revision = models.PositiveIntegerField(default=0)
    label_revision_reason = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'slow_moving_outcome_cohorts'
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'source_key', 'source_assessment_key'],
                name='slow_outcome_source_assessment_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['workspace', 'source_key', 'policy_checksum', 'maturity_eligible_at'],
                name='slow_outcome_maturity_idx',
            ),
            models.Index(
                fields=['workspace', 'source_scope_fingerprint', 'decision_cutoff'],
                name='slow_outcome_scope_cutoff_idx',
            ),
            models.Index(
                fields=['workspace', 'opened_alert', 'status'],
                name='slow_outcome_open_status_idx',
            ),
        ]


class SlowMovingDispositionEvent(models.Model):
    """Lineaged operational event that invalidates a clean demand outcome.

    The record says that an outcome is confounded, not that a merchant action
    caused a revenue or capital result. Events are append-only so quality
    reports remain reproducible.
    """

    TYPE_STOCKOUT = 'STOCKOUT'
    TYPE_DELISTED = 'DELISTED'
    TYPE_STOCK_TRANSFER = 'STOCK_TRANSFER'
    TYPE_SUPPLIER_RETURN = 'SUPPLIER_RETURN'
    TYPE_INVENTORY_ADJUSTMENT = 'INVENTORY_ADJUSTMENT'
    TYPE_CHOICES = [
        (TYPE_STOCKOUT, 'Stockout'),
        (TYPE_DELISTED, 'Delisted'),
        (TYPE_STOCK_TRANSFER, 'Stock transfer'),
        (TYPE_SUPPLIER_RETURN, 'Supplier return'),
        (TYPE_INVENTORY_ADJUSTMENT, 'Inventory adjustment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_disposition_events'
    )
    source_type = models.CharField(max_length=16, choices=SlowMovingAssessmentRun.SOURCE_CHOICES)
    source_key = models.CharField(max_length=128)
    source_scope_fingerprint = models.CharField(max_length=64, db_index=True)
    canonical_sku = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    occurred_at = models.DateTimeField(db_index=True)
    evidence_reference = models.CharField(max_length=512, blank=True, default='')
    provenance_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slow_moving_disposition_events'
        indexes = [
            models.Index(
                fields=['workspace', 'source_scope_fingerprint', 'canonical_sku', 'occurred_at'],
                name='slow_disp_scope_sku_time_idx',
            ),
            models.Index(
                fields=['workspace', 'source_key', 'event_type', 'occurred_at'],
                name='slow_disp_source_type_time_idx',
            ),
        ]


class SlowMovingAlertFeedback(models.Model):
    """Append-only merchant feedback, deliberately separate from outcome truth."""

    REASON_ACCEPTED = 'ACCEPTED'
    REASON_DATA_INCORRECT = 'DATA_INCORRECT'
    REASON_STOCK_MOVED = 'STOCK_ALREADY_MOVED'
    REASON_SEASONAL = 'SEASONAL_ITEM'
    REASON_PLANNED_CAMPAIGN = 'PLANNED_CAMPAIGN'
    REASON_REPLACEMENT_SKU = 'REPLACEMENT_SKU'
    REASON_DISPLAY_STOCK = 'DISPLAY_STOCK'
    REASON_BUNDLE_COMPONENT = 'BUNDLE_COMPONENT'
    REASON_NON_SELLABLE_STOCK = 'NON_SELLABLE_STOCK'
    REASON_PREORDER_OR_CONSIGNMENT = 'PREORDER_OR_CONSIGNMENT'
    REASON_MAPPING_ISSUE = 'MAPPING_ISSUE'
    REASON_NOT_RELEVANT = 'NOT_RELEVANT'
    REASON_SNOOZED = 'SNOOZED'
    REASON_RESOLVED = 'RESOLVED'
    REASON_CHOICES = [
        (REASON_ACCEPTED, 'Accepted'),
        (REASON_DATA_INCORRECT, 'Data incorrect'),
        (REASON_STOCK_MOVED, 'Stock already moved'),
        (REASON_SEASONAL, 'Seasonal item'),
        (REASON_PLANNED_CAMPAIGN, 'Planned campaign'),
        (REASON_REPLACEMENT_SKU, 'Replacement SKU'),
        (REASON_DISPLAY_STOCK, 'Display stock'),
        (REASON_BUNDLE_COMPONENT, 'Bundle or component'),
        (REASON_NON_SELLABLE_STOCK, 'Stock is not sellable'),
        (REASON_PREORDER_OR_CONSIGNMENT, 'Preorder or consignment'),
        (REASON_MAPPING_ISSUE, 'SKU or warehouse mapping issue'),
        (REASON_NOT_RELEVANT, 'Not relevant'),
        (REASON_SNOOZED, 'Snoozed'),
        (REASON_RESOLVED, 'Resolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_alert_feedback'
    )
    alert_state = models.ForeignKey(
        SlowMovingAlertState, on_delete=models.CASCADE, related_name='feedback_events'
    )
    action = models.CharField(max_length=20)
    reason = models.CharField(max_length=32, choices=REASON_CHOICES)
    note = models.CharField(max_length=500, blank=True, default='')
    evidence_reference = models.CharField(max_length=512, blank=True, default='')
    submitted_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slow_moving_alert_feedback'
        indexes = [
            models.Index(fields=['workspace', 'reason', '-created_at'], name='slow_feedback_reason_idx'),
            models.Index(fields=['alert_state', '-created_at'], name='slow_feedback_alert_idx'),
        ]


class SlowMovingFeedbackRemediation(models.Model):
    """A visible follow-up created from merchant feedback.

    It records a data or catalogue correction process. Completing this work
    never mutates an assessment, score, policy threshold or mature outcome.
    """

    STATUS_OPEN = 'OPEN'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Cần xử lý'),
        (STATUS_IN_PROGRESS, 'Đang xử lý'),
        (STATUS_COMPLETED, 'Đã hoàn thành'),
        (STATUS_CANCELLED, 'Không thực hiện'),
    ]
    TYPE_DATA = 'DATA'
    TYPE_CATALOG = 'CATALOG'
    TYPE_OPERATIONS = 'OPERATIONS'
    TYPE_CHOICES = [
        (TYPE_DATA, 'Xác minh dữ liệu'),
        (TYPE_CATALOG, 'Cập nhật danh mục'),
        (TYPE_OPERATIONS, 'Theo dõi vận hành'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        'supplyforge.Workspace', on_delete=models.CASCADE, related_name='slow_moving_feedback_remediations'
    )
    alert_state = models.ForeignKey(
        SlowMovingAlertState, on_delete=models.CASCADE, related_name='feedback_remediations'
    )
    feedback = models.ForeignKey(
        SlowMovingAlertFeedback, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='remediations',
    )
    # Stable, generated scope key makes repeat feedback safe to retry.
    open_key = models.CharField(max_length=255, unique=True)
    remediation_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    title = models.CharField(max_length=255)
    detail = models.CharField(max_length=800, blank=True, default='')
    owner_label = models.CharField(max_length=128, blank=True, default='')
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    evidence_reference = models.CharField(max_length=512, blank=True, default='')
    outcome_note = models.CharField(max_length=800, blank=True, default='')
    completed_by = models.CharField(max_length=128, blank=True, default='')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'slow_moving_feedback_remediations'
        indexes = [
            models.Index(
                fields=['workspace', 'status', 'due_at'],
                name='slow_remed_ws_status_due_idx',
            ),
            models.Index(
                fields=['alert_state', 'status', '-created_at'],
                name='slow_remed_alert_status_idx',
            ),
        ]
