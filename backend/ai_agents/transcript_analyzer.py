# backend/ai_agents/transcript_analyzer.py
import logging
import re
import spacy
import gensim # type: ignore
from gensim import corpora
from gensim.models import LdaModel # TfidfModel
from sentence_transformers import SentenceTransformer # type: ignore
from nltk.tokenize import word_tokenize # type: ignore
from nltk.corpus import stopwords # type: ignore
import nltk # NLTK for stop words and tokenization
import requests # For fetching VTT from URL

from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models, QdrantClientException # Renamed to avoid conflict

# Import Django models (use with caution at module level, or import within methods)
# from api.models import Transcript, ExtractedKeyword, VideoTopic # Moved to method scope

from .utils import clean_text, normalize_text_unicode # Assuming utils.py is in the same package

logger = logging.getLogger(__name__)

# Download NLTK resources if not already present (run this once during setup)
try:
    stopwords.words('english')
    nltk.data.find('tokenizers/punkt')
except LookupError:
    logger.info("NLTK 'stopwords' or 'punkt' not found. Downloading...")
    nltk.download('stopwords', quiet=True)
    nltk.download('punkt', quiet=True)


class TranscriptAnalyzer:
    def __init__(self):
        self.nlp_model_name = getattr(settings, 'SPACY_MODEL_NAME', "en_core_web_sm")
        self.sentence_transformer_model_name = settings.SENTENCE_TRANSFORMER_MODEL
        
        self.qdrant_host = settings.QDRANT_HOST
        self.qdrant_port = settings.QDRANT_PORT
        self.qdrant_url = settings.QDRANT_URL # Use the constructed or env-set URL
        self.qdrant_api_key = settings.QDRANT_API_KEY # Can be None
        self.qdrant_prefer_grpc = settings.QDRANT_PREFER_GRPC
        self.qdrant_timeout = settings.QDRANT_TIMEOUT_SECONDS
        self.qdrant_collection_transcripts = settings.QDRANT_TRANSCRIPT_COLLECTION_NAME
        self.text_embedding_dim = settings.TEXT_EMBEDDING_DIMENSION

        try:
            self.nlp = spacy.load(self.nlp_model_name)
            logger.info(f"spaCy model '{self.nlp_model_name}' loaded for TranscriptAnalyzer.")
        except OSError:
            logger.error(f"spaCy model '{self.nlp_model_name}' not found. Download with: python -m spacy download {self.nlp_model_name}", exc_info=True)
            self.nlp = None

        try:
            self.sentence_model = SentenceTransformer(self.sentence_transformer_model_name)
            # Verify embedding dimension from model if possible, or trust setting
            model_dim = self.sentence_model.get_sentence_embedding_dimension()
            if model_dim != self.text_embedding_dim:
                logger.warning(f"SentenceTransformer model '{self.sentence_transformer_model_name}' output dim ({model_dim}) "
                               f"differs from settings.TEXT_EMBEDDING_DIMENSION ({self.text_embedding_dim}). Using model's dimension.")
                self.text_embedding_dim = model_dim # Prioritize actual model dimension
            logger.info(f"SentenceTransformer '{self.sentence_transformer_model_name}' loaded (Dim: {self.text_embedding_dim}).")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer model '{self.sentence_transformer_model_name}': {e}", exc_info=True)
            self.sentence_model = None
            # If model fails, text_embedding_dim might be incorrect or unusable.

        try:
            self.qdrant_client = QdrantClient(
                url=self.qdrant_url, 
                port=self.qdrant_port if not self.qdrant_url.startswith("http") else None, # Port only if host is given
                grpc_port=settings.QDRANT_GRPC_PORT if self.qdrant_prefer_grpc else None,
                prefer_grpc=self.qdrant_prefer_grpc,
                api_key=self.qdrant_api_key,
                timeout=self.qdrant_timeout
            )
            self.qdrant_client.health_check() # Verify connection
            self._ensure_qdrant_transcript_collection()
            logger.info(f"Qdrant client initialized for TranscriptAnalyzer. Collection: '{self.qdrant_collection_transcripts}' at {self.qdrant_url}")
        except QdrantClientException as qe:
            logger.error(f"Qdrant client initialization error (QdrantClientException): {qe}", exc_info=True)
            self.qdrant_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client or ensure collection: {e}", exc_info=True)
            self.qdrant_client = None
            
        self.stop_words = set(stopwords.words('english'))
        logger.info("TranscriptAnalyzer initialized.")

    def _ensure_qdrant_transcript_collection(self):
        if not self.qdrant_client:
            logger.error("Qdrant client not available. Cannot ensure transcript collection.")
            return
        if not self.text_embedding_dim or self.text_embedding_dim == 0:
             logger.error(f"Invalid TEXT_EMBEDDING_DIMENSION ({self.text_embedding_dim}). Cannot create/verify Qdrant collection.")
             return

        try:
            self.qdrant_client.get_collection(collection_name=self.qdrant_collection_transcripts)
            logger.debug(f"Qdrant transcript collection '{self.qdrant_collection_transcripts}' already exists.")
        except QdrantClientException as qe: # More specific exception type
            if "not found" in str(qe).lower() or (hasattr(qe, 'status_code') and qe.status_code == 404):
                logger.info(f"Qdrant collection '{self.qdrant_collection_transcripts}' not found. Creating now...")
                try:
                    self.qdrant_client.create_collection(
                        collection_name=self.qdrant_collection_transcripts,
                        vectors_config=qdrant_models.VectorParams(size=self.text_embedding_dim, distance=qdrant_models.Distance.COSINE)
                    )
                    logger.info(f"Qdrant transcript collection '{self.qdrant_collection_transcripts}' created with dim {self.text_embedding_dim}.")
                except Exception as e_create:
                    logger.error(f"Failed to create Qdrant transcript collection '{self.qdrant_collection_transcripts}': {e_create}", exc_info=True)
            else: # Other Qdrant client error
                 logger.error(f"Qdrant client error when checking collection '{self.qdrant_collection_transcripts}': {qe}", exc_info=True)
        except Exception as e: # Catch any other broader exceptions
            logger.error(f"Unexpected error ensuring Qdrant transcript collection '{self.qdrant_collection_transcripts}': {e}", exc_info=True)


    def _fetch_vtt_content(self, vtt_url: str) -> Optional[str]:
        if not vtt_url: return None
        logger.debug(f"Fetching VTT content from URL: {vtt_url}")
        try:
            # Use requests for direct VTT file URLs
            if vtt_url.endswith('.vtt'):
                response = requests.get(vtt_url, timeout=10)
                response.raise_for_status()
                raw_vtt_content = response.text
                lines = raw_vtt_content.splitlines()
                text_lines = [line for line in lines if line and not line.startswith("WEBVTT") and "-->" not in line and not line.isdigit()]
                return " ".join(text_lines).strip()
            else:
                # If not a direct .vtt, yt-dlp logic (as complex as it is) might be needed for video pages
                # For now, assume CAAgent handles downloading for non-direct VTTs or SOIAgent gets full text.
                logger.warning(f"Direct VTT content fetching for non-.vtt URL {vtt_url} is not robustly supported here. Best if full text or direct VTT provided.")
                return None
        except requests.RequestException as e:
            logger.error(f"Error fetching VTT from {vtt_url} with requests: {e}", exc_info=True)
            return None
        except Exception as e_gen: # Catch-all for other parsing issues
            logger.error(f"Generic error processing VTT URL {vtt_url}: {e_gen}", exc_info=True)
            return None

    # ... (rest of the methods: _preprocess_text_for_lda, extract_keywords_from_text, perform_topic_modeling, generate_transcript_embeddings are largely the same) ...
    # Minor changes might be related to logging or error propagation if needed.

    def generate_transcript_embeddings(self, text: str, segment_length: int = 200, overlap: int = 50) -> list[tuple[str, list[float]]]:
        """Generates embeddings for segments of the transcript."""
        if not self.sentence_model or not text: return []
        
        words = text.split()
        embeddings_with_text = []
        
        for i in range(0, len(words), segment_length - overlap):
            segment_words = words[i : i + segment_length]
            segment_text = " ".join(segment_words)
            if not segment_text.strip(): continue

            try:
                embedding = self.sentence_model.encode(segment_text)
                embeddings_with_text.append((segment_text, embedding.tolist()))
            except Exception as e:
                logger.error(f"Error encoding segment '{segment_text[:50]}...': {e}", exc_info=True)
                
        return embeddings_with_text

    def store_embeddings_in_qdrant(self, video_source_db_id: Any, embeddings_with_text: list[tuple[str, list[float]]]) -> bool:
        """Stores text segments and their embeddings in Qdrant."""
        if not self.qdrant_client:
            logger.error(f"Qdrant client not available. Cannot store embeddings for VSID {video_source_db_id}.")
            return False
        if not embeddings_with_text:
            logger.info(f"No embeddings provided to store for VSID {video_source_db_id}.")
            return False # Or True if "nothing to do" is success

        points_to_upsert = []
        for i, (text_segment, embedding_vector) in enumerate(embeddings_with_text):
            qdrant_point_id = f"{video_source_db_id}_transcript_seg_{i}" # More specific ID
            
            payload = {
                "video_source_db_id": str(video_source_db_id), 
                "segment_index": i,
                "text_content": text_segment[:1500] # Qdrant payload limit considerations
            }
            points_to_upsert.append(
                qdrant_models.PointStruct(id=qdrant_point_id, vector=embedding_vector, payload=payload)
            )
        
        if not points_to_upsert: return False

        try:
            self.qdrant_client.upsert(
                collection_name=self.qdrant_collection_transcripts, # Use configured name
                points=points_to_upsert,
                wait=True 
            )
            logger.info(f"Successfully stored {len(points_to_upsert)} transcript segments in Qdrant for VSID {video_source_db_id}.")
            return True
        except QdrantClientException as qe:
            logger.error(f"QdrantClientException storing transcript embeddings for VSID {video_source_db_id}: {qe}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error storing transcript embeddings for VSID {video_source_db_id}: {e}", exc_info=True)
            return False

    def process_transcript_for_video_source(self, video_source_model: Any, raw_video_item_data: dict) -> dict:
        # Import models here to avoid AppRegistryNotReady at module load if this file is imported early
        from api.models import Transcript, ExtractedKeyword, VideoTopic

        logger.info(f"TranscriptAnalyzer: Starting processing for VideoSource ID {video_source_model.id}")
        analysis_results = {
            "transcript_db_id": None,
            "keywords_extracted_count": 0,
            "topics_identified_count": 0,
            "embeddings_generated_count": 0,
            "embeddings_stored_qdrant": False,
            "status": "pending", # Overall status for this TA run
            "errors": []
        }

        full_transcript_text = raw_video_item_data.get('transcript_text')
        vtt_url = raw_video_item_data.get('transcript_vtt_url')

        if not full_transcript_text and vtt_url:
            logger.debug(f"No direct transcript text for VSID {video_source_model.id}, fetching from VTT URL: {vtt_url}")
            full_transcript_text = self._fetch_vtt_content(vtt_url)
        
        if not full_transcript_text or not full_transcript_text.strip():
            logger.warning(f"No transcript content found for VSID {video_source_model.id}.")
            analysis_results["errors"].append("No transcript content available.")
            analysis_results["status"] = "failed_no_content"
            return analysis_results

        # 1. Save to Transcript model
        transcript_obj = None
        try:
            # Changed field name to transcript_text_content
            transcript_obj, created = Transcript.objects.update_or_create(
                video_source=video_source_model,
                language_code=raw_video_item_data.get('language_code', 'en'), # Assuming only one per lang
                defaults={
                    'transcript_text_content': full_transcript_text,
                    # 'transcript_timed_json': ..., # Placeholder
                    'processing_status': 'pending' # Initial status for the DB object
                }
            )
            analysis_results["transcript_db_id"] = transcript_obj.id
            logger.info(f"Transcript {'created' if created else 'updated'} in DB (ID: {transcript_obj.id}) for VSID {video_source_model.id}.")
        except Exception as e:
            logger.error(f"Error saving transcript to DB for VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_results["errors"].append(f"DB transcript save error: {str(e)}")
            analysis_results["status"] = "failed_db_error"
            return analysis_results

        # If self.nlp or self.sentence_model failed to load, many features can't be extracted.
        if not self.nlp:
            analysis_results["errors"].append("spaCy NLP model not available. Keyword/Topic extraction skipped.")
        if not self.sentence_model:
            analysis_results["errors"].append("SentenceTransformer model not available. Embedding generation skipped.")

        # 2. Extract Keywords (if NLP model available)
        if self.nlp:
            try:
                # keywords_with_scores = self.extract_keywords_from_text(full_transcript_text, top_n=15)
                # ExtractedKeyword.objects.filter(transcript=transcript_obj).delete() # Clear old for this transcript
                # for kw, score in keywords_with_scores:
                #     ExtractedKeyword.objects.create(transcript=transcript_obj, keyword_text=kw, relevance_score=score)
                # analysis_results["keywords_extracted_count"] = len(keywords_with_scores)
                # logger.info(f"Extracted {len(keywords_with_scores)} keywords for TID {transcript_obj.id}.")
                pass # Keyword model changed to link to VideoSource, adapt if re-enabling
            except Exception as e:
                logger.error(f"Error extracting/saving keywords for TID {transcript_obj.id}: {e}", exc_info=True)
                analysis_results["errors"].append(f"Keyword extraction error: {str(e)}")
        
        # 3. Perform Topic Modeling (if NLP model available)
        if self.nlp:
            try:
                # topics = self.perform_topic_modeling(full_transcript_text, num_topics=3, num_words_per_topic=5)
                # VideoTopic.objects.filter(transcript=transcript_obj).delete() # Clear old
                # for topic_data in topics:
                #     VideoTopic.objects.create(transcript=transcript_obj, topic_label=topic_data['name'], topic_relevance_score=topic_data.get('overall_score_for_doc'))
                # analysis_results["topics_identified_count"] = len(topics)
                # logger.info(f"Identified {len(topics)} topics for TID {transcript_obj.id}.")
                pass # Topic model changed to link to VideoSource, adapt if re-enabling
            except Exception as e:
                logger.error(f"Error topic modeling for TID {transcript_obj.id}: {e}", exc_info=True)
                analysis_results["errors"].append(f"Topic modeling error: {str(e)}")

        # 4. Generate and Store Embeddings (if sentence model and Qdrant client available)
        if self.sentence_model and self.qdrant_client:
            try:
                embeddings_with_text_segments = self.generate_transcript_embeddings(full_transcript_text)
                analysis_results["embeddings_generated_count"] = len(embeddings_with_text_segments)
                if embeddings_with_text_segments:
                    # Consider deleting old points for this video_source_model.id (safer by filter)
                    try:
                        self.qdrant_client.delete(
                            collection_name=self.qdrant_collection_transcripts,
                            points_selector=qdrant_models.FilterSelector(
                                filter=qdrant_models.Filter(
                                    must=[
                                        qdrant_models.FieldCondition(
                                            key="video_source_db_id",
                                            match=qdrant_models.MatchValue(value=str(video_source_model.id))
                                        )
                                    ]
                                )
                            )
                        )
                        logger.info(f"Cleared old Qdrant transcript points for VSID {video_source_model.id}")
                    except Exception as e_del:
                        logger.warning(f"Could not clear old Qdrant transcript points for VSID {video_source_model.id}: {e_del}")

                    stored_ok = self.store_embeddings_in_qdrant(video_source_model.id, embeddings_with_text_segments)
                    analysis_results["embeddings_stored_qdrant"] = stored_ok
                    if stored_ok:
                        transcript_obj.vector_db_transcript_id = f"qdrant_vsid_{video_source_model.id}_indexed" # More specific
                        logger.info(f"Embeddings stored in Qdrant for VSID {video_source_model.id}.")
                    else:
                        analysis_results["errors"].append("Failed to store embeddings in Qdrant.")
            except Exception as e:
                logger.error(f"Error generating/storing transcript embeddings for VSID {video_source_model.id}: {e}", exc_info=True)
                analysis_results["errors"].append(f"Embedding processing error: {str(e)}")
        elif not self.sentence_model:
            logger.warning(f"Sentence model not available. Skipping embedding generation for VSID {video_source_model.id}.")
        elif not self.qdrant_client:
             logger.warning(f"Qdrant client not available. Skipping embedding storage for VSID {video_source_model.id}.")
            
        # Finalize transcript object status
        if analysis_results["errors"]:
            transcript_obj.processing_status = 'failed'
            transcript_obj.save(update_fields=['processing_status', 'vector_db_transcript_id', 'updated_at'])
            analysis_results["status"] = "failed_processing"
        else:
            transcript_obj.processing_status = 'processed'
            transcript_obj.save(update_fields=['processing_status', 'vector_db_transcript_id', 'updated_at'])
            analysis_results["status"] = "processed"
            
        logger.info(f"TranscriptAnalyzer: Finished for VSID {video_source_model.id}. Status: {analysis_results['status']}. Results: {analysis_results}")
        return analysis_results

    # placeholder for methods from original file that were not changed
    def _preprocess_text_for_lda(self, text: str) -> list[str]: # type: ignore
        if not self.nlp: return []
        text = clean_text(text) 
        text = normalize_text_unicode(text)
        text = re.sub(r'[^\w\s]', '', text) 
        text = re.sub(r'\d+', '', text)      
        tokens = word_tokenize(text)
        lemmatized_tokens = []
        doc = self.nlp(" ".join(tokens)) 
        for token in doc:
            if not token.is_stop and token.lemma_ not in self.stop_words and len(token.lemma_) > 2 and token.is_alpha:
                lemmatized_tokens.append(token.lemma_)
        return lemmatized_tokens

    def extract_keywords_from_text(self, text: str, top_n: int = 10) -> list[tuple[str, float]]: # type: ignore
        if not self.nlp or not text: return []
        doc = self.nlp(text)
        keywords_with_counts = {}
        for chunk in doc.noun_chunks:
            keyword = chunk.lemma_.lower().strip()
            if keyword and len(keyword) > 2 and keyword not in self.stop_words:
                 keywords_with_counts[keyword] = keywords_with_counts.get(keyword, 0) + 1
        if not keywords_with_counts:
            for token in doc:
                if token.pos_ in ('NOUN', 'PROPN', 'ADJ') and not token.is_stop and len(token.lemma_) > 2:
                    keyword = token.lemma_.lower()
                    keywords_with_counts[keyword] = keywords_with_counts.get(keyword, 0) + 1
        if not keywords_with_counts: return []
        max_count = max(keywords_with_counts.values()) if keywords_with_counts else 1
        sorted_keywords = sorted(keywords_with_counts.items(), key=lambda item: item[1], reverse=True)
        return [(kw, round(count / max_count, 3)) for kw, count in sorted_keywords[:top_n]]

    def perform_topic_modeling(self, text: str, num_topics: int = 3, num_words_per_topic: int = 5) -> list[dict]: # type: ignore
        if not text: return []
        processed_docs = [self._preprocess_text_for_lda(text)] 
        if not processed_docs[0]: 
            logger.warning("Text preprocessing for LDA resulted in no usable tokens.")
            return []
        try:
            dictionary = corpora.Dictionary(processed_docs)
            dictionary.filter_extremes(no_below=2, no_above=0.8) 
            corpus = [dictionary.doc2bow(doc) for doc in processed_docs]
            if not corpus or not corpus[0]: 
                 logger.warning("Corpus for LDA is empty after dictionary filtering.")
                 return []
            # from gensim.models import TfidfModel # Moved import to top
            # tfidf = TfidfModel(corpus)
            # corpus_tfidf = tfidf[corpus]
            lda_model = LdaModel(corpus=corpus, id2word=dictionary, num_topics=num_topics,random_state=42,passes=10, alpha='auto',eta='auto') # Removed tfidf for simplicity, can add back
            topics_found = []
            raw_topics = lda_model.show_topics(num_topics=num_topics, num_words=num_words_per_topic, formatted=False)
            for topic_id, topic_terms in raw_topics:
                terms = [{"word": word, "score": float(score)} for word, score in topic_terms]
                topic_name = ", ".join([term["word"] for term in terms[:3]])
                topics_found.append({"id": topic_id, "name": topic_name, "terms": terms})
            return topics_found
        except Exception as e:
            logger.error(f"Error during LDA topic modeling: {e}", exc_info=True)
            return []
