# -*- coding: utf-8 -*-
"""İBB açık verisini siteye hazır `data/mekanlar.json` haline getirir.

Girdiler (hepsi İBB Açık Veri Portalı):
  data/ibb_mekanlar.json      · müze, kütüphane, yeşil alan  (build/ibb_veri.py üretir)
  data/ham/kultur_merkezleri.xlsx
  data/ham/sosyal_tesis.xlsx
  data/ham/tiyatro_oyun.csv   · Şehir Tiyatroları 2017-2023 oyun kayıtları
  data/koordinat.json         · müze/kütüphane için OSM koordinatları (build/koordinat.py)

Çıktılar:
  data/mekanlar.json          · kendi sayfası olan mekânlar
  data/yesil_alanlar.json     · ilçe park tabloları için TAM yeşil alan envanteri

İlke: hiçbir alan tahminle doldurulmaz. Kaynakta yoksa None kalır.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DATA = KOK / "data"
HAM = DATA / "ham"

PORTAL = "https://data.ibb.gov.tr/dataset/"
KAYNAK = {
    "muze": ("İBB Müzeleri Lokasyon, Çalışma Gün ve Saatleri",
             PORTAL + "ibb-muzeleri-lokasyon-calisma-gun-ve-saatleri"),
    "kutuphane": ("İBB Kütüphaneleri Lokasyon, Çalışma Gün ve Saatleri",
                  PORTAL + "ibb-kutuphaneleri-lokasyon-calisma-gun-ve-saatleri"),
    "yesil": ("İBB Park, Bahçe ve Yeşil Alan Verileri",
              PORTAL + "park-bahce-ve-yesil-alanlar-dairesi-baskanligi-verileri"),
    "kultur": ("İBB Kültür Merkezleri Veri Seti", PORTAL + "kultur-merkezleri-veri-seti"),
    "tesis": ("İBB Sosyal Tesis Konumları", PORTAL + "sosyal-tesis-konumlari"),
    "tiyatro": ("İBB Şehir Tiyatroları Veri Seti", PORTAL + "sehir-tiyatrolari-veri-seti"),
}

ILCELER = [
    "Adalar", "Arnavutköy", "Ataşehir", "Avcılar", "Bahçelievler", "Bakırköy", "Bağcılar",
    "Bayrampaşa", "Başakşehir", "Beykoz", "Beylikdüzü", "Beyoğlu", "Beşiktaş", "Büyükçekmece",
    "Esenler", "Esenyurt", "Eyüpsultan", "Fatih", "Gaziosmanpaşa", "Güngören", "Kadıköy",
    "Kartal", "Kağıthane", "Küçükçekmece", "Maltepe", "Pendik", "Sancaktepe", "Sarıyer",
    "Silivri", "Sultanbeyli", "Sultangazi", "Tuzla", "Zeytinburnu", "Çatalca", "Çekmeköy",
    "Ümraniye", "Üsküdar", "Şile", "Şişli",
]
# Kaynak dosyalarda aynı ilçe farklı yazılıyor.
ILCE_DUZELT = {"K.çekmece": "Küçükçekmece", "Kâğıthane": "Kağıthane", "Eyüp": "Eyüpsultan",
               "Küçük Çekmece": "Küçükçekmece", "Büyük Çekmece": "Büyükçekmece"}

ANADOLU = {"Adalar", "Ataşehir", "Beykoz", "Çekmeköy", "Kadıköy", "Kartal", "Maltepe",
           "Pendik", "Sancaktepe", "Sultanbeyli", "Şile", "Tuzla", "Ümraniye", "Üsküdar"}

IST_KUTU = (40.78, 41.65, 27.90, 29.95)   # lat_min, lat_max, lng_min, lng_max

# Kendi sayfasını hak eden park büyüklüğü. Altındakiler ilçe park tablosunda listelenir:
# 5.000 m²'lik mahalle parkına ayrı sayfa açmak ince içeriktir, tabloda ise değerlidir.
PARK_SAYFA_ESIGI = 50_000
YESIL_TURLER = {"park", "koru", "mesire", "kent_ormani", "hatira_ormani"}

# Kaynakta adlar BÜYÜK HARFten .title() ile dönüştürülmüş; kısaltmalar bozulmuş.
# Hem ASCII I'li (eski _baslik çıktısı) hem noktalı İ'li (düzeltilmiş çıktı) biçim:
# _tr_bas artık "IBB" -> "İbb" üretiyor, KISALTMA yalnız "Ibb" arıyordu ve kısaltma bozuk kalıyordu.
KISALTMA = {"Ibb": "İBB", "İbb": "İBB", "Ido": "İDO", "İdo": "İDO",
            "Iett": "İETT", "İett": "İETT", "Tem": "TEM", "Iski": "İSKİ", "İski": "İSKİ",
            "Ipa": "İPA", "İpa": "İPA", "Crr": "CRR", "Ii": "II", "Iii": "III",
            "Ido'": "İDO'"}


# Ham kaynak dosyalar 52 MB; depoya girmez, eksikse portaldan indirilir.
KAYNAK_DOSYA = {
    "kultur_merkezleri.xlsx": PORTAL + "d299950a-3476-4576-967a-9ab7bbe2aa06/resource/"
                                       "9f16f741-742f-41f8-9e36-918fb7fc2a7f/download/"
                                       "kultur-merkezleri-veri-seti_.xlsx",
    "sosyal_tesis.xlsx": PORTAL + "6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d/resource/"
                                  "87517b4e-28b5-478f-a0ba-27291cf17b69/download/"
                                  "ibb-sosyal-tesis-konumlar.xlsx",
    "tiyatro_oyun.csv": PORTAL + "cd121983-4063-4d12-a900-3c928d59d963/resource/"
                                 "79465ce9-8755-4b57-8e6c-def0c0caadc8/download/theater_play.csv",
}


def ham_indir() -> None:
    HAM.mkdir(parents=True, exist_ok=True)
    for ad, url in KAYNAK_DOSYA.items():
        p = HAM / ad
        if p.exists():
            continue
        print(f"  indiriliyor: {ad}", flush=True)
        istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(istek, timeout=180) as y:
            p.write_bytes(y.read())


# Kaynak metin onarımları -----------------------------------------------------
# Kaynakta doğrulanmış yazım hataları. Aynı veri setinde doğrusu da geçtiği için
# (ör. "İBB Belgradkapı Kara Surları Ziyaretçi Merkezi") düzeltme güvenli.
AD_DUZELT = {"Berlgradkapı": "Belgradkapı"}


def ad_onar(ad: str) -> str:
    for yanlis, dogru in AD_DUZELT.items():
        ad = ad.replace(yanlis, dogru)
    return ad


def gun_onar(gun: str) -> str:
    """"Hergün" TDK'ya göre ayrı yazılır; 50 kayıtta bitişik geliyor."""
    return re.sub(r"(?i)\bher\s*g[üu]n\b", "Her gün", (gun or "").strip())


