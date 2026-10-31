"""Workspace-scoped, provider-neutral commerce integration records."""

import uuid

from django.db import models


class WorkspaceEntitlement(models.Model):
    """Internal feature grant, intentionally separate from a future billing provider."""

    FEATURE_ERP_INTEGRATIONS = 'ERP_INTEGRATIONS'
    FEATURE_CHOICES = [(FEATURE_ERP_INTEGRATIONS, 'ERP integrations')]

    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='entitlements')
    feature_code = models.CharField(max_length=64, choices=FEATURE_CHOICES)
    is_enabled = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.CharField(max_length=128, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workspace_entitlements'
        constraints = [models.UniqueConstraint(fields=['workspace', 'feature_code'], name='ws_feature_entitlement_uq')]


class IntegrationConnection(models.Model):
    PROVIDER_ODOO = 'ODOO'
    PROVIDER_CHOICES = [(PROVIDER_ODOO, 'Odoo')]
    STATUS_DRAFT = 'DRAFT'
    STATUS_VALIDATING = 'VALIDATING'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_PAUSED = 'PAUSED'
    STATUS_ERROR = 'ERROR'
    STATUS_DISCONNECTED = 'DISCONNECTED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_VALIDATING, 'Validating'), (STATUS_ACTIVE, 'Active'),
        (STATUS_PAUSED, 'Paused'), (STATUS_ERROR, 'Error'), (STATUS_DISCONNECTED, 'Disconnected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('supplyforge.Workspace', on_delete=models.CASCADE, related_name='integration_connections')
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    display_name = models.CharField(max_length=128)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    base_url = models.URLField(max_length=512)
    external_database = models.CharField(max_length=128, blank=True, default='')
    external_company_id = models.CharField(max_length=128, blank=True, default='')
    external_company_name = models.CharField(max_length=255, blank=True, default='')
    warehouse_ids = models.JSONField(default=list, blank=True)
    warehouse_names = models.JSONField(default=list, blank=True)
    credential_encrypted = models.TextField(blank=True, default='')
    webhook_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    webhook_secret_hash = models.CharField(max_length=128, blank=True, default='')
    cursor_json = models.JSONField(default=dict, blank=True)
    last_successful_sync_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default='')
    last_error_message = models.CharField(max_length=512, blank=True, default='')
    created_by = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_connections'
        indexes = [
            models.Index(fields=['workspace', 'provider', 'status'], name='int_conn_ws_prov_status_idx'),
        ]


class IntegrationSyncRun(models.Model):
    TYPE_VALIDATE = 'VALIDATE'
    TYPE_INITIAL = 'INITIAL'
    TYPE_INCREMENTAL = 'INCREMENTAL'
    TYPE_RECONCILIATION = 'RECONCILIATION'
    TYPE_CHOICES = [(TYPE_VALIDATE, 'Validate'), (TYPE_INITIAL, 'Initial'), (TYPE_INCREMENTAL, 'Incremental'), (TYPE_RECONCILIATION, 'Reconciliation')]
    STATUS_PENDING = 'PENDING'
    STATUS_RUNNING = 'RUNNING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [(STATUS_PENDING, 'Pending'), (STATUS_RUNNING, 'Running'), (STATUS_COMPLETED, 'Completed'), (STATUS_FAILED, 'Failed')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='sync_runs')
    run_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    background_job = models.ForeignKey('supplyforge.BackgroundJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='integration_sync_runs')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cursor_before = models.JSONField(default=dict, blank=True)
    cursor_after = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default='')
    error_message = models.CharField(max_length=512, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_sync_runs'
        indexes = [models.Index(fields=['connection', 'created_at'], name='int_sync_conn_created_idx')]


class IntegrationEvent(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_PROCESSING = 'PROCESSING'
    STATUS_PROCESSED = 'PROCESSED'
    STATUS_NEEDS_MAPPING = 'NEEDS_MAPPING'
    STATUS_FAILED = 'FAILED'
    STATUS_CHOICES = [(STATUS_PENDING, 'Pending'), (STATUS_PROCESSING, 'Processing'), (STATUS_PROCESSED, 'Processed'), (STATUS_NEEDS_MAPPING, 'Needs mapping'), (STATUS_FAILED, 'Failed')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='events')
    external_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=64, db_index=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    payload_checksum = models.CharField(max_length=64)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error_code = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'integration_events'
        constraints = [models.UniqueConstraint(fields=['connection', 'external_event_id'], name='int_event_conn_external_uq')]
        indexes = [models.Index(fields=['connection', 'status', 'created_at'], name='int_event_conn_status_idx')]


class IntegrationSkuMapping(models.Model):
    STATUS_AUTO = 'AUTO_MAPPED'
    STATUS_REVIEW = 'NEEDS_REVIEW'
    STATUS_CONFIRMED = 'CONFIRMED'
    STATUS_IGNORED = 'IGNORED'
    STATUS_CHOICES = [(STATUS_AUTO, 'Auto mapped'), (STATUS_REVIEW, 'Needs review'), (STATUS_CONFIRMED, 'Confirmed'), (STATUS_IGNORED, 'Ignored')]

    METHOD_AUTO = 'AUTO'
    METHOD_MANUAL = 'MANUAL'
    METHOD_CHOICES = [(METHOD_AUTO, 'Automatic'), (METHOD_MANUAL, 'Manual')]

    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='sku_mappings')
    external_sku = models.CharField(max_length=255)
    external_name = models.CharField(max_length=512, blank=True, default='')
    # Retain the display SKU for auditability while linking to a stable local
    # product identity. A SKU code can be renamed after a mapping is approved.
    canonical_product = models.ForeignKey(
        'supplyforge.Product', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='erp_sku_mappings', db_column='canonical_product_id',
    )
    canonical_sku = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_REVIEW)
    mapping_method = models.CharField(max_length=16, choices=METHOD_CHOICES, blank=True, default='')
    mapped_by = models.CharField(max_length=128, blank=True, default='')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    ignored_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_sku_mappings'
        constraints = [models.UniqueConstraint(fields=['connection', 'external_sku'], name='int_mapping_conn_sku_uq')]


class IntegrationSkuMappingAudit(models.Model):
    """Immutable record of a merchant's mapping resolution decisions."""

    ACTION_AUTO = 'AUTO_MAPPED'
    ACTION_CONFIRMED = 'CONFIRMED'
    ACTION_CORRECTED = 'CORRECTED'
    ACTION_IGNORED = 'IGNORED'
    ACTION_REOPENED = 'REOPENED'
    ACTION_UNLINKED = 'UNLINKED'
    ACTION_CHOICES = [
        (ACTION_AUTO, 'Automatically mapped'),
        (ACTION_CONFIRMED, 'Confirmed'),
        (ACTION_CORRECTED, 'Corrected'),
        (ACTION_IGNORED, 'Ignored'),
        (ACTION_REOPENED, 'Reopened'),
        (ACTION_UNLINKED, 'Unlinked'),
    ]

    mapping = models.ForeignKey(IntegrationSkuMapping, on_delete=models.CASCADE, related_name='audit_events')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    previous_canonical_product_id = models.CharField(max_length=24, blank=True, default='')
    previous_canonical_sku = models.CharField(max_length=255, blank=True, default='')
    canonical_product_id_snapshot = models.CharField(max_length=24, blank=True, default='')
    canonical_sku = models.CharField(max_length=255, blank=True, default='')
    actor = models.CharField(max_length=128, blank=True, default='')
    note = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_sku_mapping_audits'
        indexes = [models.Index(fields=['mapping', 'created_at'], name='int_map_audit_map_at_idx')]


class IntegrationSkuDailyMetric(models.Model):
    """Provider-neutral operational facts used by ERP-backed screens.

    A metric is deliberately scoped to an integration connection and warehouse.
    This prevents a later SAP adapter, or a second legal entity, from mutating
    the CSV/legacy product projection owned by another source.
    """

    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name='daily_metrics',
    )
    external_sku = models.CharField(max_length=255)
    external_product_id = models.CharField(max_length=128, blank=True, default='')
    external_name = models.CharField(max_length=512, blank=True, default='')
    warehouse_id = models.CharField(max_length=128, blank=True, default='')
    warehouse_name = models.CharField(max_length=255, blank=True, default='')
    metric_date = models.DateField()
    sales_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    returned_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    receipt_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    revenue = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    on_hand_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'integration_sku_daily_metrics'
        constraints = [
            models.UniqueConstraint(
                fields=['connection', 'external_sku', 'warehouse_id', 'metric_date'],
                name='int_metric_conn_sku_wh_day_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['connection', 'metric_date'],
                name='int_metric_conn_day_idx',
            ),
            models.Index(
                fields=['connection', 'external_sku', 'metric_date'],
                name='int_metric_conn_sku_day_idx',
            ),
        ]


