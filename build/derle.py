# -*- coding: utf-8 -*-
"""istanbuldacocuk.com — statik site üreteci.

Girdi : data/site.json, data/mekanlar.json, data/yesil_alanlar.json,
        data/rehberler.json, data/sayfalar.json
Çıktı : dist/

Sitenin ayrışma noktası — rakiplerde olmayan üç şey:
  1. Her kayıt İBB Açık Veri Portalı'ndan, kaynak bağlantısı ve ham koordinatıyla
  2. İlçe başına TAM yeşil alan envanteri (523 park/koru, büyüklükleriyle)
  3. Görünür son doğrulama tarihi

Hiçbir alan tahminle doldurulmaz. Puan yok: mekânlar elle gezilip puanlanmadığı
sürece puan uydurmak, resmî kaydı sahte bir otoriteyle süslemek olur.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

KOK = Path(__file__).resolve().parent.parent
DATA = KOK / "data"
DIST = KOK / "dist"
STATIC = KOK / "static"
TEMPLATES = KOK / "templates"

FUTBOL_SAHASI_M2 = 7140          # 105 × 68 m, FIFA standart saha

KATEGORILER = {
    "park": {"ad": "Park, Koru ve Ormanlar", "cumle": "parklar, korular ve ormanlar",
             "tekil": "Yeşil alan", "slug": "park",
             "ikon": "🌳", "schema": "Park",
             "aciklama": "İBB'nin yeşil alan envanterindeki büyük parklar, korular, "
                         "mesire alanları ve kent ormanları. Girişleri ücretsiz."},
    "muze": {"ad": "İBB Müzeleri", "cumle": "İBB müzeleri", "tekil": "Müze", "slug": "muze",
             "ikon": "🏛", "schema": "Museum",
             "aciklama": "İstanbul Büyükşehir Belediyesi'ne bağlı müzeler; adres, "
                         "çalışma gün ve saatleriyle."},
    "kutuphane": {"ad": "İBB Kütüphaneleri", "cumle": "İBB kütüphaneleri",
                  "tekil": "Kütüphane", "slug": "kutuphane",
                  "ikon": "📚", "schema": "Library",
                  "aciklama": "İBB'ye bağlı halk kütüphaneleri. Giriş ve üyelik ücretsiz. "
                              "Çocuk bölümü olup olmadığı açık veride yer almıyor; "
                              "gitmeden önce kütüphaneyi arayın."},
    "tiyatro": {"ad": "Çocuk Tiyatrosu Sahneleri", "cumle": "çocuk tiyatrosu sahneleri",
                "tekil": "Tiyatro sahnesi",
                "slug": "cocuk-tiyatrosu", "ikon": "🎭", "schema": "PerformingArtsTheater",
                "aciklama": "İBB Şehir Tiyatroları'nın çocuk oyunu sahnelediği sahneler; "
                            "hangi sahnede kaç çocuk oyunu oynandığı açık veriden."},
    "kultur": {"ad": "Kültür Merkezleri", "cumle": "kültür merkezleri",
               "tekil": "Kültür merkezi", "slug": "kultur-merkezi",
               "ikon": "🎨", "schema": "CivicStructure",
               "aciklama": "İBB kültür merkezleri; hangisinde çocuk birimi bulunduğu "
                           "kurumun kendi verisinden."},
    "tesis": {"ad": "İBB Sosyal Tesisleri", "cumle": "İBB sosyal tesisleri",
              "tekil": "Sosyal tesis", "slug": "sosyal-tesis",
              "ikon": "☕", "schema": "LocalBusiness",
              "aciklama": "İBB'nin işlettiği sosyal tesisler; çoğu park, koru ya da "
                          "sahil içinde, aileyle oturmaya uygun."},
}

ALT_TUR = {
    "park": "Park", "koru": "Koru", "mesire": "Mesire alanı",
    "kent_ormani": "Kent ormanı", "hatira_ormani": "Hatıra ormanı",
    "muze": "Müze", "kutuphane": "Kütüphane", "kultur": "Kültür merkezi",
    "tesis": "Sosyal tesis", "tiyatro": "Tiyatro sahnesi",
}

YAKALAR = {
    "anadolu": {"ad": "Anadolu Yakası", "slug": "anadolu-yakasi",
                "aciklama": "Kadıköy'den Şile'ye, boğazın doğu kıyısındaki 14 ilçe."},
    "avrupa": {"ad": "Avrupa Yakası", "slug": "avrupa-yakasi",
               "aciklama": "Fatih'ten Silivri'ye, boğazın batı kıyısındaki 25 ilçe."},
}

TR_ASCII = str.maketrans("çğıöşüâîÇĞİÖŞÜÂÎI", "cgiosuaicgiosuaii")


SESLI = "aeıioöuü"
KALIN = "aıou"
SERT = "fstkçşhp"          # sert ünsüzden sonra ek sertleşir: Fatih'te, Pendik'te
# Üçüncü tekil iyelik ekiyle biten ilçe adları kaynaştırma 'n'si ister:
# "Beyoğlu'nda", "Beyoğlu'de" değil. Bu üç ad dışında İstanbul'da örneği yok.
IYELIK_ILCE = {"Beyoğlu", "Zeytinburnu", "Beylikdüzü"}


def _son_sesli(ad: str) -> str:
    for h in reversed(ad.replace("I", "ı").replace("İ", "i").lower()):
        if h in SESLI:
            return h
    return "e"


def bulunma(ad: str, ek: str = "") -> str:
    """İlçe adına bulunma hâli eki: Kadıköy'de, Fatih'te, Beyoğlu'nda, Üsküdar'da."""
    kalin = _son_sesli(ad) in KALIN
    if ad in IYELIK_ILCE:
        return f"{ad}'n{'da' if kalin else 'de'}{ek}"
    sert = ad[-1].replace("I", "ı").replace("İ", "i").lower() in SERT
    if sert:
        return f"{ad}'{'ta' if kalin else 'te'}{ek}"
    return f"{ad}'{'da' if kalin else 'de'}{ek}"


def tamlayan(ad: str) -> str:
    """İlgi hâli: Fatih'in, Kadıköy'ün, Beyoğlu'nun, Şile'nin."""
    s = _son_sesli(ad)
    ek = {"a": "ın", "ı": "ın", "e": "in", "i": "in",
          "o": "un", "u": "un", "ö": "ün", "ü": "ün"}[s]
    sesliyle_biter = ad[-1].replace("I", "ı").replace("İ", "i").lower() in SESLI
    return f"{ad}'{'n' if sesliyle_biter else ''}{ek}"


def slugify(metin: str) -> str:
    metin = unicodedata.normalize("NFKD", (metin or "").translate(TR_ASCII))
    metin = metin.encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", metin)).strip("-")


def yukle(ad: str, varsayilan=None):
    yol = DATA / ad
    if not yol.exists():
        if varsayilan is None:
            sys.exit(f"Eksik veri dosyası: {yol}")
        return varsayilan
    return json.loads(yol.read_text(encoding="utf-8"))


def km(a_lat, a_lng, b_lat, b_lng) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def kisalt(metin: str, en: int = 158) -> str:
    metin = " ".join((metin or "").split())
    if len(metin) <= en:
        return metin
    kesik = metin[:en]
    bosluk = kesik.rfind(" ")
    return (kesik[:bosluk] if bosluk > en * 0.6 else kesik).rstrip(" ,.;:") + "…"


def dokum(mekanlar: list[dict]) -> list[tuple[str, int]]:
    """[('kütüphane', 4), ('müze', 2)] — ilçe sayfası giriş metni için tür dökümü."""
    sayim: dict[str, int] = {}
    for m in mekanlar:
        ad = KATEGORILER[m["kategori"]]["tekil"].lower()
        sayim[ad] = sayim.get(ad, 0) + 1
    return sorted(sayim.items(), key=lambda t: -t[1])


def binlik(n) -> str:
    return f"{n:,.0f}".replace(",", ".") if n else ""


def alan_yazi(m2) -> str:
    """Metrekareyi okunur hale getirir: 428.026 m² (yaklaşık 60 futbol sahası)."""
    if not m2:
        return ""
    metin = f"{binlik(m2)} m²"
    saha = m2 / FUTBOL_SAHASI_M2
    if saha >= 1.5:
        metin += f" (yaklaşık {saha:.0f} futbol sahası)"
    return metin


GUN_KODU = {"pazartesi": "Mo", "salı": "Tu", "çarşamba": "We", "perşembe": "Th",
            "cuma": "Fr", "cumartesi": "Sa", "pazar": "Su"}


def schema_saat(m: dict) -> str | None:
    """schema.org openingHours biçimi ("Tu-Su 10:00-18:00") ya da None.

    Ham Türkçe metin ("Salı-Pazar 10:00 - 18:00") geçersiz yapısal veridir; Google
    ayrıştıramaz. Çeviremediğimizde alanı hiç yayımlamıyoruz — yanlış işaretlemektense
    eksik bırakmak doğru.
    """
    gun, saat = (m.get("gun") or "").strip(), (m.get("saat") or "").strip()
    saat = saat.replace(" ", "")
    ss = re.fullmatch(r"(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", saat)
    if not ss:
        return None
    araligi = f"{ss.group(1)}-{ss.group(2)}"
    g = gun.lower().replace("i̇", "i")
    if not gun or re.search(r"her\s*gün", g):
        return f"Mo-Su {araligi}"
    parca = [p.strip() for p in g.split("-")]
    if len(parca) == 2 and all(p in GUN_KODU for p in parca):
        return f"{GUN_KODU[parca[0]]}-{GUN_KODU[parca[1]]} {araligi}"
    if len(parca) == 1 and parca[0] in GUN_KODU:
        return f"{GUN_KODU[parca[0]]} {araligi}"
    return None


def saat_yazi(m: dict) -> str:
    """Gün + saat. Gün alanı zaten saat içeriyorsa saati tekrarlama.

    İtfaiye Müzesi'nin gün alanı tam programı taşıyor ("Hafta içi: 09:00 - 17:00 /
    Hafta sonu: Kapalı"); saati eklemek "Hafta sonu: Kapalı 09:00 - 17:00" üretiyordu.
    """
    gun, saat = m.get("gun") or "", m.get("saat") or ""
    if gun and re.search(r"\d{1,2}[:.]\d{2}", gun):
        return gun
    return " ".join(x for x in (gun, saat) if x)


# ------------------------------------------------------------------------- hazırlama
def hazirla(mekanlar: list[dict], site: dict) -> list[dict]:
    goruldu: set[str] = set()
    for m in mekanlar:
        if m["kategori"] not in KATEGORILER:
            sys.exit(f"Bilinmeyen kategori: {m['kategori']} ({m['ad']})")
        temel = slugify(m["ad"])
        slug, m["ad_ayirt"] = temel, m["ad"]
        if slug in goruldu:
            # Aynı adda mekân var (birden çok "Cumhuriyet Parkı" gibi); ilçe ekleyerek
            # hem URL hem sayfa başlığı ayrışsın, çift başlık oluşmasın.
            m["ad_ayirt"] = f"{m['ad']} ({m['ilce']})"
            slug = slugify(f"{temel}-{m['ilce']}")
        n = 2
        while slug in goruldu:
            slug, n = f"{temel}-{n}", n + 1
        goruldu.add(slug)
        m["slug"] = slug
        m["url"] = f"/mekan/{slug}/"
        m["kat"] = KATEGORILER[m["kategori"]]
        m["tur_ad"] = ALT_TUR.get(m["tur"], m["kat"]["tekil"])
        m["ilce_slug"] = slugify(m["ilce"])
        m["yaka_bilgi"] = YAKALAR[m["yaka"]]
        m["alan_yazi"] = alan_yazi(m.get("alan_m2"))
        m["saat_yazi"] = saat_yazi(m)
        m["dogrulama"] = site["veri_tarihi"]
        if m.get("lat") is not None and m.get("koordinat_durum") != "supheli":
            m["koordinat_yazi"] = f"{m['lat']:.6f}, {m['lng']:.6f}"
            m["maps_url"] = f"https://www.google.com/maps/search/?api=1&query={m['lat']},{m['lng']}"
        else:
            m["koordinat_yazi"] = ""
            m["maps_url"] = ("https://www.google.com/maps/search/?api=1&query="
                             + re.sub(r"\s+", "+", f"{m['ad']} {m['ilce']} İstanbul"))
        m["ozet"] = ozet(m)
    mekanlar.sort(key=lambda m: (m["kategori"] != "park", -(m.get("alan_m2") or 0), m["ad"]))
    return mekanlar


def ozet(m: dict) -> str:
    """Mekân özeti — yalnızca kaynakta bulunan bilgiden kurulur."""
    k, ilce = m["kategori"], m["ilce"]
    if k == "park":
        p = f"{m['ad']}, {bulunma(ilce)} bulunan bir {m['tur_ad'].lower()}"
        if m["alan_yazi"]:
            p += f"; büyüklüğü {m['alan_yazi']}"
        p += ". İBB'nin yeşil alan envanterinde kayıtlı, girişi ücretsiz açık alan."
        return p
    if k == "kutuphane":
        p = f"{m['ad']}, {bulunma(ilce)} İBB'ye bağlı halk kütüphanesi."
        if m["saat_yazi"]:
            p += f" {m['saat_yazi']} açık."
        if m.get("acilis_yili"):
            p += f" {m['acilis_yili']} yılından beri hizmette."
        return p + " Kullanım ve üyelik ücretsiz."
    if k == "muze":
        p = f"{m['ad']}, {bulunma(ilce)} İBB'ye bağlı müze."
        if m["saat_yazi"]:
            p += f" {m['saat_yazi']} açık."
        if m.get("acilis_yili"):
            p += f" {m['acilis_yili']} yılında ziyarete açıldı."
        return p
    if k == "tiyatro":
        return (f"{m['ad']}, İBB Şehir Tiyatroları'nın {bulunma(ilce, 'ki')} sahnesi. Kurumun "
                f"{m['veri_yillari']} açık veri kayıtlarında bu sahnede "
                f"{binlik(m['cocuk_seans'])} çocuk oyunu seansı görünüyor.")
    if k == "kultur":
        p = f"{m['ad']}, {bulunma(ilce)} İBB kültür merkezi."
        if m["saat_yazi"]:
            p += f" {m['saat_yazi']} saatleri arasında açık."
        if m.get("cocuk_birimi") is True:
            p += " İBB'nin kendi verisinde bu merkezde çocuk birimi olduğu belirtiliyor."
        elif m.get("cocuk_birimi") is False:
            p += " İBB verisinde ayrı bir çocuk birimi belirtilmiyor."
        return p
    return (f"{m['ad']}, İBB'nin {bulunma(ilce, 'ki')} sosyal tesisi. "
            f"Hizmet içeriği tesise göre değişir; gitmeden önce teyit edin.")


def kisa_cevap(m: dict) -> str:
    """Sayfanın en üstündeki tek cümlelik doğrudan cevap (GEO / öne çıkan snippet)."""
    yer = f"{m['ilce']}, {m['yaka_bilgi']['ad']}"
    if m["kategori"] == "park":
        buyukluk = f"{m['alan_yazi']} büyüklüğünde " if m["alan_yazi"] else ""
        return (f"{m['ad']}, {yer}'nda {buyukluk}bir {m['tur_ad'].lower()}. "
                f"Giriş ücretsiz, açık alan.")
    if m["kategori"] == "kutuphane":
        return (f"{m['ad']}, {yer}'nda bulunan bir İBB halk kütüphanesi. "
                + (f"Açık olduğu saatler: {m['saat_yazi']}. " if m["saat_yazi"] else "")
                + "Giriş ve üyelik ücretsiz.")
    if m["kategori"] == "muze":
        return (f"{m['ad']}, {yer}'nda bulunan bir İBB müzesi."
                + (f" Açık olduğu saatler: {m['saat_yazi']}." if m["saat_yazi"] else ""))
    if m["kategori"] == "tiyatro":
        return (f"{m['ad']}, {yer}'nda bulunan bir İBB Şehir Tiyatroları sahnesi. "
                f"Kurumun {m['veri_yillari']} açık veri kayıtlarında bu sahnede "
                f"{binlik(m['cocuk_seans'])} çocuk oyunu seansı görünüyor; güncel program "
                f"için İBB Şehir Tiyatroları'nın kendi sitesine bakın.")
    if m["kategori"] == "kultur":
        return (f"{m['ad']}, {yer}'nda bulunan bir İBB kültür merkezi."
                + (" Çocuk birimi var." if m.get("cocuk_birimi") else ""))
    return f"{m['ad']}, {yer}'nda bulunan bir İBB sosyal tesisi."


# ------------------------------------------------------------------------------ şema
def kirintilar(site, *parcalar):
    ogeler = [{"@type": "ListItem", "position": 1, "name": "Ana sayfa", "item": site["url"] + "/"}]
    for i, (ad, yol) in enumerate(parcalar, start=2):
        ogeler.append({"@type": "ListItem", "position": i, "name": ad, "item": site["url"] + yol})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": ogeler}


def mekan_schema(m: dict, site: dict) -> dict:
    s = {
        "@context": "https://schema.org",
        "@type": sorted({m["kat"]["schema"], "TouristAttraction"}),
        "name": m["ad"],
        "url": site["url"] + m["url"],
        "dateModified": site["veri_tarihi"],
        "description": m["ozet"],
        "address": {"@type": "PostalAddress", "addressLocality": m["ilce"],
                    "addressRegion": "İstanbul", "addressCountry": "TR",
                    **({"streetAddress": m["adres"]} if m.get("adres") else {})},
        "publicAccess": True,
        "audience": {"@type": "PeopleAudience", "audienceType": "Çocuklu aileler"},
    }
    if m.get("ucretsiz") is not None:
        s["isAccessibleForFree"] = bool(m["ucretsiz"])
    if m["koordinat_yazi"]:
        s["geo"] = {"@type": "GeoCoordinates", "latitude": m["lat"], "longitude": m["lng"]}
        s["hasMap"] = m["maps_url"]
    if m.get("telefon"):
        s["telephone"] = m["telefon"]
    _oh = schema_saat(m)
    if _oh:
        s["openingHours"] = _oh
    if m.get("alan_m2"):
        s["additionalProperty"] = [{"@type": "PropertyValue", "name": "Alan",
                                    "value": m["alan_m2"], "unitCode": "MTK"}]
    if m.get("foto"):
        s["image"] = f"{site['url']}/static/img/mekan/{m['foto']['lg']}"
    return s


def liste_schema(site, ad, yol, mekanlar):
    return {"@context": "https://schema.org", "@type": "ItemList", "name": ad,
            "url": site["url"] + yol, "numberOfItems": len(mekanlar),
            "itemListElement": [{"@type": "ListItem", "position": i, "name": m["ad"],
                                 "url": site["url"] + m["url"]}
                                for i, m in enumerate(mekanlar[:60], start=1)]}


def sss_schema(sorular):
    """Boş FAQPage yayımlanmaz: Google en az bir Question ister, boş blok hatalı sayılır."""
    if not sorular:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": s["s"],
                            "acceptedAnswer": {"@type": "Answer", "text": s["c"]}}
                           for s in sorular]}


def mekan_sss(m: dict) -> list[dict]:
    s = [{"s": f"{m['ad']} nerede?",
          "c": f"{m['ilce']} ilçesinde, İstanbul'un {m['yaka_bilgi']['ad']}'nda."
               + (f" Adres: {m['adres']}." if m.get("adres") else "")
               + (f" Koordinat: {m['koordinat_yazi']}." if m["koordinat_yazi"] else "")}]
    if m["saat_yazi"]:
        s.append({"s": f"{m['ad']} hangi gün ve saatlerde açık?",
                  "c": f"İBB'nin açık veri kaydına göre {m['saat_yazi']}. Resmî tatillerde "
                       f"ve bakım günlerinde değişebilir; gitmeden önce arayın."})
    if m["kategori"] == "park":
        s.append({"s": f"{m['ad']} girişi ücretli mi?",
                  "c": "İBB'nin yeşil alan envanterindeki parklar, korular ve kent ormanları "
                       "halka açık alanlardır ve girişleri için ücret alınmaz. İBB veri "
                       "setinde ücret sütunu bulunmuyor; otopark, tesis ve büfe hizmetleri "
                       "ile bazı mesire alanlarında hafta sonu uygulamaları ücretli olabilir."})
        if m["alan_yazi"]:
            s.append({"s": f"{m['ad']} ne kadar büyük?",
                      "c": f"İBB kaydına göre {m['alan_yazi']}."
                           + (f" Alan {m['parca_sayisi']} ayrı poligon parçası olarak "
                              f"kayıtlı; toplamı verilmiştir." if m.get("parca_sayisi", 1) > 1 else "")})
    if m["kategori"] == "kutuphane":
        s.append({"s": f"{m['ad']} ücretli mi, üyelik gerekiyor mu?",
                  "c": "İBB kütüphanelerinde giriş ve üyelik ücretsizdir. Ödünç kitap almak "
                       "için üyelik gerekir; içeride okumak için gerekmez."})
    if m["kategori"] == "muze":
        s.append({"s": f"{m['ad']} giriş ücretini nereden öğrenebilirim?",
                  "c": "Giriş ücreti İBB'nin açık veri setinde yer almadığı için burada da "
                       "yazmıyoruz. Güncel ücret ve indirim durumunu müzeyi arayarak ya da "
                       "İBB'nin kendi müze sayfasından öğrenebilirsiniz."})
    if m["kategori"] == "tiyatro":
        s.append({"s": f"{m['ad']} çocuk oyunu sahneliyor mu?",
                  "c": f"İBB Şehir Tiyatroları'nın {m['veri_yillari']} dönemine ait açık "
                       f"verisinde bu sahnede {binlik(m['cocuk_seans'])} çocuk oyunu seansı "
                       f"kayıtlı. Bu geçmiş kayıttır, güncel program değildir; oyun takvimi "
                       f"ve bilet için İBB Şehir Tiyatroları'nın kendi sitesine bakın."})
    if m["kategori"] == "kultur" and m.get("cocuk_birimi") is not None:
        s.append({"s": f"{m['ad']} — çocuk birimi var mı?",
                  "c": ("İBB'nin kültür merkezleri veri setinde bu merkez için çocuk birimi "
                        "'VAR' olarak işaretli." if m["cocuk_birimi"] else
                        "İBB'nin kültür merkezleri veri setinde bu merkez için çocuk birimi "
                        "'YOK' olarak işaretli. Merkezde çocuklara yönelik etkinlik yine de "
                        "düzenlenebilir; programı merkeze sorun.")})
    if m.get("telefon"):
        s.append({"s": f"{m['ad']} telefon numarası nedir?",
                  "c": f"İBB açık veri kaydındaki numara: {m['telefon']}. Numaralar "
                       f"değişebilir; son doğrulama {m['dogrulama']}."})
    return s[:6]


def liste_sss(baslik: str, mekanlar: list[dict], ek: list[dict] | None = None) -> list[dict]:
    """Liste sayfaları için veriden türeyen SSS. Uydurma yok: hepsi sayılabilir bilgi."""
    s = list(ek or [])
    if not mekanlar:
        return s
    ucretsiz = [m for m in mekanlar if m.get("ucretsiz")]
    kapali = [m for m in mekanlar if m.get("kapali")]
    buyuk = sorted([m for m in mekanlar if m.get("alan_m2")],
                   key=lambda m: -m["alan_m2"])[:3]
    if buyuk:
        s.append({"s": f"{baslik} arasında en büyük yeşil alan hangisi?",
                  "c": "En geniş olanlar: " + ", ".join(
                      f"{m['ad']} ({m['ilce']}, {binlik(m['alan_m2'])} m²)" for m in buyuk) + "."})
    if ucretsiz:
        s.append({"s": f"{baslik} arasında ücretsiz olan var mı?",
                  "c": f"Evet, {len(ucretsiz)} tanesinin girişi ücretsiz: "
                       + ", ".join(m["ad"] for m in ucretsiz[:5])
                       + (" ve diğerleri." if len(ucretsiz) > 5 else ".")})
    if kapali:
        s.append({"s": f"{baslik} arasında yağmurlu güne uygun kapalı mekân var mı?",
                  "c": f"{len(kapali)} kapalı mekân var: "
                       + ", ".join(m["ad"] for m in kapali[:4]) + "."})
    return s[:5]


# ---------------------------------------------------------------------------- yazma
def yaz(yol: str, icerik: str) -> None:
    hedef = DIST / "index.html" if yol == "/" else DIST / yol.strip("/") / "index.html"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(icerik, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    site = yukle("site.json")
    site["yil"] = date.today().year
    site["derleme_zamani"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    site["veri_tarihi_tr"] = date.fromisoformat(site["veri_tarihi"]).strftime("%d.%m.%Y")

    mekanlar = hazirla(yukle("mekanlar.json"), site)
    # Gerçek fotoğraflar (build/foto.py): yoksa None kalır, sayfa emoji kapakla çıkar.
    fotolar = yukle("foto.json", {})
    for m in mekanlar:
        m["foto"] = fotolar.get(m["ad"]) or None
    yesil = yukle("yesil_alanlar.json")
    for y in yesil:
        y["alan_yazi"] = alan_yazi(y.get("alan_m2"))
        y["maps_url"] = (f"https://www.google.com/maps/search/?api=1&query={y['lat']},{y['lng']}"
                         if y.get("lat") else "")
        y["tur_ad"] = ALT_TUR.get(y["tur"], "Yeşil alan")
    sayfali = {(m["ad"], m["ilce"]): m for m in mekanlar if m["kategori"] == "park"}
    for y in yesil:
        e = sayfali.get((y["ad"], y["ilce"]))
        y["url"] = e["url"] if e else ""

    rehberler = yukle("rehberler.json", [])
    sayfalar = yukle("sayfalar.json", [])
    for r in rehberler:
        r["url"] = f"/rehber/{r['slug']}/"

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["json"] = lambda v: json.dumps(v, ensure_ascii=False)
    env.filters["binlik"] = binlik
    env.filters["bulunma"] = bulunma

    # ---- gruplar
    ilce_grup: dict[str, list[dict]] = {}
    for m in mekanlar:
        ilce_grup.setdefault(m["ilce"], []).append(m)
    yesil_grup: dict[str, list[dict]] = {}
    for y in yesil:
        yesil_grup.setdefault(y["ilce"], []).append(y)
    for g in yesil_grup.values():
        g.sort(key=lambda y: -(y["alan_m2"] or 0))

    ilceler = sorted(
        ({"ad": ad, "slug": slugify(ad), "url": f"/ilce/{slugify(ad)}/",
          "yaka": YAKALAR["anadolu" if any(m["yaka"] == "anadolu" for m in ilce_grup.get(ad, []))
                          or any(y["yaka"] == "anadolu" for y in yesil_grup.get(ad, []))
                          else "avrupa"],
          "mekanlar": sorted(ilce_grup.get(ad, []),
                             key=lambda m: (m["kategori"] != "park", -(m.get("alan_m2") or 0), m["ad"])),
          "yesil": yesil_grup.get(ad, []),
          "yesil_m2": sum(y["alan_m2"] or 0 for y in yesil_grup.get(ad, []))}
         for ad in sorted(set(ilce_grup) | set(yesil_grup))),
        key=lambda i: i["ad"])

    kategoriler = [dict(k, anahtar=a, url=f"/tur/{k['slug']}/",
                        mekanlar=[m for m in mekanlar if m["kategori"] == a])
                   for a, k in KATEGORILER.items()]
    yakalar = [dict(y, anahtar=a, url=f"/{y['slug']}/",
                    mekanlar=[m for m in mekanlar if m["yaka"] == a],
                    ilceler=[i for i in ilceler if i["yaka"]["slug"] == y["slug"]])
               for a, y in YAKALAR.items()]

    ucretsiz = [m for m in mekanlar if m.get("ucretsiz")]
    kapali = [m for m in mekanlar if m.get("kapali")]
    tiyatrolar = [m for m in mekanlar if m["kategori"] == "tiyatro"]
    toplam_alan = sum(y["alan_m2"] or 0 for y in yesil)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    shutil.copytree(STATIC, DIST / "static")
    for ad in ("favicon.svg", "logo.svg"):
        if (STATIC / ad).exists():
            shutil.copy(STATIC / ad, DIST / ad)

    ortak = {"site": site, "ilceler": ilceler, "kategoriler": kategoriler, "yakalar": yakalar,
             "rehberler": rehberler, "toplam": len(mekanlar), "yesil_toplam": len(yesil)}
    yollar: list[tuple[str, str, str | None]] = []

    def tam_baslik(b: str) -> str:
        """Site adı yalnızca 60 karaktere sığıyorsa eklenir; yer adları kısaltılmaz."""
        ekli = f"{b} | {site['ad']}"
        return ekli if len(ekli) <= 60 else b

    def mekan_baslik(m: dict) -> str:
        """En bilgili biçimden başlar, 62 karaktere sığana kadar kırpar."""
        for aday in (f"{m['ad_ayirt']} — {m['ilce']}, İstanbul",
                     f"{m['ad_ayirt']} — {m['ilce']}",
                     m["ad_ayirt"]):
            if len(aday) <= 62:
                return aday
        return m["ad_ayirt"]

    def sayfa(yol, sablon, baslik, aciklama, schema, oncelik="0.6", og_gorsel=None, **kw):
        yaz(yol, env.get_template(sablon).render(
            baslik=baslik, tam_baslik=tam_baslik(baslik), meta_desc=kisalt(aciklama),
            canonical=yol, schema=[x for x in schema if x], og_gorsel=og_gorsel,
            **ortak, **kw))
        yollar.append((yol, oncelik, og_gorsel))

    # ---------------------------------------------------------------- ana sayfa
    sayfa("/", "home.html",
          f"İstanbul'da Çocukla Gidilecek Yerler ({site['yil']})",
          f"İstanbul'da çocukla gidilecek {len(mekanlar)} yer: {len(yesil)} park ve korunun "
          f"tam envanteri, İBB müzeleri, kütüphaneleri ve çocuk tiyatrosu sahneleri — "
          f"her biri resmî açık veriden, koordinatı ve kaynağıyla.",
          [{"@context": "https://schema.org", "@type": "WebSite", "name": site["ad"],
            "url": site["url"] + "/", "inLanguage": "tr-TR"},
           {"@context": "https://schema.org", "@type": "Organization", "name": site["ad"],
            "url": site["url"] + "/", "email": site["eposta"],
            "areaServed": {"@type": "City", "name": "İstanbul"}},
           liste_schema(site, "Öne çıkan mekânlar", "/", mekanlar[:20])],
          oncelik="1.0", one_cikan=mekanlar[:12], ucretsiz_sayi=len(ucretsiz),
          kapali_sayi=len(kapali), toplam_alan=toplam_alan, tiyatrolar=tiyatrolar[:6])

    # ---------------------------------------------------------------- yaka sayfaları
    for y in yakalar:
        sayfa(y["url"], "liste.html",
              f"{y['ad']}'nda Çocukla Gidilecek Yerler",
              f"İstanbul {y['ad']}'ndaki {len(y['ilceler'])} ilçede çocukla gidilebilecek "
              f"{len(y['mekanlar'])} yer: park ve korular, müzeler, kütüphaneler ve "
              f"tiyatro sahneleri.",
              [liste_schema(site, y["ad"], y["url"], y["mekanlar"]),
               sss_schema(liste_sss(f"{y['ad']} mekânları", y["mekanlar"])),
               kirintilar(site, (y["ad"], y["url"]))],
              oncelik="0.9", liste=y["mekanlar"], liste_basligi=f"{y['ad']} — tüm mekânlar",
              giris=(f"{y['aciklama']} Aşağıdaki {len(y['mekanlar'])} kayıt İBB Açık Veri "
                     f"Portalı'ndan derlendi; her birinin ilçesi, koordinatı ve kaynağı var."),
              sss=liste_sss(f"{y['ad']} mekânları", y["mekanlar"]),
              alt_baglar=[{"ad": i["ad"], "url": i["url"], "sayi": len(i["mekanlar"])}
                          for i in y["ilceler"]],
              alt_baslik="İlçeler", kirinti=[(y["ad"], y["url"])])

        # yaka × kategori kesişimleri — "anadolu yakasında müze" gibi uzun kuyruk
        for k in kategoriler:
            uyeler = [m for m in y["mekanlar"] if m["kategori"] == k["anahtar"]]
            if len(uyeler) < 5:
                continue
            url = f"{y['url']}{k['slug']}/"
            sayfa(url, "liste.html",
                  f"{y['ad']} {k['ad']}: {len(uyeler)} Yer",
                  f"İstanbul {y['ad']}'nda {k['cumle']}: {len(uyeler)} kayıt, "
                  f"ilçe, adres ve koordinatıyla. {k['aciklama']}",
                  [liste_schema(site, f"{y['ad']} {k['ad']}", url, uyeler),
                   sss_schema(liste_sss(f"{y['ad']}'ndaki {k['cumle']}", uyeler)),
                   kirintilar(site, (y["ad"], y["url"]), (k["ad"], url))],
                  oncelik="0.8", liste=uyeler, liste_basligi=f"{y['ad']} {k['cumle']}",
                  giris=(f"{k['aciklama']} İstanbul {y['ad']}'nda bu türden {len(uyeler)} kayıt "
                         f"var; {len({m['ilce'] for m in uyeler})} ilçeye dağılmış durumda. "
                         f"{y['aciklama']} Listedeki her kayıt İBB Açık Veri Portalı'ndan "
                         f"geliyor; kaynağı ve son doğrulama tarihi kendi sayfasında yazılı."),
                  sss=liste_sss(f"{y['ad']}'ndaki {k['cumle']}", uyeler),
                  kirinti=[(y["ad"], y["url"]), (k["ad"], url)])

    # ---------------------------------------------------------------- kategori sayfaları
    for k in kategoriler:
        sayfa(k["url"], "liste.html",
              f"İstanbul'da {k['ad']} ({len(k['mekanlar'])})",
              f"İstanbul'daki {len(k['mekanlar'])} {k['tekil'].lower()}; ilçe, adres, "
              f"koordinat ve resmî kaynağıyla. {k['aciklama']}",
              [liste_schema(site, k["ad"], k["url"], k["mekanlar"]),
               sss_schema(liste_sss(f"İstanbul'daki {k['cumle']}", k["mekanlar"])),
               kirintilar(site, (k["ad"], k["url"]))],
              oncelik="0.9", liste=k["mekanlar"], liste_basligi=k["ad"], giris=k["aciklama"],
              sss=liste_sss(f"İstanbul'daki {k['cumle']}", k["mekanlar"]),
              kirinti=[(k["ad"], k["url"])])

    # ---------------------------------------------------------------- ilçe sayfaları
    sayfa("/ilce/", "ilce_dizini.html", "İlçelere Göre İstanbul'da Çocukla Gidilecek Yerler",
          f"İstanbul'un 39 ilçesinde çocukla gidilecek yerler; her ilçenin park envanteri, "
          f"müzeleri ve kütüphaneleriyle.",
          [kirintilar(site, ("İlçeler", "/ilce/"))], oncelik="0.9",
          kirinti=[("İlçeler", "/ilce/")])

    for i in ilceler:
        park_url = f"{i['url']}parklar/"
        sayfa(i["url"], "liste.html",
              f"{bulunma(i['ad'])} Çocukla Gidilecek Yerler",
              (f"{i['ad']} ilçesinde çocukla gidilebilecek {len(i['mekanlar'])} yer ve "
               f"ilçedeki {len(i['yesil'])} park/korunun tam listesi — İBB açık verisinden."
               if i["mekanlar"] else
               f"{i['ad']} ilçesindeki {len(i['yesil'])} park, koru ve mesire alanının tam "
               f"listesi — büyüklükleri ve konumlarıyla, İBB açık verisinden."),
              [liste_schema(site, f"{i['ad']} mekânları", i["url"], i["mekanlar"]),
               sss_schema(liste_sss(f"{i['ad']} mekânları", i["mekanlar"], ek=[
                   {"s": f"{bulunma(i['ad'])} kaç park var?",
                    "c": f"İBB'nin yeşil alan envanterinde {i['ad']} ilçesinde "
                         f"{len(i['yesil'])} park, koru ve mesire alanı kayıtlı; toplam "
                         f"{binlik(sum(y['alan_m2'] or 0 for y in i['yesil']))} m². "
                         f"Tam liste: {site['url']}{park_url}"}])),
               kirintilar(site, ("İlçeler", "/ilce/"), (i["ad"], i["url"]))],
              oncelik="0.8", liste=i["mekanlar"], liste_basligi=f"{i['ad']} — çocukla gidilecek yerler",
              giris=(f"{i['ad']}, İstanbul'un {i['yaka']['ad']}'nda yer alıyor. İBB'nin "
                     f"açık veri kayıtlarına göre ilçede "
                     + (", ".join(f"{sayi} {ad}" for ad, sayi in dokum(i["mekanlar"])) + " bulunuyor"
                        if i["mekanlar"] else
                        "kendi sayfası açılan bir müze, kütüphane ya da büyük park bulunmuyor")
                     + f"; ayrıca İBB envanterinde ilçe için {len(i['yesil'])} park, "
                     f"koru ve mesire alanı kayıtlı ve bunların toplam büyüklüğü "
                     f"{binlik(i['yesil_m2'])} m². Aşağıdaki kayıtların hepsi resmî açık "
                     f"veriden derlendi; her birinin kaynağı ve doğrulama tarihi kendi "
                     f"sayfasında yazılı."),
              sss=liste_sss(f"{i['ad']} mekânları", i["mekanlar"], ek=[
                  {"s": f"{bulunma(i['ad'])} kaç park var?",
                   "c": f"İBB'nin yeşil alan envanterinde {i['ad']} ilçesinde "
                        f"{len(i['yesil'])} park, koru ve mesire alanı kayıtlı; toplam "
                        f"{binlik(sum(y['alan_m2'] or 0 for y in i['yesil']))} m²."}]),
              alt_baglar=[{"ad": f"{i['ad']} park listesi ({len(i['yesil'])})", "url": park_url}],
              alt_baslik="İlçenin tam park envanteri",
              onizleme=i["yesil"][:10], onizleme_url=park_url, onizleme_toplam=len(i["yesil"]),
              kirinti=[("İlçeler", "/ilce/"), (i["ad"], i["url"])])

        if i["yesil"]:
            top = i["yesil_m2"]
            park_sss = [
                {"s": f"{bulunma(i['ad'])} kaç park var?",
                 "c": f"İBB Park, Bahçe ve Yeşil Alan verisinde {i['ad']} ilçesi için "
                      f"{len(i['yesil'])} kayıt bulunuyor; toplam alan {binlik(top)} m²."},
                {"s": f"{tamlayan(i['ad'])} en büyük parkı hangisi?",
                 "c": f"{i['yesil'][0]['ad']} — {i['yesil'][0]['alan_yazi']}."},
                {"s": "Bu liste nereden alındı?",
                 "c": "İBB Açık Veri Portalı'nın Park, Bahçe ve Yeşil Alanlar Dairesi "
                      "verisinden. Alanlar poligon geometrisinden hesaplandı; parça "
                      "parça kayıtlı parklar birleştirildi."}]
            sayfa(park_url, "ilce_parklar.html",
                  f"{i['ad']} Parkları: {len(i['yesil'])} Yeşil Alanın Tam Listesi",
                  f"{i['ad']} ilçesindeki {len(i['yesil'])} park, koru ve mesire alanının "
                  f"tam listesi; her birinin büyüklüğü ve konumuyla. Toplam "
                  f"{binlik(top)} m² yeşil alan.",
                  [liste_schema(site, f"{i['ad']} parkları", park_url,
                                [y for y in i["yesil"] if y["url"]]),
                   sss_schema(park_sss),
                   kirintilar(site, ("İlçeler", "/ilce/"), (i["ad"], i["url"]),
                              ("Parklar", park_url))],
                  oncelik="0.7", i=i, yesil=i["yesil"], toplam_m2=top, sss=park_sss,
                  kirinti=[("İlçeler", "/ilce/"), (i["ad"], i["url"]), ("Parklar", park_url)])

    # ---------------------------------------------------------------- tematik sayfalar
    sayfa("/ucretsiz/", "liste.html",
          f"İstanbul'da Çocukla Ücretsiz Gidilecek {len(ucretsiz)} Yer",
          f"İstanbul'da girişi ücretsiz {len(ucretsiz)} yer: parklar, korular, kent ormanları "
          f"ve İBB halk kütüphaneleri. Hepsi resmî kayıttan, koordinatıyla.",
          [liste_schema(site, "Ücretsiz mekânlar", "/ucretsiz/", ucretsiz),
           sss_schema(liste_sss("ücretsiz mekânlar", ucretsiz)),
           kirintilar(site, ("Ücretsiz", "/ucretsiz/"))],
          oncelik="0.9", liste=ucretsiz, liste_basligi="Girişi ücretsiz mekânlar",
          giris=("Buradaki mekânların girişi ücretsizdir: İBB'nin yeşil alan envanterindeki "
                 "parklar, korular ve kent ormanları halka açıktır; İBB halk kütüphanelerinde "
                 "giriş ve üyelik ücret alınmaz. Tesis, otopark ve büfe hizmetleri ayrıca "
                 "ücretli olabilir."),
          sss=liste_sss("ücretsiz mekânlar", ucretsiz),
          kirinti=[("Ücretsiz", "/ucretsiz/")])

    sayfa("/yagmurlu-gunde/", "liste.html",
          "Yağmurlu Günde İstanbul'da Çocukla Nereye Gidilir?",
          f"Yağmurlu ve soğuk günlerde İstanbul'da çocukla gidilebilecek {len(kapali)} kapalı "
          f"mekân: İBB müzeleri, kütüphaneleri, kültür merkezleri ve tiyatro sahneleri.",
          [liste_schema(site, "Kapalı mekânlar", "/yagmurlu-gunde/", kapali),
           sss_schema(liste_sss("kapalı mekânlar", kapali)),
           kirintilar(site, ("Yağmurlu günde", "/yagmurlu-gunde/"))],
          oncelik="0.9", liste=kapali, liste_basligi="Kapalı mekânlar",
          giris=("Hava bozduğunda işe yarayan liste: kapalı alanda vakit geçirilebilen "
                 "müzeler, kütüphaneler, kültür merkezleri ve tiyatro sahneleri. "
                 "Kütüphanelerin girişi ücretsizdir."),
          sss=liste_sss("kapalı mekânlar", kapali),
          kirinti=[("Yağmurlu günde", "/yagmurlu-gunde/")])

    # ---------------------------------------------------------------- mekân sayfaları
    for m in mekanlar:
        sss = mekan_sss(m)
        ayni_ilce = [b for b in ilce_grup[m["ilce"]] if b["slug"] != m["slug"]][:8]
        yakin = []
        if m.get("lat") is not None and m.get("koordinat_durum") != "supheli":
            aday = [(km(m["lat"], m["lng"], b["lat"], b["lng"]), b) for b in mekanlar
                    if b["slug"] != m["slug"] and b.get("lat") is not None
                    and b.get("koordinat_durum") != "supheli"]
            yakin = [(b, round(d, 1)) for d, b in sorted(aday, key=lambda t: t[0])[:6] if d <= 8]
        sayfa(m["url"], "mekan.html",
              mekan_baslik(m),
              m["ozet"],
              [mekan_schema(m, site), sss_schema(sss),
               kirintilar(site, ("İlçeler", "/ilce/"), (m["ilce"], f"/ilce/{m['ilce_slug']}/"),
                          (m["ad"], m["url"]))],
              oncelik="0.7", m=m, sss=sss, kisa=kisa_cevap(m), yakin=yakin, ayni_ilce=ayni_ilce,
              og_gorsel=(f"/static/img/mekan/{m['foto']['lg']}" if m.get("foto") else None),
              kirinti=[("İlçeler", "/ilce/"), (m["ilce"], f"/ilce/{m['ilce_slug']}/"),
                       (m["ad"], m["url"])])

    # ---------------------------------------------------------------- harita
    noktalar = [m for m in mekanlar
                if m.get("lat") is not None and m.get("koordinat_durum") != "supheli"]
    sayfa("/harita/", "harita.html", "İstanbul Çocuk Mekânları Haritası",
          f"İstanbul'da çocukla gidilebilecek {len(noktalar)} mekânın haritası; ilçeye, "
          f"türe ve yakaya göre filtreli.",
          [kirintilar(site, ("Harita", "/harita/"))], oncelik="0.8",
          nokta_sayisi=len(noktalar), kirinti=[("Harita", "/harita/")])

    # ---------------------------------------------------------------- rehberler
    if rehberler:
        sayfa("/rehber/", "rehber_dizini.html",
              "İstanbul'da Çocukla Gezi Rehberleri",
              "İstanbul'da çocukla nereye gidilir, hangi sahnede çocuk oyunu sahnelendi, "
              "hangi park kaç metrekare — hepsi İBB açık verisinden hesaplanmış rehberler.",
              [kirintilar(site, ("Rehberler", "/rehber/"))], oncelik="0.8",
              kirinti=[("Rehberler", "/rehber/")])
    for r in rehberler:
        sayfa(r["url"], "rehber.html", r["baslik"], r["ozet"],
              [sss_schema(r.get("sss", [])),
               {"@context": "https://schema.org", "@type": "Article", "headline": r["baslik"],
                "description": r["ozet"], "dateModified": site["veri_tarihi"],
                "inLanguage": "tr-TR", "url": site["url"] + r["url"],
                "author": {"@type": "Organization", "name": site["ad"]}},
               kirintilar(site, ("Rehberler", "/rehber/"), (r["baslik"], r["url"]))],
              oncelik="0.8", r=r, kirinti=[("Rehberler", "/rehber/"), (r["baslik"], r["url"])])

    # ---------------------------------------------------------------- düz sayfalar
    for p in sayfalar:
        sayfa(p["url"], "sayfa.html", p["baslik"], p["meta"],
              [kirintilar(site, (p["baslik"], p["url"]))], oncelik="0.4", p=p,
              kirinti=[(p["baslik"], p["url"])])

    (DIST / "404.html").write_text(env.get_template("404.html").render(
        baslik="Sayfa bulunamadı", tam_baslik="Sayfa bulunamadı | " + site["ad"],
        meta_desc="Aradığınız sayfa bulunamadı.", canonical="/404.html", schema=[],
        **ortak), encoding="utf-8")

    # ---------------------------------------------------------------- açık veri
    (DIST / "veri").mkdir(exist_ok=True)
    disari = ("ad", "slug", "url", "kategori", "tur", "tur_ad", "ilce", "yaka", "adres",
              "telefon", "saat", "gun", "acilis_yili", "lat", "lng", "koordinat_kaynak",
              "koordinat_durum", "alan_m2", "kapali", "ucretsiz", "cocuk_birimi",
              "cocuk_seans", "kaynak_ad", "kaynak_url")
    (DIST / "veri" / "mekanlar.json").write_text(json.dumps(
        [{k: m.get(k) for k in disari if k in m} | {"ikon": m["kat"]["ikon"]} for m in mekanlar],
        ensure_ascii=False), encoding="utf-8")
    (DIST / "veri" / "yesil-alanlar.json").write_text(
        json.dumps(yesil, ensure_ascii=False), encoding="utf-8")
    # Harita bu dosyayı çekiyor.
    (DIST / "static" / "noktalar.json").write_text(json.dumps(
        [{"a": m["ad"], "u": m["url"], "k": m["kategori"], "i": m["ilce"], "y": m["yaka"],
          "lat": m["lat"], "lng": m["lng"], "n": m["kat"]["ikon"], "t": m["tur_ad"],
          "uc": bool(m.get("ucretsiz")), "kp": bool(m.get("kapali"))} for m in noktalar],
        ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- sitemap / robots
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
          'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">']
    for yol, onc, gorsel in yollar:
        img = (f"<image:image><image:loc>{site['url']}{gorsel}</image:loc></image:image>"
               if gorsel else "")
        sm.append(f"  <url><loc>{site['url']}{yol}</loc>"
                  f"<lastmod>{site['veri_tarihi']}</lastmod><priority>{onc}</priority>{img}</url>")
    sm.append("</urlset>")
    (DIST / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")

    (DIST / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        "# Yapay zekâ tarayıcıları (GEO): içeriğin alıntılanmasına izin veriyoruz\n"
        + "".join(f"User-agent: {b}\nAllow: /\n" for b in
                  ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
                   "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot"))
        + f"\nSitemap: {site['url']}/sitemap.xml\n", encoding="utf-8")

    if site.get("adsense"):
        (DIST / "ads.txt").write_text(
            f"google.com, {site['adsense'].removeprefix('ca-')}, DIRECT, f08c47fec0942fa0\n",
            encoding="utf-8")

    llms = [f"# {site['ad']}", "", f"> {site['aciklama']}", "",
            f"Veri kaynağı: İBB Açık Veri Portalı (data.ibb.gov.tr). "
            f"Son doğrulama: {site['veri_tarihi']}. Mekânlar puanlanmaz; yalnız resmî "
            f"kayıttaki bilgi yayımlanır.", "",
            f"## Sayılar", "",
            f"- Kendi sayfası olan mekân: {len(mekanlar)}",
            f"- İlçe park envanterindeki yeşil alan: {len(yesil)} ({binlik(toplam_alan)} m²)",
            f"- Girişi ücretsiz mekân: {len(ucretsiz)}",
            f"- Kapalı (yağmurlu güne uygun) mekân: {len(kapali)}", ""]
    for k in kategoriler:
        llms += ["", f"## {k['ad']} ({len(k['mekanlar'])})", ""]
        for m in k["mekanlar"]:
            llms.append(f"- [{m['ad']}]({site['url']}{m['url']}): {m['ilce']}, "
                        f"{m['yaka_bilgi']['ad']}. {m['ozet']}")
    if rehberler:
        llms += ["", "## Rehberler", ""]
        llms += [f"- [{r['baslik']}]({site['url']}{r['url']}): {r['ozet']}" for r in rehberler]
    (DIST / "llms.txt").write_text("\n".join(llms), encoding="utf-8")

    fotolu = sum(1 for m in mekanlar if m.get("foto"))
    supheli = sum(1 for m in mekanlar if m.get("koordinat_durum") == "supheli")
    print(f"✓ {len(yollar)} sayfa | {len(mekanlar)} mekân | {len(yesil)} yeşil alan | "
          f"{len(ilceler)} ilçe | {len(rehberler)} rehber -> {DIST}")
    print(f"  koordinatlı {len(noktalar)} | fotoğraflı {fotolu} | ücretsiz {len(ucretsiz)} | kapalı {len(kapali)}"
          + (f" | ŞÜPHELİ KOORDİNAT {supheli}" if supheli else ""))


if __name__ == "__main__":
    main()
