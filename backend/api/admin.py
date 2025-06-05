# backend/api/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User # If extending User admin for UserProfile

from .models import (
    Video, VideoSource, Transcript, ExtractedKeyword, VideoTopic,
    VideoFrameFeature, UserProfile, SearchTask, SignupCode,
    VideoEditProject, EditTask
)

# --- Inlines ---
# Inlines allow editing related models on the same page as the parent model.

class VideoSourceInline(admin.TabularInline): # Or StackedInline for a different layout
    model = VideoSource
    extra = 0 # Number of empty forms to display
    show_change_link = True # Link to the VideoSource change page
    fields = ('platform_name', 'platform_video_id', 'original_url', 'processing_status', 'last_scraped_at', 'last_analyzed_at')
    readonly_fields = ('last_scraped_at', 'last_analyzed_at') # Often set by system
    ordering = ('-last_scraped_at',)

class TranscriptInline(admin.StackedInline): # Stacked for potentially larger text fields
    model = Transcript
    extra = 0
    fields = ('language_code', 'full_text_content_preview', 'source_type', 'updated_at')
    readonly_fields = ('updated_at', 'full_text_content_preview')
    
    def full_text_content_preview(self, obj):
        # Provide a preview to avoid displaying massive text directly in inline
        if obj.full_text_content:
            return (obj.full_text_content[:200] + '...') if len(obj.full_text_content) > 200 else obj.full_text_content
        return "N/A"
    full_text_content_preview.short_description = "Content Preview"


class ExtractedKeywordInline(admin.TabularInline):
    model = ExtractedKeyword
    extra = 0
    fields = ('keyword_text', 'relevance_score', 'source_field')
    ordering = ('-relevance_score',)

class VideoTopicInline(admin.TabularInline):
    model = VideoTopic
    extra = 0
    fields = ('topic_name', 'confidence_score', 'modeling_method')
    ordering = ('-confidence_score',)

class VideoFrameFeatureInline(admin.TabularInline):
    model = VideoFrameFeature
    extra = 0
    fields = ('timestamp_ms', 'feature_type', 'feature_data_preview')
    readonly_fields = ('feature_data_preview',)
    ordering = ('timestamp_ms',)

    def feature_data_preview(self, obj):
        if obj.feature_data_json:
            # Preview just a snippet of the JSON to keep inline clean
            preview = str(obj.feature_data_json)[:100]
            return (preview + '...') if len(str(obj.feature_data_json)) > 100 else preview
        return "N/A"
    feature_data_preview.short_description = "Feature Data"


class EditTaskInline(admin.TabularInline):
    model = EditTask
    extra = 0
    fields = ('id', 'prompt_text_preview', 'status', 'result_media_path', 'created_at', 'updated_at')
    readonly_fields = ('id', 'created_at', 'updated_at', 'prompt_text_preview')
    show_change_link = True
    ordering = ('-created_at',)

    def prompt_text_preview(self, obj):
        if obj.prompt_text:
            return (obj.prompt_text[:100] + '...') if len(obj.prompt_text) > 100 else obj.prompt_text
        return "N/A"
    prompt_text_preview.short_description = "Prompt Preview"


# --- ModelAdmins ---
# These classes customize the Django admin interface for each model.

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'duration_seconds', 'publication_date', 'category', 'deduplication_hash', 'created_at', 'updated_at')
    list_filter = ('category', 'publication_date', 'created_at')
    search_fields = ('title', 'description', 'deduplication_hash', 'id')
    date_hierarchy = 'publication_date' # Useful for navigating by date
    readonly_fields = ('id', 'created_at', 'updated_at', 'deduplication_hash')
    fieldsets = (
        (None, {'fields': ('id', 'title', 'description')}),
        ('Details', {'fields': ('duration_seconds', 'publication_date', 'tags', 'category')}),
        ('Internal', {'fields': ('deduplication_hash', 'created_at', 'updated_at')}),
    )
    inlines = [VideoSourceInline] # Show related VideoSource instances


