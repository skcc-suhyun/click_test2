import sys
import os
sys.path.append('.')

try:
    from pages import test2
    print("✅ test2 모듈 import 성공")
    
    # main 함수 직접 호출 테스트
    import argparse
    args = argparse.Namespace(
        json='data/actions/metadata_182.json',
        phash_threshold=18,
        ssim_threshold=0.95
    )
    
    # analyzer 생성 및 실행
    analyzer = test2.UIScreenshotAnalyzer(
        json_path=args.json,
        phash_threshold=args.phash_threshold,
        ssim_threshold=args.ssim_threshold,
    )
    
    analyzer.load_actions()
    analyzer.collect_screenshot_paths()
    analyzer.load_images_and_hashes()
    analyzer.cluster_images()
    analyzer.build_screen_summary()
    analyzer.print_summary()
    
    print("\n✅ test2 로직 검증 완료!")
    
except Exception as e:
    print(f"❌ 에러 발생: {e}")
    import traceback
    traceback.print_exc()

