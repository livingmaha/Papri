# backend/ai_agents/result_aggregation_agent.py
import logging
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone # Use timezone explicitly for awareness
from typing import List, Dict, Any, Tuple, Optional

from django.conf import settings
from django.db.models import Q as db_Q # For complex Django ORM lookups
from qdrant_client import QdrantClient, models as qdrant_models

# Django models (import within methods if causing circular issues, or manage carefully)
from api.models import Video, VideoSource, Transcript, ExtractedKeyword, VideoFrameFeature

from .utils import normalize_text_unicode, generate_deduplication_hash # Import utility

logger = logging.getLogger(__name__)

# Constants for scoring (these should be configurable, perhaps from Django settings)
TEXT_QUERY_EMBEDDING_WEIGHT = 0.6
VISUAL_QUERY_EMBEDDING_WEIGHT = 0.7
KEYWORD_MATCH_WEIGHT = 0.3
VISUAL_HASH_MATCH_WEIGHT = 0.4 # If using perceptual hashes for ranking
RECENCY_WEIGHT = 0.1 # Score multiplier based on recency
PLATFORM_PREFERENCE_BOOST = 0.05 # Small boost for preferred platforms
MIN_RELEVANCE_SCORE_THRESHOLD = 0.1 # Minimum score to be included in results


