import requests
import base64
import json
import numpy as np
from PIL import Image
import io
import soundfile as sf

def load_image(image_path=None):
    """Load an image from path or create a random dummy one"""
    if image_path:
        print(f"Loading image from: {image_path}")
        try:
            img = Image.open(image_path)
            # Resize to ensure consistency (server handles resizing too, but good practice)
            img = img.resize((224, 224))
        except Exception as e:
            print(f"Error loading image: {e}")
            print("Falling back to dummy image...")
            return create_dummy_image()
    else:
        print("No image path provided. Generating dummy image...")
        # Create random image
        img_array = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)
    
    # Compress to JPEG
    buffer = io.BytesIO()
    img.convert('RGB').save(buffer, format="JPEG")
    img_bytes = buffer.getvalue()
    
    # Encode to base64
    return base64.b64encode(img_bytes).decode('utf-8')

def create_dummy_image():
    # Helper for fallback
    img_array = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
    img = Image.fromarray(img_array)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def create_dummy_audio():
    """Create a random 2-second audio clip and return as base64 string"""
    print("Generating dummy audio...")
    # Create random noise (2 seconds at 22050Hz)
    sr = 22050
    duration = 2.0
    t = np.linspace(0, duration, int(sr * duration))
    # Generate a simple sine wave + noise
    audio_data = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.normal(0, 1, t.shape)
    
    # Save to WAV buffer
    buffer = io.BytesIO()
    sf.write(buffer, audio_data, sr, format='WAV')
    audio_bytes = buffer.getvalue()
    
    # Encode to base64
    return base64.b64encode(audio_bytes).decode('utf-8')

def test_predict(image_path=None):
    url = "http://localhost:5000/predict"
    
    try:
        # Prepare payload
        payload = {
            "event_id": "test_001",
            "image": load_image(image_path),  # Changed function call
            "audio": create_dummy_audio(),
            "timestamp": 1234567890.0
        }
        
        print(f"\nSending request to {url}...")
        headers = {'Content-Type': 'application/json'}
        
        # Send POST request
        response = requests.post(url, json=payload, headers=headers)
        
        print(f"Status Code: {response.status_code}")
        print("\nResponse Body:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to the server.")
        print("Make sure the server is running on localhost:5000")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    import sys
    # Check if user provided an image path argument
    img_path = sys.argv[1] if len(sys.argv) > 1 else None
    test_predict(img_path)
