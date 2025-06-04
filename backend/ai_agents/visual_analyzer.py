# backend/ai_agents/visual_analyzer.py
import logging
import os
import cv2 # OpenCV for video processing
import imagehash
import numpy as np
from PIL import Image # Pillow for imagehash compatibility if needed
from tensorflow.keras.applications import EfficientNetV2S # Or other models like ResNet50
from tensorflow.keras.preprocessing import image as keras_image
from tensorflow.keras.applications.efficientnet_v2 import preprocess_input as efficientnet_preprocess_input
# from tensorflow.keras.applications.resnet50 import preprocess_input as resnet_preprocess_input
import tensorflow as tf # To check GPU availability

from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector # For scene detection
from scenedetect.video_splitter import split_video_ffmpeg # If saving scenes as clips

from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models

# Import Django models (use with caution, or import within methods)
# from api.models import VideoFrameFeature, VideoSource

logger = logging.getLogger(__name__)

# Check TensorFlow GPU availability
# tf_gpus = tf.config.list_physical_devices('GPU')
# if tf_gpus:
#     logger.info(f"TensorFlow: GPUs available: {tf_gpus}")
#     try:
#         for gpu in tf_gpus:
#             tf.config.experimental.set_memory_growth(gpu, True)
#         logger.info("TensorFlow GPU memory growth enabled.")
#     except RuntimeError as e:
#         logger.error(f"Error setting TensorFlow GPU memory growth: {e}")
# else:
#     logger.info("TensorFlow: No GPUs available, using CPU.")


