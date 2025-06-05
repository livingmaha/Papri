# backend/api/views.py
import os
import uuid
import logging
import json # Added for papri_app_view context

from django.conf import settings
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render
from django.urls import reverse # Added for papri_app_view context
from django.http import JsonResponse # Not directly used but good to have
from django.db.models import Case, When, Value, IntegerField, Prefetch
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone # For ActivateAccountView

from rest_framework import generics, views, status, permissions, serializers # Added serializers for perform_create
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import MultiPartParser, FormParser

from allauth.account.utils import send_email_confirmation

# Import for django-ratelimit
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

from .models import (
    UserProfile, SearchTask, SignupCode, Video, VideoSource,
    VideoEditProject, EditTask, Transcript # Transcript added for SearchResultsView
)
from .serializers import (
    UserSerializer, UserProfileSerializer, SearchTaskSerializer,
    InitiateSearchQuerySerializer, VideoResultSerializer, # VideoSourceResultSerializer removed as it's part of VideoResultSerializer
    SignupCodeSerializer, ActivateAccountSerializer,
    VideoEditProjectSerializer, EditTaskSerializer
)
from .tasks import process_search_query_task, process_video_edit_task

logger = logging.getLogger(__name__)

# --- User and Authentication Views ---

class UserDetailView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user

class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

