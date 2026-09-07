# -*- coding: utf-8 -*-
"""Mekânların GERÇEK fotoğraflarını toplar -> data/foto.json + static/img/mekan/*.webp

Üç kademe, sırayla; fotoğrafı olmayan mekân bir sonraki kademeye düşer:
  1. Wikipedia (tr) madde ön görseli — kesin ad eşleşmesi, serbest lisans
  2. Wikimedia Commons — dosya adı araması + koordinata göre 300 m geosearch
  3. Google **Places API (New)** — build/.places.key varsa (git'e girmez);
     places:searchText → photos[].name → /media. Eski `maps.googleapis.com`
     uçları yeni projelerde kapalı ("legacy API ... not enabled").

İlke: stok/uydurma fotoğraf YOK. Eşleşme belirsizse foto konmaz, sayfa emoji
kapakla kalır. Yazar + lisans + kaynak saklanır ve sayfada künye gösterilir.
Google fotoğraflarında authorAttributions'taki isim künyeye yazılır (zorunlu).

Kullanım:
  python build/foto.py                 # üç kademe (Google, anahtar varsa)
  python build/foto.py --sadece-google # yalnız 3. kademe (anahtar sonradan geldiğinde)
  python build/foto.py --yenile        # foto.json'u sıfırdan kur
"""
from __future__ import annotations

import io
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
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
# 16:9'a kırpıldıktan sonraki en küçük kabul edilebilir kaynak genişliği.
EN_AZ_GENISLIK = 900
# Kapak görseli LCP öğesi; 3G'de 300 KB'lık bir kapak sayfayı saniyelerce bekletiyor.
BUTCE = {"lg": 150_000, "sm": 45_000, "og": 110_000}
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


# ------------------------------------------------------------------ 3. Google Places (New)
# Eski (legacy) `maps.googleapis.com/maps/api/place/*` uçları yeni projelerde
# kapalı: "You're calling a legacy API, which is not enabled for your project."
# Places API (New) tek çağrıda arama + fotoğraf üstverisi veriyor; alanlar
# X-Goog-FieldMask ile açıkça isteniyor (istenmeyen alan faturaya girmiyor).
YENI_BASE = "https://places.googleapis.com/v1/"
ARAMA_ALANLARI = ("places.id,places.displayName,places.formattedAddress,"
                  "places.location,places.googleMapsUri,places.photos")


def _gpost(anahtar: str, yol: str, govde: dict, alanlar: str) -> dict:
    istek = urllib.request.Request(
        YENI_BASE + yol, data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": anahtar,
                 "X-Goog-FieldMask": alanlar, **UA})
    with urllib.request.urlopen(istek, timeout=40) as r:
        return json.load(r)


def _gyazar(foto: dict) -> str:
    """Fotoğrafın kime ait olduğu. Google, künye gösterimini şart koşuyor."""
    for a in foto.get("authorAttributions") or []:
        if a.get("displayName"):
            return a["displayName"]
    return "Google Haritalar kullanıcısı"


