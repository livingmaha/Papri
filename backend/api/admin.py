# backend/api/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
import json

# Import all models from the current app (api.models)
from .models import (
    Video, VideoSource, Transcript, ExtractedKeyword, VideoTopic,
    VideoFrameFeature, UserProfile, SearchTask, SignupCode,
    VideoEditProject, EditTask
)

# --- Inlines ---

class VideoSourceInline(admin.TabularInline):
    model = VideoSource
    fk_name = 'video'
    extra = 0
    show_change_link = True
    fields = ('platform_name', 'platform_video_id', 'original_url', 'is_primary_source', 'processing_status', 'meta_visual_processing_status', 'last_scraped_at')
    readonly_fields = ('last_scraped_at', 'processing_status', 'meta_visual_processing_status') # Status fields are usually system-set
    ordering = ('-created_at',)
    verbose_name_plural = "Platform Sources for this Video"

class TranscriptInline(admin.StackedInline):
    model = Transcript
    fk_name = 'video_source'
    extra = 0
    fields = ('language_code', 'processing_status', 'transcript_text_content_preview', 'transcript_timed_json_preview', 'quality_score', 'updated_at')
    readonly_fields = ('updated_at', 'transcript_text_content_preview', 'transcript_timed_json_preview')
    verbose_name_plural = "Transcripts for this Source"

    def transcript_text_content_preview(self, obj):
        text_content = obj.transcript_text_content
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
            except Exception: return "Error parsing JSON"
        return "N/A"
    transcript_timed_json_preview.short_description = "Timed JSON Preview"

class ExtractedKeywordInline(admin.TabularInline):
    model = ExtractedKeyword
    fk_name = 'transcript'
    extra = 0
    fields = ('keyword_text', 'relevance_score')
    ordering = ('-relevance_score',)
    verbose_name_plural = "Keywords from this Transcript"

class VideoTopicInline(admin.TabularInline):
    model = VideoTopic
    fk_name = 'transcript'
    extra = 0
    fields = ('topic_label', 'topic_relevance_score')
    ordering = ('-topic_relevance_score',)
    verbose_name_plural = "Topics from this Transcript"

class VideoFrameFeatureInline(admin.TabularInline):
    model = VideoFrameFeature
    fk_name = 'video_source'
    extra = 0
    fields = ('timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status')
    readonly_fields = ('hash_value_preview', 'vector_db_id_status')
    ordering = ('timestamp_in_video_ms',)
    verbose_name_plural = "Visual Features for this Source"

    def hash_value_preview(self, obj):
        return (obj.hash_value[:30] + '...') if obj.hash_value and len(obj.hash_value) > 30 else obj.hash_value or "N/A"
    hash_value_preview.short_description = "Hash Value Preview"
    
    def vector_db_id_status(self,obj):
        return "Set" if obj.vector_db_id else "Not Set"
    vector_db_id_status.short_description = "In Vector DB?"

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False # Typically, deleting a User should delete the Profile via cascade
    verbose_name_plural = 'User Profile Details'
    fk_name = 'user'
    fields = ('subscription_plan', 'subscription_id_gateway', 'subscription_expiry_date', 'remaining_trial_searches')
    readonly_fields = ('subscription_id_gateway',) # Usually set by payment system

class EditTaskInline(admin.TabularInline):
    model = EditTask
    fk_name = 'project'
    extra = 0
    fields = ('id', 'prompt_text_preview', 'status', 'result_media_path_link', 'created_at', 'updated_at')
    readonly_fields = ('id', 'created_at', 'updated_at', 'prompt_text_preview', 'result_media_path_link')
    show_change_link = True
    ordering = ('-created_at',)
    verbose_name_plural = "Editing Tasks for this Project"

    def prompt_text_preview(self, obj):
        return (obj.prompt_text[:100] + '...') if obj.prompt_text and len(obj.prompt_text) > 100 else obj.prompt_text or "N/A"
    prompt_text_preview.short_description = "Prompt Preview"
    
    def result_media_path_link(self,obj):
        url = obj.get_result_url()
        if url:
            return format_html("<a href='{}' target='_blank'>View/Download</a> ({})", url, obj.result_media_path)
        return obj.result_media_path or "N/A"
    result_media_path_link.short_description = "Result Media"


