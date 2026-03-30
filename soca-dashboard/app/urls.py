from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Cameras
    path("cameras/", views.camera_list, name="camera_list"),
    path("cameras/new/", views.camera_form, name="camera_create"),
    path("cameras/<int:pk>/edit/", views.camera_form, name="camera_edit"),
    path("cameras/<int:pk>/delete/", views.camera_delete, name="camera_delete"),
    path("cameras/<int:pk>/snapshot/", views.camera_snapshot, name="camera_snapshot"),

    # Schedules
    path("schedules/", views.schedule_list, name="schedule_list"),
    path("schedules/new/", views.schedule_form, name="schedule_create"),
    path("schedules/<int:pk>/edit/", views.schedule_form, name="schedule_edit"),
    path("schedules/<int:pk>/delete/", views.schedule_delete, name="schedule_delete"),
    path("schedules/<int:pk>/start/", views.schedule_start, name="schedule_start"),
    path("schedules/<int:pk>/stop/", views.schedule_stop, name="schedule_stop"),
    path("schedules/<int:pk>/status/", views.schedule_status, name="schedule_status"),

    # Rules
    path("schedules/<int:pk>/rules/save/", views.rule_save, name="rule_save"),
    path("schedules/<int:pk>/rules/<int:rid>/delete/", views.rule_delete, name="rule_delete"),

    # Monitor
    path("monitor/", views.monitor_view, name="monitor"),

    # Alerts & Snapshots
    path("alerts/", views.alerts, name="alerts"),
    path("alerts/stats/", views.alerts_stats, name="alerts_stats"),
    path("alerts/snapshot/<path:rel_path>", views.snapshot_image, name="snapshot_image"),

    # Public API
    path("api/edge-info/", views.edge_info, name="edge_info"),
    path("api/cameras/", views.api_cameras, name="api_cameras"),
    path("api/models/labels/", views.model_labels_proxy, name="model_labels_proxy"),

    # Settings
    path("settings/", views.settings_view, name="settings"),
    path("settings/users/new/", views.user_create, name="user_create"),
    path("settings/users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("settings/branding/", views.site_branding_save, name="site_branding_save"),
    path("settings/edge/", views.edge_settings, name="edge_settings"),
    path("settings/edge/generate-key/", views.generate_api_key, name="generate_api_key"),
    path('settings/push-to-engine/', views.push_to_engine, name='push_to_engine'),
    path('settings/models/', views.models_list_proxy, name='models_list_proxy'),
    path('settings/models/upload/', views.model_upload, name='model_upload'),
    path('settings/models/<str:filename>/delete/', views.model_delete, name='model_delete'),
    path("settings/operations/schedules/", views.schedule_status_all, name="schedule_status_all"),
    path("settings/operations/purge/preview/", views.purge_preview_view, name="purge_preview"),
    path("settings/operations/purge/execute/", views.purge_execute_view, name="purge_execute"),

    # API v1 (API-key auth)
    path("api/v1/cameras/", views.api_v1_cameras, name="api_v1_cameras"),
    path("api/v1/schedules/", views.api_v1_schedules, name="api_v1_schedules"),
    path("api/v1/schedules/<int:pk>/start/", views.api_v1_schedule_start, name="api_v1_schedule_start"),
    path("api/v1/schedules/<int:pk>/stop/", views.api_v1_schedule_stop, name="api_v1_schedule_stop"),
    path("api/v1/purge/preview/", views.api_v1_purge_preview, name="api_v1_purge_preview"),
    path("api/v1/purge/execute/", views.api_v1_purge_execute, name="api_v1_purge_execute"),
]
