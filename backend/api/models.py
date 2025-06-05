# backend/api/models.py
from django.db import models
from django.contrib.auth.models import User # Using Django's built-in User model
from django.utils import timezone # For publication_date default and other timestamps
from django.db.models.signals import post_save # For UserProfile creation
from django.dispatch import receiver # For UserProfile creation
import uuid # For SearchTask and EditTask IDs

# Helper function for default expiry for SignupCode
def default_signup_code_expiry():
    return timezone.now() + timezone.timedelta(days=7)

# --- Core Video and Source Models ---
class Video(models.Model):
    """
    Represents a unique video entity identified by Papri, potentially existing on multiple platforms.
    """
    id = models.BigAutoField(primary_key=True)
    title = models.TextField(help_text="Title of the video.") # From your models.py
    description = models.TextField(null=True, blank=True, help_text="Description of the video.") # From your models.py
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds.") # From your models.py
    publication_date = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Original publication date.") # From your models.py
    primary_thumbnail_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL of the primary thumbnail.") # From your models.py
    
    tags = models.JSONField(null=True, blank=True, help_text="List of tags or keywords associated with the video, from canonical source.") # Added for completeness
    category = models.CharField(max_length=100, null=True, blank=True, db_index=True, help_text="Primary category of the video.") # Added for completeness


    deduplication_hash = models.CharField(
        max_length=128, # Allowing for longer hash algorithms like SHA256 hex
        null=True, 
        blank=True, 
        db_index=True, 
        unique=True, 
        help_text="Content-based hash (e.g., SHA256 of normalized title+duration or visual hash) for deduplication."
    ) # Length changed from 64 to 128
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or f"Video {self.id}"

    class Meta:
        indexes = [
            models.Index(fields=['title'], name='api_video_title_idx'), 
            models.Index(fields=['publication_date'], name='api_video_pub_date_idx'), # Added index
            models.Index(fields=['created_at'], name='api_video_created_at_idx'),
        ]
        verbose_name = "Canonical Video"
        verbose_name_plural = "Canonical Videos"


class VideoSource(models.Model):
    """
    Represents a specific instance of a Video on a particular platform (e.g., a YouTube URL for a Video).
    """
    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(Video, related_name='sources', on_delete=models.CASCADE, db_index=True, help_text="The canonical Papri Video entry.")
    platform_name = models.CharField(max_length=100, db_index=True, help_text="Name of the platform, e.g., YouTube, Vimeo.")
    platform_video_id = models.CharField(max_length=255, db_index=True, help_text="Video's unique ID on the source platform.")
    original_url = models.URLField(max_length=2048, unique=True, help_text="Direct URL to the video on the source platform.")
    embed_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL for embedding the video.")
    source_metadata_json = models.JSONField(null=True, blank=True, help_text="Raw metadata from the source platform.") # From your models.py
    last_scraped_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful scrape/API fetch.")
    is_primary_source = models.BooleanField(default=False, help_text="Is this considered the canonical source for this video's metadata on Papri?") # Clarified help_text

    # Uploader & stats from source (can be denormalized here for quick access)
    uploader_name = models.CharField(max_length=255, null=True, blank=True) # Added
    uploader_url = models.URLField(max_length=2048, null=True, blank=True) # Added
    view_count = models.PositiveIntegerField(null=True, blank=True) # Added
    like_count = models.PositiveIntegerField(null=True, blank=True) # Added
    comment_count = models.PositiveIntegerField(null=True, blank=True) # Added


    # --- Processing Status Fields (Consolidated) ---
    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending All Processing'),
        ('metadata_fetched', 'Metadata Fetched'),
        ('transcript_processing', 'Transcript Processing'),
        ('transcript_processed', 'Transcript Processed/Unavailable'), # Combined status
        ('visual_downloading', 'Visual: Downloading Video'),
        ('visual_processing', 'Visual: Processing Frames'),
        ('visual_processed', 'Visual: Processing Complete/Skipped'), # Combined status
        ('analysis_complete', 'All Analysis Complete'),
        ('processing_failed', 'Processing Failed (General)'),
        ('transcript_failed', 'Transcript Processing Failed'),
        ('visual_failed', 'Visual Processing Failed'),
        ('download_failed', 'Visual: Download Failed'),
    ]
    processing_status = models.CharField( # Overall status for the source
        max_length=30, choices=PROCESSING_STATUS_CHOICES, default='pending', db_index=True,
        help_text="Overall content processing status for this source."
    )
    processing_error_message = models.TextField(null=True, blank=True, help_text="Consolidated error messages from processing stages.")
    last_analyzed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful full analysis (transcript & visual).")

    # Visual-specific status (from your models.py, kept for detailed visual tracking)
    VISUAL_DETAIL_STATUS_CHOICES = [ # Renamed from VISUAL_PROCESSING_STATUS_CHOICES to avoid clash
        ('pending', 'Pending Index'),
        ('downloading', 'Downloading'), # Kept from your model
        ('download_failed', 'Download Failed'), # Kept from your model
        ('indexing', 'Indexing Frames'), # Kept from your model
        ('analysis_failed', 'Frame Analysis Failed'), # Kept from your model
        ('error_unexpected', 'Unexpected Error'), # Kept from your model
        ('completed', 'Visual Indexing Completed'), # Kept from your model
        ('not_applicable', 'Not Applicable'), # Kept from your model
        ('skipped_no_file', 'Skipped (No File)'), # Added
    ]
    meta_visual_processing_status = models.CharField(
        max_length=20, choices=VISUAL_DETAIL_STATUS_CHOICES, default='pending', 
        null=True, blank=True, db_index=True, help_text="Detailed status of visual feature extraction."
    ) # Name from your models.py
    meta_visual_processing_error = models.TextField(null=True, blank=True, help_text="Specific error from visual processing stage.") # From your models.py
    last_visual_indexed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last successful visual indexing.") # From your models.py

    created_at = models.DateTimeField(auto_now_add=True) # Defined once
    updated_at = models.DateTimeField(auto_now=True) # Defined once

    class Meta:
        unique_together = ('platform_name', 'platform_video_id') 
        indexes = [
            models.Index(fields=['last_scraped_at'], name='api_videosource_scraped_idx'),
            models.Index(fields=['processing_status'], name='api_vs_proc_status_idx'), # Added
            models.Index(fields=['meta_visual_processing_status'], name='api_vs_meta_vis_stat_idx'), # Added
        ]
        verbose_name = "Video Source Instance"
        verbose_name_plural = "Video Source Instances"

    def __str__(self):
        title_preview = self.video.title[:50] if self.video else "N/A"
        return f"{self.platform_name} ({self.platform_video_id or 'N/A'}) - {title_preview}"


