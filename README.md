# istanbuldacocuk.com

İstanbul'da çocukla gidilecek yerler — tamamı **İBB Açık Veri Portalı**'ndan derlenen,
puansız ve kaynaklı statik rehber.

## Neden puan yok?

Mekân gezilmeden verilen puan, olmayan bir değerlendirmeyi varmış gibi gösterir.
Bu sitede yalnızca ölçülebilir bilgi yayımlanır: alan kaç m², hangi gün/saatte açık,
girişi ücretsiz mi, kapalı alan mı, koordinatı ne, kaynağı hangi veri seti.

## Veri hattı

```
build/ibb_veri.py    İBB CKAN API'sinden müze, kütüphane ve yeşil alan verisi
build/koordinat.py   müze/kütüphane koordinatları + tiyatro sahnesi ilçesi (OSM/Nominatim)
build/veri.py        temizler, parçalı parkları birleştirir, ilçe/yaka ekler  -> data/mekanlar.json
build/icerik.py      rehber ve düz sayfaları VERİDEN üretir  -> data/rehberler.json
build/derle.py       dist/ altına tüm siteyi yazar
build/denetle.py     yayından önce HTML/SEO denetimi
```

Ham kaynak dosyalar (52 MB) depoda tutulmaz; `veri.py` eksikse portaldan indirir.

## Kaynak dosyalarda bulunan ve onarılan hatalar

1. **Parçalı park kaydı** — aynı park "…/doğu 1", "/doğu 2" gibi ayrı satırlarda.
   Birleştirilmeseydi tek park birkaç sayfa ve gerçek boyutunun altında görünürdü.
2. **Ondalık ayracı düşmüş koordinat** — sosyal tesis dosyasında `410578458`.
3. **Türkçe büyük/küçük harf bozulması** — kaynak adlar `.title()` ile üretilmiş;
   `"BAKIRKÖY EĞİTİM".title()` Python'da `"Bakirköy Eği̇ti̇m"` verir. 46 ad bozuktu.
4. **Adresten ilçe çıkarımı** — "Arnavutköy Sosyal Tesisi" Beşiktaş'ta; ilçe her zaman
   adresin ilçe alanından alınır, addan değil.
5. **Koordinatı olmayan müze/kütüphane** — İBB verisinde koordinat sütunu yok;
   OSM'den bulundu, bulunamayanlar boş bırakıldı.

## Yayın

`main`'e push → GitHub Actions → Coolify deploy API (`force=true`) → Docker (nginx:alpine).