def adres_onar(adres: str) -> str:
    """Adresi cümleye gömülebilir hale getirir.

    Kaynakta adresler "…Bakırköy/İst.", "…Fatih, İstanbul," ya da "…Kadıköy / istanbul"
    gibi bitiyor; şablon sonuna nokta ekleyince "İst.." ve "İstanbul,." çıkıyordu.
    """
    a = " ".join((adres or "").split())
    if not a:
        return ""
    a = re.sub(r"(?i)/\s*[iİ]st\.?$", "/İstanbul", a)
    a = re.sub(r"(?i)/\s*istanbul\b", "/İstanbul", a)
    a = re.sub(r"\s+,", ",", a)
    a = re.sub(r"\bPtt\b", "PTT", a)
    return a.rstrip(" .,;/")


ALAN_KODU = ("212", "216")


def telefon_onar(ham: str) -> str:
    """Kütüphane kaynağındaki telefon alanını okunur hale getirir.

    Alan tek numara değil; santralin iki hattı ayraçsız yapıştırılmış:
    `0 (212) 249 95 65 0 (212) 249 09 45 Dahili:663827`. Dahili kimi kayıtta
    "Dahili:" ile geliyor, kimisinde ilk numaraya tireyle bağlı
    (`… 95 65-663826`). Bir kayıtta baştaki 0 yerine 2 yazılmış.

    Çıktı: `0212 249 95 65 (dahili 663826) · 0212 249 09 45`
    """
    m = " ".join((ham or "").split())
    if not m:
        return ""
    dahili: list[str] = []
    for kalip in (r"(?i)\bdahili\s*:?\s*(\d{3,6})", r"(?<=\d)\s*-\s*(\d{3,6})\b"):
        dahili += re.findall(kalip, m)
        m = re.sub(kalip, " ", m)

    haneler = re.sub(r"\D", "", m)
    numaralar: list[str] = []
    while len(haneler) >= 10:
        if haneler[0] == "0" and haneler[1:4] in ALAN_KODU:
            numaralar.append(haneler[:11])
            haneler = haneler[11:]
        elif haneler[:3] in ALAN_KODU:
            numaralar.append("0" + haneler[:10])
            haneler = haneler[10:]
        else:
            # Kaynak hatasından gelen fazladan hane; birini atıp yeniden dene.
            haneler = haneler[1:]
    if not numaralar:
        return ""

    yazi = [f"{n[:4]} {n[4:7]} {n[7:9]} {n[9:]}" for n in dict.fromkeys(numaralar)]
    if dahili:
        yazi[0] += f" (dahili {', '.join(dict.fromkeys(dahili))})"
    return " · ".join(yazi)


def tr_alt(s: str) -> str:
    """Türkçe küçük harf: I->ı, İ->i. Python'un lower()'ı ikisini de bozar."""
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_baslik(s: str) -> str:
    """Türkçe büyük harf başlatma.

    `"BAKIRKÖY EĞİTİM".title()` Python'da "Bakirköy Eği̇ti̇m" verir: I noktalı i'ye
    dönüşür, İ'nin noktası ayrı birleşen karakter olarak kalır. 46 kültür merkezi ve
    sosyal tesis adı bu yüzden bozuktu.
    """
    kelimeler = []
    for k in s.split():
        a = tr_alt(k)
        for i, h in enumerate(a):
            if h.isalpha():
                ilk = "İ" if h == "i" else ("I" if h == "ı" else h.upper())
                kelimeler.append(a[:i] + ilk + a[i + 1:])
                break
        else:
            kelimeler.append(a)
    return " ".join(kelimeler)


def temiz_ad(ad: str) -> str:
    ad = " ".join((ad or "").split())
    ad = re.sub(r"\b(" + "|".join(KISALTMA) + r")\b", lambda m: KISALTMA[m.group(1)], ad)
    # ".title()" parantez ve tire sonrasını küçük bırakmış: "(caddebostan" -> "(Caddebostan"
    ad = re.sub(r"([(\-/]\s*)([a-zçğıöşü])", lambda m: m.group(1) + m.group(2).upper(), ad)
    # ".title()" bağlaçları da büyütmüş: "Kara Ve Sahil Parkı" -> "Kara ve Sahil Parkı"
    ad = re.sub(r"(?<= )(Ve|İle)(?= )", lambda m: tr_alt(m.group(1)), ad)
    return ad