class VisualAnalyzer:
    def __init__(self):
        self.visual_model_name = settings.VISUAL_CNN_MODEL_NAME
        self.qdrant_url = settings.QDRANT_URL
        self.qdrant_api_key = settings.QDRANT_API_KEY
        self.qdrant_collection_visual = settings.QDRANT_COLLECTION_VISUAL

        self.cnn_model = None
        self.cnn_target_size = (224, 224) # Default, adjust per model
        self.preprocess_input_func = None
        self.embedding_dim_visual = 0

        if self.visual_model_name == 'EfficientNetV2S':
            try:
                self.cnn_model = EfficientNetV2S(weights='imagenet', include_top=False, pooling='avg')
                self.preprocess_input_func = efficientnet_preprocess_input
                # EfficientNetV2S default input size is variable, but common practice is e.g. 224x224, 384x384.
                # For feature extraction, exact input size used during pre-training might not be strictly required
                # if using pooling='avg', but consistency is good. The model handles various sizes.
                # Let's assume a common size for consistency for now.
                self.cnn_target_size = (384, 384) # A common size for EfficientNetV2S
                self.embedding_dim_visual = self.cnn_model.output_shape[-1]
                logger.info(f"CNN model '{self.visual_model_name}' loaded for VisualAnalyzer. Embedding dim: {self.embedding_dim_visual}")
            except Exception as e:
                logger.error(f"Failed to load CNN model '{self.visual_model_name}': {e}", exc_info=True)
        # Add elif for 'ResNet50' or other models if needed
        # elif self.visual_model_name == 'ResNet50':
        #     self.cnn_model = ResNet50(weights='imagenet', include_top=False, pooling='avg')
        #     self.preprocess_input_func = resnet_preprocess_input
        #     self.cnn_target_size = (224, 224)
        #     self.embedding_dim_visual = self.cnn_model.output_shape[-1]

        if not self.cnn_model:
            logger.warning("No CNN model loaded for VisualAnalyzer. Feature extraction will be unavailable.")

        try:
            self.qdrant_client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key, timeout=20)
            self._ensure_qdrant_visual_collection()
            logger.info(f"Qdrant client initialized for VisualAnalyzer. Collection: '{self.qdrant_collection_visual}'")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client or ensure visual collection: {e}", exc_info=True)
            self.qdrant_client = None
        
        logger.info("VisualAnalyzer initialized.")

    def _ensure_qdrant_visual_collection(self):
        if not self.qdrant_client or not self.embedding_dim_visual:
            logger.error("Qdrant client or visual embedding dimension not available. Cannot ensure collection.")
            return
        try:
            self.qdrant_client.get_collection(collection_name=self.qdrant_collection_visual)
            logger.debug(f"Qdrant visual collection '{self.qdrant_collection_visual}' already exists.")
        except Exception:
            logger.info(f"Qdrant visual collection '{self.qdrant_collection_visual}' not found. Creating now...")
            self.qdrant_client.create_collection(
                collection_name=self.qdrant_collection_visual,
                vectors_config=qdrant_models.VectorParams(size=self.embedding_dim_visual, distance=qdrant_models.Distance.COSINE)
                # You might want to add HNSW or other indexing params here for performance
            )
            logger.info(f"Qdrant visual collection '{self.qdrant_collection_visual}' created with dim {self.embedding_dim_visual}.")


    def _extract_cnn_features_from_frame(self, frame_np_array) -> list[float] | None:
        """Extracts CNN features from a single NumPy frame."""
        if not self.cnn_model or self.preprocess_input_func is None: return None
        try:
            # Resize frame to target size expected by CNN model
            # Ensure frame is in RGB if model expects it (OpenCV loads BGR by default)
            if frame_np_array.shape[-1] == 3: # Color image
                frame_rgb = cv2.cvtColor(frame_np_array, cv2.COLOR_BGR2RGB)
            else: # Grayscale, convert to RGB by repeating channels
                frame_rgb = cv2.cvtColor(frame_np_array, cv2.COLOR_GRAY2RGB)

            img_resized = cv2.resize(frame_rgb, self.cnn_target_size)
            img_array = keras_image.img_to_array(img_resized)
            img_array_expanded = np.expand_dims(img_array, axis=0)
            img_preprocessed = self.preprocess_input_func(img_array_expanded)
            
            features = self.cnn_model.predict(img_preprocessed)
            return features.flatten().tolist()
        except Exception as e:
            logger.error(f"Error extracting CNN features from frame: {e}", exc_info=True)
            return None

    def _calculate_perceptual_hashes(self, frame_np_array) -> dict:
        """Calculates various perceptual hashes for a frame."""
        hashes = {}
        try:
            # imagehash library expects PIL Image objects
            pil_image = Image.fromarray(cv2.cvtColor(frame_np_array, cv2.COLOR_BGR2RGB)) # Convert BGR to RGB for PIL
            hashes['average_hash'] = str(imagehash.average_hash(pil_image))
            hashes['phash'] = str(imagehash.phash(pil_image))
            hashes['dhash'] = str(imagehash.dhash(pil_image))
            hashes['whash'] = str(imagehash.whash(pil_image)) # Wavelet hash
            # hashes['colorhash'] = str(imagehash.colorhash(pil_image)) # Can be slow
        except Exception as e:
            logger.error(f"Error calculating perceptual hashes for frame: {e}", exc_info=True)
        return hashes

    def extract_features_from_query_image(self, image_path: str) -> dict:
        """
        Extracts CNN features and perceptual hashes from a static query image file.
        Returns a dict: {'cnn_embedding': [...], 'perceptual_hashes': {'phash': '...', ...}}
        """
        if not os.path.exists(image_path):
            logger.error(f"Query image path does not exist: {image_path}")
            return {}
        
        logger.debug(f"VisualAnalyzer extracting features from query image: {image_path}")
        try:
            # Load image using OpenCV (consistent with frame processing)
            frame = cv2.imread(image_path)
            if frame is None:
                logger.error(f"Failed to read query image at path: {image_path}")
                return {}

            cnn_embedding = self._extract_cnn_features_from_frame(frame)
            perceptual_hashes = self._calculate_perceptual_hashes(frame)
            
            return {
                "cnn_embedding": cnn_embedding,
                "perceptual_hashes": perceptual_hashes
            }
        except Exception as e:
            logger.error(f"Error processing query image {image_path}: {e}", exc_info=True)
            return {}


    def process_video_frames(self, video_source_model, video_file_path: str, frame_interval_sec: int = 2) -> dict:
        """
        Processes a video file: detects scenes, extracts keyframes, calculates features, and stores them.
        `video_source_model` is the Django VideoSource model instance.
        `video_file_path` is the path to the locally accessible video file.
        Returns a summary dict of processing.
        """
        from api.models import VideoFrameFeature # Import here

        logger.info(f"VisualAnalyzer: Starting frame processing for VideoSource ID {video_source_model.id} from path: {video_file_path}")
        if not os.path.exists(video_file_path):
            logger.error(f"Video file not found at path: {video_file_path} for VSID {video_source_model.id}")
            return {"error": "Video file not found.", "frames_processed": 0, "scenes_detected": 0}

        analysis_summary = {
            "frames_processed_for_features": 0,
            "scenes_detected": 0,
            "cnn_features_extracted": 0,
            "hashes_calculated": 0,
            "qdrant_points_stored": 0,
            "db_frame_features_saved": 0,
            "errors": []
        }
        
        qdrant_points_batch = []
        db_frame_features_batch = []

        try:
            video_manager = VideoManager([video_file_path])
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=27.0)) # threshold can be tuned

            # Improve efficiency by downscaling video during processing by VideoManager.
            video_manager.set_downscale_factor() # Auto-downscale based on resolution
            video_manager.start() # Start video decoding
            
            scene_manager.detect_scenes(frame_source=video_manager, show_progress=False)
            scene_list = scene_manager.get_scene_list() # List of (StartTimecode, EndTimecode)
            analysis_summary["scenes_detected"] = len(scene_list)
            logger.info(f"Detected {len(scene_list)} scenes in VSID {video_source_model.id}.")

            # Clear old frame features for this video source before adding new ones
            VideoFrameFeature.objects.filter(video_source=video_source_model).delete()
            # TODO: Also delete corresponding points from Qdrant if re-indexing
            # self.qdrant_client.delete_points(collection_name=self.qdrant_collection_visual,
            #                                 points_selector=FilterSelector(filter=Filter(must=[...video_source_db_id...])) )
            
            processed_timestamps_ms = set() # To avoid processing nearly identical frames from scene list

            # Option 1: Process middle frame of each scene
            for i, (start_time, end_time) in enumerate(scene_list):
                # Get middle frame of the scene
                middle_time_frame_obj = start_time + ((end_time.get_frames() - start_time.get_frames()) // 2)
                timestamp_ms = middle_time_frame_obj.get_timecode(precision=3).split(':') # HH:MM:SS.mmm
                timestamp_ms_int = middle_time_frame_obj.get_seconds() * 1000 + int(timestamp_ms[-1]) if len(timestamp_ms) == 4 else middle_time_frame_obj.get_seconds() * 1000

                if timestamp_ms_int in processed_timestamps_ms: continue
                processed_timestamps_ms.add(timestamp_ms_int)

                video_manager.seek(middle_time_frame_obj)
                ret, frame = video_manager.read()
                if not ret or frame is None: continue

                analysis_summary["frames_processed_for_features"] += 1
                
                # a. CNN Features
                if self.cnn_model:
                    cnn_embedding = self._extract_cnn_features_from_frame(frame)
                    if cnn_embedding:
                        analysis_summary["cnn_features_extracted"] += 1
                        qdrant_point_id = f"{video_source_model.id}_frame_cnn_{timestamp_ms_int}"
                        qdrant_points_batch.append(qdrant_models.PointStruct(
                            id=qdrant_point_id, vector=cnn_embedding,
                            payload={"video_source_db_id": str(video_source_model.id), "timestamp_ms": timestamp_ms_int, "type": "cnn_embedding", "scene_index": i}
                        ))
                        db_frame_features_batch.append(VideoFrameFeature(
                            video_source=video_source_model, timestamp_ms=timestamp_ms_int, feature_type='cnn_embedding',
                            feature_data_json={"model": self.visual_model_name, "vector_preview": cnn_embedding[:5]} # Store preview or link to Qdrant ID
                        ))
                
                # b. Perceptual Hashes
                hashes = self._calculate_perceptual_hashes(frame)
                if hashes:
                    analysis_summary["hashes_calculated"] += 1
                    # Hashes are often stored directly in relational DB as they are smaller and good for exact/near match lookups.
                    db_frame_features_batch.append(VideoFrameFeature(
                        video_source=video_source_model, timestamp_ms=timestamp_ms_int, feature_type='perceptual_hash',
                        feature_data_json=hashes
                    ))

                # Batch insert to Qdrant and DB periodically
                if len(qdrant_points_batch) >= 50:
                    if self.qdrant_client and qdrant_points_batch:
                        self.qdrant_client.upsert(collection_name=self.qdrant_collection_visual, points=qdrant_points_batch)
                        analysis_summary["qdrant_points_stored"] += len(qdrant_points_batch)
                    qdrant_points_batch = []
                if len(db_frame_features_batch) >= 100:
                    VideoFrameFeature.objects.bulk_create(db_frame_features_batch)
                    analysis_summary["db_frame_features_saved"] += len(db_frame_features_batch)
                    db_frame_features_batch = []

            # Option 2: Process frames at fixed intervals (if scene detection yields too few/many)
            # This is an alternative or supplementary to scene-based keyframes.
            # For now, focusing on scene-based. If implementing interval:
            # video_manager.reset() # Reset video_manager to start from beginning
            # total_frames = video_manager.get_num_frames()
            # fps = video_manager.get_framerate()
            # frame_skip = int(fps * frame_interval_sec)
            # for frame_num in range(0, total_frames, frame_skip):
            #     video_manager.seek(frame_num)
            #     ret, frame = video_manager.read()
            #     # ... process frame ... timestamp_ms = int(frame_num / fps * 1000)

            # Final batch insert for any remaining points/features
            if self.qdrant_client and qdrant_points_batch:
                self.qdrant_client.upsert(collection_name=self.qdrant_collection_visual, points=qdrant_points_batch)
                analysis_summary["qdrant_points_stored"] += len(qdrant_points_batch)
            if db_frame_features_batch:
                VideoFrameFeature.objects.bulk_create(db_frame_features_batch)
                analysis_summary["db_frame_features_saved"] += len(db_frame_features_batch)

            video_manager.release() # Release video resource

        except Exception as e:
            logger.error(f"Error during visual processing of VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_summary["errors"].append(f"Visual processing failed: {str(e)}")
            if 'video_manager' in locals() and video_manager.is_started():
                video_manager.release()

        logger.info(f"VisualAnalyzer: Finished frame processing for VSID {video_source_model.id}. Summary: {analysis_summary}")
        return analysis_summary
