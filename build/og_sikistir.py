# -*- coding: utf-8 -*-
"""Paylaşım kartı JPEG'lerini bütçeye sokar — yeniden indirmeden.

`-og.jpg` dosyaları sitede hiç gösterilmiyor; yalnız sosyal medya tarayıcısı
çekiyor. Bütçesiz üretilenler ortalama 187 KB'tı. Kaynak `-lg.webp` zaten aynı
16:9 kırpmanın 1200x675 hali, o yüzden ağdan bir şey indirmeye gerek yok.

Kullanım: python build/og_sikistir.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "build"))
from foto import BOYUTLAR, BUTCE, IMG  # noqa: E402

HEDEF = KOK / "data" / "foto.json"


def main() -> int:
    kayitlar = json.loads(HEDEF.read_text("utf-8"))
    hedefler = [(ad, f) for ad, f in kayitlar.items() if f and f.get("og")]
    onceki = sonraki = 0
    dokunulan = 0
    for ad, f in hedefler:
        og = IMG / f["og"]
        lg = IMG / f["lg"]
        if not (og.exists() and lg.exists()):
            continue
        eski = og.stat().st_size
        onceki += eski
        if eski <= BUTCE["og"]:
            sonraki += eski
            continue
        with Image.open(lg) as im:
            kaynak = im.convert("RGB").resize(BOYUTLAR["lg"], Image.LANCZOS)
        for kalite in (78, 70, 62, 54):
            kaynak.save(og, "JPEG", quality=kalite, optimize=True, progressive=True)
            if og.stat().st_size <= BUTCE["og"]:
                break
        sonraki += og.stat().st_size
        dokunulan += 1
    print(f"{len(hedefler)} og dosyası, {dokunulan} tanesi küçültüldü")
    print(f"✓ {onceki/1e6:.1f} MB -> {sonraki/1e6:.1f} MB"
          + (f"  (%{100*(onceki-sonraki)/onceki:.0f} küçüldü)" if onceki else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
