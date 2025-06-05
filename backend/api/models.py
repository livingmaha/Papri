# backend/api/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings # For EditTask.get_result_url()
import uuid
import logging # For EditTask.get_result_url()

logger = logging.getLogger(__name__) # For EditTask.get_result_url()

def default_signup_code_expiry():
    return timezone.now() + timezone.timedelta(days=settings.SIGNUP_CODE_EXPIRY_DAYS if hasattr(settings, 'SIGNUP_CODE_EXPIRY_DAYS') else 7)

class Video(models.Model):
    id = models.BigAutoField(primary_key=True)
    title = models.TextField(help_text="Title of the video.")
    description = models.TextField(null=True, blank=True, help_text="Description of the video.")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds.")
    publication_date = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Original publication date.")
    primary_thumbnail_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL of the primary thumbnail.")
    tags = models.JSONField(null=True, blank=True, help_text="List of tags or keywords associated with the video.")
    category = models.CharField(max_length=100, null=True, blank=True, db_index=True, help_text="Primary category of the video.")
    deduplication_hash = models.CharField(
        max_length=128, null=True, blank=True, db_index=True, unique=True,
        help_text="Content-based hash for deduplication."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or f"Video {self.id}"

    class Meta:
        indexes = [
            models.Index(fields=['title'], name='api_video_title_idx'),
            models.Index(fields=['publication_date'], name='api_video_pub_date_idx'),
            models.Index(fields=['created_at'], name='api_video_created_at_idx'),
        ]
        verbose_name = "Canonical Video"
        verbose_name_plural = "Canonical Videos"

class VideoSource(models.Model):
    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(Video, related_name='sources', on_delete=models.CASCADE, db_index=True, help_text="The canonical Papri Video entry.")
    platform_name = models.CharField(max_length=100, db_index=True, help_text="Name of the platform.")
    platform_video_id = models.CharField(max_length=255, db_index=True, help_text="Video's unique ID on the source platform.")
    original_url = models.URLField(max_length=2048, unique=True, help_text="Direct URL to the video on the source platform.")
    embed_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL for embedding the video.")
    thumbnail_url = models.URLField(max_length=2048, null=True, blank=True) # Specific thumbnail for this source
    source_metadata_json = models.JSONField(null=True, blank=True, help_text="Raw metadata from the source platform.")
    last_scraped_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful scrape/API fetch.")
    is_primary_source = models.BooleanField(default=False, help_text="Is this considered the canonical source for this video's metadata on Papri?")
    uploader_name = models.CharField(max_length=255, null=True, blank=True)
    uploader_url = models.URLField(max_length=2048, null=True, blank=True)
    view_count = models.PositiveIntegerField(null=True, blank=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending All Processing'),
        ('metadata_fetched', 'Metadata Fetched'),
        ('transcript_processing', 'Transcript Processing'),
        ('transcript_processed', 'Transcript Processed'),
        ('transcript_unavailable', 'Transcript Unavailable'),
        ('transcript_failed', 'Transcript Processing Failed'),
        ('visual_downloading', 'Visual: Downloading Video'),
        ('download_failed', 'Visual: Download Failed'),
        ('visual_processing', 'Visual: Processing Frames'),
        ('visual_processed', 'Visual: Processing Complete'),
        ('visual_skipped', 'Visual: Processing Skipped/Not Applicable'),
        ('visual_failed', 'Visual Processing Failed'),
        ('analysis_complete', 'All Analysis Complete'),
        ('processing_failed_general', 'Processing Failed (General)'),
    ]
    processing_status = models.CharField(
        max_length=30, choices=PROCESSING_STATUS_CHOICES, default='pending', db_index=True,
        help_text="Overall content processing status for this source."
    )
    processing_error_message = models.TextField(null=True, blank=True, help_text="Consolidated error messages from processing stages.")
    last_analyzed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful full analysis.")
    
    # Kept meta_visual_processing_status for granular visual state if needed by VisualAnalyzer itself
    VISUAL_DETAIL_STATUS_CHOICES = [
        ('pending', 'Pending Index'), ('downloading', 'Downloading'), ('download_failed', 'Download Failed'),
        ('indexing', 'Indexing Frames'), ('analysis_failed', 'Frame Analysis Failed'),
        ('error_unexpected', 'Unexpected Error'), ('completed', 'Visual Indexing Completed'),
        ('not_applicable', 'Not Applicable'), ('skipped_no_file', 'Skipped (No File)'),
    ]
    meta_visual_processing_status = models.CharField(
        max_length=20, choices=VISUAL_DETAIL_STATUS_CHOICES, default='pending',
        null=True, blank=True, db_index=True, help_text="Detailed status of visual feature extraction."
    )
    meta_visual_processing_error = models.TextField(null=True, blank=True, help_text="Specific error from visual processing stage.")
    last_visual_indexed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful visual indexing.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('platform_name', 'platform_video_id')
        indexes = [
            models.Index(fields=['last_scraped_at'], name='api_videosource_scraped_idx'),
            models.Index(fields=['processing_status'], name='api_vs_proc_status_idx'),
            models.Index(fields=['meta_visual_processing_status'], name='api_vs_meta_vis_stat_idx'),
        ]
        verbose_name = "Video Source Instance"
        verbose_name_plural = "Video Source Instances"

    def __str__(self):
        title_preview = self.video.title[:50] if self.video else "N/A"
        return f"{self.platform_name} ({self.platform_video_id or 'N/A'}) - {title_preview}"

class Transcript(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.OneToOneField(VideoSource, related_name='transcript_data', on_delete=models.CASCADE, db_index=True) # Changed from ForeignKey to OneToOne
    language_code = models.CharField(max_length=15, default='en', db_index=True, help_text="Language code (e.g., en, es-MX).")
    transcript_text_content = models.TextField(help_text="Full plain text of the transcript.")
    transcript_timed_json = models.JSONField(null=True, blank=True, help_text="Structured timed transcript (e.g., VTT segments as JSON).")
    quality_score = models.FloatField(null=True, blank=True, help_text="Estimated quality (0.0-1.0).")
    source_type = models.CharField(max_length=50, null=True, blank=True, help_text="e.g., 'auto_generated', 'manual_upload', 'third_party_api'")

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'), ('processed', 'Processed'), ('failed', 'Failed'),
        ('not_available', 'Not Available'),
    ]
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='pending', db_index=True)
    vector_db_transcript_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="ID in the vector database.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # unique_together = ('video_source', 'language_code') # Removed as it's OneToOne with VideoSource now
        verbose_name = "Video Transcript"
        verbose_name_plural = "Video Transcripts"
        indexes = [models.Index(fields=['processing_status'], name='api_transcript_proc_stat_idx')]

    def __str__(self):
        return f"Transcript for VSID {self.video_source_id} ({self.language_code})"