TR_ASCII = str.maketrans("çğıöşüâîÇĞİÖŞÜÂÎI", "cgiosuaicgiosuaii")


def katla(metin: str) -> str:
    """Türkçe duyarlı karşılaştırma anahtarı.

    `"BEŞİKTAŞ".lower()` Python'da "beşi̇ktaş" üretir — büyük İ'nin noktası ayrı bir
    birleşen karakter olarak kalır ve "beşiktaş" ile eşleşmez. Dört sosyal tesis bu
    yüzden ilçesiz kalmıştı.
    """
    return unicodedata.normalize("NFKD", (metin or "").translate(TR_ASCII)) \
        .encode("ascii", "ignore").decode().lower()


def ilce_bul(metin: str) -> str | None:
    """Adresten ilçe çıkarır. Önce '<İlçe>/İstanbul' kalıbı, sonra son geçen ilçe adı.

    Sıra önemli: 'Fatih Mahallesi ... Küçükçekmece/İstanbul' adresinde naif tarama
    ilçeyi Fatih sanıyor. Aynı tuzak 'ARNAVUTKÖY SOSYAL TESİSİ'nde de var — tesis
    Beşiktaş'ın Arnavutköy mahallesinde, Arnavutköy ilçesinde değil.
    """
    if not metin:
        return None
    d = {katla(i): i for i in ILCELER} | {katla(k): v for k, v in ILCE_DUZELT.items()}
    kalip = re.search(r"([A-Za-zÇĞİÖŞÜÂÎçğıöşüâî.\s]+?)\s*/\s*[İIi]stanbul", metin)
    if kalip:
        aday = katla(kalip.group(1).strip().split()[-1])
        if aday in d:
            return d[aday]
    kat = katla(metin)
    son, yer = None, -1
    for k, v in d.items():
        p = kat.rfind(k)
        if p > yer:
            son, yer = v, p
    return son


def _sayi(v) -> float | None:
    """'410578458' -> 41.0578458 ; '41.067491' -> 41.067491

    İBB sosyal tesis dosyasında ondalık ayraç düşmüş (DKMP dosyalarındaki hatanın aynısı).
    Değerler 40/41 (enlem) ve 28/29 (boylam) ile başladığı için ilk iki hane tam kısımdır.
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    if re.fullmatch(r"\d{6,12}", s):
        return float(s[:2] + "." + s[2:])
    try:
        return float(s)
    except ValueError:
        return None


def ist_ici(lat, lng) -> bool:
    return (lat is not None and lng is not None
            and IST_KUTU[0] <= lat <= IST_KUTU[1] and IST_KUTU[2] <= lng <= IST_KUTU[3])


# OSM'in önerdiği ilçe, kaydın koordinatından bu km'den uzaktaysa öneri reddedilir.
YAKINLIK_ESIGI_KM = 6.0


def ilce_karar(kayitlar: list[dict], osm: dict) -> int:
    """İBB'nin ilçe alanı ile OSM ters çözümü çeliştiğinde COĞRAFYAYA sorar.

    İkisi de yanılabiliyor: İBB Taksim Gezi Parkı'nı Şişli yazmış (gerçekte Beyoğlu),
    OSM ise Burgazada'daki bir kaydı Fatih sanıyor. Bu yüzden hakem, kaydın
    koordinatının hangi ilçenin kayıt kümesine daha yakın düştüğüdür: aday ilçenin
    ortancasına belirgin biçimde (en az 2 kat) daha yakınsa düzeltilir, yoksa
    İBB'nin değeri korunur.
    """
    ortanca: dict[str, tuple[float, float]] = {}
    grup: dict[str, list[dict]] = defaultdict(list)
    for k in kayitlar:
        if k.get("lat"):
            grup[k["ilce"]].append(k)
    for il, g in grup.items():
        if len(g) >= 4:
            ortanca[il] = (statistics.median(x["lat"] for x in g),
                           statistics.median(x["lng"] for x in g))

    def uzaklik(k, il):
        """Kaydın, o ilçenin kayıt kümesinin ortancasına kuş uçuşu km'si."""
        if il not in ortanca:
            return None
        o = ortanca[il]
        return math.hypot((k["lat"] - o[0]) * 111, (k["lng"] - o[1]) * 84)

    duzeltilen = 0
    for k in kayitlar:
        if not k.get("lat"):
            continue
        aday = osm.get(f"{k['lat']:.6f},{k['lng']:.6f}")
        aday = ILCE_DUZELT.get(aday, aday)
        if not aday or aday == k["ilce"] or aday not in ILCELER:
            continue
        d_ibb, d_osm = uzaklik(k, k["ilce"]), uzaklik(k, aday)
        if d_ibb is None or d_osm is None:
            continue
        # OSM'in dediği ilçe hem daha yakın hem de coğrafi olarak makul olmalı.
        # Gezi Parkı Şişli/Beyoğlu sınırında (1,97'ye karşı 1,58 km) -> düzeltilir.
        # Burgazada'daki kayıt için OSM "Fatih" diyor (17,7 km) -> reddedilir.
        if d_osm >= d_ibb or d_osm > YAKINLIK_ESIGI_KM:
            continue
        k["ilce_kaynak_ibb"] = k["ilce"]
        k["ilce"] = aday
        duzeltilen += 1
    return duzeltilen


