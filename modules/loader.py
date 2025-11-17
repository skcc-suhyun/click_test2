import json


def load_actions(json_path: str):
    """Load actions from a JSON file."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    key = list(data.keys())[0]
    return data[key]