def places_cek(m: dict, anahtar: str) -> tuple[dict | None, str]:
    govde: dict = {"textQuery": f"{_cekirdek(m['ad'])} {m['ilce']} İstanbul",
                   "languageCode": "tr", "maxResultCount": 3}
    if m.get("lat") and m.get("lng"):
        govde["locationBias"] = {"circle": {"center": {"latitude": m["lat"],
                                                       "longitude": m["lng"]},
                                            "radius": 3000.0}}
    else:
        govde["locationBias"] = {"circle": {"center": {"latitude": 41.02, "longitude": 28.98},
                                            "radius": 40000.0}}
    try:
        d = _gpost(anahtar, "places:searchText", govde, ARAMA_ALANLARI)
    except urllib.error.HTTPError as e:
        try:
            ileti = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            ileti = ""
        return None, f"HTTP{e.code}-{ileti[:60]}"
    yerler = d.get("places") or []
    if not yerler:
        return None, "SONUÇ-YOK"

    # Ad denetimi Commons kademesindekiyle aynı ilkede: ortak ayırt edici sözcük
    # yoksa başka bir işletmenin fotoğrafını koymaktansa boş bırak.
    tur_sozcukleri = {k for aile in TUR_AILE.values() for k in aile}
    vtok = _norm(m["ad"])
    nedenler: list[str] = []
    for c in yerler:
        gad = (c.get("displayName") or {}).get("text", "")
        gtok = _norm(gad)
        if not any(len(t) >= 4 for t in vtok & gtok):
            nedenler.append(f"AD-UYUŞMAZ({gad[:22]})")
            continue
        # Google, mekânın İÇİNDEKİ başka bir noktayı döndürebiliyor: "15 Temmuz Kent
        # Ormanı 3. Etap" için "… Şehir Tuvaleti". Ayırt edici sözcüklerin hepsi STOP
        # listesinde olduğundan ortak token sınavını geçiyordu. Kural baslik_uygun'daki
        # ile aynı: mekân adında olmayan ayırt edici sözcük eklenmişse başka bir varlıktır.
        fazla = {t for t in (gtok - vtok) if len(t) >= 4 and not t.isdigit()} - tur_sozcukleri
        if fazla and len(vtok) <= 2:
            nedenler.append(f"BAŞKA-YER({gad[:22]})")
            continue
        fotolar = c.get("photos") or []
        manzara = [p for p in fotolar if p.get("widthPx", 0) >= p.get("heightPx", 1) * 1.2]
        p = next(iter(manzara or fotolar), None)
        if not p:
            nedenler.append("FOTO-YOK")
            continue
        # skipHttpRedirect: yönlendirme yerine photoUri'yi JSON olarak verir.
        url = (YENI_BASE + p["name"] + "/media?maxWidthPx=1600&skipHttpRedirect=true"
               + "&key=" + urllib.parse.quote(anahtar))
        try:
            uri = _get(url).get("photoUri")
            ham = _indir(uri) if uri else b""
        except Exception as e:  # noqa: BLE001
            return None, f"FOTO-HATA-{str(e)[:30]}"
        if not (ham[:3] == b"\xff\xd8\xff" or ham[:4] == b"\x89PNG" or ham[:4] == b"RIFF"):
            return None, "GÖRSEL-DEĞİL"
        # `wiki` alanı eşleşmenin KAYNAK ADI: Wikipedia kademesinde madde adı,
        # burada Google'ın döndürdüğü işletme adı. Sonradan "hangi mekân neye
        # eşleşmiş" diye denetlemenin tek yolu bu.
        return {"ham": ham, "yazar": _gyazar(p), "lisans": "Google", "lisans_url": "",
                "sayfa": c.get("googleMapsUri") or "", "kaynak": "google", "wiki": gad}, "OK"
    # Her adayın kendi elenme nedeni raporlanır: hepsini "AD-UYUŞMAZ" saymak,
    # adı doğru ama fotoğrafı olmayan mekânları yanlış teşhis ediyordu.
    return None, " | ".join(dict.fromkeys(nedenler)) or "ADAY-YOK"


# ------------------------------------------------------------------ kaydetme
def _km(a: dict, b: dict) -> float:
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def ayni_yer(a: str, b: str, mekanlar: dict) -> bool:
    """İki kayıt fiziksel olarak aynı yerin birimleri mi?

    Koordinat varsa mesafe karar verir. Yoksa ada bakılır: ayırt edici sözcükler
    biri diğerini kapsıyorsa aynı binanın iki birimidir ("Turhan Selçuk
    Kütüphanesi" / "Turhan Selçuk Müzesi", "Habitat Sanat" / "Habitat Yaşam
    Merkezi"). Ayırt edici sözcükler farklıysa iki ayrı yerdir ("Belgradkapı" /
    "Mevlanakapı Kara Surları Ziyaretçi Merkezi").
    """
    A, B = mekanlar.get(a), mekanlar.get(b)
    if A and B and A.get("lat") and B.get("lat"):
        return _km(A, B) <= 0.2
    ta, tb = _norm(a), _norm(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta)


def dosya_tekille(sonuc: dict, at, mekanlar: dict) -> int:
    """Aynı görseli iki AYRI yer kullanıyorsa ikisini de at.

    Commons kademesinde bu hep hataydı: Büyük ve Küçük Çamlıca Korusu (1 km
    arayla iki ayrı tepe) aynı "Çamlıca_Tepesi.jpg"yi almıştı; hangisinin doğru
    olduğu bilinemez, ikisini de boş bırakmak doğru.

    Google kademesinde ise aynı kaydı paylaşmak çoğu zaman HATA DEĞİL: aynı
    binadaki kütüphane ile müzenin tek bir Google işletme kaydı var. Kör
    tekilleme 20 kaydın 16'sını haksız yere atıyordu. Bu yüzden önce mekânların
    gerçekten ayrı yerler olup olmadığına bakılıyor.
    """
    sayfalar: dict[str, list[str]] = {}
    for ad, v in sonuc.items():
        if v and v.get("sayfa"):
            sayfalar.setdefault(v["sayfa"], []).append(ad)
    n = 0
    for adlar in sayfalar.values():
        if len(adlar) < 2:
            continue
        # Grubun tamamı aynı yerin birimleriyse foto hepsinde doğru; bırak.
        if all(ayni_yer(a, b, mekanlar)
               for i, a in enumerate(adlar) for b in adlar[i + 1:]):
            continue
        for ad in adlar:
            at(ad, sonuc[ad], "ayrı yerler aynı görseli aldı")
            n += 1
    return n


