import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('supplyforge', '0093_decision_review_weekly_actions_and_outcome_closeout'),
    ]

    operations = [
        migrations.AddField(
            model_name='slowmovingalertstate',
            name='owner_label',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='slowmovingalertstate',
            name='next_review_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='slowmovingalertstate',
            name='last_signal_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='slowmovingalertstate',
            name='last_signal_fingerprint',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='slowmovingalertstate',
            name='last_material_change_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='slowmovingalertfeedback',
            name='reason',
            field=models.CharField(choices=[('ACCEPTED', 'Accepted'), ('DATA_INCORRECT', 'Data incorrect'), ('STOCK_ALREADY_MOVED', 'Stock already moved'), ('SEASONAL_ITEM', 'Seasonal item'), ('PLANNED_CAMPAIGN', 'Planned campaign'), ('REPLACEMENT_SKU', 'Replacement SKU'), ('DISPLAY_STOCK', 'Display stock'), ('BUNDLE_COMPONENT', 'Bundle or component'), ('NON_SELLABLE_STOCK', 'Stock is not sellable'), ('PREORDER_OR_CONSIGNMENT', 'Preorder or consignment'), ('MAPPING_ISSUE', 'SKU or warehouse mapping issue'), ('NOT_RELEVANT', 'Not relevant'), ('SNOOZED', 'Snoozed'), ('RESOLVED', 'Resolved')], max_length=32),
        ),
        migrations.CreateModel(
            name='SlowMovingSkuContext',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canonical_sku', models.CharField(db_index=True, max_length=255)),
                ('source_key', models.CharField(blank=True, default='', max_length=128)),
                ('warehouse_code', models.CharField(blank=True, default='', max_length=128)),
                ('channel', models.CharField(blank=True, default='', max_length=128)),
                ('availability', models.CharField(choices=[('SELLABLE', 'Có thể bán'), ('HELD', 'Đang giữ chỗ'), ('DAMAGED', 'Hàng hỏng hoặc kiểm kê'), ('PREORDER', 'Hàng đặt trước'), ('CONSIGNMENT', 'Hàng ký gửi'), ('UNKNOWN', 'Chưa xác nhận khả năng bán')], max_length=24)),
                ('catalog_role', models.CharField(choices=[('STANDALONE', 'SKU độc lập'), ('VARIANT', 'Biến thể'), ('PARENT', 'Sản phẩm cha'), ('BUNDLE', 'Sản phẩm bán theo gói'), ('COMPONENT', 'Linh kiện của gói'), ('REPLACEMENT', 'SKU thay thế'), ('SEASONAL', 'Sản phẩm theo mùa'), ('NEW_LAUNCH', 'Sản phẩm mới mở bán'), ('END_OF_LIFE', 'Sản phẩm ngừng bán'), ('UNKNOWN', 'Chưa xác nhận loại sản phẩm')], default='STANDALONE', max_length=24)),
                ('related_canonical_sku', models.CharField(blank=True, default='', max_length=255)),
                ('conversion_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)),
                ('effective_from', models.DateTimeField(db_index=True, default=timezone.now)),
                ('effective_to', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('evidence_reference', models.CharField(blank=True, default='', max_length=512)),
                ('provenance_json', models.JSONField(blank=True, default=dict)),
                ('declared_by', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_sku_contexts', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_sku_contexts'},
        ),
        migrations.AddIndex(
            model_name='slowmovingskucontext',
            index=models.Index(fields=['workspace', 'canonical_sku', 'source_key', 'effective_from'], name='slow_ctx_ws_sku_source_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingskucontext',
            index=models.Index(fields=['workspace', 'warehouse_code', 'effective_from'], name='slow_ctx_ws_wh_time_idx'),
        ),
        migrations.CreateModel(
            name='SlowMovingAlertPassport',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('event_type', models.CharField(choices=[('OPENED', 'Mở cảnh báo'), ('WORSENED', 'Cảnh báo xấu đi'), ('REOPENED', 'Mở lại cảnh báo'), ('DATA_BLOCKED', 'Cần kiểm tra dữ liệu'), ('RECHECK', 'Kiểm tra lại')], max_length=24)),
                ('source_scope_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('previous_facts_json', models.JSONField(blank=True, default=dict)),
                ('current_facts_json', models.JSONField(blank=True, default=dict)),
                ('changed_facts_json', models.JSONField(blank=True, default=list)),
                ('title', models.CharField(max_length=255)),
                ('summary', models.CharField(max_length=800)),
                ('safe_next_step', models.CharField(blank=True, default='', max_length=500)),
                ('recheck_condition', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('alert_state', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='passports', to='supplyforge.slowmovingalertstate')),
                ('assessment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='alert_passports', to='supplyforge.slowmovingriskassessment')),
                ('assessment_run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alert_passports', to='supplyforge.slowmovingassessmentrun')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_alert_passports', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_alert_passports'},
        ),
        migrations.AddConstraint(
            model_name='slowmovingalertpassport',
            constraint=models.UniqueConstraint(fields=('alert_state', 'assessment_run'), name='slow_passport_alert_run_uq'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertpassport',
            index=models.Index(fields=['workspace', 'alert_state', '-created_at'], name='slow_passport_ws_alert_at_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertpassport',
            index=models.Index(fields=['workspace', 'source_scope_fingerprint', '-created_at'], name='slow_passport_ws_scope_at_idx'),
        ),
        migrations.CreateModel(
            name='SlowMovingAlertAttentionEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('event_type', models.CharField(choices=[('OPENED', 'Mở cảnh báo'), ('WORSENED', 'Cảnh báo xấu đi'), ('REOPENED', 'Mở lại cảnh báo'), ('ACKNOWLEDGED', 'Đã tiếp nhận'), ('SNOOZED', 'Tạm ẩn'), ('RESOLVED', 'Đã xử lý'), ('DATA_BLOCKED', 'Cần kiểm tra dữ liệu')], max_length=24)),
                ('reason_codes', models.JSONField(blank=True, default=list)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('actor', models.CharField(blank=True, default='', max_length=128)),
                ('policy_version', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('alert_state', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attention_events', to='supplyforge.slowmovingalertstate')),
                ('assessment_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attention_events', to='supplyforge.slowmovingassessmentrun')),
                ('passport', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attention_events', to='supplyforge.slowmovingalertpassport')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_attention_events', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_alert_attention_events'},
        ),
        migrations.AddIndex(
            model_name='slowmovingalertattentionevent',
            index=models.Index(fields=['workspace', 'alert_state', '-created_at'], name='slow_attention_ws_alert_at_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingalertattentionevent',
            index=models.Index(fields=['workspace', 'event_type', '-created_at'], name='slow_attention_ws_type_at_idx'),
        ),
        migrations.CreateModel(
            name='SlowMovingAlertDigestDelivery',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_key', models.CharField(max_length=128)),
                ('owner_label', models.CharField(blank=True, default='', max_length=128)),
                ('delivery_date', models.DateField(db_index=True)),
                ('idempotency_key', models.CharField(max_length=255, unique=True)),
                ('status', models.CharField(choices=[('QUEUED', 'Đã xếp hàng'), ('DELIVERED', 'Đã gửi'), ('SKIPPED', 'Không gửi'), ('FAILED', 'Gửi thất bại')], default='QUEUED', max_length=16)),
                ('alert_ids_json', models.JSONField(blank=True, default=list)),
                ('failure_reason', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_alert_digest_deliveries', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_alert_digest_deliveries'},
        ),
        migrations.AddIndex(
            model_name='slowmovingalertdigestdelivery',
            index=models.Index(fields=['workspace', 'source_key', 'delivery_date'], name='slow_digest_ws_source_day_idx'),
        ),
        migrations.CreateModel(
            name='SlowMovingFeedbackRemediation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('open_key', models.CharField(max_length=255, unique=True)),
                ('remediation_type', models.CharField(choices=[('DATA', 'Xác minh dữ liệu'), ('CATALOG', 'Cập nhật danh mục'), ('OPERATIONS', 'Theo dõi vận hành')], max_length=24)),
                ('status', models.CharField(choices=[('OPEN', 'Cần xử lý'), ('IN_PROGRESS', 'Đang xử lý'), ('COMPLETED', 'Đã hoàn thành'), ('CANCELLED', 'Không thực hiện')], db_index=True, default='OPEN', max_length=24)),
                ('title', models.CharField(max_length=255)),
                ('detail', models.CharField(blank=True, default='', max_length=800)),
                ('owner_label', models.CharField(blank=True, default='', max_length=128)),
                ('due_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('evidence_reference', models.CharField(blank=True, default='', max_length=512)),
                ('outcome_note', models.CharField(blank=True, default='', max_length=800)),
                ('completed_by', models.CharField(blank=True, default='', max_length=128)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('alert_state', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback_remediations', to='supplyforge.slowmovingalertstate')),
                ('feedback', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='remediations', to='supplyforge.slowmovingalertfeedback')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slow_moving_feedback_remediations', to='supplyforge.workspace')),
            ],
            options={'db_table': 'slow_moving_feedback_remediations'},
        ),
        migrations.AddIndex(
            model_name='slowmovingfeedbackremediation',
            index=models.Index(fields=['workspace', 'status', 'due_at'], name='slow_remed_ws_status_due_idx'),
        ),
        migrations.AddIndex(
            model_name='slowmovingfeedbackremediation',
            index=models.Index(fields=['alert_state', 'status', '-created_at'], name='slow_remed_alert_status_idx'),
        ),
    ]
