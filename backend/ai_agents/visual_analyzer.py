# backend/ai_agents/visual_analyzer.py
import logging
import os
import cv2 # OpenCV for video processing
import imagehash # type: ignore
import numpy as np
from PIL import Image
from tensorflow.keras.applications import EfficientNetV2S
from tensorflow.keras.preprocessing import image as keras_image
from tensorflow.keras.applications.efficientnet_v2 import preprocess_input as efficientnet_preprocess_input

from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector

from django.conf import settings
from qdrant_client import QdrantClient, models as qdrant_models, QdrantClientException

logger = logging.getLogger(__name__)

class VisualAnalyzer:
    def __init__(self):
        self.visual_model_name = settings.VISUAL_CNN_MODEL_NAME
        
        self.qdrant_host = settings.QDRANT_HOST
        self.qdrant_port = settings.QDRANT_PORT
        self.qdrant_url = settings.QDRANT_URL
        self.qdrant_api_key = settings.QDRANT_API_KEY
        self.qdrant_prefer_grpc = settings.QDRANT_PREFER_GRPC
        self.qdrant_timeout = settings.QDRANT_TIMEOUT_SECONDS
        self.qdrant_collection_visual = settings.QDRANT_COLLECTION_VISUAL
        self.image_embedding_dim = settings.IMAGE_EMBEDDING_DIMENSION 

        self.cnn_model = None
        self.cnn_target_size = (224, 224)
        self.preprocess_input_func = None
        
        # Scene detection parameters from settings
        self.pyscenedetect_threshold = getattr(settings, 'PYSCENEDETECT_THRESHOLD', 27.0)
        self.pyscenedetect_min_scene_len = getattr(settings, 'PYSCENEDETECT_MIN_SCENE_LEN', 15) # In frames

        if self.visual_model_name == 'EfficientNetV2S':
            try:
                self.cnn_model = EfficientNetV2S(weights='imagenet', include_top=False, pooling='avg')
                self.preprocess_input_func = efficientnet_preprocess_input
                self.cnn_target_size = (384, 384) 
                model_dim = self.cnn_model.output_shape[-1]
                if model_dim != self.image_embedding_dim:
                    logger.warning(f"EfficientNetV2S output dim ({model_dim}) differs from settings.IMAGE_EMBEDDING_DIMENSION ({self.image_embedding_dim}). Using model's dim.")
                    self.image_embedding_dim = model_dim
                logger.info(f"CNN model '{self.visual_model_name}' loaded (Dim: {self.image_embedding_dim}).")
            except Exception as e:
                logger.error(f"Failed to load CNN model '{self.visual_model_name}': {e}", exc_info=True)
                self.cnn_model = None
        
        if not self.cnn_model:
            logger.warning("No CNN model loaded for VisualAnalyzer. Visual CNN feature extraction will be unavailable.")

        try:
            self.qdrant_client = QdrantClient(
                url=self.qdrant_url,
                port=self.qdrant_port if not self.qdrant_url.startswith("http") else None,
                grpc_port=settings.QDRANT_GRPC_PORT if self.qdrant_prefer_grpc else None,
                prefer_grpc=self.qdrant_prefer_grpc,
                api_key=self.qdrant_api_key,
                timeout=self.qdrant_timeout
            )
            self.qdrant_client.health_check()
            self._ensure_qdrant_visual_collection()
            logger.info(f"Qdrant client initialized for VisualAnalyzer. Collection: '{self.qdrant_collection_visual}' at {self.qdrant_url}")
        except QdrantClientException as qe:
            logger.error(f"Qdrant client initialization error (QdrantClientException): {qe}", exc_info=True)
            self.qdrant_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client or ensure visual collection: {e}", exc_info=True)
            self.qdrant_client = None
        
        logger.info(f"VisualAnalyzer initialized. PySceneDetect Threshold: {self.pyscenedetect_threshold}, Min Scene Len: {self.pyscenedetect_min_scene_len} frames.")

    def _ensure_qdrant_visual_collection(self):
        # (Content of _ensure_qdrant_visual_collection from previous refinement)
        if not self.qdrant_client:
            logger.error("Qdrant client not available. Cannot ensure visual collection.")
            return
        if not self.image_embedding_dim or self.image_embedding_dim == 0:
            logger.error(f"Invalid IMAGE_EMBEDDING_DIMENSION ({self.image_embedding_dim}). Cannot create/verify Qdrant visual collection.")
            return
            
        try:
            self.qdrant_client.get_collection(collection_name=self.qdrant_collection_visual)
            logger.debug(f"Qdrant visual collection '{self.qdrant_collection_visual}' already exists.")
        except QdrantClientException as qe:
            if "not found" in str(qe).lower() or (hasattr(qe, 'status_code') and qe.status_code == 404):
                logger.info(f"Qdrant visual collection '{self.qdrant_collection_visual}' not found. Creating now...")
                try:
                    self.qdrant_client.create_collection(
                        collection_name=self.qdrant_collection_visual,
                        vectors_config=qdrant_models.VectorParams(size=self.image_embedding_dim, distance=qdrant_models.Distance.COSINE),
                    )
                    logger.info(f"Qdrant visual collection '{self.qdrant_collection_visual}' created with dim {self.image_embedding_dim}.")
                except Exception as e_create:
                     logger.error(f"Failed to create Qdrant visual collection '{self.qdrant_collection_visual}': {e_create}", exc_info=True)
            else:
                 logger.error(f"Qdrant client error when checking visual collection '{self.qdrant_collection_visual}': {qe}", exc_info=True)
        except Exception as e:
             logger.error(f"Unexpected error ensuring Qdrant visual collection '{self.qdrant_collection_visual}': {e}", exc_info=True)


    def _extract_cnn_features_from_frame(self, frame_np_array: np.ndarray) -> Optional[list[float]]:
        # (Content from previous refinement)
        if not self.cnn_model or self.preprocess_input_func is None: return None
        try:
            if frame_np_array.shape[-1] == 3: frame_rgb = cv2.cvtColor(frame_np_array, cv2.COLOR_BGR2RGB)
            else: frame_rgb = cv2.cvtColor(frame_np_array, cv2.COLOR_GRAY2RGB)
            img_resized = cv2.resize(frame_rgb, self.cnn_target_size)
            img_array = keras_image.img_to_array(img_resized)
            img_array_expanded = np.expand_dims(img_array, axis=0)
            img_preprocessed = self.preprocess_input_func(img_array_expanded)
            features = self.cnn_model.predict(img_preprocessed, verbose=0)
            return features.flatten().tolist()
        except Exception as e:
            logger.error(f"Error extracting CNN features from frame: {e}", exc_info=True)
            return None

    def _calculate_perceptual_hashes(self, frame_np_array: np.ndarray) -> dict:
        # (Content from previous refinement)
        hashes = {}
        try:
            pil_image = Image.fromarray(cv2.cvtColor(frame_np_array, cv2.COLOR_BGR2RGB))
            hashes['average_hash'] = str(imagehash.average_hash(pil_image))
            hashes['phash'] = str(imagehash.phash(pil_image))
            hashes['dhash'] = str(imagehash.dhash(pil_image))
            hashes['whash'] = str(imagehash.whash(pil_image))
        except Exception as e:
            logger.error(f"Error calculating perceptual hashes for frame: {e}", exc_info=True)
        return hashes
        
    def extract_features_from_query_image(self, image_path: str) -> dict:
        # (Content from previous refinement)
        if not os.path.exists(image_path):
            logger.error(f"Query image path does not exist: {image_path}")
            return {}
        logger.debug(f"VisualAnalyzer extracting features from query image: {image_path}")
        try:
            frame = cv2.imread(image_path)
            if frame is None:
                logger.error(f"Failed to read query image at path: {image_path}")
                return {}
            cnn_embedding = self._extract_cnn_features_from_frame(frame)
            perceptual_hashes = self._calculate_perceptual_hashes(frame)
            return {"cnn_embedding": cnn_embedding, "perceptual_hashes": perceptual_hashes}
        except Exception as e:
            logger.error(f"Error processing query image {image_path}: {e}", exc_info=True)
            return {}

    def process_video_frames(self, video_source_model: Any, video_file_path: str) -> dict: # Removed frame_interval_sec, use settings
        from api.models import VideoFrameFeature # Import here
        logger.info(f"VisualAnalyzer: Starting frame processing for VSID {video_source_model.id} from: {video_file_path}")
        # ... (rest of the method is largely the same as refined previously for Qdrant) ...
        # Key change: Use self.pyscenedetect_threshold and self.pyscenedetect_min_scene_len
        
        analysis_summary = {
            "frames_processed_for_features": 0, "scenes_detected": 0,
            "cnn_features_extracted": 0, "hashes_calculated": 0,
            "qdrant_points_stored": 0, "db_frame_features_saved": 0, "status": "pending", "errors": []
        }
        qdrant_points_batch = []
        db_frame_features_batch = []
        video_manager = None

        try:
            video_manager = VideoManager([video_file_path])
            scene_manager = SceneManager()
            # Use tunable parameters from settings
            scene_manager.add_detector(ContentDetector(threshold=self.pyscenedetect_threshold, min_scene_len=self.pyscenedetect_min_scene_len))
            video_manager.set_downscale_factor() 
            video_manager.start()
            scene_manager.detect_scenes(frame_source=video_manager, show_progress=False)
            scene_list = scene_manager.get_scene_list() 
            analysis_summary["scenes_detected"] = len(scene_list)
            logger.info(f"Detected {len(scene_list)} scenes in VSID {video_source_model.id} using threshold {self.pyscenedetect_threshold}.")

            # ... (rest of the loop and batch insert logic as in previous refined version of this method) ...
            # (Ensure VideoFrameFeature.timestamp_ms is used consistently as renamed in api.models.py)
            VideoFrameFeature.objects.filter(video_source=video_source_model).delete()
            if self.qdrant_client:
                try:
                    self.qdrant_client.delete(
                        collection_name=self.qdrant_collection_visual,
                        points_selector=qdrant_models.FilterSelector(filter=qdrant_models.Filter(must=[
                            qdrant_models.FieldCondition(key="video_source_db_id", match=qdrant_models.MatchValue(value=str(video_source_model.id)))
                        ]))
                    )
                except Exception as e_del_qdrant: logger.warning(f"Could not clear old Qdrant visual points for VSID {video_source_model.id}: {e_del_qdrant}")
            
            processed_timestamps_ms = set() 
            for i, (start_time, end_time) in enumerate(scene_list):
                middle_time_frame_obj = start_time + ((end_time.get_frames() - start_time.get_frames()) // 2)
                try:
                    ts_parts = middle_time_frame_obj.get_timecode(precision=3).split(':')
                    timestamp_ms_int = int(float(ts_parts[0])*3600*1000 + float(ts_parts[1])*60*1000 + float(ts_parts[2])*1000 + float(ts_parts[3])) if len(ts_parts) == 4 else int(middle_time_frame_obj.get_seconds() * 1000)
                except Exception: timestamp_ms_int = int(middle_time_frame_obj.get_seconds() * 1000)

                if timestamp_ms_int in processed_timestamps_ms: continue
                processed_timestamps_ms.add(timestamp_ms_int)
                video_manager.seek(middle_time_frame_obj)
                ret, frame = video_manager.read()
                if not ret or frame is None: continue
                analysis_summary["frames_processed_for_features"] += 1
                
                if self.cnn_model:
                    cnn_embedding = self._extract_cnn_features_from_frame(frame)
                    if cnn_embedding:
                        analysis_summary["cnn_features_extracted"] += 1
                        qdrant_point_id = f"{video_source_model.id}_frame_cnn_{timestamp_ms_int}"
                        qdrant_points_batch.append(qdrant_models.PointStruct(
                            id=qdrant_point_id, vector=cnn_embedding,
                            payload={"video_source_db_id": str(video_source_model.id), "timestamp_ms": timestamp_ms_int, "type": "cnn_embedding", "scene_idx": i}
                        ))
                        db_frame_features_batch.append(VideoFrameFeature(
                            video_source=video_source_model, timestamp_ms=timestamp_ms_int, feature_type='cnn_embedding', # Changed field name
                            vector_db_id=qdrant_point_id, feature_data_json={"model": self.visual_model_name} 
                        ))
                
                hashes = self._calculate_perceptual_hashes(frame)
                if hashes:
                    analysis_summary["hashes_calculated"] += 1
                    db_frame_features_batch.append(VideoFrameFeature(
                        video_source=video_source_model, timestamp_ms=timestamp_ms_int, feature_type='perceptual_hash', # Changed field name
                        feature_data_json=hashes, hash_value = hashes.get('phash') 
                    ))

                if len(qdrant_points_batch) >= 50 and self.qdrant_client:
                    self.qdrant_client.upsert(collection_name=self.qdrant_collection_visual, points=qdrant_points_batch, wait=False)
                    analysis_summary["qdrant_points_stored"] += len(qdrant_points_batch); qdrant_points_batch = []
                if len(db_frame_features_batch) >= 100:
                    VideoFrameFeature.objects.bulk_create(db_frame_features_batch, ignore_conflicts=True)
                    analysis_summary["db_frame_features_saved"] += len(db_frame_features_batch); db_frame_features_batch = []
            
            if self.qdrant_client and qdrant_points_batch:
                self.qdrant_client.upsert(collection_name=self.qdrant_collection_visual, points=qdrant_points_batch, wait=True)
                analysis_summary["qdrant_points_stored"] += len(qdrant_points_batch)
            if db_frame_features_batch:
                VideoFrameFeature.objects.bulk_create(db_frame_features_batch, ignore_conflicts=True)
                analysis_summary["db_frame_features_saved"] += len(db_frame_features_batch)
            analysis_summary["status"] = "completed"

        except QdrantClientException as qe: # More specific handling for Qdrant
            logger.error(f"QdrantClientException during visual processing of VSID {video_source_model.id}: {qe}", exc_info=True)
            analysis_summary["errors"].append(f"Qdrant error: {str(qe)}")
            analysis_summary["status"] = "failed_qdrant_error"
        except Exception as e:
            logger.error(f"Error during visual processing of VSID {video_source_model.id}: {e}", exc_info=True)
            analysis_summary["errors"].append(f"Visual processing failed: {str(e)}")
            analysis_summary["status"] = "failed_general_error"
        finally:
            if video_manager and video_manager.is_started():
                video_manager.release()

        logger.info(f"VisualAnalyzer: Finished for VSID {video_source_model.id}. Summary: {analysis_summary}")
        return analysis_summary