def kirp_kaydet(veri: bytes, ad_slug: str) -> dict | None:
    """Kapak görsellerini üretir. Kaynak çok küçükse None döner (foto konmaz)."""
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
    # Kapak masaüstünde 1120 piksel geniş basılıyor. 333 pikselik bir kaynak
    # (Gezi Parkı böyleydi) orada bulanık bir leke oluyor — emoji kapak daha iyi.
    if im.width < EN_AZ_GENISLIK:
        return None
    out: dict = {}
    for et, (bg, by) in BOYUTLAR.items():
        yol = IMG / f"{ad_slug}-{et}.webp"
        # Kaynaktan büyütme yok: 1200'e şişirilen küçük görsel hem bulanık oluyor
        # hem de dosyayı büyütüyor. Oran zaten 16:9'a kırpıldı.
        if im.width < bg:
            bg, by = im.width, im.height
        out[f"{et}_en"], out[f"{et}_boy"] = bg, by
        kucuk = im.resize((bg, by), Image.LANCZOS)
        # Yoğun yapraklı park fotoğrafları sabit kalitede 300 KB'ı geçiyordu.
        # Bütçeye inene kadar kaliteyi düşür; taban kaliteden aşağı inme.
        for kalite in range(KALITE, TABAN_KALITE - 1, -6):
            kucuk.save(yol, "WEBP", quality=kalite, method=6)
            if yol.stat().st_size <= BUTCE[et]:
                break
        out[et] = yol.name
    # Paylaşım kartı için JPEG kopya: X ve WhatsApp WebP og:image'ı güvenilir
    # biçimde basmıyor, kart boş çıkıyor. Sayfada HİÇ gösterilmiyor, yalnız sosyal
    # medya tarayıcısı çekiyor — bu yüzden kapaktan daha sıkı bir bütçesi var.
    # Bütçesiz haliyle ortalama 187 KB'tı; 280 mekânda 52 MB ölü ağırlık demek.
    og = IMG / f"{ad_slug}-og.jpg"
    ogim = im.resize(BOYUTLAR["lg"], Image.LANCZOS).convert("RGB")
    for kalite in (78, 70, 62, 54):
        ogim.save(og, "JPEG", quality=kalite, optimize=True, progressive=True)
        if og.stat().st_size <= BUTCE["og"]:
            break
    out["og"] = og.name
    return out


def main() -> int:
    sadece_google = "--sadece-google" in sys.argv
    yenile = "--yenile" in sys.argv
    mekanlar = json.loads((KOK / "data" / "mekanlar.json").read_text("utf-8"))
    mek_dizin = {m["ad"]: m for m in mekanlar}
    IMG.mkdir(parents=True, exist_ok=True)
    sonuc = {} if yenile or not HEDEF.exists() else json.loads(HEDEF.read_text("utf-8"))

    # Eşleştirici sıkılaştığında eski kayıtlar yeni kurala göre yeniden doğrulanır;
    # geçemeyenin dosyaları silinir ve mekân yeniden (Commons/Google) denenir.
    if "--yeniden-dogrula" in sys.argv:
        atilan = 0
        def at(ad, v, neden):
            for et in ("lg", "sm", "og"):
                if v.get(et):
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
        atilan += dosya_tekille(sonuc, at, mek_dizin)
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
                    boy = kirp_kaydet(ham, slugify(ad))
                    sonuc[ad] = {**g, **boy} if boy else None
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
            for et in ("lg", "sm", "og"):
                if v.get(et):
                    (IMG / v[et]).unlink(missing_ok=True)
            sonuc[ad] = None
            print(f"  x atildi: {ad[:36]:38} ({neden}: {v.get('wiki', '')[:30]})")
        # Getirme döngüsü yeni çiftler yaratmış olabilir; tekilleme burada da çalışır.
        dosya_tekille(sonuc, _at, mek_dizin)
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
            boy = kirp_kaydet(g.pop("ham"), slugify(ad))
            sonuc[ad] = {**g, **boy} if boy else None
            sayac["google"] += 1
            print(f"{i:3}/{len(hedefler)} ✓ {ad[:38]:38} <- {g['yazar'][:26]}")
        except Exception as ex:
            print(f"{i:3}/{len(hedefler)} ! {ad[:38]} {type(ex).__name__}: {str(ex)[:40]}")
        if i % 10 == 0:
            kaydet()
        time.sleep(0.12)
    def _at2(ad, v, neden):
        # og (paylaşım JPEG'i) de silinmeli; yoksa artık dosya kalıyor.
        for et in ("lg", "sm", "og"):
            if v.get(et):
                (IMG / v[et]).unlink(missing_ok=True)
        sonuc[ad] = None
        print(f"  x atildi: {ad[:36]:38} ({neden}: {v.get('wiki', '')[:30]})")
    # Google kademesi de yeni çift yaratabilir; son bir tekilleme.
    dosya_tekille(sonuc, _at2, mek_dizin)
    kaydet()
    print(f"\nGoogle +{sayac['google']}. Toplam gerçek foto: "
          f"{sum(1 for v in sonuc.values() if v)}/{len(mekanlar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
