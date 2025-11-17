import streamlit as st
import base64
import os
import json

# Version: 2.0.0 - Updated to use action metadata with scale calculation

def render_highlight(action):
    """
    Render an image with a highlighted bounding box based on action metadata.
    
    Args:
        action: dict containing 'screenshot_real_path' and 'metadata' (JSON string)
    """
    image_path = action.get("screenshot_real_path")
    raw_metadata = action.get("metadata")
    
    if image_path is None or not os.path.exists(image_path):
        st.error("❌ 스크린샷 파일이 존재하지 않습니다.")
        return
    
    if not raw_metadata:
        st.warning("⚠️ metadata가 없습니다.")
        return
    
    # metadata 파싱
    try:
        if isinstance(raw_metadata, str):
            metadata = json.loads(raw_metadata)
        else:
            metadata = raw_metadata
    except json.JSONDecodeError as e:
        st.error(f"❌ metadata 파싱 오류: {e}")
        return
    
    # elementBounds 추출
    coordinates = metadata.get("coordinates", {})
    element_bounds = coordinates.get("elementBounds")
    
    if not element_bounds:
        st.warning("⚠️ elementBounds가 없습니다.")
        return
    
    # viewport 크기 추출
    viewport_width = coordinates.get("viewportWidth")
    viewport_height = coordinates.get("viewportHeight")
    
    # 이미지를 base64로 인코딩
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode()
    
    # elementBounds에서 좌표 추출
    bounds_top = element_bounds.get("top", 0)
    bounds_left = element_bounds.get("left", 0)
    bounds_width = element_bounds.get("width", 0)
    bounds_height = element_bounds.get("height", 0)
    
    # scale 계산은 JavaScript에서 실제 렌더링된 이미지 크기를 기준으로 수행
    
    # HTML로 이미지와 하이라이트 렌더링
    # use_column_width 같은 옵션을 사용하지 않고 직접 HTML로 렌더링하여 크기 조정 방지
    
    # 이미지 크기 가져오기 (PIL 사용)
    try:
        from PIL import Image
        with Image.open(image_path) as pil_img:
            img_natural_width = pil_img.width
            img_natural_height = pil_img.height
    except:
        # PIL이 없으면 기본값 사용
        img_natural_width = None
        img_natural_height = None
    
    # 이미지 크기를 1859×910px로 고정 (원본 크기 사용)
    fixed_img_width = img_natural_width if img_natural_width else 1859
    fixed_img_height = img_natural_height if img_natural_height else 910
    
    # scale 계산 (viewport 정보가 있으면 사용)
    if viewport_width and viewport_height:
        # 고정된 이미지 크기와 viewport 크기 비교하여 scale 계산
        scale_x = fixed_img_width / viewport_width
        scale_y = fixed_img_height / viewport_height
    else:
        # viewport 정보가 없으면 scale 1.0 사용
        scale_x = 1.0
        scale_y = 1.0
    
    # elementBounds에 scale 적용
    scaled_top = bounds_top * scale_y
    scaled_left = bounds_left * scale_x
    scaled_width = bounds_width * scale_x
    scaled_height = bounds_height * scale_y
    
    # 좌표 검증 (음수 방지)
    final_top = max(0, scaled_top)
    final_left = max(0, scaled_left)
    final_width = max(1, scaled_width)
    final_height = max(1, scaled_height)
    
    html = f"""
    <div id="wrapper-div-{id(action)}" style="position: relative; display: inline-block; width: {fixed_img_width}px; height: {fixed_img_height}px;">
        <img id="screenshot-img-{id(action)}" 
             src="data:image/png;base64,{img_base64}" 
             style="width: {fixed_img_width}px; height: {fixed_img_height}px; display: block;">
        <div id="highlight-box-{id(action)}" style="
            position: absolute;
            top: {final_top}px;
            left: {final_left}px;
            width: {final_width}px;
            height: {final_height}px;
            border: 3px solid red;
            background-color: rgba(255, 0, 0, 0.2);
            box-sizing: border-box;
            pointer-events: none;
            z-index: 10;">
        </div>
    </div>
    <script>
        // 이미지가 로드된 후 실제 렌더링 크기 확인 및 하이라이트 조정
        (function() {{
            const wrapper = document.getElementById('wrapper-div-{id(action)}');
            const img = document.getElementById('screenshot-img-{id(action)}');
            const highlight = document.getElementById('highlight-box-{id(action)}');
            
            if (!wrapper || !img || !highlight) {{
                console.error('요소를 찾을 수 없습니다:', {{
                    wrapper: !!wrapper,
                    img: !!img,
                    highlight: !!highlight
                }});
                return;
            }}
            
            // 고정된 크기 값
            const FIXED_WIDTH = {fixed_img_width};
            const FIXED_HEIGHT = {fixed_img_height};
            
            function checkAndLogSizes() {{
                // wrapper 크기 확인
                const wrapperWidth = wrapper.offsetWidth || wrapper.clientWidth;
                const wrapperHeight = wrapper.offsetHeight || wrapper.clientHeight;
                const wrapperRect = wrapper.getBoundingClientRect();
                
                // img 크기 확인
                const imgWidth = img.offsetWidth || img.clientWidth;
                const imgHeight = img.offsetHeight || img.clientHeight;
                const imgRect = img.getBoundingClientRect();
                const imgNaturalWidth = img.naturalWidth;
                const imgNaturalHeight = img.naturalHeight;
                
                // highlight 크기 확인
                const highlightRect = highlight.getBoundingClientRect();
                
                console.log('========== 크기 확인 ==========');
                console.log('고정 크기 (목표):', `${{FIXED_WIDTH}}x${{FIXED_HEIGHT}}`);
                console.log('Wrapper:', {{
                    offsetWidth: wrapperWidth,
                    offsetHeight: wrapperHeight,
                    clientWidth: wrapper.clientWidth,
                    clientHeight: wrapper.clientHeight,
                    getBoundingClientRect: `${{wrapperRect.width.toFixed(2)}}x${{wrapperRect.height.toFixed(2)}}`,
                    style: wrapper.style.width + ' x ' + wrapper.style.height
                }});
                console.log('IMG:', {{
                    offsetWidth: imgWidth,
                    offsetHeight: imgHeight,
                    clientWidth: img.clientWidth,
                    clientHeight: img.clientHeight,
                    naturalWidth: imgNaturalWidth,
                    naturalHeight: imgNaturalHeight,
                    getBoundingClientRect: `${{imgRect.width.toFixed(2)}}x${{imgRect.height.toFixed(2)}}`,
                    style: img.style.width + ' x ' + img.style.height
                }});
                console.log('Highlight:', {{
                    top: highlight.style.top,
                    left: highlight.style.left,
                    width: highlight.style.width,
                    height: highlight.style.height,
                    getBoundingClientRect: `top=${{highlightRect.top.toFixed(2)}}, left=${{highlightRect.left.toFixed(2)}}, width=${{highlightRect.width.toFixed(2)}}, height=${{highlightRect.height.toFixed(2)}}`
                }});
                
                // 크기 검증
                const wrapperCorrect = Math.abs(wrapperWidth - FIXED_WIDTH) < 1 && Math.abs(wrapperHeight - FIXED_HEIGHT) < 1;
                const imgCorrect = Math.abs(imgWidth - FIXED_WIDTH) < 1 && Math.abs(imgHeight - FIXED_HEIGHT) < 1;
                
                console.log('크기 검증:', {{
                    wrapper: wrapperCorrect ? '✅ 정확함' : `❌ 오차: ${{Math.abs(wrapperWidth - FIXED_WIDTH)}}px x ${{Math.abs(wrapperHeight - FIXED_HEIGHT)}}px`,
                    img: imgCorrect ? '✅ 정확함' : `❌ 오차: ${{Math.abs(imgWidth - FIXED_WIDTH)}}px x ${{Math.abs(imgHeight - FIXED_HEIGHT)}}px`
                }});
                console.log('================================');
            }}
            
            function adjustHighlight() {{
                // 이미지가 완전히 로드되지 않았으면 대기
                if (!img.complete || img.naturalWidth === 0 || img.naturalHeight === 0) {{
                    console.log('이미지 로딩 대기 중...');
                    return;
                }}
                
                // 크기 확인 로그
                checkAndLogSizes();
                
                // 실제 렌더링된 이미지 크기 가져오기
                let imgDisplayWidth = img.offsetWidth || img.clientWidth;
                let imgDisplayHeight = img.offsetHeight || img.clientHeight;
                
                // offsetWidth가 0이면 다른 방법 시도
                if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                    const rect = img.getBoundingClientRect();
                    imgDisplayWidth = rect.width;
                    imgDisplayHeight = rect.height;
                }}
                
                // 그래도 0이면 naturalWidth 사용 (원본 크기)
                if (imgDisplayWidth === 0 || imgDisplayHeight === 0) {{
                    imgDisplayWidth = img.naturalWidth;
                    imgDisplayHeight = img.naturalHeight;
                }}
                
                const viewportWidth = {viewport_width if viewport_width else 'null'};
                const viewportHeight = {viewport_height if viewport_height else 'null'};
                
                // elementBounds 값
                const boundsTop = {bounds_top};
                const boundsLeft = {bounds_left};
                const boundsWidth = {bounds_width};
                const boundsHeight = {bounds_height};
                
                console.log('하이라이트 계산:', {{
                    imgDisplay: `${{imgDisplayWidth}}x${{imgDisplayHeight}}`,
                    imgNatural: `${{img.naturalWidth}}x${{img.naturalHeight}}`,
                    viewport: `${{viewportWidth}}x${{viewportHeight}}`,
                    bounds: `top=${{boundsTop}}, left=${{boundsLeft}}, width=${{boundsWidth}}, height=${{boundsHeight}}`
                }});
                
                if (viewportWidth && viewportHeight && imgDisplayWidth > 0 && imgDisplayHeight > 0) {{
                    // 실제 렌더링된 이미지 크기 / viewport 크기로 scale 계산
                    const scaleX = imgDisplayWidth / viewportWidth;
                    const scaleY = imgDisplayHeight / viewportHeight;
                    
                    // elementBounds 값에 scale 적용하여 좌표 재계산
                    const scaledTop = boundsTop * scaleY;
                    const scaledLeft = boundsLeft * scaleX;
                    const scaledWidth = boundsWidth * scaleX;
                    const scaledHeight = boundsHeight * scaleY;
                    
                    console.log('스케일 적용:', {{
                        scale: `${{scaleX.toFixed(4)}}x${{scaleY.toFixed(4)}}`,
                        scaled: `top=${{scaledTop.toFixed(2)}}, left=${{scaledLeft.toFixed(2)}}, width=${{scaledWidth.toFixed(2)}}, height=${{scaledHeight.toFixed(2)}}`
                    }});
                    
                    // 좌표 검증 (음수 방지)
                    const finalTop = Math.max(0, scaledTop);
                    const finalLeft = Math.max(0, scaledLeft);
                    const finalWidth = Math.max(1, scaledWidth);
                    const finalHeight = Math.max(1, scaledHeight);
                    
                    highlight.style.top = finalTop + 'px';
                    highlight.style.left = finalLeft + 'px';
                    highlight.style.width = finalWidth + 'px';
                    highlight.style.height = finalHeight + 'px';
                    highlight.style.display = 'block';
                    
                    console.log('하이라이트 박스 설정 완료:', {{
                        top: finalTop,
                        left: finalLeft,
                        width: finalWidth,
                        height: finalHeight
                    }});
                }} else {{
                    console.log('viewport 정보 없음, 초기값 사용');
                    // viewport 정보가 없으면 초기값 유지 (이미 설정됨)
                    highlight.style.display = 'block';
                }}
                
                // 최종 크기 확인
                setTimeout(checkAndLogSizes, 100);
            }}
            
            // 이미지 로드 완료 후 조정
            function initHighlight() {{
                function tryAdjust() {{
                    if (img.complete && img.naturalWidth > 0 && img.naturalHeight > 0) {{
                        // DOM이 완전히 렌더링될 때까지 여러 번 시도
                        let attempts = 0;
                        const maxAttempts = 20;
                        const checkInterval = setInterval(function() {{
                            attempts++;
                            const width = img.offsetWidth || img.getBoundingClientRect().width;
                            if (width > 0 || attempts >= maxAttempts) {{
                                clearInterval(checkInterval);
                                adjustHighlight();
                            }}
                        }}, 100);
                    }} else {{
                        img.addEventListener('load', function() {{
                            setTimeout(function() {{
                                let attempts = 0;
                                const maxAttempts = 20;
                                const checkInterval = setInterval(function() {{
                                    attempts++;
                                    const width = img.offsetWidth || img.getBoundingClientRect().width;
                                    if (width > 0 || attempts >= maxAttempts) {{
                                        clearInterval(checkInterval);
                                        adjustHighlight();
                                    }}
                                }}, 100);
                            }}, 50);
                        }}, {{ once: true }});
                    }}
                }}
                
                // DOMContentLoaded 또는 즉시 실행
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', tryAdjust);
                }} else {{
                    setTimeout(tryAdjust, 100);
                }}
            }}
            
            // 초기화
            initHighlight();
            
            // 윈도우 리사이즈 시에도 조정 (디바운싱)
            let resizeTimeout;
            window.addEventListener('resize', function() {{
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(function() {{
                    checkAndLogSizes();
                    adjustHighlight();
                }}, 200);
            }});
            
            // MutationObserver로 이미지 크기 변경 감지
            if (window.MutationObserver) {{
                const observer = new MutationObserver(function(mutations) {{
                    setTimeout(function() {{
                        checkAndLogSizes();
                        adjustHighlight();
                    }}, 50);
                }});
                observer.observe(img, {{ 
                    attributes: true, 
                    attributeFilter: ['style', 'width', 'height', 'src'],
                    childList: false,
                    subtree: false
                }});
                observer.observe(wrapper, {{
                    attributes: true,
                    attributeFilter: ['style', 'width', 'height'],
                    childList: false,
                    subtree: false
                }});
            }}
        }})();
    </script>
    """
    
    st.markdown(html, unsafe_allow_html=True)


