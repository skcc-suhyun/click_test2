import sys
import os
import json
import base64
import re
import hashlib
from collections import defaultdict
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont
from modules.loader import load_actions

# imagehash 라이브러리 import
try:
    import imagehash
    HAS_IMAGEHASH = True
except ImportError:
    HAS_IMAGEHASH = False
    st.warning("⚠️ imagehash 라이브러리가 없습니다. pip install imagehash를 실행하세요.")
    st.stop()

# scikit-image 라이브러리 import
try:
    import numpy as np
    from skimage.metrics import structural_similarity as ssim
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False
    st.warning("⚠️ scikit-image 라이브러리가 없습니다. pip install scikit-image를 실행하세요.")
    st.stop()

# ==========================
# CSS (테스트 환경용 스타일)
# ==========================
if not hasattr(st.session_state, 'test_screen_grouping_css_injected'):
    st.markdown("""
    <style>
    .test-original-img {
        max-width: 100% !important;
        max-height: 100vh !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        position: relative !important;
        z-index: 1 !important;
    }
    .test-overlay-wrapper {
        position: relative !important;
        display: inline-block !important;
        max-width: 100% !important;
        max-height: 100vh !important;
    }
    .test-overlay-box {
        position: absolute !important;
        border: 3px solid blue !important;
        background-color: rgba(0, 0, 255, 0.3) !important;
        pointer-events: none !important;
        box-sizing: border-box !important;
        z-index: 10 !important;
    }
    .test-overlay-label {
        position: absolute !important;
        background: white !important;
        color: blue !important;
        border: 1px solid blue !important;
        width: 10px !important;
        height: 10px !important;
        border-radius: 50% !important;
        line-height: 10px !important;
        text-align: center !important;
        font-weight: bold !important;
        font-size: 6px !important;
        pointer-events: none !important;
        z-index: 20 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    st.session_state.test_screen_grouping_css_injected = True


# ==========================
# Utility (클래스 기반 접근)
# ==========================
class ActionMetadataParser:
    """액션 메타데이터를 파싱하는 클래스"""
    
    @staticmethod
    def parse(action):
        """완전 고정된 metadata 파싱 - 절대 실패 안함"""
        raw = action.get("metadata")
        return ActionMetadataParser.parse_metadata(raw)
    
    @staticmethod
    def parse_metadata(raw):
        """metadata 파싱 - 완전 고정 버전"""
        if raw is None:
            return {}
        
        if isinstance(raw, dict):
            return raw
        
        if isinstance(raw, str):
            raw = raw.strip()
            if raw.startswith("{") and raw.endswith("}"):
                try:
                    return json.loads(raw)
                except:
                    pass
            
            # 따옴표가 escape된 상태 → 자동 수정
            raw = raw.replace('\\"', '"')
            # 다시 시도
            try:
                return json.loads(raw)
            except:
                return {}
        
        return {}
    
    @staticmethod
    def get_label(action):
        meta = ActionMetadataParser.parse(action)
        return meta.get("label", "")
    
    @staticmethod
    def get_coordinates(action):
        meta = ActionMetadataParser.parse(action)
        return meta.get("coordinates", {})
    
    @staticmethod
    def get_element_bounds(action):
        coords = ActionMetadataParser.get_coordinates(action)
        return coords.get("elementBounds")


class ScreenGrouper:
    """
    완전히 새로 설계된 화면 그룹핑 엔진
    1) 이미지 기반(pHash + SSIM)
    2) DOM은 2차 보조 판별
    3) 팝업 분리
    """

    def __init__(self, actions, progress_callback=None):
        # action_sequence 기준으로 정렬 (로그 순서 우선)
        self.actions = sorted(actions, key=lambda a: a.get("action_sequence", 999999))
        self.cache = {}
        self.action_to_global_idx = {id(action): idx for idx, action in enumerate(self.actions)}
        self.progress_callback = progress_callback
        self.stats = {
            "total_actions": len(actions),
            "click_actions": 0,
            "images_loaded": 0,
            "hashes_calculated": 0,
            "clusters_created": 0,
            "phash_distances": []
        }

    # ---------------------------
    # 이미지 로딩 / 해시 / SSIM
    # ---------------------------
    def load_image(self, path):
        if path in self.cache:
            return self.cache[path]

        if not os.path.exists(path):
            return None

        try:
            img = Image.open(path).convert("RGB").resize((384, 384))
            self.cache[path] = img
            return img
        except Exception as e:
            return None

    def phash(self, img):
        if img is None:
            return None
        return imagehash.phash(img)

    def phash_distance(self, h1, h2):
        if h1 is None or h2 is None:
            return float('inf')
        return h1 - h2

    def calc_ssim(self, img1, img2):
        if img1 is None or img2 is None:
            return 0.0
        try:
            a1 = np.asarray(img1.convert("L"), dtype=np.float32)
            a2 = np.asarray(img2.convert("L"), dtype=np.float32)
            score, _ = ssim(a1, a2, full=True)
            return score
        except:
            return 0.0

    # ---------------------------
    # 1차: 클릭 전 이미지 기준 클러스터링
    # ---------------------------
    def get_screen_name_key(self, action):
        """액션의 screen_name을 정규화하여 그룹 키로 사용"""
        screen_name = action.get("screen_name")
        if not screen_name:
            # label에서 확인
            meta = ActionMetadataParser.parse(action)
            label = meta.get("label") or action.get("text_content") or ""
            if "요구사항 정의" in str(label):
                return "요구사항 정의"
            elif "프로그램 설계" in str(label) or "설계" in str(label):
                return "프로그램 설계"
            return None
        
        # screen_name 정규화
        if "요구사항 정의" in screen_name:
            return "요구사항 정의"
        elif "프로그램 설계" in screen_name or "설계" in screen_name:
            return "프로그램 설계"
        else:
            return screen_name
    
    def cluster_by_image(self):
        """
        핵심: 클릭 전 스크린샷 이미지(_prev_screenshot) 기준으로 그룹핑
        - pHash distance ≤ 18이면 같은 화면 (배경만 비교)
        - screen_name이 다르면 같은 이미지라도 다른 그룹으로 분리
        - 팝업이 감지된 상태에서는 새 그룹을 만들지 않고 이전 그룹에 추가
        - 팝업 내 액션들은 같은 그룹으로 묶음 (팝업 ID 기반)
        """
        groups = []
        used_actions = set()
        prev_image_to_group = {}  # (이미지 경로, screen_name_key) -> 그룹 매핑
        popup_group_map = {}  # 팝업 ID -> 그룹 매핑
        current_popup_group = None  # 현재 활성 팝업 그룹
        
        # 진행 상황 업데이트
        if self.progress_callback:
            self.progress_callback(0.1, "클릭 액션의 _prev_screenshot 설정 중...")
        
        # 먼저 모든 클릭 액션의 _prev_screenshot 설정
        self._set_prev_screenshots()
        
        click_actions = [a for a in self.actions if a.get("action_type") == "click"]
        self.stats["click_actions"] = len(click_actions)
        total_clicks = len(click_actions)
        
        for i, act in enumerate(self.actions):
            if id(act) in used_actions:
                continue
            
            # 진행 상황 업데이트
            if self.progress_callback and i % max(1, len(self.actions) // 20) == 0:
                progress = 0.2 + (i / len(self.actions)) * 0.6
                self.progress_callback(progress, f"액션 처리 중... ({i}/{len(self.actions)})")
            
            # 클릭 액션인 경우: _prev_screenshot 기준으로 그룹핑
            if act.get("action_type") == "click":
                prev_screenshot = act.get("_prev_screenshot")
                
                # 팝업 상태 확인
                is_popup = self.is_popup_action(act)
                
                if prev_screenshot and os.path.exists(prev_screenshot):
                    # 클릭 전 이미지에 팝업이 있는지 확인
                    has_popup_in_screenshot, popup_box = self.is_popup_screenshot(prev_screenshot)
                    
                    # 배경만 크롭해서 pHash 계산
                    prev_hash = self.phash_background_only(prev_screenshot, popup_box if has_popup_in_screenshot else None)
                    
                    if prev_hash:
                        self.stats["images_loaded"] += 1
                        self.stats["hashes_calculated"] += 1
                        
                        # 팝업이 감지된 상태에서는 새 그룹을 만들지 않고 이전 그룹에 추가
                        if has_popup_in_screenshot and current_popup_group:
                            # 팝업 상태: 이전 그룹에 추가
                            current_popup_group["actions"].append(act)
                            current_popup_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                            used_actions.add(id(act))
                            
                            # 팝업 종료 액션(저장하기 등)이면 그룹핑 종료
                            if self.is_popup_terminating_action(act):
                                current_popup_group = None
                            
                            continue
                        
                        # 팝업 액션인 경우: 팝업 그룹에 추가
                        if is_popup:
                            # 팝업 종료 액션(저장하기 등)이면 현재 팝업 그룹에 추가하고 종료
                            if self.is_popup_terminating_action(act) and current_popup_group:
                                current_popup_group["actions"].append(act)
                                current_popup_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                                used_actions.add(id(act))
                                current_popup_group = None  # 팝업 그룹핑 종료
                                continue
                            
                            # 팝업 ID 생성 (이미지 경로 기반)
                            popup_id = f"popup_{prev_screenshot}"
                            
                            if popup_id in popup_group_map:
                                # 기존 팝업 그룹에 추가
                                popup_group = popup_group_map[popup_id]
                                popup_group["actions"].append(act)
                                popup_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                                current_popup_group = popup_group
                                
                                # 팝업 종료 액션이면 그룹핑 종료
                                if self.is_popup_terminating_action(act):
                                    current_popup_group = None
                            else:
                                # 새 팝업 그룹 생성 또는 기존 그룹 찾기
                                current_screen_name_key = self.get_screen_name_key(act)
                                found_group = None
                                min_distance = float('inf')
                                
                                # Lightweight Vision Check + pHash로 기존 그룹 찾기 (screen_name도 고려)
                                for (prev_path, screen_key), group_info in prev_image_to_group.items():
                                    # screen_name이 다르면 같은 이미지라도 다른 그룹으로 분리
                                    if current_screen_name_key is not None and screen_key is not None:
                                        if current_screen_name_key != screen_key:
                                            continue  # screen_name이 다르면 스킵
                                    
                                    has_popup2, popup_box2 = self.is_popup_screenshot(prev_path)
                                    
                                    # Lightweight Vision Check 먼저 수행 (빠른 필터링)
                                    vision_diff = self.lightweight_vision_check(
                                        prev_screenshot, prev_path,
                                        popup_box if has_popup_in_screenshot else None,
                                        popup_box2 if has_popup2 else None
                                    )
                                    
                                    # Vision Check 임계값: 30 (너무 다르면 스킵)
                                    if vision_diff > 30:
                                        continue
                                    
                                    # pHash로 정확도 향상
                                    prev_hash2 = self.phash_background_only(prev_path, popup_box2 if has_popup2 else None)
                                    
                                    if prev_hash2:
                                        distance = self.phash_distance(prev_hash, prev_hash2)
                                        self.stats["phash_distances"].append(distance)
                                        
                                        # Vision Check와 pHash를 결합한 점수
                                        combined_score = distance + (vision_diff / 2)
                                        
                                        if distance <= 18 and combined_score < min_distance:
                                            min_distance = combined_score
                                            found_group = group_info["group"]
                                
                                if found_group:
                                    # 기존 그룹에 추가
                                    found_group["actions"].append(act)
                                    found_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                                    popup_group_map[popup_id] = found_group
                                    current_popup_group = found_group
                                    
                                    # 팝업 종료 액션이면 그룹핑 종료
                                    if self.is_popup_terminating_action(act):
                                        current_popup_group = None
                                else:
                                    # 새 팝업 그룹 생성
                                    action_seq = act.get("action_sequence", 999999)
                                    group = {
                                        "prev_image": prev_screenshot,
                                        "prev_image_hash": prev_hash,
                                        "images": [prev_screenshot],
                                        "actions": [act],
                                        "representative_image": None,
                                        "first_action_idx": i,
                                        "first_action_sequence": action_seq,
                                        "phash_distances": [],
                                        "is_popup_group": True,
                                        "popup_id": popup_id,
                                        "screen_name_key": current_screen_name_key  # screen_name 키 저장
                                    }
                                    groups.append(group)
                                    self.stats["clusters_created"] += 1
                                    # (이미지 경로, screen_name_key) 튜플을 키로 사용
                                    prev_image_to_group[(prev_screenshot, current_screen_name_key)] = {
                                        "group": group,
                                        "hash": prev_hash
                                    }
                                    popup_group_map[popup_id] = group
                                    current_popup_group = group
                                    
                                    # 팝업 종료 액션이면 그룹핑 종료
                                    if self.is_popup_terminating_action(act):
                                        current_popup_group = None
                                
                                used_actions.add(id(act))
                                continue
                        
                        # 일반 액션: Lightweight Vision Check + pHash로 그룹 찾기
                        # screen_name도 함께 고려하여 분리
                        current_screen_name_key = self.get_screen_name_key(act)
                        
                        found_group = None
                        min_distance = float('inf')
                        min_vision_diff = float('inf')
                        
                        for (prev_path, screen_key), group_info in prev_image_to_group.items():
                            # screen_name이 다르면 같은 이미지라도 다른 그룹으로 분리
                            if current_screen_name_key is not None and screen_key is not None:
                                if current_screen_name_key != screen_key:
                                    continue  # screen_name이 다르면 스킵
                            
                            has_popup2, popup_box2 = self.is_popup_screenshot(prev_path)
                            
                            # Lightweight Vision Check 먼저 수행 (빠른 필터링)
                            vision_diff = self.lightweight_vision_check(
                                prev_screenshot, prev_path,
                                popup_box if has_popup_in_screenshot else None,
                                popup_box2 if has_popup2 else None
                            )
                            
                            # Vision Check 임계값: 30 (너무 다르면 스킵)
                            if vision_diff > 30:
                                continue
                            
                            # pHash로 정확도 향상
                            prev_hash2 = self.phash_background_only(prev_path, popup_box2 if has_popup2 else None)
                            
                            if prev_hash2:
                                distance = self.phash_distance(prev_hash, prev_hash2)
                                self.stats["phash_distances"].append(distance)
                                
                                # Vision Check와 pHash를 결합한 점수
                                combined_score = distance + (vision_diff / 2)  # Vision diff를 가중치 적용
                                
                                if distance <= 18 and combined_score < min_distance:
                                    min_distance = combined_score
                                    min_vision_diff = vision_diff
                                    found_group = group_info["group"]
                        
                        if found_group:
                            # 기존 그룹에 추가
                            found_group["actions"].append(act)
                            found_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                            if "phash_distances" not in found_group:
                                found_group["phash_distances"] = []
                            found_group["phash_distances"].append(min_distance)
                            used_actions.add(id(act))
                            
                            # 팝업이 닫혔는지 확인
                            if current_popup_group and found_group["actions"]:
                                prev_action = found_group["actions"][-2] if len(found_group["actions"]) > 1 else None
                                if prev_action and self.is_popup_closed(prev_action, act):
                                    current_popup_group = None
                            
                            # 팝업 그룹이 아니면 current_popup_group 초기화
                            if not found_group.get("is_popup_group"):
                                current_popup_group = None
                        else:
                            # 새 그룹 생성
                            action_seq = act.get("action_sequence", 999999)
                            group = {
                                "prev_image": prev_screenshot,
                                "prev_image_hash": prev_hash,
                                "images": [prev_screenshot],
                                "actions": [act],
                                "representative_image": None,
                                "first_action_idx": i,
                                "first_action_sequence": action_seq,
                                "phash_distances": [],
                                "is_popup_group": False,
                                "screen_name_key": current_screen_name_key  # screen_name 키 저장
                            }
                            groups.append(group)
                            self.stats["clusters_created"] += 1
                            # (이미지 경로, screen_name_key) 튜플을 키로 사용
                            prev_image_to_group[(prev_screenshot, current_screen_name_key)] = {
                                "group": group,
                                "hash": prev_hash
                            }
                            used_actions.add(id(act))
                            current_popup_group = None
                    else:
                        # 이미지 로딩 실패 - 마지막 그룹에 추가
                        if groups:
                            groups[-1]["actions"].append(act)
                            used_actions.add(id(act))
                else:
                    # _prev_screenshot이 없으면 마지막 그룹에 추가
                    if groups:
                        groups[-1]["actions"].append(act)
                        used_actions.add(id(act))
            else:
                # 클릭이 아닌 액션: 팝업 그룹이 있으면 팝업 그룹에 추가, 없으면 가장 가까운 그룹에 포함
                if current_popup_group:
                    # 팝업 상태: 현재 팝업 그룹에 추가
                    current_popup_group["actions"].append(act)
                    current_popup_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                    used_actions.add(id(act))
                    
                    # 팝업 종료 액션 체크는 클릭 액션에서만 수행
                else:
                    # 팝업이 아닌 상태: action_sequence 순서상 가장 가까운 그룹에 포함
                    current_seq = act.get("action_sequence", 999999)
                    
                    # 가장 가까운 그룹 찾기 (action_sequence 기준)
                    found_group = None
                    min_seq_diff = float('inf')
                    
                    for group in groups:
                        if not group["actions"]:
                            continue
                        # 그룹의 첫 번째와 마지막 액션의 action_sequence 확인
                        first_seq = group["actions"][0].get("action_sequence", 999999)
                        last_seq = group["actions"][-1].get("action_sequence", 999999)
                        
                        # 현재 액션이 이 그룹의 범위 내에 있거나 바로 앞/뒤에 있는지 확인
                        if first_seq <= current_seq <= last_seq:
                            # 그룹 범위 내에 있으면 이 그룹에 추가
                            found_group = group
                            break
                        elif current_seq < first_seq:
                            # 현재 액션이 그룹보다 앞에 있으면 가장 가까운 그룹 찾기
                            diff = first_seq - current_seq
                            if diff < min_seq_diff:
                                min_seq_diff = diff
                                found_group = group
                    
                    if found_group:
                        found_group["actions"].append(act)
                        # 액션 순서 정렬 (action_sequence 기준 - 로그 순서 우선)
                        found_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                        used_actions.add(id(act))
                    elif groups:
                        # 그룹을 찾지 못했으면 action_sequence가 가장 작은 그룹에 추가
                        min_seq_group = min(groups, key=lambda g: g["actions"][0].get("action_sequence", 999999) if g["actions"] else 999999)
                        min_seq_group["actions"].append(act)
                        # 액션 순서 정렬 (action_sequence 기준)
                        min_seq_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                        used_actions.add(id(act))
        
        # 처리되지 않은 액션들을 action_sequence 순서에 맞는 그룹에 추가
        for act in self.actions:
            if id(act) not in used_actions:
                act_seq = act.get("action_sequence", 999999)
                
                if groups:
                    # action_sequence가 가장 가까운 그룹 찾기
                    best_group = None
                    min_diff = float('inf')
                    
                    for group in groups:
                        if not group["actions"]:
                            continue
                        first_seq = group["actions"][0].get("action_sequence", 999999)
                        last_seq = group["actions"][-1].get("action_sequence", 999999)
                        
                        if first_seq <= act_seq <= last_seq:
                            best_group = group
                            break
                        else:
                            diff = min(abs(act_seq - first_seq), abs(act_seq - last_seq))
                            if diff < min_diff:
                                min_diff = diff
                                best_group = group
                    
                    if best_group:
                        best_group["actions"].append(act)
                        best_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                    else:
                        # 그룹을 찾지 못했으면 action_sequence가 가장 작은 그룹에 추가
                        min_seq_group = min(groups, key=lambda g: g["actions"][0].get("action_sequence", 999999) if g["actions"] else 999999)
                        min_seq_group["actions"].append(act)
                        min_seq_group["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                else:
                    act_idx = self.action_to_global_idx.get(id(act), 999999)
                    groups.append({
                        "prev_image": None,
                        "prev_image_hash": None,
                        "images": [],
                        "actions": [act],
                        "representative_image": None,
                        "first_action_idx": act_idx,
                        "first_action_sequence": act_seq  # action_sequence 저장
                    })
                used_actions.add(id(act))

        # 그룹들을 첫 번째 액션의 action_sequence 순으로 정렬 (로그 순서 우선)
        groups.sort(key=lambda g: g.get("first_action_sequence", 999999) if g.get("first_action_sequence") is not None else g.get("first_action_idx", 999999))
        
        # 진행 상황 업데이트
        if self.progress_callback:
            self.progress_callback(0.9, f"클러스터링 완료: {len(groups)}개 그룹 생성")

        return groups
    
    def _set_prev_screenshots(self):
        """모든 클릭 액션의 _prev_screenshot 설정"""
        for i, action in enumerate(self.actions):
            if action.get("action_type") != "click":
                continue
            
            if action.get("_prev_screenshot"):
                continue
            
            # 이전 액션들에서 스크린샷 찾기
            prev_screenshot = None
            for j in range(i - 1, -1, -1):
                prev_action = self.actions[j]
                screenshot_path = prev_action.get("screenshot_real_path") or prev_action.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    prev_screenshot = os.path.normpath(screenshot_path)
                    break
            
            if prev_screenshot:
                action["_prev_screenshot"] = prev_screenshot

    # ---------------------------
    # 2차: 팝업 감지 및 처리
    # ---------------------------
    def is_popup_action(self, action):
        """액션이 팝업 내에서 발생했는지 확인"""
        meta = ActionMetadataParser.parse(action)
        coords = meta.get("coordinates") or {}
        bounds = coords.get("elementBounds") or {}
        
        # role="dialog" 확인
        role = meta.get("role") or action.get("role")
        if role and "dialog" in str(role).lower():
            return True
        
        # z-index 높은 modal 영역 확인 (metadata에서 확인)
        z_index = meta.get("zIndex") or meta.get("z-index")
        if z_index and isinstance(z_index, (int, float)) and z_index > 1000:
            return True
        
        # 기존 룰: 중앙 + 작은 영역
        w = bounds.get("widthRatio")
        h = bounds.get("heightRatio")
        top = bounds.get("topRatio")
        left = bounds.get("leftRatio")

        if any(x is None for x in [w, h, top, left]):
            return False

        # 팝업 룰: 중앙 + 작은 영역
        if w < 0.55 and h < 0.55 and 0.15 < top < 0.55:
            return True
        
        return False
    
    def is_popup_terminating_action(self, action):
        """팝업을 종료하는 액션인지 확인 (저장하기, 확인, 취소 등)"""
        if action.get("action_type") != "click":
            return False
        
        meta = ActionMetadataParser.parse(action)
        label = meta.get("label") or action.get("text_content") or ""
        label = str(label).strip()
        
        # 팝업 종료 버튼들
        terminating_labels = ["저장하기", "확인", "취소", "닫기", "완료", "저장", "OK", "Cancel", "Close"]
        
        if label in terminating_labels:
            # 팝업 내에서 발생한 액션인지 확인
            if self.is_popup_action(action):
                return True
        
        return False
    
    def is_popup_screenshot(self, screenshot_path):
        """스크린샷 이미지에 팝업이 있는지 확인 (이미지 분석)"""
        if not screenshot_path or not os.path.exists(screenshot_path):
            return False, None
        
        try:
            img = Image.open(screenshot_path).convert("RGB")
            # 간단한 팝업 감지: 중앙 영역의 밝기 변화 확인
            # 실제로는 더 정교한 방법이 필요하지만, 일단 기본 로직 사용
            width, height = img.size
            
            # 중앙 영역 확인 (20% ~ 80% 영역)
            center_left = int(width * 0.2)
            center_top = int(height * 0.2)
            center_right = int(width * 0.8)
            center_bottom = int(height * 0.8)
            
            # 중앙 영역의 평균 밝기 계산
            center_region = img.crop((center_left, center_top, center_right, center_bottom))
            center_pixels = list(center_region.getdata())
            center_brightness = sum(sum(pixel) for pixel in center_pixels) / (len(center_pixels) * 3)
            
            # 가장자리 영역의 평균 밝기 계산
            edge_region = img.crop((0, 0, width, height))
            edge_pixels = list(edge_region.getdata())
            edge_brightness = sum(sum(pixel) for pixel in edge_pixels) / (len(edge_pixels) * 3)
            
            # 중앙이 밝고 가장자리가 어두우면 팝업 가능성
            if center_brightness > edge_brightness * 1.1:
                # 팝업 bounding box 추정 (중앙 영역)
                popup_box = {
                    "left": center_left,
                    "top": center_top,
                    "right": center_right,
                    "bottom": center_bottom
                }
                return True, popup_box
            
            return False, None
        except:
            return False, None
    
    def crop_background(self, img, popup_box):
        """팝업 영역을 제외한 배경만 크롭"""
        if popup_box is None:
            return img
        
        width, height = img.size
        left = popup_box.get("left", 0)
        top = popup_box.get("top", 0)
        right = popup_box.get("right", width)
        bottom = popup_box.get("bottom", height)
        
        # 배경 영역들: 상단, 하단, 좌측, 우측
        background_regions = []
        
        # 상단 영역
        if top > 0:
            background_regions.append(img.crop((0, 0, width, top)))
        
        # 하단 영역
        if bottom < height:
            background_regions.append(img.crop((0, bottom, width, height)))
        
        # 좌측 영역
        if left > 0:
            background_regions.append(img.crop((0, top, left, bottom)))
        
        # 우측 영역
        if right < width:
            background_regions.append(img.crop((right, top, width, bottom)))
        
        if not background_regions:
            return img
        
        # 배경 영역들을 합치기 (가장 큰 영역 사용)
        largest_region = max(background_regions, key=lambda r: r.width * r.height)
        return largest_region.resize((384, 384))
    
    def phash_background_only(self, img_path, popup_box=None):
        """배경만 크롭해서 pHash 계산"""
        if not img_path or not os.path.exists(img_path):
            return None
        
        try:
            img = Image.open(img_path).convert("RGB")
            
            if popup_box:
                # 팝업 영역 제외하고 배경만 크롭
                background_img = self.crop_background(img, popup_box)
            else:
                # 팝업이 없으면 전체 이미지 사용
                background_img = img.resize((384, 384))
            
            return self.phash(background_img)
        except:
            return None
    
    def lightweight_vision_check(self, img1_path, img2_path, popup_box1=None, popup_box2=None):
        """
        Lightweight Vision Check: 가벼운 이미지 비교 방법
        - 작은 해상도로 리사이즈 후 간단한 픽셀 차이 비교
        - pHash보다 빠르고 가벼움
        """
        if not img1_path or not img2_path:
            return float('inf')
        
        if not os.path.exists(img1_path) or not os.path.exists(img2_path):
            return float('inf')
        
        try:
            # 이미지 로드 및 배경만 크롭
            img1 = Image.open(img1_path).convert("RGB")
            img2 = Image.open(img2_path).convert("RGB")
            
            if popup_box1:
                img1 = self.crop_background(img1, popup_box1)
            else:
                img1 = img1.resize((128, 128))  # 작은 해상도로 리사이즈
            
            if popup_box2:
                img2 = self.crop_background(img2, popup_box2)
            else:
                img2 = img2.resize((128, 128))  # 작은 해상도로 리사이즈
            
            # 동일한 크기로 맞추기
            img1 = img1.resize((128, 128))
            img2 = img2.resize((128, 128))
            
            # 픽셀 차이 계산 (간단한 L1 거리)
            arr1 = np.array(img1, dtype=np.float32)
            arr2 = np.array(img2, dtype=np.float32)
            
            diff = np.abs(arr1 - arr2)
            avg_diff = np.mean(diff)
            
            return avg_diff
        except Exception as e:
            return float('inf')
    
    def is_popup_closed(self, prev_action, current_action):
        """팝업이 닫혔는지 확인"""
        # screen_name 변경 확인
        prev_screen = prev_action.get("screen_name")
        curr_screen = current_action.get("screen_name")
        if prev_screen and curr_screen and prev_screen != curr_screen:
            return True
        
        # 현재 액션의 스크린샷에 팝업이 없는지 확인
        curr_screenshot = current_action.get("screenshot_real_path") or current_action.get("screenshot_path")
        if curr_screenshot:
            has_popup, _ = self.is_popup_screenshot(curr_screenshot)
            if not has_popup:
                # 이전에 팝업이 있었는지 확인
                prev_screenshot = prev_action.get("screenshot_real_path") or prev_action.get("screenshot_path")
                if prev_screenshot:
                    prev_has_popup, _ = self.is_popup_screenshot(prev_screenshot)
                    if prev_has_popup:
                        return True
        
        # elementBounds가 팝업 영역에서 벗어났는지 확인
        prev_meta = ActionMetadataParser.parse(prev_action)
        curr_meta = ActionMetadataParser.parse(current_action)
        
        prev_bounds = prev_meta.get("coordinates", {}).get("elementBounds", {})
        curr_bounds = curr_meta.get("coordinates", {}).get("elementBounds", {})
        
        # 이전 액션이 팝업이었고, 현재 액션이 팝업이 아니면 팝업 닫힘
        if self.is_popup_action(prev_action) and not self.is_popup_action(current_action):
            return True
        
        return False

    def split_by_screen_name_or_label(self, cluster):
        """
        screen_name 또는 label 기준으로 클러스터를 분리
        예: "요구사항 정의"와 "프로그램 설계"를 별도 화면으로 분리
        """
        actions = cluster["actions"]
        if len(actions) <= 1:
            return [cluster]
        
        # screen_name 또는 label 기준으로 그룹핑
        groups = {}
        unassigned = []
        
        for action in actions:
            # screen_name 확인
            screen_name = action.get("screen_name")
            
            # label 확인 (metadata에서)
            meta = ActionMetadataParser.parse(action)
            label = meta.get("label") or action.get("text_content")
            
            # 그룹 키 결정
            group_key = None
            
            # 1순위: screen_name
            if screen_name:
                if "요구사항 정의" in screen_name:
                    group_key = "요구사항 정의"
                elif "프로그램 설계" in screen_name:
                    group_key = "프로그램 설계"
                else:
                    group_key = screen_name
            
            # 2순위: label
            if not group_key and label:
                if "요구사항 정의" in label:
                    group_key = "요구사항 정의"
                elif "프로그램 설계" in label:
                    group_key = "프로그램 설계"
            
            # 그룹에 할당
            if group_key:
                if group_key not in groups:
                    groups[group_key] = {
                        "prev_image": cluster.get("prev_image"),
                        "prev_image_hash": cluster.get("prev_image_hash"),
                        "images": cluster.get("images", []).copy(),
                        "actions": [],
                        "representative_image": None,
                        "first_action_idx": cluster.get("first_action_idx", 999999),
                        "first_action_sequence": 999999,
                        "phash_distances": cluster.get("phash_distances", []).copy(),
                        "is_popup_group": cluster.get("is_popup_group", False),
                        "popup_id": cluster.get("popup_id")
                    }
                groups[group_key]["actions"].append(action)
            else:
                unassigned.append(action)
        
        # 분리된 그룹이 2개 이상이면 분리 수행
        if len(groups) >= 2:
            result_clusters = []
            for group_key, group_data in groups.items():
                if group_data["actions"]:
                    # action_sequence 정렬
                    group_data["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
                    # first_action_sequence 설정
                    if group_data["actions"]:
                        group_data["first_action_sequence"] = group_data["actions"][0].get("action_sequence", 999999)
                    result_clusters.append(group_data)
            
            # 할당되지 않은 액션들은 첫 번째 그룹에 추가
            if unassigned and result_clusters:
                result_clusters[0]["actions"].extend(unassigned)
                result_clusters[0]["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
            
            return result_clusters
        
        # 분리할 필요 없으면 원본 반환
        return [cluster]

    def process_clusters(self, clusters):
        """
        클러스터 후처리: 팝업은 분리하지 않고 같은 그룹에 유지
        대표 이미지는 팝업 이미지 우선, 없으면 클릭 전 이미지
        screen_name 또는 label 기준으로 분리 가능한 경우 분리
        """
        results = []
        
        for cluster in clusters:
            # 액션 순서 정렬 (action_sequence 기준 - 로그 순서 우선)
            cluster["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
            
            # screen_name 또는 label 기준으로 분리 시도
            split_clusters = self.split_by_screen_name_or_label(cluster)
            
            for split_cluster in split_clusters:
                # 대표 이미지 선택 우선순위:
                # 1순위: 팝업 이미지 (클릭 후 팝업 이미지)
                # 2순위: 클릭 후 새로운 스크린샷 (클릭 결과 화면)
                # 3순위: 클릭 전 이미지
                
                popup_image = None
                click_result_image = None
                prev_image = split_cluster.get("prev_image")
                
                # 클릭 액션 추출
                click_actions = [a for a in split_cluster["actions"] if a.get("action_type") == "click"]
                
                # 1순위: 팝업 이미지 찾기
                for act in split_cluster["actions"]:
                    if self.is_popup_action(act):
                        # 팝업 액션의 스크린샷 (클릭 후 팝업 이미지)
                        popup_img_path = act.get("screenshot_real_path") or act.get("screenshot_path")
                        if popup_img_path and os.path.exists(popup_img_path):
                            popup_image = popup_img_path
                            break
                
                # 2순위: 클릭 후 새로운 스크린샷 찾기 (클릭 결과 화면)
                if not popup_image and click_actions:
                    # 마지막 클릭 액션부터 역순으로 확인
                    for click_action in reversed(click_actions):
                        click_idx = split_cluster["actions"].index(click_action)
                        
                        # 클릭 후 다음 액션들에서 새로운 스크린샷 찾기
                        for j in range(click_idx + 1, len(split_cluster["actions"])):
                            next_action = split_cluster["actions"][j]
                            screenshot_path = next_action.get("screenshot_real_path") or next_action.get("screenshot_path")
                            
                            if screenshot_path and os.path.exists(screenshot_path):
                                # 클릭 전 이미지와 다른지 확인
                                prev_screenshot = click_action.get("_prev_screenshot")
                                if screenshot_path != prev_screenshot:
                                    click_result_image = screenshot_path
                                    break
                        
                        if click_result_image:
                            break
                        
                        # 클릭 액션 자체의 스크린샷도 확인 (클릭 후 화면)
                        click_screenshot = click_action.get("screenshot_real_path") or click_action.get("screenshot_path")
                        if click_screenshot and os.path.exists(click_screenshot):
                            prev_screenshot = click_action.get("_prev_screenshot")
                            if click_screenshot != prev_screenshot:
                                click_result_image = click_screenshot
                                break
                        
                        if click_result_image:
                            break
                
                # 대표 이미지: 팝업 이미지 우선, 없으면 클릭 결과 이미지, 없으면 클릭 전 이미지
                representative_image = popup_image or click_result_image or prev_image
                
                # elementBounds가 있는 클릭 액션 확인
                valid_click_count = 0
                for action in click_actions:
                    bounds = ActionMetadataParser.get_element_bounds(action)
                    if bounds:
                        valid_click_count += 1
                
                # 클릭 액션이 있고 elementBounds가 있는 액션이 있으면 유효한 화면
                if len(click_actions) > 0 and valid_click_count > 0:
                    # 첫 번째 액션의 action_sequence 가져오기 (정렬용)
                    first_action_seq = split_cluster["actions"][0].get("action_sequence", 999999) if split_cluster["actions"] else 999999
                    
                    results.append({
                        "type": "screen",
                        "screen_name": f"화면 {len(results) + 1}",
                        "actions": split_cluster["actions"],
                        "images": split_cluster.get("images", []),
                        "representative_image": representative_image,
                        "is_popup": False,
                        "prev_image": prev_image,
                        "popup_image": popup_image,
                        "click_result_image": click_result_image,  # 클릭 결과 이미지 저장
                        "first_action_sequence": first_action_seq  # 정렬용 저장
                    })

        return results

    # ---------------------------
    # 최종 실행
    # ---------------------------
    def run(self):
        # 진행 상황 업데이트
        if self.progress_callback:
            self.progress_callback(0.0, "그룹핑 시작...")
        
        # 클릭 전 이미지 기준으로 클러스터링
        img_clusters = self.cluster_by_image()
        
        # 진행 상황 업데이트
        if self.progress_callback:
            self.progress_callback(0.85, "클러스터 후처리 중...")
        
        # 팝업 분리 없이 후처리 (팝업은 같은 그룹에 유지)
        screens = self.process_clusters(img_clusters)

        # 각 화면 내 액션 순서도 확실히 정렬 (action_sequence 기준 - 로그 순서 우선)
        for screen in screens:
            screen["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
            # first_action_sequence 업데이트 (정렬 후)
            if screen["actions"]:
                screen["first_action_sequence"] = screen["actions"][0].get("action_sequence", 999999)

        # 화면 순서 정렬 (action_sequence 기준 - 로그 순서 우선)
        screens.sort(key=lambda s: s.get("first_action_sequence", 999999))

        # 클릭 액션 추출 (정렬 후)
        for screen in screens:
            click_actions = [a for a in screen["actions"] if a.get("action_type") == "click"]
            screen["click_actions"] = click_actions

        # 마지막 화면의 대표 이미지를 마지막 이미지로 설정
        if screens:
            last_screen = screens[-1]
            for action in reversed(self.actions):
                screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    last_screen["representative_image"] = screenshot_path
                    break
        
        # 진행 상황 완료
        if self.progress_callback:
            self.progress_callback(1.0, f"완료: {len(screens)}개 화면 생성")

        return screens


# ==========================
# 간단한 그룹핑 함수 (순차적 접근)
# ==========================
class SimpleGroup:
    """간단한 그룹 클래스"""
    def __init__(self):
        self.actions = []
        self.images = []
        self.representative_image = None
    
    def add(self, action, image):
        """액션과 이미지를 그룹에 추가"""
        self.actions.append(action)
        if image and image not in self.images:
            self.images.append(image)
    
    def not_empty(self):
        """그룹이 비어있지 않은지 확인"""
        return len(self.actions) > 0


def new_group():
    """새 그룹 생성"""
    return SimpleGroup()


def get_screenshot(action):
    """액션의 스크린샷 경로 반환"""
    screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
    if screenshot_path and os.path.exists(screenshot_path):
        return screenshot_path
    return None


def is_same_screen(prev_image, curr_image):
    """
    두 이미지가 같은 화면인지 확인
    SSIM + OCR diff + elementBounds 변동을 고려
    """
    if prev_image is None or curr_image is None:
        return False
    
    if not os.path.exists(prev_image) or not os.path.exists(curr_image):
        return False
    
    try:
        # 이미지 로드
        img1 = Image.open(prev_image).convert("RGB").resize((384, 384))
        img2 = Image.open(curr_image).convert("RGB").resize((384, 384))
        
        # SSIM 계산
        a1 = np.asarray(img1.convert("L"), dtype=np.float32)
        a2 = np.asarray(img2.convert("L"), dtype=np.float32)
        ssim_score, _ = ssim(a1, a2, full=True)
        
        # pHash 계산
        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)
        phash_distance = hash1 - hash2
        
        # SSIM 임계값: 0.95 이상이면 같은 화면
        # pHash 거리: 18 이하면 같은 화면
        if ssim_score >= 0.95 or phash_distance <= 18:
            return True
        
        return False
    except Exception as e:
        return False


def is_popup(action):
    """액션이 팝업 내에서 발생했는지 확인 (기존 로직 재사용)"""
    meta = ActionMetadataParser.parse(action)
    coords = meta.get("coordinates") or {}
    bounds = coords.get("elementBounds") or {}
    
    # role="dialog" 확인
    role = meta.get("role") or action.get("role")
    if role and "dialog" in str(role).lower():
        return True
    
    # z-index 높은 modal 영역 확인
    z_index = meta.get("zIndex") or meta.get("z-index")
    if z_index and isinstance(z_index, (int, float)) and z_index > 1000:
        return True
    
    # 팝업 룰: 중앙 + 작은 영역
    w = bounds.get("widthRatio")
    h = bounds.get("heightRatio")
    top = bounds.get("topRatio")
    left = bounds.get("leftRatio")
    
    if any(x is None for x in [w, h, top, left]):
        return False
    
    # 팝업 룰: 중앙 + 작은 영역
    if w < 0.55 and h < 0.55 and 0.15 < top < 0.55:
        return True
    
    return False


def choose_representative_image(group):
    """
    그룹의 대표 이미지 선택
    우선순위: 팝업 이미지 > 클릭 후 이미지 > 클릭 전 이미지
    """
    if not group.images:
        return None
    
    # 팝업 이미지 우선 찾기
    for action in group.actions:
        if is_popup(action):
            screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
            if screenshot_path and os.path.exists(screenshot_path):
                return screenshot_path
    
    # 클릭 액션의 클릭 후 이미지 찾기
    click_actions = [a for a in group.actions if a.get("action_type") == "click"]
    for click_action in reversed(click_actions):
        screenshot_path = click_action.get("screenshot_real_path") or click_action.get("screenshot_path")
        if screenshot_path and os.path.exists(screenshot_path):
            return screenshot_path
    
    # 마지막으로 그룹의 첫 번째 이미지 사용
    if group.images:
        return group.images[0]
    
    return None


def group_screens(actions):
    """
    간단한 순차적 화면 그룹핑 함수
    - SSIM + OCR diff + elementBounds 변동으로 화면 변화 체크
    - 팝업 규칙 적용
    """
    groups = []
    current_group = new_group()
    
    prev_image = None
    prev_action = None
    
    for action in actions:
        curr_image = get_screenshot(action)
        
        if prev_image is None:
            # 첫 액션 → 그냥 현재 그룹에 넣기
            current_group.add(action, curr_image)
            prev_image = curr_image
            prev_action = action
            continue
        
        # 1) 화면 변화 체크 (SSIM + OCR diff + elementBounds 변동)
        same_screen = is_same_screen(prev_image, curr_image)
        
        # 2) 팝업 규칙
        prev_popup = is_popup(prev_action)
        curr_popup = is_popup(action)
        
        if same_screen:
            # 화면이 그대로면 그냥 같은 그룹
            current_group.add(action, curr_image)
        else:
            # 화면이 바뀐다. 팝업 관련인지 확인
            if prev_popup or curr_popup:
                # 팝업 전/후 이동 → 같은 그룹 유지
                current_group.add(action, curr_image)
            else:
                # 완전히 다른 화면 → 그룹 종료 후 새 그룹 시작
                groups.append(current_group)
                current_group = new_group()
                current_group.add(action, curr_image)
        
        prev_image = curr_image
        prev_action = action
    
    if current_group.not_empty():
        groups.append(current_group)
    
    # 각 그룹에 대표 이미지 설정
    for g in groups:
        g.representative_image = choose_representative_image(g)
    
    return groups


# ==========================
# 이미지 저장 함수
# ==========================
def save_highlighted_image(image_path, actions, output_path):
    """하이라이트가 그려진 이미지를 저장합니다."""
    valid_actions = []
    for action in actions:
        coords = ActionMetadataParser.get_coordinates(action)
        bounds = coords.get("elementBounds")
        x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
        y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
        
        if bounds or (x is not None and y is not None):
            valid_actions.append(action)
    
    if len(valid_actions) == 0:
        return None
    
    try:
        # 이미지 열기
        img = Image.open(image_path).convert("RGB")
        image_width = img.width
        image_height = img.height
        
        # Draw 객체 생성
        draw = ImageDraw.Draw(img)
        
        # 폰트 설정 (라벨용)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
            except:
                font = ImageFont.load_default()
        
        meta0 = ActionMetadataParser.parse(valid_actions[0])
        coords0 = meta0.get("coordinates", {})
        vp_w = int(coords0.get("viewportWidth", 1859))
        vp_h = int(coords0.get("viewportHeight", 910))
        
        # 각 액션에 대해 하이라이트 그리기
        for idx, action in enumerate(valid_actions, start=1):
            coords = ActionMetadataParser.get_coordinates(action)
            bounds = coords.get("elementBounds", {})
            
            if bounds:
                top_ratio = bounds.get("topRatio")
                left_ratio = bounds.get("leftRatio")
                width_ratio = bounds.get("widthRatio")
                height_ratio = bounds.get("heightRatio")
                
                if all(r is not None for r in [top_ratio, left_ratio, width_ratio, height_ratio]):
                    # 비율을 픽셀 좌표로 변환
                    top = top_ratio * image_height
                    left = left_ratio * image_width
                    width = width_ratio * image_width
                    height = height_ratio * image_height
                    
                    # 하이라이트 박스 그리기 (파란색)
                    draw.rectangle(
                        [left, top, left + width, top + height],
                        outline="blue",
                        width=4
                    )
                    
                    # 라벨 그리기
                    label_text = str(idx)
                    bbox = draw.textbbox((0, 0), label_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    label_x = max(0, left - text_width - 5)
                    label_y = max(0, top - text_height - 5)
                    
                    # 라벨 배경
                    draw.rectangle(
                        [label_x - 2, label_y - 2, label_x + text_width + 2, label_y + text_height + 2],
                        fill="white",
                        outline="blue",
                        width=1
                    )
                    # 라벨 텍스트
                    draw.text((label_x, label_y), label_text, fill="blue", font=font)
            else:
                x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
                y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
                
                if x is not None and y is not None:
                    # 비율을 픽셀 좌표로 변환
                    scale_x = image_width / vp_w if vp_w > 0 else 1.0
                    scale_y = image_height / vp_h if vp_h > 0 else 1.0
                    center_x = x * scale_x
                    center_y = y * scale_y
                    box_size = 20
                    
                    # 원 그리기 (파란색)
                    draw.ellipse(
                        [center_x - box_size/2, center_y - box_size/2, 
                         center_x + box_size/2, center_y + box_size/2],
                        outline="blue",
                        width=4
                    )
                    
                    # 라벨 그리기
                    label_text = str(idx)
                    bbox = draw.textbbox((0, 0), label_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    label_x = max(0, center_x - text_width/2)
                    label_y = max(0, center_y - box_size/2 - text_height - 5)
                    
                    # 라벨 배경
                    draw.rectangle(
                        [label_x - 2, label_y - 2, label_x + text_width + 2, label_y + text_height + 2],
                        fill="white",
                        outline="blue",
                        width=1
                    )
                    # 라벨 텍스트
                    draw.text((label_x, label_y), label_text, fill="blue", font=font)
        
        # 이미지 저장 (최고 품질)
        img.save(output_path, "PNG", optimize=False)
        return output_path
    
    except Exception as e:
        st.error(f"❌ 이미지 저장 오류: {e}")
        return None


# ==========================
# 이미지 하이라이트 렌더러
# ==========================
def render_test_highlight(image_path, actions):
    """테스트용 하이라이트 렌더링"""
    valid_actions = []
    for action in actions:
        coords = ActionMetadataParser.get_coordinates(action)
        bounds = coords.get("elementBounds")
        x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
        y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
        
        if bounds or (x is not None and y is not None):
            valid_actions.append(action)
    
    if len(valid_actions) == 0:
        st.warning("⚠️ elementBounds 또는 x, y 좌표가 있는 액션이 없습니다.")
        return
    
    try:
        with Image.open(image_path) as pil_img:
            image_width = pil_img.width
            image_height = pil_img.height
    except Exception as e:
        st.error(f"❌ 이미지 읽기 오류: {e}")
        return
    
    meta0 = ActionMetadataParser.parse(valid_actions[0])
    coords0 = meta0.get("coordinates", {})
    vp_w = int(coords0.get("viewportWidth", 1859))
    vp_h = int(coords0.get("viewportHeight", 910))
    
    # 원본 이미지 그대로 사용 (압축 없이)
    with open(image_path, "rb") as f:
        img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode()
    
    wrapper_id = f"test-wrapper-{abs(hash(image_path))}"
    img_id = f"test-img-{abs(hash(image_path))}"
    
    bounds_data = []
    for idx, action in enumerate(valid_actions):
        coords = ActionMetadataParser.get_coordinates(action)
        bounds = coords.get("elementBounds", {})
        
        if bounds:
            top_ratio = bounds.get("topRatio")
            left_ratio = bounds.get("leftRatio")
            width_ratio = bounds.get("widthRatio")
            height_ratio = bounds.get("heightRatio")
            
            if all(r is not None for r in [top_ratio, left_ratio, width_ratio, height_ratio]):
                bounds_data.append({
                    'idx': idx + 1,
                    'type': 'bounds',
                    'topRatio': top_ratio,
                    'leftRatio': left_ratio,
                    'widthRatio': width_ratio,
                    'heightRatio': height_ratio
                })
        else:
            x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
            y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
            
            if x is not None and y is not None:
                box_size = 20
                bounds_data.append({
                    'idx': idx + 1,
                    'type': 'point',
                    'top': y - box_size / 2,
                    'left': x - box_size / 2,
                    'width': box_size,
                    'height': box_size,
                    'x': x,
                    'y': y
                })
    
    overlay_html = ""
    for data in bounds_data:
        box_id = f"test-box-{wrapper_id}-{data['idx']}"
        label_id = f"test-label-{wrapper_id}-{data['idx']}"
        
        if data.get('type') == 'point':
            scale_x_init = image_width / vp_w if vp_w > 0 else 1.0
            scale_y_init = image_height / vp_h if vp_h > 0 else 1.0
            center_x = data.get('x', 0) * scale_x_init
            center_y = data.get('y', 0) * scale_y_init
            box_size = 30
            init_left = center_x - box_size / 2
            init_top = center_y - box_size / 2
            init_width = box_size
            init_height = box_size
        else:
            top_ratio = data.get('topRatio', 0)
            left_ratio = data.get('leftRatio', 0)
            width_ratio = data.get('widthRatio', 0)
            height_ratio = data.get('heightRatio', 0)
            
            init_top = top_ratio * image_height
            init_left = left_ratio * image_width
            init_width = width_ratio * image_width
            init_height = height_ratio * image_height
        
        overlay_html += f'<div id="{box_id}" class="test-overlay-box" style="position:absolute!important;top:{init_top}px!important;left:{init_left}px!important;width:{init_width}px!important;height:{init_height}px!important;border:4px solid blue!important;background-color:rgba(0,0,255,0.5)!important;box-sizing:border-box!important;pointer-events:none!important;z-index:10!important;display:block!important;"></div>'
        label_top_init = max(0, init_top - 15)
        label_left_init = max(0, init_left - 15)
        overlay_html += f'<div id="{label_id}" class="test-overlay-label" style="position:absolute!important;top:{label_top_init}px!important;left:{label_left_init}px!important;background:white!important;color:blue!important;border:1px solid blue!important;width:12px!important;height:12px!important;border-radius:50%!important;line-height:12px!important;text-align:center!important;font-weight:bold!important;font-size:7px!important;z-index:20!important;display:block!important;">{data["idx"]}</div>'
    
    bounds_json = json.dumps(bounds_data)
    
    js_code = f"""
    <script>
    (function() {{
        // ============================================
        // DOM 트리 수집 및 압축 함수들
        // ============================================
        function isVisible(el) {{
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (!rect.width && !rect.height) return false;
            if (style.display === "none") return false;
            if (style.visibility === "hidden") return false;
            if (+style.opacity === 0) return false;
            return true;
        }}

        function getOwnText(el) {{
            let own = "";
            el.childNodes.forEach(n => {{
                if (n.nodeType === Node.TEXT_NODE) {{
                    const t = n.textContent?.trim();
                    if (t) own += t + " ";
                }}
            }});
            return own.trim() || null;
        }}

        // tag가 div, span이면 제외
        function getMetaFlat(el) {{
            const obj = {{}};
            const tag = el.tagName.toLowerCase();

            if (tag !== "div" && tag !== "span") obj.tag = tag;
            if (el.id) obj.id = el.id;

            const role = el.getAttribute("role");
            if (role) obj.role = role;

            return obj;
        }}

        // 기본 트리 수집
        function collectPure(root = document.body, depth = 0) {{
            const results = [];

            [...root.children].forEach(el => {{
                if (!isVisible(el)) return;

                const ownText = getOwnText(el);
                const metaFlat = getMetaFlat(el);
                const children = collectPure(el, depth + 1);

                const node = {{
                    depth,
                    ...metaFlat
                }};

                if (ownText !== null) node.text = ownText;
                if (children.length > 0) node.children = children;

                results.push(node);
            }});

            return results;
        }}

        // text 없는 leaf 제거
        function pruneTree(nodes) {{
            const pruned = [];

            nodes.forEach(node => {{
                let newNode = {{ ...node }};

                if (newNode.children) {{
                    newNode.children = pruneTree(newNode.children);
                }}

                const hasText = newNode.text && newNode.text.trim().length > 0;
                const hasChildren = newNode.children && newNode.children.length > 0;

                if (!hasText && !hasChildren) return;

                pruned.push(newNode);
            }});

            return pruned;
        }}

        // depthChain 압축
        function compressEmptyChains(nodes) {{
            return nodes.map(node => compressNode(node));
        }}

        function compressNode(node) {{
            let n = {{ ...node }};

            if (n.children && n.children.length > 0) {{
                n.children = n.children.map(c => compressNode(c));
            }}

            const isWrapper =
                !n.text &&
                !n.tag &&
                !n.id &&
                !n.role &&
                n.children &&
                n.children.length === 1;

            if (isWrapper) {{
                const child = n.children[0];
                const chain = [child.depth];

                if (child.depthChain) {{
                    chain.push(...child.depthChain);
                }}

                return {{
                    depth: n.depth,
                    depthChain: chain,
                    ...removeUndefinedKeys({{
                        tag: child.tag,
                        id: child.id,
                        role: child.role,
                        text: child.text,
                        children: child.children
                    }})
                }};
            }}

            return n;
        }}

        function removeUndefinedKeys(obj) {{
            const clean = {{}};
            for (const k in obj) {{
                if (obj[k] !== undefined) clean[k] = obj[k];
            }}
            return clean;
        }}

        function printResult(result) {{
            function replacer(key, value) {{
                if (key === "depthChain" && Array.isArray(value)) {{
                    return `[${{value.join(",")}}]`;
                }}
                return value;
            }}

            let json = JSON.stringify(result, replacer, 2);
            json = json.replace(/"\\[(.*?)\\]"/g, "[$1]");
            console.log(json);
        }}

        // DOM 트리 수집 실행 (옵션)
        // const raw = collectPure(document.body);
        // const pruned = pruneTree(raw);
        // const compressed = compressEmptyChains(pruned);
        // printResult(compressed);

        // ============================================
        // 하이라이트 조정 함수
        // ============================================
        const wrapperId = '{wrapper_id}';
        const wrapper = document.getElementById(wrapperId);
        const imgId = '{img_id}';
        const img = document.getElementById(imgId);
        
        if (!wrapper || !img) {{
            console.error('요소를 찾을 수 없습니다:', {{wrapperId, imgId, wrapper: !!wrapper, img: !!img}});
            return;
        }}
        
        const viewportWidth = {vp_w};
        const viewportHeight = {vp_h};
        const boundsData = {bounds_json};
        
        function adjustHighlights() {{
            if (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0) {{
                setTimeout(adjustHighlights, 500);
                return;
            }}
            
            let imgDisplayWidth = img.offsetWidth || img.clientWidth;
            let imgDisplayHeight = img.offsetHeight || img.offsetHeight;
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                const rect = img.getBoundingClientRect();
                imgDisplayWidth = rect.width;
                imgDisplayHeight = rect.height;
            }}
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                imgDisplayWidth = img.naturalWidth;
                imgDisplayHeight = img.naturalHeight;
            }}
            
            const scaleX = imgDisplayWidth / viewportWidth;
            const scaleY = imgDisplayHeight / viewportHeight;
            
            boundsData.forEach(function(data) {{
                const boxId = 'test-box-' + wrapperId + '-' + data.idx;
                const labelId = 'test-label-' + wrapperId + '-' + data.idx;
                
                const box = document.getElementById(boxId);
                const label = document.getElementById(labelId);
                
                if (!box || !label) {{
                    return;
                }}
                
                let drawTop, drawLeft, drawWidth, drawHeight;
                
                if (data.type === 'point') {{
                    const centerX = data.x * scaleX;
                    const centerY = data.y * scaleY;
                    const boxSize = 20;
                    drawLeft = centerX - boxSize / 2;
                    drawTop = centerY - boxSize / 2;
                    drawWidth = boxSize;
                    drawHeight = boxSize;
                }} else {{
                    const topRatio = data.topRatio;
                    const leftRatio = data.leftRatio;
                    const widthRatio = data.widthRatio;
                    const heightRatio = data.heightRatio;
                    
                    drawTop = topRatio * imgDisplayHeight;
                    drawLeft = leftRatio * imgDisplayWidth;
                    drawWidth = widthRatio * imgDisplayWidth;
                    drawHeight = heightRatio * imgDisplayHeight;
                }}
                
                box.style.setProperty('top', drawTop + 'px', 'important');
                box.style.setProperty('left', drawLeft + 'px', 'important');
                box.style.setProperty('width', Math.max(10, drawWidth) + 'px', 'important');
                box.style.setProperty('height', Math.max(10, drawHeight) + 'px', 'important');
                box.style.setProperty('display', 'block', 'important');
                box.style.setProperty('position', 'absolute', 'important');
                box.style.setProperty('border', '4px solid #0000ff', 'important');
                box.style.setProperty('background-color', 'rgba(0, 0, 255, 0.5)', 'important');
                box.style.setProperty('box-sizing', 'border-box', 'important');
                box.style.setProperty('pointer-events', 'none', 'important');
                box.style.setProperty('z-index', '100', 'important');
                
                if (data.type === 'point') {{
                    box.style.setProperty('border-radius', '50%', 'important');
                }}
                
                const labelTop = Math.max(0, drawTop - 10);
                const labelLeft = Math.max(0, drawLeft - 10);
                label.style.setProperty('top', labelTop + 'px', 'important');
                label.style.setProperty('left', labelLeft + 'px', 'important');
                label.style.setProperty('display', 'block', 'important');
            }});
        }}
        
        if (img.complete) {{
            setTimeout(adjustHighlights, 500);
        }} else {{
            img.addEventListener('load', function() {{
                setTimeout(adjustHighlights, 500);
            }});
        }}
        
        let attempts = 0;
        const maxAttempts = 50;
        const checkInterval = setInterval(function() {{
            attempts++;
            const width = img.offsetWidth || img.getBoundingClientRect().width;
            if (width > 0 || attempts >= maxAttempts) {{
                clearInterval(checkInterval);
                adjustHighlights();
                setTimeout(adjustHighlights, 1000);
                setTimeout(adjustHighlights, 2000);
            }}
        }}, 200);
    }})();
    </script>
    """
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }}
        .container {{
            width: 100% !important;
            height: 100vh !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            overflow: hidden !important;
        }}
        .test-original-img {{
            max-width: 100% !important;
            max-height: 100vh !important;
            width: auto !important;
            height: auto !important;
            object-fit: contain !important;
            position: relative !important;
            z-index: 1 !important;
            display: block !important;
            image-rendering: auto !important;
            -ms-interpolation-mode: bicubic !important;
        }}
        .test-overlay-wrapper {{
            position: relative !important;
            display: inline-block !important;
            max-width: 100% !important;
            max-height: 100vh !important;
        }}
        .test-overlay-box {{
            position: absolute !important;
            border: 4px solid blue !important;
            background-color: rgba(0, 0, 255, 0.5) !important;
            pointer-events: none !important;
            box-sizing: border-box !important;
            z-index: 10 !important;
        }}
        .test-overlay-label {{
            position: absolute !important;
            background: white !important;
            color: blue !important;
            border: 1px solid blue !important;
            width: 10px !important;
            height: 10px !important;
            border-radius: 50% !important;
            line-height: 10px !important;
            text-align: center !important;
            font-weight: bold !important;
            font-size: 6px !important;
            pointer-events: none !important;
            z-index: 20 !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div id="{wrapper_id}" class="test-overlay-wrapper">
            <img id="{img_id}" class="test-original-img"
                 src="data:image/png;base64,{img_b64}"
                 style="image-rendering: auto; -ms-interpolation-mode: bicubic;"
                 loading="eager">
            {overlay_html}
        </div>
    </div>
    {js_code}
</body>
</html>
"""
    
    components.html(html, height=600, scrolling=False)


