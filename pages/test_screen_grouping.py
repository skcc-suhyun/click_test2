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

    def __init__(self, actions):
        self.actions = actions
        self.cache = {}
        self.action_to_global_idx = {id(action): idx for idx, action in enumerate(actions)}

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
    def cluster_by_image(self):
        """
        핵심: 클릭 전 스크린샷 이미지(_prev_screenshot) 기준으로 그룹핑
        - pHash distance ≤ 18이면 같은 화면
        - 팝업도 같은 '전 이미지'면 같은 그룹에 포함
        """
        groups = []
        used_actions = set()
        prev_image_to_group = {}  # 클릭 전 이미지 -> 그룹 매핑
        
        # 먼저 모든 클릭 액션의 _prev_screenshot 설정
        self._set_prev_screenshots()
        
        for i, act in enumerate(self.actions):
            if id(act) in used_actions:
                continue
            
            # 클릭 액션인 경우: _prev_screenshot 기준으로 그룹핑
            if act.get("action_type") == "click":
                prev_screenshot = act.get("_prev_screenshot")
                
                if prev_screenshot and os.path.exists(prev_screenshot):
                    # 클릭 전 이미지의 해시 계산
                    prev_img = self.load_image(prev_screenshot)
                    if prev_img:
                        prev_hash = self.phash(prev_img)
                        
                        # 기존 그룹 중 유사한 클릭 전 이미지가 있는지 확인
                        found_group = None
                        for prev_path, group_info in prev_image_to_group.items():
                            prev_img2 = self.load_image(prev_path)
                            if prev_img2:
                                prev_hash2 = self.phash(prev_img2)
                                distance = self.phash_distance(prev_hash, prev_hash2)
                                
                                if distance <= 18:
                                    found_group = group_info["group"]
                                    break
                        
                        if found_group:
                            # 기존 그룹에 추가 (순서 유지를 위해 인덱스 기준으로 삽입)
                            found_group["actions"].append(act)
                            # 액션 순서 정렬 (원본 순서 유지)
                            found_group["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))
                            used_actions.add(id(act))
                        else:
                            # 새 그룹 생성
                            group = {
                                "prev_image": prev_screenshot,
                                "prev_image_hash": prev_hash,
                                "images": [prev_screenshot],
                                "actions": [act],
                                "representative_image": None,  # 나중에 설정
                                "first_action_idx": i  # 첫 번째 액션 인덱스 저장
                            }
                            groups.append(group)
                            prev_image_to_group[prev_screenshot] = {
                                "group": group,
                                "hash": prev_hash
                            }
                            used_actions.add(id(act))
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
                # 클릭이 아닌 액션: 이전 클릭 액션의 그룹에 포함
                # 이전 액션들을 역순으로 확인하여 클릭 액션 찾기
                found_group = None
                for j in range(i - 1, -1, -1):
                    prev_act = self.actions[j]
                    if prev_act.get("action_type") == "click" and id(prev_act) in used_actions:
                        # 이전 클릭 액션이 속한 그룹 찾기
                        for group in groups:
                            if prev_act in group["actions"]:
                                found_group = group
                                break
                        if found_group:
                            break
                
                if found_group:
                    found_group["actions"].append(act)
                    # 액션 순서 정렬 (원본 순서 유지)
                    found_group["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))
                    used_actions.add(id(act))
                elif groups:
                    # 그룹을 찾지 못했으면 마지막 그룹에 추가
                    groups[-1]["actions"].append(act)
                    # 액션 순서 정렬
                    groups[-1]["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))
                    used_actions.add(id(act))
        
        # 처리되지 않은 액션들을 마지막 그룹에 추가
        for act in self.actions:
            if id(act) not in used_actions:
                if groups:
                    groups[-1]["actions"].append(act)
                    # 액션 순서 정렬
                    groups[-1]["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))
                else:
                    act_idx = self.action_to_global_idx.get(id(act), 999999)
                    groups.append({
                        "prev_image": None,
                        "prev_image_hash": None,
                        "images": [],
                        "actions": [act],
                        "representative_image": None,
                        "first_action_idx": act_idx
                    })
                used_actions.add(id(act))

        # 그룹들을 첫 번째 액션 인덱스 순으로 정렬 (원본 순서 유지)
        groups.sort(key=lambda g: g.get("first_action_idx", 999999) if g.get("first_action_idx") is not None else 999999)

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
    # 2차: 팝업 분리
    # ---------------------------
    def is_popup_action(self, action):
        meta = ActionMetadataParser.parse(action)
        coords = meta.get("coordinates") or {}
        bounds = coords.get("elementBounds") or {}

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

    def process_clusters(self, clusters):
        """
        클러스터 후처리: 팝업은 분리하지 않고 같은 그룹에 유지
        대표 이미지는 팝업 이미지 우선, 없으면 클릭 전 이미지
        """
        results = []
        
        for cluster in clusters:
            # 액션 순서 정렬 (원본 순서 유지 - 이미 정렬되어 있을 수 있지만 확실히)
            cluster["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))
            
            # 팝업 이미지 찾기 (클릭 후 팝업 이미지)
            popup_image = None
            prev_image = cluster.get("prev_image")
            
            for act in cluster["actions"]:
                if self.is_popup_action(act):
                    # 팝업 액션의 스크린샷 (클릭 후 팝업 이미지)
                    popup_img_path = act.get("screenshot_real_path") or act.get("screenshot_path")
                    if popup_img_path and os.path.exists(popup_img_path):
                        popup_image = popup_img_path
                        break
            
            # 대표 이미지: 팝업 이미지 우선, 없으면 클릭 전 이미지
            representative_image = popup_image or prev_image
            
            # 클릭 액션 추출
            click_actions = [a for a in cluster["actions"] if a.get("action_type") == "click"]
            
            # elementBounds가 있는 클릭 액션 확인
            valid_click_count = 0
            for action in click_actions:
                bounds = ActionMetadataParser.get_element_bounds(action)
                if bounds:
                    valid_click_count += 1
            
            # 클릭 액션이 있고 elementBounds가 있는 액션이 있으면 유효한 화면
            if len(click_actions) > 0 and valid_click_count > 0:
                results.append({
                    "type": "screen",
                    "screen_name": f"화면 {len(results) + 1}",
                    "actions": cluster["actions"],
                    "images": cluster.get("images", []),
                    "representative_image": representative_image,
                    "is_popup": False,
                    "prev_image": prev_image,
                    "popup_image": popup_image
                })

        return results

    # ---------------------------
    # 최종 실행
    # ---------------------------
    def run(self):
        # 클릭 전 이미지 기준으로 클러스터링
        img_clusters = self.cluster_by_image()
        
        # 팝업 분리 없이 후처리 (팝업은 같은 그룹에 유지)
        screens = self.process_clusters(img_clusters)

        # 화면 순서 정렬 (원본 action의 순서 기반 - 이미 정렬되어 있을 수 있지만 확실히)
        screens.sort(key=lambda s: self.action_to_global_idx.get(id(s["actions"][0]), 999999) if s["actions"] else 999999)
        
        # 각 화면 내 액션 순서도 확실히 정렬
        for screen in screens:
            screen["actions"].sort(key=lambda a: self.action_to_global_idx.get(id(a), 999999))

        # 클릭 액션 추출
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

        return screens


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
                 src="data:image/png;base64,{img_b64}">
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

# 클릭 액션만 필터링
click_actions = [a for a in actions if a.get("action_type") == "click"]
st.info(f"🖱️ 클릭 액션: {len(click_actions)}개")

# 진행 표시
with st.spinner("🔄 이미지 해시 계산 및 화면 그룹핑 중..."):
    # 범용 그룹핑 사용 (pHash + SSIM 기반)
    grouper = ScreenGrouper(actions)
    screens = grouper.run()

# 그룹핑 결과 표시
with st.expander("🔍 범용 분류기 디버깅 정보", expanded=True):
    st.write("**그룹핑 방법:**")
    st.write("1. 📸 **클릭 전 이미지 기준**: 클릭 액션의 _prev_screenshot을 기준으로 그룹핑")
    st.write("2. 🔍 **pHash distance ≤ 18**: 같은 클릭 전 이미지면 같은 화면 그룹")
    st.write("3. 🎯 **팝업 포함**: 팝업은 분리하지 않고 같은 그룹에 포함 (클릭 후 팝업까지 하나의 화면)")
    st.write("4. 🖼️ **대표 이미지**: 팝업 이미지 우선, 없으면 클릭 전 이미지")
    st.write(f"\n**그룹핑 결과:** {len(screens)}개 그룹")
    for idx, screen in enumerate(screens):
        is_popup = screen.get('is_popup', False)
        popup_marker = " (팝업)" if is_popup else ""
        st.write(f"- 그룹 {idx+1}: `{screen.get('screen_name', '알 수 없음')}`{popup_marker} ({len(screen.get('actions', []))}개 액션)")

st.success(f"✅ 총 **{len(screens)}개**의 화면으로 그룹핑되었습니다. (범용 분류기)")

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
    
    with st.expander(
        f"🧪 Screen {screen_idx + 1} (TEST): {screen_name} (클릭 {len(click_actions_in_screen)}개, elementBounds {len(valid_click_actions)}개)", 
        expanded=(screen_idx == 0)
    ):
        st.write(f"🔸 전체 액션: **{len(all_actions_in_screen)}개** | 클릭 액션 (elementBounds 있음): **{len(valid_click_actions)}개**")
        
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
            # 테스트용 하이라이트 렌더링 (파란색 스타일)
            render_test_highlight(image_path, valid_click_actions)
            
            # 액션 목록 표시
            st.write("### 📝 클릭 액션 목록 (테스트)")
            for idx, action in enumerate(valid_click_actions, start=1):
                coords = ActionMetadataParser.get_coordinates(action)
                bounds = coords.get("elementBounds", {})
                label = ActionMetadataParser.get_label(action)
                text_content = action.get("text_content") or action.get("description") or label or f"액션 {idx}"
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{idx}.** {text_content}")
                with col2:
                    if bounds:
                        st.caption(f"위치: ({bounds.get('left', 0)}, {bounds.get('top', 0)})")
        else:
            st.error("❌ 대표 이미지를 찾을 수 없습니다.")
            st.write("### 📝 클릭 액션 목록 (이미지 없음)")
            for idx, action in enumerate(valid_click_actions, start=1):
                label = ActionMetadataParser.get_label(action)
                text_content = action.get("text_content") or action.get("description") or label or f"액션 {idx}"
                st.write(f"**{idx}.** {text_content}")