# --- ModelAdmin Configurations ---

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('id', 'title_preview', 'duration_seconds', 'publication_date', 'category', 'deduplication_hash_short', 'source_instance_count', 'created_at')
    list_filter = ('publication_date', 'category', 'created_at')
    search_fields = ('title', 'description', 'deduplication_hash', 'id__iexact')
    date_hierarchy = 'publication_date'
    readonly_fields = ('id', 'created_at', 'updated_at', 'deduplication_hash')
    fieldsets = (
        (None, {'fields': ('id', 'title', 'description')}),
        ('Details', {'fields': ('duration_seconds', 'publication_date', 'primary_thumbnail_url', 'tags', 'category')}),
        ('Internal Tracking', {'fields': ('deduplication_hash', 'created_at', 'updated_at')}),
    )
    inlines = [VideoSourceInline]
    list_per_page = 20

    def title_preview(self, obj):
        return (obj.title[:75] + '...') if obj.title and len(obj.title) > 75 else obj.title or "N/A"
    title_preview.short_description = 'Title'

    def deduplication_hash_short(self, obj):
        return (obj.deduplication_hash[:12] + '...') if obj.deduplication_hash else "N/A"
    deduplication_hash_short.short_description = 'Dedupe Hash'

    def source_instance_count(self, obj):
        return obj.sources.count()
    source_instance_count.short_description = '# Sources'


