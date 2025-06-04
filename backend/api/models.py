# backend/api/models.py
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import JSONField # Standard JSONField

# Helper function for default expiry for SignupCode
def default_signup_code_expiry():
    return timezone.now() + timezone.timedelta(days=7)

class Video(models.Model):
    """
    Canonical representation of a video, independent of its source.
    Used for deduplication and central storage of core video metadata.
    """
    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=500, db_index=True)
    description = models.TextField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds")
    publication_date = models.DateTimeField(null=True, blank=True, db_index=True)
    tags = models.JSONField(null=True, blank=True, help_text="List of tags or keywords associated with the video")
    category = models.CharField(max_length=100, null=True, blank=True, db_index=True)

    # For deduplication and integrity
    deduplication_hash = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True, help_text="Hash based on content or unique identifiers for deduplication")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Full-text search vector (example for PostgreSQL, adjust for MySQL)
    # search_vector = SearchVectorField(null=True) # Requires django.contrib.postgres

    class Meta:
        verbose_name = "Video (Canonical)"
        verbose_name_plural = "Videos (Canonical)"
        # Add index for faster searching by title, if not using advanced FTS
        indexes = [
            models.Index(fields=['title']),
            # models.Index(fields=['search_vector'], name='video_search_vector_idx'), # For PostgreSQL FTS
        ]

    def __str__(self):
        return f"{self.title} (ID: {self.id})"


class VideoSource(models.Model):
    """
    Represents a specific instance of a video from a particular platform (e.g., a YouTube video).
    Links to the canonical Video object.
    """
    PLATFORM_CHOICES = [
        ('youtube', 'YouTube'),
        ('vimeo', 'Vimeo'),
        ('dailymotion', 'Dailymotion'),
        ('peertube', 'PeerTube'),
        ('tiktok', 'TikTok'),
        ('rumble', 'Rumble'),
        ('bitchute', 'Bitchute'),
        ('other_scrape', 'Other (Scraped)'),
        ('user_upload', 'User Uploaded'),
    ]

    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending Processing'),
        ('metadata_fetched', 'Metadata Fetched'),
        ('transcript_processing', 'Transcript Processing'),
        ('transcript_processed', 'Transcript Processed'),
        ('visual_processing', 'Visual Processing'),
        ('visual_processed', 'Visual Processed'),
        ('analysis_complete', 'Analysis Complete'),
        ('processing_failed', 'Processing Failed'),
        ('manual_review', 'Manual Review Required'),
    ]

    id = models.BigAutoField(primary_key=True)
    video = models.ForeignKey(Video, related_name='sources', on_delete=models.CASCADE)
    platform_name = models.CharField(max_length=50, choices=PLATFORM_CHOICES, db_index=True)
    platform_video_id = models.CharField(max_length=255, db_index=True, help_text="Video ID specific to the platform")
    original_url = models.URLField(max_length=2048, unique=True, help_text="Direct URL to the video on the source platform")
    embed_url = models.URLField(max_length=2048, null=True, blank=True)
    thumbnail_url = models.URLField(max_length=2048, null=True, blank=True)
    uploader_name = models.CharField(max_length=255, null=True, blank=True)
    uploader_url = models.URLField(max_length=2048, null=True, blank=True)
    view_count = models.PositiveIntegerField(null=True, blank=True)
    like_count = models.PositiveIntegerField(null=True, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)

    # Processing and analysis status
    processing_status = models.CharField(max_length=30, choices=PROCESSING_STATUS_CHOICES, default='pending', db_index=True)
    processing_error_message = models.TextField(null=True, blank=True)
    last_scraped_at = models.DateTimeField(null=True, blank=True, help_text="When the metadata was last scraped/fetched")
    last_analyzed_at = models.DateTimeField(null=True, blank=True, help_text="When content analysis was last performed")

    # Specific flags for visual indexing from your initial models.py
    meta_visual_processing_status = models.CharField(max_length=30, choices=PROCESSING_STATUS_CHOICES, default='pending', help_text="Status of visual feature extraction")
    meta_visual_processing_error = models.TextField(null=True, blank=True)
    last_visual_indexed_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Video Source"
        verbose_name_plural = "Video Sources"
        unique_together = ('platform_name', 'platform_video_id') # A video ID on a specific platform should be unique
        indexes = [
            models.Index(fields=['platform_name', 'platform_video_id']),
            models.Index(fields=['original_url']),
        ]

    def __str__(self):
        return f"{self.video.title} on {self.get_platform_name_display()} (ID: {self.id})"


