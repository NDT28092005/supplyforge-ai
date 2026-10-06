# supplyforge/views package
# Re-export all view functions for clean URL routing and external imports

from .health import ping, check_data, health_live, health_ready, health_dependencies, health_celery
from .version import get_version_info
from .auth import (
    google_callback, verify_token, register_user, verify_email, resend_verification_email,
    login_user, refresh_token_api, logout_user, get_current_user, google_complete_phone,
    forgot_password, reset_password, update_user_profile, update_me_profile, check_object_ownership,
)
from .sync import sync_products, sync_orders
from .leak_detector import refresh_dead_stock, get_dead_stock, get_aging
from .recovery_copilot import get_portfolio_command, get_financial_analysis
from .xai import get_sku_xai
from .sku_tinder import get_candidates, merge_products, undo_merge, ignore_pair
from .shopee import (
    shopee_oauth_authorize_url, shopee_oauth_callback,
    shopee_webhook, trigger_sync, get_sync_status,
)
from .dss_web import dss_upload, dss_summary, dss_sku_detail
from .ingestion import (
    ingestion_upload, ingestion_session_detail, ingestion_session_list,
    analyze_file, process_file, clear_data, process_file_async, get_ingestion_progress,
    cancel_ingestion_session, get_record_lineage, get_error_matrix,
    get_post_import_quality_report, propagate_pipeline_health_score, verify_tenant_isolation,
    tenant_delete_data, verify_tenant_context
)
from .dataset_profiling import trigger_dataset_profiling, get_dataset_profile, get_sku_profiles
from .column_mapping import trigger_column_mapping, submit_mapping_override, get_mapping_audit
from .schema_validation import validate_canonical_schema, get_schema_validation_report
from .data_quality import trigger_data_quality_validation, get_data_quality_report, get_sku_quality_profiles
from .sku_normalization import (
    trigger_sku_normalization, get_sku_candidates, merchant_merge_sku,
    merchant_undo_sku_merge, get_sku_master_catalog
)
from .incremental_merge import (
    trigger_incremental_merge, get_merge_report, get_dataset_versions
)
from .data_freshness import (
    trigger_freshness_tracking, get_freshness_status, get_sku_freshness_report
)
from .ingestion_history import (
    record_ingestion_history_event, get_ingestion_history_detail, get_all_ingestion_history_list
)
from .data_quality_report import (
    generate_quality_report, get_quality_dashboard, get_affected_records_sample
)
from .data_readiness_gate import (
    evaluate_data_readiness, get_readiness_gate_status
)
from .slow_moving_analytics import (
    compute_slow_moving_features, get_slow_moving_features, get_feature_quality_report,
    classify_demand_patterns, get_demand_patterns, get_demand_pattern_summary,
    assemble_risk_features, get_risk_features, get_feature_registry,
    build_risk_feature_matrix, get_risk_feature_matrix, get_feature_dictionary, get_feature_correlation,
    compute_risk_scores, get_risk_scores, get_risk_scoring_config,
    classify_slow_moving_risk, get_risk_classifications, get_risk_classification_summary,
    prioritize_slow_moving_risk, get_risk_prioritized_queue, get_risk_prioritization_summary,
    validate_feature_matrix, get_feature_readiness_certificate, get_frozen_feature_matrix,
    create_feature_snapshot, get_feature_snapshot_metadata, get_risk_model_contract,
    run_module02_acceptance, get_risk_summary, get_risk_products, get_risk_product_detail,
    run_risk_model_inference, get_risk_model_predictions, get_risk_model_status,
    run_risk_scoring, get_risk_scoring_summary,
    run_risk_classification, get_risk_classifications, get_risk_classification_summary,
    run_probability_calibration, get_probability_calibrated_predictions, get_calibration_summary,
    run_risk_diagnostics, get_risk_diagnostics, get_diagnostic_summary,
    run_risk_assessment_assembly, get_risk_assessments, get_risk_assessment_summary
)
from .risk_assessment_api import (
    run_and_persist_assessments, list_risk_assessments,
    get_risk_assessment_detail, get_sku_risk_assessment,
    get_global_risk_summary
)
from .risk_monitoring_api import (
    execute_risk_monitoring, list_monitoring_runs,
    get_monitoring_run_detail, get_active_monitoring_alerts
)
from .explanation_views import (
    list_explanations_view, get_global_explanation_view,
    get_batch_explanations_view, get_sku_explanation_view,
    get_sku_explanation_history_view
)
from .capital_exposure_views import (
    create_capital_exposure_analysis,
    get_capital_exposure_analysis,
    get_capital_exposure_summary,
    list_capital_exposure_items,
    get_capital_exposure_sku_detail,
    get_capital_exposure_aging_distribution,
    get_capital_exposure_risk_distribution
)
from .decision_views import (
    DecisionListCreateView,
    DecisionDetailView,
    DecisionStatusUpdateView,
    DecisionHistoryView,
    DecisionExplanationView,
    DecisionSimulationView
)
from .action_plan_views import (
    ActionPlanListCreateView,
    ActionPlanStatusUpdateView,
    ActionPlanOutcomeView
)
from .content_views import (
    about_us_api,
    services_api,
    blog_list_api,
    blog_detail_api
)
from .copilot_views import CopilotChatView
from .notification_views import list_notifications, mark_notifications_read, create_notification
from .export_views import (
    ExportRiskReportView,
    ExportCapitalReportView,
    ExportDecisionReportView,
    ExportActionPlanReportView
)
from .job_views import (
    enqueue_upload_job, list_jobs, get_job_status,
    cancel_job, retry_job, delete_job
)
from .query_views import (
    get_cached_dashboard_summary, refresh_workspace_cache
)