class IntegrationOperationalRiskSnapshot(models.Model):
    """Latest materialised operational risk view for one ERP connection.

    This is intentionally separate from ``SlowMovingRiskAssessment``. The
    latter is a reproducible CSV/LightGBM research result, while this table is
    rebuilt from the merchant's live ERP facts and approved SKU identities.
    Keeping both sources isolated prevents sales from being double counted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.OneToOneField(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name='operational_risk_snapshot',
    )
    source_data_as_of = models.DateField(null=True, blank=True)
    source_synced_at = models.DateTimeField(null=True, blank=True)
    risk_engine_version = models.CharField(max_length=64, default='odoo_operational_rules_v1')
    coverage = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, default='READY', db_index=True)
    calculated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_operational_risk_snapshots'


class IntegrationOperationalRiskAssessment(models.Model):
    """One live, explainable slow-moving assessment per mapped ERP SKU."""

    snapshot = models.ForeignKey(
        IntegrationOperationalRiskSnapshot,
        on_delete=models.CASCADE,
        related_name='assessments',
    )
    mapping = models.ForeignKey(
        IntegrationSkuMapping,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operational_assessments',
    )
    external_sku = models.CharField(max_length=255)
    canonical_sku = models.CharField(max_length=255, db_index=True)
    product_name = models.CharField(max_length=512, blank=True, default='')
    category = models.CharField(max_length=100, blank=True, default='ERP')
    risk_class = models.CharField(max_length=20, db_index=True)
    risk_probability = models.FloatField()
    risk_score = models.FloatField(db_index=True)
    primary_signals = models.JSONField(default=list)
    supporting_signals = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_operational_risk_assessments'
        constraints = [
            models.UniqueConstraint(
                fields=['snapshot', 'external_sku'],
                name='int_op_risk_snapshot_sku_uq',
            ),
        ]
        indexes = [
            models.Index(
                fields=['snapshot', 'risk_class', '-risk_score'],
                name='int_op_risk_class_score_idx',
            ),
            models.Index(
                fields=['snapshot', '-risk_score', 'external_sku'],
                name='int_op_risk_score_sku_idx',
            ),
        ]