class Transcript(models.Model):
    """
    Stores transcript data for a video source.
    """
    video_source = models.OneToOneField(VideoSource, related_name='transcript_data', on_delete=models.CASCADE)
    language_code = models.CharField(max_length=10, default='en', help_text="e.g., en, es, fr")
    full_text_content = models.TextField(help_text="The complete transcript text")
    transcript_timed_json = JSONField(null=True, blank=True, help_text="JSON array of timed segments, e.g., [{'start_ms': 0, 'end_ms': 5000, 'text': 'Hello world'}]")
    source_type = models.CharField(max_length=20, default='auto_generated', choices=[('auto_generated', 'Auto-generated'), ('manual', 'Manual'), ('user_provided', 'User Provided')])

    # Vector DB reference if storing embeddings separately and linking
    vector_db_transcript_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="ID in the vector database for this transcript's embeddings")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transcript"
        verbose_name_plural = "Transcripts"

    def __str__(self):
        return f"Transcript for {self.video_source_id} ({self.language_code})"


class ExtractedKeyword(models.Model):
    """
    Keywords extracted from video transcripts or metadata.
    """
    video_source = models.ForeignKey(VideoSource, related_name='extracted_keywords', on_delete=models.CASCADE)
    keyword_text = models.CharField(max_length=255, db_index=True)
    relevance_score = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    source_field = models.CharField(max_length=50, default='transcript', help_text="e.g., transcript, title, description") # Where the keyword was found
    extraction_method = models.CharField(max_length=50, null=True, blank=True, help_text="e.g., RAKE, YAKE, TF-IDF")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Extracted Keyword"
        verbose_name_plural = "Extracted Keywords"
        unique_together = ('video_source', 'keyword_text', 'source_field')
        indexes = [
            models.Index(fields=['keyword_text']),
        ]

    def __str__(self):
        return f"'{self.keyword_text}' from VSID {self.video_source_id}"


class VideoTopic(models.Model):
    """
    Topics identified in a video, e.g., through LDA or other topic modeling.
    """
    video_source = models.ForeignKey(VideoSource, related_name='video_topics', on_delete=models.CASCADE)
    topic_name = models.CharField(max_length=255, db_index=True)
    confidence_score = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    modeling_method = models.CharField(max_length=50, null=True, blank=True, help_text="e.g., LDA, BERTopic")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Video Topic"
        verbose_name_plural = "Video Topics"
        unique_together = ('video_source', 'topic_name')

    def __str__(self):
        return f"Topic '{self.topic_name}' for VSID {self.video_source_id}"


class VideoFrameFeature(models.Model):
    """
    Stores visual features extracted from individual video frames.
    """
    FEATURE_TYPE_CHOICES = [
        ('cnn_embedding', 'CNN Embedding'),
        ('perceptual_hash', 'Perceptual Hash'),
        ('scene_boundary', 'Scene Boundary Marker'),
        ('object_detection', 'Object Detection Result'),
    ]
    video_source = models.ForeignKey(VideoSource, related_name='frame_features', on_delete=models.CASCADE)
    timestamp_ms = models.PositiveIntegerField(help_text="Timestamp of the frame in milliseconds")
    feature_type = models.CharField(max_length=30, choices=FEATURE_TYPE_CHOICES, db_index=True)
    feature_data_json = JSONField(help_text="JSON containing the feature data, e.g., {'hash_type': 'phash', 'value': 'abcdef123456'}, or {'model': 'EfficientNet', 'vector': [0.1, ...]}" )

    # Vector DB reference if storing embeddings separately and linking
    vector_db_frame_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="ID in the vector database for this frame's features")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Video Frame Feature"
        verbose_name_plural = "Video Frame Features"
        indexes = [
            models.Index(fields=['video_source', 'timestamp_ms']),
            models.Index(fields=['video_source', 'feature_type']),
        ]

    def __str__(self):
        return f"{self.get_feature_type_display()} at {self.timestamp_ms}ms for VSID {self.video_source_id}"