# ==========================
# MAIN UI (테스트 환경)
# ==========================
st.title("🧪 범용 화면 분류기: 클릭 전 이미지 기준 그룹핑")

st.info("💡 **핵심 아이디어**: 클릭 전 스크린샷 이미지(_prev_screenshot) 기준으로 그룹핑. 팝업은 분리하지 않고 같은 그룹에 포함.")

json_file = "data/actions/metadata_182.json"
if not os.path.exists(json_file):
    st.error(f"❌ JSON 파일을 찾을 수 없습니다: {json_file}")
    st.stop()

actions = load_actions(json_file)
st.info(f"📊 총 {len(actions)}개의 액션을 로드했습니다.")

# action_sequence 확인 및 디버깅
if actions:
    first_seq = actions[0].get("action_sequence")
    last_seq = actions[-1].get("action_sequence")
    st.caption(f"🔍 action_sequence 범위: {first_seq} ~ {last_seq} (첫 액션: {actions[0].get('action_type')}, 마지막 액션: {actions[-1].get('action_type')})")

# 클릭 액션만 필터링
click_actions = [a for a in actions if a.get("action_type") == "click"]
st.info(f"🖱️ 클릭 액션: {len(click_actions)}개")

# 진행 표시
progress_bar = st.progress(0)
status_text = st.empty()

