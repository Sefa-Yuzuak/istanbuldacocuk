# -*- coding: utf-8 -*-
"""Mevcut kapak görsellerini yeni bayt bütçesiyle yeniden kodlar.

`foto.py` kodlama ayarları değiştiğinde (kalite, bütçe, boyut) elde yalnız
işlenmiş webp'ler kalıyor; aslı saklanmıyor. Bu betik `foto.json`'daki Commons
dosya adından aslı yeniden indirip `kirp_kaydet`'i çalıştırır. Eşleştirmeye
dokunmaz — hangi mekânda hangi foto var, aynen korunur.

Kullanım: python build/yeniden_kodla.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK / "build"))
from foto import IMG, UA, kirp_kaydet  # noqa: E402

HEDEF = KOK / "data" / "foto.json"
# 1600 piksel, 1200'lük kapak için fazlasıyla yeter; aslını indirmekten çok hızlı.
GENISLIK = 1600


def indir(sayfa_url: str) -> bytes | None:
    dosya = urllib.parse.unquote(sayfa_url.rsplit("File:", 1)[-1])
    url = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
           + urllib.parse.quote(dosya) + f"?width={GENISLIK}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        print(f"    indirilemedi: {e}")
        return None


def main() -> int:
    kayitlar = json.loads(HEDEF.read_text("utf-8"))
    hedefler = [(ad, f) for ad, f in kayitlar.items()
                if f and f.get("kaynak") in ("wikipedia", "commons")]
    print(f"{len(hedefler)} görsel yeniden kodlanacak (bütçe: lg 150 KB, sm 45 KB)\n")

    onceki = sonraki = 0
    for i, (ad, f) in enumerate(hedefler, 1):
        eski = sum((IMG / f[e]).stat().st_size for e in ("lg", "sm") if (IMG / f[e]).exists())
        veri = indir(f["sayfa"])
        if not veri:
            continue
        slug = f["lg"].rsplit("-lg.webp", 1)[0]
        f.update(kirp_kaydet(veri, slug))   # 'og' (paylaşım JPEG'i) dahil
        HEDEF.write_text(json.dumps(kayitlar, ensure_ascii=False, indent=1), "utf-8")
        yeni = sum((IMG / f[e]).stat().st_size for e in ("lg", "sm"))
        onceki += eski
        sonraki += yeni
        ok = "↓" if yeni < eski else "="
        print(f"  {i:>2}/{len(hedefler)} {ok} {eski//1024:>4} -> {yeni//1024:>4} KB  {ad}")
        time.sleep(0.4)

    print(f"\n✓ toplam {onceki/1e6:.1f} MB -> {sonraki/1e6:.1f} MB "
          f"(%{100*(onceki-sonraki)/onceki:.0f} küçüldü)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