@ratelimit(key=settings.RATELIMIT_KEYS.get('auth_actions', 'ip'), group='auth_actions', rate=settings.RATELIMIT_DEFAULTS.get('auth_actions', '30/m'), block=True)
@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def auth_status_view(request):
    if request.user.is_authenticated:
        user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response({
            'isAuthenticated': True,
            'user': UserSerializer(request.user).data,
            'profile': UserProfileSerializer(user_profile).data
        })
    return Response({'isAuthenticated': False})

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('auth_actions', 'ip'), group='auth_actions', rate=settings.RATELIMIT_DEFAULTS.get('auth_actions', '10/h'), block=True), name='post')
class ActivateAccountView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = ActivateAccountSerializer(data=request.data)
        if serializer.is_valid():
            code_value = serializer.validated_data['code']
            try:
                signup_code = SignupCode.objects.get(
                    code=code_value,
                    is_used=False,
                    expires_at__gte=timezone.now()
                )
                user, created = User.objects.get_or_create(
                    email=signup_code.email,
                    defaults={'username': signup_code.email}
                )

                if created: # If new user via signup code (less common for allauth setup)
                    user.is_active = True
                    user.save(update_fields=['is_active'])
                    # Ensure UserProfile is created
                    user_profile, _ = UserProfile.objects.get_or_create(user=user)
                    if not user.emailaddress_set.filter(verified=True, primary=True).exists():
                         send_email_confirmation(request, user) # Trigger email verification
                else: # Existing user
                    user_profile, _ = UserProfile.objects.get_or_create(user=user)
                    if not user.is_active:
                        user.is_active = True
                        user.save(update_fields=['is_active'])
                
                user_profile.subscription_plan = signup_code.plan_name
                if "monthly" in signup_code.plan_name.lower():
                    user_profile.subscription_expiry_date = timezone.now() + timezone.timedelta(days=30)
                elif "yearly" in signup_code.plan_name.lower():
                    user_profile.subscription_expiry_date = timezone.now() + timezone.timedelta(days=365)
                else:
                    user_profile.subscription_expiry_date = timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS)
                
                user_profile.remaining_trial_searches = 0
                user_profile.save()

                signup_code.is_used = True
                signup_code.user_activated = user # Changed from used_by
                signup_code.used_at = timezone.now()
                signup_code.save()

                logger.info(f"Account for {user.email} activated/upgraded with code {code_value}.")
                return Response({
                    "success": True,
                    "message": f"Account for {user.email} successfully activated/upgraded to {signup_code.plan_name}."
                }, status=status.HTTP_200_OK)
            except SignupCode.DoesNotExist:
                logger.warning(f"Invalid, expired, or used signup code attempted: {code_value}")
                return Response({"success": False, "error": "Invalid, expired, or already used signup code."}, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist: # Should be caught by get_or_create, but as a safeguard
                logger.error(f"User not found for email associated with signup code {code_value}.")
                return Response({"success": False, "error": "User not found for this code's email."}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error during account activation with code {code_value}: {e}", exc_info=True)
                return Response({"success": False, "error": "An unexpected error occurred during activation."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- Search Task Views ---
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_search_initiate', 'user_or_ip_key'), group='api_search_initiate', rate=settings.RATELIMIT_DEFAULTS.get('api_search_initiate', '20/m'), block=True), name='post')
class InitiateSearchView(views.APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        query_serializer = InitiateSearchQuerySerializer(data=request.data)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = query_serializer.validated_data
        query_text = validated_data.get('query_text')
        query_image_file = validated_data.get('query_image')
        query_video_url = validated_data.get('query_video_url')
        filters_json = validated_data.get('filters', {})

        user = request.user if request.user.is_authenticated else None
        session_id = request.session.session_key
        if not session_id:
            request.session.create()
            session_id = request.session.session_key
        
        if not user:
            trial_searches_key = f"trial_searches_{session_id}"
            current_trial_count = request.session.get(trial_searches_key, 0)
            if current_trial_count >= getattr(settings, 'MAX_DEMO_SEARCHES', 3):
                 return Response({"error": "Demo search limit reached. Please sign up for more searches."}, status=status.HTTP_402_PAYMENT_REQUIRED)
            request.session[trial_searches_key] = current_trial_count + 1

        image_ref_path = None
        if query_image_file:
            try:
                temp_dir_name = 'temp_query_images'
                os.makedirs(os.path.join(settings.MEDIA_ROOT, temp_dir_name), exist_ok=True)
                safe_filename = f"queryimg_{uuid.uuid4().hex}{os.path.splitext(query_image_file.name)[1]}"
                image_ref_path_relative = os.path.join(temp_dir_name, safe_filename)
                saved_path = default_storage.save(image_ref_path_relative, query_image_file)
                image_ref_path = saved_path
            except Exception as e:
                logger.error(f"Could not process uploaded query image: {e}", exc_info=True)
                return Response({"error": "Could not process uploaded image."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        search_task = SearchTask.objects.create(
            user=user, session_id=session_id, query_text=query_text,
            query_image_ref=image_ref_path, query_video_url=query_video_url,
            applied_filters_json=filters_json if isinstance(filters_json, dict) else {},
            status='pending'
        )
        process_search_query_task.delay(search_task.id)
        task_data = SearchTaskSerializer(search_task, context={'request': request}).data
        return Response(task_data, status=status.HTTP_202_ACCEPTED)

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'ip_key'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
class SearchStatusView(views.APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, task_id, *args, **kwargs):
        try:
            search_task = SearchTask.objects.get(id=uuid.UUID(task_id))
            task_data = SearchTaskSerializer(search_task, context={'request': request}).data
            return Response(task_data)
        except SearchTask.DoesNotExist:
            return Response({"error": "Search task not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError:
            return Response({"error": "Invalid task ID format."}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'ip_key'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
class SearchResultsView(views.APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, task_id, *args, **kwargs):
        try:
            search_task = get_object_or_404(SearchTask, id=uuid.UUID(task_id))
        except ValueError: # Handles malformed UUID
            return Response({"error": "Invalid task ID format."}, status=status.HTTP_400_BAD_REQUEST)

        if search_task.status not in ['completed', 'partial_results']:
            return Response({"task_status": search_task.status, "message": "Search is still processing or has failed.","results_data": []},
                            status=status.HTTP_202_ACCEPTED if search_task.status in ['pending', 'processing'] else status.HTTP_200_OK)
        
        detailed_ranked_results_from_task = search_task.detailed_results_info_json or []
        if not detailed_ranked_results_from_task:
            return Response({"results_data": [], "task_status": search_task.status, "message": "No results found."}, status.HTTP_200_OK)

        video_ids_ordered = [item['video_id'] for item in detailed_ranked_results_from_task if 'video_id' in item]
        if not video_ids_ordered:
             return Response({"results_data": [], "task_status": search_task.status, "message": "No video IDs found in results detail."}, status.HTTP_200_OK)

        preserved_order = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(video_ids_ordered)], output_field=IntegerField())
        
        # Prefetch related sources and their transcripts for efficiency
        videos_queryset = Video.objects.filter(id__in=video_ids_ordered).prefetch_related(
            Prefetch('sources', queryset=VideoSource.objects.select_related('video')) # Corrected from transcript_data to video
        ).order_by(preserved_order)

        video_details_map = {item['video_id']: item for item in detailed_ranked_results_from_task}
        
        serialized_videos = []
        for video_obj in videos_queryset:
            details = video_details_map.get(str(video_obj.id)) # Ensure ID is string for map lookup
            if details:
                video_obj.relevance_score = details.get('combined_score', 0.0)
                video_obj.match_types = details.get('match_types', [])
                
                best_source_data = details.get('best_source')
                if best_source_data and isinstance(best_source_data, dict) and best_source_data.get('platform_video_id'):
                    primary_source_instance = next(
                        (s for s in video_obj.sources.all() if s.platform_video_id == best_source_data['platform_video_id'] and s.platform_name == best_source_data['platform_name']),
                        None
                    )
                    if primary_source_instance:
                        primary_source_instance.match_score = best_source_data.get('match_score', video_obj.relevance_score)
                        primary_source_instance.match_type_tags = best_source_data.get('match_type_tags', video_obj.match_types)
                        primary_source_instance.best_match_timestamp_ms = best_source_data.get('best_match_timestamp_ms')
                        primary_source_instance.relevant_text_snippet = best_source_data.get('relevant_text_snippet')
                        video_obj.primary_source_display = primary_source_instance
                    else: 
                         video_obj.primary_source_display = best_source_data 
                else: video_obj.primary_source_display = None # Ensure it's None if no valid best_source_data
                
                serialized_videos.append(video_obj)

        page_size_str = request.query_params.get('page_size', str(settings.REST_FRAMEWORK.get('PAGE_SIZE', 10)))
        try:
            page_size = int(page_size_str)
            if page_size <= 0 or page_size > settings.REST_FRAMEWORK.get('MAX_PAGE_SIZE', 100):
                page_size = settings.REST_FRAMEWORK.get('PAGE_SIZE', 10)
        except ValueError:
            page_size = settings.REST_FRAMEWORK.get('PAGE_SIZE', 10)

        paginator = Paginator(serialized_videos, page_size)
        page_number = request.query_params.get('page', 1)
        try: page_obj = paginator.page(page_number)
        except PageNotAnInteger: page_obj = paginator.page(1)
        except EmptyPage: page_obj = paginator.page(paginator.num_pages)

        serializer = VideoResultSerializer(page_obj, many=True, context={'request': request})
        return Response({
            'task_status': search_task.status, 'count': paginator.count, 'num_pages': paginator.num_pages,
            'current_page': page_obj.number, 'next': page_obj.has_next(), 'previous': page_obj.has_previous(),
            'results_data': serializer.data
        })


# --- AI Video Editor Views ---
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'user'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_edit_task_create', 'user'), group='api_edit_task_create', rate=settings.RATELIMIT_DEFAULTS.get('api_edit_task_create', '10/h'), block=True), name='post')
class VideoEditProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = VideoEditProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return VideoEditProject.objects.filter(user=self.request.user).order_by('-created_at').prefetch_related('edit_tasks')

    def perform_create(self, serializer):
        user = self.request.user
        uploaded_video_file = self.request.FILES.get('uploaded_video_file')
        uploaded_video_path_final = None

        if uploaded_video_file:
            try:
                edit_temp_dir_name = os.path.join('user_edits_temp', str(user.id))
                os.makedirs(os.path.join(settings.MEDIA_ROOT, edit_temp_dir_name), exist_ok=True)
                safe_filename = f"edit_upload_{uuid.uuid4().hex}{os.path.splitext(uploaded_video_file.name)[1]}"
                relative_path = os.path.join(edit_temp_dir_name, safe_filename)
                saved_path = default_storage.save(relative_path, uploaded_video_file)
                uploaded_video_path_final = saved_path
                logger.info(f"User {user.id} uploaded video for editing: {uploaded_video_path_final}")
            except Exception as e:
                logger.error(f"Error saving uploaded video for editing by user {user.id}: {e}", exc_info=True)
                raise serializers.ValidationError({"uploaded_video_file": f"Failed to save uploaded video: {str(e)}"}) # Use DRF validation error
        
        serializer.save(user=user, uploaded_video_path=uploaded_video_path_final) # Use correct field name
        logger.info(f"VideoEditProject created for user {user.id}")

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'user'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_edit_task_create', 'user'), group='api_edit_task_create', rate=settings.RATELIMIT_DEFAULTS.get('api_edit_task_create', '20/h'), block=True), name='put')
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_edit_task_create', 'user'), group='api_edit_task_create', rate=settings.RATELIMIT_DEFAULTS.get('api_edit_task_create', '20/h'), block=True), name='patch')
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_edit_task_create', 'user'), group='api_edit_task_create', rate=settings.RATELIMIT_DEFAULTS.get('api_edit_task_create', '20/h'), block=True), name='delete')
class VideoEditProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VideoEditProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return VideoEditProject.objects.filter(user=self.request.user).prefetch_related('edit_tasks')

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'user'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_edit_task_create', 'user'), group='api_edit_task_create', rate=settings.RATELIMIT_DEFAULTS.get('api_edit_task_create', '10/h'), block=True), name='post')
class EditTaskListCreateView(generics.ListCreateAPIView):
    serializer_class = EditTaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        project_id = self.kwargs.get('project_id')
        project = get_object_or_404(VideoEditProject, id=project_id, user=self.request.user)
        return EditTask.objects.filter(project=project).order_by('-created_at')

    def perform_create(self, serializer):
        project_id = self.kwargs.get('project_id')
        project = get_object_or_404(VideoEditProject, id=project_id, user=self.request.user)
        if not project.original_video_source and not project.uploaded_video_path: # Check path
            raise serializers.ValidationError("The project does not have a video associated for editing.")
        edit_task_instance = serializer.save(project=project)
        logger.info(f"EditTask {edit_task_instance.id} created for project {project.id}. Dispatching to Celery.")
        process_video_edit_task.delay(edit_task_instance.id)

@method_decorator(ratelimit(key=settings.RATELIMIT_KEYS.get('api_general_read', 'user'), group='api_general_read', rate=settings.RATELIMIT_DEFAULTS.get('api_general_read', '300/m'), block=True), name='get')
class EditTaskStatusView(generics.RetrieveAPIView):
    serializer_class = EditTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return EditTask.objects.filter(project__user=self.request.user)

def papri_app_view(request):
    api_base_url = settings.API_BASE_URL_FRONTEND
    if not api_base_url.startswith(('http://', 'https://')) and api_base_url: # if relative, make absolute
        api_base_url = request.build_absolute_uri(api_base_url.lstrip('/'))
    elif not api_base_url: # if empty, means same origin
        api_base_url = request.build_absolute_uri('/api') # Default to /api on same origin

    context = {
        'django_context_json': json.dumps({
            'API_BASE_URL': api_base_url.rstrip('/'),
            'PAYSTACK_PUBLIC_KEY': settings.PAYSTACK_PUBLIC_KEY,
            'LOGOUT_URL': reverse('account_logout'),
        })
    }
    return render(request, 'papriapp.html', context)
