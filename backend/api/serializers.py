# backend/api/serializers.py
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    Video, VideoSource, Transcript, ExtractedKeyword, VideoTopic,
    VideoFrameFeature, UserProfile, SearchTask, SignupCode,
    VideoEditProject, EditTask
)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    class Meta:
        model = UserProfile
        fields = ['user', 'subscription_plan', 'subscription_expiry_date', 'remaining_trial_searches']


class SignupCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SignupCode
        fields = ['id', 'email', 'code', 'plan_name', 'is_used', 'is_expired', 'expires_at', 'created_at']
        read_only_fields = ['id', 'is_used', 'is_expired', 'created_at']


class ActivateAccountSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    # Optionally include password fields if setting password during activation
    # password = serializers.CharField(write_only=True, required=False)


# --- Video and Related Serializers ---

class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['language_code', 'full_text_content', 'transcript_timed_json', 'source_type']


class ExtractedKeywordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractedKeyword
        fields = ['keyword_text', 'relevance_score', 'source_field']


class VideoTopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoTopic
        fields = ['topic_name', 'confidence_score']


class VideoFrameFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoFrameFeature
        fields = ['timestamp_ms', 'feature_type', 'feature_data_json']


class VideoSourceResultSerializer(serializers.ModelSerializer):
    """Serializer for VideoSource when presented as part of search results."""
    transcript_data = TranscriptSerializer(read_only=True, required=False)
    # extracted_keywords = ExtractedKeywordSerializer(many=True, read_only=True, required=False)
    # video_topics = VideoTopicSerializer(many=True, read_only=True, required=False)
    # frame_features_sample = serializers.SerializerMethodField() # Example for a sample

    # Additional fields that might be populated by RARAgent from detailed_results_info_json
    match_score = serializers.FloatField(read_only=True, required=False)
    match_type_tags = serializers.ListField(child=serializers.CharField(), read_only=True, required=False) # e.g. ['transcript_kw', 'visual_sim']
    best_match_timestamp_ms = serializers.IntegerField(read_only=True, required=False, allow_null=True)
    relevant_text_snippet = serializers.CharField(read_only=True, required=False, allow_null=True)

    class Meta:
        model = VideoSource
        fields = [
            'id', 'platform_name', 'platform_video_id', 'original_url', 'embed_url',
            'thumbnail_url', 'uploader_name', 'view_count', 'like_count',
            'match_score', 'match_type_tags', 'best_match_timestamp_ms', 'relevant_text_snippet',
            'transcript_data', # 'extracted_keywords', 'video_topics', 'frame_features_sample'
            'created_at', 'updated_at', 'last_scraped_at',
        ]

    # def get_frame_features_sample(self, obj):
    #     # Example: return a small sample of frame features if needed in results
    #     sample_features = obj.frame_features.order_by('timestamp_ms')[:3] # Get first 3
    #     return VideoFrameFeatureSerializer(sample_features, many=True).data


class VideoResultSerializer(serializers.ModelSerializer):
    """Serializer for the canonical Video object in search results."""
    sources = VideoSourceResultSerializer(many=True, read_only=True)

    # Fields populated by RARAgent from SearchTask.detailed_results_info_json,
    # representing the aggregate score for this canonical video across its sources.
    # These are added dynamically in the view.
    relevance_score = serializers.FloatField(read_only=True, required=False)
    match_types = serializers.ListField(child=serializers.CharField(), read_only=True, required=False) # Overall match types for this video
    primary_source_display = VideoSourceResultSerializer(read_only=True, required=False, allow_null=True) # The best matching source


    class Meta:
        model = Video
        fields = [
            'id', 'title', 'description', 'duration_seconds', 'publication_date',
            'tags', 'category',
            'relevance_score', 'match_types', # Dynamically added
            'primary_source_display', # Dynamically added best source representation
            'sources', # All sources, or a primary one if preferred
            'created_at', 'updated_at'
        ]


class SearchTaskSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True, required=False)
    result_videos = VideoResultSerializer(many=True, read_only=True, source='detailed_results_info_json') # This is a conceptual mapping

    class Meta:
        model = SearchTask
        fields = [
            'id', 'user', 'session_id', 'query_text', 'query_image_ref', 'query_video_url',
            'applied_filters_json', 'status', 'celery_task_id', 'error_message',
            'result_video_ids_json', # Raw IDs
            'detailed_results_info_json', # Rich detailed results
            'result_videos', # Serialized representation for API (needs view logic)
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'session_id', 'status', 'celery_task_id', 'error_message', 'result_video_ids_json', 'detailed_results_info_json', 'result_videos', 'created_at', 'updated_at']

class InitiateSearchQuerySerializer(serializers.Serializer):
    query_text = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    query_image = serializers.ImageField(required=False, allow_null=True) # For file upload
    query_video_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    filters = serializers.JSONField(required=False, allow_null=True) # e.g., {"platforms": ["youtube"], "duration_min": 300}

    def validate(self, data):
        if not data.get('query_text') and not data.get('query_image') and not data.get('query_video_url'):
            raise serializers.ValidationError("At least one query input (text, image, or video URL) must be provided.")
        return data


# --- AI Video Editor Serializers ---

class EditTaskSerializer(serializers.ModelSerializer):
    result_url = serializers.SerializerMethodField()
    class Meta:
        model = EditTask
        fields = [
            'id', 'project', 'prompt_text', 'status', 'celery_task_id',
            'result_media_path', 'result_preview_url', 'result_url',
            'error_message', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'project', 'status', 'celery_task_id',
            'result_media_path', 'result_preview_url', 'result_url',
            'error_message', 'created_at', 'updated_at'
        ]
    
    def get_result_url(self, obj):
        return obj.get_result_url()


class VideoEditProjectSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    edit_tasks = EditTaskSerializer(many=True, read_only=True)
    # Allow original_video_source_id for linking existing video source
    original_video_source_id = serializers.PrimaryKeyRelatedField(
        queryset=VideoSource.objects.all(), source='original_video_source', write_only=True, required=False, allow_null=True
    )
    # For uploading a new video file directly (handled by the view)
    # uploaded_video_file = serializers.FileField(write_only=True, required=False, allow_null=True)


    class Meta:
        model = VideoEditProject
        fields = [
            'id', 'user', 'project_name',
            'original_video_source', # Read-only representation of linked source
            'original_video_source_id', # Write-only for linking
            'uploaded_video_name', # Name of the file if user uploaded one
            # 'uploaded_video_file', # For write operations
            'edit_tasks',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'uploaded_video_name', 'edit_tasks', 'created_at', 'updated_at', 'original_video_source']