# Örtüşme sayılmayan sözcükler: her iki adda da geçmesi doğal olan tür ve yer
# sözcükleri. Bunlar sayılınca "Mecidiyeköy Sanat Galerisi" ile "Mecidiyeköy
# Meydanı" eşleşiyordu.
GENEL_SOZCUK = frozenset({
    "istanbul", "kültür", "merkez", "merkezi", "müze", "müzesi", "kütüphane",
    "kütüphanesi", "park", "parkı", "sanat", "galeri", "galerisi", "mahalle",
    "mahallesi", "cadde", "caddesi", "sokak", "sokağı", "bulvar", "bulvarı",
    "belediye", "belediyesi", "büyükşehir", "sahne", "sahnesi", "tiyatro",
    "tiyatrosu", "spor", "kompleks", "kompleksi", "sosyal", "tesis", "tesisi",
    "çocuk", "hangar", "ziyaretçi", "surları",
})


def osm_ortusuyor(ad: str, osm_ad: str, adres: str = "") -> bool:
    """OSM sonucu gerçekten bu mekân mı, yoksa yakındaki başka bir yer mi?

    Adres tabanlı yedek sorgu çevredeki rastgele bir POI'yi döndürüyor:
    "Dudullu Ödünç Kütüphanesi" için yağlama cihazları mağazası, "Baruthane
    Galeri" için Hyatt Regency oteli.

    "Bir ortak sözcük yeter" ölçütü zayıf çıktı: ortak sözcük mekânın adı değil
    SEMTİ olabiliyor. Mevlanakapı Ziyaretçi Merkezi "Holiday Inn"e, İstanbul
    Tasarım Müzesi "Süleymaniye hamamı"na, Yenibosna Kültür Merkezi "Vizyon Park
    Ofis Blokları"na bu yüzden bağlanmıştı — hepsinde ortak sözcük semt adıydı.

    Ölçüt: mekânın kendi adresinde ya da genel sözcük listesinde GEÇMEYEN bir
    ortak sözcük olmalı; yoksa en az iki ortak sözcük ("Şile Kültür Merkezi"
    gibi adı zaten yer + tür sözcüklerinden kurulu mekânlar için).
    """
    def sozcuk(s: str) -> set[str]:
        return set(re.findall(r"[a-zçğıöşü]{4,}", katla(s)))

    ortak = sozcuk(ad) & sozcuk(osm_ad)
    if not ortak:
        return False
    ayirt = ortak - GENEL_SOZCUK - {katla(i) for i in ILCELER} - sozcuk(adres)
    return bool(ayirt) or len(ortak) >= 2


def koordinat_al(c: dict | None, ad: str, adres: str = "") -> tuple[float, float, str] | tuple[None, None, None]:
    """Geocoder sonucunu kabul eder ya da eler.

    Ad örtüşmesi HER YOL için aranır — adresten bulunanlar için de. Bir kez
    gevşetip "adresten geldi, ilçesi doğruysa yeter" denendi ve üç sonucun üçü de
    başka binaydı: Casa Botter Galerisi yerine İstanbul Araştırmaları Enstitüsü,
    Gazhane Sesli Kütüphane yerine Hackerspace İstanbul. Nominatim adresi tam
    çözemediğinde en yakın ADLI noktayı döndürüyor; ilçe doğru çıkıyor ama bina
    yanlış. Yanlış konum göstermektense hiç göstermemek doğru.
    """
    if (c and ist_ici(c.get("lat"), c.get("lng"))
            and osm_ortusuyor(ad, c.get("osm_ad", ""), adres)):
        return c["lat"], c["lng"], c["kaynak"]
    return None, None, None


def _yesil_kayit(g: list[dict], ilce: str, tur: str, ad: str) -> dict:
    """Bir ya da birkaç poligon parçasından tek yeşil alan kaydı kurar."""
    alan = sum(x["alan_m2"] or 0 for x in g) or None
    noktali = [x for x in g if ist_ici(x.get("lat"), x.get("lng"))]
    if noktali and alan:
        # Ağırlık merkezi, parça alanlarıyla ağırlıklı ortalama.
        ag = sum(x["alan_m2"] or 0 for x in noktali) or 1
        lat = sum(x["lat"] * (x["alan_m2"] or 0) for x in noktali) / ag
        lng = sum(x["lng"] * (x["alan_m2"] or 0) for x in noktali) / ag
    elif noktali:
        lat = statistics.mean(x["lat"] for x in noktali)
        lng = statistics.mean(x["lng"] for x in noktali)
    else:
        lat = lng = None
    return {
        "ad": ad, "tur": tur, "kategori": "park", "ilce": ilce,
        "adres": "", "telefon": "", "saat": "", "gun": "", "acilis_yili": "",
        "lat": round(lat, 6) if lat else None, "lng": round(lng, 6) if lng else None,
        "koordinat_kaynak": "İBB Açık Veri — poligon ağırlık merkezi" if lat else None,
        "alan_m2": round(alan) if alan else None,
        "parca_sayisi": len(g),
        "kapali": False, "ucretsiz": True,
        "kaynak_ad": KAYNAK["yesil"][0], "kaynak_url": KAYNAK["yesil"][1],
    }


# "Müze Gazhane C Binası / L Binası / P Binası" üç mekân değil, tek mekânın üç binası;
# üçüne ayrı sayfa açmak %99 aynı üç sayfa demek. Ama aynı adresteki "Karikatür ve Mizah
# Müzesi" ile "İklim Müzesi" GERÇEKTEN ayrı müzeler. Ayrım adın kendisinde: yalnız sondaki
# bina/birim etiketiyle ayrışanlar birleşir.
BIRIM_EKI = re.compile(r"\s*(?:[A-ZÇĞİÖŞÜ]\s*)?(?:bina|binası|blok|blogu|bloğu|etap|kısım|kısmı)?\s*\d*\s*$", re.I)


