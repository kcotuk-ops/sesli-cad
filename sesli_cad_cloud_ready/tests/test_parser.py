from app.parser import parse_turkish_command
from app.cad_engine import CadState, build_model

def f(state, typ):
    return [x for x in state.features if x['type']==typ]

def test_user_voice_phrase_center_hole():
    s=parse_turkish_command('100 milim çapında 20 milim kalınlığında flanş yap ortasına 40mm tam ortasına')
    assert s.base == {'type':'flange','diameter':100.0,'thickness':20.0}
    holes=f(s,'through_hole')
    assert len(holes)==1 and holes[0]['diameter']==40 and holes[0]['x']==0 and holes[0]['y']==0
    build_model(s)

def test_new_part_clears_old_features():
    old=CadState(part_name='eski',base={'type':'flange','diameter':80,'thickness':10},features=[{'id':'feature_001','type':'through_hole','diameter':10,'x':15,'y':0}])
    s=parse_turkish_command('100 çapında 20 kalınlığında flanş yap ortasına 40 delik aç',old)
    holes=f(s,'through_hole')
    assert len(holes)==1 and holes[0]['diameter']==40 and holes[0]['x']==0

def test_edit_center_hole_updates_not_duplicates():
    s=parse_turkish_command('100 çapında 20 kalınlığında flanş yap ortasına 40 delik aç')
    s=parse_turkish_command('merkez deliğini 50 yap',s)
    holes=f(s,'through_hole')
    assert len(holes)==1 and holes[0]['diameter']==50

def test_pattern():
    s=parse_turkish_command('100 çapında 20 kalınlığında flanş yap. 80 PCD üzerinde 6 tane 10 luk delik aç')
    ps=f(s,'circular_hole_pattern')
    assert len(ps)==1 and ps[0]['quantity']==6 and ps[0]['pcd']==80 and ps[0]['hole_diameter']==10
    build_model(s)

def test_chamfer():
    s=parse_turkish_command('100 çapında 20 kalınlığında flanş yap. 2 mm pah ver')
    assert f(s,'chamfer')[0]['distance']==2
