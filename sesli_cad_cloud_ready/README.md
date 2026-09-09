# VoiceCAD Studio V8 Standalone

Bu sürüm Anthropic/Claude/OpenAI gibi harici bir AI API'sine ihtiyaç duymaz.

## Teknik resim motoru
- OpenCV: perspektif düzeltme, çizgi/daire geometrisi
- Tesseract OCR (Türkçe + İngilizce): ölçü ve teknik sembol metni
- Kendi mühendislik kuralları: Ø, R, M, PCD, adet x çap, pah ve parça aileleri
- CadQuery/OpenCascade: gerçek STEP/STL üretimi
- PyMuPDF: PDF teknik resimlerin ilk sayfasını yüksek çözünürlükte işleme

## Desteklenen geniş geometri aileleri
- prizmatik blok/plaka/braket tabanları
- silindir, flanş, boru
- dönel parça zarfı ve doğrulanabilir profiller
- delik, kör delik, havşa, karşı havşa
- doğrusal/dairesel delik düzenleri
- slot, cep, kama, kademe
- pah, radyüs
- diş çağrıları/metadata

## Güvenlik ilkesi
Program fotoğraf ölçeğinden ölçü uydurmaz. STEP'i tanımlayan ölçü veya feature konumu kesin belirlenemiyorsa eksik bilgi olarak gösterir. Kullanıcı eksik ölçüyü tamamlayınca 3D/STEP oluşturulur.

## Render
Bu sürümde `ANTHROPIC_API_KEY` gerekmez. Eski Environment değişkenini istersen silebilirsin.

Not: Tesseract/OpenCV kullandığı için ilk Docker build önceki sürümlere göre daha uzun sürebilir.
