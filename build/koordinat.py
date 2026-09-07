"""İBB müze ve kütüphanelerinin koordinatlarını OpenStreetMap'ten bulur.

İBB'nin açık veri dosyalarında müze ve kütüphaneler için enlem/boylam sütunu YOK;
yalnız adres var. Bu kayıtlar OSM'de büyük ölçüde "İBB <ad>" biçiminde işaretli
olduğu için Nominatim ile isabetli eşleşiyor.

Sonuç `data/koordinat.json` dosyasına yazılır ve orada kalır: her derlemede
yeniden sorgulanmaz, kaynak da kayıtla birlikte saklanır (uydurma koordinat yok).

Kullanım:  python build/koordinat.py [--yenile]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DATA = KOK / "data"
ONBELLEK = DATA / "koordinat.json"

# Nominatim kullanım koşulu: gerçek bir kimlik ve saniyede en fazla 1 istek.
BASLIK = {"User-Agent": "istanbuldacocuk.com/1.0 (merhaba@istanbuldacocuk.com)"}
BEKLE = 1.2

# İstanbul sınır kutusu — dışına düşen sonuç kabul edilmez.
IST_KUTU = (40.78, 41.65, 27.90, 29.95)  # lat_min, lat_max, lng_min, lng_max


def sorgula(q: str) -> tuple[float, float, str] | None:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 3, "countrycodes": "tr"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=BASLIK), timeout=30) as y:
            sonuc = json.load(y)
    except Exception:
        return None
    for s in sonuc:
        lat, lng = float(s["lat"]), float(s["lon"])
        if IST_KUTU[0] <= lat <= IST_KUTU[1] and IST_KUTU[2] <= lng <= IST_KUTU[3]:
            return lat, lng, s.get("display_name", "")
    return None


# Nominatim Türkçe adres kısaltmalarını çözemiyor: "Çubuklu Mah. Şehit Ersin
# Güner Cad." boş dönerken açılmış hali eşleşiyor. 47 kayıt bu yüzden koordinatsızdı.
ADRES_KISALTMA = [
    (r"(?i)\bmah(?:\.|allesi)?(?=\s|,|$)", "Mahallesi"),
    (r"(?i)\bcad(?:\.|desi)?(?=\s|,|$)", "Caddesi"),
    (r"(?i)\bcd\.?(?=\s|,|$)", "Caddesi"),
    (r"(?i)\bsok(?:\.|ak|ağı)?(?=\s|,|$)", "Sokak"),
    (r"(?i)\bsk\.?(?=\s|,|$)", "Sokak"),
    (r"(?i)\bbul(?:\.|var[ıi])?(?=\s|,|$)", "Bulvarı"),
    (r"(?i)\bblv\.?(?=\s|,|$)", "Bulvarı"),
    (r"(?i)\bno\s*:?\s*[\d/\-]+\w*", ""),   # kapı numarası Nominatim'i şaşırtıyor
    (r"(?i)\bkat\s*:?\s*[\d/\-]+", ""),
]


def adres_ac(adres: str) -> str:
    """Kısaltmaları açar, kapı/kat bilgisini atar."""
    a = (adres or "").replace("/", ", ")
    for kalip, yerine in ADRES_KISALTMA:
        a = re.sub(kalip, yerine, a)
    a = re.sub(r"\s+", " ", a)
    return re.sub(r"\s*,\s*", ", ", a).strip(" ,.")


def ara(ad: str, ilce: str, adres: str) -> tuple[float, float, str, str] | None:
    """En dar kalıptan en genişe dener; ilk İstanbul içi sonuç kazanır.

    Dördüncü değer sonucun HANGİ YOLLA bulunduğu: "ad" ya da "adres". `veri.py`
    ikisini farklı denetler — ad eşleşmesinde OSM adının mekân adıyla örtüşmesi,
    adres eşleşmesinde sonucun ilçeye düşmesi aranır. Tek bir ölçüt ikisine de
    uymuyor: adresten bulunan nokta mekân adını taşımaz, bu doğaldır.
    """
    denemeler = [(f"İBB {ad}, {ilce}, İstanbul", "ad"), (f"{ad}, {ilce}, İstanbul", "ad")]
    if adres:
        acik = adres_ac(adres)
        parca = [p.strip() for p in acik.split(",") if p.strip()]
        if len(parca) >= 2:
            denemeler.append((f"{', '.join(parca[:2])}, {ilce}, İstanbul", "adres"))
        if acik:
            denemeler.append((f"{acik}, İstanbul", "adres"))
    for q, yol in denemeler:
        s = sorgula(q)
        time.sleep(BEKLE)
        if s:
            return s[0], s[1], s[2], yol
    return None


def ters(lat: float, lng: float) -> str | None:
    """Koordinattan ilçe adı (Nominatim reverse). Şehir Tiyatroları verisinde ilçe yok."""
    url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lng, "format": "json", "zoom": 10, "accept-language": "tr"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=BASLIK), timeout=30) as y:
            a = json.load(y).get("address", {})
    except Exception:
        return None
    # İstanbul'da ilçe OSM'de town/city_district/suburb alanlarından birinde geliyor.
    for k in ("town", "city_district", "municipality", "county", "suburb"):
        if a.get(k):
            return a[k]
    return None


def ters_toplu(noktalar: list[tuple[str, float, float]]) -> dict:
    """[(anahtar, lat, lng)] -> {anahtar: ilçe}. Sonuç koordinat.json içinde saklanır."""
    onbellek = json.loads(ONBELLEK.read_text(encoding="utf-8")) if ONBELLEK.exists() else {}
    for anahtar, lat, lng in noktalar:
        k = f"ters|{anahtar}"
        if k in onbellek:
            continue
        onbellek[k] = ters(lat, lng)
        time.sleep(BEKLE)
    ONBELLEK.write_text(json.dumps(onbellek, ensure_ascii=False, indent=1), encoding="utf-8")
    return {a: onbellek.get(f"ters|{a}") for a, _, _ in noktalar}


def hedefler() -> list[dict]:
    """Koordinatı olmayan müze, kütüphane ve kültür merkezleri.

    Kültür merkezleri ayrı bir xlsx'ten geliyor ve hiç sorgulanmamıştı; 16'sının
    da koordinatı yoktu. Anahtarları `veri.py`'nin kullandığı temizlenmiş adla
    kurulur, ham adla değil.
    """
    sys.path.insert(0, str(KOK / "build"))
    from veri import kultur_merkezleri  # noqa: PLC0415  (döngüsel içe aktarımı önler)

    kayitlar = json.loads((DATA / "ibb_mekanlar.json").read_text(encoding="utf-8"))
    out = [k for k in kayitlar if k["tur"] in ("muze", "kutuphane") and not k.get("lat")]
    out += [k for k in kultur_merkezleri() if not k.get("lat")]
    return out


def main():
    yenile = "--yenile" in sys.argv
    hedef = hedefler()
    onbellek = {} if yenile or not ONBELLEK.exists() else json.loads(ONBELLEK.read_text(encoding="utf-8"))

    bulundu = eksik = 0
    for i, k in enumerate(hedef, 1):
        anahtar = f"{k['tur']}|{k['ad']}|{k['ilce']}"
        if onbellek.get(anahtar):
            continue          # boş (None) kayıtlar yeni adres kalıbıyla yeniden denenir
        s = ara(k["ad"], k["ilce"], k.get("adres") or "")
        if s:
            onbellek[anahtar] = {"lat": round(s[0], 6), "lng": round(s[1], 6),
                                 "kaynak": "OpenStreetMap (Nominatim)", "osm_ad": s[2][:90],
                                 "yol": s[3]}
            bulundu += 1
        else:
            onbellek[anahtar] = None
            eksik += 1
        if i % 20 == 0:
            ONBELLEK.write_text(json.dumps(onbellek, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {i}/{len(hedef)} ... bulundu {bulundu}, bulunamadı {eksik}", flush=True)

    ONBELLEK.write_text(json.dumps(onbellek, ensure_ascii=False, indent=1), encoding="utf-8")
    var = sum(1 for v in onbellek.values() if v)
    print(f"✓ {len(onbellek)} kayıt sorgulandı, {var} koordinat bulundu -> {ONBELLEK.name}")


if __name__ == "__main__":
    main()