def update_progress(progress, message):
    progress_bar.progress(progress)
    status_text.text(f"🔄 {message}")

# 재그룹핑 limit 확인 (저장하기 버튼 클릭 시 설정됨)
regroup_limits = []
for key in st.session_state.keys():
    if key.startswith("regroup_limit_"):
        limit_seq = st.session_state[key]
        if isinstance(limit_seq, (int, float)):
            regroup_limits.append(limit_seq)

# 재그룹핑이 필요한 경우: limit 시점 이후의 액션만으로 재그룹핑
if regroup_limits and st.session_state.get("regroup_triggered", False):
    max_limit = max(regroup_limits)
    st.info(f"🔄 재그룹핑 모드: 시점 {max_limit} 이후의 액션만 그룹핑합니다.")
    
    # limit 시점 이후의 액션만 필터링
    filtered_actions = [a for a in actions if a.get("action_sequence", 999999) > max_limit]
    
    if filtered_actions:
        # 필터링된 액션으로 재그룹핑
        grouper = ScreenGrouper(filtered_actions, progress_callback=update_progress)
        screens = grouper.run()
        
        # 재그룹핑된 화면에 원본 시점 정보 추가
        for screen in screens:
            screen["is_regrouped"] = True
            screen["regroup_limit"] = max_limit
        
        # 재그룹핑 완료 후 플래그 초기화
        st.session_state["regroup_triggered"] = False
    else:
        st.warning("⚠️ 재그룹핑할 액션이 없습니다.")
        screens = []
        st.session_state["regroup_triggered"] = False
