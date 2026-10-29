"""Stable, high-traffic V2 routes kept separate from legacy URL aliases."""

from django.urls import path

from supplyforge import views


urlpatterns = [
    # Background work and direct-to-object-storage upload lifecycle.
    path('jobs/upload', views.enqueue_upload_job, name='enqueue_upload_job'),
    path('jobs/upload/initiate', views.initiate_s3_multipart_upload, name='initiate_s3_multipart_upload'),
    path(
        'jobs/<uuid:session_id>/upload/complete',
        views.complete_s3_multipart_upload,
        name='complete_s3_multipart_upload',
    ),
    path('jobs', views.list_jobs, name='list_jobs_no_slash'),
    path('jobs/', views.list_jobs, name='list_jobs'),
    path('jobs/<str:job_id>/status', views.get_job_status, name='get_job_status'),
    path('jobs/<str:job_id>/cancel', views.cancel_job, name='cancel_job'),
    path('jobs/<str:job_id>/retry', views.retry_job, name='retry_job'),
    path('jobs/<str:job_id>', views.delete_job, name='delete_job'),

    # Read-only dashboard queries and explicitly queued cache warming.
    path('query/dashboard-summary', views.get_cached_dashboard_summary, name='get_cached_dashboard_summary'),
    path('query/cache-refresh', views.refresh_workspace_cache, name='refresh_workspace_cache'),
]