@admin.register(VideoSource)
class VideoSourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_title_link', 'platform_name', 'platform_video_id', 'processing_status', 'meta_visual_processing_status', 'last_scraped_at', 'last_analyzed_at')
    list_filter = ('platform_name', 'processing_status', 'meta_visual_processing_status', 'last_scraped_at', 'last_analyzed_at')
    search_fields = ('video__title', 'platform_video_id', 'original_url', 'id', 'video__id')
    raw_id_fields = ('video',) # Useful if you have many Video records
    readonly_fields = ('id', 'created_at', 'updated_at', 'last_visual_indexed_at', 'last_analyzed_at')
    list_select_related = ('video',) # Optimize query for list display
    fieldsets = (
        ('Linkage', {'fields': ('video',)}),
        ('Platform Info', {'fields': ('id', 'platform_name', 'platform_video_id', 'original_url', 'embed_url', 'thumbnail_url')}),
        ('Uploader & Stats', {'fields': ('uploader_name', 'uploader_url', 'view_count', 'like_count', 'comment_count')}),
        ('Processing', {'fields': ('processing_status', 'processing_error_message', 'meta_visual_processing_status', 'meta_visual_processing_error')}),
        ('Timestamps', {'fields': ('last_scraped_at', 'last_analyzed_at', 'last_visual_indexed_at', 'created_at', 'updated_at')}),
    )
    inlines = [TranscriptInline, ExtractedKeywordInline, VideoTopicInline, VideoFrameFeatureInline]
    actions = ['mark_analysis_complete', 'reset_processing_status']

    def video_title_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if obj.video:
            link = reverse("admin:api_video_change", args=[obj.video.id])
            return format_html('<a href="{}">{}</a>', link, obj.video.title)
        return "N/A"
    video_title_link.short_description = 'Canonical Video Title'
    video_title_link.admin_order_field = 'video__title'

    def mark_analysis_complete(self, request, queryset):
        updated_count = queryset.update(
            processing_status='analysis_complete', 
            meta_visual_processing_status='visual_processed',
            last_analyzed_at=django_timezone.now(),
            last_visual_indexed_at=django_timezone.now(),
            processing_error_message=None,
            meta_visual_processing_error=None
        )
        self.message_user(request, f"{updated_count} video sources marked as analysis complete.")
    mark_analysis_complete.short_description = "Mark selected as 'Analysis Complete'"

    def reset_processing_status(self, request, queryset):
        updated_count = queryset.update(
            processing_status='pending', 
            meta_visual_processing_status='pending',
            last_analyzed_at=None,
            last_visual_indexed_at=None,
            processing_error_message=None,
            meta_visual_processing_error=None
        )
        self.message_user(request, f"{updated_count} video sources reset to 'Pending' status.")
    reset_processing_status.short_description = "Reset processing status to 'Pending'"


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_info', 'language_code', 'source_type', 'content_preview', 'updated_at')
    list_filter = ('language_code', 'source_type', 'updated_at')
    search_fields = ('video_source__video__title', 'video_source__platform_video_id', 'full_text_content', 'id')
    raw_id_fields = ('video_source',)
    readonly_fields = ('id', 'created_at', 'updated_at')
    list_select_related = ('video_source__video',)

    def video_source_info(self, obj):
        if obj.video_source and obj.video_source.video:
            return f"VSID: {obj.video_source.id} (Video: {obj.video_source.video.title[:30]}...)"
        return str(obj.video_source_id)
    video_source_info.short_description = 'Video Source'

    def content_preview(self, obj):
        if obj.full_text_content:
            return (obj.full_text_content[:100] + '...') if len(obj.full_text_content) > 100 else obj.full_text_content
        return "N/A"
    content_preview.short_description = 'Content Preview'


