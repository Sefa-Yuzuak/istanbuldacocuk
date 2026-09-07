# -*- coding: utf-8 -*-
"""Mekânların GERÇEK fotoğraflarını toplar -> data/foto.json + static/img/mekan/*.webp

Üç kademe, sırayla; fotoğrafı olmayan mekân bir sonraki kademeye düşer:
  1. Wikipedia (tr) madde ön görseli — kesin ad eşleşmesi, serbest lisans
  2. Wikimedia Commons — dosya adı araması + koordinata göre 300 m geosearch
  3. Google Places — build/.places.key varsa (git'e girmez); Find Place → Details → Photo

İlke: stok/uydurma fotoğraf YOK. Eşleşme belirsizse foto konmaz, sayfa emoji
kapakla kalır. Yazar + lisans + kaynak saklanır ve sayfada künye gösterilir.
Google fotoğraflarında html_attributions olduğu gibi gösterilir.

Kullanım:
  python build/foto.py                 # üç kademe (Google, anahtar varsa)
  python build/foto.py --sadece-google # yalnız 3. kademe (anahtar sonradan geldiğinde)
  python build/foto.py --yenile        # foto.json'u sıfırdan kur
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
IMG = KOK / "static" / "img" / "mekan"
HEDEF = KOK / "data" / "foto.json"
ANAHTAR = KOK / "build" / ".places.key"
UA = {"User-Agent": "istanbuldacocuk.com/1.0 (https://istanbuldacocuk.com; merhaba@istanbuldacocuk.com)"}
BOYUTLAR = {"lg": (1200, 675), "sm": (640, 360)}
KALITE = 72
TABAN_KALITE = 48
# Kapak görseli LCP öğesi; 3G'de 300 KB'lık bir kapak sayfayı saniyelerce bekletiyor.
BUTCE = {"lg": 150_000, "sm": 45_000}
IST_BIAS = "circle:40000@41.02,28.98"
LOGO_RE = re.compile(r"logo|seal|amblem|emblem|arma|coat|flag|bayrak|_map|harita|icon|afi[sş]|"
                     r"poster|banner|plan|kroki|tabela", re.I)
TR = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛI", "cgiosuaiucgiosuaiui")
STOP = {"ve", "ile", "istanbul", "ibb", "cocuk", "cocuklar", "muzesi", "muze", "parki",
        "park", "merkezi", "merkez", "the", "tarihi", "kir", "kafe", "cafe", "korusu", "koru",
        "bahcesi", "eski", "yeni", "buyuk", "kucuk", "sahnesi", "sahne", "tesisi", "tesis",
        "sosyal", "kutuphanesi", "kutuphane", "kent", "ormani", "orman", "alani", "mesire",
        "etap", "hatira", "sehir", "sehitler", "kultur"}

sys.path.insert(0, str(KOK / "build"))
from derle import slugify  # noqa: E402


def _norm(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", (s or "").translate(TR).lower()).encode("ascii", "ignore").decode()
    return {t for t in re.findall(r"[a-z0-9]+", s) if len(t) > 2} - STOP


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)


def _indir(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def _temiz(h) -> str:
    if not h:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", urllib.parse.unquote(str(h)))).strip()


def _cekirdek(ad: str) -> str:
    return re.split(r"[(–\-/]", ad)[0].strip()


# Mekân adındaki tür sözcükleri: madde ile mekân aynı tür ailesinden olmalı.
# "Cebeci Parkı" için "Cebeci Plajı" (Kandıra'da), "Toprak Dede Hayrettin Karaca Parkı"
# için "Hayrettin Karaca" (kişi maddesi, fotoğraf Yalova'daki heykel) kabul edilmişti.
TUR_AILE = {
    "yesil": {"park", "parki", "koru", "korusu", "orman", "ormani", "mesire", "bahce", "bahcesi",
              "tepe", "tepesi", "fidanlik", "fidanligi", "golet", "goleti", "sahil", "millet",
              "vadi", "vadisi", "yasam"},
    "kutuphane": {"kutuphane", "kutuphanesi", "kitaplik", "kitapligi", "library"},
    "muze": {"muze", "muzesi", "galeri", "galerisi", "museum", "sarnic", "sarnici",
             "cistern", "saray", "sarayi", "palace", "hisar", "hisari", "kule", "kulesi"},
    "sahne": {"sahne", "sahnesi", "tiyatro", "tiyatrosu", "gazhane", "stage", "theatre", "theater"},
    "merkez": {"merkez", "merkezi", "salonu", "evi", "center", "centre"},
    "tesis": {"tesis", "tesisi", "kosk", "kosku", "kahvesi", "facility"},
    "plaj": {"plaj", "plaji", "beach"},
}
for _a in ("park", "parki", "garden", "forest", "grove"):
    TUR_AILE["yesil"].add(_a)


def _tur_aile(metin: str) -> set[str]:
    ham = unicodedata.normalize("NFKD", (metin or "").translate(TR).lower()).encode("ascii", "ignore").decode()
    tok = set(re.findall(r"[a-z]+", ham))
    return {aile for aile, kelimeler in TUR_AILE.items() if tok & kelimeler}


def baslik_uygun(mekan_ad: str, madde: str) -> bool:
    """Wikipedia maddesi gerçekten bu MEKÂNI mı anlatıyor, yoksa semti/ilçeyi/kişiyi mi?

    Reddedilenler: virgüllü semt maddesi ("Çırpıcı, Zeytinburnu"); tek kelimelik yer
    maddesi ("Beykoz", "Emirgan" — fotoğrafı kasabanın); tür ailesi uyuşmayan madde
    (plaj ≠ park); tür sözcüğü hiç olmayan ve mekân adını kapsamayan madde (kişi).
    """
    if "," in madde:
        return False
    vtok, ptok = _norm(mekan_ad), _norm(madde)
    if not _eslesir(vtok, ptok):
        return False
    v_aile, p_aile = _tur_aile(mekan_ad), _tur_aile(madde)
    if v_aile and not p_aile:
        # "X Kütüphanesi" ile eşleşen "X" maddesi kütüphaneyi değil X'i anlatıyor.
        # Kütüphaneler kişi adı taşıdığı için bu dal portre getiriyordu (Ahmet Kabaklı
        # Kütüphanesi ← kişinin fotoğrafı, Evliya Çelebi Kütüphanesi ← Seyahatname sayfası).
        return False
    if not p_aile:
        return len(ptok) >= 2 and ptok >= vtok
    # Madde adı mekân adının üstüne ayırt edici bir sözcük ekliyorsa başka bir varlıktır:
    # "İstanbul Sanat Müzesi" ← "İstanbul ÇAĞDAŞ Sanat Müzesi" (ayrı, özel bir müze).
    # Bu yalnız madde BAŞLIKLARI için geçerli; Commons dosya adlarında fazladan sözcük
    # betimlemedir ("Troleybus Garage Library Istanbul").
    tur_sozcukleri = {k for aile in TUR_AILE.values() for k in aile}
    fazla = {t for t in (ptok - vtok) if len(t) >= 4 and not t.isdigit()} - tur_sozcukleri
    if fazla and len(vtok) <= 2:
        return False
    return bool(v_aile & p_aile) if v_aile else True


GENEL_FOTO_RE = re.compile(r"panoramio|metrob|istasyon|iskele|otogar|stadyum|camii|cami\b|kilise|"
                           r"hisar|kale|koprü|kopru|bridge|mosque|station|street|sokak|caddesi", re.I)


def dosya_uygun(mekan_ad: str, dosya: str) -> bool:
    """Commons dosyası gerçekten bu mekânı mı gösteriyor?

    "X Sosyal Tesisi" gibi adlarda ayırt edici tek token yer adıdır; o yerin her fotoğrafı
    eşleşir (Küçükçekmece Sosyal Tesisi ← Metrobüs İstasyonu, Kasımpaşa ← İskele). Kural:
    tek ayırt edici token varsa dosya adında mekânla AYNI tür ailesinden bir sözcük olmalı;
    tür ailesi çelişiyorsa (tesis ← koru fotoğrafı) red; genel manzara/ulaşım sözcükleri red.
    """
    vtok, ptok = _norm(mekan_ad), _norm(dosya)
    if not _eslesir(vtok, ptok):
        return False
    if GENEL_FOTO_RE.search(dosya) and not GENEL_FOTO_RE.search(mekan_ad):
        return False
    v_aile, p_aile = _tur_aile(mekan_ad), _tur_aile(dosya)
    if v_aile and not (v_aile & p_aile):
        return False
    if len(vtok) == 1 and not (v_aile & p_aile):
        return False
    return True


def _eslesir(vtok: set[str], ptok: set[str]) -> bool:
    """Katı eşleşme: en az bir uzun ortak token + kapsama ya da ≥2 ortak."""
    ortak = vtok & ptok
    return bool(ortak) and any(len(t) >= 5 for t in ortak) and (
        ptok <= vtok or vtok <= ptok or len(ortak) >= 2)


def _lisans(meta: dict) -> dict | None:
    m = lambda k: _temiz((meta.get(k) or {}).get("value"))
    lisans = m("LicenseShortName") or "Wikimedia Commons"
    if "all rights" in lisans.lower():
        return None
    if meta.get("Copyrighted", {}).get("value") == "True" and not m("LicenseUrl"):
        return None
    return {"yazar": m("Artist") or "Bilinmiyor", "lisans": lisans, "lisans_url": m("LicenseUrl")}


# ------------------------------------------------------------------ 1. Wikipedia
def wiki_bul(m: dict) -> dict | None:
    vtok = _norm(m["ad"])
    if not vtok:
        return None
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrsearch": _cekirdek(m["ad"]) + " İstanbul", "gsrlimit": "4",
        "gsrnamespace": "0", "prop": "pageimages|info", "piprop": "original|name",
        "pilicense": "free", "inprop": "url"})
    try:
        pages = _get("https://tr.wikipedia.org/w/api.php?" + q).get("query", {}).get("pages", [])
    except Exception:
        return None
    for p in sorted(pages, key=lambda p: p.get("index", 99)):
        baslik = p.get("title", "")
        if "(anlam ayrımı)" in baslik or not (p.get("original") or {}).get("source"):
            continue
        if not baslik_uygun(m["ad"], baslik):
            continue
        dosya = p.get("pageimage")
        # PNG: Commons'ta gerçek fotoğraf neredeyse hep JPG'dir; PNG logo/amblem/şema
        # oluyor (Büyükdere Atatürk Fidanlığı'na kurumun siyah zeminli logosu gelmişti).
        if not dosya or LOGO_RE.search(dosya) or dosya.lower().endswith(".png"):
            continue
        q2 = urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2",
            "titles": f"File:{dosya}", "prop": "imageinfo",
            "iiprop": "extmetadata|url", "iiurlwidth": "1600"})
        try:
            bilgi = _get("https://commons.wikimedia.org/w/api.php?" + q2)["query"]["pages"][0]
        except Exception:
            continue
        ii = (bilgi.get("imageinfo") or [{}])[0]
        lis = _lisans(ii.get("extmetadata") or {})
        if not lis:
            continue
        return {"indir": ii.get("thumburl") or p["original"]["source"], "wiki": baslik,
                "kaynak": "wikipedia",
                "sayfa": ii.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/File:{dosya}",
                **lis}
    return None


# ------------------------------------------------------------------ 2. Commons
COMMONS = "https://commons.wikimedia.org/w/api.php?"


def _commons_uygun(p: dict, vtok_ad: str) -> dict | None:
    vtok = _norm(vtok_ad)
    title = p.get("title", "")
    dosya = title.split("File:")[-1]
    if LOGO_RE.search(dosya) or dosya.lower().rsplit(".", 1)[-1] in ("svg", "pdf", "gif", "tif", "tiff", "png"):
        return None
    ii = (p.get("imageinfo") or [{}])[0]
    if not str(ii.get("mime", "")).startswith("image/"):
        return None
    if not dosya_uygun(vtok_ad, dosya):
        return None
    lis = _lisans(ii.get("extmetadata") or {})
    if not lis:
        return None
    return {"indir": ii.get("thumburl") or ii.get("url"), "wiki": dosya, "kaynak": "commons",
            "sayfa": ii.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{title}", **lis}


def commons_bul(m: dict) -> dict | None:
    vtok = _norm(m["ad"])
    if not vtok:
        return None
    ortak = {"prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": "1600",
             "action": "query", "format": "json", "formatversion": "2"}
    q = urllib.parse.urlencode({**ortak, "generator": "search", "gsrnamespace": "6",
                                "gsrsearch": _cekirdek(m["ad"]) + " İstanbul", "gsrlimit": "6"})
    try:
        pages = _get(COMMONS + q).get("query", {}).get("pages", [])
    except Exception:
        pages = []
    for p in sorted(pages, key=lambda p: p.get("index", 99)):
        r = _commons_uygun(p, m["ad"])
        if r:
            return r
    if m.get("lat") and m.get("lng"):
        q2 = urllib.parse.urlencode({**ortak, "generator": "geosearch", "ggsnamespace": "6",
                                     "ggscoord": f"{m['lat']}|{m['lng']}", "ggsradius": "300",
                                     "ggslimit": "12"})
        try:
            pages2 = _get(COMMONS + q2).get("query", {}).get("pages", [])
        except Exception:
            pages2 = []
        for p in pages2:
            r = _commons_uygun(p, m["ad"])
            if r:
                return r
    return None


# ------------------------------------------------------------------ 3. Google Places
BASE = "https://maps.googleapis.com/maps/api/place/"


def _gjson(anahtar: str, yol: str, par: dict) -> dict:
    par["key"] = anahtar
    with urllib.request.urlopen(urllib.request.Request(BASE + yol + "?" + urllib.parse.urlencode(par),
                                                       headers=UA), timeout=40) as r:
        return json.load(r)


def places_cek(m: dict, anahtar: str) -> tuple[dict | None, str]:
    par = {"input": f"{_cekirdek(m['ad'])} {m['ilce']} İstanbul", "inputtype": "textquery",
           "fields": "place_id,name",
           "locationbias": f"point:{m['lat']},{m['lng']}" if m.get("lat") else IST_BIAS}
    d = _gjson(anahtar, "findplacefromtext/json", par)
    if d.get("status") != "OK" or not d.get("candidates"):
        return None, d.get("status", "?")
    c = d["candidates"][0]
    ortak = _norm(m["ad"]) & _norm(c.get("name", ""))
    if not any(len(t) >= 4 for t in ortak):
        return None, f"AD-UYUŞMAZ({c.get('name', '')[:24]})"
    dd = _gjson(anahtar, "details/json", {"place_id": c["place_id"], "fields": "name,photos,url"})
    if dd.get("status") != "OK":
        return None, "DETAILS-" + dd.get("status", "?")
    res = dd.get("result", {})
    fotolar = res.get("photos") or []
    manzara = [p for p in fotolar if p.get("width", 0) >= p.get("height", 1) * 1.2]
    p = (manzara or fotolar or [None])[0]
    if not p:
        return None, "FOTO-YOK"
    attr = re.sub("<[^>]+>", "", (p.get("html_attributions") or ["Google"])[0]).strip() or "Google"
    q = urllib.parse.urlencode({"maxwidth": "1600", "photo_reference": p["photo_reference"], "key": anahtar})
    ham = _indir(BASE + "photo?" + q)
    if not (ham[:3] == b"\xff\xd8\xff" or ham[:4] == b"\x89PNG" or ham[:4] == b"RIFF"):
        return None, "GÖRSEL-DEĞİL"
    return {"ham": ham, "yazar": attr, "lisans": "Google", "lisans_url": "",
            "sayfa": res.get("url") or "", "kaynak": "google", "wiki": ""}, "OK"


# ------------------------------------------------------------------ kaydetme
def dosya_tekille(sonuc: dict, at) -> int:
    """Aynı Commons dosyasını iki mekân kullanıyorsa ikisini de at.

    Hangisinin doğru olduğunu bilemeyiz: Büyük ve Küçük Çamlıca Korusu (4,7 km uzakta
    iki ayrı tepe) aynı "Çamlıca_Tepesi.jpg"yi almıştı. Yanlış olanı yayımlamaktansa
    ikisini de boş bırakmak doğru.
    """
    sayfalar: dict[str, list[str]] = {}
    for ad, v in sonuc.items():
        if v and v.get("sayfa"):
            sayfalar.setdefault(v["sayfa"], []).append(ad)
    n = 0
    for adlar in sayfalar.values():
        if len(adlar) > 1:
            for ad in adlar:
                at(ad, sonuc[ad], "aynı dosya")
                n += 1
    return n


def kirp_kaydet(veri: bytes, ad_slug: str) -> dict:
    im = Image.open(io.BytesIO(veri))
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    g, y = im.size
    istenen = 16 / 9
    if g / y > istenen:
        yg = int(y * istenen)
        sol = (g - yg) // 2
        im = im.crop((sol, 0, sol + yg, y))
    else:
        yy = int(g / istenen)
        ust = int((y - yy) * 0.32)
        im = im.crop((0, ust, g, ust + yy))
    out = {}
    for et, (bg, by) in BOYUTLAR.items():
        yol = IMG / f"{ad_slug}-{et}.webp"
        # Kaynaktan büyütme yok: 1200'e şişirilen küçük görsel hem bulanık oluyor
        # hem de dosyayı büyütüyor. Oran zaten 16:9'a kırpıldı.
        if im.width < bg:
            bg, by = im.width, im.height
        kucuk = im.resize((bg, by), Image.LANCZOS)
        # Yoğun yapraklı park fotoğrafları sabit kalitede 300 KB'ı geçiyordu.
        # Bütçeye inene kadar kaliteyi düşür; taban kaliteden aşağı inme.
        for kalite in range(KALITE, TABAN_KALITE - 1, -6):
            kucuk.save(yol, "WEBP", quality=kalite, method=6)
            if yol.stat().st_size <= BUTCE[et]:
                break
        out[et] = yol.name
    return out


def main() -> int:
    sadece_google = "--sadece-google" in sys.argv
    yenile = "--yenile" in sys.argv
    mekanlar = json.loads((KOK / "data" / "mekanlar.json").read_text("utf-8"))
    IMG.mkdir(parents=True, exist_ok=True)
    sonuc = {} if yenile or not HEDEF.exists() else json.loads(HEDEF.read_text("utf-8"))

    # Eşleştirici sıkılaştığında eski kayıtlar yeni kurala göre yeniden doğrulanır;
    # geçemeyenin dosyaları silinir ve mekân yeniden (Commons/Google) denenir.
    if "--yeniden-dogrula" in sys.argv:
        atilan = 0
        def at(ad, v, neden):
            for et in ("lg", "sm"):
                (IMG / v[et]).unlink(missing_ok=True)
            sonuc[ad] = None
            print(f"  ✗ atıldı: {ad[:36]:38} ({neden}: {v.get('wiki','')[:30]})")

        for ad, v in list(sonuc.items()):
            if not v:
                continue
            if v.get("kaynak") == "google":
                continue
            if v.get("kaynak") == "wikipedia" and not baslik_uygun(ad, v.get("wiki", "")):
                at(ad, v, "madde"); atilan += 1
            elif v.get("kaynak") == "commons" and not dosya_uygun(ad, v.get("wiki", "")):
                at(ad, v, "dosya"); atilan += 1
        atilan += dosya_tekille(sonuc, at)
        print(f"yeniden doğrulama: {atilan} kayıt atıldı")
        print()
        # Reddedilen mekânlar aşağıda 'None' olduğu için yeniden denenecek.
        for ad in [a for a, v in sonuc.items() if v is None]:
            del sonuc[ad]
    anahtar = ANAHTAR.read_text().strip() if ANAHTAR.exists() else ""

    def kaydet():
        HEDEF.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), "utf-8")

    sayac = {"wikipedia": 0, "commons": 0, "google": 0}
    if not sadece_google:
        for i, m in enumerate(mekanlar, 1):
            ad = m["ad"]
            if ad in sonuc and sonuc[ad]:
                continue
            g = None
            try:
                g = wiki_bul(m) or commons_bul(m)
                if g:
                    ham = _indir(g.pop("indir"))
                    sonuc[ad] = {**g, **kirp_kaydet(ham, slugify(ad))}
                    sayac[g["kaynak"]] += 1
                    print(f"{i:3}/{len(mekanlar)} ✓ {ad[:38]:38} <- {g['wiki'][:30]} [{g['lisans'][:14]}]")
                else:
                    sonuc.setdefault(ad, None)
            except Exception as ex:
                sonuc.setdefault(ad, None)
                print(f"{i:3}/{len(mekanlar)} ! {ad[:38]} {type(ex).__name__}")
            if i % 10 == 0:
                kaydet()
            time.sleep(0.3)
        def _at(ad, v, neden):
            for et in ("lg", "sm"):
                (IMG / v[et]).unlink(missing_ok=True)
            sonuc[ad] = None
            print(f"  x atildi: {ad[:36]:38} ({neden}: {v.get('wiki', '')[:30]})")
        # Getirme döngüsü yeni çiftler yaratmış olabilir; tekilleme burada da çalışır.
        dosya_tekille(sonuc, _at)
        kaydet()
        print(f"\nWikipedia {sayac['wikipedia']} + Commons {sayac['commons']} = "
              f"{sum(1 for v in sonuc.values() if v)}/{len(mekanlar)} gerçek foto")

    if not anahtar:
        print("\nGoogle Places kademesi atlandı: build/.places.key yok.")
        return 0
    hedefler = [m for m in mekanlar if not sonuc.get(m["ad"])]
    print(f"\nGoogle Places: fotoğrafı olmayan {len(hedefler)} mekân denenecek")
    for i, m in enumerate(hedefler, 1):
        ad = m["ad"]
        try:
            g, durum = places_cek(m, anahtar)
            if not g:
                print(f"{i:3}/{len(hedefler)} - {ad[:38]:38} [{durum}]")
                continue
            sonuc[ad] = {**g, **kirp_kaydet(g.pop("ham"), slugify(ad))}
            sayac["google"] += 1
            print(f"{i:3}/{len(hedefler)} ✓ {ad[:38]:38} <- {g['yazar'][:26]}")
        except Exception as ex:
            print(f"{i:3}/{len(hedefler)} ! {ad[:38]} {type(ex).__name__}: {str(ex)[:40]}")
        if i % 10 == 0:
            kaydet()
        time.sleep(0.12)
    def _at2(ad, v, neden):
        for et in ("lg", "sm"):
            (IMG / v[et]).unlink(missing_ok=True)
        sonuc[ad] = None
        print(f"  x atildi: {ad[:36]:38} ({neden}: {v.get('wiki', '')[:30]})")
    # Google kademesi de yeni çift yaratabilir; son bir tekilleme.
    dosya_tekille(sonuc, _at2)
    kaydet()
    print(f"\nGoogle +{sayac['google']}. Toplam gerçek foto: "
          f"{sum(1 for v in sonuc.values() if v)}/{len(mekanlar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
