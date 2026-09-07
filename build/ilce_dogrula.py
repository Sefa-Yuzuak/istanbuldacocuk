# -*- coding: utf-8 -*-
"""Koordinatı olan her kaydın ilçesini OpenStreetMap'ten ters çözümler.

İBB'nin ilçe alanı çoğunlukla doğru ama hatasız değil: Taksim Gezi Parkı Şişli
yazılmış, gerçekte Beyoğlu'nda. Öte yandan OSM de yanılıyor (Burgazada'daki bir
kaydı Fatih sanıyor). Bu yüzden ters çözüm tek başına karar vermez; `veri.py`
anlaşmazlıkta coğrafyaya sorar (bkz. ilce_karar).

Çıktı: data/ilce_osm.json  {"41.038655,28.986853": "Beyoğlu", ...}
Kullanım: python build/ilce_dogrula.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "build"))
from koordinat import ters  # noqa: E402

HEDEF = KOK / "data" / "ilce_osm.json"


def main() -> None:
    kayitlar = []
    for ad in ("mekanlar.json", "yesil_alanlar.json"):
        kayitlar += json.loads((KOK / "data" / ad).read_text(encoding="utf-8"))
    noktalar = sorted({f"{k['lat']:.6f},{k['lng']:.6f}" for k in kayitlar if k.get("lat")})
    onbellek = json.loads(HEDEF.read_text(encoding="utf-8")) if HEDEF.exists() else {}
    kalan = [n for n in noktalar if n not in onbellek]
    print(f"{len(noktalar)} nokta, {len(kalan)} tanesi sorgulanacak")

    for i, n in enumerate(kalan, 1):
        lat, lng = (float(x) for x in n.split(","))
        onbellek[n] = ters(lat, lng)
        time.sleep(1.15)
        if i % 25 == 0:
            HEDEF.write_text(json.dumps(onbellek, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {i}/{len(kalan)}", flush=True)

    HEDEF.write_text(json.dumps(onbellek, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {sum(1 for v in onbellek.values() if v)}/{len(onbellek)} nokta çözüldü -> {HEDEF.name}")


if __name__ == "__main__":
    main()