@admin.register(ExtractedKeyword)
class ExtractedKeywordAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_id_link', 'keyword_text', 'relevance_score', 'source_field', 'created_at')
    list_filter = ('source_field', 'created_at')
    search_fields = ('keyword_text', 'video_source__id', 'video_source__video__title')
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('video_source',)
    list_select_related = ('video_source',)

    def video_source_id_link(self, obj):
         from django.urls import reverse
         from django.utils.html import format_html
         if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">{}</a>', link, obj.video_source.id)
         return "N/A"
    video_source_id_link.short_description = 'VideoSource ID'

@admin.register(VideoTopic)
class VideoTopicAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_id_link', 'topic_name', 'confidence_score', 'modeling_method', 'created_at')
    list_filter = ('modeling_method', 'created_at')
    search_fields = ('topic_name', 'video_source__id', 'video_source__video__title')
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('video_source',)

    def video_source_id_link(self, obj): # Duplicated from ExtractedKeywordAdmin - could be a mixin
         from django.urls import reverse
         from django.utils.html import format_html
         if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">{}</a>', link, obj.video_source.id)
         return "N/A"
    video_source_id_link.short_description = 'VideoSource ID'

@admin.register(VideoFrameFeature)
class VideoFrameFeatureAdmin(admin.ModelAdmin):
    list_display = ('id', 'video_source_id_link', 'timestamp_ms', 'feature_type', 'data_preview', 'created_at')
    list_filter = ('feature_type', 'created_at')
    search_fields = ('video_source__id', 'video_source__video__title', 'feature_data_json') # Search in JSON data
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('video_source',)
    list_per_page = 25

    def video_source_id_link(self, obj): # Duplicated - make a mixin
         from django.urls import reverse
         from django.utils.html import format_html
         if obj.video_source:
            link = reverse("admin:api_videosource_change", args=[obj.video_source.id])
            return format_html('<a href="{}">{}</a>', link, obj.video_source.id)
         return "N/A"
    video_source_id_link.short_description = 'VideoSource ID'

    def data_preview(self, obj):
        if obj.feature_data_json:
            preview = str(obj.feature_data_json)
            return (preview[:75] + '...') if len(preview) > 75 else preview
        return "N/A"
    data_preview.short_description = 'Feature Data'


class UserProfileInline(admin.StackedInline): # Or TabularInline
    model = UserProfile
    can_delete = False # Usually don't want to delete UserProfile when deleting User
    verbose_name_plural = 'Profile'
    fk_name = 'user'
    fields = ('subscription_plan', 'subscription_expiry_date', 'remaining_trial_searches')


# Extend the default User admin to include UserProfile
class CustomUserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_subscription_plan')
    list_select_related = ('profile',) # For get_subscription_plan optimization

    def get_subscription_plan(self, instance):
        try:
            return instance.profile.subscription_plan
        except UserProfile.DoesNotExist:
            return 'N/A'
    get_subscription_plan.short_description = 'Subscription Plan'

    def get_inline_instances(self, request, obj=None):
        if not obj: # No inlines on user creation page
            return []
        return super().get_inline_instances(request, obj)

# Unregister the original User admin if it's registered by default
if admin.site.is_registered(User):
    admin.site.unregister(User)
# Register the User model with our custom admin
admin.site.register(User, CustomUserAdmin)


@admin.register(SearchTask)
class SearchTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_email', 'query_text_preview', 'query_image_ref_exists', 'status', 'celery_task_id', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'user')
    search_fields = ('id', 'user__email', 'user__username', 'query_text', 'celery_task_id')
    readonly_fields = ('id', 'user', 'session_id', 'query_text', 'query_image_ref', 'query_image_fingerprint', 'query_video_url',
                       'applied_filters_json', 'celery_task_id', 'result_video_ids_json', 'detailed_results_info_json_pretty',
                       'created_at', 'updated_at')
    list_per_page = 25
    ordering = ('-created_at',)

    def user_email(self, obj):
        return obj.user.email if obj.user else "Anonymous"
    user_email.short_description = "User Email"
    user_email.admin_order_field = 'user__email'

    def query_text_preview(self, obj):
        if obj.query_text:
            return (obj.query_text[:75] + '...') if len(obj.query_text) > 75 else obj.query_text
        return "N/A"
    query_text_preview.short_description = "Query Text"
    
    def query_image_ref_exists(self, obj):
        return bool(obj.query_image_ref)
    query_image_ref_exists.short_description = "Image Query?"
    query_image_ref_exists.boolean = True

    def detailed_results_info_json_pretty(self, obj):
        import json
        from django.utils.html import format_html
        if obj.detailed_results_info_json:
            pretty_json = json.dumps(obj.detailed_results_info_json, indent=2)
            return format_html("<pre>{}</pre>", pretty_json)
        return "N/A"
    detailed_results_info_json_pretty.short_description = "Detailed Results (Formatted)"


