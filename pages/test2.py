#!/usr/bin/env python3
"""
test2.py - 메뉴얼 에이전트 시각화/좌표 개발용 통합 로직 테스트 스크립트

기능:
- actions JSON을 읽어서
- 스크린샷 경로 추출
- 이미지 기반 화면 그룹핑 (pHash + SSIM)
- 각 그룹(화면)에 포함된 액션/좌표/API URL 요약
- 터미널에 예쁘게 출력

UI/서버/React 완전 분리, 순수 로직 검증용 스크립트.
"""

import sys
import os
import json
import argparse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 상위 디렉터리를 sys.path에 추가 (modules.loader 사용 위해)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 외부 라이브러리
from PIL import Image
import imagehash
import numpy as np
from skimage.metrics import structural_similarity as ssim

# 프로젝트 내부 로더 (가정)
from modules.loader import load_actions


# =========================
# 데이터 모델 정의
# =========================

@dataclass
class Action:
    """한 개의 test_execution_action 레코드를 표현하는 모델"""
    action_id: int
    execution_id: Optional[int]
    sequence: Optional[int]
    action_type: Optional[str]
    screenshot_path: Optional[str]
    coordinates: Optional[Dict[str, Any]] = None
    http_url: Optional[str] = None
    screen_name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenCluster:
    """한 화면(클러스터) 정보를 표현"""
    cluster_id: int
    representative_image: str
    image_paths: List[str]
    actions: List[Action]


# =========================
# 유틸 함수
# =========================

def load_image(path: str, size: Tuple[int, int] = (384, 384)) -> Optional[Image.Image]:
    """이미지 로드 + RGB + 리사이즈"""
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGB")
        if size:
            img = img.resize(size)
        return img
    except Exception as e:
        print(f"⚠️ 이미지 로드 실패: {path} - {e}")
        return None


def compute_phash(img: Image.Image) -> Optional[imagehash.ImageHash]:
    """pHash 계산"""
    if img is None:
        return None
    try:
        return imagehash.phash(img)
    except Exception:
        return None


def phash_distance(h1: Optional[imagehash.ImageHash],
                   h2: Optional[imagehash.ImageHash]) -> float:
    """pHash 간 거리 계산 (헤밍 거리)"""
    if h1 is None or h2 is None:
        return float("inf")
    return h1 - h2


def calc_ssim(img1: Optional[Image.Image],
              img2: Optional[Image.Image]) -> float:
    """두 이미지 간 SSIM 계산 (0~1)"""
    if img1 is None or img2 is None:
        return 0.0
    try:
        a1 = np.asarray(img1.convert("L"), dtype=np.float32)
        a2 = np.asarray(img2.convert("L"), dtype=np.float32)
        score, _ = ssim(a1, a2, full=True)
        return float(score)
    except Exception:
        return 0.0


def safe_parse_metadata(metadata: Any) -> Dict[str, Any]:
    """
    metadata가 dict일 수도 있고 JSON string일 수도 있다고 가정하고,
    dict로 안전하게 파싱.
    """
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except json.JSONDecodeError:
            return {}
    return {}


# =========================
# 메인 분석 클래스
# =========================