__all__ = [
    'about_us_api', 'services_api', 'blog_list_api', 'blog_detail_api',
    'ping', 'check_data', 'health_live', 'health_ready', 'health_dependencies', 'health_celery', 'get_version_info',
    'google_callback', 'verify_token', 'register_user', 'login_user', 'google_complete_phone',
    'forgot_password', 'reset_password',
    'sync_products', 'sync_orders',
    'analyze_file', 'process_file', 'clear_data', 'process_file_async', 'get_ingestion_progress', 'cancel_ingestion_session', 'get_record_lineage', 'get_error_matrix',
    'tenant_delete_data', 'verify_tenant_context',
    'enqueue_upload_job', 'list_jobs', 'get_job_status', 'cancel_job', 'retry_job', 'delete_job',
    'get_cached_dashboard_summary', 'refresh_workspace_cache',
    'refresh_dead_stock', 'get_dead_stock', 'get_aging',
    'get_portfolio_command', 'get_financial_analysis',
    'get_sku_xai',
    'get_candidates', 'merge_products', 'undo_merge', 'ignore_pair',
    'shopee_oauth_authorize_url', 'shopee_oauth_callback',
    'shopee_webhook', 'trigger_sync', 'get_sync_status',
    'dss_upload', 'dss_summary', 'dss_sku_detail',
    'ingestion_upload', 'ingestion_session_detail', 'ingestion_session_list',
    'trigger_dataset_profiling', 'get_dataset_profile', 'get_sku_profiles',
    'trigger_column_mapping', 'submit_mapping_override', 'get_mapping_audit',
    'validate_canonical_schema', 'get_schema_validation_report',
    'trigger_data_quality_validation', 'get_data_quality_report', 'get_sku_quality_profiles',
    'trigger_sku_normalization', 'get_sku_candidates', 'merchant_merge_sku',
    'merchant_undo_sku_merge', 'get_sku_master_catalog',
    'trigger_incremental_merge', 'get_merge_report', 'get_dataset_versions',
    'trigger_freshness_tracking', 'get_freshness_status', 'get_sku_freshness_report',
    'record_ingestion_history_event', 'get_ingestion_history_detail', 'get_all_ingestion_history_list',
    'generate_quality_report', 'get_quality_dashboard', 'get_affected_records_sample',
    'evaluate_data_readiness', 'get_readiness_gate_status',
    'compute_slow_moving_features', 'get_slow_moving_features', 'get_feature_quality_report',
    'classify_demand_patterns', 'get_demand_patterns', 'get_demand_pattern_summary',
    'assemble_risk_features', 'get_risk_features', 'get_feature_registry',
    'build_risk_feature_matrix', 'get_risk_feature_matrix', 'get_feature_dictionary', 'get_feature_correlation',
    'compute_risk_scores', 'get_risk_scores', 'get_risk_scoring_config',
    'classify_slow_moving_risk', 'get_risk_classifications', 'get_risk_classification_summary',
    'prioritize_slow_moving_risk', 'get_risk_prioritized_queue', 'get_risk_prioritization_summary',
    'validate_feature_matrix', 'get_feature_readiness_certificate', 'get_frozen_feature_matrix',
    'create_feature_snapshot', 'get_feature_snapshot_metadata', 'get_risk_model_contract',
    'run_module02_acceptance', 'get_risk_summary', 'get_risk_products', 'get_risk_product_detail',
    'run_risk_model_inference', 'get_risk_model_predictions', 'get_risk_model_status',
    'run_risk_scoring', 'get_risk_scoring_summary',
    'run_risk_classification', 'get_risk_classifications', 'get_risk_classification_summary',
    'run_probability_calibration', 'get_probability_calibrated_predictions', 'get_calibration_summary',
    'run_risk_diagnostics', 'get_risk_diagnostics', 'get_diagnostic_summary',
    'run_risk_assessment_assembly', 'get_risk_assessments', 'get_risk_assessment_summary',
    'run_and_persist_assessments', 'list_risk_assessments',
    'get_risk_assessment_detail', 'get_sku_risk_assessment',
    'get_global_risk_summary',
    'execute_risk_monitoring', 'list_monitoring_runs',
    'get_monitoring_run_detail', 'get_active_monitoring_alerts',
    'list_explanations_view', 'get_global_explanation_view',
    'get_batch_explanations_view', 'get_sku_explanation_view',
    'get_sku_explanation_history_view',
    'create_capital_exposure_analysis', 'get_capital_exposure_analysis',
    'get_capital_exposure_summary', 'list_capital_exposure_items',
    'get_capital_exposure_sku_detail', 'get_capital_exposure_aging_distribution',
    'get_capital_exposure_risk_distribution',
    'DecisionListCreateView', 'DecisionDetailView',
    'DecisionStatusUpdateView', 'DecisionHistoryView',
    'DecisionExplanationView', 'DecisionSimulationView',
    'ActionPlanListCreateView', 'ActionPlanStatusUpdateView', 'ActionPlanOutcomeView',
    'CopilotChatView',
    'list_notifications', 'mark_notifications_read', 'create_notification',
    'ExportRiskReportView', 'ExportCapitalReportView',
    'ExportDecisionReportView', 'ExportActionPlanReportView'
]