# --- Transcript and NLP Feature Models ---
class Transcript(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.ForeignKey(VideoSource, related_name='transcripts', on_delete=models.CASCADE, db_index=True)
    language_code = models.CharField(max_length=15, default='en', db_index=True, help_text="Language code (e.g., en, es-MX).") # From your models.py
    transcript_text_content = models.TextField(help_text="Full plain text of the transcript.") # From your models.py
    transcript_timed_json = models.JSONField(null=True, blank=True, help_text="Structured timed transcript (e.g., VTT segments as JSON).") # From your models.py
    quality_score = models.FloatField(null=True, blank=True, help_text="Estimated quality (0.0-1.0).") # From your models.py
    
    # processing_status_choices from your models.py
    PROCESSING_STATUS_CHOICES = [ 
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('not_available', 'Not Available'),
    ]
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='pending', db_index=True) # From your models.py
    
    # Added for vector DB linking if needed
    vector_db_transcript_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="ID in the vector database for this transcript's embeddings")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('video_source', 'language_code')
        verbose_name = "Video Transcript"
        verbose_name_plural = "Video Transcripts"
        indexes = [
             models.Index(fields=['processing_status'], name='api_transcript_proc_stat_idx'), # Added
            # Consider FULLTEXT for transcript_text_content via migration
        ]

    def __str__(self):
        return f"Transcript for VSID {self.video_source_id} ({self.language_code})"


class ExtractedKeyword(models.Model):
    id = models.BigAutoField(primary_key=True)
    transcript = models.ForeignKey(Transcript, related_name='keywords', on_delete=models.CASCADE, db_index=True) # From your models.py
    keyword_text = models.CharField(max_length=255, db_index=True) # From your models.py
    relevance_score = models.FloatField(null=True, blank=True, help_text="Score from extraction algorithm.") # From your models.py
    created_at = models.DateTimeField(auto_now_add=True) # Added for consistency

    class Meta:
        unique_together = ('transcript', 'keyword_text')
        verbose_name = "Extracted Keyword"
        verbose_name_plural = "Extracted Keywords"
        indexes = [
            models.Index(fields=['keyword_text'], name='api_keyword_text_idx'), # Added
        ]


    def __str__(self):
        return self.keyword_text


