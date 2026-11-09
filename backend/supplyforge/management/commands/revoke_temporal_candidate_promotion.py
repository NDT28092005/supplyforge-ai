"""Revoke a temporal ACTIVE promotion approval without changing artifacts."""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from supplyforge.models import TemporalCandidatePromotionApproval


class Command(BaseCommand):
    help = "Revoke a temporal promotion approval so the active candidate fails closed on the next load."

    def add_arguments(self, parser):
        parser.add_argument("approval_id")
        parser.add_argument("--revoked-by", required=True)
        parser.add_argument("--revoke-reference", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--revoke", action="store_true")

    def handle(self, *args, **options):
        if not options["revoke"]:
            raise CommandError("Refusing to revoke without --revoke.")
        approval = TemporalCandidatePromotionApproval.objects.filter(id=options["approval_id"]).first()
        if not approval:
            raise CommandError("Promotion approval does not exist.")
        if approval.status == TemporalCandidatePromotionApproval.STATUS_REVOKED:
            self.stdout.write(self.style.WARNING("Promotion approval is already revoked."))
            return
        approval.status = TemporalCandidatePromotionApproval.STATUS_REVOKED
        approval.revoked_at = timezone.now()
        approval.revoked_by = options["revoked_by"].strip()
        approval.revoke_reference = options["revoke_reference"].strip()
        approval.revoke_reason = options["reason"].strip()
        approval.save(update_fields=["status", "revoked_at", "revoked_by", "revoke_reference", "revoke_reason"])
        self.stdout.write(self.style.SUCCESS(f"Revoked temporal promotion approval {approval.id}."))
