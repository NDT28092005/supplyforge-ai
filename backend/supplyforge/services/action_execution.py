"""Checklist creation, completion gates and reliable plan reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from supplyforge.models import (
    ActionPlanEvidence, ActionPlanReminderDelivery, ActionPlanTask, NotificationRecord,
)


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    title: str
    instruction: str
    required: bool = True


CHECKLISTS: dict[str, tuple[ChecklistItem, ...]] = {
    'DISCOUNT': (
        ChecklistItem('confirm_price_floor', 'Xác nhận giá sàn', 'Kiểm tra giá sau giảm vẫn đạt hàng rào lợi nhuận.'),
        ChecklistItem('publish_price', 'Cập nhật giá trên kênh bán', 'Lưu liên kết hoặc ảnh xác nhận giá đã áp dụng.'),
        ChecklistItem('verify_price_applied', 'Kiểm tra giá đã áp dụng', 'Sau khi cập nhật, đối chiếu giá hiển thị với mức đã phê duyệt và lưu bằng chứng.'),
        ChecklistItem('monitor_sales', 'Theo dõi doanh số trong chiến dịch', 'Kiểm tra doanh số và tồn kho tại các mốc đã hẹn.'),
    ),
    'CLEARANCE': (
        ChecklistItem('approve_clearance', 'Phê duyệt xả hàng', 'Ghi rõ lý do chấp nhận mức biên lợi nhuận của phương án.'),
        ChecklistItem('publish_clearance', 'Thiết lập giá xả hàng', 'Lưu bằng chứng giá và thời gian áp dụng.'),
        ChecklistItem('verify_price_applied', 'Kiểm tra giá đã áp dụng', 'Đối chiếu giá xả hiển thị với mức đã phê duyệt và lưu bằng chứng.'),
        ChecklistItem('close_campaign', 'Đóng chiến dịch và đối soát', 'Đối soát doanh số, hàng trả và tồn cuối kỳ.'),
    ),
    'BUNDLE': (
        ChecklistItem('confirm_bundle_stock', 'Xác nhận tồn của sản phẩm đi kèm', 'Không tạo gói nếu SKU đi kèm không đủ tồn.'),
        ChecklistItem('publish_bundle', 'Tạo gói bán', 'Lưu liên kết hoặc ảnh sản phẩm gói.'),
        ChecklistItem('monitor_bundle', 'Theo dõi doanh số gói', 'Đối soát số lượng từng SKU sau chiến dịch.'),
    ),
    'REPOSITION': (
        ChecklistItem('confirm_destination', 'Xác nhận kho hoặc kênh nhận hàng', 'Xác nhận người nhận và năng lực lưu kho/kênh bán.'),
        ChecklistItem('create_transfer', 'Tạo lệnh điều chuyển', 'Lưu mã phiếu điều chuyển hoặc bằng chứng giao nhận.'),
        ChecklistItem('confirm_receipt', 'Xác nhận hàng đã đến nơi', 'Đối soát số lượng thực nhận.'),
    ),
    'RETURN_TO_SUPPLIER': (
        ChecklistItem('confirm_return_terms', 'Xác nhận điều kiện hoàn trả', 'Kiểm tra nhà cung cấp, phiếu nhập gốc, số lượng và điều kiện hoàn trả.'),
        ChecklistItem('create_return_request', 'Tạo yêu cầu hoàn trả', 'Lưu mã yêu cầu hoàn trả và bằng chứng nhà cung cấp tiếp nhận.'),
        ChecklistItem('confirm_return_receipt', 'Đối soát hoàn trả', 'Lưu xác nhận nhận hàng hoặc chứng từ điều chỉnh công nợ.'),
    ),
    'STOP_REPLENISHMENT': (
        ChecklistItem('review_open_purchase_orders', 'Rà soát đơn mua đang mở', 'Xác nhận PO nào giữ, hoãn hoặc hủy.'),
        ChecklistItem('notify_procurement', 'Thông báo bộ phận mua hàng', 'Lưu bằng chứng đã thông báo.'),
    ),
    'REVIEW': (
        ChecklistItem('collect_missing_data', 'Bổ sung dữ liệu còn thiếu', 'Bổ sung tồn, giá vốn, giá bán hoặc nhu cầu bán được quan sát.'),
    ),
    'HOLD': (
        ChecklistItem('set_review_date', 'Đặt lịch rà soát lại', 'Chọn ngày xem lại tín hiệu bán hàng và tồn kho.'),
    ),
    'MONITOR': (
        ChecklistItem('monitor_sales', 'Theo dõi tín hiệu bán hàng', 'Theo dõi doanh số, tồn kho và hàng trả theo lịch.'),
    ),
    'PROMOTION': (
        ChecklistItem('confirm_price_floor', 'Xác nhận giá sàn', 'Kiểm tra toàn bộ chi phí trước khi chạy khuyến mại.'),
        ChecklistItem('publish_promotion', 'Thiết lập chương trình khuyến mại', 'Lưu liên kết hoặc ảnh xác nhận chương trình.'),
        ChecklistItem('verify_price_applied', 'Kiểm tra giá đã áp dụng', 'Đối chiếu giá/ưu đãi hiển thị với mức đã phê duyệt và lưu bằng chứng.'),
        ChecklistItem('monitor_sales', 'Theo dõi doanh số trong chiến dịch', 'Đối soát doanh số và chi phí quảng cáo.'),
    ),
}


class ActionExecutionService:
    @staticmethod
    def create_checklist(plan) -> list[ActionPlanTask]:
        templates = CHECKLISTS.get(plan.strategy, CHECKLISTS['MONITOR'])
        tasks: list[ActionPlanTask] = []
        plan_due = plan.due_date or (plan.start_date + timedelta(days=max(1, plan.duration_days or 1)))
        for index, item in enumerate(templates, start=1):
            # A price action has a meaningful immediate proof point and a
            # short post-publish check.  Other action types retain the plan
            # deadline unless a merchant deliberately changes a task date.
            if item.key.startswith(('confirm_', 'approve_', 'review_', 'set_')):
                task_due = plan.start_date
            elif item.key.startswith(('publish_', 'create_')):
                task_due = min(plan_due, plan.start_date + timedelta(days=1))
            elif item.key.startswith('verify_'):
                task_due = min(plan_due, plan.start_date + timedelta(days=1))
            elif item.key.startswith(('monitor_', 'close_')):
                task_due = plan_due
            else:
                task_due = plan_due
            task, _ = ActionPlanTask.objects.get_or_create(
                plan=plan,
                task_key=item.key,
                defaults={
                    'title': item.title,
                    'instruction': item.instruction,
                    'is_required': item.required,
                    'sort_order': index,
                    'due_date': task_due,
                    'assignee_user': plan.assignee_user,
                },
            )
            tasks.append(task)
        return tasks

    @staticmethod
    def serialise_task(task: ActionPlanTask) -> dict:
        evidence = list(task.evidence.all()) if hasattr(task, '_prefetched_objects_cache') else list(task.evidence.all())
        return {
            'id': task.id,
            'task_key': task.task_key,
            'title': task.title,
            'instruction': task.instruction,
            'is_required': task.is_required,
            'status': task.status,
            'due_date': task.due_date.isoformat() if task.due_date else None,
            'assignee': ({
                'user_id': task.assignee_user_id,
                'display_name': task.assignee_user.display_name or task.assignee_user.email,
            } if task.assignee_user_id and task.assignee_user else None),
            'completion_note': task.completion_note,
            'skipped_reason': task.skipped_reason,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'evidence': [{
                'id': item.id, 'type': item.evidence_type, 'title': item.title,
                'reference_url': item.reference_url, 'note': item.note,
                'submitted_by': item.submitted_by, 'created_at': item.created_at.isoformat(),
            } for item in evidence],
        }

    @classmethod
    def task_summary(cls, plan) -> dict:
        tasks = list(plan.tasks.select_related('assignee_user').prefetch_related('evidence').all())
        required = [task for task in tasks if task.is_required]
        done = [task for task in required if task.status in {ActionPlanTask.STATUS_COMPLETED, ActionPlanTask.STATUS_SKIPPED}]
        return {
            'total': len(tasks),
            'required_total': len(required),
            'required_resolved': len(done),
            'is_ready_to_complete': len(done) == len(required),
            'items': [cls.serialise_task(task) for task in tasks],
        }

    @staticmethod
    @transaction.atomic
    def update_task(*, task: ActionPlanTask, status: str, actor: str, note: str = '', skipped_reason: str = '', due_date=None, assignee_user=None) -> ActionPlanTask:
        status = str(status or '').upper()
        if status not in dict(ActionPlanTask.STATUS_CHOICES):
            raise ValueError('Trạng thái công việc không hợp lệ.')
        if status == ActionPlanTask.STATUS_SKIPPED and len(skipped_reason.strip()) < 8:
            raise ValueError('Cần nêu lý do không thực hiện tối thiểu 8 ký tự.')
        if status == ActionPlanTask.STATUS_COMPLETED and task.is_required and not task.evidence.exists():
            raise ValueError('Công việc bắt buộc cần ít nhất một bằng chứng hoàn thành.')
        task.status = status
        task.completion_note = note.strip()
        task.skipped_reason = skipped_reason.strip() if status == ActionPlanTask.STATUS_SKIPPED else ''
        if status in {ActionPlanTask.STATUS_COMPLETED, ActionPlanTask.STATUS_SKIPPED}:
            task.completed_by = actor[:128]
            task.completed_at = timezone.now()
        else:
            task.completed_by, task.completed_at = '', None
        if due_date is not None:
            task.due_date = due_date
        if assignee_user is not None:
            task.assignee_user = assignee_user
        task.save()
        return task

    @staticmethod
    def add_evidence(*, task: ActionPlanTask, evidence_type: str, title: str, reference_url: str, note: str, actor: str) -> ActionPlanEvidence:
        if not title.strip():
            raise ValueError('Cần mô tả bằng chứng.')
        if not reference_url.strip() and not note.strip():
            raise ValueError('Cần cung cấp liên kết hoặc ghi chú bằng chứng.')
        return ActionPlanEvidence.objects.create(
            task=task, evidence_type=(evidence_type or 'LINK').upper()[:32], title=title.strip()[:255],
            reference_url=reference_url.strip(), note=note.strip(), submitted_by=actor[:128],
        )


class ActionReminderService:
    """Create delivery records before sending so retries never duplicate a reminder."""

    OFFSETS = (7, 3, 1, 0, -1)

    @classmethod
    def _deliver(cls, *, plan, task, reminder_key: str, recipient: str, title: str, message: str) -> tuple[int, int, int]:
        """Deliver one deduplicated notification per channel and reminder key."""
        sent = failed = skipped = 0
        for channel in (ActionPlanReminderDelivery.CHANNEL_IN_APP, ActionPlanReminderDelivery.CHANNEL_EMAIL):
            channel_recipient = recipient if channel == ActionPlanReminderDelivery.CHANNEL_EMAIL else ''
            try:
                delivery, created = ActionPlanReminderDelivery.objects.get_or_create(
                    plan=plan, task=task, channel=channel, reminder_key=reminder_key,
                    defaults={'recipient': channel_recipient},
                )
            except IntegrityError:
                skipped += 1
                continue
            if not created or delivery.status == ActionPlanReminderDelivery.STATUS_SENT:
                skipped += 1
                continue
            try:
                if channel == ActionPlanReminderDelivery.CHANNEL_IN_APP:
                    NotificationRecord.objects.create(
                        workspace_id=plan.workspace_id,
                        notification_type=NotificationRecord.TRIGGER_ACTION_DEADLINE_APPROACHING,
                        title=title,
                        message=message,
                        severity=NotificationRecord.SEVERITY_WARNING,
                        related_sku=plan.sku,
                        action_url=f'/app/decisions?plan={plan.plan_id}',
                    )
                elif channel_recipient:
                    send_mail('Nhắc việc SupplyForge', message, None, [channel_recipient], fail_silently=False)
                else:
                    skipped += 1
                    continue
                delivery.status, delivery.sent_at, delivery.attempt_count = 'SENT', timezone.now(), delivery.attempt_count + 1
                delivery.save(update_fields=['status', 'sent_at', 'attempt_count', 'updated_at'])
                sent += 1
            except Exception as exc:
                delivery.status, delivery.last_error, delivery.attempt_count = 'FAILED', str(exc)[:512], delivery.attempt_count + 1
                delivery.save(update_fields=['status', 'last_error', 'attempt_count', 'updated_at'])
                failed += 1
        return sent, failed, skipped

    @classmethod
    def send_due_reminders(cls, today=None) -> dict:
        from supplyforge.models import ActionPlanRecord

        today = today or timezone.localdate()
        sent, failed, skipped = 0, 0, 0
        plans = ActionPlanRecord.objects.exclude(status__in=['COMPLETED', 'CANCELLED']).select_related('assignee_user')
        for plan in plans.iterator(chunk_size=200):
            due = plan.due_date
            if not due:
                continue
            days_remaining = (due - today).days
            if days_remaining not in cls.OFFSETS:
                continue
            reminder_key = f'plan:{plan.plan_id}:due:{due.isoformat()}:offset:{days_remaining}'
            recipients = []
            if plan.assignee_user and plan.assignee_user.email:
                recipients.append(plan.assignee_user.email)
            increment = cls._deliver(
                plan=plan, task=None, reminder_key=reminder_key,
                recipient=recipients[0] if recipients else '',
                title='Kế hoạch sắp đến hạn' if days_remaining >= 0 else 'Kế hoạch đã quá hạn',
                message=f'Kế hoạch xử lý SKU {plan.sku} đến hạn {due.strftime("%d/%m/%Y")}. Hãy kiểm tra checklist và cập nhật kết quả.',
            )
            sent += increment[0]
            failed += increment[1]
            skipped += increment[2]

        # A plan deadline alone is too late for a team to recover.  Group all
        # open tasks due on the same day into one concise digest per plan to
        # avoid one notification per checkbox.
        open_tasks = ActionPlanTask.objects.filter(
            plan__status__in=['DRAFT', 'CONFIRMED', 'IN_PROGRESS'],
            due_date__isnull=False,
        ).exclude(status__in=[ActionPlanTask.STATUS_COMPLETED, ActionPlanTask.STATUS_SKIPPED]).select_related(
            'plan', 'plan__assignee_user', 'assignee_user',
        )
        grouped: dict[tuple[str, object, int], list[ActionPlanTask]] = {}
        for task in open_tasks.iterator(chunk_size=500):
            remaining = (task.due_date - today).days
            if remaining not in cls.OFFSETS:
                continue
            grouped.setdefault((str(task.plan_id), task.due_date, remaining), []).append(task)
        for (_, due, remaining), tasks in grouped.items():
            plan = tasks[0].plan
            names = ', '.join(task.title for task in tasks[:3])
            if len(tasks) > 3:
                names += f' và {len(tasks) - 3} việc khác'
            assignee = next((task.assignee_user for task in tasks if task.assignee_user_id), None) or plan.assignee_user
            recipient = assignee.email if assignee and assignee.email else ''
            reminder_key = f'tasks:{plan.plan_id}:due:{due.isoformat()}:offset:{remaining}:count:{len(tasks)}'
            increment = cls._deliver(
                plan=plan, task=None, reminder_key=reminder_key, recipient=recipient,
                title='Công việc sắp đến hạn' if remaining >= 0 else 'Công việc đã quá hạn',
                message=(
                    f'SKU {plan.sku} có {len(tasks)} công việc đến hạn {due.strftime("%d/%m/%Y")}: {names}. '
                    'Hãy cập nhật checklist hoặc nêu lý do chưa thực hiện.'
                ),
            )
            sent += increment[0]
            failed += increment[1]
            skipped += increment[2]
        return {'sent': sent, 'failed': failed, 'skipped': skipped, 'evaluated_at': timezone.now().isoformat()}
