from django.urls import path
from supplyforge import views
from supplyforge.views.export_views import (
    ExportRiskReportView,
    ExportCapitalReportView,
    ExportDecisionReportView,
    ExportActionPlanReportView
)

urlpatterns = [
    # Root Health Check for Render & Cloud Probes
    path('', views.health_live, name='root_health'),

    # Health & System Liveness & Readiness Probes (Phase 0 & Phase 1)
    path('health/live', views.health_live, name='health_live_root'),
    path('health/ready', views.health_ready, name='health_ready_root'),
    path('health/dependencies', views.health_dependencies, name='health_dependencies_root'),
    path('health/celery', views.health_celery, name='health_celery_root'),
    path('api/v1/health/live', views.health_live, name='health_live_v1'),
    path('api/v1/health/ready', views.health_ready, name='health_ready_v1'),
    path('api/v1/health/dependencies', views.health_dependencies, name='health_dependencies_v1'),
    path('api/v1/health/celery', views.health_celery, name='health_celery_v1'),
    path('api/version', views.get_version_info, name='api_version'),
    path('api/v1/version', views.get_version_info, name='api_v1_version'),
    path('api/v1/ping', views.ping, name='ping'),
    path('api/v1/data/check', views.check_data, name='check_data'),


    # Authentication & User Management (AUTH-001 & AUTH-002)
    path('api/auth/register', views.register_user, name='register_user'),
    path('api/v1/auth/register', views.register_user, name='register_user_v1'),
    path('api/auth/verify-email', views.verify_email, name='verify_email'),
    path('api/v1/auth/verify-email', views.verify_email, name='verify_email_v1'),
    path('api/auth/resend-verification', views.resend_verification_email, name='resend_verification_email'),
    path('api/v1/auth/resend-verification', views.resend_verification_email, name='resend_verification_email_v1'),

    path('api/auth/forgot-password', views.forgot_password, name='forgot_password'),
    path('api/v1/auth/forgot-password', views.forgot_password, name='forgot_password_v1'),
    path('api/auth/reset-password', views.reset_password, name='reset_password'),
    path('api/v1/auth/reset-password', views.reset_password, name='reset_password_v1'),

    path('api/auth/login', views.login_user, name='login_user'),
    path('api/v1/auth/login', views.login_user, name='login_user_v1'),
    path('api/auth/logout', views.logout_user, name='logout_user'),
    path('api/v1/auth/logout', views.logout_user, name='logout_user_v1'),
    path('api/auth/refresh', views.refresh_token_api, name='refresh_token'),
    path('api/v1/auth/refresh', views.refresh_token_api, name='refresh_token_v1'),
    path('api/auth/verify', views.verify_token, name='verify_token'),
    path('api/v1/auth/verify', views.verify_token, name='verify_token_v1'),
    path('api/auth/me', views.get_current_user, name='get_current_user'),
    path('api/v1/auth/me', views.get_current_user, name='get_current_user_v1'),
    path('api/v1/auth/profile', views.update_user_profile, name='update_user_profile_v1'),
    path('api/v1/auth/me/profile', views.update_me_profile, name='update_me_profile_v1'),
    path('api/v1/me/profile', views.update_me_profile, name='update_me_profile'),
    path('api/v1/users/update', views.update_user_profile, name='update_user_profile_legacy'),
    path('api/v1/users/<int:target_user_id>', views.update_user_profile, name='update_target_user_profile_v1'),

    path('api/auth/google/callback', views.google_callback, name='google_callback'),
    path('api/v1/auth/google/callback', views.google_callback, name='google_callback_v1'),
    path('api/auth/google/complete-phone', views.google_complete_phone, name='google_complete_phone'),
    path('api/v1/auth/google/complete-phone', views.google_complete_phone, name='google_complete_phone_v1'),

    # ── Content REST APIs (About Us, Services, Blog) ──
    path('api/v1/about_us', views.about_us_api, name='about_us_v1'),
    path('api/v1/about_us/', views.about_us_api),
    path('api/v1/services', views.services_api, name='services_v1'),
    path('api/v1/services/', views.services_api),
    path('api/v1/blog', views.blog_list_api, name='blog_list_v1'),
    path('api/v1/blog/', views.blog_list_api),
    path('api/v1/blog/<slug:slug>', views.blog_detail_api, name='blog_detail_v1'),
    path('api/v1/blog/<slug:slug>/', views.blog_detail_api),

    # Data Sync (JSON Batch)
    path('api/v1/sync/products', views.sync_products, name='sync_products'),
    path('api/v1/sync/orders', views.sync_orders, name='sync_orders'),

    # Dynamic CSV Import Engine (Streaming + Gemini AI Column Mapping)
    path('api/v1/import/analyze', views.analyze_file, name='analyze_file'),
    path('api/v1/import/process', views.process_file, name='process_file'),
    path('api/v1/import/clear', views.clear_data, name='clear_data'),

    # Leak Detector & Inventory Aging Dashboard
    path('api/v1/workspaces/<int:workspace_id>/dead-stock/refresh', views.refresh_dead_stock, name='refresh_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/dead-stock', views.get_dead_stock, name='get_dead_stock'),
    path('api/v1/workspaces/<int:workspace_id>/aging', views.get_aging, name='get_aging'),

    # Recovery Copilot & Financial Liquidation Engine
    path('api/v1/workspaces/<int:workspace_id>/portfolio/command', views.get_portfolio_command, name='get_portfolio_command'),
    path('api/v1/workspaces/<int:workspace_id>/portfolio/financial-analysis', views.get_financial_analysis, name='get_financial_analysis'),
    path('api/v1/workspaces/<int:workspace_id>/sku/<str:sku_id>/xai', views.get_sku_xai, name='get_sku_xai'),

    # SKU Tinder (Levenshtein & Normalization Matching Engine)
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/candidates', views.get_candidates, name='get_candidates'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/merge', views.merge_products, name='merge_products'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/undo', views.undo_merge, name='undo_merge'),
    path('api/v1/workspaces/<int:workspace_id>/sku-merge/ignore', views.ignore_pair, name='ignore_pair'),

    # Shopee Open API Integration (OAuth2 + HMAC Webhooks + Manual Sync)
    path('api/v1/shopee/oauth/authorize', views.shopee_oauth_authorize_url, name='shopee_oauth_authorize_url'),
    path('api/v1/shopee/oauth/callback', views.shopee_oauth_callback, name='shopee_oauth_callback'),
    path('api/v1/shopee/webhook', views.shopee_webhook, name='shopee_webhook'),
    path('api/v1/shopee/sync/trigger', views.trigger_sync, name='shopee_trigger_sync'),
    path('api/v1/shopee/sync/status', views.get_sync_status, name='shopee_sync_status'),

    # Merchant DSS Web Prototype REST API (EXP-12 Production Pipeline Integration)
    path('api/v1/dss/upload', views.dss_upload, name='dss_upload'),
    path('api/v1/dss/summary', views.dss_summary, name='dss_summary'),
    path('api/v1/dss/sku/<str:sku_id>', views.dss_sku_detail, name='dss_sku_detail'),

    # ── Module 01 Data Ingestion (Streaming CSV Upload & Profiling) ──
    path('api/v1/ingestion/upload', views.ingestion_upload, name='ingestion_upload_v1'),
    path('api/v2/ingestion/upload', views.ingestion_upload, name='ingestion_upload'),
    path('api/v2/ingestion/process-async', views.process_file_async, name='process_file_async'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/cancel', views.cancel_ingestion_session, name='cancel_ingestion_session_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/cancel', views.cancel_ingestion_session, name='cancel_ingestion_session'),
    path('api/v1/ingestion/lineage/<str:record_id>', views.get_record_lineage, name='get_record_lineage_v1'),
    path('api/v2/ingestion/lineage/<str:record_id>', views.get_record_lineage, name='get_record_lineage'),
    path('api/v1/ingestion/error-matrix', views.get_error_matrix, name='get_error_matrix_v1'),
    path('api/v2/ingestion/error-matrix', views.get_error_matrix, name='get_error_matrix'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/post-import-quality-report', views.get_post_import_quality_report, name='get_post_import_quality_report_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/post-import-quality-report', views.get_post_import_quality_report, name='get_post_import_quality_report'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/pipeline-propagate', views.propagate_pipeline_health_score, name='propagate_pipeline_health_score_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/pipeline-propagate', views.propagate_pipeline_health_score, name='propagate_pipeline_health_score'),
    path('api/v1/tenant/verify-isolation', views.verify_tenant_isolation, name='verify_tenant_isolation_v1'),
    path('api/v2/tenant/verify-isolation', views.verify_tenant_isolation, name='verify_tenant_isolation'),
    path('api/v1/tenant/context', views.verify_tenant_context, name='verify_tenant_context_v1'),
    path('api/v1/tenant/delete-data', views.tenant_delete_data, name='tenant_delete_data_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/progress', views.get_ingestion_progress, name='get_ingestion_progress'),
    path('api/v1/ingestion/history-list', views.get_all_ingestion_history_list, name='get_all_ingestion_history_list_v1'),
    path('api/v2/ingestion/history-list', views.get_all_ingestion_history_list, name='get_all_ingestion_history_list'),
    path('api/v1/ingestion/sessions/<uuid:session_id>', views.ingestion_session_detail, name='ingestion_session_detail_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>', views.ingestion_session_detail, name='ingestion_session_detail'),
    path('api/v1/ingestion/sessions', views.ingestion_session_list, name='ingestion_session_list_v1'),
    path('api/v2/ingestion/sessions', views.ingestion_session_list, name='ingestion_session_list'),

    # ── Module 01 Task 02 Dataset Profiling & Data Quality ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/profile', views.trigger_dataset_profiling, name='trigger_dataset_profiling_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/profile', views.trigger_dataset_profiling, name='trigger_dataset_profiling'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/profile/detail', views.get_dataset_profile, name='get_dataset_profile_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/profile/detail', views.get_dataset_profile, name='get_dataset_profile'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-profiles', views.get_sku_profiles, name='get_sku_profiles_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-profiles', views.get_sku_profiles, name='get_sku_profiles'),

    # ── Module 01 Task 03 Automatic Column Mapping ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/map-columns', views.trigger_column_mapping, name='trigger_column_mapping_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/map-columns', views.trigger_column_mapping, name='trigger_column_mapping'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/mapping-override', views.submit_mapping_override, name='submit_mapping_override_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/mapping-override', views.submit_mapping_override, name='submit_mapping_override'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/mapping-audit', views.get_mapping_audit, name='get_mapping_audit_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/mapping-audit', views.get_mapping_audit, name='get_mapping_audit'),

    # ── Module 01 Task 04 Canonical Schema Validation ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/validate-schema', views.validate_canonical_schema, name='validate_canonical_schema_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/validate-schema', views.validate_canonical_schema, name='validate_canonical_schema'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/schema-validation', views.get_schema_validation_report, name='get_schema_validation_report_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/schema-validation', views.get_schema_validation_report, name='get_schema_validation_report'),

    # ── Module 01 DAT-05 Data Quality Validation ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/quality-validation', views.trigger_data_quality_validation, name='trigger_data_quality_validation_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/quality-validation', views.trigger_data_quality_validation, name='trigger_data_quality_validation'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/quality-report', views.get_data_quality_report, name='get_data_quality_report_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/quality-report', views.get_data_quality_report, name='get_data_quality_report'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-quality-profiles', views.get_sku_quality_profiles, name='get_sku_quality_profiles_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-quality-profiles', views.get_sku_quality_profiles, name='get_sku_quality_profiles'),

    # ── Module 01 DAT-06 SKU Normalization ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/normalize-skus', views.trigger_sku_normalization, name='trigger_sku_normalization_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/normalize-skus', views.trigger_sku_normalization, name='trigger_sku_normalization'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-candidates', views.get_sku_candidates, name='get_sku_candidates_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-candidates', views.get_sku_candidates, name='get_sku_candidates'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-merge', views.merchant_merge_sku, name='merchant_merge_sku_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-merge', views.merchant_merge_sku, name='merchant_merge_sku'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-undo-merge', views.merchant_undo_sku_merge, name='merchant_undo_sku_merge_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-undo-merge', views.merchant_undo_sku_merge, name='merchant_undo_sku_merge'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-master', views.get_sku_master_catalog, name='get_sku_master_catalog_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-master', views.get_sku_master_catalog, name='get_sku_master_catalog'),

    # ── Module 01 DAT-07 Incremental Upload & Dataset Merge ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/incremental-merge', views.trigger_incremental_merge, name='trigger_incremental_merge_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/incremental-merge', views.trigger_incremental_merge, name='trigger_incremental_merge'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/merge-report', views.get_merge_report, name='get_merge_report_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/merge-report', views.get_merge_report, name='get_merge_report'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/dataset-versions', views.get_dataset_versions, name='get_dataset_versions_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/dataset-versions', views.get_dataset_versions, name='get_dataset_versions'),

    # ── Module 01 DAT-08 Data Freshness Tracking ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/freshness-tracking', views.trigger_freshness_tracking, name='trigger_freshness_tracking_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/freshness-tracking', views.trigger_freshness_tracking, name='trigger_freshness_tracking'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/freshness-status', views.get_freshness_status, name='get_freshness_status_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/freshness-status', views.get_freshness_status, name='get_freshness_status'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/sku-freshness', views.get_sku_freshness_report, name='get_sku_freshness_report_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/sku-freshness', views.get_sku_freshness_report, name='get_sku_freshness_report'),

    # ── Module 01 DAT-09 Ingestion History & Audit Trail ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/record-history', views.record_ingestion_history_event, name='record_ingestion_history_event_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/record-history', views.record_ingestion_history_event, name='record_ingestion_history_event'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/history', views.get_ingestion_history_detail, name='get_ingestion_history_detail_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/history', views.get_ingestion_history_detail, name='get_ingestion_history_detail'),

    # ── Module 01 DAT-10 Data Quality Report UI & Readiness Guard ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/generate-quality-report', views.generate_quality_report, name='generate_quality_report_v1'),
    # ── Background Job Queue (Release 1: Queue v1.0) ──
    path('api/v2/jobs/upload', views.enqueue_upload_job, name='enqueue_upload_job'),
    path('api/v2/jobs', views.list_jobs, name='list_jobs_no_slash'),
    path('api/v2/jobs/', views.list_jobs, name='list_jobs'),
    path('api/v2/jobs/<str:job_id>/status', views.get_job_status, name='get_job_status'),
    path('api/v2/jobs/<str:job_id>/cancel', views.cancel_job, name='cancel_job'),
    path('api/v2/jobs/<str:job_id>/retry', views.retry_job, name='retry_job'),
    path('api/v2/jobs/<str:job_id>', views.delete_job, name='delete_job'),

    # ── High-Speed Query & Redis Cache APIs (QUERY Layer) ──
    path('api/v2/query/dashboard-summary', views.get_cached_dashboard_summary, name='get_cached_dashboard_summary'),
    path('api/v2/query/cache-refresh', views.refresh_workspace_cache, name='refresh_workspace_cache'),

    path('api/v2/ingestion/sessions/<uuid:session_id>/generate-quality-report', views.generate_quality_report, name='generate_quality_report'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/quality-dashboard', views.get_quality_dashboard, name='get_quality_dashboard_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/quality-dashboard', views.get_quality_dashboard, name='get_quality_dashboard'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/affected-records', views.get_affected_records_sample, name='get_affected_records_sample_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/affected-records', views.get_affected_records_sample, name='get_affected_records_sample'),

    # ── Module 01 DAT-11 Data Readiness Gate & Downstream Guard ──
    path('api/v1/ingestion/sessions/<uuid:session_id>/evaluate-readiness', views.evaluate_data_readiness, name='evaluate_data_readiness_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/evaluate-readiness', views.evaluate_data_readiness, name='evaluate_data_readiness'),
    path('api/v1/ingestion/sessions/<uuid:session_id>/readiness-gate-status', views.get_readiness_gate_status, name='get_readiness_gate_status_v1'),
    path('api/v2/ingestion/sessions/<uuid:session_id>/readiness-gate-status', views.get_readiness_gate_status, name='get_readiness_gate_status'),

    # ── Module 02 Analytics: M2-01 Slow-Moving Risk Feature Engineering ──
    path('api/v1/analytics/sessions/<uuid:session_id>/compute-features', views.compute_slow_moving_features, name='compute_slow_moving_features_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/compute-features', views.compute_slow_moving_features, name='compute_slow_moving_features'),
    path('api/v1/analytics/sessions/<uuid:session_id>/features', views.get_slow_moving_features, name='get_slow_moving_features_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/features', views.get_slow_moving_features, name='get_slow_moving_features'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-quality', views.get_feature_quality_report, name='get_feature_quality_report_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-quality', views.get_feature_quality_report, name='get_feature_quality_report'),

    # ── Module 02 Analytics: M2-02 Demand Pattern Classification ──
    path('api/v1/analytics/sessions/<uuid:session_id>/classify-demand-patterns', views.classify_demand_patterns, name='classify_demand_patterns_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/classify-demand-patterns', views.classify_demand_patterns, name='classify_demand_patterns'),
    path('api/v1/analytics/sessions/<uuid:session_id>/demand-patterns', views.get_demand_patterns, name='get_demand_patterns_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/demand-patterns', views.get_demand_patterns, name='get_demand_patterns'),
    path('api/v1/analytics/sessions/<uuid:session_id>/demand-pattern-summary', views.get_demand_pattern_summary, name='get_demand_pattern_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/demand-pattern-summary', views.get_demand_pattern_summary, name='get_demand_pattern_summary'),

    # ── Module 02 Analytics: M2-03 Slow-Moving Risk Feature Assembly ──
    path('api/v1/analytics/sessions/<uuid:session_id>/assemble-risk-features', views.assemble_risk_features, name='assemble_risk_features_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/assemble-risk-features', views.assemble_risk_features, name='assemble_risk_features'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-features', views.get_risk_features, name='get_risk_features_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-features', views.get_risk_features, name='get_risk_features'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-registry', views.get_feature_registry, name='get_feature_registry_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-registry', views.get_feature_registry, name='get_feature_registry'),

    # ── Module 02 Analytics: M2-04 Slow-Moving Risk Feature Engineering ──
    path('api/v1/analytics/sessions/<uuid:session_id>/build-risk-feature-matrix', views.build_risk_feature_matrix, name='build_risk_feature_matrix_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/build-risk-feature-matrix', views.build_risk_feature_matrix, name='build_risk_feature_matrix'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-feature-matrix', views.get_risk_feature_matrix, name='get_risk_feature_matrix_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-feature-matrix', views.get_risk_feature_matrix, name='get_risk_feature_matrix'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-dictionary', views.get_feature_dictionary, name='get_feature_dictionary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-dictionary', views.get_feature_dictionary, name='get_feature_dictionary'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-correlation', views.get_feature_correlation, name='get_feature_correlation_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-correlation', views.get_feature_correlation, name='get_feature_correlation'),

    # ── Module 02 Analytics: M2-05 Slow-Moving Risk Feature Scoring ──
    path('api/v1/analytics/sessions/<uuid:session_id>/compute-risk-scores', views.compute_risk_scores, name='compute_risk_scores_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/compute-risk-scores', views.compute_risk_scores, name='compute_risk_scores'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-scoring-config', views.get_risk_scoring_config, name='get_risk_scoring_config_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-scoring-config', views.get_risk_scoring_config, name='get_risk_scoring_config'),

    # ── Module 02 Analytics: M2-06 Slow-Moving Risk Classification ──
    path('api/v1/analytics/sessions/<uuid:session_id>/classify-slow-moving-risk', views.classify_slow_moving_risk, name='classify_slow_moving_risk_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/classify-slow-moving-risk', views.classify_slow_moving_risk, name='classify_slow_moving_risk'),

    # ── Module 02 Analytics: M2-07 Slow-Moving Risk Ranking & Prioritization ──
    path('api/v1/analytics/sessions/<uuid:session_id>/prioritize-slow-moving-risk', views.prioritize_slow_moving_risk, name='prioritize_slow_moving_risk_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/prioritize-slow-moving-risk', views.prioritize_slow_moving_risk, name='prioritize_slow_moving_risk'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-prioritized-queue', views.get_risk_prioritized_queue, name='get_risk_prioritized_queue_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-prioritized-queue', views.get_risk_prioritized_queue, name='get_risk_prioritized_queue'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-prioritization-summary', views.get_risk_prioritization_summary, name='get_risk_prioritization_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-prioritization-summary', views.get_risk_prioritization_summary, name='get_risk_prioritization_summary'),

    # ── Module 02 Analytics: M2-08 Feature Validation & Readiness Gate ──
    path('api/v1/analytics/sessions/<uuid:session_id>/validate-feature-matrix', views.validate_feature_matrix, name='validate_feature_matrix_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/validate-feature-matrix', views.validate_feature_matrix, name='validate_feature_matrix'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-readiness-certificate', views.get_feature_readiness_certificate, name='get_feature_readiness_certificate_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-readiness-certificate', views.get_feature_readiness_certificate, name='get_feature_readiness_certificate'),
    path('api/v1/analytics/sessions/<uuid:session_id>/frozen-feature-matrix', views.get_frozen_feature_matrix, name='get_frozen_feature_matrix_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/frozen-feature-matrix', views.get_frozen_feature_matrix, name='get_frozen_feature_matrix'),

    # ── Module 02 Analytics: M2-09 Feature Snapshot & Downstream Handoff ──
    path('api/v1/analytics/sessions/<uuid:session_id>/create-feature-snapshot', views.create_feature_snapshot, name='create_feature_snapshot_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/create-feature-snapshot', views.create_feature_snapshot, name='create_feature_snapshot'),
    path('api/v1/analytics/sessions/<uuid:session_id>/feature-snapshot-metadata', views.get_feature_snapshot_metadata, name='get_feature_snapshot_metadata_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/feature-snapshot-metadata', views.get_feature_snapshot_metadata, name='get_feature_snapshot_metadata'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-model-contract', views.get_risk_model_contract, name='get_risk_model_contract_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-model-contract', views.get_risk_model_contract, name='get_risk_model_contract'),

    # ── Module 02 Analytics: M2-10 Risk Dashboard UI & Module 02 Acceptance ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-module02-acceptance', views.run_module02_acceptance, name='run_module02_acceptance_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-module02-acceptance', views.run_module02_acceptance, name='run_module02_acceptance'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-summary', views.get_risk_summary, name='get_risk_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-summary', views.get_risk_summary, name='get_risk_summary'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-products', views.get_risk_products, name='get_risk_products_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-products', views.get_risk_products, name='get_risk_products'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-products/<str:sku>', views.get_risk_product_detail, name='get_risk_product_detail_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-products/<str:sku>', views.get_risk_product_detail, name='get_risk_product_detail'),

    # ── Module 03 Analytics: M3-01 Risk Model Integration ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-risk-model-inference', views.run_risk_model_inference, name='run_risk_model_inference_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-risk-model-inference', views.run_risk_model_inference, name='run_risk_model_inference'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-model-predictions', views.get_risk_model_predictions, name='get_risk_model_predictions_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-model-predictions', views.get_risk_model_predictions, name='get_risk_model_predictions'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-model-status', views.get_risk_model_status, name='get_risk_model_status_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-model-status', views.get_risk_model_status, name='get_risk_model_status'),

    # ── Module 03 Analytics: M3-02 Risk Scoring Engine ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-risk-scoring', views.run_risk_scoring, name='run_risk_scoring_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-risk-scoring', views.run_risk_scoring, name='run_risk_scoring'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-scores', views.get_risk_scores, name='get_risk_scores_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-scores', views.get_risk_scores, name='get_risk_scores'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-scoring-summary', views.get_risk_scoring_summary, name='get_risk_scoring_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-scoring-summary', views.get_risk_scoring_summary, name='get_risk_scoring_summary'),

    # ── Module 03 Analytics: M3-03 Risk Classification ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-risk-classification', views.run_risk_classification, name='run_risk_classification_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-risk-classification', views.run_risk_classification, name='run_risk_classification'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-classifications', views.get_risk_classifications, name='get_risk_classifications_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-classifications', views.get_risk_classifications, name='get_risk_classifications'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-classification-summary', views.get_risk_classification_summary, name='get_risk_classification_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-classification-summary', views.get_risk_classification_summary, name='get_risk_classification_summary'),

    # ── Module 03 Analytics: M3-04 Risk Probability Calibration ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-probability-calibration', views.run_probability_calibration, name='run_probability_calibration_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-probability-calibration', views.run_probability_calibration, name='run_probability_calibration'),
    path('api/v1/analytics/sessions/<uuid:session_id>/probability-calibrated-predictions', views.get_probability_calibrated_predictions, name='get_probability_calibrated_predictions_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/probability-calibrated-predictions', views.get_probability_calibrated_predictions, name='get_probability_calibrated_predictions'),
    path('api/v1/analytics/sessions/<uuid:session_id>/calibration-summary', views.get_calibration_summary, name='get_calibration_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/calibration-summary', views.get_calibration_summary, name='get_calibration_summary'),

    # ── Module 03 Analytics: M3-05 Risk Diagnostic Engine ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-risk-diagnostics', views.run_risk_diagnostics, name='run_risk_diagnostics_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-risk-diagnostics', views.run_risk_diagnostics, name='run_risk_diagnostics'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-diagnostics', views.get_risk_diagnostics, name='get_risk_diagnostics_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-diagnostics', views.get_risk_diagnostics, name='get_risk_diagnostics'),
    path('api/v1/analytics/sessions/<uuid:session_id>/diagnostic-summary', views.get_diagnostic_summary, name='get_diagnostic_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/diagnostic-summary', views.get_diagnostic_summary, name='get_diagnostic_summary'),

    # ── Module 03 Analytics: M3-06 Risk Assessment Assembly ──
    path('api/v1/analytics/sessions/<uuid:session_id>/run-risk-assessment-assembly', views.run_risk_assessment_assembly, name='run_risk_assessment_assembly_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/run-risk-assessment-assembly', views.run_risk_assessment_assembly, name='run_risk_assessment_assembly'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-assessments', views.get_risk_assessments, name='get_risk_assessments_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-assessments', views.get_risk_assessments, name='get_risk_assessments'),
    path('api/v1/analytics/sessions/<uuid:session_id>/risk-assessment-summary', views.get_risk_assessment_summary, name='get_risk_assessment_summary_v1'),
    path('api/v2/analytics/sessions/<uuid:session_id>/risk-assessment-summary', views.get_risk_assessment_summary, name='get_risk_assessment_summary'),

    # ── Module 03 Analytics: M3-07 Risk API & Persistence ──
    path('api/v1/risk/assessments', views.run_and_persist_assessments, name='run_and_persist_assessments_v1'),
    path('api/v1/risk/assessments/', views.run_and_persist_assessments),
    path('api/v1/risk/assessments/list', views.list_risk_assessments, name='list_risk_assessments_v1'),
    path('api/v1/risk/assessments/list/', views.list_risk_assessments),
    path('api/v1/risk/assessments/<uuid:id>', views.get_risk_assessment_detail, name='get_risk_assessment_detail_v1'),
    path('api/v1/risk/assessments/<uuid:id>/', views.get_risk_assessment_detail),
    path('api/v1/risk/skus/<str:sku_id>', views.get_sku_risk_assessment, name='get_sku_risk_assessment_v1'),
    path('api/v1/risk/skus/<str:sku_id>/', views.get_sku_risk_assessment),
    path('api/v1/risk/summary', views.get_global_risk_summary, name='get_global_risk_summary_v1'),
    path('api/v1/risk/summary/', views.get_global_risk_summary),

    # ── Module 03 Analytics: M3-08 Risk Monitoring & Validation ──
    path('api/v1/risk/monitoring/run', views.execute_risk_monitoring, name='execute_risk_monitoring_v1'),
    path('api/v1/risk/monitoring/run/', views.execute_risk_monitoring),
    path('api/v1/risk/monitoring', views.list_monitoring_runs, name='list_monitoring_runs_v1'),
    path('api/v1/risk/monitoring/', views.list_monitoring_runs),
    path('api/v1/risk/monitoring/alerts', views.get_active_monitoring_alerts, name='get_active_monitoring_alerts_v1'),
    path('api/v1/risk/monitoring/alerts/', views.get_active_monitoring_alerts),
    path('api/v1/risk/monitoring/<uuid:run_id>', views.get_monitoring_run_detail, name='get_monitoring_run_detail_v1'),
    path('api/v1/risk/monitoring/<uuid:run_id>/', views.get_monitoring_run_detail),

    # ── Module 04 Explainability: M4-08 Explainability API & Persistence ──
    path('api/explanations/global', views.get_global_explanation_view, name='get_global_explanation_v1'),
    path('api/explanations/global/', views.get_global_explanation_view),
    path('api/explanations/batch', views.get_batch_explanations_view, name='get_batch_explanations_v1'),
    path('api/explanations/batch/', views.get_batch_explanations_view),
    path('api/explanations/<str:sku_id>/history', views.get_sku_explanation_history_view, name='get_sku_explanation_history_v1'),
    path('api/explanations/<str:sku_id>/history/', views.get_sku_explanation_history_view),
    path('api/explanations/<str:sku_id>', views.get_sku_explanation_view, name='get_sku_explanation_v1'),
    path('api/explanations/<str:sku_id>/', views.get_sku_explanation_view),
    path('api/explanations', views.list_explanations_view, name='list_explanations_v1'),
    path('api/explanations/', views.list_explanations_view),

    # ── Module 05 Capital Exposure: M5-09 Capital Exposure API & Persistence ──
    path('api/capital-exposure/analyses', views.create_capital_exposure_analysis, name='create_capital_exposure_analysis_v1'),
    path('api/capital-exposure/analyses/', views.create_capital_exposure_analysis),
    path('api/capital-exposure/analyses/<str:analysis_id>/summary', views.get_capital_exposure_summary, name='get_capital_exposure_summary_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/summary/', views.get_capital_exposure_summary),
    path('api/capital-exposure/analyses/<str:analysis_id>/aging', views.get_capital_exposure_aging_distribution, name='get_capital_exposure_aging_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/aging/', views.get_capital_exposure_aging_distribution),
    path('api/capital-exposure/analyses/<str:analysis_id>/risk-distribution', views.get_capital_exposure_risk_distribution, name='get_capital_exposure_risk_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/risk-distribution/', views.get_capital_exposure_risk_distribution),
    path('api/capital-exposure/analyses/<str:analysis_id>/items/<str:sku_id>', views.get_capital_exposure_sku_detail, name='get_capital_exposure_sku_detail_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/items/<str:sku_id>/', views.get_capital_exposure_sku_detail),
    path('api/capital-exposure/analyses/<str:analysis_id>/items', views.list_capital_exposure_items, name='list_capital_exposure_items_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/items/', views.list_capital_exposure_items),
    path('api/capital-exposure/analyses/<str:analysis_id>', views.get_capital_exposure_analysis, name='get_capital_exposure_analysis_v1'),
    path('api/capital-exposure/analyses/<str:analysis_id>/', views.get_capital_exposure_analysis),

    # ── Module 06 Decision Support: M6-10 Decision API & Persistence ──
    path('api/v1/decisions/', views.DecisionListCreateView.as_view(), name='decision_list_create_v1'),
    path('api/v1/decisions', views.DecisionListCreateView.as_view()),
    path('api/v1/decisions/<str:decision_id>/status/', views.DecisionStatusUpdateView.as_view(), name='decision_status_update_v1'),
    path('api/v1/decisions/<str:decision_id>/status', views.DecisionStatusUpdateView.as_view()),
    path('api/v1/decisions/<str:decision_id>/history/', views.DecisionHistoryView.as_view(), name='decision_history_v1'),
    path('api/v1/decisions/<str:decision_id>/history', views.DecisionHistoryView.as_view()),
    path('api/v1/decisions/<str:decision_id>/explanation/', views.DecisionExplanationView.as_view(), name='decision_explanation_v1'),
    path('api/v1/decisions/<str:decision_id>/explanation', views.DecisionExplanationView.as_view()),
    path('api/v1/decisions/simulate/', views.DecisionSimulationView.as_view(), name='decision_simulate_v1'),
    path('api/v1/decisions/simulate', views.DecisionSimulationView.as_view()),
    path('api/v1/decisions/<str:decision_id>/', views.DecisionDetailView.as_view(), name='decision_detail_v1'),
    path('api/v1/decisions/<str:decision_id>', views.DecisionDetailView.as_view()),

    # ── Module 07 Action Planning: ACT-001, ACT-002, ACT-003 & ACT-004 ──
    path('api/v1/action-plans/', views.ActionPlanListCreateView.as_view(), name='action_plan_list_create_v1'),
    path('api/v1/action-plans', views.ActionPlanListCreateView.as_view()),
    path('api/v1/action-plans/<str:plan_id>/status/', views.ActionPlanStatusUpdateView.as_view(), name='action_plan_status_update_v1'),
    path('api/v1/action-plans/<str:plan_id>/status', views.ActionPlanStatusUpdateView.as_view()),
    path('api/v1/action-plans/<str:plan_id>/outcome/', views.ActionPlanOutcomeView.as_view(), name='action_plan_outcome_update_v1'),
    path('api/v1/action-plans/<str:plan_id>/outcome', views.ActionPlanOutcomeView.as_view()),

    # ── Module 07 Copilot: COP-001 Context Awareness & COP-002 Grounded Answers ──
    path('api/v1/copilot/chat/', views.CopilotChatView.as_view(), name='copilot_chat_v1'),
    path('api/v1/copilot/chat', views.CopilotChatView.as_view()),

    # ── Notification & Alert System: NOTI-001 & NOTI-002 ──
    path('api/v1/notifications/', views.list_notifications, name='list_notifications_v1'),
    path('api/v1/notifications', views.list_notifications),
    path('api/v1/notifications/mark-read/', views.mark_notifications_read, name='mark_notifications_read_v1'),
    path('api/v1/notifications/mark-read', views.mark_notifications_read),
    path('api/v1/notifications/create/', views.create_notification, name='create_notification_v1'),
    path('api/v1/notifications/create', views.create_notification),

    # ── EXPORT-001 Report Export APIs ──
    path('api/v1/export/risk', ExportRiskReportView.as_view(), name='export_risk_report'),
    path('api/v1/export/risk/', ExportRiskReportView.as_view()),
    path('api/v1/export/capital', ExportCapitalReportView.as_view(), name='export_capital_report'),
    path('api/v1/export/capital/', ExportCapitalReportView.as_view()),
    path('api/v1/export/decisions', ExportDecisionReportView.as_view(), name='export_decision_report'),
    path('api/v1/export/decisions/', ExportDecisionReportView.as_view()),
    path('api/v1/export/action-plans', ExportActionPlanReportView.as_view(), name='export_action_plan_report'),
    path('api/v1/export/action-plans/', ExportActionPlanReportView.as_view()),
]


