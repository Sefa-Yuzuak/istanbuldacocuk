# -*- coding: utf-8 -*-
"""İBB Açık Veri Portalı'ndan indirilen resmî dosyaları tek biçime çevirir.

Girdi (data/ham/ altına indirilir):
  muzeler.xlsx       İBB Müzeleri Lokasyon Çalışma Gün ve Saatleri
  kutuphaneler.xlsx  İBB Kütüphaneleri Lokasyon Çalışma Gün ve Saatleri
  yesilalan.geojson  İstanbul Kentsel Açık ve Yeşil Alan Koordinatları

Çıktı:
  data/ibb_mekanlar.json   ad, tur, ilce, adres, telefon, saat, gun, lat, lng, alan_m2

Kural: hiçbir alan tahminle doldurulmaz. Kaynakta yoksa alan boş bırakılır.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
HAM = KOK / "data" / "ham"
CIKTI = KOK / "data" / "ibb_mekanlar.json"

# Çocuklu aile için anlamlı yeşil alan türleri. "Cadde (Kavşak ve Refüj)",
# "Karayolu", "Metro Çıkışı" ve "Kamu" türleri gidilecek yer değil, elenir.
YESIL_TURLER = {
    "Park": "park",
    "Mesire Alanı": "mesire",
    "Koru": "koru",
    "Kent Ormanı": "kent_ormani",
    "Hatıra Ormanı": "hatira_ormani",
    "Meydan": "meydan",
}

KAYNAKLAR = {
    "muze": "İBB Açık Veri Portalı — İBB Müzeleri Lokasyon, Çalışma Gün ve Saatleri",
    "kutuphane": "İBB Açık Veri Portalı — İBB Kütüphaneleri Lokasyon, Çalışma Gün ve Saatleri",
    "yesil": "İBB Açık Veri Portalı — İstanbul Kentsel Açık ve Yeşil Alan Koordinatları",
}


def _halkalar(geom: dict):
    """Her poligon için (dış halka, iç halkalar) verir.

    GeoJSON'da bir poligonun ilk halkası dış sınır, sonrakiler DELİKTİR (park içindeki
    gölet, bina, yol adası). 9.519 poligonun 50'sinde delik var; düşülmezse o alanların
    büyüklüğü olduğundan fazla görünür.
    """
    t, k = geom["type"], geom["coordinates"]
    if t == "Polygon":
        yield k[0], k[1:]
    elif t == "MultiPolygon":
        for parca in k:
            yield parca[0], parca[1:]


def _alan_ve_merkez(halka: list) -> tuple[float, float, float]:
    """Kabuk koordinatlarından ağırlık merkezi ve yaklaşık alan (m²).

    Küçük alanlarda eşit dikdörtgen izdüşümü yeterli: enlem 1° ≈ 111.320 m,
    boylam 1° ≈ 111.320 · cos(enlem) m.
    """
    if len(halka) < 3:
        return 0.0, 0.0, 0.0
    ort_en = sum(n[1] for n in halka) / len(halka)
    olcek_x = 111_320 * math.cos(math.radians(ort_en))
    olcek_y = 111_320
    xs = [n[0] * olcek_x for n in halka]
    ys = [n[1] * olcek_y for n in halka]
    iki_alan = cx = cy = 0.0
    for i in range(len(halka) - 1):
        capraz = xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
        iki_alan += capraz
        cx += (xs[i] + xs[i + 1]) * capraz
        cy += (ys[i] + ys[i + 1]) * capraz
    if abs(iki_alan) < 1e-9:          # dejenere halka: düz ortalama
        return (sum(n[1] for n in halka) / len(halka),
                sum(n[0] for n in halka) / len(halka), 0.0)
    alan = abs(iki_alan) / 2
    cx /= 3 * iki_alan
    cy /= 3 * iki_alan
    return cy / olcek_y, cx / olcek_x, alan


def _tr_bas(p: str) -> str:
    """Sözcüğün ilk harfini TÜRKÇE kurala göre büyütür.

    `"i".upper()` ASCII "I" verir; İSTANBUL/İDEALTEPE/İNÖNÜ küçültülüp geri
    büyütülünce "Istanbul", "Idealtepe", "Inönü" oluyordu (88 sayfada görünür).
    """
    if not p:
        return p
    ilk = {"i": "İ", "ı": "I"}.get(p[0], p[0].upper())
    return ilk + p[1:]


def _kucult(ad: str) -> str:
    return ad.replace("I", "ı").replace("İ", "i").lower()


def _ilce_duzelt(ad: str) -> str:
    """BEYOĞLU -> Beyoğlu. Türkçe büyük-küçük harf tuzağına dikkat."""
    ad = (ad or "").strip()
    if not ad:
        return ""
    return " ".join(_tr_bas(p) for p in _kucult(ad).split())


def _baslik(ad: str) -> str:
    ad = " ".join((ad or "").split())
    if ad.isupper():
        ad = " ".join(_tr_bas(p) for p in _kucult(ad).split())
    return ad


def _hucre(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def xlsx_oku(dosya: Path, tur: str) -> list[dict]:
    import openpyxl

    ws = openpyxl.load_workbook(dosya, read_only=True, data_only=True).active
    satirlar = list(ws.iter_rows(values_only=True))
    basliklar = [_hucre(h) for h in satirlar[0]]
    cikti = []
    for s in satirlar[1:]:
        k = dict(zip(basliklar, s))
        ad = _hucre(k.get("Müze Adı") or k.get("Kütüphane Adı"))
        if not ad:
            continue
        cikti.append({
            "ad": ad,
            "tur": tur,
            "ilce": _ilce_duzelt(_hucre(k.get("İlçe Adı"))),
            "adres": _hucre(k.get("Adres")),
            "telefon": _hucre(k.get("Telefon")).replace("\n", " / "),
            "saat": _hucre(k.get("Çalışma Saatleri")),
            "gun": _hucre(k.get("Çalışma Günleri")),
            "acilis_yili": _hucre(k.get("Açılış Yılı")),
            "lat": None, "lng": None, "alan_m2": None,
            "kaynak": KAYNAKLAR[tur],
        })
    return cikti


def geojson_oku(dosya: Path) -> list[dict]:
    veri = json.loads(dosya.read_text(encoding="utf-8"))
    cikti = []
    for ozellik in veri["features"]:
        o = ozellik["properties"]
        tur_ham = (o.get("TUR") or "").strip()
        if tur_ham not in YESIL_TURLER:
            continue
        ad = _baslik(o.get("MAHALLE"))
        if not ad:
            continue
        toplam_alan, en_iyi = 0.0, None
        for dis, icler in _halkalar(ozellik["geometry"]):
            lat, lng, alan = _alan_ve_merkez(dis)
            for ic in icler:                      # delikleri düş
                alan -= _alan_ve_merkez(ic)[2]
            alan = max(alan, 0.0)
            toplam_alan += alan
            if en_iyi is None or alan > en_iyi[2]:
                en_iyi = (lat, lng, alan)
        if en_iyi is None:
            continue
        cikti.append({
            "ad": ad,
            "tur": YESIL_TURLER[tur_ham],
            "ilce": _ilce_duzelt(o.get("ILCE")),
            "adres": "", "telefon": "", "saat": "", "gun": "", "acilis_yili": "",
            "lat": round(en_iyi[0], 6),
            "lng": round(en_iyi[1], 6),
            "alan_m2": round(toplam_alan),
            "kaynak": KAYNAKLAR["yesil"],
        })
    return cikti


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not HAM.exists():
        sys.exit(f"Ham veri klasörü yok: {HAM}\nÖnce build/ibb_indir.py çalıştırın.")

    kayitlar: list[dict] = []
    for dosya, tur in (("muzeler.xlsx", "muze"), ("kutuphaneler.xlsx", "kutuphane")):
        yol = HAM / dosya
        if yol.exists():
            k = xlsx_oku(yol, tur)
            kayitlar += k
            print(f"  {dosya:<20} {len(k):>4} kayıt")
        else:
            print(f"  {dosya:<20} YOK, atlandı")

    gj = HAM / "yesilalan.geojson"
    if gj.exists():
        k = geojson_oku(gj)
        kayitlar += k
        print(f"  {'yesilalan.geojson':<20} {len(k):>4} kayıt (ilgisiz türler elendi)")
    else:
        print(f"  {'yesilalan.geojson':<20} YOK, atlandı")

    kayitlar.sort(key=lambda k: (k["ilce"], k["tur"], k["ad"]))
    CIKTI.write_text(json.dumps(kayitlar, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    print(f"\n{len(kayitlar)} kayıt -> {CIKTI.relative_to(KOK)}")
    print("tür :", dict(Counter(k["tur"] for k in kayitlar).most_common()))
    print("ilçe:", len({k['ilce'] for k in kayitlar}), "farklı")
    koordinatli = sum(1 for k in kayitlar if k["lat"])
    print(f"koordinatlı: {koordinatli}/{len(kayitlar)}")


if __name__ == "__main__":
    main()
