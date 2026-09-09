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