else:
    # 일반 그룹핑 (전체 액션)
    grouper = ScreenGrouper(actions, progress_callback=update_progress)
    screens = grouper.run()

# 최종 검증: 모든 화면과 액션이 action_sequence 순서대로 정렬되었는지 확인 및 재정렬
for screen_idx, screen in enumerate(screens):
    screen_actions = screen.get("actions", [])
    if screen_actions:
        sequences = [a.get("action_sequence", 999999) for a in screen_actions]
        # 정렬 확인
        if sequences != sorted(sequences):
            screen["actions"].sort(key=lambda a: a.get("action_sequence", 999999))
            # first_action_sequence 업데이트
            screen["first_action_sequence"] = screen["actions"][0].get("action_sequence", 999999)

# 화면 순서 최종 재정렬 (action_sequence 기준)
screens.sort(key=lambda s: s.get("first_action_sequence", 999999))

# 진행 바 숨기기
progress_bar.empty()
status_text.empty()

# 통계 대시보드
st.success(f"✅ 총 **{len(screens)}개**의 화면으로 그룹핑되었습니다.")

# 통계 메트릭
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("📊 총 액션", grouper.stats["total_actions"])
with col2:
    st.metric("🖱️ 클릭 액션", grouper.stats["click_actions"])
with col3:
    st.metric("🖼️ 이미지 로드", grouper.stats["images_loaded"])