class VideoTopic(models.Model):
    id = models.BigAutoField(primary_key=True)
    transcript = models.ForeignKey(Transcript, related_name='topics', on_delete=models.CASCADE, db_index=True) # From your models.py
    topic_label = models.CharField(max_length=255, db_index=True, help_text="Human-readable topic label.") # From your models.py
    topic_relevance_score = models.FloatField(null=True, blank=True, help_text="Score from topic modeling.") # From your models.py
    created_at = models.DateTimeField(auto_now_add=True) # Added for consistency

    class Meta:
        unique_together = ('transcript', 'topic_label')
        verbose_name = "Video Topic"
        verbose_name_plural = "Video Topics"

    def __str__(self):
        return self.topic_label


# --- Visual Feature Models ---
class VideoFrameFeature(models.Model):
    id = models.BigAutoField(primary_key=True)
    video_source = models.ForeignKey(VideoSource, related_name='frame_features', on_delete=models.CASCADE, db_index=True)
    timestamp_in_video_ms = models.PositiveIntegerField(help_text="Timestamp of frame in milliseconds from video start.") # From your models.py
    frame_image_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL to stored representative keyframe image.") # From your models.py
    feature_type = models.CharField(max_length=50, db_index=True, help_text="Type of feature (e.g., EfficientNetV2S_embedding, pHash).") # From your models.py
    hash_value = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Perceptual hash value.") # From your models.py
    feature_data_json = models.JSONField(null=True, blank=True, help_text="Additional metadata or small features (e.g., ORB keypoints).") # From your models.py
    vector_db_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, unique=True, help_text="ID of corresponding vector in Vector DB.") # From your models.py
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('video_source', 'timestamp_in_video_ms', 'feature_type')
        indexes = [
            models.Index(fields=['video_source', 'timestamp_in_video_ms'], name='api_frame_time_idx'),
            models.Index(fields=['feature_type', 'hash_value'], name='api_frame_hash_idx'), # Added for hash lookups
        ]
        verbose_name = "Video Frame Feature"
        verbose_name_plural = "Video Frame Features"

    def __str__(self):
        return f"{self.feature_type} for VSID {self.video_source_id} at {self.timestamp_in_video_ms}ms"


