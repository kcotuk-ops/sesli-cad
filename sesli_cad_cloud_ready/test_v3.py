from app.parser import parse_turkish_command
from app.cad_engine import build_model

def ok(cmd, checks):
    s=parse_turkish_command(cmd)
    for fn in checks: assert fn(s), (cmd,s)
    sh=build_model(s); assert sh.val().Volume()>0
    print('OK',cmd)

ok('blok x 100 y 60 z 20 çiz. üst yüzeyde sağ kenardan 20 mm üst kenardan 10 mm 8 mm delik aç', [lambda s:s.features[0]['x']==30,lambda s:s.features[0]['y']==20])
ok('blok x 100 y 60 z 20 çiz. sağ yüzeyde x 5 y 0 10 mm delik aç',[lambda s:s.features[0]['face']=='right'])
ok('blok x 100 y 60 z 20 çiz. üst yüzeyde merkezden 20 mm sağa 10 mm kör delik aç derinliği 8',[lambda s:s.features[0]['depth']==8])
ok('blok x 100 y 60 z 20 çiz. üst yüzeyde x 10 y -5 30 uzunluğunda 8 genişliğinde 5 derinliğinde slot aç',[lambda s:s.features[0]['x']==10,lambda s:s.features[0]['y']==-5])
ok('blok x 100 y 60 z 20 çiz. üst yüzeyde x=10 y=5 8 mm delik aç 14 mm havşa 90 derece',[lambda s:s.features[0]['countersink_diameter']==14])
ok('blok x 100 y 60 z 20 çiz. üst yüzeyde 4 adet 8 mm delik doğrusal 20 mm aralıklı',[lambda s:s.features[0]['type']=='linear_hole_pattern'])
ok('100 çapında 20 kalınlığında flanş yap. ortasına 40 mm delik aç. 80 pcd üzerinde 6 adet 10 mm delik aç',[lambda s:len(s.features)==2,lambda s:s.features[1]['quantity']==6])
print('ALL TESTS PASSED')