def _birim_koku(ad: str) -> str:
    kok = re.sub(r"\s+(?:[A-ZÇĞİÖŞÜ]|\d+)\s+(?:Binası|Bina|Blok|Bloğu)\s*$", "", ad, flags=re.I)
    kok = re.sub(r"\s+\d+\s*$", "", kok)
    return katla(kok).strip()


def birimleri_birlestir(mekanlar: list[dict]) -> tuple[list[dict], int]:
    """Aynı adres + aynı tür + aynı ad kökü olan birimleri tek kayda indirir."""
    gruplar: dict[tuple, list[dict]] = defaultdict(list)
    for m in mekanlar:
        anahtar = (m["ilce"], (m.get("adres") or "").lower(), m["kategori"], _birim_koku(m["ad"]))
        gruplar[anahtar].append(m)
    sonuc, birlesen = [], 0
    for (_, _, _, kok), g in gruplar.items():
        if len(g) == 1 or not kok:
            sonuc.extend(g)
            continue
        birlesen += len(g) - 1
        ana = max(g, key=lambda x: len(x["ad"]))
        ortak = re.sub(r"\s+(?:[A-ZÇĞİÖŞÜ]|\d+)\s+(?:Binası|Bina|Blok|Bloğu)\s*$", "",
                       ana["ad"], flags=re.I)
        ortak = re.sub(r"\s+\d+\s*$", "", ortak).strip()
        ana = dict(ana, ad=ortak or ana["ad"],
                   birimler=sorted(x["ad"] for x in g))
        sonuc.append(ana)
    return sonuc, birlesen


AYRI_PARK_ORANI = 4.0     # mesafe / √alan bunun üstündeyse parçalar ayrı yerlerdir


def _dagilmis(g: list[dict]) -> bool:
    """Parçalar tek bir yerin bölümleri olamayacak kadar dağınık mı?"""
    pts = [(x["lat"], x["lng"]) for x in g if ist_ici(x.get("lat"), x.get("lng"))]
    alan = sum(x["alan_m2"] or 0 for x in g)
    if len(pts) < 2 or alan <= 0:
        return False
    en_uzak = max(
        math.hypot((a - c) * 111_320, (b - d) * 111_320 * math.cos(math.radians(a)))
        for i, (a, b) in enumerate(pts) for (c, d) in pts[i + 1:])
    return en_uzak > AYRI_PARK_ORANI * math.sqrt(alan)


# --------------------------------------------------------------------- yeşil alanlar
def yesil_alanlar(kayitlar: list[dict]) -> tuple[list[dict], dict]:
    """Yeşil alanları temizler ve parça parça girilmiş parkları birleştirir.

    Kaynakta bazı parklar poligon parçası olarak ayrı satırlarda: 'Orhangazi Şehir
    Parkı/doğu 1', '/doğu 2', '/batı 1', '/batı 2'. Birleştirilmezse aynı park dört
    ayrı sayfa oluyor ve hiçbirinin büyüklüğü gerçek değil.
    """
    ham = [k for k in kayitlar if k["tur"] in YESIL_TURLER]
    gruplar: dict[tuple, list[dict]] = defaultdict(list)
    for k in ham:
        ilce = ILCE_DUZELT.get(k["ilce"], k["ilce"])
        temel = re.sub(r"\s*[/\-]\s*(doğu|batı|kuzey|güney)?\s*\d+\s*$", "", k["ad"], flags=re.I)
        gruplar[(temiz_ad(temel).lower(), ilce, k["tur"])].append(k)

    sonuc, birlesen, bolunen = [], 0, 0
    for (_, ilce, tur), g in gruplar.items():
        # Aynı adı taşıyan parçalar her zaman tek yerin bölümü değil: Şile'de 1,4 km
        # arayla iki ayrı 350 m²'lik "Değirmençayır Mahalle Parkı" var. Ölçüt, parçalar
        # arası mesafenin alanın karakteristik boyuna (√alan) oranı: sahil boyunca uzanan
        # gerçek tek park 2-3 civarında kalıyor, ayrı parklar 5'in üstüne çıkıyor.
        if len(g) > 1 and _dagilmis(g):
            bolunen += len(g)
            for tekil in g:
                sonuc.append(_yesil_kayit([tekil], ilce, tur, temiz_ad(tekil["ad"])))
            continue
        if len(g) > 1:
            birlesen += len(g)
        temel_ad = temiz_ad(re.sub(r"\s*[/\-]\s*(doğu|batı|kuzey|güney)?\s*\d+\s*$", "",
                                   g[0]["ad"], flags=re.I))
        sonuc.append(_yesil_kayit(g, ilce, tur, temel_ad))
    sonuc.sort(key=lambda x: -(x["alan_m2"] or 0))
    return sonuc, {"ham": len(ham), "birlesen_satir": birlesen,
                   "bolunen_satir": bolunen, "sonuc": len(sonuc)}