@admin.register(VideoSource)
class VideoSourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_title_admin', 'platform_name', 'platform_video_id_preview', 'is_primary_source', 'processing_status', 'meta_visual_processing_status', 'last_scraped_at', 'transcript_count_display')
    list_filter = ('platform_name', 'is_primary_source', 'processing_status', 'meta_visual_processing_status', 'last_scraped_at')
    search_fields = ('video__title', 'platform_video_id', 'original_url', 'id__iexact', 'video__id__iexact')
    raw_id_fields = ('video',)
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_visual_indexed_at', 'last_analyzed_at', 'processing_error_message', 'meta_visual_processing_error')
    list_select_related = ('video',)
    fieldsets = (
        ('Linkage', {'fields': ('video',)}),
        ('Platform Details', {'fields': ('id', 'platform_name', 'platform_video_id', 'original_url', 'embed_url', 'is_primary_source')}),
        ('Uploader & Source Stats', {'fields': ('uploader_name', 'uploader_url', 'view_count', 'like_count', 'comment_count')}),
        ('Source Metadata', {'fields': ('source_metadata_json_pretty',)}),
        ('Processing Status', {
            'fields': ('processing_status', 'processing_error_message', 'last_analyzed_at', 
                       'meta_visual_processing_status', 'meta_visual_processing_error', 'last_visual_indexed_at')
        }),
        ('Timestamps', {'fields': ('last_scraped_at', 'created_at', 'updated_at')}),
    )
    inlines = [TranscriptInline, VideoFrameFeatureInline]
    list_per_page = 20
    actions = ['reset_all_processing_action', 'mark_analysis_complete_action']

    def linked_video_title_admin(self, obj):
        if obj.video:
            link = reverse("admin:api_video_change", args=[obj.video.id])
            title_preview = (obj.video.title[:30] + '...') if obj.video.title and len(obj.video.title) > 30 else obj.video.title or "N/A"
            return format_html('<a href="{}">{} (ID: {})</a>', link, title_preview, obj.video.id)
        return "N/A"
    linked_video_title_admin.short_description = 'Canonical Video'
    linked_video_title_admin.admin_order_field = 'video__title'

    def platform_video_id_preview(self, obj):
        return (obj.platform_video_id[:20] + '...') if obj.platform_video_id and len(obj.platform_video_id) > 20 else obj.platform_video_id or "N/A"
    platform_video_id_preview.short_description = 'Platform ID'

    def transcript_count_display(self, obj):
        return obj.transcripts.count()
    transcript_count_display.short_description = '# Transcripts'

    def source_metadata_json_pretty(self, obj):
        if obj.source_metadata_json:
            pretty_json = json.dumps(obj.source_metadata_json, indent=2, sort_keys=True)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    source_metadata_json_pretty.short_description = "Source Metadata (JSON)"

    def reset_all_processing_action(self, request, queryset):
        updated_count = queryset.update(
            processing_status='pending', meta_visual_processing_status='pending',
            processing_error_message=None, meta_visual_processing_error=None,
            last_analyzed_at=None, last_visual_indexed_at=None
        )
        self.message_user(request, f"{updated_count} video sources reset to 'Pending' for all processing.")
    reset_all_processing_action.short_description = "Reset ALL processing to 'Pending'"

    def mark_analysis_complete_action(self, request, queryset):
        updated_count = queryset.update(
            processing_status='analysis_complete', meta_visual_processing_status='completed', # 'completed' from VISUAL_DETAIL_STATUS_CHOICES
            processing_error_message=None, meta_visual_processing_error=None,
            last_analyzed_at=timezone.now(), last_visual_indexed_at=timezone.now()
        )
        self.message_user(request, f"{updated_count} video sources marked as 'Analysis Complete'.")
    mark_analysis_complete_action.short_description = "Mark selected as 'Analysis Complete'"


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_source_admin_info', 'language_code', 'processing_status', 'quality_score', 'updated_at', 'feature_counts')
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

    def linked_video_source_admin_info(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">VSID: {} ({})</a>', link, obj.video_source.id, obj.video_source.platform_name)
        return "N/A"
    linked_video_source_admin_info.short_description = 'Video Source'
    linked_video_source_admin_info.admin_order_field = 'video_source__id'

    def transcript_timed_json_pretty(self, obj):
        if obj.transcript_timed_json:
            pretty_json = json.dumps(obj.transcript_timed_json, indent=2)
            return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", pretty_json)
        return "N/A"
    transcript_timed_json_pretty.short_description = "Timed Transcript (JSON)"

    def feature_counts(self, obj):
        return f"KW: {obj.keywords.count()}, Topics: {obj.topics.count()}"
    feature_counts.short_description = "Features"

@admin.register(ExtractedKeyword)
class ExtractedKeywordAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_transcript_admin_info', 'keyword_text', 'relevance_score', 'created_at')
    search_fields = ('keyword_text', 'transcript__id__iexact', 'transcript__video_source__video__title')
    list_filter = ('created_at', 'relevance_score',)
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-created_at', '-relevance_score', 'keyword_text')
    list_select_related = ('transcript__video_source',)
    readonly_fields = ('id','created_at')


    def linked_transcript_admin_info(self, obj):
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {} (VSID: {})</a>', link, obj.transcript.id, obj.transcript.video_source_id)
        return "N/A"
    linked_transcript_admin_info.short_description = 'Transcript'

@admin.register(VideoTopic)
class VideoTopicAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_transcript_admin_info', 'topic_label', 'topic_relevance_score', 'created_at')
    search_fields = ('topic_label', 'transcript__id__iexact', 'transcript__video_source__video__title')
    list_filter = ('created_at', 'topic_relevance_score',)
    raw_id_fields = ('transcript',)
    list_per_page = 50
    ordering = ('-created_at', '-topic_relevance_score', 'topic_label')
    list_select_related = ('transcript__video_source',)
    readonly_fields = ('id','created_at')


    def linked_transcript_admin_info(self, obj):
        if obj.transcript:
            link = reverse("admin:api_transcript_change", args=[obj.transcript.id])
            return format_html('<a href="{}">TID: {} (VSID: {})</a>', link, obj.transcript.id, obj.transcript.video_source_id)
        return "N/A"
    linked_transcript_admin_info.short_description = 'Transcript'


@admin.register(VideoFrameFeature)
class VideoFrameFeatureAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_video_source_admin_info', 'timestamp_in_video_ms', 'feature_type', 'hash_value_preview', 'vector_db_id_status', 'created_at')
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

    def linked_video_source_admin_info(self, obj):
        if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            vs_id_str = f"VSID: {obj.video_source.id}"
            if obj.video_source.video: vs_id_str += f" (Video: {obj.video_source.video.title[:20]}...)"
            return format_html('<a href="{}">{}</a>', link, vs_id_str)
        return "N/A"
    linked_video_source_admin_info.short_description = 'Video Source'

    def hash_value_preview(self, obj):
        return (obj.hash_value[:20] + '...') if obj.hash_value and len(obj.hash_value) > 20 else obj.hash_value or "N/A"
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
    list_display = ('id', 'linked_user_admin_email', 'query_text_preview', 'status', 'formatted_created_at', 'formatted_updated_at')
    list_filter = ('status', 'created_at', 'user')
    search_fields = ('id__iexact', 'user__email', 'user__username', 'query_text', 'celery_task_id')
    readonly_fields = ('id', 'user', 'session_id', 'query_text', 'query_image_ref', 'query_image_fingerprint', 'query_video_url',
                       'applied_filters_json_pretty', 'result_video_ids_json_pretty', 'detailed_results_info_json_pretty',
                       'celery_task_id', 'error_message', 'created_at', 'updated_at')
    fieldsets = (
        ('Task Overview', {'fields': ('id', 'user', 'session_id', 'status', 'celery_task_id')}),
        ('Query Details', {'fields': ('query_text', 'query_image_ref', 'query_image_fingerprint', 'query_video_url', 'applied_filters_json_pretty')}),
        ('Results & Errors', {'fields': ('result_video_ids_json_pretty', 'detailed_results_info_json_pretty', 'error_message')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    list_per_page = 25
    ordering = ('-created_at',)

    def linked_user_admin_email(self, obj):
        return obj.user.email if obj.user else "Anonymous/Session"
    linked_user_admin_email.short_description = "User"
    linked_user_admin_email.admin_order_field = 'user__email'

    def query_text_preview(self, obj):
        if obj.query_text:
            return (obj.query_text[:75] + '...') if len(obj.query_text) > 75 else obj.query_text
        return "Image/URL Query" if obj.query_image_ref or obj.query_video_url else "N/A"
    query_text_preview.short_description = "Query"

    def _format_datetime_admin(self, dt_obj):
        return dt_obj.strftime("%Y-%m-%d %H:%M") if dt_obj else "N/A"

    def formatted_created_at(self,obj): return self._format_datetime_admin(obj.created_at)
    formatted_created_at.admin_order_field = 'created_at'
    formatted_created_at.short_description = 'Created'

    def formatted_updated_at(self,obj): return self._format_datetime_admin(obj.updated_at)
    formatted_updated_at.admin_order_field = 'updated_at'
    formatted_updated_at.short_description = 'Updated'

    def _pretty_json_readonly_field_admin(self, obj_json_field):
        if obj_json_field:
            try:
                return format_html("<pre style='white-space: pre-wrap; word-wrap: break-word; max-height: 400px; overflow-y: auto; border: 1px solid #ccc; padding: 5px;'>{}</pre>", json.dumps(obj_json_field, indent=2, sort_keys=True))
            except TypeError: return str(obj_json_field)
        return "N/A"
    
    def applied_filters_json_pretty(self, obj): return self._pretty_json_readonly_field_admin(obj.applied_filters_json)
    applied_filters_json_pretty.short_description = "Applied Filters (JSON)"

    def result_video_ids_json_pretty(self, obj): return self._pretty_json_readonly_field_admin(obj.result_video_ids_json)
    result_video_ids_json_pretty.short_description = "Result Video IDs (JSON)"
    
    def detailed_results_info_json_pretty(self, obj): return self._pretty_json_readonly_field_admin(obj.detailed_results_info_json)
    detailed_results_info_json_pretty.short_description = "Detailed Results Info (JSON)"


@admin.register(SignupCode)
class SignupCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'code', 'plan_name', 'is_used', 'linked_activated_user_email', 'formatted_expires_at', 'created_at')
    list_filter = ('is_used', 'plan_name', 'expires_at', 'created_at')
    search_fields = ('id__iexact', 'email', 'code', 'user_activated__email')
    readonly_fields = ('id', 'created_at', 'updated_at')
    actions = ['mark_as_unused_and_unlink_action']
    list_per_page = 25
    ordering = ('-created_at',)

    def linked_activated_user_email(self, obj):
        if obj.user_activated:
            link = reverse("admin:auth_user_change", args=[obj.user_activated.id])
            return format_html('<a href="{}">{}</a>', link, obj.user_activated.email)
        return "Not Activated"
    linked_activated_user_email.short_description = "Activated By User"
    linked_activated_user_email.admin_order_field = 'user_activated__email'

    def formatted_expires_at(self, obj):
        return obj.expires_at.strftime("%Y-%m-%d %H:%M") if obj.expires_at else "Never"
    formatted_expires_at.short_description = "Expires At"
    formatted_expires_at.admin_order_field = 'expires_at'

    def mark_as_unused_and_unlink_action(self, request, queryset):
        updated_count = queryset.update(is_used=False, user_activated=None)
        self.message_user(request, f"{updated_count} signup codes marked as UNUSED and unlinked.")
    mark_as_unused_and_unlink_action.short_description = "Mark selected as UNUSED & Unlink User"

# --- UserProfile, VideoEditProject, EditTask Admin Registrations (if models exist) ---
# These are based on the models integrated in the Step 1 `models.py` file.

class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_user_subscription_plan', 'get_trial_searches')
    list_select_related = ('profile',) # For custom methods optimization

    def get_user_subscription_plan(self, instance):
        try: return instance.profile.get_subscription_plan_display() # Use Django's get_FOO_display
        except UserProfile.DoesNotExist: return 'N/A (No Profile)'
    get_user_subscription_plan.short_description = 'Subscription Plan'

    def get_trial_searches(self, instance):
        try: return instance.profile.remaining_trial_searches
        except UserProfile.DoesNotExist: return 'N/A'
    get_trial_searches.short_description = 'Trial Searches Left'
    
    # To add profile fields to user search, if UserProfile has searchable fields
    # search_fields = BaseUserAdmin.search_fields + ('profile__some_profile_field',)

# Unregister default User admin and reregister with custom one
if admin.site.is_registered(User):
    admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
# admin.site.register(UserProfile) # UserProfile is managed via UserAdmin inline

@admin.register(VideoEditProject)
class VideoEditProjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_user_admin', 'project_name', 'linked_original_video_source', 'uploaded_video_path_preview', 'task_count', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('id__iexact', 'project_name', 'user__email', 'original_video_source__id__iexact', 'uploaded_video_path')
    raw_id_fields = ('user', 'original_video_source')
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [EditTaskInline]
    ordering = ('-created_at',)
    list_select_related = ('user', 'original_video_source__video')

    def linked_user_admin(self, obj):
        if obj.user:
            link = reverse("admin:auth_user_change", args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', link, obj.user.email)
        return "N/A"
    linked_user_admin.short_description = "User"

    def linked_original_video_source(self, obj):
        if obj.original_video_source:
            link = reverse("admin:api_videosource_change", args=[obj.original_video_source.id])
            title = obj.original_video_source.video.title[:30]+"..." if obj.original_video_source.video else "VSID"
            return format_html('<a href="{}">{} ({})</a>', link, title, obj.original_video_source.id)
        return "N/A (User Upload)"
    linked_original_video_source.short_description = 'Original Video Source'

    def uploaded_video_path_preview(self, obj):
        if obj.uploaded_video_path:
            return ("..." + obj.uploaded_video_path[-40:]) if len(obj.uploaded_video_path) > 40 else obj.uploaded_video_path
        return "N/A"
    uploaded_video_path_preview.short_description = "Uploaded Path"

    def task_count(self, obj):
        return obj.edit_tasks.count()
    task_count.short_description = "# Tasks"


@admin.register(EditTask)
class EditTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'linked_project_admin', 'prompt_text_preview', 'status', 'celery_task_id_short', 'created_at', 'updated_at_formatted_admin')
    list_filter = ('status', 'created_at')
    search_fields = ('id__iexact', 'project__project_name', 'project__user__email', 'prompt_text', 'celery_task_id')
    raw_id_fields = ('project',)
    readonly_fields = ('id', 'celery_task_id', 'created_at', 'updated_at', 'result_media_path', 'error_message_display')
    fieldsets = (
        ("Task Overview", {'fields': ('id', 'project', 'status', 'celery_task_id')}),
        ("Details", {'fields': ('prompt_text', 'result_media_path', 'error_message_display')}),
        ("Timestamps", {'fields': ('created_at', 'updated_at')}),
    )
    list_select_related = ('project__user',)
    ordering = ('-created_at',)

    def linked_project_admin(self, obj):
        if obj.project:
            link = reverse("admin:api_videoeditproject_change", args=[obj.project.id])
            return format_html('<a href="{}">Project {} (User: {})</a>', link, obj.project.project_name[:20], obj.project.user.email)
        return "N/A"
    linked_project_admin.short_description = 'Video Edit Project'

    def prompt_text_preview(self, obj):
        return (obj.prompt_text[:75] + '...') if obj.prompt_text and len(obj.prompt_text) > 75 else obj.prompt_text or "N/A"
    prompt_text_preview.short_description = "Prompt"

    def celery_task_id_short(self, obj):
        return (obj.celery_task_id[:12] + "...") if obj.celery_task_id and len(obj.celery_task_id) > 12 else obj.celery_task_id or "N/A"
    celery_task_id_short.short_description = "Celery ID"
    
    def updated_at_formatted_admin(self, obj):
        return obj.updated_at.strftime("%Y-%m-%d %H:%M") if obj.updated_at else "N/A"
    updated_at_formatted_admin.admin_order_field = 'updated_at'
    updated_at_formatted_admin.short_description = 'Last Updated'

    def error_message_display(self, obj):
        if obj.error_message:
            return format_html("<div style='max-height: 100px; overflow-y: auto; border: 1px solid #ccc; padding: 3px;'>{}</div>", obj.error_message)
        return "No errors."
    error_message_display.short_description = "Error Message"
