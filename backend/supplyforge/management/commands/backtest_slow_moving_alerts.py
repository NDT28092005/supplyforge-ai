"""Export leakage-safe quality evidence from frozen slow-moving cohorts."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from supplyforge.models import SlowMovingAssessmentRun, SlowMovingOutcomeCohort
from supplyforge.services.slow_moving_policy_backtest import (
    SlowMovingPolicyReplayError,
    SlowMovingPolicyReplayService,
    load_candidate_policy,
)
from supplyforge.services.slow_moving_quality_monitoring import SlowMovingQualityMonitoringService
from supplyforge.services.slow_moving_quality_policy import load_slow_moving_quality_policy


class Command(BaseCommand):
    help = (
        'Export quality evidence from immutable rolling slow-moving decision cohorts. '
        'The command never changes a policy or score threshold.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--workspace-id', type=int, required=True)
        parser.add_argument('--source', default='CSV')
        parser.add_argument('--output-dir', type=Path, required=True)
        parser.add_argument(
            '--candidate-policy', type=Path,
            help=(
                'Tệp replay v1 chỉ thay đổi ngưỡng mức cần xem và số lần xác nhận. '
                'Thay đổi điều kiện dữ liệu/tình trạng hàng phải chạy lại từ nguồn đóng băng.'
            ),
        )
        parser.add_argument(
            '--baseline-policy-checksum', default='',
            help='Checksum chính sách gốc; mặc định là chính sách của lần đánh giá hiện hành.',
        )

    def handle(self, *args, **options):
        requested_source = str(options['source'] or 'CSV')
        source_key = (
            'CSV' if requested_source.upper() == 'CSV'
            else f"ODOO:{requested_source.split(':', 1)[1].lower()}"
            if requested_source.upper().startswith('ODOO:') else None
        )
        if source_key is None:
            raise CommandError('--source phải là CSV hoặc ODOO:<connection-id>.')
        current_run = SlowMovingAssessmentRun.objects.filter(
            workspace_id=options['workspace_id'],
            source_key=source_key,
            status=SlowMovingAssessmentRun.STATUS_COMPLETED,
            is_current=True,
        ).order_by('-completed_at').first()
        if not current_run:
            raise CommandError('Không có lần đánh giá hiện hành để tạo bằng chứng kiểm chứng.')
        report = SlowMovingQualityMonitoringService.report(
            workspace_id=options['workspace_id'], source_key=source_key,
        )
        quality_policy, quality_policy_checksum = load_slow_moving_quality_policy()
        cohorts = list(SlowMovingOutcomeCohort.objects.filter(
            workspace_id=options['workspace_id'],
            source_key=source_key,
            source_scope_fingerprint=current_run.source_scope_fingerprint,
        ).order_by('decision_cutoff', 'source_assessment_key').only(
            'id', 'status', 'policy_checksum', 'decision_cutoff', 'predicted_risk_class',
            'opened_alert', 'future_net_fulfilled_units_30',
            'future_net_fulfilled_units_60', 'future_net_fulfilled_units_90',
            'block_reason', 'source_scope_fingerprint', 'canonical_sku',
            'source_assessment_key', 'rule_snapshot_json', 'segment_json',
        ))
        if not cohorts:
            raise CommandError('Không có cohort đóng băng đúng phạm vi để kiểm chứng. Không tạo báo cáo trống.')
        status_counts = Counter(cohort.status for cohort in cohorts)
        policy_counts = Counter(cohort.policy_checksum for cohort in cohorts)
        frozen_rows = [
            {
                'id': str(cohort.id),
                'cutoff': cohort.decision_cutoff.isoformat(),
                'policy': cohort.policy_checksum,
                'risk_class': cohort.predicted_risk_class,
                'opened': cohort.opened_alert,
                'status': cohort.status,
                'outcome_30': str(cohort.future_net_fulfilled_units_30),
                'outcome_60': str(cohort.future_net_fulfilled_units_60),
                'outcome_90': str(cohort.future_net_fulfilled_units_90),
                'block_reason': cohort.block_reason,
            }
            for cohort in cohorts
        ]
        evidence_checksum = hashlib.sha256(
            json.dumps(frozen_rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        ).hexdigest()
        report['backtest_manifest'] = {
            'source_run_id': str(current_run.id),
            'source_key': source_key,
            'source_scope_fingerprint': current_run.source_scope_fingerprint,
            'evaluated_score_policy_checksum': current_run.policy_checksum,
            'quality_policy_checksum': quality_policy_checksum,
            'primary_outcome_days': int(quality_policy['primary_horizon_days']),
            'sensitivity_outcome_days': list(quality_policy['sensitivity_horizon_days']),
            'cohort_count': len(cohorts),
            'cutoff_dates': sorted({cohort.decision_cutoff.date().isoformat() for cohort in cohorts}),
            'status_counts': dict(sorted(status_counts.items())),
            'policy_counts': dict(sorted(policy_counts.items())),
            'frozen_evidence_checksum': evidence_checksum,
            'selection_boundary': (
                'Chỉ dùng cohort đúng workspace, nguồn và phạm vi đã đóng băng. '
                'Cohort chưa đủ 60 ngày, thiếu dữ liệu hoặc bị nhiễu không nằm trong mẫu đánh giá chính.'
            ),
        }
        # This command evaluates historical evidence. It must not manufacture
        # an old-vs-new result without a separately frozen candidate replay.
        candidate_path = options.get('candidate_policy')
        if candidate_path:
            try:
                candidate_policy, candidate_policy_checksum = load_candidate_policy(candidate_path.resolve())
                baseline_checksum = str(options.get('baseline_policy_checksum') or current_run.policy_checksum)
                baseline_cohorts = [
                    cohort for cohort in cohorts if cohort.policy_checksum == baseline_checksum
                ]
                if not baseline_cohorts:
                    raise SlowMovingPolicyReplayError('Không có cohort nào cho chính sách gốc trong đúng phạm vi hiện hành.')
                comparison = SlowMovingPolicyReplayService.replay(
                    cohorts=baseline_cohorts,
                    candidate_policy=candidate_policy,
                    quality_policy=quality_policy,
                )
                report['policy_comparison'] = {
                    'state': 'REPLAY_COMPLETED',
                    'baseline_policy_checksum': baseline_checksum,
                    'candidate_policy_checksum': candidate_policy_checksum,
                    **comparison,
                    'approval_state': 'REQUIRES_SEPARATE_APPROVAL',
                    'message': (
                        'Kết quả replay là bằng chứng để xem xét, không tự thay đổi cảnh báo, nhắc việc hoặc dữ liệu lịch sử.'
                    ),
                }
            except SlowMovingPolicyReplayError as exc:
                raise CommandError(str(exc)) from exc
        else:
            report['policy_comparison'] = {
                'state': 'CANDIDATE_REPLAY_REQUIRED',
                'message': (
                    'Báo cáo này không tự so sánh hay chọn chính sách mới. Cần một lần chạy thử '
                    'được đóng băng trên cùng các mốc dữ liệu trước khi có thể so sánh hai chính sách.'
                ),
            }
        output_dir = options['output_dir'].resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            'json': output_dir / 'slow_moving_backtest.json',
            'csv': output_dir / 'slow_moving_backtest_cohorts.csv',
            'markdown': output_dir / 'slow_moving_backtest.md',
        }
        existing = [path for path in paths.values() if path.exists()]
        if existing:
            raise CommandError(f'Refusing to overwrite existing output: {existing[0]}')
        paths['json'].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        rows = report.get('cohorts') or []
        headers = [
            'decision_cutoff_date', 'matured_eligible_skus', 'opened_high_risk_alert_count',
            'opened_critical_alert_count', 'high_risk_precision', 'high_risk_precision_wilson_lower',
            'high_risk_recall', 'critical_precision', 'critical_precision_wilson_lower',
            'opened_alert_rate', 'label_revision_rate',
        ]
        with paths['csv'].open('x', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows([{field: row.get(field) for field in headers} for row in rows])
        metrics = report.get('metrics') or {}
        markdown = [
            '# Slow-Moving Frozen Cohort Backtest',
            '',
            f"- State: `{report.get('state')}`",
            f"- Source run: `{report.get('source_run_id', 'none')}`",
            f"- Mature eligible SKUs: `{metrics.get('matured_eligible_skus', 0)}`",
            f"- Opened C+H alerts: `{metrics.get('opened_high_risk_alert_count', 0)}`",
            f"- Tỷ lệ cảnh báo C+H phù hợp sau 60 ngày: `{metrics.get('high_risk_precision')}`",
            f"- Mức thận trọng tối thiểu của tỷ lệ này: `{metrics.get('high_risk_precision_wilson_lower')}`",
            f"- Tỷ lệ SKU bán chậm đã được nhận diện: `{metrics.get('high_risk_recall')}`",
            f"- Frozen evidence checksum: `{evidence_checksum}`",
            '',
            'Báo cáo chỉ đánh giá dữ liệu đã đóng băng tại từng mốc và kết quả đã đủ thời gian theo dõi. Báo cáo không tự điều chỉnh điểm ưu tiên hoặc chính sách.',
            'So sánh chính sách cũ/mới chỉ được thực hiện sau khi có candidate replay độc lập trên cùng các mốc dữ liệu.',
            '',
        ]
        paths['markdown'].write_text('\n'.join(markdown), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(
            f"Wrote slow-moving cohort evidence: {paths['json']}, {paths['csv']}, {paths['markdown']}"
        ))
