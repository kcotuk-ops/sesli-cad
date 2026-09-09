# VoiceCAD Studio V5 — Tek Paket

Mobil/masaüstü tarayıcıda çalışan feature tabanlı CAD prototipi.

## V5 özellikleri
- SolidWorks/CATIA benzeri çalışma alanı
- FeatureManager ağacı
- PropertyManager ile feature ölçüsü değiştirme / silme
- 3D STL önizleme: döndür, zoom, pan, standart görünüşler
- Model yüzeyine/noktaya dokunarak konum seçme
- Seçili noktaya manuel Delik, Kör Delik, Havşa, Cep, Slot, Kama vb. ekleme
- Seçili noktadan sonra Türkçe “buraya Ø8 delik aç” gibi ses/metin komutları
- Türkçe sesli komut
- STEP, STL ve teknik resim PDF çıktısı
- WhatsApp paylaşım bağlantısı
- iPhone Safari responsive arayüz

## Dokunarak işlem
1. 3D model üzerinde planar bir yüzeye kısa dokun.
2. Seçilen yüzey ve X/Y koordinatı ekranda gösterilir.
3. Üst araç çubuğundan Delik/Cep/Slot vb. seç. Form seçili koordinatla açılır.
4. Alternatif: mikrofona “buraya 8 mm delik aç” de.

Not: V5’te blokların üst/alt/sağ/sol/ön/arka yüzeyleri dokunarak konumlandırmayı destekler. Silindirik parçaların eğrisel yan yüzeyine dokunarak feature yerleştirme henüz sınırlandırılmıştır; uç yüzeylerde ve sesli tarifte çalışır.

## Render kurulumu
Mevcut Render servisiniz `sesli_cad_cloud_ready` Root Directory kullanıyorsa bu ZIP'in içindeki tüm dosya/klasörleri GitHub'da o klasörün içine yükleyin ve commit edin. Render otomatik deploy eder.

Health check: `/health`

## V6 AI çalışma akışı
- Sesli/yazılı komut önce öneri olarak yorumlanır; doğrudan modele uygulanmaz.
- Önerilen model 3D görünümde turuncu yarı saydam olarak gösterilir.
- Kullanıcı Uygula/Vazgeç seçer.
- Delik/cep/slot yerleşimi için X/Y zorunlu değildir: merkez, sağ, sol, üst, alt ve köşeler seçilebilir.
- İstenirse model üzerinde dokunulan nokta kullanılabilir; koordinatlar kullanıcıdan istenmez.
- Pah gerçek geometrik dış kenardan seçilir: üst dış, alt dış veya iki dış kenar.

## V7 — Teknik resim fotoğrafı/PDF → STEP

Üst menüde **📷 Teknik Resim** butonu bulunur. Kullanıcı JPG/PNG/WEBP veya PDF teknik resim yükleyebilir.

Akış:
1. AI görünüşleri ve basılı ölçüleri okur.
2. İlk CAD yorumu oluşturulur.
3. Aynı teknik resim ikinci bir bağımsız AI mühendislik kontrolünden geçirilir.
4. Ölçüler, güven yüzdeleri, uyarılar ve bloklayıcı belirsizlikler kullanıcıya gösterilir.
5. Geometri oluşturulabiliyorsa 3D turuncu önizleme gösterilir.
6. `confidence >= 0.72` ve bloklayıcı belirsizlik yoksa **Bu modeli kullan** açılır.
7. Kullanıcı onayladıktan sonra mevcut STEP/PDF çıktısı kullanılabilir.

### Render'da zorunlu ayar
Render > sesli-cad > Environment bölümüne şu secret eklenmelidir:

- `ANTHROPIC_API_KEY` = Anthropic API anahtarınız

İsteğe bağlı:
- `ANTHROPIC_MODEL=claude-sonnet-5`
- `DRAWING_AI_VERIFY=1` (iki aşamalı kontrol açık)

> Önemli: Teknik resimde geometriyi tanımlamak için gerekli bir ölçü okunamıyorsa sistem ölçüyü tahmin etmez ve STEP üretimini kilitler. Fotoğrafın düz, net, kırpılmamış ve tüm ölçülerin okunur olması sonuç kalitesini doğrudan etkiler.
