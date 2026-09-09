# Sesli CAD – V1

iPhone/iPad/PC tarayıcısından çalışan, Türkçe sesli veya manuel komutla mekanik parça oluşturan prototip.

## Özellikler
- Manuel parça: mil/silindir, flanş, blok, boru
- Türkçe komut ayrıştırma (internet/AI API olmadan temel kalıplar)
- Sesli giriş: tarayıcının SpeechRecognition/webkitSpeechRecognition desteği varsa Türkçe konuşma
- İşlem ekleme: delik, kör delik, PCD delikleri, pah, radyüs, kademe, kama kanalı, cep, diş notasyonu
- STEP + STL üretimi
- A4 yatay teknik resim PDF'i (4 görünüş + işlem/ölçü özeti)
- WhatsApp paylaşım bağlantısı
- Mobil uyumlu/PWA tabanlı arayüz

> Not: V1 teknik resim PDF'i otomatik 4 görünüş ve ölçü/feature özeti üretir; üretim standardında tam GD&T / otomatik ölçülendirme henüz değildir. Diş özelliği V1'de geometrik helis yerine teknik notasyon/metadata olarak tutulur.

## Çalıştırma
Python 3.11/3.12 önerilir.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Bilgisayarda: http://localhost:8000

iPhone ile aynı Wi-Fi ağındaysan bilgisayarın yerel IP'sini aç: `http://BILGISAYAR_IP:8000`.
Gerçek internet kullanımı için HTTPS destekli bir sunucuya deploy et.

## Örnek ses/metin komutu
`100 milimetre çapında 20 milimetre kalınlığında flanş oluştur. Ortasına 40 milimetre delik aç. 80 PCD üzerinde 6 tane 10 milimetrelik delik aç ve 2 milimetre pah ver.`

## Buluta yayınlama (Render / HTTPS)

Bu proje Docker ile Render'a hazırdır. Repo kökünde `Dockerfile` ve `render.yaml` bulunur.
Render üzerinde Web Service oluşturup bu repoyu seçin; runtime Docker olsun. Uygulama `0.0.0.0:$PORT` üzerinden başlar ve `/health` sağlık kontrolü vardır.
