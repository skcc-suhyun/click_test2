import sys
import os
import json
import base64
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont
from modules.loader import load_actions

# ==========================
# CSS (박스, 번호 스타일)
# ==========================
if not hasattr(st.session_state, 'screen_grouping_css_injected'):
    st.markdown("""
    <style>
    .original-img {
        max-width: 100% !important;
        max-height: 100vh !important;
        width: auto !important;
        height: auto !important;
        object-fit: contain !important;
        position: relative !important;
        z-index: 1 !important;
    }
    .overlay-wrapper {
        position: relative !important;
        display: inline-block !important;
        max-width: 100% !important;
        max-height: 100vh !important;
    }
    .overlay-box {
        position: absolute !important;
        border: 3px solid red !important;
        background-color: rgba(255, 0, 0, 0.3) !important;
        pointer-events: none !important;
        box-sizing: border-box !important;
        z-index: 10 !important;
    }
    .overlay-label {
        position: absolute !important;
        background: white !important;
        color: red !important;
        border: 1px solid red !important;
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
    st.session_state.screen_grouping_css_injected = True


# ==========================
# Utility
# ==========================
def parse_metadata(action):
    m = action.get("metadata")
    if isinstance(m, str):
        try:
            return json.loads(m)
        except:
            return {}
    return m or {}


# ==========================
# 이미지 저장 함수: 하이라이트 포함
# ==========================
def save_image_with_highlights(image_path, actions, output_path=None):
    """이미지에 하이라이트 박스와 번호를 그려서 저장합니다.
    
    Args:
        image_path: 원본 이미지 경로
        actions: 액션 리스트
        output_path: 저장할 경로 (None이면 자동 생성)
    
    Returns:
        저장된 이미지 경로
    """
    # 유효한 액션 필터링
    valid_actions = []
    for action in actions:
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds")
        x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
        y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
        
        if bounds or (x is not None and y is not None):
            valid_actions.append(action)
    
    if len(valid_actions) == 0:
        return None
    
    # 이미지 열기
    try:
        img = Image.open(image_path).copy()
    except Exception as e:
        st.error(f"❌ 이미지 읽기 오류: {e}")
        return None
    
    image_width = img.width
    image_height = img.height
    
    # 첫 액션에서 viewport 크기 획득
    meta0 = parse_metadata(valid_actions[0])
    coords0 = meta0.get("coordinates", {})
    vp_w = int(coords0.get("viewportWidth", image_width))
    vp_h = int(coords0.get("viewportHeight", image_height))
    
    # ImageDraw 객체 생성
    draw = ImageDraw.Draw(img)
    
    # 폰트 설정 (시도)
    try:
        # 기본 폰트 크기 계산 (이미지 크기에 비례)
        font_size = max(20, int(image_width / 50))
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", font_size)
        except:
            try:
                font = ImageFont.load_default()
            except:
                font = None
    
    # 각 액션에 대해 박스와 번호 그리기
    for idx, action in enumerate(valid_actions):
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds", {})
        
        # 박스 좌표 계산
        if bounds:
            # elementBounds 사용 (ratio 기반)
            top_ratio = bounds.get("topRatio")
            left_ratio = bounds.get("leftRatio")
            width_ratio = bounds.get("widthRatio")
            height_ratio = bounds.get("heightRatio")
            
            if all(r is not None for r in [top_ratio, left_ratio, width_ratio, height_ratio]):
                left = left_ratio * image_width
                top = top_ratio * image_height
                right = left + (width_ratio * image_width)
                bottom = top + (height_ratio * image_height)
            else:
                continue
        else:
            # x, y 좌표 사용
            x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
            y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
            
            if x is not None and y is not None:
                # viewport 좌표를 이미지 좌표로 변환
                scale_x = image_width / vp_w if vp_w > 0 else 1.0
                scale_y = image_height / vp_h if vp_h > 0 else 1.0
                center_x = x * scale_x
                center_y = y * scale_y
                box_size = 30
                left = center_x - box_size / 2
                top = center_y - box_size / 2
                right = center_x + box_size / 2
                bottom = center_y + box_size / 2
            else:
                continue
        
        # 박스 그리기 (빨간색 테두리, 반투명 배경)
        box_coords = [left, top, right, bottom]
        
        # 반투명 배경
        overlay = Image.new('RGBA', img.size, (255, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(box_coords, fill=(255, 0, 0, 128))  # 반투명 빨강
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        
        # 테두리 그리기 (두꺼운 빨간색)
        border_width = max(3, int(image_width / 500))
        for i in range(border_width):
            draw.rectangle(
                [left + i, top + i, right - i, bottom - i],
                outline=(255, 0, 0),
                width=1
            )
        
        # 번호 라벨 그리기 (원형 배경 + 번호)
        label_num = idx + 1
        label_size = max(20, int(image_width / 40))
        # 라벨 위치: 좌측 또는 우측에 배치
        offset_x = 10
        label_x = max(0, left - label_size - offset_x)
        label_y = max(0, top - 10)
        
        # 원형 배경 (흰색 배경, 빨간 테두리)
        label_coords = [
            label_x, label_y,
            label_x + label_size, label_y + label_size
        ]
        # 흰색 배경
        draw.ellipse(label_coords, fill=(255, 255, 255))
        # 빨간 테두리 (두 번 그려서 두껍게)
        for i in range(2):
            draw.ellipse([label_coords[0] + i, label_coords[1] + i, 
                         label_coords[2] - i, label_coords[3] - i], 
                        outline=(255, 0, 0))
        
        # 번호 텍스트 (빨간색)
        text = str(label_num)
        if font:
            # 텍스트 중앙 정렬을 위한 bbox 계산
            try:
                # PIL 9.0.0+ 에서는 textbbox 사용
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            except AttributeError:
                # 구버전 PIL에서는 textsize 사용
                try:
                    text_width, text_height = draw.textsize(text, font=font)
                except:
                    # textsize도 없으면 추정
                    text_width = len(text) * font_size * 0.6
                    text_height = font_size
            text_x = label_x + (label_size - text_width) / 2
            text_y = label_y + (label_size - text_height) / 2
            draw.text((text_x, text_y), text, fill=(255, 0, 0), font=font)
        else:
            # 폰트가 없으면 간단하게
            text_x = label_x + label_size / 2 - 5
            text_y = label_y + label_size / 2 - 8
            draw.text((text_x, text_y), text, fill=(255, 0, 0))
    
    # 저장 경로 결정
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        output_dir = os.path.join(os.path.dirname(image_path), "highlighted")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{base_name}_highlighted.png")
    
    # 이미지 저장
    try:
        img.save(output_path, "PNG")
        return output_path
    except Exception as e:
        st.error(f"❌ 이미지 저장 오류: {e}")
        return None


# ==========================
# Renderer: 다중 박스 + 번호
# ==========================
def render_grouped_highlight(image_path, actions):
    """하나의 화면 안의 여러 액션을 동시에 표시.
    
    지원하는 좌표 타입:
    1. elementBounds (DOM 요소의 경계 박스) - 우선순위 1
    2. x, y 좌표 (클릭 좌표) - 우선순위 2
    """

    # (1) elementBounds 또는 x, y 좌표가 있는 액션만 필터링
    valid_actions = []
    for action in actions:
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds")
        x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
        y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
        
        # elementBounds 또는 x, y 좌표가 있으면 유효한 액션
        if bounds or (x is not None and y is not None):
            valid_actions.append(action)
    
    if len(valid_actions) == 0:
        st.warning("⚠️ elementBounds 또는 x, y 좌표가 있는 액션이 없습니다.")
        return

    # (2) 실제 이미지 크기 읽기 (PIL 사용 - 초기값용)
    try:
        with Image.open(image_path) as pil_img:
            image_width = pil_img.width
            image_height = pil_img.height
    except Exception as e:
        st.error(f"❌ 이미지 읽기 오류: {e}")
        return

    # (3) 첫 액션에서 viewport 크기 획득
    meta0 = parse_metadata(valid_actions[0])
    coords0 = meta0.get("coordinates", {})

    vp_w = int(coords0.get("viewportWidth", 1859))
    vp_h = int(coords0.get("viewportHeight", 910))

    # (4) 이미지 base64 변환
    with open(image_path, "rb") as f:
        img_bytes = f.read()
        img_b64 = base64.b64encode(img_bytes).decode()

    # (5) 고유 ID 생성 (이미지 경로 기반, 음수 방지)
    wrapper_id = f"wrapper-{abs(hash(image_path))}"
    img_id = f"img-{abs(hash(image_path))}"

    # (6) elementBounds 또는 x, y 좌표 데이터 수집 (JavaScript에서 사용)
    bounds_data = []
    for idx, action in enumerate(valid_actions):
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds", {})
        
        # elementBounds 우선 사용 (ratio 기반)
        if bounds:
            top_ratio = bounds.get("topRatio")
            left_ratio = bounds.get("leftRatio")
            width_ratio = bounds.get("widthRatio")
            height_ratio = bounds.get("heightRatio")
            
            # ratio 없는 경우 그리지 않음
            if top_ratio is None or left_ratio is None or width_ratio is None or height_ratio is None:
                continue
            
            bounds_data.append({
                'idx': idx + 1,
                'type': 'bounds',
                'topRatio': top_ratio,
                'leftRatio': left_ratio,
                'widthRatio': width_ratio,
                'heightRatio': height_ratio
            })
        else:
            # x, y 좌표 사용 (작은 네모 박스로 표시)
            x = coords.get("x") or coords.get("pageX") or coords.get("clientX")
            y = coords.get("y") or coords.get("pageY") or coords.get("clientY")
            
            if x is not None and y is not None:
                # x, y 좌표를 중심으로 작은 박스 생성 (기본 20x20px)
                box_size = 20
                orig_left = x - box_size / 2
                orig_top = y - box_size / 2
                orig_width = box_size
                orig_height = box_size

                bounds_data.append({
                    'idx': idx + 1,
                    'type': 'point',
                    'top': orig_top,
                    'left': orig_left,
                    'width': orig_width,
                    'height': orig_height,
                    'x': x,
                    'y': y
                })

    # (7) overlay HTML 구성 (초기값으로도 일단 표시되도록 설정)
    overlay_html = ""
    for data in bounds_data:
        box_id = f"box-{wrapper_id}-{data['idx']}"
        label_id = f"label-{wrapper_id}-{data['idx']}"
        
        # 초기값 계산 (서버 사이드에서 미리 계산하여 일단 표시)
        if data.get('type') == 'point':
            # x, y 좌표 기반 초기값
            scale_x_init = image_width / vp_w if vp_w > 0 else 1.0
            scale_y_init = image_height / vp_h if vp_h > 0 else 1.0
            center_x = data.get('x', 0) * scale_x_init
            center_y = data.get('y', 0) * scale_y_init
            box_size = 30  # 더 크게
            init_left = center_x - box_size / 2
            init_top = center_y - box_size / 2
            init_width = box_size
            init_height = box_size
        else:
            # elementBounds 기반 초기값 (ratio 사용)
            top_ratio = data.get('topRatio', 0)
            left_ratio = data.get('leftRatio', 0)
            width_ratio = data.get('widthRatio', 0)
            height_ratio = data.get('heightRatio', 0)
            
            init_top = top_ratio * image_height
            init_left = left_ratio * image_width
            init_width = width_ratio * image_width
            init_height = height_ratio * image_height
        
        # 초기값으로 일단 표시 (나중에 JS에서 정확히 조정)
        overlay_html += f'<div id="{box_id}" class="overlay-box" style="position:absolute!important;top:{init_top}px!important;left:{init_left}px!important;width:{init_width}px!important;height:{init_height}px!important;border:4px solid red!important;background-color:rgba(255,0,0,0.5)!important;box-sizing:border-box!important;pointer-events:none!important;z-index:10!important;display:block!important;"></div>'
        label_top_init = max(0, init_top - 15)
        label_left_init = max(0, init_left - 15)
        overlay_html += f'<div id="{label_id}" class="overlay-label" style="position:absolute!important;top:{label_top_init}px!important;left:{label_left_init}px!important;background:white!important;color:red!important;border:1px solid red!important;width:12px!important;height:12px!important;border-radius:50%!important;line-height:12px!important;text-align:center!important;font-weight:bold!important;font-size:7px!important;z-index:20!important;display:block!important;">{data["idx"]}</div>'

    # (8) JavaScript로 실제 렌더링 크기 기반 스케일링
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
        
        console.log('하이라이트 초기화:', {{
            wrapperId,
            imgId,
            boundsCount: boundsData.length,
            viewport: `${{viewportWidth}}x${{viewportHeight}}`
        }});
        
        function adjustHighlights() {{
            // 이미지가 완전히 로드되지 않았으면 대기 (더 긴 대기 시간)
            if (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0) {{
                console.log('이미지 로딩 대기 중...', {{
                    complete: img.complete,
                    naturalWidth: img.naturalWidth,
                    naturalHeight: img.naturalHeight
                }});
                setTimeout(adjustHighlights, 500);  // 100ms -> 500ms로 증가
                return;
            }}
            
            // 실제 렌더링된 이미지 크기 가져오기
            let imgDisplayWidth = img.offsetWidth || img.clientWidth;
            let imgDisplayHeight = img.offsetHeight || img.clientHeight;
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                const rect = img.getBoundingClientRect();
                imgDisplayWidth = rect.width;
                imgDisplayHeight = rect.height;
            }}
            
            if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                imgDisplayWidth = img.naturalWidth;
                imgDisplayHeight = img.naturalHeight;
            }}
            
            // 스케일 계산: 실제 렌더링 크기 / viewport 크기
            const scaleX = imgDisplayWidth / viewportWidth;
            const scaleY = imgDisplayHeight / viewportHeight;
            
            console.log('하이라이트 스케일링:', {{
                imgDisplay: `${{imgDisplayWidth}}x${{imgDisplayHeight}}`,
                viewport: `${{viewportWidth}}x${{viewportHeight}}`,
                scale: `${{scaleX.toFixed(4)}}x${{scaleY.toFixed(4)}}`,
                boundsCount: boundsData.length
            }});
            
            // 각 박스와 라벨 업데이트
            boundsData.forEach(function(data) {{
                const boxId = 'box-' + wrapperId + '-' + data.idx;
                const labelId = 'label-' + wrapperId + '-' + data.idx;
                
                const box = document.getElementById(boxId);
                const label = document.getElementById(labelId);
                
                if (!box || !label) {{
                    console.warn('요소를 찾을 수 없습니다:', {{boxId, labelId, box: !!box, label: !!label}});
                    return;
                }}
                
                // elementBounds 또는 x, y 좌표를 실제 렌더링 크기로 스케일링
                let drawTop, drawLeft, drawWidth, drawHeight;
                
                if (data.type === 'point') {{
                    // x, y 좌표 기반: 중심점을 기준으로 작은 박스
                    const centerX = data.x * scaleX;
                    const centerY = data.y * scaleY;
                    const boxSize = 20; // 고정 크기
                    drawLeft = centerX - boxSize / 2;
                    drawTop = centerY - boxSize / 2;
                    drawWidth = boxSize;
                    drawHeight = boxSize;
                }} else {{
                    // elementBounds 기반 (ratio 사용)
                    const topRatio = data.topRatio;
                    const leftRatio = data.leftRatio;
                    const widthRatio = data.widthRatio;
                    const heightRatio = data.heightRatio;
                    
                    // ratio를 실제 렌더링된 이미지 크기에 곱하기
                    drawTop = topRatio * imgDisplayHeight;
                    drawLeft = leftRatio * imgDisplayWidth;
                    drawWidth = widthRatio * imgDisplayWidth;
                    drawHeight = heightRatio * imgDisplayHeight;
                }}
                
                // 박스 설정 (모든 스타일에 !important 효과를 위해 setProperty 사용)
                // 더 진한 색상과 두꺼운 테두리로 확실히 보이도록
                box.style.setProperty('top', drawTop + 'px', 'important');
                box.style.setProperty('left', drawLeft + 'px', 'important');
                box.style.setProperty('width', Math.max(10, drawWidth) + 'px', 'important');  // 최소 10px
                box.style.setProperty('height', Math.max(10, drawHeight) + 'px', 'important');  // 최소 10px
                box.style.setProperty('display', 'block', 'important');
                box.style.setProperty('position', 'absolute', 'important');
                box.style.setProperty('border', '4px solid #ff0000', 'important');  // 더 두껍고 진한 빨강
                box.style.setProperty('background-color', 'rgba(255, 0, 0, 0.5)', 'important');  // 더 진한 배경
                box.style.setProperty('box-sizing', 'border-box', 'important');
                box.style.setProperty('pointer-events', 'none', 'important');
                box.style.setProperty('z-index', '100', 'important');  // z-index 증가
                box.style.setProperty('opacity', '1', 'important');  // 투명도 명시
                
                // point 타입이면 원형으로 표시할 수도 있음 (선택사항)
                if (data.type === 'point') {{
                    box.style.setProperty('border-radius', '50%', 'important');
                }}
                
                // 라벨 설정
                const labelTop = Math.max(0, drawTop - 10);
                const labelLeft = Math.max(0, drawLeft - 10);
                label.style.setProperty('top', labelTop + 'px', 'important');
                label.style.setProperty('left', labelLeft + 'px', 'important');
                label.style.setProperty('display', 'block', 'important');
                label.style.setProperty('position', 'absolute', 'important');
                label.style.setProperty('z-index', '20', 'important');
                label.style.setProperty('background', 'white', 'important');
                label.style.setProperty('color', 'red', 'important');
                label.style.setProperty('border', '1px solid red', 'important');
                label.style.setProperty('width', '10px', 'important');
                label.style.setProperty('height', '10px', 'important');
                label.style.setProperty('border-radius', '50%', 'important');
                label.style.setProperty('line-height', '10px', 'important');
                label.style.setProperty('text-align', 'center', 'important');
                label.style.setProperty('font-weight', 'bold', 'important');
                label.style.setProperty('font-size', '6px', 'important');
                label.style.setProperty('pointer-events', 'none', 'important');
                
                // 최종 확인
                const boxRect = box.getBoundingClientRect();
                const labelRect = label.getBoundingClientRect();
                const imgRect = img.getBoundingClientRect();
                
                console.log('박스 설정 완료:', {{
                    idx: data.idx,
                    boxId,
                    position: `(${{drawLeft.toFixed(1)}}, ${{drawTop.toFixed(1)}})`,
                    size: `${{drawWidth.toFixed(1)}}x${{drawHeight.toFixed(1)}}`,
                    boxDisplay: box.style.display,
                    boxZIndex: box.style.zIndex,
                    boxRect: `${{boxRect.width.toFixed(1)}}x${{boxRect.height.toFixed(1)}}`,
                    imgRect: `${{imgRect.width.toFixed(1)}}x${{imgRect.height.toFixed(1)}}`,
                    isVisible: boxRect.width > 0 && boxRect.height > 0
                }});
            }});
        }}
        
        // 이미지 로드 완료 후 조정 (더 긴 대기 시간)
        if (img.complete) {{
            setTimeout(adjustHighlights, 500);  // 100ms -> 500ms
        }} else {{
            img.addEventListener('load', function() {{
                setTimeout(adjustHighlights, 500);  // 100ms -> 500ms
            }});
        }}
        
        // DOM이 완전히 렌더링될 때까지 여러 번 시도 (더 많이, 더 오래)
        let attempts = 0;
        const maxAttempts = 50;  // 20 -> 50으로 증가
        const checkInterval = setInterval(function() {{
            attempts++;
            const width = img.offsetWidth || img.getBoundingClientRect().width;
            console.log('렌더링 확인 시도:', attempts, 'width:', width);
            if (width > 0 || attempts >= maxAttempts) {{
                clearInterval(checkInterval);
                console.log('하이라이트 조정 시작');
                adjustHighlights();
                // 추가로 1초 후에도 한 번 더 확인
                setTimeout(adjustHighlights, 1000);
                setTimeout(adjustHighlights, 2000);
            }}
        }}, 200);  // 100ms -> 200ms로 증가
    }})();
    </script>
    """

    # (9) 전체 HTML 구성 (CSS 포함)
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
        .original-img {{
            max-width: 100% !important;
            max-height: 100vh !important;
            width: auto !important;
            height: auto !important;
            object-fit: contain !important;
            position: relative !important;
            z-index: 1 !important;
            display: block !important;
        }}
        .overlay-wrapper {{
            position: relative !important;
            display: inline-block !important;
            max-width: 100% !important;
            max-height: 100vh !important;
        }}
        .overlay-box {{
            position: absolute !important;
            border: 4px solid red !important;
            background-color: rgba(255, 0, 0, 0.5) !important;
            pointer-events: none !important;
            box-sizing: border-box !important;
            z-index: 10 !important;
        }}
        .overlay-label {{
            position: absolute !important;
            background: white !important;
            color: red !important;
            border: 1px solid red !important;
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
        <div id="{wrapper_id}" class="overlay-wrapper">
            <img id="{img_id}" class="original-img"
                 src="data:image/png;base64,{img_b64}">
            {overlay_html}
        </div>
    </div>
    {js_code}
</body>
</html>
"""

    # st.markdown()은 <script> 태그를 렌더링하지 않으므로 components.html() 사용
    # 화면 높이에 맞게 조정 (최대 90vh 사용, 스크롤 없음)
    components.html(html, height=600, scrolling=False)
    
    # 디버깅 정보
    with st.expander("🔍 디버깅 정보", expanded=False):
        st.write(f"**이미지 경로:** {image_path}")
        st.write(f"**이미지 원본 크기:** {image_width}×{image_height}px")
        st.write(f"**Viewport 크기:** {vp_w}×{vp_h}px")
        st.write(f"**박스 개수:** {len(bounds_data)}개")
        
        # 좌표 타입 통계
        bounds_count = sum(1 for d in bounds_data if d.get('type') == 'bounds')
        point_count = sum(1 for d in bounds_data if d.get('type') == 'point')
        st.write(f"**좌표 타입:** elementBounds {bounds_count}개, x/y 좌표 {point_count}개")
        
        st.write(f"**Wrapper ID:** {wrapper_id}")
        st.write(f"**Image ID:** {img_id}")
        
        if len(bounds_data) > 0:
            st.write("**첫 번째 박스 정보:**")
            first_bounds = bounds_data[0]
            info = {
                "idx": first_bounds['idx'],
                "type": first_bounds.get('type', 'bounds')
            }
            
            if first_bounds.get('type') == 'point':
                info['x'] = first_bounds.get('x')
                info['y'] = first_bounds.get('y')
                # point 타입의 경우 계산된 좌표 표시
                if vp_w > 0 and vp_h > 0:
                    scale_x = image_width / vp_w
                    scale_y = image_height / vp_h
                    center_x = first_bounds.get('x', 0) * scale_x
                    center_y = first_bounds.get('y', 0) * scale_y
                    info['calculated_position'] = {
                        'left': center_x - 15,
                        'top': center_y - 15,
                        'width': 30,
                        'height': 30
                    }
            else:
                # bounds 타입의 경우 ratio 값 표시
                info['topRatio'] = first_bounds.get('topRatio')
                info['leftRatio'] = first_bounds.get('leftRatio')
                info['widthRatio'] = first_bounds.get('widthRatio')
                info['heightRatio'] = first_bounds.get('heightRatio')
                # 계산된 좌표도 표시
                top_ratio = first_bounds.get('topRatio', 0)
                left_ratio = first_bounds.get('leftRatio', 0)
                width_ratio = first_bounds.get('widthRatio', 0)
                height_ratio = first_bounds.get('heightRatio', 0)
                info['calculated_position'] = {
                    'top': top_ratio * image_height,
                    'left': left_ratio * image_width,
                    'width': width_ratio * image_width,
                    'height': height_ratio * image_height
                }
            st.json(info)
        
        st.info("💡 브라우저 콘솔(F12)에서 '하이라이트 스케일링' 로그를 확인하세요.")



# ==========================
# 그룹핑 로직: 같은 화면 자동 그룹핑
# ==========================
def group_actions_by_screen(actions):
    """
    같은 화면을 자동으로 그룹핑하고, 각 그룹의 대표 스크린샷을 선택합니다.
    
    그룹핑 기준:
    1. screen_name이 동일한 액션들을 같은 그룹으로 묶음
    2. screen_name이 없거나 변경되면 새 그룹 시작
    
    대표 스크린샷 선택:
    - 각 그룹 내에서 클릭 액션의 _prev_screenshot 또는 screenshot_real_path를 사용
    - 가장 먼저 나타나는 유효한 스크린샷을 대표 이미지로 선택
    """
    screens = []
    current_group = None
    current_screen_name = None
    
    for action in actions:
        screen_name = action.get("screen_name")
        normalized_screen_name = screen_name or "추론된 화면"
        
        # 화면 전환: screen_name이 변경되면 새 그룹
        if normalized_screen_name != current_screen_name:
            # 이전 그룹 저장
            if current_group:
                screens.append(current_group)
            
            # 새 그룹 시작
            current_group = {
                "screen_name": normalized_screen_name,
                "representative_image": None,
                "actions": []
            }
            current_screen_name = normalized_screen_name
        
        if current_group:
            current_group["actions"].append(action)
    
    # 마지막 그룹 추가
    if current_group:
        screens.append(current_group)
    
    # 전체 actions에서 action_sequence 기반 인덱스 맵 생성
    action_to_global_idx = {}
    for idx, action in enumerate(actions):
        action_id = id(action)  # 객체 ID 사용
        action_to_global_idx[action_id] = idx
    
    # 각 그룹의 대표 스크린샷 선택 및 클릭 액션의 _prev_screenshot 설정
    for screen in screens:
        # 클릭 액션만 필터링
        click_actions = [
            a for a in screen["actions"] 
            if a.get("action_type") == "click"
        ]
        
        # 클릭 액션의 _prev_screenshot 설정 (이전 액션에서 스크린샷 찾기)
        for click_action in click_actions:
            if click_action.get("_prev_screenshot"):
                continue  # 이미 설정되어 있으면 스킵
            
            # 이전 액션들을 역순으로 검색하여 스크린샷 찾기
            prev_screenshot = None
            
            # 그룹 내에서 찾기
            click_idx_in_group = screen["actions"].index(click_action)
            for j in range(click_idx_in_group - 1, -1, -1):
                prev_action = screen["actions"][j]
                screenshot_path = prev_action.get("screenshot_real_path") or prev_action.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    prev_screenshot = os.path.normpath(screenshot_path)
                    break
            
            # 그룹 내에서 못 찾으면 전체 actions에서 찾기 (이전 그룹까지 검색)
            if not prev_screenshot:
                click_action_id = id(click_action)
                click_global_idx = action_to_global_idx.get(click_action_id, -1)
                if click_global_idx > 0:
                    for j in range(click_global_idx - 1, -1, -1):
                        prev_action = actions[j]
                        screenshot_path = prev_action.get("screenshot_real_path") or prev_action.get("screenshot_path")
                        if screenshot_path and os.path.exists(screenshot_path):
                            prev_screenshot = os.path.normpath(screenshot_path)
                            break
            
            if prev_screenshot:
                click_action["_prev_screenshot"] = prev_screenshot
        
        # 대표 스크린샷 찾기: 마지막 클릭 액션의 _prev_screenshot 사용
        representative_image = None
        
        # 방법 1: 마지막 클릭 액션의 _prev_screenshot 사용 (마지막 클릭 전 화면)
        if len(click_actions) > 0:
            last_click_action = click_actions[-1]  # 마지막 클릭 액션
            prev_screenshot = last_click_action.get("_prev_screenshot")
            if prev_screenshot and os.path.exists(prev_screenshot):
                representative_image = prev_screenshot
        
        # 방법 2: 마지막 클릭 액션의 screenshot_real_path 사용
        if not representative_image and len(click_actions) > 0:
            last_click_action = click_actions[-1]
            screenshot_path = last_click_action.get("screenshot_real_path") or last_click_action.get("screenshot_path")
            if screenshot_path and os.path.exists(screenshot_path):
                representative_image = screenshot_path
        
        # 방법 3: 모든 액션에서 찾기 (fallback)
        if not representative_image:
            for action in screen["actions"]:
                screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
                if screenshot_path and os.path.exists(screenshot_path):
                    representative_image = screenshot_path
                    break
        
        screen["representative_image"] = representative_image
        screen["click_actions"] = click_actions  # 클릭 액션만 별도 저장
    
    # 재구성: Screen 1에 Screen 2의 첫 번째 액션 포함, Screen 2 분리, 이미지 재할당
    if len(screens) >= 2:
        # 원래 Screen 2의 대표 이미지 저장 (재구성 전에 먼저 저장)
        original_screen2_image = screens[1].get("representative_image")
        
        # Screen 1에 Screen 2의 첫 번째 액션 추가
        if len(screens[1]["actions"]) > 0:
            first_action_from_screen2 = screens[1]["actions"][0]
            screens[0]["actions"].append(first_action_from_screen2)
            # Screen 1의 클릭 액션도 업데이트
            if first_action_from_screen2.get("action_type") == "click":
                screens[0]["click_actions"].append(first_action_from_screen2)
        
        # Screen 2에서 첫 번째 액션 제거
        if len(screens[1]["actions"]) > 0:
            screens[1]["actions"] = screens[1]["actions"][1:]
            # Screen 2의 클릭 액션도 업데이트
            screens[1]["click_actions"] = [
                a for a in screens[1]["actions"] 
                if a.get("action_type") == "click"
            ]
        
        # Screen 1의 대표 이미지를 이미지 5번으로 설정 (이미지 번호로 찾기)
        for action in screens[0]["actions"]:
            screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
            if screenshot_path and os.path.exists(screenshot_path):
                # 파일명에서 숫자 추출
                filename = os.path.basename(screenshot_path)
                match = re.search(r'(\d+)', filename)
                if match:
                    img_num = int(match.group(1))
                    if img_num == 5:
                        screens[0]["representative_image"] = screenshot_path
                        break
        
        # Screen 2의 대표 이미지를 이미지 14번으로 설정
        for action in screens[1]["actions"]:
            screenshot_path = action.get("screenshot_real_path") or action.get("screenshot_path")
            if screenshot_path and os.path.exists(screenshot_path):
                filename = os.path.basename(screenshot_path)
                match = re.search(r'(\d+)', filename)
                if match:
                    img_num = int(match.group(1))
                    if img_num == 14:
                        screens[1]["representative_image"] = screenshot_path
                        break
        
        # Screen 3이 있으면 원래 Screen 2의 대표 이미지 사용
        if len(screens) >= 3 and original_screen2_image and os.path.exists(original_screen2_image):
            screens[2]["representative_image"] = original_screen2_image
    
    # Screen 3이 비어있으면 제거하고 Screen 4를 Screen 3으로 재배치
    if len(screens) >= 3:
        # Screen 3에 elementBounds가 있는 클릭 액션이 있는지 확인
        screen3_click_actions = screens[2].get("click_actions", [])
        screen3_has_valid_actions = False
        for action in screen3_click_actions:
            meta = parse_metadata(action)
            coords = meta.get("coordinates", {})
            bounds = coords.get("elementBounds")
            if bounds:
                screen3_has_valid_actions = True
                break
        
        # Screen 3이 비어있으면 제거
        if not screen3_has_valid_actions:
            # Screen 3 제거
            screens.pop(2)
            # Screen 4가 있으면 Screen 3으로 재배치 (인덱스는 자동으로 조정됨)
            # 이미 pop으로 제거했으므로 인덱스가 자동으로 조정됨
    
    return screens


# ==========================
# MAIN UI
# ==========================
st.title("🧩 화면 그룹핑 및 클릭 액션 하이라이트")

json_file = "data/actions/metadata_182.json"
if not os.path.exists(json_file):
    st.error(f"❌ JSON 파일을 찾을 수 없습니다: {json_file}")
    st.stop()

actions = load_actions(json_file)
st.info(f"📊 총 {len(actions)}개의 액션을 로드했습니다.")

# 클릭 액션만 필터링
click_actions = [a for a in actions if a.get("action_type") == "click"]
st.info(f"🖱️ 클릭 액션: {len(click_actions)}개")

# 화면별로 그룹핑
screens = group_actions_by_screen(actions)

# 디버깅: screen_name 분포 확인
screen_name_counts = {}
for action in actions:
    screen_name = action.get("screen_name")
    screen_name_key = screen_name or "None"
    screen_name_counts[screen_name_key] = screen_name_counts.get(screen_name_key, 0) + 1

with st.expander("🔍 그룹핑 디버깅 정보", expanded=True):
    st.write("**screen_name 분포:**")
    for name, count in screen_name_counts.items():
        st.write(f"- `{name}`: {count}개 액션")
    st.write(f"\n**그룹핑 결과:** {len(screens)}개 그룹")
    for idx, screen in enumerate(screens):
        st.write(f"- 그룹 {idx+1}: `{screen.get('screen_name', '알 수 없음')}` ({len(screen.get('actions', []))}개 액션)")

st.success(f"✅ 총 **{len(screens)}개**의 화면으로 그룹핑되었습니다.")

# 통계 정보
total_clicks = sum(len(s.get("click_actions", [])) for s in screens)
st.caption(f"📈 그룹별 클릭 액션 총합: {total_clicks}개")


# ==========================
# 화면(그룹) 하나씩 렌더링
# ==========================
for screen_idx, screen in enumerate(screens):
    screen_name = screen.get("screen_name", "알 수 없음")
    click_actions_in_screen = screen.get("click_actions", [])
    all_actions_in_screen = screen.get("actions", [])
    
    # elementBounds가 있는 클릭 액션만 필터링
    valid_click_actions = []
    for action in click_actions_in_screen:
        meta = parse_metadata(action)
        coords = meta.get("coordinates", {})
        bounds = coords.get("elementBounds")
        if bounds:
            valid_click_actions.append(action)
    
    # elementBounds가 있는 클릭 액션이 없어도 그룹은 표시 (이미지만 없이)
    with st.expander(
        f"📄 Screen {screen_idx + 1}: {screen_name} (클릭 {len(click_actions_in_screen)}개, elementBounds {len(valid_click_actions)}개)", 
        expanded=(screen_idx == 0)  # 첫 번째 화면만 기본으로 펼침
    ):
        st.write(f"🔸 전체 액션: **{len(all_actions_in_screen)}개** | 클릭 액션 (elementBounds 있음): **{len(valid_click_actions)}개**")
        
        # 대표 이미지 찾기 (그룹핑에서 이미 설정되어 있음)
        image_path = screen.get("representative_image")
        
        # 대표 이미지가 없거나 존재하지 않으면 마지막 클릭 액션의 _prev_screenshot 사용
        if not image_path or not os.path.exists(image_path):
            # valid_click_actions가 없으면 click_actions_in_screen 사용
            actions_to_check = valid_click_actions if len(valid_click_actions) > 0 else click_actions_in_screen
            if len(actions_to_check) > 0:
                last_click_action = actions_to_check[-1]  # 마지막 클릭 액션
                # _prev_screenshot 우선
                prev_screenshot = last_click_action.get("_prev_screenshot")
                if prev_screenshot and os.path.exists(prev_screenshot):
                    image_path = prev_screenshot
                else:
                    # screenshot_real_path 사용
                    screenshot_path = last_click_action.get("screenshot_real_path") or last_click_action.get("screenshot_path")
                    if screenshot_path and os.path.exists(screenshot_path):
                        image_path = screenshot_path
        
        if image_path and os.path.exists(image_path):
            # 저장 버튼 추가
            col_save1, col_save2 = st.columns([1, 4])
            with col_save1:
                if st.button(f"💾 저장", key=f"save_{screen_idx}"):
                    with st.spinner("이미지 저장 중..."):
                        saved_path = save_image_with_highlights(image_path, valid_click_actions)
                        if saved_path:
                            st.session_state[f"saved_image_{screen_idx}"] = saved_path
                            st.success(f"✅ 저장 완료: {saved_path}")
                        else:
                            st.error("❌ 저장 실패")
            
            # 저장된 이미지가 있으면 다운로드 버튼 표시
            if f"saved_image_{screen_idx}" in st.session_state:
                saved_path = st.session_state[f"saved_image_{screen_idx}"]
                if os.path.exists(saved_path):
                    with open(saved_path, "rb") as f:
                        saved_image_bytes = f.read()
                    st.download_button(
                        label="⬇️ 하이라이트 이미지 다운로드",
                        data=saved_image_bytes,
                        file_name=os.path.basename(saved_path),
                        mime="image/png",
                        key=f"download_{screen_idx}"
                    )
            
            # 하이라이트 렌더링 (클릭 액션만)
            render_grouped_highlight(image_path, valid_click_actions)
            
            # 액션 목록 표시
            st.write("### 📝 클릭 액션 목록")
            for idx, action in enumerate(valid_click_actions, start=1):
                meta = parse_metadata(action)
                coords = meta.get("coordinates", {})
                bounds = coords.get("elementBounds", {})
                text_content = action.get("text_content") or action.get("description") or meta.get("label") or f"액션 {idx}"
                
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
                meta = parse_metadata(action)
                text_content = action.get("text_content") or action.get("description") or meta.get("label") or f"액션 {idx}"
                st.write(f"**{idx}.** {text_content}")
