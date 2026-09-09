
from app.drawing_ai import validate_analysis, rescore_analysis

def complete_plate():
    return {
        "confidence": 0.45,  # AI'nin ham/keyfi güveni düşük olsa bile
        "drawing_type":"prismatic",
        "state":{
            "part_name":"plate",
            "base":{"type":"block","x":250,"y":60,"z":30},
            "features":[
                {"type":"through_hole","diameter":10,"face":"top","placement":{"mode":"point","x":-100,"y":0}},
                {"type":"through_hole","diameter":10,"face":"top","placement":{"mode":"point","x":100,"y":0}},
            ],
        },
        "dimensions":[
            {"label":"L","value":250,"confidence":0.99},
            {"label":"W","value":60,"confidence":0.99},
            {"label":"H","value":30,"confidence":0.99},
            {"label":"Delik çapı","value":10,"confidence":0.98},
        ],
        "blocking_ambiguities":[],
        "missing_inputs":[],
        "warnings":[],
        "interpretation":[],
    }

def test_complete_geometry_is_100_percent_complete():
    r=validate_analysis(complete_plate())
    assert r["geometry_completeness"] == 1.0
    assert r["can_build"] is True
    assert r["reading_confidence"] > 0.97

def test_cad_validated_clear_drawing_scores_high():
    r=validate_analysis(complete_plate())
    r=rescore_analysis(r,cad_validated=True,verification_passed=True)
    assert r["geometry_completeness"] == 1.0
    assert r["confidence"] >= 0.98