@admin.register(SignupCode)
class SignupCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'code', 'plan_name', 'is_used', 'used_by_email', 'is_expired', 'expires_at', 'created_at')
    list_filter = ('is_used', 'plan_name', 'expires_at', 'created_at')
    search_fields = ('id', 'email', 'code', 'used_by__email')
    readonly_fields = ('id', 'created_at', 'updated_at', 'used_at')
    actions = ['mark_as_used', 'mark_as_unused']
    
    def used_by_email(self, obj):
        return obj.used_by.email if obj.used_by else "N/A"
    used_by_email.short_description = "Used By"

    def mark_as_used(self, request, queryset):
        # Note: Doesn't assign a user, just marks the flag. Real usage flow is via ActivateAccountView.
        updated_count = queryset.update(is_used=True, used_at=django_timezone.now())
        self.message_user(request, f"{updated_count} signup codes marked as used.")
    mark_as_used.short_description = "Mark selected codes as USED"

    def mark_as_unused(self, request, queryset):
        updated_count = queryset.update(is_used=False, used_at=None, used_by=None)
        self.message_user(request, f"{updated_count} signup codes marked as UNUSED.")
    mark_as_unused.short_description = "Mark selected codes as UNUSED"


@admin.register(VideoEditProject)
class VideoEditProjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_email', 'project_name', 'original_video_source_id_link', 'uploaded_video_name', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('id', 'project_name', 'user__email', 'original_video_source__id', 'uploaded_video_name')
    raw_id_fields = ('user', 'original_video_source')
    readonly_fields = ('id', 'created_at', 'updated_at')
    inlines = [EditTaskInline]
    ordering = ('-created_at',)

    def user_email(self, obj):
        return obj.user.email if obj.user else "N/A"
    user_email.short_description = "User"

    def original_video_source_id_link(self, obj):
         from django.urls import reverse
         from django.utils.html import format_html
         if obj.original_video_source:
            link = reverse("admin:api_videosource_change", args=[obj.original_video_source.id])
            return format_html('<a href="{}">VSID: {}</a>', link, obj.original_video_source.id)
         return "N/A"
    original_video_source_id_link.short_description = 'Original VideoSource'


@admin.register(EditTask)
class EditTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'project_link', 'prompt_preview', 'status', 'celery_task_id', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('id', 'project__project_name', 'project__user__email', 'prompt_text', 'celery_task_id')
    raw_id_fields = ('project',)
    readonly_fields = ('id', 'celery_task_id', 'created_at', 'updated_at', 'result_media_path', 'result_preview_url', 'error_message')
    list_select_related = ('project__user',)
    ordering = ('-created_at',)

    def project_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if obj.project:
            link = reverse("admin:api_videoeditproject_change", args=[obj.project.id])
            return format_html('<a href="{}">Project {} ({})</a>', link, obj.project.id, obj.project.project_name[:20])
        return "N/A"
    project_link.short_description = 'Edit Project'

    def prompt_preview(self, obj):
        if obj.prompt_text:
            return (obj.prompt_text[:75] + '...') if len(obj.prompt_text) > 75 else obj.prompt_text
        return "N/A"
    prompt_preview.short_description = "Prompt"

# Note: For UserProfile to appear under the User admin, the User model itself
# needs to be re-registered with an admin class that includes UserProfileInline.
# This was done above with CustomUserAdmin.