# --- User Profile, Activity and Search Task Models ---
class UserProfile(models.Model): # NEWLY INTEGRATED
    """
    Extends the default Django User model for Papri-specific attributes.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', primary_key=True)
    subscription_plan_choices = [
        ('free_trial', 'Free Trial'),
        ('papri_pro_monthly', 'Papri Pro Monthly'),
        ('papri_pro_yearly', 'Papri Pro Yearly'),
        ('cancelled', 'Cancelled'),
    ]
    subscription_plan = models.CharField(max_length=50, choices=subscription_plan_choices, default='free_trial', db_index=True)
    subscription_id_gateway = models.CharField(max_length=255, null=True, blank=True, help_text="Subscription ID from payment gateway (e.g., Paystack)")
    subscription_expiry_date = models.DateTimeField(null=True, blank=True)
    remaining_trial_searches = models.PositiveIntegerField(default=3, help_text="For the initial demo searches on landing page.")
    # preferences_json = models.JSONField(null=True, blank=True, help_text="User preferences, e.g., preferred sources, result filters.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.username} (Plan: {self.get_subscription_plan_display()})"

@receiver(post_save, sender=User) # Signal to create/update UserProfile when User is created/saved
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    try:
        instance.profile.save() # Ensure profile is saved if User object is saved
    except UserProfile.DoesNotExist: # Handle case where profile might have been deleted manually
        UserProfile.objects.create(user=instance)


class SearchTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, help_text="Unique ID for the search task.") # From your models.py
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, help_text="User who initiated (if logged in).") # From your models.py
    session_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Session ID for anonymous users.") # From your models.py
    query_text = models.TextField(null=True, blank=True) # From your models.py
    query_image_ref = models.CharField(max_length=1024, null=True, blank=True, help_text="Reference to uploaded query image.") # From your models.py
    query_image_fingerprint = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Hash/fingerprint of query image.") # From your models.py
    query_video_url = models.URLField(max_length=2048, null=True, blank=True, help_text="Direct video URL for 'search within this video'.") # Added based on initial prompt
    
    applied_filters_json = models.JSONField(null=True, blank=True, help_text="JSON of filters applied.") # From your models.py
    result_video_ids_json = models.JSONField(null=True, blank=True, help_text="JSON array of Papri Video IDs (ordered by rank).") # From your models.py
    detailed_results_info_json = models.JSONField(null=True, blank=True, help_text="JSON array of detailed result info (scores, match types).") # From your models.py
    
    STATUS_CHOICES = [ # Standardized choices (from your models.py, `status_choices`)
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('partial_results', 'Partial Results'),
        ('cancelled', 'Cancelled'), # Added for completeness
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True) # Name from your models.py
    error_message = models.TextField(null=True, blank=True) # From your models.py
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Celery task ID for this operation.") # Added
    # progress = models.PositiveIntegerField(default=0, help_text="Approximate progress percentage (0-100).") # Added
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: # Added Meta for ordering
        ordering = ['-created_at']
        verbose_name = "User Search Task"
        verbose_name_plural = "User Search Tasks"

    def __str__(self):
        return f"SearchTask {self.id} ({self.status})"


class SignupCode(models.Model): # Model from your models.py
    id = models.BigAutoField(primary_key=True) # Changed from your models.py for consistency (was BigAutoField)
    email = models.EmailField(unique=True, help_text="Email address the code was sent to.")
    code = models.CharField(max_length=20, unique=True, db_index=True) # Increased length from 10
    plan_name = models.CharField(max_length=100, default="Papri Pro Plan") # Changed default
    is_used = models.BooleanField(default=False, db_index=True)
    user_activated = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="activated_with_signup_code") # Changed related_name
    payment_reference = models.CharField(max_length=255, null=True, blank=True, help_text="Reference from payment gateway.")
    expires_at = models.DateTimeField(default=default_signup_code_expiry, help_text="Expiry for the code.") # Used helper
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta: # Added Meta
        verbose_name = "User Signup Code"
        verbose_name_plural = "User Signup Codes"

    def __str__(self):
        return f"Code {self.code} for {self.email} (Used: {self.is_used})"

    @property
    def is_expired(self):
        if not self.expires_at: return False # If no expiry, not expired
        return timezone.now() > self.expires_at


# --- AI Video Editor Models (NEWLY INTEGRATED) ---
class VideoEditProject(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_edit_projects')
    original_video_source = models.ForeignKey(VideoSource, null=True, blank=True, on_delete=models.SET_NULL, help_text="Source video if from Papri search results")
    # Store name/path for user-uploaded video relative to a specific MEDIA_ROOT subdir for edits
    uploaded_video_path = models.CharField(max_length=1024, null=True, blank=True, help_text="Path (relative to MEDIA_ROOT/user_edits_temp/) of user-uploaded video")
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
        ('pending', 'Pending'),
        ('queued', 'Queued in Celery'),
        ('processing', 'Processing Video'),
        ('completed', 'Completed Successfully'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(VideoEditProject, related_name='edit_tasks', on_delete=models.CASCADE)
    prompt_text = models.TextField(help_text="User's text prompt for editing instructions.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Celery task ID for this edit operation.")
    # Path to the edited video file (relative to MEDIA_ROOT/edited_videos/ or full URL if S3)
    result_media_path = models.CharField(max_length=1024, null=True, blank=True, help_text="Path/URL to the final edited video file.")
    # result_preview_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL to a preview of the edited video (e.g., GIF).")
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "AI Video Edit Task"
        verbose_name_plural = "AI Video Edit Tasks"

    def __str__(self):
        return f"Edit Task {self.id} for Project '{self.project.project_name}' ({self.status})"

    def get_result_url(self) -> Optional[str]:
        """Returns an absolute URL to the edited media if available and stored locally."""
        if not self.result_media_path:
            return None
        if self.result_media_path.startswith(('http://', 'https://')): # Already a full URL (e.g. S3)
            return self.result_media_path
        
        # Assumes result_media_path is relative to MEDIA_URL if stored locally
        if hasattr(settings, 'MEDIA_URL') and settings.MEDIA_URL:
            return f"{str(settings.MEDIA_URL).rstrip('/')}/{self.result_media_path.lstrip('/')}"
        logger.warning(f"MEDIA_URL not configured or empty; cannot construct full URL for EditTask {self.id} result: {self.result_media_path}")
        return None # Cannot construct URL if MEDIA_URL is not set