class UIScreenshotAnalyzer:
    """
    메뉴얼 에이전트용 스크린샷/좌표/액션 통합 분석기
    - actions JSON 기반
    - 이미지 기반 화면 그룹핑
    - 화면별 클릭좌표 및 API URL 요약
    """

    def __init__(
        self,
        json_path: str,
        phash_threshold: int = 18,
        ssim_threshold: float = 0.95,
        filter_no_clicks: bool = True
    ) -> None:
        self.json_path = json_path
        self.phash_threshold = phash_threshold
        self.ssim_threshold = ssim_threshold
        self.filter_no_clicks = filter_no_clicks

        self.actions: List[Action] = []
        self.image_paths: List[str] = []
        self.images: Dict[str, Image.Image] = {}
        self.hashes: Dict[str, imagehash.ImageHash] = {}
        self.clusters: List[ScreenCluster] = []

    # ---------- 1. 액션 로드 ----------

    def load_actions(self) -> None:
        """JSON 파일에서 액션 로드 + Action 모델 리스트로 변환"""
        print(f"[1/6] 액션 로드 중... ({self.json_path})")
        raw_actions = load_actions(self.json_path)

        result: List[Action] = []
        for raw in raw_actions:
            metadata = safe_parse_metadata(raw.get("metadata"))

            # 스크린샷 경로 (우선순위: screenshot_real_path > screenshot_path)
            screenshot_path = (
                raw.get("screenshot_real_path")
                or raw.get("screenshot_path")
                or metadata.get("screenshot_real_path")
                or metadata.get("screenshot_path")
            )

            # 좌표
            coordinates = raw.get("coordinates") or metadata.get("coordinates")

            # URL (request 타입일 때 주로 의미 있음)
            http_url = raw.get("http_url") or metadata.get("http_url")

            action = Action(
                action_id=raw.get("action_id"),
                execution_id=raw.get("execution_id"),
                sequence=raw.get("action_sequence"),
                action_type=raw.get("action_type"),
                screenshot_path=screenshot_path,
                coordinates=coordinates,
                http_url=http_url,
                screen_name=raw.get("screen_name"),
                raw=raw,
            )
            result.append(action)

        self.actions = result
        print(f"  ✅ 액션 {len(self.actions)}개 로드 완료")

    # ---------- 2. 스크린샷 경로 수집 ----------

    def collect_screenshot_paths(self) -> None:
        """액션에서 실제 존재하는 스크린샷 경로만 수집"""
        print("[2/6] 스크린샷 경로 수집 중...")
        paths = []
        missing = 0

        for ac in self.actions:
            if not ac.screenshot_path:
                continue
            if os.path.exists(ac.screenshot_path):
                if ac.screenshot_path not in paths:
                    paths.append(ac.screenshot_path)
            else:
                missing += 1

        paths.sort()
        self.image_paths = paths
        print(f"  ✅ 유효한 이미지 경로: {len(self.image_paths)}개")
        if missing:
            print(f"  ⚠️ 존재하지 않는 스크린샷 경로: {missing}개 (무시됨)")

    # ---------- 3. 이미지 로드 + pHash 계산 ----------

    def load_images_and_hashes(self) -> None:
        """이미지 로드 및 pHash 계산"""
        print("[3/6] 이미지 로드 및 pHash 계산 중...")
        images: Dict[str, Image.Image] = {}
        hashes: Dict[str, imagehash.ImageHash] = {}

        total = len(self.image_paths)
        for idx, path in enumerate(self.image_paths, 1):
            img = load_image(path)
            if img is None:
                continue

            images[path] = img
            hashes[path] = compute_phash(img)

            if total > 0 and idx % max(1, total // 10) == 0:
                print(f"  - 진행률: {idx}/{total} ({idx / total * 100:.1f}%)")

        self.images = images
        self.hashes = hashes
        print(f"  ✅ 이미지 로드: {len(self.images)}개, pHash 계산 완료")

    # ---------- 4. 이미지 클러스터링 ----------

    def cluster_images(self) -> None:
        """
        pHash + SSIM 기반 그리디 클러스터링
        - 기준 이미지 하나 잡고, 나머지와 비교하면서 같은 그룹에 편입
        """
        print("[4/6] 이미지 클러스터링 중...")
        clusters: List[Dict[str, Any]] = []
        used: set[str] = set()

        total = len(self.image_paths)
        for idx, base_path in enumerate(self.image_paths, 1):
            if base_path in used:
                continue
            if base_path not in self.images:
                continue

            base_img = self.images[base_path]
            base_hash = self.hashes.get(base_path)

            # 새 클러스터 생성
            cluster_paths = [base_path]
            used.add(base_path)

            # 다른 이미지들과 비교
            for other_path in self.image_paths:
                if other_path == base_path or other_path in used:
                    continue
                if other_path not in self.images:
                    continue

                other_img = self.images[other_path]
                other_hash = self.hashes.get(other_path)

                distance = phash_distance(base_hash, other_hash)
                ssim_score = calc_ssim(base_img, other_img)

                if distance <= self.phash_threshold or ssim_score >= self.ssim_threshold:
                    cluster_paths.append(other_path)
                    used.add(other_path)

            clusters.append(
                {
                    "representative_image": base_path,
                    "image_paths": cluster_paths,
                }
            )

            if total > 0 and idx % max(1, total // 10) == 0:
                print(f"  - 기준 이미지 진행률: {idx}/{total} ({idx / total * 100:.1f}%)")

        # ScreenCluster 객체로 변환은 build_screen_summary()에서 처리
        print(f"  ✅ 클러스터 {len(clusters)}개 생성 완료")
        # 임시로 저장
        self._raw_clusters = clusters  # type: ignore[attr-defined]

    # ---------- 5. 순서 기반 플로우 생성 및 화면 전환 감지 ----------

    def build_screen_summary(self) -> None:
        """
        순서 기반 플로우 생성 및 화면 전환 감지
        1) 액션 순서 보존하여 1차 플로우 생성
        2) Flow 안에서 화면 전환 신호 감지해서 재분할
        3) 묶음의 대표 화면 = 항상 마지막 화면
        """
        print("[5/6] 순서 기반 플로우 생성 및 화면 전환 감지 중...")

        # 1) 액션을 sequence 순서대로 정렬 (순서 보존 필수)
        sorted_actions = sorted(
            [a for a in self.actions if a.screenshot_path and os.path.exists(a.screenshot_path)],
            key=lambda a: (
                a.sequence if a.sequence is not None else float('inf'),
                a.action_id if a.action_id is not None else float('inf')
            )
        )

        if not sorted_actions:
            self.clusters = []
            print("  ⚠️ 스크린샷이 있는 액션이 없습니다.")
            return

        # 2) 순서대로 플로우 생성하면서 화면 전환 감지
        flows: List[List[Action]] = []
        current_flow: List[Action] = [sorted_actions[0]]

        for i in range(1, len(sorted_actions)):
            prev_action = sorted_actions[i - 1]
            curr_action = sorted_actions[i]

            prev_path = prev_action.screenshot_path
            curr_path = curr_action.screenshot_path

            # 화면 전환 감지
            is_screen_change = False

            if prev_path and curr_path and prev_path != curr_path:
                # 이미지가 다르면 화면 전환 가능성 체크
                if prev_path in self.images and curr_path in self.images:
                    prev_img = self.images[prev_path]
                    curr_img = self.images[curr_path]
                    prev_hash = self.hashes.get(prev_path)
                    curr_hash = self.hashes.get(curr_path)

                    # pHash와 SSIM으로 화면 전환 여부 판단
                    distance = phash_distance(prev_hash, curr_hash)
                    ssim_score = calc_ssim(prev_img, curr_img)

                    # 화면이 다르면 (임계값을 넘으면) 화면 전환으로 판단
                    if distance > self.phash_threshold and ssim_score < self.ssim_threshold:
                        is_screen_change = True
                else:
                    # 이미지가 로드되지 않았으면 경로가 다르면 화면 전환으로 간주
                    is_screen_change = True

            if is_screen_change:
                # 화면 전환 감지 → 현재 플로우 종료, 새 플로우 시작
                flows.append(current_flow)
                current_flow = [curr_action]
            else:
                # 같은 화면 → 현재 플로우에 추가
                current_flow.append(curr_action)

        # 마지막 플로우 추가
        if current_flow:
            flows.append(current_flow)

        # 3) 각 플로우를 ScreenCluster로 변환 (대표 이미지 = 마지막 화면)
        clusters: List[ScreenCluster] = []
        for idx, flow_actions in enumerate(flows):
            if not flow_actions:
                continue

            # 플로우 내의 고유한 이미지 경로 수집
            flow_image_paths: List[str] = []
            seen_paths: set[str] = set()
            for action in flow_actions:
                if action.screenshot_path and action.screenshot_path not in seen_paths:
                    flow_image_paths.append(action.screenshot_path)
                    seen_paths.add(action.screenshot_path)

            if not flow_image_paths:
                continue

            # 대표 이미지 = 마지막 화면 (마지막 액션의 스크린샷)
            representative_image = flow_actions[-1].screenshot_path

            sc = ScreenCluster(
                cluster_id=idx,
                representative_image=representative_image,
                image_paths=flow_image_paths,
                actions=flow_actions,  # 이미 순서대로 정렬되어 있음
            )
            clusters.append(sc)

        # 클릭이 없는 클러스터 필터링 (옵션)
        if self.filter_no_clicks:
            filtered_clusters = []
            removed_count = 0
            for sc in clusters:
                click_actions = [a for a in sc.actions if a.coordinates]
                if click_actions:
                    filtered_clusters.append(sc)
                else:
                    removed_count += 1
            clusters = filtered_clusters
            if removed_count > 0:
                print(f"  ⚠️ 클릭이 없는 플로우 {removed_count}개 제외됨")

        self.clusters = clusters
        print(f"  ✅ {len(flows)}개 플로우 생성, {len(self.clusters)}개 ScreenCluster 생성 완료")

    # ---------- 6. 결과 출력 ----------

    def print_summary(self) -> None:
        """클러스터 결과를 터미널에 예쁘게 출력"""
        print("[6/6] 결과 출력\n")
        print("=" * 100)
        print(f"📊 클러스터링 완료: 총 {len(self.clusters)}개 화면 그룹")
        print("=" * 100)

        for sc in self.clusters:
            print(f"\n[Cluster {sc.cluster_id}]")
            print(f"  ▸ 대표 이미지: {os.path.basename(sc.representative_image)}")
            print(f"  ▸ 포함 이미지 수: {len(sc.image_paths)}개")

            # 액션 요약
            action_ids = sorted({a.action_id for a in sc.actions if a.action_id is not None})
            click_actions = [a for a in sc.actions if a.coordinates]
            request_actions = [a for a in sc.actions if a.action_type == "request"]
            urls = sorted({a.http_url for a in request_actions if a.http_url})

            print(f"  ▸ 포함 액션 수: {len(sc.actions)}개")
            print(f"  ▸ 액션 ID 목록: {action_ids}")
            print(f"  ▸ 클릭 횟수: {len(click_actions)}회")

            # 클릭 좌표 출력
            print(f"  ▸ 클릭 좌표 ({len(click_actions)}개):")
            for a in click_actions:
                print(
                    f"      - action_id={a.action_id}, seq={a.sequence}, "
                    f"coords={a.coordinates}"
                )

            # API URL 출력
            print(f"  ▸ 관련 API URL ({len(urls)}개):")
            for u in urls:
                print(f"      - {u}")

            # 포함 이미지 목록
            print(f"  ▸ 이미지 목록:")
            for idx, p in enumerate(sc.image_paths, 1):
                print(f"      {idx}. {os.path.basename(p)}")

        # 통계 정보
        total_images = sum(len(sc.image_paths) for sc in self.clusters)
        total_actions = sum(len(sc.actions) for sc in self.clusters)
        total_clicks = sum(len([a for a in sc.actions if a.coordinates]) for sc in self.clusters)
        cluster_sizes = [len(sc.image_paths) for sc in self.clusters]

        print("\n" + "=" * 100)
        print("📈 통계 정보")
        print("=" * 100)
        print(f"  ▸ 총 클러스터 수: {len(self.clusters)}개")
        print(f"  ▸ 총 이미지 수: {total_images}개")
        print(f"  ▸ 총 액션 수: {total_actions}개")
        print(f"  ▸ 총 클릭 횟수: {total_clicks}회")
        if self.clusters:
            print(f"  ▸ 평균 이미지/클러스터: {total_images / len(self.clusters):.2f}개")
            print(f"  ▸ 최소 클러스터 크기: {min(cluster_sizes)}개")
            print(f"  ▸ 최대 클러스터 크기: {max(cluster_sizes)}개")
        print("=" * 100)


# =========================
# main
# =========================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="메뉴얼 에이전트 - 스크린샷/좌표/액션 통합 로직 테스트 (test2)"
    )
    parser.add_argument(
        "--json",
        required=True,
        help="actions JSON 파일 경로 (예: data/actions/metadata_182.json)",
    )
    parser.add_argument(
        "--phash-threshold",
        type=int,
        default=18,
        help="pHash 거리 임계값 (작을수록 엄격, 기본=18)",
    )
    parser.add_argument(
        "--ssim-threshold",
        type=float,
        default=0.95,
        help="SSIM 임계값 (클수록 엄격, 기본=0.95)",
    )
    parser.add_argument(
        "--no-filter-clicks",
        action="store_true",
        help="클릭이 없는 클러스터도 포함 (기본: 클릭 없는 클러스터 제외)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not os.path.exists(args.json):
        print(f"❌ 오류: JSON 파일을 찾을 수 없습니다: {args.json}")
        sys.exit(1)

    print("=" * 100)
    print("🧪 메뉴얼 에이전트 - 스크린샷 기반 화면 그룹핑 & 좌표/API 로직 검증 (test2)")
    print("=" * 100)
    print(f"  ▸ JSON 파일: {args.json}")
    print(f"  ▸ pHash 임계값: {args.phash_threshold}")
    print(f"  ▸ SSIM 임계값: {args.ssim_threshold}")
    print("=" * 100)

    analyzer = UIScreenshotAnalyzer(
        json_path=args.json,
        phash_threshold=args.phash_threshold,
        ssim_threshold=args.ssim_threshold,
        filter_no_clicks=not args.no_filter_clicks,
    )

    analyzer.load_actions()
    analyzer.collect_screenshot_paths()
    analyzer.load_images_and_hashes()  # 이미지와 해시 로드 (화면 전환 감지에 필요)
    # cluster_images()는 더 이상 사용하지 않음 (순서 기반 플로우 생성으로 변경)
    analyzer.build_screen_summary()  # 순서 기반 플로우 생성 및 화면 전환 감지
    analyzer.print_summary()

    print("\n✅ test2 로직 검증 완료!")


if __name__ == "__main__":
    main()
