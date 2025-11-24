import sys

print("라이브러리 확인 중...")

try:
    from PIL import Image
    print("✅ PIL (Pillow) 설치됨")
except Exception as e:
    print(f"❌ PIL 에러: {e}")

try:
    import imagehash
    print("✅ imagehash 설치됨")
except Exception as e:
    print(f"❌ imagehash 에러: {e}")

try:
    from skimage.metrics import structural_similarity
    print("✅ scikit-image 설치됨")
except Exception as e:
    print(f"❌ scikit-image 에러: {e}")
    print("   설치 필요: pip install scikit-image")

try:
    import numpy as np
    print("✅ numpy 설치됨")
except Exception as e:
    print(f"❌ numpy 에러: {e}")

sys.stdout.flush()

