# backend/api/management/commands/indexvideosvisual.py
import logging
import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone

from api.models import VideoSource
from api.analyzer_instances import get_visual_analyzer # Assuming VisualAnalyzer is globally accessible
from backend.ai_agents.content_analysis_agent import ContentAnalysisAgent # For download logic if needed

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Manually triggers visual indexing for specified VideoSource entries or all pending ones.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--video_source_ids',
            nargs='*', # 0 or more
            type=int,
            help='Specific VideoSource IDs to process. If not provided, processes all pending.',
        )
        parser.add_argument(
            '--all_pending',
            action='store_true',
            help='Process all VideoSource entries currently in a pending visual state.',
        )
        parser.add_argument(
            '--reindex_all_processed',
            action='store_true',
            help='Re-index all VideoSource entries already marked as visually processed (use with caution).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0, # 0 means no limit unless --all_pending or --video_source_ids is used
            help='Limit the number of videos to process (useful with --all_pending or --reindex_all_processed).'
        )
        parser.add_argument(
            '--force_download',
            action='store_true',
            help='Force re-download of video files even if a local path seems to exist (use with caution).',
        )

    def handle(self, *args, **options):
        visual_analyzer = get_visual_analyzer()
        if not visual_analyzer:
            raise CommandError("VisualAnalyzer is not available. Check AI agent initialization.")

        video_source_ids = options['video_source_ids']
        all_pending = options['all_pending']
        reindex_all_processed = options['reindex_all_processed']
        limit = options['limit']
        force_download = options['force_download']

        queryset = VideoSource.objects.select_related('video').all()

        if video_source_ids:
            self.stdout.write(f"Processing specified VideoSource IDs: {video_source_ids}")
            queryset = queryset.filter(id__in=video_source_ids)
        elif all_pending:
            self.stdout.write("Processing all VideoSource entries pending visual indexing...")
            # Define what 'pending' means based on your VideoSource.meta_visual_processing_status choices
            pending_statuses = ['pending', 'download_failed', 'analysis_failed', 'error_unexpected']
            queryset = queryset.filter(meta_visual_processing_status__in=pending_statuses)
        elif reindex_all_processed:
            self.stdout.write(self.style.WARNING("Re-indexing all visually processed VideoSource entries..."))
            processed_statuses = ['completed', 'visual_processed'] # Based on your model choices
            queryset = queryset.filter(meta_visual_processing_status__in=processed_statuses)
        else:
            self.stdout.write(self.style.ERROR("No action specified. Use --video_source_ids, --all_pending, or --reindex_all_processed."))
            return

        if limit > 0:
            queryset = queryset[:limit]

        if not queryset.exists():
            self.stdout.write(self.style.SUCCESS("No VideoSources found matching the criteria to process."))
            return

        self.stdout.write(f"Found {queryset.count()} VideoSources to process for visual indexing.")
        
        # Instantiate CAAgent for its download logic if needed
        ca_agent = ContentAnalysisAgent() # For _download_video_if_needed

        processed_count = 0
        failed_count = 0

        for vs in queryset:
            self.stdout.write(f"Processing VideoSource ID: {vs.id} - {vs.video.title[:50] if vs.video else 'N/A'}...")
            
            local_video_path = None
            temp_download_dir_to_cleanup = None

            # Try to get local_file_path from raw_video_item_data if it's stored or construct it
            # This part depends on how your 'raw_video_item_data' is structured or if video files are managed
            # For this command, we'll primarily rely on downloading if no obvious path.
            
            if vs.original_url:
                if force_download:
                    vs.meta_visual_processing_status = 'downloading' # Mark for download
                    vs.save(update_fields=['meta_visual_processing_status'])
                
                # Attempt download if forced or if no clear local path and status suggests it's needed
                if force_download or vs.meta_visual_processing_status in ['pending', 'download_failed']:
                    self.stdout.write(f"  Attempting to download video for VSID {vs.id} from {vs.original_url}...")
                    local_video_path = ca_agent._download_video_if_needed(vs.original_url, vs.id)
                    if local_video_path:
                        temp_download_dir_to_cleanup = os.path.dirname(local_video_path)
                        self.stdout.write(self.style.SUCCESS(f"  Downloaded video to: {local_video_path}"))
                        vs.meta_visual_processing_status = 'downloaded' # Dummy status, VA will set 'indexing'
                    else:
                        self.stdout.write(self.style.ERROR(f"  Failed to download video for VSID {vs.id}."))
                        vs.meta_visual_processing_status = 'download_failed'
                        vs.meta_visual_processing_error = "Download failed via management command."
                        vs.save(update_fields=['meta_visual_processing_status', 'meta_visual_processing_error'])
                        failed_count += 1
                        continue # Skip to next video source
                elif os.path.exists(str(vs.processing_error_message)): # Example: if error message was used to store a path previously
                     local_video_path = str(vs.processing_error_message) # Bad practice, just an example
            
            if not local_video_path:
                # Fallback: If your VideoSource model has a field like 'local_file_path'
                # if hasattr(vs, 'local_file_path_field') and getattr(vs, 'local_file_path_field'):
                #    local_video_path = os.path.join(settings.MEDIA_ROOT, getattr(vs, 'local_file_path_field'))
                # else:
                self.stdout.write(self.style.WARNING(f"  No local video path available or derivable for VSID {vs.id} and not forced to download. Skipping visual analysis."))
                if vs.meta_visual_processing_status == 'pending':
                    vs.meta_visual_processing_status = 'skipped_no_file'
                    vs.save(update_fields=['meta_visual_processing_status'])
                failed_count += 1
                continue

            if not os.path.exists(local_video_path):
                self.stdout.write(self.style.ERROR(f"  Local video path {local_video_path} does not exist for VSID {vs.id}. Skipping."))
                vs.meta_visual_processing_status = 'skipped_no_file'
                vs.meta_visual_processing_error = "Derived local file path not found."
                vs.save(update_fields=['meta_visual_processing_status','meta_visual_processing_error'])
                failed_count += 1
                continue

            try:
                vs.meta_visual_processing_status = 'indexing' # Use 'indexing' from VISUAL_DETAIL_STATUS_CHOICES
                vs.meta_visual_processing_error = None
                vs.save(update_fields=['meta_visual_processing_status', 'meta_visual_processing_error'])

                analysis_summary = visual_analyzer.process_video_frames(
                    video_source_model=vs,
                    video_file_path=local_video_path,
                    # frame_interval_sec can be a setting
                )

                if analysis_summary.get("errors"):
                    vs.meta_visual_processing_status = 'analysis_failed'
                    vs.meta_visual_processing_error = "; ".join(analysis_summary["errors"][:2])
                    failed_count += 1
                    self.stdout.write(self.style.ERROR(f"  Visual analysis failed for VSID {vs.id}: {vs.meta_visual_processing_error}"))
                else:
                    vs.meta_visual_processing_status = 'completed' # 'completed' from VISUAL_DETAIL_STATUS_CHOICES
                    vs.last_visual_indexed_at = timezone.now()
                    processed_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  Successfully indexed visuals for VSID {vs.id}. Frames processed: {analysis_summary.get('frames_processed_for_features',0)}, Qdrant points: {analysis_summary.get('qdrant_points_stored',0)}"))
                
                vs.save(update_fields=['meta_visual_processing_status', 'meta_visual_processing_error', 'last_visual_indexed_at'])

            except Exception as e:
                logger.error(f"Unhandled error during visual indexing for VSID {vs.id}: {e}", exc_info=True)
                vs.meta_visual_processing_status = 'error_unexpected'
                vs.meta_visual_processing_error = f"Unexpected error: {str(e)[:200]}"
                vs.save(update_fields=['meta_visual_processing_status', 'meta_visual_processing_error'])
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"  Unexpected error indexing VSID {vs.id}: {e}"))
            finally:
                if temp_download_dir_to_cleanup and os.path.exists(temp_download_dir_to_cleanup):
                    try:
                        shutil.rmtree(temp_download_dir_to_cleanup)
                        self.stdout.write(f"  Cleaned up temp download directory: {temp_download_dir_to_cleanup}")
                    except Exception as e_clean:
                        self.stderr.write(self.style.WARNING(f"  Could not clean up temp dir {temp_download_dir_to_cleanup}: {e_clean}"))


        self.stdout.write(self.style.SUCCESS(f"Visual indexing command finished. Processed: {processed_count}, Failed/Skipped: {failed_count}."))