class ResultAggregationAgent:
    def __init__(self):
        self.qdrant_url = settings.QDRANT_URL
        self.qdrant_api_key = settings.QDRANT_API_KEY
        self.qdrant_collection_transcripts = settings.QDRANT_COLLECTION_TRANSCRIPTS
        self.qdrant_collection_visual = settings.QDRANT_COLLECTION_VISUAL
        
        try:
            self.qdrant_client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key, timeout=15)
            # Test connection by trying to get collection info (optional)
            # self.qdrant_client.get_collection(collection_name=self.qdrant_collection_transcripts)
            # self.qdrant_client.get_collection(collection_name=self.qdrant_collection_visual)
            logger.info("Qdrant client initialized successfully for RARAgent.")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client for RARAgent: {e}", exc_info=True)
            self.qdrant_client = None
            
        logger.info("ResultAggregationAgent initialized.")

    def _semantic_search_transcripts(self, query_text_embedding: List[float], top_k: int = 20, search_filters: Optional[qdrant_models.Filter] = None) -> List[qdrant_models.ScoredPoint]:
        """Performs semantic search in the Qdrant transcript collection."""
        if not self.qdrant_client or not query_text_embedding:
            return []
        try:
            logger.debug(f"RARAgent: Searching Qdrant transcripts. Top_k: {top_k}, Filters: {search_filters}")
            search_results = self.qdrant_client.search(
                collection_name=self.qdrant_collection_transcripts,
                query_vector=query_text_embedding,
                query_filter=search_filters, # Optional: filter by video_source_db_id, etc.
                limit=top_k,
                with_payload=True # We need payload to get video_source_db_id and text
            )
            logger.debug(f"RARAgent: Qdrant transcript search returned {len(search_results)} points.")
            return search_results
        except Exception as e:
            logger.error(f"Error during Qdrant transcript search: {e}", exc_info=True)
            return []

    def _semantic_search_visual(self, query_visual_embedding: List[float], top_k: int = 20, search_filters: Optional[qdrant_models.Filter] = None) -> List[qdrant_models.ScoredPoint]:
        """Performs semantic search in the Qdrant visual collection."""
        if not self.qdrant_client or not query_visual_embedding:
            return []
        try:
            logger.debug(f"RARAgent: Searching Qdrant visual. Top_k: {top_k}, Filters: {search_filters}")
            search_results = self.qdrant_client.search(
                collection_name=self.qdrant_collection_visual,
                query_vector=query_visual_embedding,
                query_filter=search_filters,
                limit=top_k,
                with_payload=True # We need video_source_db_id, timestamp_ms
            )
            logger.debug(f"RARAgent: Qdrant visual search returned {len(search_results)} points.")
            return search_results
        except Exception as e:
            logger.error(f"Error during Qdrant visual search: {e}", exc_info=True)
            return []

    def _calculate_recency_score(self, publication_date: Optional[datetime]) -> float:
        """Calculates a recency score (0.0 to 1.0), higher for more recent dates."""
        if not publication_date:
            return 0.5 # Neutral score if no date

        # Ensure publication_date is offset-aware for correct comparison with timezone.now()
        if publication_date.tzinfo is None or publication_date.tzinfo.utcoffset(publication_date) is None:
            # Assume UTC if naive, or use Django's default timezone if configured
            # For simplicity, let's assume UTC if naive. For Django projects, use settings.TIME_ZONE
            publication_date = publication_date.replace(tzinfo=dt_timezone.utc)

        now = datetime.now(dt_timezone.utc)
        age = now - publication_date
        
        if age.days < 0: return 1.0 # Future publish date (treat as very recent)
        if age.days <= 7: return 1.0  # Within a week
        if age.days <= 30: return 0.9 # Within a month
        if age.days <= 90: return 0.75 # Within 3 months
        if age.days <= 365: return 0.6 # Within a year
        if age.days <= (365 * 2): return 0.4 # Within 2 years
        return 0.2 # Older than 2 years

    def _apply_filters(self, video_source_queryset, user_filters: Dict[str, Any]):
        """
        Applies user-defined filters to a Django queryset of VideoSource objects.
        `user_filters` example: {'platform': ['youtube', 'vimeo'], 'min_duration_sec': 60, 'max_duration_sec': 600,
                                'upload_date_after': '2023-01-01', 'upload_date_before': '2023-12-31'}
        """
        if not user_filters:
            return video_source_queryset

        q_objects = db_Q()

        if 'platform' in user_filters and isinstance(user_filters['platform'], list) and user_filters['platform']:
            q_objects &= db_Q(platform_name__in=user_filters['platform'])
        
        # Accessing duration from the related Video object
        if 'min_duration_sec' in user_filters and user_filters['min_duration_sec'] is not None:
            q_objects &= db_Q(video__duration_seconds__gte=user_filters['min_duration_sec'])
        if 'max_duration_sec' in user_filters and user_filters['max_duration_sec'] is not None:
            q_objects &= db_Q(video__duration_seconds__lte=user_filters['max_duration_sec'])
        
        # Accessing publication_date from the related Video object
        if 'upload_date_after' in user_filters and user_filters['upload_date_after']:
            try:
                date_after = datetime.fromisoformat(user_filters['upload_date_after']).replace(tzinfo=dt_timezone.utc)
                q_objects &= db_Q(video__publication_date__gte=date_after)
            except ValueError:
                logger.warning(f"Invalid 'upload_date_after' format: {user_filters['upload_date_after']}")
        if 'upload_date_before' in user_filters and user_filters['upload_date_before']:
            try:
                date_before = datetime.fromisoformat(user_filters['upload_date_before']).replace(tzinfo=dt_timezone.utc)
                q_objects &= db_Q(video__publication_date__lte=date_before)
            except ValueError:
                logger.warning(f"Invalid 'upload_date_before' format: {user_filters['upload_date_before']}")
        
        # Add more filters as needed: category, uploader, etc.
        # if 'category' in user_filters:
        #     q_objects &= db_Q(video__category__iexact=user_filters['category'])

        logger.debug(f"RARAgent: Applying DB filters: {q_objects}")
        return video_source_queryset.filter(q_objects) if q_objects else video_source_queryset
        

    def aggregate_and_rank_results(
        self,
        processed_query_data: Dict[str, Any],
        # List of VideoSource objects fetched in current session (optional, can be empty if only searching index)
        # current_session_video_sources: List[VideoSource], # Not directly used if relying on Qdrant + DB query
        user_filters: Dict[str, Any] = None,
        user_preferences: Dict[str, Any] = None # e.g., {'preferred_platforms': ['youtube']}
    ) -> List[Dict[str, Any]]:
        """
        Aggregates results from various analyses (Qdrant semantic search, keyword matches),
        deduplicates, applies filters, ranks them, and prepares them for presentation.

        `processed_query_data` comes from QAgent.
        `user_filters` are from the user's search form.
        `user_preferences` could come from UserProfile.

        Returns a list of dicts, where each dict is a ranked canonical Video
        with its best matching source and relevant details.
        """
        logger.info(f"RARAgent: Starting aggregation and ranking. Query intent: {processed_query_data.get('intent')}")
        if user_filters: logger.debug(f"RARAgent: User filters received: {user_filters}")
        if user_preferences: logger.debug(f"RARAgent: User preferences: {user_preferences}")

        # --- 1. Gather Candidate Videos ---
        # This involves querying Qdrant (for semantic matches) and potentially
        # your relational DB (for keyword matches, metadata filters).
        
        candidate_video_source_scores = defaultdict(lambda: {"score": 0.0, "match_types": set(), "details": {}})
        # `details` will store things like best_match_timestamp_ms, relevant_text_snippet per source

        # a) Semantic Search (Text)
        query_text_embedding = processed_query_data.get('text_component', {}).get('text_embedding') or \
                               processed_query_data.get('text_embedding') # For direct text query
        if query_text_embedding:
            # TODO: Construct Qdrant filter based on user_filters if applicable at Qdrant level
            # This is complex as user_filters apply to Django models, not directly Qdrant payload unless payload is designed for it.
            # For now, Qdrant search is broad, Django filters later.
            transcript_hits = self._semantic_search_transcripts(query_text_embedding, top_k=50)
            for hit in transcript_hits:
                vs_db_id = hit.payload.get("video_source_db_id")
                if vs_db_id:
                    candidate_video_source_scores[vs_db_id]["score"] += hit.score * TEXT_QUERY_EMBEDDING_WEIGHT
                    candidate_video_source_scores[vs_db_id]["match_types"].add("transcript_semantic")
                    candidate_video_source_scores[vs_db_id]["details"]["relevant_text_snippet"] = hit.payload.get("text_content", "")[:200] + "..." # Example snippet
                    # If transcript segments have timestamps, add best_match_timestamp_ms here

        # b) Semantic Search (Visual)
        query_visual_embedding = processed_query_data.get('image_component', {}).get('visual_cnn_embedding') or \
                                 processed_query_data.get('visual_cnn_embedding') # For direct image query
        if query_visual_embedding:
            visual_hits = self._semantic_search_visual(query_visual_embedding, top_k=50)
            for hit in visual_hits:
                vs_db_id = hit.payload.get("video_source_db_id")
                if vs_db_id:
                    candidate_video_source_scores[vs_db_id]["score"] += hit.score * VISUAL_QUERY_EMBEDDING_WEIGHT
                    candidate_video_source_scores[vs_db_id]["match_types"].add("visual_semantic_cnn")
                    candidate_video_source_scores[vs_db_id]["details"]["best_match_timestamp_ms"] = hit.payload.get("timestamp_ms")

        # c) Keyword-based Search (from DB)
        # If query has keywords, search ExtractedKeyword model
        keywords = processed_query_data.get('text_component', {}).get('keywords') or \
                   processed_query_data.get('keywords', [])
        if keywords:
            keyword_q_objects = db_Q()
            for kw in keywords:
                keyword_q_objects |= db_Q(keyword_text__icontains=kw) # Simple OR for keywords
            
            if keyword_q_objects:
                # Find VideoSource IDs that have these keywords
                # Limit this query to avoid fetching too many; perhaps top N by relevance_score if available
                keyword_matched_vs_ids = ExtractedKeyword.objects.filter(keyword_q_objects)\
                                        .values_list('video_source_id', flat=True).distinct()[:200] # Limit initial pool
                
                for vs_id in keyword_matched_vs_ids:
                    candidate_video_source_scores[vs_id]["score"] += KEYWORD_MATCH_WEIGHT # Simple boost, can be weighted by keyword relevance
                    candidate_video_source_scores[vs_id]["match_types"].add("transcript_keyword")
                    # Snippet generation for keyword matches is more complex, requires fetching transcript and finding KWIC.
                    # For now, semantic snippet might be used if also a semantic hit.

        # d) Visual Hash Matching (from DB) - If query was an image
        # query_image_hashes = processed_query_data.get('image_component',{}).get('image_fingerprints', {})
        # if query_image_hashes and query_image_hashes.get('phash'):
        #     # Search VideoFrameFeature for matching phash (or other hashes)
        #     # This requires an efficient way to compare hashes (e.g., Hamming distance)
        #     # For simplicity, assume exact phash match here.
        #     hash_matched_frames = VideoFrameFeature.objects.filter(
        #         feature_type='perceptual_hash',
        #         feature_data_json__phash=query_image_hashes['phash'] # Exact match on phash (example)
        #     ).select_related('video_source').values_list('video_source_id', 'timestamp_ms')[:50]
            
        #     for vs_id, timestamp_ms in hash_matched_frames:
        #         candidate_video_source_scores[vs_id]["score"] += VISUAL_HASH_MATCH_WEIGHT
        #         candidate_video_source_scores[vs_id]["match_types"].add("visual_hash_match")
        #         candidate_video_source_scores[vs_id]["details"]["best_match_timestamp_ms"] = \
        #             min(timestamp_ms, candidate_video_source_scores[vs_id]["details"].get("best_match_timestamp_ms", float('inf')))


        # --- 2. Filter Candidate VideoSources based on DB properties & User Filters ---
        # Get all unique VideoSource IDs from candidates
        all_candidate_vs_ids = list(candidate_video_source_scores.keys())
        if not all_candidate_vs_ids:
            logger.info("RARAgent: No candidate videos found after initial search phase.")
            return []

        # Fetch VideoSource objects from DB, prefetching related Video for filtering and display
        # Only fetch those that are 'analysis_complete' or a similar ready status
        # And apply user_filters
        video_sources_qs = VideoSource.objects.filter(
            id__in=all_candidate_vs_ids,
            # video__isnull=False, # Ensure canonical video link exists
            # processing_status='analysis_complete' # Or similar status indicating it's ready for display
        ).select_related('video') # Important: select_related 'video' for filtering and data access

        filtered_video_sources_qs = self._apply_filters(video_sources_qs, user_filters)
        
        # Filter candidate_video_source_scores to only include those that passed DB filters
        valid_filtered_vs_ids = set(filtered_video_sources_qs.values_list('id', flat=True))
        
        filtered_candidate_scores = {
            vs_id: data for vs_id, data in candidate_video_source_scores.items() if vs_id in valid_filtered_vs_ids
        }
        
        if not filtered_candidate_scores:
            logger.info("RARAgent: No candidate videos remaining after applying DB filters.")
            return []
            
        # Map VideoSource objects by ID for easy access
        video_source_map = {vs.id: vs for vs in filtered_video_sources_qs}

        # --- 3. Consolidate Scores to Canonical Videos & Deduplication ---
        # Group VideoSources by their canonical Video ID and aggregate scores.
        canonical_video_scores = defaultdict(lambda: {"total_score": 0.0, "sources": [], "match_types": set(), "best_source_details": None})

        for vs_id, data in filtered_candidate_scores.items():
            video_source_obj = video_source_map.get(vs_id)
            if not video_source_obj or not video_source_obj.video: continue # Should not happen if qs is correct

            canonical_video_id = video_source_obj.video.id
            
            # Apply recency score to this source's contribution
            recency_score_multiplier = 1.0 + (self._calculate_recency_score(video_source_obj.video.publication_date) * RECENCY_WEIGHT)
            
            # Platform preference boost
            if user_preferences and video_source_obj.platform_name in user_preferences.get('preferred_platforms', []):
                recency_score_multiplier += PLATFORM_PREFERENCE_BOOST

            source_final_score = data["score"] * recency_score_multiplier
            
            # Aggregate to canonical video
            canonical_video_scores[canonical_video_id]["total_score"] = max(
                canonical_video_scores[canonical_video_id]["total_score"], # Take the max score from its sources
                source_final_score 
            )
            canonical_video_scores[canonical_video_id]["match_types"].update(data["match_types"])
            
            current_source_info = {
                "video_source_id": vs_id,
                "platform_name": video_source_obj.platform_name,
                "platform_video_id": video_source_obj.platform_video_id,
                "original_url": video_source_obj.original_url,
                "match_score": source_final_score, # Store the source-specific score after boosts
                "match_type_tags": list(data["match_types"]), # Source specific match types
                **data["details"] # Snippet, timestamp for this source
            }
            canonical_video_scores[canonical_video_id]["sources"].append(current_source_info)

            # Update best_source_details for the canonical video if this source is better
            if canonical_video_scores[canonical_video_id]["best_source_details"] is None or \
               source_final_score > canonical_video_scores[canonical_video_id]["best_source_details"]["match_score"]:
                canonical_video_scores[canonical_video_id]["best_source_details"] = current_source_info

        # --- 4. Rank Canonical Videos ---
        # Sort canonical videos by their aggregated total_score
        ranked_canonical_videos_data = sorted(
            [{"video_id": vid, **data} for vid, data in canonical_video_scores.items() if data["total_score"] >= MIN_RELEVANCE_SCORE_THRESHOLD],
            key=lambda x: x["total_score"],
            reverse=True
        )
        
        # Limit final results (e.g., top 50-100 overall)
        ranked_canonical_videos_data = ranked_canonical_videos_data[:100] 
        
        # --- 5. Prepare final output structure for SearchTask.detailed_results_info_json ---
        # This structure should be what SearchResultsView expects to build its response.
        # It's a list of dicts, each representing a canonical video and its best source info.
        output_results_for_task = []
        for ranked_video_data in ranked_canonical_videos_data:
            output_item = {
                "video_id": ranked_video_data["video_id"], # Canonical Video ID
                "combined_score": round(ranked_video_data["total_score"], 4),
                "match_types": list(ranked_video_data["match_types"]), # Overall match types for this canonical video
                "best_source": ranked_video_data["best_source_details"], # Dict of the best source's details
                # "all_contributing_sources": ranked_video_data["sources"] # Optionally include all sources info
            }
            output_results_for_task.append(output_item)

        logger.info(f"RARAgent: Aggregation complete. Returning {len(output_results_for_task)} ranked canonical videos.")
        return output_results_for_task
