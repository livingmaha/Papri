# backend/ai_agents/query_understanding_agent.py
import logging
import os
import spacy
from sentence_transformers import SentenceTransformer
import imagehash # For basic image hashing if needed by QAgent
import cv2 # OpenCV for image loading/basic processing if doing more here
from django.conf import settings
from tensorflow.keras.applications import EfficientNetV2S # Example
from tensorflow.keras.preprocessing import image as keras_image
from tensorflow.keras.applications.efficientnet_v2 import preprocess_input
import numpy as np

# from .visual_analyzer import VisualAnalyzer # Can be instantiated if QAgent directly generates query embeddings

logger = logging.getLogger(__name__)

class QueryUnderstandingAgent:
    def __init__(self):
        self.nlp_model_name = "en_core_web_sm" # Small model for speed, consider larger for accuracy
        self.sentence_transformer_model_name = settings.SENTENCE_TRANSFORMER_MODEL
        
        try:
            self.nlp = spacy.load(self.nlp_model_name)
            logger.info(f"spaCy model '{self.nlp_model_name}' loaded successfully for QAgent.")
        except OSError:
            logger.error(f"spaCy model '{self.nlp_model_name}' not found. Please download it: python -m spacy download {self.nlp_model_name}")
            # Fallback or raise critical error depending on desired behavior
            self.nlp = None 
                                   
        try:
            self.sentence_model = SentenceTransformer(self.sentence_transformer_model_name)
            logger.info(f"SentenceTransformer model '{self.sentence_transformer_model_name}' loaded successfully for QAgent.")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer model '{self.sentence_transformer_model_name}': {e}", exc_info=True)
            self.sentence_model = None

        # For image query processing (visual feature extraction)
        # This could be a simplified version of what VisualAnalyzer does, or it could call VisualAnalyzer.
        # For this example, QAgent will do its own basic visual feature extraction for the query image.
        self.visual_model_name = settings.VISUAL_CNN_MODEL_NAME
        if self.visual_model_name == 'EfficientNetV2S':
            try:
                # Using include_top=False to get feature vectors, not classifications
                self.cnn_model = EfficientNetV2S(weights='imagenet', include_top=False, pooling='avg') 
                self.cnn_target_size = (224, 224) # Example target size for EfficientNet
                logger.info(f"CNN model '{self.visual_model_name}' loaded successfully for QAgent image processing.")
            except Exception as e:
                logger.error(f"Failed to load CNN model '{self.visual_model_name}': {e}", exc_info=True)
                self.cnn_model = None
        else:
            logger.warning(f"Visual CNN model '{self.visual_model_name}' not configured for QAgent, image queries might be limited.")
            self.cnn_model = None
            
        logger.info("QueryUnderstandingAgent initialized.")

    def _extract_keywords_entities(self, text: str) -> tuple[list[str], list[dict]]:
        keywords = []
        entities = []
        if not self.nlp or not text:
            return keywords, entities
        
        doc = self.nlp(text)
        # Simple keyword extraction (nouns, proper nouns, adjectives - can be refined)
        keywords = [token.lemma_.lower() for token in doc if token.pos_ in ('NOUN', 'PROPN', 'ADJ') and not token.is_stop and len(token.lemma_) > 2]
        
        entities = [{"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char} for ent in doc.ents]
        
        # Fallback keywords if NLP found few: just split and lowercase
        if not keywords and len(text.split()) > 1:
            keywords = [word.lower() for word in text.split() if len(word) > 2]

        return list(set(keywords)), entities # Return unique keywords

    def _generate_text_embedding(self, text: str) -> list[float] | None:
        if not self.sentence_model or not text:
            return None
        try:
            embedding = self.sentence_model.encode(text)
            return embedding.tolist() # Convert numpy array to list for JSON serialization
        except Exception as e:
            logger.error(f"Error generating text embedding for QAgent: {e}", exc_info=True)
            return None

    def process_text_query(self, text_query: str) -> dict:
        """
        Processes a natural language text query.
        Returns a dictionary with processed query, keywords, entities, intent, and embedding.
        """
        if not text_query:
            return {"error": "Text query is empty.", "status_code": 400}

        logger.debug(f"QAgent processing text query: '{text_query[:100]}...'")
        
        cleaned_query = text_query.strip() # Basic cleaning
        keywords, entities = self._extract_keywords_entities(cleaned_query)
        text_embedding = self._generate_text_embedding(cleaned_query)

        # Basic intent detection (can be made more sophisticated)
        intent = "general_video_search"
        if any(kw in cleaned_query.lower() for kw in ["how to", "tutorial", "learn"]):
            intent = "instructional_video_search"
        elif entities and any(ent['label'] in ('PERSON', 'ORG', 'PRODUCT') for ent in entities):
            intent = "entity_focused_search"
        
        processed_data = {
            "original_query_text": text_query,
            "processed_query_text": cleaned_query,
            "keywords": keywords,
            "entities": entities,
            "intent": intent,
            "text_embedding": text_embedding, # For semantic search
            "query_type": "text"
        }
        logger.debug(f"QAgent text query processing result: {processed_data}")
        return processed_data

    def _generate_image_fingerprints(self, image_path: str) -> dict:
        """Generates various perceptual hashes for an image."""
        hashes = {}
        try:
            img_obj = imagehash.average_hash(cv2.imread(image_path)) # Using cv2 to read for consistency
            hashes['average_hash'] = str(img_obj)
            hashes['phash'] = str(imagehash.phash(cv2.imread(image_path)))
            hashes['dhash'] = str(imagehash.dhash(cv2.imread(image_path)))
            # Consider adding colorhash if useful: imagehash.colorhash(cv2.imread(image_path))
        except Exception as e:
            logger.error(f"Error generating image fingerprints for {image_path} in QAgent: {e}", exc_info=True)
        return hashes

    def _extract_visual_cnn_features(self, image_path: str) -> list[float] | None:
        """Extracts CNN feature vector from an image."""
        if not self.cnn_model or not os.path.exists(image_path):
            logger.warning(f"CNN model not available or image path invalid for QAgent: {image_path}")
            return None
        try:
            img = keras_image.load_img(image_path, target_size=self.cnn_target_size)
            img_array = keras_image.img_to_array(img)
            img_array_expanded = np.expand_dims(img_array, axis=0)
            img_preprocessed = preprocess_input(img_array_expanded) # Specific to the CNN model (EfficientNetV2 here)
            
            features = self.cnn_model.predict(img_preprocessed)
            return features.flatten().tolist() # Flatten and convert to list
        except Exception as e:
            logger.error(f"Error extracting CNN features for query image {image_path} in QAgent: {e}", exc_info=True)
            return None

    def process_image_query(self, image_path: str, accompanying_text: str = None) -> dict:
        """
        Processes an image query (e.g., a screenshot).
        Returns a dictionary with image features, hashes, and potentially analyzed accompanying text.
        `image_path` should be an accessible local file path.
        """
        if not image_path or not os.path.exists(image_path):
            logger.error(f"Image path invalid or not provided for QAgent: {image_path}")
            return {"error": "Image path is invalid or file does not exist.", "status_code": 400}

        logger.debug(f"QAgent processing image query from path: {image_path}")

        image_fingerprints = self._generate_image_fingerprints(image_path)
        visual_cnn_embedding = self._extract_visual_cnn_features(image_path)
        
        processed_data = {
            "original_image_path": image_path, # Keep original path for reference
            "intent": "visual_similarity_search", # Default intent for image query
            "image_fingerprints": image_fingerprints, # e.g., phash, dhash for quick matching
            "visual_cnn_embedding": visual_cnn_embedding, # For deep visual similarity
            "query_type": "image"
        }

        if accompanying_text:
            logger.debug(f"QAgent processing accompanying text for image query: '{accompanying_text[:100]}...'")
            text_analysis = self.process_text_query(accompanying_text)
            # Merge text analysis results, perhaps prefixing keys to avoid clashes
            processed_data["accompanying_text_analysis"] = {
                f"text_{k}": v for k,v in text_analysis.items() if k not in ['query_type', 'original_query_text']
            }
            processed_data["original_query_text"] = accompanying_text
            # Refine intent if text is present
            if visual_cnn_embedding and text_analysis.get("text_embedding"):
                processed_data["intent"] = "hybrid_visual_text_search"
            elif not visual_cnn_embedding and text_analysis.get("text_embedding"): # Image failed but text ok
                processed_data["intent"] = text_analysis.get("intent", "general_video_search")
                # Copy top-level text fields if image processing failed significantly
                processed_data.update({k:v for k,v in text_analysis.items() if k not in processed_data})


        logger.debug(f"QAgent image query processing result: {str(processed_data)[:500]}...") # Log snippet
        return processed_data

    def process_hybrid_query(self, text_query: str, image_path: str) -> dict:
        """
        Processes a query that has both text and image components.
        """
        logger.debug(f"QAgent processing hybrid query: Text='{text_query[:100]}...', Image='{image_path}'")
        
        text_processed_data = self.process_text_query(text_query)
        image_processed_data = self.process_image_query(image_path)

        if "error" in text_processed_data and "error" in image_processed_data:
            return {"error": "Both text and image processing failed.", 
                    "text_error": text_processed_data["error"], 
                    "image_error": image_processed_data["error"],
                    "status_code": 400}
        
        # Combine results. Prioritize intent based on success of components.
        combined_data = {
            "original_query_text": text_query,
            "original_image_path": image_path,
            "query_type": "hybrid",
            "text_component": text_processed_data,
            "image_component": image_processed_data,
            "intent": "hybrid_visual_text_search" # Default for hybrid
        }

        # If one part failed, adjust intent or flag it
        if "error" in text_processed_data:
            combined_data["intent"] = "visual_similarity_search_with_failed_text"
        if "error" in image_processed_data:
            combined_data["intent"] = "text_search_with_failed_image"
        
        # Example of merging top-level convenience fields (keywords, embeddings)
        # This needs careful consideration of how RARAgent will use them.
        # For now, RARAgent should look into 'text_component' and 'image_component'.
        # combined_data["keywords"] = text_processed_data.get("keywords", [])
        # combined_data["text_embedding"] = text_processed_data.get("text_embedding")
        # combined_data["visual_cnn_embedding"] = image_processed_data.get("visual_cnn_embedding")
        # combined_data["image_fingerprints"] = image_processed_data.get("image_fingerprints")

        logger.debug(f"QAgent hybrid query processing result: {str(combined_data)[:500]}...")
        return combined_data

    def process_video_url_query(self, video_url: str, text_prompt: str = None) -> dict:
        """
        Processes a query that is a direct video URL, potentially with a text prompt
        for what to do with it (e.g., "summarize this video", "find scenes with X").
        """
        logger.debug(f"QAgent processing video URL query: {video_url}, Prompt: '{text_prompt[:100]}...'")
        
        # Basic validation of URL (more can be done in SOIAgent)
        if not video_url or not (video_url.startswith("http://") or video_url.startswith("https://")):
            return {"error": "Invalid video URL provided.", "status_code": 400}

        processed_data = {
            "original_video_url": video_url,
            "query_type": "video_url_focused",
            "intent": "analyze_specific_video" # Default intent
        }

        if text_prompt:
            text_analysis = self.process_text_query(text_prompt)
            processed_data["prompt_analysis"] = {
                 f"text_{k}": v for k,v in text_analysis.items() if k not in ['query_type', 'original_query_text']
            }
            processed_data["original_prompt_text"] = text_prompt
            # Refine intent based on prompt, e.g., "summarize", "edit_instructions", "find_timestamps"
            if "summarize" in text_prompt.lower():
                processed_data["intent"] = "summarize_video_from_url"
            elif any(kw in text_prompt.lower() for kw in ["edit", "cut", "remove", "add music"]):
                processed_data["intent"] = "edit_video_from_url_instructions"
            elif any(kw in text_prompt.lower() for kw in ["find scenes", "timestamps for", "show me when"]):
                processed_data["intent"] = "find_in_video_from_url"

        logger.debug(f"QAgent video URL query processing result: {processed_data}")
        return processed_data


# Example Usage (for testing, not part of the class typically)
if __name__ == '__main__':
    # This block will only run if the script is executed directly
    # Ensure Django settings are configured if this script needs them
    # (e.g., by setting DJANGO_SETTINGS_MODULE environment variable)
    
    # Create a dummy settings.SENTENCE_TRANSFORMER_MODEL for this test if needed
    class DummySettings:
        SENTENCE_TRANSFORMER_MODEL = 'all-MiniLM-L6-v2' # A common small model
        VISUAL_CNN_MODEL_NAME = 'EfficientNetV2S' # Requires TensorFlow and weights

    if not hasattr(settings, 'SENTENCE_TRANSFORMER_MODEL'):
        settings.SENTENCE_TRANSFORMER_MODEL = DummySettings.SENTENCE_TRANSFORMER_MODEL
    if not hasattr(settings, 'VISUAL_CNN_MODEL_NAME'):
        settings.VISUAL_CNN_MODEL_NAME = DummySettings.VISUAL_CNN_MODEL_NAME

    q_agent = QueryUnderstandingAgent()

    sample_text = "Show me exciting cat videos from 2023 about playing with yarn"
    text_result = q_agent.process_text_query(sample_text)
    print("\n--- Text Query Result ---")
    print(text_result)

    # For image query, you'd need a sample image file
    # Create a dummy image file for testing if one doesn't exist
    dummy_image_path = "dummy_query_image.png"
    if not os.path.exists(dummy_image_path) and q_agent.cnn_model: # Only create if CNN model loaded
        try:
            # Create a small black image using OpenCV
            dummy_img_arr = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.imwrite(dummy_image_path, dummy_img_arr)
            print(f"\nCreated dummy image at: {dummy_image_path}")
            
            image_result = q_agent.process_image_query(dummy_image_path, accompanying_text="A cute black cat")
            print("\n--- Image Query Result (with text) ---")
            print(image_result)

            hybrid_result = q_agent.process_hybrid_query("Black cat playing", dummy_image_path)
            print("\n--- Hybrid Query Result ---")
            print(hybrid_result)

        except Exception as e:
            print(f"Error during image query test: {e}")
        finally:
            if os.path.exists(dummy_image_path):
                 # os.remove(dummy_image_path) # Clean up dummy image
                 print(f"Dummy image kept at {dummy_image_path} for inspection.")
    else:
        print(f"\nSkipping image query test: CNN model not loaded or dummy image '{dummy_image_path}' could not be prepared.")

    url_query_result = q_agent.process_video_url_query("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Summarize the key moments.")
    print("\n--- Video URL Query Result ---")
    print(url_query_result)
