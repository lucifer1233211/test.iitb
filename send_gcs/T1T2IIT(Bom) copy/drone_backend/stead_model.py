import numpy as np
import cv2

try:
    import onnxruntime as ort
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

class STEADPredictor:
    def __init__(self, model_path="models/stead_mobile_v1.onnx"):
        self.model_path = model_path
        self.session = None
        if HAS_ONNX:
            try:
                # In a real environment, you should use GPU or TensorRT: 
                # providers=['TensorrtExecutionProvider', 'CUDAExecutionProvider']
                self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                self.input_name = self.session.get_inputs()[0].name
                print(f"[STEAD] Successfully loaded ONNX model from {model_path}")
            except Exception as e:
                print(f"[STEAD] Could not load ONNX model. Ensure {model_path} exists. Simulation mode active.")
                self.session = None
        else:
            print("[STEAD] ONNX Runtime not installed. Using simulated STEAD inference.")
    
    def preprocess(self, frame_buffer):
        """
        STEAD typically analyzes a temporal window of frames simultaneously.
        This function resizes, normalizes, and reshapes the buffer into a 
        Spatio-Temporal Tensor [Batch, Channels, Time, Height, Width].
        """
        processed = []
        for frame in frame_buffer:
            # Resize to standard model input (e.g., 224x224)
            resized = cv2.resize(frame, (224, 224))
            # Convert BGR to RGB
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            # Normalize to [0, 1]
            norm = rgb.astype(np.float32) / 255.0
            # Optional: Subtract mean / divide by std deviation here
            processed.append(norm)
        
        # Shape is currently: [Time, H, W, C]
        tensor = np.array(processed)
        
        # Transpose to: [C, Time, H, W] (PyTorch 3D-Conv standard)
        tensor = np.transpose(tensor, (3, 0, 1, 2))
        
        # Add batch dimension: [1, C, Time, H, W]
        tensor = np.expand_dims(tensor, axis=0)
        return tensor

    def infer(self, frame_buffer) -> float:
        """
        Runs the hardware-accelerated ONNX model to generate an anomaly score.
        Fallback to simulated beta distribution if model fails or is missing.
        """
        if self.session is None:
            # Simulated Spatio-Temporal predictive output
            return float(np.random.beta(0.5, 2.0))
        
        try:
            input_tensor = self.preprocess(frame_buffer)
            # Run inference. Output is assumes to be [Batch, 1] for Anomaly Probability
            outputs = self.session.run(None, {self.input_name: input_tensor})
            anomaly_score = float(outputs[0][0][0]) 
            return anomaly_score
        except Exception as e:
            print(f"[STEAD INFERENCE ERROR] {e}. Falling back to simulation.")
            return float(np.random.beta(0.5, 2.0))
