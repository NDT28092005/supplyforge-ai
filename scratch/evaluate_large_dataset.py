import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from supplyforge.models import Workspace, IngestionSession, BackgroundJob, SlowMovingRiskAssessment
from supplyforge.tasks import run_import_pipeline
from supplyforge.services.query_service import DashboardQueryService

def evaluate_dataset():
    ws, _ = Workspace.objects.get_or_create(id=99, defaults={'name': 'Enterprise Benchmark WS', 'slug': 'enterprise-bench'})
    csv_path = "/home/nguyen-dai-tung/supplyforge-ai/test_data/enterprise_inventory_500_skus.csv"
    file_size = os.path.getsize(csv_path)

    # Clean ALL previous sessions, orders, order items and assessments
    from supplyforge.models import Order, OrderItem, SlowMovingRiskAssessment
    SlowMovingRiskAssessment.objects.all().delete()
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    IngestionSession.objects.all().delete()

    session = IngestionSession.objects.create(
        workspace=ws,
        original_filename="enterprise_inventory_500_skus.csv",
        storage_path=csv_path,
        raw_storage_path=csv_path,
        file_size_bytes=file_size,
        status="QUEUED"
    )

    job = BackgroundJob.objects.create(
        workspace=ws,
        job_type="CSV_IMPORT",
        ingestion_session=session,
        status="PENDING",
        current_stage="PARSING",
        progress_pct=0,
        stages_json={
            'PARSING': {'status': 'PENDING', 'progress': 0},
            'PROFILING': {'status': 'PENDING', 'progress': 0},
            'MAPPING': {'status': 'PENDING', 'progress': 0},
            'IMPORTING': {'status': 'PENDING', 'progress': 0},
            'ML_INFERENCE': {'status': 'PENDING', 'progress': 0},
            'FINALIZING': {'status': 'PENDING', 'progress': 0},
        }
    )

    print(f"Running import pipeline for job {job.id}...")
    run_import_pipeline(str(job.id))

    job.refresh_from_db()
    session.refresh_from_db()
    print(f"Pipeline finished with job status: {job.status}, session status: {session.status}")

    # Query results
    summary, status = DashboardQueryService.get_executive_summary(ws.id, force_refresh=True)

    print("\n==========================================")
    print("      ENTERPRISE BENCHMARK RESULTS       ")
    print("==========================================")
    print(f"Total SKUs: {summary['totalSkus']}")
    print(f"Critical Count (Critical Risk): {summary['criticalCount']}")
    print(f"High Risk Count: {summary['highRiskCount']}")
    print(f"Medium Risk Count (Watchlist): {summary['mediumRiskCount']}")
    print(f"Low Risk Count (Safe): {summary['lowRiskCount']}")
    print(f"Total Capital Exposure (VNĐ): {summary['totalCapitalExposureVnd']:,.0f}")
    print(f"At-Risk Capital (VNĐ): {summary['atRiskCapitalVnd']:,.0f}")
    print(f"Aged Capital >90d (VNĐ): {summary['agedCapitalVnd']:,.0f}")
    print(f"Capital Status: {summary['capitalStatus']}")
    
    print("\nTop 5 Highest Capital Exposure SKUs:")
    for idx, s in enumerate(summary['topRiskSkus'], 1):
        print(f"  {idx}. {s['sku']} | {s['name']} | Risk: {s['riskClass']} | Score: {s['riskScore']} | Capital: {s['capitalExposureVnd']:,.0f} VNĐ | DSLS: {s['daysInInventory']} days")

if __name__ == "__main__":
    evaluate_dataset()
