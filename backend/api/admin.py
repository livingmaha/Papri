# backend/api/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
import json # For pretty printing JSON fields

# Import models from the current app (api.models)
from .models import (
    Video, VideoSource, Transcript, ExtractedKeyword, VideoTopic,
    VideoFrameFeature, SearchTask, SignupCode
)

# --- Inlines for Related Models ---

class VideoSourceInline(admin.TabularInline):
    model = VideoSource
    fk_name = 'video' # Explicitly define foreign key if not default
    extra = 0  # Number of empty forms to display
    show_change_link = True
    fields = ('platform_name', 'platform_video_id', 'original_url', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at')
    readonly_fields = ('last_scraped_at',)
    ordering = ('-created_at',)
    verbose_name_plural = "Video Sources on Different Platforms"


class TranscriptInline(admin.StackedInline): # Stacked for potentially larger text fields
    model = Transcript
    extra = 0
    fields = ('language_code', 'processing_status', 'transcript_text_content_preview', 'transcript_timed_json_preview', 'quality_score', 'updated_at')
    readonly_fields = ('updated_at', 'transcript_text_content_preview', 'transcript_timed_json_preview')
    verbose_name_plural = "Transcripts"

    def transcript_text_content_preview(self, obj):
        if obj.transcript_text_content:
            return (obj.transcript_text_content[:150] + '...') if len(obj.transcript_text_content) > 150 else obj.transcript_text_content
        return "N/A"
    transcript_text_content_preview.short_description = "Text Preview"

    def transcript_timed_json_preview(self, obj):
        if obj.transcript_timed_json:
            try:
                # Show first few entries or a summary
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
    fk_name = 'transcript'
    extra = 0
    fields = ('keyword_text', 'relevance_score')
    ordering = ('-relevance_score',)
    verbose_name_plural = "Extracted Keywords"


class VideoTopicInline(admin.TabularInline):
    model = VideoTopic
    fk_name = 'transcript'
    extra = 0
    fields = ('topic_label', 'topic_relevance_score')
    ordering = ('-topic_relevance_score',)
    verbose_name_plural = "Identified Topics"


class VideoFrameFeatureInline(admin.TabularInline):
    model = VideoFrameFeature
    fk_name = 'video_source'
    extra = 0
    fields = ('timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status')
    readonly_fields = ('hash_value_preview', 'vector_db_id_status')
    ordering = ('timestamp_in_video_ms',)
    verbose_name_plural = "Visual Frame Features"

    def hash_value_preview(self, obj):
        if obj.hash_value:
            return obj.hash_value[:30] + '...' if len(obj.hash_value) > 30 else obj.hash_value
        return "N/A"
    hash_value_preview.short_description = "Hash Value"
    
    def vector_db_id_status(self,obj):
        return "Set" if obj.vector_db_id else "Not Set"
    vector_db_id_status.short_description = "In Vector DB?"


# --- ModelAdmin Configurations ---

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('id', 'title_preview', 'duration_seconds', 'publication_date', 'deduplication_hash_short', 'source_count', 'created_at')
    list_filter = ('publication_date', 'created_at')
    search_fields = ('title', 'description', 'deduplication_hash', 'id')
    date_hierarchy = 'publication_date'
    readonly_fields = ('id', 'created_at', 'updated_at', 'deduplication_hash')
    fieldsets = (
        (None, {'fields': ('id', 'title', 'description')}),
        ('Details', {'fields': ('duration_seconds', 'publication_date', 'primary_thumbnail_url')}),
        ('Internal', {'fields': ('deduplication_hash', 'created_at', 'updated_at')}),
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

    def source_count(self, obj):
        return obj.sources.count()
    source_count.short_description = '# Sources'


@admin.register(VideoSource)
class VideoSourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_link', 'platform_name', 'platform_video_id_short', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at', 'transcript_count')
    list_filter = ('platform_name', 'is_primary_source', 'meta_visual_processing_status', 'last_scraped_at')
    search_fields = ('video__title', 'platform_video_id', 'original_url', 'id', 'video__id')
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
    inlines = [TranscriptInline, VideoFrameFeatureInline] # Keywords & Topics are under Transcript
    list_per_page = 20
    actions = ['reset_visual_processing']

    def video_link(self, obj):
        if obj.video:
            link = reverse("admin:api_video_change", args=[obj.video.id])
            title_preview = (obj.video.title[:30] + '...') if len(obj.video.title) > 30 else obj.video.title
            return format_html('<a href="{}">{}</a>', link, title_preview)
        return "N/A"
    video_link.short_description = 'Canonical Video'
    video_link.admin_order_field = 'video__title'

    def platform_video_id_short(self, obj):
        return (obj.platform_video_id[:20] + '...') if len(obj.platform_video_id) > 20 else obj.platform_video_id
    platform_video_id_short.short_description = 'Platform ID'

    def transcript_count(self, obj):
        return obj.transcripts.count()
    transcript_count.short_description = '# Transcripts'

    def source_metadata_json_pretty(self, obj):
        if obj.source_metadata_json:
            pretty_json = json.dumps(obj.source_metadata_json, indent=2, sort_keys=True)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    source_metadata_json_pretty.short_description = "Source Metadata (JSON)"

    def reset_visual_processing(self, request, queryset):
        updated_count = queryset.update(
            meta_visual_processing_status='pending',
            meta_visual_processing_error=None,
            last_visual_indexed_at=None
        )
        self.message_user(request, f"{updated_count} video sources reset for visual processing.")
    reset_visual_processing.short_description = "Reset visual processing status to 'Pending'"


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_link', 'language_code', 'processing_status', 'quality_score', 'updated_at', 'keyword_topic_counts')
    list_filter = ('language_code', 'processing_status', 'quality_score', 'updated_at')
    search_fields = ('video_source__video__title', 'video_source__platform_video_id', 'transcript_text_content', 'id')
    raw_id_fields = ('video_source',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('id', 'video_source', 'language_code')}),
        ('Content & Quality', {'fields': ('transcript_text_content', 'transcript_timed_json_pretty', 'quality_score')}),
        ('Processing', {'fields': ('processing_status',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    inlines = [ExtractedKeywordInline, VideoTopicInline]
    list_select_related = ('video_source__video',) # For video_source_link
    list_per_page = 20

    def video_source_link(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">VSID: {} ({})</a>', link, obj.video_source.id, obj.video_source.platform_name)
        return "N/A"
    video_source_link.short_description = 'Video Source'
    video_source_link.admin_order_field = 'video_source__id' # Allow sorting by this

    def transcript_timed_json_pretty(self, obj):
        if obj.transcript_timed_json:
            pretty_json = json.dumps(obj.transcript_timed_json, indent=2)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    transcript_timed_json_pretty.short_description = "Timed Transcript (JSON)"

    def keyword_topic_counts(self, obj):
        return f"KW: {obj.keywords.count()}, Topics: {obj.topics.count()}"
    keyword_topic_counts.short_description = "Features"

@admin.register(ExtractedKeyword)
class ExtractedKeywordAdmin(admin.ModelAdmin):
    list_display = ('id', 'transcript_id_link', 'keyword_text', 'relevance_score')
    search_fields = ('keyword_text', 'transcript__id', 'transcript__video_source__video__title')
    list_filter = ('relevance_score',) # Could be by ranges if many
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-relevance_score', 'keyword_text')

    def transcript_id_link(self, obj):
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {}</a>', link, obj.transcript.id)
        return "N/A"
    transcript_id_link.short_description = 'Transcript ID'

@admin.register(VideoTopic)
class VideoTopicAdmin(admin.ModelAdmin):
    list_display = ('id', 'transcript_id_link', 'topic_label', 'topic_relevance_score')
    search_fields = ('topic_label', 'transcript__id', 'transcript__video_source__video__title')
    list_filter = ('topic_relevance_score',)
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-topic_relevance_score', 'topic_label')

    def transcript_id_link(self, obj): # Duplicated code, consider a mixin or helper
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {}</a>', link, obj.transcript.id)
        return "N/A"
    transcript_id_link.short_description = 'Transcript ID'


@admin.register(VideoFrameFeature)
class VideoFrameFeatureAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_link', 'timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status', 'created_at')
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
    list_select_related = ('video_source__video',) # For video_source_link

    def video_source_link(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">VSID: {} ({})</a>', link, obj.video_source.id, obj.video_source.platform_video_id)
        return "N/A"
    video_source_link.short_description = 'Video Source'

    def hash_value_preview(self, obj):
        if obj.hash_value:
            return obj.hash_value[:20] + '...' if len(obj.hash_value) > 20 else obj.hash_value
        return "N/A"
    hash_value_preview.short_description = 'Hash'

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
    list_display = ('id', 'user_email', 'query_text_preview', 'status', 'created_at_time', 'updated_at_time')
    list_filter = ('status', 'created_at', 'user')
    search_fields = ('id__iexact', 'user__email', 'user__username', 'query_text', 'celery_task_id') # Use id__iexact for UUIDs if needed
    readonly_fields = ('id', 'user', 'session_id', 'query_text', 'query_image_ref', 'query_image_fingerprint',
                       'applied_filters_json_pretty', 'result_video_ids_json_pretty', 'detailed_results_info_json_pretty',
                       'celery_task_id', 'error_message', 'created_at', 'updated_at')
    fieldsets = (
        ('Task Info', {'fields': ('id', 'user', 'session_id', 'status', 'celery_task_id')}),
        ('Query', {'fields': ('query_text', 'query_image_ref', 'query_image_fingerprint', 'applied_filters_json_pretty')}),
        ('Results & Errors', {'fields': ('result_video_ids_json_pretty', 'detailed_results_info_json_pretty', 'error_message')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    list_per_page = 25
    ordering = ('-created_at',)

    def user_email(self, obj):
        return obj.user.email if obj.user else "Anonymous"
    user_email.short_description = "User"
    user_email.admin_order_field = 'user__email'

    def query_text_preview(self, obj):
        if obj.query_text:
            return (obj.query_text[:75] + '...') if len(obj.query_text) > 75 else obj.query_text
        return "N/A"
    query_text_preview.short_description = "Query"

    def created_at_time(self,obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")
    created_at_time.admin_order_field = 'created_at'
    created_at_time.short_description = 'Created'

    def updated_at_time(self,obj):
        return obj.updated_at.strftime("%Y-%m-%d %H:%M")
    updated_at_time.admin_order_field = 'updated_at'
    updated_at_time.short_description = 'Updated'

    def _pretty_json_field(self, obj_json_field, field_name):
        if obj_json_field:
            try:
                pretty_json = json.dumps(obj_json_field, indent=2, sort_keys=True)
                return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 400px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
            except TypeError:
                return str(obj_json_field) # Fallback if not serializable directly
        return "N/A"

    def applied_filters_json_pretty(self, obj):
        return self._pretty_json_field(obj.applied_filters_json, "Applied Filters")
    applied_filters_json_pretty.short_description = "Applied Filters (JSON)"

    def result_video_ids_json_pretty(self, obj):
        return self._pretty_json_field(obj.result_video_ids_json, "Result Video IDs")
    result_video_ids_json_pretty.short_description = "Result Video IDs (JSON)"
    
    def detailed_results_info_json_pretty(self, obj):
        return self._pretty_json_field(obj.detailed_results_info_json, "Detailed Results Info")
    detailed_results_info_json_pretty.short_description = "Detailed Results Info (JSON)"


@admin.register(SignupCode)
class SignupCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'code', 'plan_name', 'is_used', 'user_activated_email', 'expires_at_display', 'created_at')
    list_filter = ('is_used', 'plan_name', 'expires_at', 'created_at')
    search_fields = ('id__iexact', 'email', 'code', 'user_activated__email')
    readonly_fields = ('id', 'created_at', 'updated_at')
    actions = ['mark_as_unused_admin'] # 'mark_as_used' might be too risky without user context.
    list_per_page = 25
    ordering = ('-created_at',)

    def user_activated_email(self, obj):
        return obj.user_activated.email if obj.user_activated else "Not Activated"
    user_activated_email.short_description = "Activated By"

    def expires_at_display(self, obj):
        return obj.expires_at.strftime("%Y-%m-%d %H:%M") if obj.expires_at else "N/A"
    expires_at_display.short_description = "Expires At"
    expires_at_display.admin_order_field = 'expires_at'

    def mark_as_unused_admin(self, request, queryset):
        updated_count = queryset.update(is_used=False, user_activated=None)
        self.message_user(request, f"{updated_count} signup codes marked as UNUSED and
