
from app.drawing_ai import validate_analysis

def test_resolved_analysis_becomes_buildable():
    result = {
        "can_build": False,
        "confidence": 0.92,
        "state": {
            "part_name": "plate",
            "base": {"type": "block", "x": 250, "y": 60, "z": 30},
            "features": [
                {"type": "through_hole", "diameter": 10, "face": "top",
                 "placement": {"mode":"point","x":-100,"y":0}},
                {"type": "through_hole", "diameter": 10, "face": "top",
                 "placement": {"mode":"point","x":100,"y":0}},
            ]
        },
        "blocking_ambiguities": [],
        "missing_inputs": [],
        "warnings": [],
        "dimensions": [],
        "interpretation": [],
    }
    out = validate_analysis(result)
    assert out["can_build"] is True