class ExtractedKeyword(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.ForeignKey(VideoSource, related_name='extracted_keywords', on_delete=models.CASCADE, db_index=True) # Linked to VideoSource
    keyword_text = models.CharField(max_length=255, db_index=True)
    relevance_score = models.FloatField(null=True, blank=True, help_text="Score from extraction algorithm.")
    source_field = models.CharField(max_length=50, default='transcript', help_text="Field keyword was extracted from (e.g., title, description, transcript).")
    extraction_method = models.CharField(max_length=100, null=True, blank=True, help_text="Method used for extraction (e.g., spaCy_noun_chunks, RAKE).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('video_source', 'keyword_text', 'source_field') # Ensure unique per source and field
        verbose_name = "Extracted Keyword"
        verbose_name_plural = "Extracted Keywords"
        indexes = [models.Index(fields=['keyword_text'], name='api_keyword_text_idx')]

    def __str__(self):
        return self.keyword_text

class VideoTopic(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.ForeignKey(VideoSource, related_name='video_topics', on_delete=models.CASCADE, db_index=True) # Linked to VideoSource
    topic_name = models.CharField(max_length=255, db_index=True, help_text="Name/label of the identified topic.")
    confidence_score = models.FloatField(null=True, blank=True, help_text="Confidence score from topic modeling.")
    modeling_method = models.CharField(max_length=100, null=True, blank=True, help_text="Method used (e.g., LDA_gensim, NMF_sklearn).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('video_source', 'topic_name', 'modeling_method')
        verbose_name = "Video Topic"
        verbose_name_plural = "Video Topics"

    def __str__(self):
        return self.topic_name

class VideoFrameFeature(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.ForeignKey(VideoSource, related_name='frame_features', on_delete=models.CASCADE, db_index=True)
    timestamp_ms = models.PositiveIntegerField(help_text="Timestamp of frame in milliseconds from video start.") # Renamed from timestamp_in_video_ms
    feature_type = models.CharField(max_length=50, db_index=True, help_text="Type of feature (e.g., cnn_embedding, perceptual_hash).")
    feature_data_json = models.JSONField(null=True, blank=True, help_text="Perceptual hashes or other small metadata.")
    vector_db_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, unique=True, help_text="ID of corresponding vector in Vector DB (for CNN embeddings).")
    # Storing actual hash value for direct DB indexing/search if feature_type is 'perceptual_hash'
    hash_value = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Primary hash value if feature_type is hash.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('video_source', 'timestamp_ms', 'feature_type')
        indexes = [
            models.Index(fields=['video_source', 'timestamp_ms'], name='api_frame_time_idx'),
            models.Index(fields=['feature_type', 'hash_value'], name='api_frame_hash_idx'),
        ]
        verbose_name = "Video Frame Feature"
        verbose_name_plural = "Video Frame Features"

    def __str__(self):
        return f"{self.feature_type} for VSID {self.video_source_id} at {self.timestamp_ms}ms"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', primary_key=True)
    subscription_plan_choices = [
        ('free_trial', 'Free Trial'),
        ('papri_pro_monthly', 'Papri Pro Monthly'),
        ('papri_pro_yearly', 'Papri Pro Yearly'),
        ('cancelled', 'Cancelled'),
    ]
    subscription_plan = models.CharField(max_length=50, choices=subscription_plan_choices, default='free_trial', db_index=True)
    subscription_id_gateway = models.CharField(max_length=255, null=True, blank=True, help_text="Subscription ID from payment gateway")
    subscription_expiry_date = models.DateTimeField(null=True, blank=True)
    remaining_trial_searches = models.PositiveIntegerField(default=settings.MAX_DEMO_SEARCHES if hasattr(settings, 'MAX_DEMO_SEARCHES') else 3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.username} (Plan: {self.get_subscription_plan_display()})"

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    try:
        instance.profile.save()
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=instance)

class SearchTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    session_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    query_text = models.TextField(null=True, blank=True)
    query_image_ref = models.CharField(max_length=1024, null=True, blank=True, help_text="Path or URL to query image")
    query_image_fingerprint = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    query_video_url = models.URLField(max_length=2048, null=True, blank=True)
    applied_filters_json = models.JSONField(null=True, blank=True)
    result_video_ids_json = models.JSONField(null=True, blank=True, help_text="Ordered list of canonical Video IDs")
    detailed_results_info_json = models.JSONField(null=True, blank=True, help_text="Rich structured results including scores, match types, best source info.")
    
    STATUS_CHOICES = [
        ('pending', 'Pending Submission'),
        ('queued', 'Queued for Processing'), # Task accepted by Celery
        ('processing', 'Processing Query'),
        ('processing_sources', 'Processing Sources & Content'),
        ('aggregating', 'Aggregating Results'),
        ('completed', 'Completed Successfully'),
        ('partial_results', 'Completed with Partial Results'),
        ('failed', 'Failed'),
        ('failed_query_understanding', 'Failed: Query Understanding'),
        ('failed_source_fetch', 'Failed: Source Fetching'),
        ('failed_content_analysis', 'Failed: Content Analysis'),
        ('failed_aggregation', 'Failed: Result Aggregation'),
        ('failed_timeout', 'Failed: Task Timeout'),
        ('cancelled', 'Cancelled by User'),
    ]
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True) # Increased max_length
    error_message = models.TextField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "User Search Task"
        verbose_name_plural = "User Search Tasks"

    def __str__(self):
        return f"SearchTask {self.id} ({self.get_status_display()})"

class SignupCode(models.Model):
    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(unique=True, help_text="Email address the code was sent to.")
    code = models.CharField(max_length=20, unique=True, db_index=True)
    plan_name = models.CharField(max_length=100, default="Papri Pro Monthly") # Default changed
    is_used = models.BooleanField(default=False, db_index=True)
    user_activated = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="activated_with_signup_code")
    payment_reference = models.CharField(max_length=255, null=True, blank=True, help_text="Reference from payment gateway.")
    expires_at = models.DateTimeField(default=default_signup_code_expiry)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Signup Code"
        verbose_name_plural = "User Signup Codes"

    def __str__(self):
        return f"Code {self.code} for {self.email} (Used: {self.is_used})"

    @property
    def is_expired(self):
        if not self.expires_at: return False
        return timezone.now() > self.expires_at

class VideoEditProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_edit_projects')
    original_video_source = models.ForeignKey(VideoSource, null=True, blank=True, on_delete=models.SET_NULL, help_text="Source video if from Papri search results")
    uploaded_video_path = models.CharField(max_length=1024, null=True, blank=True, help_text="Path of user-uploaded video relative to MEDIA_ROOT/user_edits_temp/")
    project_name = models.CharField(max_length=255, default="Untitled Edit Project")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "AI Video Edit Project"
        verbose_name_plural = "AI Video Edit Projects"

    def __str__(self):
        return f"Edit Project: '{self.project_name}' by {self.user.username}"

class EditTask(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Submission'),
        ('queued', 'Queued for Processing'),
        ('processing', 'Processing Video'), # General processing state
        ('downloading_video', 'Downloading Video'),
        ('interpreting_prompt', 'Interpreting Prompt'),
        ('editing_in_progress', 'Editing in Progress'),
        ('uploading_output', 'Uploading Output'), # If storing to cloud
        ('completed', 'Completed Successfully'),
        ('failed', 'Failed (Generic)'),
        ('failed_download', 'Failed: Video Download'),
        ('failed_prompt_interpretation', 'Failed: Prompt Interpretation'),
        ('failed_editing', 'Failed: Video Editing Process'),
        ('failed_output_storage', 'Failed: Output Storage'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(VideoEditProject, related_name='edit_tasks', on_delete=models.CASCADE)
    prompt_text = models.TextField(help_text="User's text prompt for editing instructions.")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending', db_index=True) # Increased max_length
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    result_media_path = models.CharField(max_length=1024, null=True, blank=True, help_text="Path/URL to the final edited video file.")
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "AI Video Edit Task"
        verbose_name_plural = "AI Video Edit Tasks"

    def __str__(self):
        return f"Edit Task {self.id} for Project '{self.project.project_name}' ({self.get_status_display()})"

    def get_result_url(self) -> Optional[str]:
        if not self.result_media_path:
            return None
        if self.result_media_path.startswith(('http://', 'https://')):
            return self.result_media_path
        if hasattr(settings, 'MEDIA_URL') and settings.MEDIA_URL:
            # Ensure no double slashes if MEDIA_URL ends with / and path starts with /
            media_url_base = str(settings.MEDIA_URL).rstrip('/')
            relative_path = self.result_media_path.lstrip('/')
            return f"{media_url_base}/{relative_path}"
        logger.warning(f"MEDIA_URL not configured or empty; cannot construct full URL for EditTask {self.id} result: {self.result_media_path}")
        return None
