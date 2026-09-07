# -*- coding: utf-8 -*-
"""Fotoğrafı olmayan sayfalar için varsayılan paylaşım görselini üretir.

391 sayfanın yalnız 32'sinde kapak fotoğrafı var; kalanı WhatsApp, X ve
Facebook'ta başlıksız boş kartla paylaşılıyordu. Tek bir markalı görsel bu
boşluğu kapatıyor — sayfa başına görsel üretmek bu iş için fazla karmaşık.

Çıktı: static/og.jpg (1200x630, Facebook/X'in beklediği oran)
Kullanım: python build/og_gorsel.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
HEDEF = KOK / "static" / "og.jpg"
BOYUT = (1200, 630)

LACIVERT = (18, 80, 107)
MAVI = (47, 159, 199)
ACIK = (232, 244, 248)
SARI = (242, 177, 52)

YAZI = Path(r"C:\Windows\Fonts")


def font(ad: str, boy: int) -> ImageFont.FreeTypeFont:
    """Türkçe karakterleri doğru basan bir yazı tipi bul; yoksa PIL varsayılanı."""
    for aday in (ad, "segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"):
        p = YAZI / aday
        if p.exists():
            return ImageFont.truetype(str(p), boy)
    return ImageFont.load_default()


def main() -> int:
    site = json.loads((KOK / "data" / "site.json").read_text(encoding="utf-8"))
    mekanlar = json.loads((KOK / "data" / "mekanlar.json").read_text(encoding="utf-8"))
    yesil = json.loads((KOK / "data" / "yesil_alanlar.json").read_text(encoding="utf-8"))

    im = Image.new("RGB", BOYUT, LACIVERT)
    d = ImageDraw.Draw(im)
    # Lacivertten maviye dikey geçiş — düz zemin ucuz görünüyor.
    for y in range(BOYUT[1]):
        t = y / BOYUT[1]
        d.line([(0, y), (BOYUT[0], y)],
               fill=tuple(round(a + (b - a) * t * 0.55) for a, b in zip(LACIVERT, MAVI)))
    d.rectangle([0, BOYUT[1] - 14, BOYUT[0], BOYUT[1]], fill=SARI)

    d.text((80, 150), site["ad"], font=font("segoeuib.ttf", 92), fill="white")
    d.text((80, 268), "İstanbul'da çocukla gidilecek yerler",
           font=font("seguisb.ttf", 44), fill=ACIK)

    sayilar = (f"{len(mekanlar)} mekân   ·   {len(yesil)} park ve koru   ·   39 ilçe")
    d.text((80, 356), sayilar, font=font("seguisb.ttf", 36), fill=ACIK)
    d.text((80, 468), "Her kayıt İBB Açık Veri Portalı'ndan · koordinatı ve kaynağıyla",
           font=font("seguisb.ttf", 30), fill=(205, 228, 238))

    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    im.save(HEDEF, "JPEG", quality=86, optimize=True)
    print(f"✓ {HEDEF.relative_to(KOK)} ({HEDEF.stat().st_size // 1024} KB, {BOYUT[0]}x{BOYUT[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
