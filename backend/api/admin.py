# backend/api/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone # For admin actions
import json # For pretty printing JSON fields

# Import models from the current app (api.models)
# Based on the provided models.py (livingmugash/papri.site/Papri.site-e0aa8dd287cc0fd30b032cf05762f341a16d8b08/backend/api/models.py)
from .models import (
    Video, VideoSource, Transcript, ExtractedKeyword, VideoTopic,
    VideoFrameFeature, SearchTask, SignupCode
)
# UserProfile, VideoEditProject, EditTask are not in the provided models.py,
# so their admin registrations are commented out but can be adapted if models exist.

# --- Inlines for Related Models ---

class VideoSourceInline(admin.TabularInline):
    model = VideoSource
    fk_name = 'video'
    extra = 0
    show_change_link = True
    fields = ('platform_name', 'platform_video_id', 'original_url', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at')
    readonly_fields = ('last_scraped_at',)
    ordering = ('-created_at',) # Assuming 'created_at' exists on VideoSource from your models.py
    verbose_name_plural = "Video Sources (Platform Instances)"


class TranscriptInline(admin.StackedInline):
    model = Transcript
    fk_name = 'video_source'
    extra = 0
    fields = ('language_code', 'processing_status', 'transcript_text_content_preview', 'transcript_timed_json_preview', 'quality_score', 'updated_at')
    readonly_fields = ('updated_at', 'transcript_text_content_preview', 'transcript_timed_json_preview')
    verbose_name_plural = "Transcripts for this Source"

    def transcript_text_content_preview(self, obj):
        text_content = obj.transcript_text_content # Field from provided models.py
        if text_content:
            return (text_content[:150] + '...') if len(text_content) > 150 else text_content
        return "N/A"
    transcript_text_content_preview.short_description = "Text Preview"

    def transcript_timed_json_preview(self, obj):
        if obj.transcript_timed_json:
            try:
                data = obj.transcript_timed_json
                if isinstance(data, list) and data:
                    return f"~{len(data)} segments. First: {str(data[0])[:100]}..."
                return (str(data)[:150] + '...') if len(str(data)) > 150 else str(data)
            except Exception:
                return "Error parsing JSON"
        return "N/A"
    transcript_timed_json_preview.short_description = "Timed JSON Preview"


class ExtractedKeywordInline(admin.TabularInline):
    model = ExtractedKeyword
    fk_name = 'transcript' # As per provided models.py
    extra = 0
    fields = ('keyword_text', 'relevance_score')
    ordering = ('-relevance_score',)
    verbose_name_plural = "Keywords Extracted from this Transcript"


class VideoTopicInline(admin.TabularInline):
    model = VideoTopic
    fk_name = 'transcript' # As per provided models.py
    extra = 0
    fields = ('topic_label', 'topic_relevance_score') # Fields from provided models.py
    ordering = ('-topic_relevance_score',)
    verbose_name_plural = "Topics Identified in this Transcript"


class VideoFrameFeatureInline(admin.TabularInline):
    model = VideoFrameFeature
    fk_name = 'video_source'
    extra = 0
    fields = ('timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status')
    readonly_fields = ('hash_value_preview', 'vector_db_id_status')
    ordering = ('timestamp_in_video_ms',)
    verbose_name_plural = "Visual Frame Features for this Source"

    def hash_value_preview(self, obj):
        if obj.hash_value: # Field from provided models.py
            return obj.hash_value[:30] + '...' if len(obj.hash_value) > 30 else obj.hash_value
        return "N/A"
    hash_value_preview.short_description = "Hash Value Preview"
    
    def vector_db_id_status(self,obj):
        return "Set" if obj.vector_db_id else "Not Set" # Field from provided models.py
    vector_db_id_status.short_description = "In Vector DB?"

# --- ModelAdmin Configurations ---

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('id', 'title_preview', 'duration_seconds', 'publication_date', 'deduplication_hash_short', 'source_instance_count', 'created_at')
    list_filter = ('publication_date', 'created_at')
    search_fields = ('title', 'description', 'deduplication_hash', 'id__iexact')
    date_hierarchy = 'publication_date'
    readonly_fields = ('id', 'created_at', 'updated_at', 'deduplication_hash')
    fieldsets = (
        (None, {'fields': ('id', 'title', 'description')}),
        ('Details', {'fields': ('duration_seconds', 'publication_date', 'primary_thumbnail_url')}),
        ('Internal Tracking', {'fields': ('deduplication_hash', 'created_at', 'updated_at')}),
    )
    inlines = [VideoSourceInline]
    list_per_page = 20

    def title_preview(self, obj):
        return (obj.title[:75] + '...') if len(obj.title) > 75 else obj.title
    title_preview.short_description = 'Title'

    def deduplication_hash_short(self, obj):
        if obj.deduplication_hash:
            return obj.deduplication_hash[:12] + '...'
        return "N/A"
    deduplication_hash_short.short_description = 'Dedupe Hash'

    def source_instance_count(self, obj):
        return obj.sources.count() # 'sources' is the related_name from VideoSource.video
    source_instance_count.short_description = '# Sources'


@admin.register(VideoSource)
class VideoSourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_title', 'platform_name', 'platform_video_id_preview', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at', 'transcript_count_display')
    list_filter = ('platform_name', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at')
    search_fields = ('video__title', 'platform_video_id', 'original_url', 'id__iexact', 'video__id__iexact')
    raw_id_fields = ('video',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_visual_indexed_at')
    list_select_related = ('video',)
    fieldsets = (
        ('Linkage', {'fields': ('video',)}),
        ('Platform Details', {'fields': ('id', 'platform_name', 'platform_video_id', 'original_url', 'embed_url', 'is_primary_source')}),
        ('Metadata & Processing', {
            'fields': ('source_metadata_json_pretty', 'last_scraped_at', 
                       'meta_visual_processing_status', 'meta_visual_processing_error', 'last_visual_indexed_at')
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    inlines = [TranscriptInline, VideoFrameFeatureInline]
    list_per_page = 20
    actions = ['reset_visual_processing_status_action']

    def linked_video_title(self, obj):
        if obj.video:
            link = reverse("admin:api_video_change", args=[obj.video.id])
            title_preview = (obj.video.title[:30] + '...') if len(obj.video.title) > 30 else obj.video.title
            return format_html('<a href="{}">{} (ID: {})</a>', link, title_preview, obj.video.id)
        return "N/A"
    linked_video_title.short_description = 'Canonical Video'
    linked_video_title.admin_order_field = 'video__title'

    def platform_video_id_preview(self, obj):
        return (obj.platform_video_id[:20] + '...') if len(obj.platform_video_id) > 20 else obj.platform_video_id
    platform_video_id_preview.short_description = 'Platform ID'

    def transcript_count_display(self, obj):
        return obj.transcripts.count() # 'transcripts' is related_name from Transcript.video_source
    transcript_count_display.short_description = '# Transcripts'

    def source_metadata_json_pretty(self, obj):
        if obj.source_metadata_json:
            pretty_json = json.dumps(obj.source_metadata_json, indent=2, sort_keys=True)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    source_metadata_json_pretty.short_description = "Source Metadata (JSON)"

    def reset_visual_processing_status_action(self, request, queryset):
        updated_count = queryset.update(
            meta_visual_processing_status='pending',
            meta_visual_processing_error=None,
            last_visual_indexed_at=None
        )
        self.message_user(request, f"{updated_count} video sources reset for visual processing.")
    reset_visual_processing_status_action.short_description = "Reset visual processing to 'Pending'"


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_source_info', 'language_code', 'processing_status', 'quality_score', 'updated_at', 'keyword_and_topic_counts')
    list_filter = ('language_code', 'processing_status', 'quality_score', 'updated_at')
    search_fields = ('video_source__video__title', 'video_source__platform_video_id', 'transcript_text_content', 'id__iexact')
    raw_id_fields = ('video_source',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('id', 'video_source', 'language_code')}),
        ('Content & Quality', {'fields': ('transcript_text_content', 'transcript_timed_json_pretty', 'quality_score')}),
        ('Processing', {'fields': ('processing_status',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    inlines = [ExtractedKeywordInline, VideoTopicInline]
    list_select_related = ('video_source__video',)
    list_per_page = 20

    def linked_video_source_info(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">VSID: {} ({})</a>', link, obj.video_source.id, obj.video_source.platform_name)
        return "N/A"
    linked_video_source_info.short_description = 'Video Source'
    linked_video_source_info.admin_order_field = 'video_source__id'

    def transcript_timed_json_pretty(self, obj):
        if obj.transcript_timed_json:
            pretty_json = json.dumps(obj.transcript_timed_json, indent=2)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    transcript_timed_json_pretty.short_description = "Timed Transcript (JSON)"

    def keyword_and_topic_counts(self, obj):
        return f"Keywords: {obj.keywords.count()}, Topics: {obj.topics.count()}" # 'keywords' and 'topics' are related_names
    keyword_and_topic_counts.short_description = "Features Count"

@admin.register(ExtractedKeyword)
class ExtractedKeywordAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_transcript_info', 'keyword_text', 'relevance_score')
    search_fields = ('keyword_text', 'transcript__id__iexact', 'transcript__video_source__video__title')
    list_filter = ('relevance_score',)
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-relevance_score', 'keyword_text')
    list_select_related = ('transcript__video_source',)

    def linked_transcript_info(self, obj):
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {} (VSID: {})</a>', link, obj.transcript.id, obj.transcript.video_source_id)
        return "N/A"
    linked_transcript_info.short_description = 'Transcript'

@admin.register(VideoTopic)
class VideoTopicAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_transcript_info', 'topic_label', 'topic_relevance_score')
    search_fields = ('topic_label', 'transcript__id__iexact', 'transcript__video_source__video__title')
    list_filter = ('topic_relevance_score',)
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-topic_relevance_score', 'topic_label')
    list_select_related = ('transcript__video_source',)

    def linked_transcript_info(self, obj): # Shared helper function
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {} (VSID: {})</a>', link, obj.transcript.id, obj.transcript.video_source_id)
        return "N/A"
    linked_transcript_info.short_description = 'Transcript'


@admin.register(VideoFrameFeature)
class VideoFrameFeatureAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_source_info', 'timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status', 'created_at')
    list_filter = ('feature_type', 'created_at')
    search_fields = ('video_source__platform_video_id', 'video_source__video__title', 'hash_value', 'vector_db_id')
    raw_id_fields = ('video_source',)
    readonly_fields = ('id', 'created_at', 'feature_data_json_pretty')
    fieldsets = (
        (None, {'fields': ('id', 'video_source', 'timestamp_in_video_ms', 'feature_type')}),
        ('Feature Data', {'fields': ('frame_image_url', 'hash_value', 'feature_data_json_pretty', 'vector_db_id')}),
        ('Timestamps', {'fields': ('created_at',)}),
    )
    list_per_page = 25
    list_select_related = ('video_source__video',)

    def linked_video_source_info(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            vs_id_str = f"VSID: {obj.video_source.id}"
            if obj.video_source.video:
                vs_id_str += f" (Video: {obj.video_source.video.title[:20]}...)"
            return format_html('<a href="{}">{}</a>', link, vs_id_str)
        return "N/A"
    linked_video_source_info.short_description = 'Video Source'

    def hash_value_preview(self, obj):
        if obj.hash_value:
            return (obj.hash_value[:20] + '...') if len(obj.hash_value) > 20 else obj.hash_value
        return "N/A"
    hash_value_preview.short_description = 'Hash Preview'

    def vector_db_id_status(self,obj):
        return "Set" if obj.vector_db_id else "Not Set"
    vector_db_id_status.short_description = "Vector DB ID"

    def feature_data_json_pretty(self, obj):
        if obj.feature_data_json:
            pretty_json = json.dumps(obj.feature_data_json, indent=2)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 200px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    feature_data_json_pretty.short_description = "Feature Data (JSON)"


@admin.register(SearchTask)
class SearchTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_user_email', 'query_text_preview', 'status', 'created_at_formatted', 'updated_at_formatted')
    list_filter = ('status', 'created_at', 'user')
    search_fields = ('id__iexact', 'user__email', 'user__username', 'query_text', 'celery_task_id')
    readonly_fields = ('id', 'user', 'session_id', 'query_text', 'query_image_ref', 'query_image_fingerprint',
                       'applied_filters_json_pretty', 'result_video_ids_json_pretty', 'detailed_results_info_json_pretty',
                       'celery_task_id', 'error_message', 'created_at', 'updated_at')
    fieldsets = (
        ('Task Overview', {'fields': ('id', 'user', 'session_id', 'status', 'celery_task_id')}),
        ('Query Details', {'fields': ('query_text', 'query_image_ref', 'query_image_fingerprint', 'applied_filters_json_pretty')}),
        ('Results & Errors', {'fields': ('result_video_ids_json_pretty', 'detailed_results_info_json_pretty', 'error_message')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    list_per_page = 25
    ordering = ('-created_at',)

    def linked_user_email(self, obj):
        return obj.user.email if obj.user else "Anonymous/Session"
    linked_user_email.short_description = "User"
    linked_user_email.admin_order_field = 'user__email'

    def query_text_preview(self, obj):
        if obj.query_text:
            return (obj.query_text[:75] + '...') if len(obj.query_text) > 75 else obj.query_text
        return "Image/URL Query" if obj.query_image_ref else "N/A"
    query_text_preview.short_description = "Query"

    def _format_datetime(self, dt_obj):
        return dt_obj.strftime("%Y-%m-%d %H:%M") if dt_obj else "N/A"

    def created_at_formatted(self,obj):
        return self._format_datetime(obj.created_at)
    created_at_formatted.admin_order_field = 'created_at'
    created_at_formatted.short_description = 'Created'

    def updated_at_formatted(self,obj):
        return self._format_datetime(obj.updated_at)
    updated_at_formatted.admin_order_field = 'updated_at'
    updated_at_formatted.short_description = 'Updated'

    def _pretty_json_readonly_field(self, obj_json_field, field_name_pretty):
        if obj_json_field:
            try:
                pretty_json = json.dumps(obj_json_field, indent=2, sort_keys=True)
                return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 400px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
            except TypeError:
                return str(obj_json_field) 
        return "N/A"
    
    def applied_filters_json_pretty(self, obj):
        return self._pretty_json_readonly_field(obj.applied_filters_json, "Applied Filters")
    applied_filters_json_pretty.short_description = "Applied Filters (JSON)"

    def result_video_ids_json_pretty(self, obj):
        return self._pretty_json_readonly_field(obj.result_video_ids_json, "Result Video IDs")
    result_video_ids_json_pretty.short_description = "Result Video IDs (JSON)"
    
    def detailed_results_info_json_pretty(self, obj):
        return self_pretty_json_readonly_field(obj.detailed_results_info_json, "Detailed Results Info") # type: ignore
    detailed_results_info_json_pretty.short_description = "Detailed Results Info (JSON)"


@admin.register(SignupCode)
class SignupCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'code', 'plan_name', 'is_used', 'activated_user_email_link', 'expires_at_formatted', 'created_at')
    list_filter = ('is_used', 'plan_name', 'expires_at', 'created_at')
    search_fields = ('id__iexact', 'email', 'code', 'user_activated__email') # Assuming user_activated is the field name
    readonly_fields = ('id', 'created_at', 'updated_at')
    actions = ['mark_as_unused_action']
    list_per_page = 25
    ordering = ('-created_at',)

    def activated_user_email_link(self, obj):
        if obj.user_activated: # Field from provided models.py
            # Assuming you have User admin registered (default or custom)
            link = reverse("admin:auth_user_change", args=[obj.user_activated.id])
            return format_html('<a href="{}">{}</a>', link, obj.user_activated.email)
        return "Not Activated"
    activated_user_email_link.short_description = "Activated By"
    activated_user_email_link.admin_order_field = 'user_activated__email'


    def expires_at_formatted(self, obj):
        return obj.expires_at.strftime("%Y-%m-%d %H:%M") if obj.expires_at else "N/A"
    expires_at_formatted.short_description = "Expires At"
    expires_at_formatted.admin_order_field = 'expires_at'

    def mark_as_unused_action(self, request, queryset):
        updated_count = queryset.update(is_used=False, user_activated=None)
        self.message_user(request, f"{updated_count} signup codes marked as UNUSED and unlinked.")
    mark_as_unused_action.short_description = "Mark selected codes as UNUSED & Unlink"

# Note: If UserProfile, VideoEditProject, EditTask models are added to your api.models,
# you would add their ModelAdmin classes and register them here similarly.
# For UserProfile, you'd typically unregister the default User admin and re-register
# it with UserProfile as an inline, like so:

# from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
# from django.contrib.auth.models import User
# from .models import UserProfile # Assuming UserProfile is in your api.models

# class UserProfileInline(admin.StackedInline):
# model = UserProfile
# can_delete = False
# verbose_name_plural = 'Profile Details'
# fk_name = 'user'
# fields = ('your_profile_field1', 'your_profile_field2') # Add actual fields

# class CustomUserAdmin(BaseUserAdmin):
# inlines = (UserProfileInline,)
# list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'profile_info_custom_method') # Example
#
#    def profile_info_custom_method(self, instance):
#        try:
# return instance.profile.your_profile_field1 # Example
#        except UserProfile.DoesNotExist:
# return 'N/A'
#    profile_info_custom_method.short_description = 'Profile Info'

# if admin.site.is_registered(User):
# admin.site.unregister(User)
# admin.site.register(User, CustomUserAdmin)
