# -*- coding: utf-8 -*-
"""dist/ çıktısını yayına vermeden önce denetler.

Kontroller: çift/uzun başlık, meta açıklama, tek robots ve canonical etiketi,
tek h1, bozuk JSON-LD, kırık iç bağlantı, sitemap tutarlılığı, ince sayfa.
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DIST = KOK / "dist"
BASLIK_EN = 62
DESC_EN = 160
EN_AZ_METIN = 900        # gövde metni bu karakterin altındaysa ince sayfa şüphesi


def metin(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    return " ".join(re.sub(r"(?s)<[^>]+>", " ", h).split())


def main() -> int:
    if not DIST.exists():
        sys.exit("dist/ yok — önce build/derle.py çalıştırın.")
    sayfalar = sorted(DIST.rglob("*.html"))
    site = json.loads((KOK / "data" / "site.json").read_text(encoding="utf-8"))
    kok = site["url"].rstrip("/")

    sorunlar: list[str] = []
    basliklar: dict[str, list[str]] = defaultdict(list)
    descler: dict[str, list[str]] = defaultdict(list)
    ic_baglar: dict[str, set[str]] = defaultdict(set)

    def yol(p: Path) -> str:
        r = p.relative_to(DIST).as_posix()
        return "/" if r == "index.html" else "/" + r.removesuffix("index.html")

    for p in sayfalar:
        h = p.read_text(encoding="utf-8")
        u = yol(p)
        dis_404 = p.name == "404.html"

        t = re.search(r"<title>(.*?)</title>", h, re.S)
        if not t:
            sorunlar.append(f"{u}: <title> yok")
        else:
            b = html.unescape(t.group(1).strip())
            if not dis_404:
                basliklar[b].append(u)
            if len(b) > BASLIK_EN:
                sorunlar.append(f"{u}: başlık {len(b)} karakter (>{BASLIK_EN}) — {b[:70]}")

        d = re.search(r'<meta name="description" content="(.*?)">', h, re.S)
        if not d or not d.group(1).strip():
            sorunlar.append(f"{u}: meta description yok")
        else:
            dd = html.unescape(d.group(1))
            if not dis_404:
                descler[dd].append(u)
            if len(dd) > DESC_EN:
                sorunlar.append(f"{u}: description {len(dd)} karakter (>{DESC_EN})")

        n = len(re.findall(r'<meta name="robots"', h))
        if n != 1:
            sorunlar.append(f"{u}: robots etiketi {n} adet (1 olmalı)")
        if dis_404 and "noindex" not in h:
            sorunlar.append(f"{u}: 404 sayfasında noindex yok")

        c = re.findall(r'<link rel="canonical" href="(.*?)"', h)
        if len(c) != 1:
            sorunlar.append(f"{u}: canonical {len(c)} adet")
        elif not dis_404 and c[0] != f"{kok}{u}":
            sorunlar.append(f"{u}: canonical uyuşmuyor -> {c[0]}")

        h1 = re.findall(r"(?s)<h1[^>]*>(.*?)</h1>", h)
        if len(h1) != 1:
            sorunlar.append(f"{u}: h1 sayısı {len(h1)}")

        for blok in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', h):
            try:
                json.loads(blok)
            except json.JSONDecodeError as e:
                sorunlar.append(f"{u}: bozuk JSON-LD ({e})")

        g = metin(h)
        if not dis_404 and len(g) < EN_AZ_METIN:
            sorunlar.append(f"{u}: gövde metni {len(g)} karakter (ince sayfa şüphesi)")

        for bag in re.findall(r'href="(/[^"#?]*)"', h):
            ic_baglar[bag].add(u)

        # Kaynaktaki telefon alanı iki numarayı ayraçsız yapıştırıyordu; 55 sayfada
        # "0 (212) 249 95 65 0 (212) 249 09 45 Dahili:663865" ham haliyle görünüyordu.
        for tel in re.findall(r"<th scope=\"row\">Telefon</th>\s*<td>(.*?)</td>", h, re.S):
            duz = " ".join(re.sub(r"(?s)<[^>]+>", " ", html.unescape(tel)).split())
            if not re.fullmatch(r"0\d{3} \d{3} \d{2} \d{2}( \(dahili [\d, ]+\))?"
                                r"( · 0\d{3} \d{3} \d{2} \d{2})*", duz):
                sorunlar.append(f"{u}: telefon biçimi bozuk -> {duz[:60]}")

    for b, yerler in basliklar.items():
        if len(yerler) > 1:
            sorunlar.append(f"ÇİFT BAŞLIK ({len(yerler)}): {b[:60]} -> {', '.join(yerler[:4])}")
    for d, yerler in descler.items():
        if len(yerler) > 1:
            sorunlar.append(f"ÇİFT DESCRIPTION ({len(yerler)}): {d[:55]}… -> {', '.join(yerler[:3])}")

    varlik = {yol(p) for p in sayfalar}
    for f in DIST.rglob("*"):
        if f.is_file() and f.suffix != ".html":
            varlik.add("/" + f.relative_to(DIST).as_posix())
    for bag, nereden in sorted(ic_baglar.items()):
        if bag not in varlik and bag.rstrip("/") + "/" not in varlik:
            sorunlar.append(f"KIRIK BAĞ: {bag} (örn. {sorted(nereden)[0]})")

    # Yetim sayfa: sitemap'te var ama hiçbir sayfadan bağlanmıyor. Yaka×kategori
    # sayfaları (12 adet) tam bu durumdaydı — sitemap onları bildiriyordu ama
    # tarayıcı gezinerek ulaşamıyordu, iç bağlantı değeri de sıfırdı.
    for u in sorted(varlik):
        if not u.endswith("/"):
            continue
        gelen = ic_baglar.get(u, set()) - {u}
        if not gelen and u != "/":
            sorunlar.append(f"YETİM SAYFA (hiç iç bağlantı yok): {u}")

    sm = (DIST / "sitemap.xml").read_text(encoding="utf-8")
    sm_urls = re.findall(r"<loc>(.*?)</loc>", sm)
    if len(sm_urls) != len(set(sm_urls)):
        sorunlar.append(f"sitemap'te tekrar eden URL: {len(sm_urls) - len(set(sm_urls))}")
    for u in sm_urls:
        if not u.startswith(kok + "/") or u.startswith(kok + "//"):
            sorunlar.append(f"sitemap'te yanlış kök: {u}")
    eksik = {u.removeprefix(kok) for u in sm_urls} - varlik
    if eksik:
        sorunlar.append(f"sitemap'te olup dosyası olmayan: {sorted(eksik)[:5]}")

    print(f"denetlenen sayfa : {len(sayfalar)}")
    print(f"sitemap URL      : {len(sm_urls)}")
    print(f"benzersiz başlık : {len(basliklar)}")
    if sorunlar:
        print(f"\n{len(sorunlar)} SORUN:")
        for s in sorunlar[:80]:
            print("  -", s)
        if len(sorunlar) > 80:
            print(f"  … {len(sorunlar) - 80} sorun daha")
        return 1
    print("\n✓ sorun yok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