# ------------------------------------------------------------------ müze / kütüphane
def muze_kutuphane(kayitlar: list[dict], koordinat: dict) -> list[dict]:
    out = []
    for k in kayitlar:
        if k["tur"] not in ("muze", "kutuphane"):
            continue
        ilce = ILCE_DUZELT.get(k["ilce"], k["ilce"])
        c = koordinat.get(f"{k['tur']}|{k['ad']}|{k['ilce']}")
        lat, lng, kkaynak = koordinat_al(c, k["ad"], k.get("adres") or "")
        out.append({
            "ad": ad_onar(temiz_ad(k["ad"])), "tur": k["tur"], "kategori": k["tur"], "ilce": ilce,
            "adres": adres_onar(k.get("adres")),
            "telefon": telefon_onar(k.get("telefon")),
            "saat": (k.get("saat") or "").strip(), "gun": gun_onar(k.get("gun")),
            "acilis_yili": str(k.get("acilis_yili") or "").strip(),
            "lat": lat, "lng": lng, "koordinat_kaynak": kkaynak, "alan_m2": None,
            "kapali": True,
            # Halk kütüphanesine giriş ücretsizdir; müzelerde ücret bilgisi kaynakta yok.
            "ucretsiz": True if k["tur"] == "kutuphane" else None,
            "kaynak_ad": KAYNAK[k["tur"]][0], "kaynak_url": KAYNAK[k["tur"]][1],
        })
    return out


# ------------------------------------------------------------------ kültür merkezleri
def kultur_merkezleri(koordinat: dict | None = None) -> list[dict]:
    """Kültür merkezleri. `koordinat` verilmezse kayıtlar koordinatsız döner —
    `koordinat.py` hedef listesini kurarken bu biçimde çağırıyor."""
    koordinat = koordinat or {}
    ws = load_workbook(HAM / "kultur_merkezleri.xlsx", read_only=True, data_only=True).active
    out = []
    for s in list(ws.iter_rows(values_only=True))[1:]:
        ad = " ".join(str(s[0] or "").split())
        if not ad:
            continue
        adres = adres_onar(str(s[1] or ""))
        ilce = ilce_bul(adres)
        if not ilce:
            continue
        saat = str(s[2] or "").strip().replace(".", ":")
        cocuk = str(s[3] or "").strip().upper()
        temiz = temiz_ad(tr_baslik(ad)).replace(" Ve ", " ve ")
        lat, lng, kkaynak = koordinat_al(koordinat.get(f"kultur|{temiz}|{ilce}"), temiz, adres)
        out.append({
            "ad": temiz,
            "tur": "kultur", "kategori": "kultur", "ilce": ilce, "adres": adres,
            "telefon": "", "saat": saat, "gun": "", "acilis_yili": "",
            "lat": lat, "lng": lng, "koordinat_kaynak": kkaynak, "alan_m2": None,
            "kapali": True, "ucretsiz": None,
            "cocuk_birimi": True if cocuk == "VAR" else (False if cocuk == "YOK" else None),
            "kaynak_ad": KAYNAK["kultur"][0], "kaynak_url": KAYNAK["kultur"][1],
        })
    return out


# -------------------------------------------------------------------- sosyal tesisler
def sosyal_tesisler() -> list[dict]:
    ws = load_workbook(HAM / "sosyal_tesis.xlsx", read_only=True, data_only=True).active
    out = []
    for s in list(ws.iter_rows(values_only=True))[1:]:
        ad = " ".join(str(s[0] or "").split())
        if not ad:
            continue
        lat, lng = _sayi(s[1]), _sayi(s[2])
        adres = adres_onar(str(s[3] or ""))
        ilce = ilce_bul(adres)
        if not ilce:
            continue
        out.append({
            "ad": temiz_ad(tr_baslik(ad)).replace(" Ve ", " ve "),
            "tur": "tesis", "kategori": "tesis",
            "ilce": ilce, "adres": adres, "telefon": "", "saat": "", "gun": "",
            "acilis_yili": "",
            "lat": lat if ist_ici(lat, lng) else None,
            "lng": lng if ist_ici(lat, lng) else None,
            "koordinat_kaynak": "İBB Açık Veri" if ist_ici(lat, lng) else None,
            "alan_m2": None, "kapali": None, "ucretsiz": None,
            "kaynak_ad": KAYNAK["tesis"][0], "kaynak_url": KAYNAK["tesis"][1],
        })
    return out


# ------------------------------------------------------------------- tiyatro sahneleri
def oyun_adi(ham: str) -> str:
    """Oyun adını yayına hazırlar: Türkçe başlık + bağlaç/kısaltma onarımı.

    Kaynak BÜYÜK HARF; yalnız tr_baslik'ten geçirmek "Bekçi İle Postacı",
    "Karagöz' Ün Uykusu", "İbbşt" gibi bozuk adlar bırakıyordu.
    """
    ad = temiz_ad(tr_baslik(" ".join((ham or "").split())))
    # Kesme işaretinden sonraki ek küçük yazılır ve araya boşluk girmez.
    ad = re.sub(r"'\s*([A-ZÇĞİÖŞÜ])", lambda m: "'" + tr_alt(m.group(1)), ad)
    return re.sub(r"\b(İbbşt|İbbst)\b", "İBBŞT", re.sub(r"\bMsgsü\b", "MSGSÜ", ad))


