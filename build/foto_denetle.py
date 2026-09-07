# -*- coding: utf-8 -*-
"""Fotoğraf eşleşmelerini denetlemeye yardımcı olur.

Yanlış fotoğraf, yanlış koordinattan daha görünür bir hata: sayfanın en üstünde
duruyor. Bu betik şüpheli eşleşmeleri öne çıkarır ve gözle bakılacak listeyi
kısaltır — kural yazmadan önce hangi kalıbın bozulduğunu görmek için.

Kullanım:
  python build/foto_denetle.py            # özet + şüpheliler
  python build/foto_denetle.py --hepsi    # her eşleşmeyi listele
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "build"))
from foto import IMG, _norm  # noqa: E402


def main() -> int:
    hepsi = "--hepsi" in sys.argv
    fotolar = json.loads((KOK / "data" / "foto.json").read_text("utf-8"))
    mekanlar = {m["ad"]: m for m in
                json.loads((KOK / "data" / "mekanlar.json").read_text("utf-8"))}
    var = {a: f for a, f in fotolar.items() if f}
    print(f"{len(var)}/{len(mekanlar)} mekânda foto · "
          f"{dict(Counter(f['kaynak'] for f in var.values()))}\n")

    supheli = []
    for ad, f in sorted(var.items()):
        kaynak_ad = f.get("wiki") or ""
        ortak = _norm(ad) & _norm(kaynak_ad) if kaynak_ad else set()
        # Ayırt edici ortak sözcük ne kadar azsa eşleşme o kadar zayıf.
        zayif = kaynak_ad and not any(len(t) >= 5 for t in ortak)
        boy = (IMG / f["lg"]).stat().st_size // 1024 if (IMG / f["lg"]).exists() else 0
        satir = (f"  {f['kaynak'][:4]:5}{ad[:40]:42}{boy:>4} KB  "
                 f"<- {(kaynak_ad or f.get('yazar', ''))[:42]}")
        if zayif:
            supheli.append(satir)
        if hepsi:
            print(("? " if zayif else "  ") + satir.lstrip())

    if not hepsi:
        print(f"Zayıf eşleşme (ortak ayırt edici sözcük yok): {len(supheli)}")
        for s in supheli:
            print(s)
    print(f"\nGözle bakmak için: {IMG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
