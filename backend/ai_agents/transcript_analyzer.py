# backend/ai_agents/transcript_analyzer.py
import logging
import re
import spacy
import gensim
from gensim import corpora
from gensim.models import LdaModel, CoherenceModel, TfidfModel
from sentence_transformers import SentenceTransformer
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
import nltk # NLTK for stop words and tokenization

from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models # Renamed to avoid conflict with Django models
import yt_dlp # For fetching transcripts if only a VTT URL is available

# Import Django models (use with caution at module level, or import within methods)
# from api.models import Transcript, ExtractedKeyword, VideoTopic, VideoSource

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
        self.nlp_model_name = "en_core_web_sm" # spaCy model for NER, POS tagging
        self.sentence_transformer_model_name = settings.SENTENCE_TRANSFORMER_MODEL
        self.qdrant_url = settings.QDRANT_URL
        self.qdrant_api_key = settings.QDRANT_API_KEY
        self.qdrant_collection_transcripts = settings.QDRANT_COLLECTION_TRANSCRIPTS
        
        try:
            self.nlp = spacy.load(self.nlp_model_name)
            logger.info(f"spaCy model '{self.nlp_model_name}' loaded for TranscriptAnalyzer.")
        except OSError:
            logger.error(f"spaCy model '{self.nlp_model_name}' not found for TranscriptAnalyzer.")
            self.nlp = None

        try:
            self.sentence_model = SentenceTransformer(self.sentence_transformer_model_name)
            self.embedding_dim = self.sentence_model.get_sentence_embedding_dimension()
            logger.info(f"SentenceTransformer '{self.sentence_transformer_model_name}' loaded for TranscriptAnalyzer (Dim: {self.embedding_dim}).")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer model '{self.sentence_transformer_model_name}': {e}", exc_info=True)
            self.sentence_model = None
            self.embedding_dim = 0 # Default or raise error

        try:
            self.qdrant_client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key, timeout=20) # Increased timeout
            # Ensure collection exists
            self._ensure_qdrant_transcript_collection()
            logger.info(f"Qdrant client initialized for TranscriptAnalyzer. Collection: '{self.qdrant_collection_transcripts}'")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client or ensure collection: {e}", exc_info=True)
            self.qdrant_client = None
            
        self.stop_words = set(stopwords.words('english'))
        logger.info("TranscriptAnalyzer initialized.")

    def _ensure_qdrant_transcript_collection(self):
        if not self.qdrant_client or not self.embedding_dim:
            logger.error("Qdrant client or embedding dimension not available. Cannot ensure collection.")
            return
        try:
            self.qdrant_client.get_collection(collection_name=self.qdrant_collection_transcripts)
            logger.debug(f"Qdrant collection '{self.qdrant_collection_transcripts}' already exists.")
        except Exception: # Collection does not exist
            logger.info(f"Qdrant collection '{self.qdrant_collection_transcripts}' not found. Creating now...")
            self.qdrant_client.create_collection(
                collection_name=self.qdrant_collection_transcripts,
                vectors_config=qdrant_models.VectorParams(size=self.embedding_dim, distance=qdrant_models.Distance.COSINE)
            )
            logger.info(f"Qdrant collection '{self.qdrant_collection_transcripts}' created with dim {self.embedding_dim}.")

    def _fetch_vtt_content(self, vtt_url: str) -> str | None:
        """Fetches and parses VTT content from a URL."""
        if not vtt_url: return None
        logger.debug(f"Fetching VTT content from URL: {vtt_url}")
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': False, # We want the content, not a file
            'writeautomaticsub': False,
            'subtitleslangs': ['en'], # Prioritize English or configure as needed
            'logger': logging.getLogger(f"{__name__}.yt_dlp_vtt"), # Use a sub-logger
            'quiet': True,
            'noplaylist': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(vtt_url, download=False)
                # yt-dlp might provide 'subtitles' or 'automatic_captions'
                # This part needs refinement based on how yt-dlp returns VTT *content* for direct VTT URLs.
                # If `vtt_url` is a direct link to a .vtt file, requests might be simpler.
                # For now, assuming `vtt_url` might be a video page URL from which yt-dlp can get subs.
                
                # This is tricky: yt-dlp usually downloads subs to files.
                # To get content directly, might need to hook into its process or use a simpler HTTP GET if it's a direct file link.
                # Let's try a simple requests.get for direct VTT files first:
                if vtt_url.endswith('.vtt'):
                    response = requests.get(vtt_url, timeout=10)
                    response.raise_for_status()
                    raw_vtt_content = response.text
                    # Basic VTT cleaning: remove timestamps and metadata lines
                    lines = raw_vtt_content.splitlines()
                    text_lines = [line for line in lines if line and not line.startswith("WEBVTT") and not "-->" in line and not line.isdigit()]
                    return " ".join(text_lines).strip()

                # If not a direct VTT, and relying on yt-dlp for a video page:
                # This path is more complex as yt-dlp doesn't easily return subtitle *content* directly.
                # One workaround is to let it download to a temp file and read it.
                logger.warning(f"Direct VTT content fetching for non-.vtt URL {vtt_url} via yt-dlp is complex and not fully implemented here. Returning None.")
                return None # Placeholder

        except Exception as e:
            logger.error(f"Error fetching/parsing VTT from {vtt_url}: {e}", exc_info=True)
            return None

    def _preprocess_text_for_lda(self, text: str) -> list[str]:
        if not self.nlp: return []
        # Lowercase, remove punctuation, numbers, stopwords, and lemmatize
        text = clean_text(text) # Basic cleaning (lowercase, strip)
        text = normalize_text_unicode(text)
        text = re.sub(r'[^\w\s]', '', text) # Remove punctuation
        text = re.sub(r'\d+', '', text)      # Remove numbers
        
        tokens = word_tokenize(text)
        lemmatized_tokens = []
        doc = self.nlp(" ".join(tokens)) # Process with spaCy for lemmatization
        for token in doc:
            if not token.is_stop and token.lemma_ not in self.stop_words and len(token.lemma_) > 2 and token.is_alpha:
                lemmatized_tokens.append(token.lemma_)
        return lemmatized_tokens

    def extract_keywords_from_text(self, text: str, top_n: int = 10) -> list[tuple[str, float]]:
        """Extracts keywords using spaCy's noun chunks and simple ranking (can be replaced by RAKE, YAKE, etc.)."""
        if not self.nlp or not text: return []
        
        doc = self.nlp(text)
        # Use noun chunks as potential keywords
        keywords_with_counts = {}
        for chunk in doc.noun_chunks:
            keyword = chunk.lemma_.lower().strip()
            if keyword and len(keyword) > 2 and keyword not in self.stop_words:
                 keywords_with_counts[keyword] = keywords_with_counts.get(keyword, 0) + 1
        
        # Fallback: Use frequent non-stopword nouns/adjectives if no noun chunks
        if not keywords_with_counts:
            for token in doc:
                if token.pos_ in ('NOUN', 'PROPN', 'ADJ') and not token.is_stop and len(token.lemma_) > 2:
                    keyword = token.lemma_.lower()
                    keywords_with_counts[keyword] = keywords_with_counts.get(keyword, 0) + 1
        
        if not keywords_with_counts: return []

        # Simple relevance: frequency. Max count for normalization.
        max_count = max(keywords_with_counts.values()) if keywords_with_counts else 1
        
        # Sort by count and return top_n with a normalized score
        sorted_keywords = sorted(keywords_with_counts.items(), key=lambda item: item[1], reverse=True)
        
        return [(kw, round(count / max_count, 3)) for kw, count in sorted_keywords[:top_n]]


    def perform_topic_modeling(self, text: str, num_topics: int = 3, num_words_per_topic: int = 5) -> list[dict]:
        """Performs LDA topic modeling on the text."""
        if not text: return []
        
        processed_docs = [self._preprocess_text_for_lda(text)] # LDA expects a list of documents (token lists)
        if not processed_docs[0]: # If preprocessing resulted in empty token list
            logger.warning("Text preprocessing for LDA resulted in no usable tokens.")
            return []

        try:
            dictionary = corpora.Dictionary(processed_docs)
            dictionary.filter_extremes(no_below=2, no_above=0.8) # Filter out very rare and very common words
            corpus = [dictionary.doc2bow(doc) for doc in processed_docs]

            if not corpus or not corpus[0]: # If corpus is empty after filtering
                 logger.warning("Corpus for LDA is empty after dictionary filtering.")
                 return []

            # TF-IDF transformation can sometimes improve LDA results
            tfidf = TfidfModel(corpus)
            corpus_tfidf = tfidf[corpus]

            lda_model = LdaModel(
                corpus=corpus_tfidf, # Use TF-IDF transformed corpus
                id2word=dictionary,
                num_topics=num_topics,
                random_state=42,
                passes=10, # Number of passes through the corpus during training
                alpha='auto', # Learn alpha from data
                eta='auto'    # Learn eta from data
            )
            
            # Get topics
            topics_found = []
            raw_topics = lda_model.show_topics(num_topics=num_topics, num_words=num_words_per_topic, formatted=False)
            for topic_id, topic_terms in raw_topics:
                terms = [{"word": word, "score": float(score)} for word, score in topic_terms]
                # Get coherence score for this topic (more complex, often calculated for the whole model)
                # For simplicity, we'll just store the terms and their scores.
                # A representative name for the topic could be the top 2-3 words.
                topic_name = ", ".join([term["word"] for term in terms[:3]])
                topics_found.append({"id": topic_id, "name": topic_name, "terms": terms})
            
            # Coherence Model (example of evaluating the whole model)
            # coherence_model_lda = CoherenceModel(model=lda_model, texts=processed_docs, dictionary=dictionary, coherence='c_v')
            # coherence_lda = coherence_model_lda.get_coherence()
            # logger.debug(f"LDA Coherence Score (c_v): {coherence_lda}")

            return topics_found
        except Exception as e:
            logger.error(f"Error during LDA topic modeling: {e}", exc_info=True)
            return []

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

    def store_embeddings_in_qdrant(self, video_source_db_id: any, embeddings_with_text: list[tuple[str, list[float]]]) -> bool:
        """Stores text segments and their embeddings in Qdrant."""
        if not self.qdrant_client or not embeddings_with_text:
            logger.warning(f"Qdrant client not available or no embeddings to store for VSID {video_source_db_id}.")
            return False

        points_to_upsert = []
        for i, (text_segment, embedding_vector) in enumerate(embeddings_with_text):
            # Generate a unique ID for each point, linking back to VideoSource and segment index
            qdrant_point_id = f"{video_source_db_id}_seg_{i}"
            
            payload = {
                "video_source_db_id": str(video_source_db_id), # Store the Django VideoSource PK
                "segment_index": i,
                "text_content": text_segment[:1000] # Store segment text (truncate if too long for payload)
                # Add other relevant metadata like timestamp if available
            }
            points_to_upsert.append(
                qdrant_models.PointStruct(
                    id=qdrant_point_id,
                    vector=embedding_vector,
                    payload=payload
                )
            )
        
        if not points_to_upsert: return False

        try:
            # Upsert in batches if many points (Qdrant client handles batching to some extent)
            self.qdrant_client.upsert(
                collection_name=self.qdrant_collection_transcripts,
                points=points_to_upsert,
                wait=True # Wait for operation to complete
            )
            logger.info(f"Successfully stored {len(points_to_upsert)} transcript segments in Qdrant for VSID {video_source_db_id}.")
            return True
        except Exception as e:
            logger.error(f"Error storing transcript embeddings in Qdrant for VSID {video_source_db_id}: {e}", exc_info=True)
            return False

    def process_transcript_for_video_source(self, video_source_model, raw_video_item_data: dict) -> dict:
        """
        Main processing pipeline for a single video's transcript.
        `video_source_model` is the Django VideoSource model instance.
        `raw_video_item_data` is the dict from SOIAgent (e.g., containing 'transcript_text' or 'transcript_vtt_url').
        Returns a dictionary of analysis results.
        """
        from api.models import Transcript, ExtractedKeyword, VideoTopic # Import here to avoid potential circular deps at startup

        logger.info(f"TranscriptAnalyzer: Starting processing for VideoSource ID {video_source_model.id}")
        analysis_results = {
            "transcript_db_id": None,
            "keywords_extracted_count": 0,
            "topics_identified_count": 0,
            "embeddings_generated_count": 0,
            "embeddings_stored_qdrant": False,
            "errors": []
        }

        full_transcript_text = raw_video_item_data.get('transcript_text')
        vtt_url = raw_video_item_data.get('transcript_vtt_url')

        if not full_transcript_text and vtt_url:
            logger.debug(f"No direct transcript text, attempting to fetch from VTT URL: {vtt_url} for VSID {video_source_model.id}")
            full_transcript_text = self._fetch_vtt_content(vtt_url)
        
        if not full_transcript_text or not full_transcript_text.strip():
            logger.warning(f"No transcript content found or fetched for VideoSource ID {video_source_model.id}.")
            analysis_results["errors"].append("No transcript content available.")
            # Update VideoSource status directly here or let CAAgent do it
            # video_source_model.processing_status = 'processing_failed' # Or a specific transcript failed status
            # video_source_model.processing_error_message = "Transcript unavailable or empty."
            # video_source_model.save()
            return analysis_results

        # 1. Save to Transcript model
        try:
            transcript_obj, created = Transcript.objects.update_or_create(
                video_source=video_source_model,
                defaults={
                    'language_code': raw_video_item_data.get('language_code', 'en'), # Assume English if not specified
                    'full_text_content': full_transcript_text,
                    # 'transcript_timed_json': ..., # TODO: Parse VTT for timed data if needed
                    'source_type': 'auto_generated' # Or determine from raw_video_item_data
                }
            )
            analysis_results["transcript_db_id"] = transcript_obj.id
            logger.info(f"Transcript {'created' if created else 'updated'} in DB for VSID {video_source_model.id}. DB ID: {transcript_obj.id}")
        except Exception as e:
            logger.error(f"Error saving transcript to DB for VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_results["errors"].append(f"DB transcript save error: {str(e)}")
            return analysis_results # Stop if DB save fails

        # 2. Extract Keywords
        try:
            keywords_with_scores = self.extract_keywords_from_text(full_transcript_text, top_n=15)
            # Save keywords to ExtractedKeyword model
            # Clear old keywords first for this source
            ExtractedKeyword.objects.filter(video_source=video_source_model, source_field='transcript').delete()
            for kw, score in keywords_with_scores:
                ExtractedKeyword.objects.create(
                    video_source=video_source_model,
                    keyword_text=kw,
                    relevance_score=score,
                    source_field='transcript',
                    extraction_method='spacy_noun_chunks' # Example method
                )
            analysis_results["keywords_extracted_count"] = len(keywords_with_scores)
            logger.info(f"Extracted {len(keywords_with_scores)} keywords for VSID {video_source_model.id}.")
        except Exception as e:
            logger.error(f"Error extracting/saving keywords for VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_results["errors"].append(f"Keyword extraction error: {str(e)}")

        # 3. Perform Topic Modeling
        try:
            topics = self.perform_topic_modeling(full_transcript_text, num_topics=3, num_words_per_topic=5)
            # Save topics to VideoTopic model
            VideoTopic.objects.filter(video_source=video_source_model, modeling_method='LDA_gensim').delete() # Clear old
            for topic_data in topics:
                VideoTopic.objects.create(
                    video_source=video_source_model,
                    topic_name=topic_data['name'], # Representative name
                    # confidence_score can be derived from LDA topic distribution for the doc if needed
                    modeling_method='LDA_gensim', # Example method
                    # Store topic_data['terms'] in a JSONField if you have one on VideoTopic model
                )
            analysis_results["topics_identified_count"] = len(topics)
            logger.info(f"Identified {len(topics)} topics for VSID {video_source_model.id}.")
        except Exception as e:
            logger.error(f"Error performing/saving topic modeling for VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_results["errors"].append(f"Topic modeling error: {str(e)}")

        # 4. Generate and Store Embeddings
        if self.sentence_model and self.qdrant_client:
            try:
                embeddings_with_text_segments = self.generate_transcript_embeddings(full_transcript_text)
                analysis_results["embeddings_generated_count"] = len(embeddings_with_text_segments)
                if embeddings_with_text_segments:
                    # Before storing new, consider deleting old segments for this video_source_db_id from Qdrant
                    # This requires knowing all previous Qdrant point IDs or using a filter.
                    # Example (if IDs are predictable or stored):
                    # self.qdrant_client.delete(collection_name=..., points_selector=qdrant_models.FilterSelector(filter=qdrant_models.Filter(must=[qdrant_models.FieldCondition(key="video_source_db_id", match=qdrant_models.MatchValue(value=str(video_source_model.id)))])))
                    
                    stored_ok = self.store_embeddings_in_qdrant(video_source_model.id, embeddings_with_text_segments)
                    analysis_results["embeddings_stored_qdrant"] = stored_ok
                    if stored_ok:
                        # Update Transcript object with a reference if needed (e.g., a flag or last indexed date)
                        transcript_obj.vector_db_transcript_id = f"qdrant_vsid_{video_source_model.id}" # Example reference
                        transcript_obj.save(update_fields=['vector_db_transcript_id'])
                    logger.info(f"Generated {len(embeddings_with_text_segments)} embeddings. Stored in Qdrant: {stored_ok} for VSID {video_source_model.id}.")
            except Exception as e:
                logger.error(f"Error generating/storing transcript embeddings for VSID {video_source_model.id}: {e}", exc_info=True)
                analysis_results["errors"].append(f"Embedding processing error: {str(e)}")
        else:
            logger.warning(f"Sentence model or Qdrant client not available. Skipping embedding generation for VSID {video_source_model.id}.")
            analysis_results["errors"].append("Embedding generation skipped (missing model/client).")
            
        logger.info(f"TranscriptAnalyzer: Finished processing for VideoSource ID {video_source_model.id}. Results: {analysis_results}")
        return analysis_results