def tiyatro_sahneleri(ilce_cozucu) -> tuple[list[dict], dict]:
    """Çocuk oyunu sahnelenen İBB Şehir Tiyatroları sahneleri.

    Veri 2017-2023 arasını kapsıyor; GÜNCEL PROGRAM DEĞİL. Sayfada da böyle yazılır.
    Buradan çıkan tek iddia şudur: bu sahnede şu kadar çocuk oyunu seansı sahnelendi.
    """
    metin = (HAM / "tiyatro_oyun.csv").read_bytes().decode("utf-8", errors="replace")
    satirlar = list(csv.DictReader(io.StringIO(metin)))
    coc = [r for r in satirlar if "ocuk" in r["PLAY_CATEGORY"]]
    grup: dict[str, list[dict]] = defaultdict(list)
    for r in coc:
        if r["THEATER_NAME"].strip().upper() == "ONLINE":
            continue
        grup[r["THEATER_NAME"].strip().replace("Celãl", "Celâl")].append(r)

    out = []
    for ad, kayitlar in grup.items():
        lat = _sayi(kayitlar[-1]["LATITUDE"])
        lng = _sayi(kayitlar[-1]["LONGITUDE"])
        if not ist_ici(lat, lng):
            lat = lng = None
        ilce = ilce_cozucu(ad, lat, lng)
        if not ilce:
            continue
        oyunlar = sorted({oyun_adi(r["PLAY_NAME"]) for r in kayitlar})
        yillar = sorted({r["PLAY_DATE"][:4] for r in kayitlar})
        out.append({
            "ad": ad, "tur": "tiyatro", "kategori": "tiyatro", "ilce": ilce,
            "adres": "", "telefon": "", "saat": "", "gun": "", "acilis_yili": "",
            "lat": lat, "lng": lng,
            "koordinat_kaynak": "İBB Açık Veri" if lat else None, "alan_m2": None,
            "kapali": True, "ucretsiz": None,
            "cocuk_seans": len(kayitlar),
            "cocuk_izleyici": sum(int(r["NUMBER_OF_AUDIENCE"] or 0) for r in kayitlar),
            "cocuk_oyunlari": oyunlar[:25],
            "veri_yillari": f"{yillar[0]}–{yillar[-1]}",
            "kaynak_ad": KAYNAK["tiyatro"][0], "kaynak_url": KAYNAK["tiyatro"][1],
        })
    out.sort(key=lambda x: -x["cocuk_seans"])
    ozet = {"oyun_adi": len({r["PLAY_NAME"].strip() for r in coc}), "seans": len(coc),
            "yil": f"{min(r['PLAY_DATE'][:4] for r in coc)}–{max(r['PLAY_DATE'][:4] for r in coc)}"}
    return out, ozet


# Bir sahneye "çocuk tiyatrosu sahnesi" demek için altı yılda birkaç seans yetmez.
# Verideki dağılım keskin: 12 sahnede 61–216 seans, kalan dördünde 1–3.
COCUK_SEANS_ESIGI = 10


def tiyatro_ayikla(tiyatro: list[dict], kultur: list[dict]) -> list[dict]:
    """Eşiğin altındaki sahneleri ayrı sayfaya çıkarmaz; kültür merkeziyse oraya işler.

    Aynı bina hem kültür merkezi hem sahne olarak geçebiliyor (Kartal Bülent Ecevit
    Kültür Merkezi gibi); birleştirilmezse tek mekân için iki sayfa oluşurdu.
    """
    dizin = {katla(k["ad"]).replace("ibb ", "").strip(): k for k in kultur}
    kalan = []
    for t in tiyatro:
        anahtar = katla(t["ad"]).replace("ibb ", "").strip()
        eslesen = dizin.get(anahtar)
        if eslesen is not None:
            eslesen["cocuk_seans"] = eslesen.get("cocuk_seans", 0) + t["cocuk_seans"]
            eslesen["veri_yillari"] = t["veri_yillari"]
            continue
        if t["cocuk_seans"] >= COCUK_SEANS_ESIGI:
            kalan.append(t)
    return kalan


def tiyatro_noktalari() -> list[tuple[str, float, float]]:
    """Sahne adı + koordinat; ilçesi ad içinde geçmeyenler ters çözümlenecek."""
    metin = (HAM / "tiyatro_oyun.csv").read_bytes().decode("utf-8", errors="replace")
    son: dict[str, tuple[float, float]] = {}
    for r in csv.DictReader(io.StringIO(metin)):
        if "ocuk" not in r["PLAY_CATEGORY"] or r["THEATER_NAME"].strip().upper() == "ONLINE":
            continue
        ad = r["THEATER_NAME"].strip().replace("Celãl", "Celâl")
        lat, lng = _sayi(r["LATITUDE"]), _sayi(r["LONGITUDE"])
        if ist_ici(lat, lng):
            son[ad] = (lat, lng)
    return [(ad, lat, lng) for ad, (lat, lng) in son.items()
            if not any(re.search(r"\b" + re.escape(katla(i)) + r"\b", katla(ad)) for i in ILCELER)]


def ters_cozumle(noktalar: list[tuple[str, float, float]]) -> dict:
    if not noktalar:
        return {}
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from koordinat import ters_toplu
    return ters_toplu(noktalar)


# ------------------------------------------------------------------- koordinat denetimi
def koordinat_denetle(mekanlar: list[dict]) -> int:
    """İlçe ortancasından çok uzaktaki koordinatları işaretler.

    İstanbul ilçeleri küçük; 25 km'lik sapma (Silivri/Çatalca gibi geniş ilçeler hariç)
    yanlış eşleşme demektir. Kaynak değeri DEĞİŞTİRİLMEZ, yalnız işaretlenir.
    """
    genis = {"Silivri", "Çatalca", "Şile", "Arnavutköy", "Beykoz", "Büyükçekmece"}
    grup: dict[str, list[dict]] = defaultdict(list)
    for m in mekanlar:
        if m["lat"] is not None:
            grup[m["ilce"]].append(m)
    supheli = 0
    for m in mekanlar:
        if m["lat"] is None:
            m["koordinat_durum"] = "yok"
            continue
        g = grup[m["ilce"]]
        if len(g) < 3:
            m["koordinat_durum"] = "tekil"
            continue
        olat = statistics.median(x["lat"] for x in g)
        olng = statistics.median(x["lng"] for x in g)
        # 1 derece enlem ≈ 111 km; İstanbul enleminde 1 derece boylam ≈ 84 km.
        sapma = ((m["lat"] - olat) * 111) ** 2 + ((m["lng"] - olng) * 84) ** 2
        esik = (40 if m["ilce"] in genis else 25) ** 2
        if sapma <= esik:
            m["koordinat_durum"] = "tamam"
        else:
            m["koordinat_durum"] = "supheli"
            supheli += 1
    return supheli


