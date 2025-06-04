# backend/api/views.py
import os
import uuid # For generating unique filenames for uploaded query images
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.db.models import Case, When, Value, IntegerField, Prefetch
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


from rest_framework import generics, views, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import MultiPartParser, FormParser # For file uploads

from allauth.account.utils import send_email_confirmation # For resending verification

from .models import (
    UserProfile, SearchTask, SignupCode, Video, VideoSource,
    VideoEditProject, EditTask
)
from .serializers import (
    UserSerializer, UserProfileSerializer, SearchTaskSerializer,
    InitiateSearchQuerySerializer, VideoResultSerializer, VideoSourceResultSerializer,
    SignupCodeSerializer, ActivateAccountSerializer,
    VideoEditProjectSerializer, EditTaskSerializer
)
from .tasks import process_search_query_task, process_video_edit_task

logger = logging.getLogger(__name__) # Get a logger instance for this module

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

@api_view(['GET'])
@permission_classes([permissions.AllowAny]) # Or IsAuthenticated if you only want logged-in users to check
def auth_status_view(request):
    if request.user.is_authenticated:
        user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response({
            'isAuthenticated': True,
            'user': UserSerializer(request.user).data,
            'profile': UserProfileSerializer(user_profile).data
        })
    return Response({'isAuthenticated': False})


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
                # Check if user with this email exists
                user, created = User.objects.get_or_create(
                    email=signup_code.email,
                    defaults={'username': signup_code.email} # Set username to email initially
                )

                if created:
                    # For new users, you might want to set a default unusable password
                    # or integrate with allauth's signup flow more deeply.
                    # For simplicity, let's assume allauth handles new user creation via social/regular signup
                    # and this code is for upgrading or activating a feature.
                    user.is_active = True # Activate user if they were inactive
                    # You might want to send a welcome email or confirm email verification
                    if not user.profile.user.emailaddress_set.filter(verified=True).exists():
                         send_email_confirmation(request, user)

                # Update user's profile/subscription
                user_profile, _ = UserProfile.objects.get_or_create(user=user)
                user_profile.subscription_plan = signup_code.plan_name # Example: "Papri Pro"
                # Set expiry based on plan, or other logic
                user_profile.subscription_expiry_date = timezone.now() + timezone.timedelta(days=30) # Example
                user_profile.remaining_trial_searches = 0 # Clear trial searches if any
                user_profile.save()

                signup_code.is_used = True
                signup_code.used_by = user
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
            except User.DoesNotExist: # Should not happen with get_or_create
                logger.error(f"User not found for email associated with signup code {code_value}.")
                return Response({"success": False, "error": "User not found for this code's email."}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"Error during account activation with code {code_value}: {e}", exc_info=True)
                return Response({"success": False, "error": "An unexpected error occurred during activation."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# --- Search Task Views ---
class InitiateSearchView(views.APIView):
    permission_classes = [permissions.AllowAny] # Allow anonymous for trial or logged in
    parser_classes = [MultiPartParser, FormParser] # For handling file uploads (query_image)

    def post(self, request, *args, **kwargs):
        query_serializer = InitiateSearchQuerySerializer(data=request.data)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = query_serializer.validated_data
        query_text = validated_data.get('query_text')
        query_image_file = validated_data.get('query_image')
        query_video_url = validated_data.get('query_video_url')
        filters_json = validated_data.get('filters', {})

        # User and session handling
        user = request.user if request.user.is_authenticated else None
        session_id = request.session.session_key
        if not session_id:
            request.session.create()
            session_id = request.session.session_key
        
        # Trial logic for anonymous or free tier users
        if user:
            user_profile, _ = UserProfile.objects.get_or_create(user=user)
            # TODO: Implement proper subscription check here.
            # For now, let's assume if authenticated, they have access or it's handled by plan.
        else: # Anonymous user, check trial
            trial_searches_key = f"trial_searches_{session_id}"
            current_trial_count = request.session.get(trial_searches_key, 0)
            if current_trial_count >= getattr(settings, 'MAX_DEMO_SEARCHES', 3): # Example limit
                 return Response({"error": "Demo search limit reached. Please sign up for more searches."}, status=status.HTTP_402_PAYMENT_REQUIRED)
            request.session[trial_searches_key] = current_trial_count + 1


        image_ref_path = None
        image_fingerprint_hash = None # Placeholder for a basic hash

        if query_image_file:
            try:
                # Ensure the temp_query_images directory exists within MEDIA_ROOT
                temp_dir_name = 'temp_query_images'
                temp_dir_path = os.path.join(settings.MEDIA_ROOT, temp_dir_name)
                os.makedirs(temp_dir_path, exist_ok=True)
                
                # Sanitize filename and create a unique name
                original_filename, original_extension = os.path.splitext(query_image_file.name)
                safe_filename = f"queryimg_{uuid.uuid4().hex}{original_extension}"
                
                # Path relative to MEDIA_ROOT for storage and later access by Celery task
                image_ref_path_relative = os.path.join(temp_dir_name, safe_filename)
                
                # Save file using Django's default storage
                saved_path = default_storage.save(image_ref_path_relative, query_image_file)
                image_ref_path = saved_path # This is the path relative to MEDIA_ROOT
                
                # TODO: Generate image_fingerprint_hash if needed (e.g., MD5 or SHA1 of file content)
                # For simplicity, we'll skip this for now.

            except Exception as e:
                logger.error(f"Could not process uploaded query image: {e}", exc_info=True)
                return Response({"error": "Could not process uploaded image."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        search_task = SearchTask.objects.create(
            user=user,
            session_id=session_id,
            query_text=query_text,
            query_image_ref=image_ref_path, # Store path relative to MEDIA_ROOT
            query_image_fingerprint=image_fingerprint_hash,
            query_video_url=query_video_url,
            applied_filters_json=filters_json if isinstance(filters_json, dict) else {},
            status='pending'
        )
        
        # Dispatch Celery task
        process_search_query_task.delay(search_task.id)
        
        # Return initial task info
        task_data = SearchTaskSerializer(search_task, context={'request': request}).data
        return Response(task_data, status=status.HTTP_202_ACCEPTED)


class SearchStatusView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, task_id, *args, **kwargs):
        try:
            search_task = SearchTask.objects.get(id=uuid.UUID(task_id))
            # Basic ownership/session check for privacy (optional for simple status)
            # if search_task.user and search_task.user != request.user:
            #     if search_task.session_id != request.session.session_key:
            #         return Response({"error": "Access denied."}, status=status.HTTP_403_FORBIDDEN)
            
            task_data = SearchTaskSerializer(search_task, context={'request': request}).data
            return Response(task_data)
        except SearchTask.DoesNotExist:
            return Response({"error": "Search task not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError: # Invalid UUID format
            return Response({"error": "Invalid task ID format."}, status=status.HTTP_400_BAD_REQUEST)


class SearchResultsView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, task_id, *args, **kwargs):
        try:
            search_task = get_object_or_404(SearchTask, id=uuid.UUID(task_id))
        except ValueError:
            return Response({"error": "Invalid task ID format."}, status.HTTP_400_BAD_REQUEST)

        # Basic ownership/session check (important for results)
        # if search_task.user and search_task.user != request.user:
        #     if search_task.session_id != request.session.session_key:
        #         return Response({"error": "Access denied to results."}, status=status.HTTP_403_FORBIDDEN)

        if search_task.status not in ['completed', 'partial_results']:
            return Response({
                "task_status": search_task.status,
                "message": "Search is still processing or has failed.",
                "results_data": []
            }, status=status.HTTP_202_ACCEPTED if search_task.status in ['pending', 'processing'] else status.HTTP_200_OK)

        # `detailed_results_info_json` is expected to be a list of dicts like:
        # [ { "video_id": canonical_video_id1, "combined_score": 0.95, "match_types": ["text", "visual"],
        #     "best_source": { "platform_video_id": "xyz", "platform_name": "youtube", ...,
        #                      "best_match_timestamp_ms": 15000, "relevant_text_snippet": "..."} }, ... ]
        
        detailed_ranked_results_from_task = search_task.detailed_results_info_json or []

        if not detailed_ranked_results_from_task:
            return Response({
                "task_status": search_task.status,
                "message": "No results found or processing error.",
                "results_data": []
            }, status=status.HTTP_200_OK)

        # Get canonical Video IDs in the ranked order
        video_ids_ordered = [item['video_id'] for item in detailed_ranked_results_from_task if 'video_id' in item]
        if not video_ids_ordered:
             return Response({"results_data": [], "task_status": search_task.status, "message": "No video IDs found in results."}, status.HTTP_200_OK)

        # Preserve order of video_ids_ordered when fetching from DB
        preserved_order = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(video_ids_ordered)], output_field=IntegerField())
        
        # Prefetch related sources and their transcripts for efficiency
        videos_queryset = Video.objects.filter(id__in=video_ids_ordered).prefetch_related(
            Prefetch('sources', queryset=VideoSource.objects.select_related('transcript_data'))
        ).order_by(preserved_order)

        # Map detailed info from task back to video objects for serialization
        video_details_map = {item['video_id']: item for item in detailed_ranked_results_from_task}
        
        serialized_videos = []
        for video_obj in videos_queryset:
            details = video_details_map.get(video_obj.id)
            if details:
                # Dynamically add RARAgent's scores and primary source info to the Video object for the serializer
                video_obj.relevance_score = details.get('combined_score', 0.0)
                video_obj.match_types = details.get('match_types', [])
                
                # Populate a 'primary_source_display' if available from RARAgent's output
                best_source_data = details.get('best_source')
                if best_source_data and best_source_data.get('platform_video_id'):
                    # Find the actual VideoSource model instance to serialize
                    primary_source_instance = next(
                        (s for s in video_obj.sources.all() if s.platform_video_id == best_source_data['platform_video_id'] and s.platform_name == best_source_data['platform_name']),
                        None
                    )
                    if primary_source_instance:
                        # Augment this instance with RARAgent specific details for serialization
                        primary_source_instance.match_score = best_source_data.get('match_score', video_obj.relevance_score) # or a specific source score
                        primary_source_instance.match_type_tags = best_source_data.get('match_type_tags', video_obj.match_types)
                        primary_source_instance.best_match_timestamp_ms = best_source_data.get('best_match_timestamp_ms')
                        primary_source_instance.relevant_text_snippet = best_source_data.get('relevant_text_snippet')
                        video_obj.primary_source_display = primary_source_instance
                    else: # Fallback if specific source not found, but data exists
                         video_obj.primary_source_display = best_source_data # Or serialize this dict directly if serializer supports it
                
                serialized_videos.append(video_obj)

        # Paginate the prepared list of video objects
        paginator = Paginator(serialized_videos, request.query_params.get('page_size', 10))
        page_number = request.query_params.get('page', 1)
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        serializer = VideoResultSerializer(page_obj, many=True, context={'request': request})
        
        return Response({
            'task_status': search_task.status,
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'current_page': page_obj.number,
            'next': page_obj.has_next(),
            'previous': page_obj.has_previous(),
            'results_data': serializer.data
        })


# --- AI Video Editor Views ---
class VideoEditProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = VideoEditProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # If allowing direct video upload here

    def get_queryset(self):
        return VideoEditProject.objects.filter(user=self.request.user).order_by('-created_at').prefetch_related('edit_tasks')

    def perform_create(self, serializer):
        user = self.request.user
        uploaded_video_file = self.request.FILES.get('uploaded_video_file') # Name used in serializer if FileField
        uploaded_video_name_final = None

        if uploaded_video_file:
            try:
                # Ensure the user_edits_temp directory exists within MEDIA_ROOT
                edit_temp_dir_name = os.path.join('user_edits_temp', str(user.id))
                edit_temp_dir_path = os.path.join(settings.MEDIA_ROOT, edit_temp_dir_name)
                os.makedirs(edit_temp_dir_path, exist_ok=True)
                
                original_filename, original_extension = os.path.splitext(uploaded_video_file.name)
                safe_filename = f"edit_upload_{uuid.uuid4().hex}{original_extension}"
                
                # Path relative to MEDIA_ROOT
                relative_path = os.path.join(edit_temp_dir_name, safe_filename)
                
                saved_path = default_storage.save(relative_path, uploaded_video_file)
                uploaded_video_name_final = saved_path # Store this relative path
                logger.info(f"User {user.id} uploaded video for editing: {uploaded_video_name_final}")

            except Exception as e:
                logger.error(f"Error saving uploaded video for editing by user {user.id}: {e}", exc_info=True)
                # serializer.errors is not ideal here, raise custom exception or return error response
                raise serializers.ValidationError({"uploaded_video_file": f"Failed to save uploaded video: {str(e)}"})
        
        # original_video_source_id is handled by serializer if passed in request.data
        serializer.save(user=user, uploaded_video_name=uploaded_video_name_final)
        logger.info(f"VideoEditProject created for user {user.id}")


class VideoEditProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = VideoEditProjectSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id' # Assuming 'id' is BigAutoField for VideoEditProject

    def get_queryset(self):
        return VideoEditProject.objects.filter(user=self.request.user).prefetch_related('edit_tasks')


class EditTaskListCreateView(generics.ListCreateAPIView):
    serializer_class = EditTaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        project_id = self.kwargs.get('project_id')
        # Ensure project belongs to the user
        project = get_object_or_404(VideoEditProject, id=project_id, user=self.request.user)
        return EditTask.objects.filter(project=project).order_by('-created_at')

    def perform_create(self, serializer):
        project_id = self.kwargs.get('project_id')
        project = get_object_or_404(VideoEditProject, id=project_id, user=self.request.user)
        
        # Check if project has a video source or an uploaded file
        if not project.original_video_source and not project.uploaded_video_name:
            raise serializers.ValidationError("The project does not have a video associated for editing.")

        edit_task_instance = serializer.save(project=project)
        logger.info(f"EditTask {edit_task_instance.id} created for project {project.id}. Dispatching to Celery.")
        
        # Dispatch Celery task for video editing
        process_video_edit_task.delay(edit_task_instance.id)


class EditTaskStatusView(generics.RetrieveAPIView):
    serializer_class = EditTaskSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id' # This is the EditTask UUID

    def get_queryset(self):
        # Ensure user can only access their own tasks via project ownership
        return EditTask.objects.filter(project__user=self.request.user)

# Simple view to serve the main papriapp.html (SPA host)
# Requires login if your app is not public
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

# @login_required # Uncomment if the entire app requires login
def papri_app_view(request):
    # You can pass context to your template if needed, e.g., API base URL
    context = {
        'API_BASE_URL_FRONTEND': settings.API_BASE_URL_FRONTEND,
        'PAYSTACK_PUBLIC_KEY': settings.PAYSTACK_PUBLIC_KEY,
    }
    return render(request, 'papriapp.html', context)
