from django.urls import path

from apps.articles.views import (
    ArticleBulkPasteView,
    ArticleBulkStatusView,
    ArticleDetailView,
    ArticleImportConfirmView,
    ArticleImportPreviewView,
    ArticleListCreateView,
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
from apps.platforms.views import PlatformActionView, PlatformDetailView, PlatformListCreateView

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
    path("articles/<int:pk>", ArticleDetailView.as_view()),
    path("articles/bulk-paste", ArticleBulkPasteView.as_view()),
    path("articles/bulk-status", ArticleBulkStatusView.as_view()),
    path("article-imports", ArticleImportPreviewView.as_view()),
    path("article-imports/<int:pk>/confirm", ArticleImportConfirmView.as_view()),
    path("platforms", PlatformListCreateView.as_view()),
    path("platforms/<int:pk>", PlatformDetailView.as_view()),
    path("platforms/<int:pk>/<str:action>", PlatformActionView.as_view()),
    path("operation-logs", OperationLogListView.as_view()),
    path("detection-batches", DetectionBatchListCreateView.as_view()),
    path("detection-batches/<int:pk>", DetectionBatchDetailView.as_view()),
    path("detection-batches/<int:pk>/matrix", DetectionMatrixView.as_view()),
    path("detection-batches/<int:pk>/statistics", DetectionStatisticsView.as_view()),
    path("detection-results/<int:pk>/reposts", DetectionResultRepostsView.as_view()),
    path("detection-selection-defaults", DetectionSelectionDefaultsView.as_view()),
    path("status-matrix", StatusMatrixView.as_view()),
    path("status-snapshots", StatusSnapshotListView.as_view()),
]
