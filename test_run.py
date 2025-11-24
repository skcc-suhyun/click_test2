#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

# 강제로 출력 버퍼링 비활성화
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)

print("=" * 100, flush=True)
print("🧪 메뉴얼 에이전트 - 스크린샷 기반 화면 그룹핑 & 좌표/API 로직 검증 (test2)", flush=True)
print("=" * 100, flush=True)

json_path = 'data/actions/metadata_182.json'
print(f"  ▸ JSON 파일: {json_path}", flush=True)
print(f"  ▸ pHash 임계값: 18", flush=True)
print(f"  ▸ SSIM 임계값: 0.95", flush=True)
print("=" * 100, flush=True)

try:
    from pages.test2 import UIScreenshotAnalyzer
    
    analyzer = UIScreenshotAnalyzer(
        json_path=json_path,
        phash_threshold=18,
        ssim_threshold=0.95,
    )
    
    analyzer.load_actions()
    analyzer.collect_screenshot_paths()
    analyzer.load_images_and_hashes()
    analyzer.cluster_images()
    analyzer.build_screen_summary()
    analyzer.print_summary()
    
    print("\n✅ test2 로직 검증 완료!", flush=True)
    
except Exception as e:
    print(f"\n❌ 에러 발생: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