with col4:
    st.metric("🔍 클러스터", grouper.stats["clusters_created"])

# pHash 거리 통계
if grouper.stats["phash_distances"]:
    distances = grouper.stats["phash_distances"]
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📏 평균 pHash 거리", f"{sum(distances) / len(distances):.2f}")
    with col2:
        st.metric("📏 최소 pHash 거리", f"{min(distances):.2f}")
    with col3:
        st.metric("📏 최대 pHash 거리", f"{max(distances):.2f}")
    
    # pHash 거리 분포
    within_threshold = sum(1 for d in distances if d <= 18)
    st.caption(f"📊 pHash 거리 ≤ 18: {within_threshold}/{len(distances)} ({within_threshold/len(distances)*100:.1f}%)")

# 그룹핑 결과 표시
with st.expander("🔍 범용 분류기 상세 정보", expanded=False):
    st.write("**그룹핑 방법:**")
    st.write("1. 📸 **클릭 전 이미지 기준**: 클릭 액션의 _prev_screenshot을 기준으로 그룹핑")
    st.write("2. 🔍 **pHash distance ≤ 18**: 같은 클릭 전 이미지면 같은 화면 그룹")
    st.write("3. 🎯 **팝업 포함**: 팝업은 분리하지 않고 같은 그룹에 포함 (클릭 후 팝업까지 하나의 화면)")
    st.write("4. 🖼️ **대표 이미지**: 팝업 이미지 우선, 없으면 클릭 전 이미지")
    st.write(f"\n**그룹핑 결과:** {len(screens)}개 그룹")
    
    # 각 그룹의 상세 정보
    for idx, screen in enumerate(screens):
        is_popup = screen.get('is_popup', False)
        popup_marker = " (팝업)" if is_popup else ""
        popup_img = screen.get('popup_image')
        prev_img = screen.get('prev_image')
        
        info_text = f"- 그룹 {idx+1}: `{screen.get('screen_name', '알 수 없음')}`{popup_marker} ({len(screen.get('actions', []))}개 액션)"
        if popup_img:
            info_text += f" | 팝업 이미지: ✅"
        elif prev_img:
            info_text += f" | 클릭 전 이미지: ✅"
        st.write(info_text)