def main() -> None:
    ham_indir()
    kayitlar = json.loads((DATA / "ibb_mekanlar.json").read_text(encoding="utf-8"))
    kyol = DATA / "koordinat.json"
    koordinat = {k: v for k, v in json.loads(kyol.read_text(encoding="utf-8")).items() if v} \
        if kyol.exists() else {}

    yesil, y_ozet = yesil_alanlar(kayitlar)
    mk = muze_kutuphane(kayitlar, koordinat)
    kultur = kultur_merkezleri(koordinat)
    tesis = sosyal_tesisler()

    # Tiyatro sahnesinin ilçesi kaynakta yok. Sahne adında ilçe geçiyorsa onu kullan;
    # geçmiyorsa koordinatı OSM'de ters çözümle. Eskiden "en yakın mekânın ilçesi"
    # denenmişti; İstanbul'un yoğunluğunda yanlış sonuç veriyor (Yenibosna sahnesini
    # Bahçelievler yerine Bağcılar'a yazmıştı).
    ters_ilce = ters_cozumle(tiyatro_noktalari())

    def tiyatro_ilce(ad: str, lat, lng):
        for i in ILCELER:
            if re.search(r"\b" + re.escape(katla(i)) + r"\b", katla(ad)):
                return i
        d = ters_ilce.get(ad)
        return ILCE_DUZELT.get(d, d) if d in ILCELER or d in ILCE_DUZELT else (
            ilce_bul(d) if d else None)

    tiyatro, t_ozet = tiyatro_sahneleri(tiyatro_ilce)
    tiyatro = tiyatro_ayikla(tiyatro, kultur)

    # İlçe hakemliği: OSM ters çözümü ile İBB kaydı çeliştiğinde coğrafyaya sor.
    iyol = DATA / "ilce_osm.json"
    ilce_osm = json.loads(iyol.read_text(encoding="utf-8")) if iyol.exists() else {}
    duzeltilen_ilce = ilce_karar(yesil + mk + kultur + tesis + tiyatro, ilce_osm) if ilce_osm else 0

    sayfali_yesil = [y for y in yesil
                     if y["tur"] != "park" or (y["alan_m2"] or 0) >= PARK_SAYFA_ESIGI]
    mekanlar, birlesen_birim = birimleri_birlestir(sayfali_yesil + mk + kultur + tesis + tiyatro)
    for m in mekanlar:
        m["yaka"] = "anadolu" if m["ilce"] in ANADOLU else "avrupa"
    for y in yesil:
        y["yaka"] = "anadolu" if y["ilce"] in ANADOLU else "avrupa"

    supheli = koordinat_denetle(mekanlar)

    (DATA / "mekanlar.json").write_text(
        json.dumps(mekanlar, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "yesil_alanlar.json").write_text(
        json.dumps(yesil, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "tiyatro_ozet.json").write_text(
        json.dumps(t_ozet, ensure_ascii=False, indent=1), encoding="utf-8")

    bilinmeyen = {m["ilce"] for m in mekanlar} - set(ILCELER)
    print(f"yeşil alan  : {y_ozet['ham']} ham satır -> {y_ozet['sonuc']} alan "
          f"({y_ozet['birlesen_satir']} satır birleşti, "
          f"{y_ozet['bolunen_satir']} satır ayrı yer olarak bölündü)")
    print(f"  sayfalı   : {len(sayfali_yesil)} (park eşiği {PARK_SAYFA_ESIGI:,} m²)")
    print(f"müze/kütüph.: {len(mk)}  (koordinatlı {sum(1 for m in mk if m['lat'])})")
    print(f"kültür merk.: {len(kultur)}  (çocuk birimi olan {sum(1 for k in kultur if k.get('cocuk_birimi'))})")
    print(f"sosyal tesis: {len(tesis)}  (koordinatlı {sum(1 for m in tesis if m['lat'])})")
    print(f"tiyatro sah.: {len(tiyatro)}  ({t_ozet['seans']} çocuk oyunu seansı, "
          f"{t_ozet['oyun_adi']} farklı oyun, {t_ozet['yil']})")
    print(f"aynı binanın birimleri birleşti: {birlesen_birim}")
    print(f"TOPLAM sayfalı mekân: {len(mekanlar)} | koordinatlı "
          f"{sum(1 for m in mekanlar if m['lat'])} | şüpheli koordinat {supheli}")
    print(f"ilçe düzeltmesi (OSM hakemliği): {duzeltilen_ilce}")
    print(f"ilçe: {len({m['ilce'] for m in mekanlar})}"
          + (f"  UYARI bilinmeyen ilçe: {bilinmeyen}" if bilinmeyen else ""))
    print("kategori:", dict(Counter(m["kategori"] for m in mekanlar)))


if __name__ == "__main__":
    main()