def render_point_highlight(image_path, x, y, radius=10):
    """Render an image with a highlighted point (circle) at x, y coordinates."""
    if image_path is None or not os.path.exists(image_path):
        st.error("❌ 스크린샷 파일이 존재하지 않습니다.")
        return

    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode()

    html = f"""
    <div style="position: relative; display: inline-block;">
        <img src="data:image/png;base64,{img_base64}" style="max-width: 100%;">
        <div style="
            position: absolute;
            top: {y - radius}px;
            left: {x - radius}px;
            width: {radius * 2}px;
            height: {radius * 2}px;
            border: 3px solid red;
            border-radius: 50%;
            background-color: rgba(255, 0, 0, 0.3);
            pointer-events: none;">
        </div>
    </div>
    """

    st.markdown(html, unsafe_allow_html=True)


def render_screen_with_actions(image_path, actions):
    """
    Render a screen image with multiple highlight boxes and action descriptions.
    
    Args:
        image_path: Path to the screenshot image file
        actions: List of action dicts that belong to the same screen
    """
    if not image_path or not os.path.exists(image_path):
        st.error(f"❌ 스크린샷 파일이 존재하지 않습니다: {image_path}")
        return
    
    if not actions or len(actions) == 0:
        st.warning("⚠️ 액션이 없습니다.")
        return
    
    # CSS 주입: 이미지 자동 리사이즈 방지 및 하이라이트 스타일
    if not hasattr(st.session_state, 'css_injected'):
        st.markdown("""
        <style>
        img {
            max-width: none !important;
            width: auto !important;
            height: auto !important;
        }
        </style>
        """, unsafe_allow_html=True)
        st.session_state.css_injected = True
    
    # 첫 번째 action에서 viewport 크기 가져오기
    first_action = actions[0]
    raw_metadata = first_action.get("metadata")
    
    if not raw_metadata:
        st.warning("⚠️ metadata가 없습니다.")
        return
    
    # metadata 파싱
    try:
        if isinstance(raw_metadata, str):
            metadata = json.loads(raw_metadata)
        else:
            metadata = raw_metadata
    except json.JSONDecodeError as e:
        st.error(f"❌ metadata 파싱 오류: {e}")
        return
    
    # viewport 크기 추출
    coordinates = metadata.get("coordinates", {})
    viewport_width = coordinates.get("viewportWidth")
    viewport_height = coordinates.get("viewportHeight")
    
    if not viewport_width or not viewport_height:
        st.warning("⚠️ viewportWidth/viewportHeight가 없습니다.")
        return
    
    # 이미지를 base64로 인코딩
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode()
    
    # elementBounds가 있는 액션들만 필터링
    valid_actions = []
    for action in actions:
        raw_meta = action.get("metadata")
        if not raw_meta:
            continue
        
        try:
            if isinstance(raw_meta, str):
                action_metadata = json.loads(raw_meta)
            else:
                action_metadata = raw_meta
            
            action_coords = action_metadata.get("coordinates", {})
            element_bounds = action_coords.get("elementBounds")
            
            if element_bounds:
                # 액션 텍스트 추출
                text_content = action.get("text_content") or action.get("description") or action_metadata.get("label") or f"액션 {action.get('action_type', 'unknown')}"
                valid_actions.append({
                    "bounds": element_bounds,
                    "text": text_content
                })
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    
    if len(valid_actions) == 0:
        st.warning("⚠️ elementBounds가 있는 액션이 없습니다.")
        return
    
    # 디버깅 정보
    with st.expander("🔍 렌더링 디버깅 정보", expanded=False):
        st.write(f"**valid_actions 수:** {len(valid_actions)}")
        st.write(f"**viewport 크기:** {viewport_width}x{viewport_height}")
        st.write(f"**이미지 경로:** {image_path}")
        if len(valid_actions) > 0:
            st.write("**첫 번째 액션 bounds:**")
            first_bounds = valid_actions[0]["bounds"]
            st.json({
                "top": first_bounds.get("top"),
                "left": first_bounds.get("left"),
                "width": first_bounds.get("width"),
                "height": first_bounds.get("height")
            })
    
    # HTML 생성: wrapper div
    wrapper_id = f"screen-wrapper-{abs(hash(image_path))}"
    html_parts = [f"""
    <div id="{wrapper_id}" style="position: relative !important; display: inline-block !important; width: {viewport_width}px !important; height: {viewport_height}px !important; margin: 10px 0 !important; border: 2px solid blue !important; background-color: #f5f5f5 !important; overflow: visible !important;">
        <img id="img-{wrapper_id}" src="data:image/png;base64,{img_base64}" 
             style="width: {viewport_width}px !important; height: {viewport_height}px !important; max-width: {viewport_width}px !important; max-height: {viewport_height}px !important; display: block !important; position: relative !important; z-index: 1 !important;">
    """]
    
    # 각 액션에 대해 박스와 번호 라벨 생성
    for idx, action_data in enumerate(valid_actions, start=1):
        bounds = action_data["bounds"]
        top = bounds.get("top", 0)
        left = bounds.get("left", 0)
        width = bounds.get("width", 0)
        height = bounds.get("height", 0)
        
        box_id = f"box-{wrapper_id}-{idx}"
        label_id = f"label-{wrapper_id}-{idx}"
        
        # 하이라이트 박스 (한 줄로 작성하여 공백 문제 방지)
        html_parts.append(f'<div id="{box_id}" style="position:absolute!important;top:{top}px!important;left:{left}px!important;width:{width}px!important;height:{height}px!important;border:3px solid red!important;background-color:rgba(255,0,0,0.3)!important;box-sizing:border-box!important;pointer-events:none!important;z-index:10!important;"></div>')
        
        # 번호 라벨 (박스 왼쪽 위)
        html_parts.append(f"""
        <div id="{label_id}" style="
            position: absolute !important;
            top: {max(0, top - 2)}px !important;
            left: {max(0, left - 2)}px !important;
            background: red !important;
            color: white !important;
            padding: 2px 5px !important;
            border-radius: 4px !important;
            font-size: 12px !important;
            font-weight: bold !important;
            z-index: 20 !important;
            line-height: 1.2 !important;
            min-width: 20px !important;
            text-align: center !important;
            white-space: nowrap !important;">
            {idx}
        </div>
        """)
    
    html_parts.append("</div>")
    
    # HTML 렌더링
    html = "".join(html_parts)
    
    # 디버깅: 생성된 HTML 일부 확인
    with st.expander("🔍 생성된 HTML 확인", expanded=False):
        st.code(html[:500] + "..." if len(html) > 500 else html, language="html")
        st.write(f"**HTML 길이:** {len(html)} bytes")
        st.write(f"**박스 개수:** {len(valid_actions)}")
    
    st.markdown(html, unsafe_allow_html=True)
    
    # 액션 텍스트 리스트 출력
    st.write("**액션 목록:**")
    for idx, action_data in enumerate(valid_actions, start=1):
        st.write(f"{idx}. {action_data['text']}")
