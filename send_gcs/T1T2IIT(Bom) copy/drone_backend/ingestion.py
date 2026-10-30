import cv2
import numpy as np
import time
import requests

from stead_model import STEADPredictor

try:
    from submodlib.functions.facilityLocation import FacilityLocationFunction
    from sklearn.metrics.pairwise import euclidean_distances
    HAS_SUBMODLIB = True
except ImportError:
    HAS_SUBMODLIB = False
    print("Warning: submodlib or sklearn not installed. Falling back to random sampling.")

class DroneIngestionPipeline:
    def __init__(self, rtsp_url="0", backend_url="http://localhost:8001/api/cortex/synthesize", model_path="models/stead_mobile_v1.onnx"):
        # Accessing the webcam or RTSP feed (e.g. "rtsp://192.168.1.10:554/stream")
        self.cap = cv2.VideoCapture(rtsp_url)
        self.frame_buffer = []
        self.backend_url = backend_url
        self.buffer_size = 30 # Accumulate 30 frames before Submodular sampling
        self.stead_predictor = STEADPredictor(model_path)

    def get_informative_frame(self):
        """
        Uses submodlib's Facility Location optimization to select the most
        informative frame from the buffer, maximizing diversity and representation.
        """
        if not HAS_SUBMODLIB or len(self.frame_buffer) == 0:
            return self.frame_buffer[np.random.randint(0, len(self.frame_buffer))]

        # 1. Feature Extraction: Resize and flatten frames for similarity computation
        # In a real scenario, you'd extract latent embeddings from a CNN (like MobileNet)
        features = []
        for frame in self.frame_buffer:
            # Resize drastically to reduce computation for the similarity matrix
            small_frame = cv2.resize(frame, (64, 64))
            features.append(small_frame.flatten())
            
        X = np.array(features)
        
        # 2. Compute similarity matrix (Kernel)
        # Using negative Euclidean distance mapped to [0, 1] as a basic similarity measure
        distances = euclidean_distances(X)
        max_dist = np.max(distances)
        if max_dist == 0:
            similarities = np.ones_like(distances)
        else:
            similarities = 1 - (distances / max_dist)
            
        # 3. Apply Facility Location Function
        n = len(self.frame_buffer)
        
        # separate_rep=False indicates that the data points and the repr points are the same
        obj = FacilityLocationFunction(n=n, mode="dense", sijs=similarities, separate_rep=False)
        
        # Maximize the submodular function to select the best greedily
        subset_size = 1
        greedy_list = obj.maximize(budget=subset_size, optimizer='NaiveGreedy', stopIfZeroGain=False, stopIfNegativeGain=False, verbose=False)
        
        # greedy_list returns a list of tuples: (index, utility_gain)
        best_frame_idx = greedy_list[0][0]
        print(f"[SUBMODLIB] Selected frame '{best_frame_idx}' as most representative of the {self.buffer_size}-frame sequence.")
        
        return self.frame_buffer[best_frame_idx]

    def run(self):
        print("Starting drone ingestion pipeline...")
        while self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                break
            
            # 1. Accumulate frames into buffer
            self.frame_buffer.append(frame)

            if len(self.frame_buffer) >= self.buffer_size:
                print(f"[PIPELINE] Buffer Full ({self.buffer_size} frames). Processing...")
                
                # 2. Informative Frame Distillation (Submodlib representation)
                # We select the most representative frame to send to Cortex/Ground Station
                selected_frame = self.get_informative_frame()
                
                # 3. Pass to STEAD Local Reflex Model (Temporal Analysis)
                # Unlike simple frame analysis, STEAD uses the whole temporal buffer
                score = self.stead_predictor.infer(self.frame_buffer)
                print(f"[STEAD] Reflex Score Calculated: {score:.3f}")
                
                # 4. Trigger Cortex if anomaly passes threshold
                if score > 0.85:
                    print(f"--> [ANOMALY DETECTED] Threshold Exceeded! Triggering Cortex...")
                    self.trigger_cortex(score)

                # Clear buffer for next cycle
                self.frame_buffer.clear()
            
            time.sleep(0.03) # Simulating ~30FPS limit

    def trigger_cortex(self, score: float):
        try:
            res = requests.post(self.backend_url, json={
                "id": f"trigger_{int(time.time())}", 
                "score": score, 
                "timestamp": time.time()
            })
            print("\n[CORTEX RESPONSE]:", res.json(), "\n")
        except requests.exceptions.RequestException as e:
            print("[CORTEX ERROR]: Cortex node offline or unreachable:", e)

if __name__ == "__main__":
    pipeline = DroneIngestionPipeline()
    try:
        pipeline.run()
    except KeyboardInterrupt:
        print("Ingestion stopped.")
