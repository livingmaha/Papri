# backend/api/urls.py
from django.urls import path
from .views import (
    UserDetailView, UserProfileView, auth_status_view, ActivateAccountView,
    InitiateSearchView, SearchStatusView, SearchResultsView,
    VideoEditProjectListCreateView, VideoEditProjectDetailView,
    EditTaskListCreateView, EditTaskStatusView
)

app_name = 'api'  # Namespace for this app's URLs

urlpatterns = [
    # User and Auth
    path('auth/status/', auth_status_view, name='auth_status'),
    path('auth/user/', UserDetailView.as_view(), name='user_detail'),
    path('auth/profile/', UserProfileView.as_view(), name='user_profile'),
    path('auth/activate/', ActivateAccountView.as_view(), name='activate_account'),
    # Note: Login, Logout, Signup, Password Reset etc., are handled by django-allauth under /accounts/

    # Search
    path('search/initiate/', InitiateSearchView.as_view(), name='search_initiate'),
    path('search/status/<uuid:task_id>/', SearchStatusView.as_view(), name='search_status'),
    path('search/results/<uuid:task_id>/', SearchResultsView.as_view(), name='search_results'),

    # AI Video Editor
    path('video_editor/projects/', VideoEditProjectListCreateView.as_view(), name='video_edit_project_list_create'),
    path('video_editor/projects/<int:id>/', VideoEditProjectDetailView.as_view(), name='video_edit_project_detail'), # Project ID is BigAutoField (int)
    path('video_editor/projects/<int:project_id>/tasks/', EditTaskListCreateView.as_view(), name='edit_task_list_create'),
    path('video_editor/tasks/<uuid:id>/status/', EditTaskStatusView.as_view(), name='edit_task_status'), # Task ID is UUID
]
