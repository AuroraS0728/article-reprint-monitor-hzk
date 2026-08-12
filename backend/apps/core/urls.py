from django.urls import path

from apps.articles.views import (
    ArticleBulkPasteView,
    ArticleBulkStatusView,
    ArticleDetailView,
    ArticleImportConfirmView,
    ArticleImportPreviewView,
    ArticleListCreateView,
    ArticleRepostsView,
)
from apps.audit.views import OperationLogListView
from apps.monitoring.views import (
    DetectionBatchDetailView,
    DetectionBatchListCreateView,
    DetectionMatrixView,
    DetectionResultRepostsView,
    DetectionSelectionDefaultsView,
    DetectionStatisticsView,
    StatusMatrixView,
    StatusSnapshotListView,
)
from apps.operations.views import (
    DatabaseBackupListView,
    FailedDetectionBatchListView,
    MaintenanceActionView,
    MaintenanceRunListView,
    RuntimeStatusView,
    SystemRuntimeConfigurationView,
    TaskFailureLogListView,
)
from apps.platforms.views import PlatformActionView, PlatformDetailView, PlatformListCreateView
from apps.reports.views import (
    EmailDeliveryListView,
    EmailDeliveryResendView,
    ReportDownloadView,
    ReportListView,
    ReportRegenerateView,
    SMTPConfigurationView,
    TestEmailView,
)
from apps.reposts.views import (
    GlobalRepostExportView,
    ManualRepostCreateView,
    ManualRepostValidityView,
    RepostRecordListView,
)
from apps.sources.views import (
    ArticleIngestConflictListView,
    ArticleIngestConflictReviewView,
    ManualGlobalSearchView,
    SourceArticleIngestView,
)

from .views import ChangePasswordView, HealthView, LoginView, LogoutView, MeView, UserDetailView, UserListCreateView

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("auth/login", LoginView.as_view()),
    path("auth/logout", LogoutView.as_view()),
    path("auth/me", MeView.as_view()),
    path("auth/change-password", ChangePasswordView.as_view()),
    path("users", UserListCreateView.as_view()),
    path("users/<int:pk>", UserDetailView.as_view()),
    path("articles", ArticleListCreateView.as_view()),
    path("source-ingest/articles", SourceArticleIngestView.as_view()),
    path("source-ingest-conflicts", ArticleIngestConflictListView.as_view()),
    path("source-ingest-conflicts/<int:pk>/review", ArticleIngestConflictReviewView.as_view()),
    path("global-search-runs", ManualGlobalSearchView.as_view()),
    path("articles/<int:pk>", ArticleDetailView.as_view()),
    path("articles/<int:pk>/reposts", ArticleRepostsView.as_view()),
    path("articles/bulk-paste", ArticleBulkPasteView.as_view()),
    path("articles/bulk-status", ArticleBulkStatusView.as_view()),
    path("article-imports", ArticleImportPreviewView.as_view()),
    path("article-imports/<int:pk>/confirm", ArticleImportConfirmView.as_view()),
    path("platforms", PlatformListCreateView.as_view()),
    path("platforms/<int:pk>", PlatformDetailView.as_view()),
    path("platforms/<int:pk>/<str:action>", PlatformActionView.as_view()),
    path("operation-logs", OperationLogListView.as_view()),
    path("system-runtime-configuration", SystemRuntimeConfigurationView.as_view()),
    path("runtime-status", RuntimeStatusView.as_view()),
    path("failed-detection-batches", FailedDetectionBatchListView.as_view()),
    path("task-failure-logs", TaskFailureLogListView.as_view()),
    path("maintenance-runs", MaintenanceRunListView.as_view()),
    path("database-backups", DatabaseBackupListView.as_view()),
    path("maintenance/<str:action>", MaintenanceActionView.as_view()),
    path("detection-batches", DetectionBatchListCreateView.as_view()),
    path("detection-batches/<int:pk>", DetectionBatchDetailView.as_view()),
    path("detection-batches/<int:pk>/matrix", DetectionMatrixView.as_view()),
    path("detection-batches/<int:pk>/statistics", DetectionStatisticsView.as_view()),
    path("detection-results/<int:pk>/reposts", DetectionResultRepostsView.as_view()),
    path("repost-records", RepostRecordListView.as_view()),
    path("repost-monitor/export.xlsx", GlobalRepostExportView.as_view()),
    path("manual-reposts", ManualRepostCreateView.as_view()),
    path("manual-reposts/<int:pk>/<str:action>", ManualRepostValidityView.as_view()),
    path("detection-selection-defaults", DetectionSelectionDefaultsView.as_view()),
    path("status-matrix", StatusMatrixView.as_view()),
    path("status-snapshots", StatusSnapshotListView.as_view()),
    path("reports", ReportListView.as_view()),
    path("reports/<int:pk>/download", ReportDownloadView.as_view()),
    path("reports/<int:pk>/regenerate", ReportRegenerateView.as_view()),
    path("smtp-configuration", SMTPConfigurationView.as_view()),
    path("report-email-deliveries", EmailDeliveryListView.as_view()),
    path("report-email-deliveries/<int:pk>/resend", EmailDeliveryResendView.as_view()),
    path("smtp-configuration/test-email", TestEmailView.as_view()),
]