# 통계 정보
total_clicks = sum(len(s.get("click_actions", [])) for s in screens)
st.caption(f"📈 그룹별 클릭 액션 총합: {total_clicks}개")


# ==========================
# 화면(그룹) 하나씩 렌더링 (테스트 스타일)
# ==========================
for screen_idx, screen in enumerate(screens):
    screen_name = screen.get("screen_name", "알 수 없음")
    click_actions_in_screen = screen.get("click_actions", [])
    all_actions_in_screen = screen.get("actions", [])
    
    # elementBounds가 있는 클릭 액션만 필터링
    valid_click_actions = []
    for action in click_actions_in_screen:
        bounds = ActionMetadataParser.get_element_bounds(action)
        if bounds:
            valid_click_actions.append(action)
    
    # 화면 정보 요약
    popup_img = screen.get('popup_image')
    prev_img = screen.get('prev_image')
    has_popup = popup_img is not None
    
    # 첫 번째와 마지막 액션의 action_sequence 표시
    first_seq = all_actions_in_screen[0].get("action_sequence", "N/A") if all_actions_in_screen else "N/A"
    last_seq = all_actions_in_screen[-1].get("action_sequence", "N/A") if all_actions_in_screen else "N/A"
    
    expander_title = f"🧪 Screen {screen_idx + 1}: {screen_name}"
    expander_title += f" | seq:{first_seq}~{last_seq}"
    expander_title += f" | 클릭 {len(click_actions_in_screen)}개"
    expander_title += f" | elementBounds {len(valid_click_actions)}개"
    if has_popup:
        expander_title += " | 🎯 팝업 포함"
    
    with st.expander(expander_title, expanded=(screen_idx == 0)):
        # 화면 상세 정보
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("전체 액션", len(all_actions_in_screen))
        with col2:
            st.metric("클릭 액션", len(click_actions_in_screen))
        with col3:
            st.metric("elementBounds", len(valid_click_actions))
        
        # 이미지 정보
        click_result_img = screen.get('click_result_image')
        if popup_img:
            st.info(f"🎯 팝업 이미지 사용: `{os.path.basename(popup_img)}`")
        elif click_result_img:
            st.info(f"📸 클릭 결과 이미지 사용: `{os.path.basename(click_result_img)}`")
        elif prev_img:
            st.info(f"📸 클릭 전 이미지 사용: `{os.path.basename(prev_img)}`")
        
        # 팝업이 있는 경우 "저장하기" 버튼 추가 (재그룹핑용)
        if has_popup:
            # 저장하기 버튼이 클릭되었는지 확인
            save_key = f"popup_save_{screen_idx}"
            if save_key not in st.session_state:
                st.session_state[save_key] = False
            
            # 재그룹핑 limit 정보 표시
            regroup_limit = screen.get("regroup_limit")
            if regroup_limit:
                st.info(f"🔄 재그룹핑 기준 시점: {regroup_limit}")
            
            col_save1, col_save2 = st.columns([1, 4])
            with col_save1:
                if st.button("💾 저장하기", key=f"popup_save_btn_{screen_idx}"):
                    # 저장하기 버튼 클릭 시 해당 시점을 기준으로 재그룹핑
                    st.session_state[save_key] = True
                    # 마지막 액션의 시점을 limit으로 설정
                    limit_seq = last_seq if isinstance(last_seq, (int, float)) else all_actions_in_screen[-1].get("action_sequence", 999999) if all_actions_in_screen else 999999
                    st.session_state[f"regroup_limit_{screen_idx}"] = limit_seq
                    st.session_state["regroup_triggered"] = True
                    st.rerun()
            
            with col_save2:
                if st.session_state.get(save_key, False):
                    limit_seq = st.session_state.get(f"regroup_limit_{screen_idx}", "N/A")
                    st.success(f"✅ 저장 완료! 시점 {limit_seq}을 기준으로 재그룹핑됩니다.")
        
        # 대표 이미지 찾기
        image_path = screen.get("representative_image")
        
        if not image_path or not os.path.exists(image_path):
            actions_to_check = valid_click_actions if len(valid_click_actions) > 0 else click_actions_in_screen
            if len(actions_to_check) > 0:
                last_click_action = actions_to_check[-1]
                screenshot_path = last_click_action.get("screenshot_real_path") or last_click_action.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    image_path = screenshot_path
        
        if image_path and os.path.exists(image_path):
            # 이미지 저장 버튼
            col1, col2 = st.columns([3, 1])
            with col1:
                # 테스트용 하이라이트 렌더링 (파란색 스타일)
                render_test_highlight(image_path, valid_click_actions)
            with col2:
                st.write("")  # 공간 확보
                st.write("")  # 공간 확보
                
                # 저장 디렉토리 생성
                save_dir = "saved_images"
                os.makedirs(save_dir, exist_ok=True)
                
                # 저장 파일명 생성
                screen_num = screen_idx + 1
                first_seq = first_seq if isinstance(first_seq, (int, float)) else "unknown"
                last_seq = last_seq if isinstance(last_seq, (int, float)) else "unknown"
                save_filename = f"screen_{screen_num}_seq{first_seq}-{last_seq}.png"
                save_path = os.path.join(save_dir, save_filename)
                
                if st.button("💾 이미지 저장", key=f"save_{screen_idx}"):
                    saved_path = save_highlighted_image(image_path, valid_click_actions, save_path)
                    if saved_path:
                        st.success(f"✅ 저장 완료: `{saved_path}`")
                        # 다운로드 버튼
                        with open(saved_path, "rb") as f:
                            st.download_button(
                                label="📥 다운로드",
                                data=f.read(),
                                file_name=save_filename,
                                mime="image/png",
                                key=f"download_{screen_idx}"
                            )
            
            # 액션 목록 표시
            st.write("### 📝 클릭 액션 목록 (테스트)")
            for idx, action in enumerate(valid_click_actions, start=1):
                coords = ActionMetadataParser.get_coordinates(action)
                bounds = coords.get("elementBounds", {})
                label = ActionMetadataParser.get_label(action)
                text_content = action.get("text_content") or action.get("description") or label or f"액션 {idx}"
                action_seq = action.get("action_sequence", "N/A")
                
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{idx}.** {text_content}")
                with col2:
                    st.caption(f"seq: {action_seq}")
                with col3:
                    if bounds:
                        st.caption(f"위치: ({bounds.get('left', 0)}, {bounds.get('top', 0)})")
        else:
            st.error("❌ 대표 이미지를 찾을 수 없습니다.")
            st.write("### 📝 클릭 액션 목록 (이미지 없음)")
            for idx, action in enumerate(valid_click_actions, start=1):
                label = ActionMetadataParser.get_label(action)
                text_content = action.get("text_content") or action.get("description") or label or f"액션 {idx}"
                st.write(f"**{idx}.** {text_content}")
