def group_screens(actions):
    """Group actions into screens based on screen_name. Only use representative screenshots."""
    screens = []
    current = None
    current_screen_name = None
    
    # 대표 이미지로 사용할 스크린샷 번호 (0-based index)
    representative_screenshot_indices = {2, 8, 10, 14, 17, 23}  # 3, 9, 11, 15, 18, 24

    for idx, action in enumerate(actions):
        screen_name = action.get("screen_name", None)
        normalized_screen_name = screen_name or "추론된 화면"

        # 화면 전환 조건: screen_name이 변경되거나, 지정된 대표 스크린샷이면 새 화면
        screen_changed = False
        
        if idx == 0:
            # 첫 번째 액션은 항상 새 화면 시작
            screen_changed = True
        elif idx in representative_screenshot_indices:
            # 지정된 대표 스크린샷이면 새 화면 시작 (같은 screen_name이어도 분리)
            screen_changed = True
        elif normalized_screen_name != current_screen_name:
            # screen_name이 변경되면 새 화면
            screen_changed = True

        if screen_changed:
            # 새 화면 시작 (대표 이미지는 나중에 설정)
            current = {
                "screen_name": normalized_screen_name,
                "representative_image": None,  # 나중에 대표 스크린샷으로 설정
                "actions": []
            }
            screens.append(current)
            current_screen_name = normalized_screen_name

        if current:
            current["actions"].append(action)
    
    # 각 screen의 actions에서 대표 이미지 설정 (지정된 대표 스크린샷만 사용)
    import os
    representative_screenshot_indices = {2, 8, 10, 14, 17, 23}  # 3, 9, 11, 15, 18, 24
    
    # actions 리스트에서 인덱스 매핑 생성
    action_to_index = {id(a): i for i, a in enumerate(actions)}
    
    for idx, screen in enumerate(screens):
        # 지정된 대표 스크린샷 번호의 액션만 찾기
        representative_action = None
        
        # screen의 actions에서 대표 스크린샷 찾기
        for action in screen["actions"]:
            global_idx = action_to_index.get(id(action))
            if global_idx is not None and global_idx in representative_screenshot_indices:
                representative_action = action
                break
        
        # 대표 스크린샷이 있으면 그것만 사용 (대표 스크린샷이 아니면 사용하지 않음)
        if representative_action and representative_action.get("screenshot_real_path"):
            screen["representative_image"] = representative_action["screenshot_real_path"]
        else:
            # 대표 스크린샷이 없으면 None (대표 스크린샷이 아닌 것은 사용하지 않음)
            screen["representative_image"] = None

    return screens
