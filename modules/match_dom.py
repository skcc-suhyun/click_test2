def match_clicked_dom(action, dom_snapshot):
    """Match clicked coordinates to DOM nodes in the snapshot.
    
    좌표 우선순위: pageX/pageY > clientX/clientY > x/y
    - pageX/pageY: 전체 페이지 기준 좌표
    - clientX/clientY: 브라우저 viewport 기준 좌표
    """
    coords = action["metadata"]["coordinates"]
    
    # 좌표 추출 (우선순위: pageX/pageY > clientX/clientY > x/y)
    cx = coords.get("pageX") or coords.get("clientX") or coords.get("x")
    cy = coords.get("pageY") or coords.get("clientY") or coords.get("y")
    
    if cx is None or cy is None:
        return None

    nodes = dom_snapshot.get("nodes", [])
    candidates = []

    def contains_point(b, x, y):
        """Check if a point is within bounds."""
        return (
            b["top"] <= y <= b["top"] + b["height"] and
            b["left"] <= x <= b["left"] + b["width"]
        )

    # 후보 찾기
    for node in nodes:
        bounds = node.get("bounds")
        if not bounds:
            continue

        if contains_point(bounds, cx, cy):
            candidates.append(node)

    if not candidates:
        return None

    # 가장 작은 노드 선택
    def area(b):
        """Calculate area of bounds."""
        return b["width"] * b["height"]

    best = min(candidates, key=lambda n: area(n["bounds"]))

    return {
        "nodeId": best.get("nodeId"),
        "tag": best.get("tagName"),
        "text": best.get("text"),
        "attributes": best.get("attributes"),
        "bounds": best.get("bounds"),
    }
