from app.drawing_ai import validate_analysis
from app.cad_engine import CadState, build_model

def test_safe_reject_missing_dimension():
    r=validate_analysis({'can_build':True,'confidence':.95,'state':{'part_name':'x','base':{'type':'cylinder','diameter':50},'features':[]}})
    assert not r['can_build']
    assert r['blocking_ambiguities']

def test_revolved_profile_builds():
    s=CadState(part_name='shaft',base={'type':'revolved_profile','stations':[{'z':0,'diameter':50},{'z':40,'diameter':50},{'z':40,'diameter':30},{'z':70,'diameter':30}]},features=[])
    assert build_model(s).val().Volume()>0

def test_low_confidence_locks_step():
    r=validate_analysis({'can_build':True,'confidence':.60,'state':{'part_name':'x','base':{'type':'block','x':20,'y':20,'z':5},'features':[]}})
    assert not r['can_build']