class UserProfile(models.Model):
    """
    Extends the default Django User model for Papri-specific attributes.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # Add fields like subscription_status, api_call_quota, preferences_json, etc.
    subscription_plan = models.CharField(max_length=50, default='free_trial', db_index=True)
    subscription_expiry_date = models.DateTimeField(null=True, blank=True)
    remaining_trial_searches = models.PositiveIntegerField(default=3) # For the initial demo
    # Add more fields as needed, e.g., saved_filters_json, preferred_sources_json

    def __str__(self):
        return f"Profile for {self.user.username}"

# Signal to create/update UserProfile when User is created/saved (optional, can be done in Allauth adapter too)
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
    instance.profile.save()


class SearchTask(models.Model):
    """
    Represents a search operation initiated by a user.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('partial_results', 'Partial Results Available'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='search_tasks')
    session_id = models.CharField(max_length=100, null=True, blank=True, db_index=True, help_text="For anonymous users or to group searches")

    query_text = models.TextField(null=True, blank=True)
    query_image_ref = models.CharField(max_length=1024, null=True, blank=True, help_text="Path/reference to the uploaded query image (temporary storage)")
    query_image_fingerprint = models.CharField(max_length=255, null=True, blank=True, help_text="Hash of the query image for quick checks")
    query_video_url = models.URLField(max_length=2048, null=True, blank=True, help_text="Direct video URL for analysis (e.g., 'search within this video')")

    applied_filters_json = JSONField(null=True, blank=True, help_text="JSON object of filters applied, e.g., {'platforms': ['youtube'], 'duration_min': 60}")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Celery task ID for this search operation")
    error_message = models.TextField(null=True, blank=True)

    # Store ranked video IDs (canonical Video IDs) and detailed info
    result_video_ids_json = JSONField(null=True, blank=True, help_text="Ordered list of canonical Video IDs as results")
    detailed_results_info_json = JSONField(null=True, blank=True, help_text="JSON array of detailed result info including scores, match types, snippets, timestamps")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Search Task"
        verbose_name_plural = "Search Tasks"
        ordering = ['-created_at']

    def __str__(self):
        return f"Search Task {self.id} ({self.status})"


class SignupCode(models.Model):
    """
    Stores signup codes generated after successful payment, used for account activation/upgrade.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, help_text="Email of the user who purchased this code") # Assuming one active code per email
    code = models.CharField(max_length=20, unique=True, db_index=True)
    plan_name = models.CharField(max_length=100, help_text="e.g., Papri Pro Monthly")
    payment_reference = models.CharField(max_length=255, null=True, blank=True, help_text="Reference from payment gateway")
    is_used = models.BooleanField(default=False, db_index=True)
    used_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='used_signup_codes')
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(default=default_signup_code_expiry)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signup Code"
        verbose_name_plural = "Signup Codes"

    def __str__(self):
        return f"Signup Code {self.code} for {self.email} (Used: {self.is_used})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at


# --- AI Video Editor Models ---
class VideoEditProject(models.Model):
    """
    Represents a project for AI-powered video editing.
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_edit_projects')
    original_video_source = models.ForeignKey(VideoSource, null=True, blank=True, on_delete=models.SET_NULL, help_text="Source video if from Papri search results")
    uploaded_video_name = models.CharField(max_length=512, null=True, blank=True, help_text="Name of the user-uploaded video file for editing (stored in MEDIA_ROOT/user_edits_temp/)")
    project_name = models.CharField(max_length=255, default="Untitled Edit Project")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Edit Project: {self.project_name} by {self.user.username}"


class EditTask(models.Model):
    """
    Represents a specific editing task within a VideoEditProject.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(VideoEditProject, related_name='edit_tasks', on_delete=models.CASCADE)
    prompt_text = models.TextField(help_text="User's text prompt for editing instructions")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, help_text="Celery task ID for this edit operation")
    
    # Stores the path relative to MEDIA_ROOT or a full URL if stored externally (e.g. S3)
    result_media_path = models.CharField(max_length=1024, null=True, blank=True, help_text="Path to the edited video file (relative to MEDIA_ROOT or full URL)")
    result_preview_url = models.URLField(max_length=2048, null=True, blank=True, help_text="URL to a preview of the edited video (if applicable)")
    error_message = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Edit Task"
        verbose_name_plural = "Edit Tasks"
        ordering = ['-created_at']

    def __str__(self):
        return f"Edit Task {self.id} for Project {self.project.id} ({self.status})"

    def get_result_url(self):
        """
        Returns an absolute URL to the edited media if available.
        Assumes result_media_path is relative to MEDIA_URL if not a full URL itself.
        """
        if not self.result_media_path:
            return None
        if self.result_media_path.startswith(('http://', 'https://')):
            return self.result_media_path
        
        from django.conf import settings
        if settings.MEDIA_URL:
            return f"{settings.MEDIA_URL.rstrip('/')}/{self.result_media_path.lstrip('/')}"
        return None # Cannot construct URL
