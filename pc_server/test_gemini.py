import os
import sys
from PIL import Image, ImageDraw
from dotenv import load_dotenv

# Ensure we can load modules from pc_server
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environmental variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from gemini_fallback import get_gemini_fallback

def create_dummy_image():
    # Create a 224x224 green image (representing a plastic bottle)
    img = Image.new("RGB", (224, 224), color=(0, 200, 100))
    d = ImageDraw.Draw(img)
    d.text((10, 10), "Test plastic bottle", fill=(255, 255, 255))
    return img

def main():
    print("Initializing Gemini Fallback...")
    gemini = get_gemini_fallback()
    
    if not gemini.is_available():
        print("Gemini Fallback is not available (check GOOGLE_API_KEY).")
        return
        
    print("Creating dummy test image...")
    img = create_dummy_image()
    
    print("Invoking classify...")
    result = gemini.classify(img, local_label="plastic", local_confidence=0.3)
    
    print("\nResult:")
    for k, v in result.items():
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
