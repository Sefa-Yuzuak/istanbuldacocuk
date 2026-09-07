# -*- coding: utf-8 -*-
"""Rehberleri ve düz sayfaları VERİDEN üretir -> data/rehberler.json, data/sayfalar.json

Sayıları elle yazmak, veri yenilendiğinde metnin sessizce yanlış olması demek.
Bu yüzden her sayı `data/mekanlar.json` ve `data/yesil_alanlar.json` okunarak hesaplanır.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DATA = KOK / "data"

ANADOLU = {"Adalar", "Ataşehir", "Beykoz", "Çekmeköy", "Kadıköy", "Kartal", "Maltepe",
           "Pendik", "Sancaktepe", "Sultanbeyli", "Şile", "Tuzla", "Ümraniye", "Üsküdar"}

# derle.py ile aynı etiketler: .title() "kent_ormani"yi "Kent Ormani" yapıyordu.
ALT_TUR = {"park": "Park", "koru": "Koru", "mesire": "Mesire alanı",
           "kent_ormani": "Kent ormanı", "hatira_ormani": "Hatıra ormanı"}

SEHIR_TIYATROLARI = "https://sehirtiyatrolari.ibb.istanbul/tr"
PORTAL = "https://data.ibb.gov.tr/"


def binlik(n) -> str:
    return f"{n or 0:,.0f}".replace(",", ".")


def main() -> None:
    mekanlar = json.loads((DATA / "mekanlar.json").read_text(encoding="utf-8"))
    yesil = json.loads((DATA / "yesil_alanlar.json").read_text(encoding="utf-8"))
    site = json.loads((DATA / "site.json").read_text(encoding="utf-8"))

    # Fotoğraf kaynakları da sayfada sayıyla anlatılıyor; sayılar veriden gelsin ki
    # foto hattı her çalıştığında metin kendiliğinden güncellensin.
    fyol = DATA / "foto.json"
    fotolar = [v for v in json.loads(fyol.read_text(encoding="utf-8")).values() if v] \
        if fyol.exists() else []
    foto_say = {k: sum(1 for f in fotolar if f.get("kaynak") == k)
                for k in ("wikipedia", "commons", "google")}

    tiyatro = sorted([m for m in mekanlar if m["kategori"] == "tiyatro"],
                     key=lambda m: -m["cocuk_seans"])
    kutuphane = [m for m in mekanlar if m["kategori"] == "kutuphane"]
    muze = [m for m in mekanlar if m["kategori"] == "muze"]
    kultur = [m for m in mekanlar if m["kategori"] == "kultur"]
    tesis = [m for m in mekanlar if m["kategori"] == "tesis"]
    park = [m for m in mekanlar if m["kategori"] == "park"]

    toplam_seans = sum(m["cocuk_seans"] for m in tiyatro)
    toplam_izleyici = sum(m.get("cocuk_izleyici") or 0 for m in tiyatro)
    oyun_adlari = sorted({o for m in tiyatro for o in m.get("cocuk_oyunlari", [])})
    yillar = tiyatro[0]["veri_yillari"] if tiyatro else ""

    yaka_ozet = {"anadolu": {"alan": 0, "sayi": 0, "ilce": set()},
                 "avrupa": {"alan": 0, "sayi": 0, "ilce": set()}}
    ilce_alan: dict[str, int] = defaultdict(int)
    ilce_sayi: dict[str, int] = defaultdict(int)
    for y in yesil:
        k = "anadolu" if y["ilce"] in ANADOLU else "avrupa"
        yaka_ozet[k]["alan"] += y["alan_m2"] or 0
        yaka_ozet[k]["sayi"] += 1
        yaka_ozet[k]["ilce"].add(y["ilce"])
        ilce_alan[y["ilce"]] += y["alan_m2"] or 0
        ilce_sayi[y["ilce"]] += 1
    en_yesil = sorted(ilce_alan.items(), key=lambda t: -t[1])[:12]
    buyuk_park = sorted(yesil, key=lambda y: -(y["alan_m2"] or 0))[:25]

    kaynak_ibb = {"ad": "İBB Açık Veri Portalı", "url": PORTAL}

    rehberler = [
        {
            "slug": "istanbulda-cocuk-tiyatrosu",
            "baslik": "İstanbul'da Çocuk Tiyatrosu: Hangi Sahnede Oynanıyor?",
            "ozet": f"İBB Şehir Tiyatroları'nın açık verisine göre çocuk oyunları "
                    f"{len(tiyatro)} sahnede oynanıyor. Sahneler, ilçeleri ve kaç çocuk "
                    f"oyunu seansı sahnelendiği.",
            "cevap": f"İBB Şehir Tiyatroları'nın {yillar} dönemine ait açık veri kayıtlarında "
                     f"{binlik(toplam_seans)} çocuk oyunu seansı görünüyor; bu seanslar "
                     f"{len(tiyatro)} sahnede, {len(oyun_adlari)} farklı oyunla gerçekleşmiş. "
                     f"En çok çocuk oyunu sahnelenen yer {tiyatro[0]['ad']} "
                     f"({tiyatro[0]['ilce']}).",
            "bolumler": [
                {"baslik": "Çocuk oyunu sahnelenen sahneler",
                 "paragraflar": [
                     "Aşağıdaki tablo İBB Şehir Tiyatroları'nın kendi açık veri setinden "
                     "üretildi. Sayılar, o sahnede kaydı bulunan çocuk oyunu seanslarının "
                     "toplamıdır — kaç ayrı oyun oynandığını değil, kaç kez perde açıldığını "
                     "gösterir.",
                 ],
                 "tablo": {
                     "basliklar": ["Sahne", "İlçe", "Çocuk oyunu seansı", "İzleyici"],
                     "satirlar": [[m["ad"], m["ilce"], binlik(m["cocuk_seans"]),
                                   binlik(m.get("cocuk_izleyici"))] for m in tiyatro]},
                 "uyari": f"Bu veri {yillar} dönemini kapsar ve GÜNCEL PROGRAM DEĞİLDİR. "
                          f"Hangi oyunun bugün hangi sahnede olduğunu ve bilet durumunu "
                          f"İBB Şehir Tiyatroları'nın kendi sitesinden öğrenin."},
                {"baslik": "Bilet ve program nereden öğrenilir?",
                 "paragraflar": [
                     "İBB Şehir Tiyatroları'nın oyun takvimi ve bilet satışı kurumun kendi "
                     "sitesi üzerinden yürüyor. Açık veri seti yalnızca geçmiş sezonların "
                     "kaydını içerdiği için burada güncel takvim yayımlanmıyor; uydurmak "
                     "yerine kaynağa yönlendiriyoruz.",
                     "Sahnelerin konumu ve hangi ilçede olduğu bu sitedeki sahne "
                     "sayfalarında koordinatıyla birlikte duruyor.",
                 ]},
                {"baslik": "Verideki çocuk oyunlarından bazıları",
                 "paragraflar": [
                     "Açık veri setinde çocuk kategorisinde kayıtlı "
                     f"{len(oyun_adlari)} farklı oyun adı geçiyor. Bir bölümü:",
                 ],
                 "liste": oyun_adlari[:30]},
            ],
            "sss": [
                {"s": "İstanbul'da çocuk tiyatrosu nerede var?",
                 "c": f"İBB Şehir Tiyatroları'nın açık verisine göre çocuk oyunları "
                      f"{len(tiyatro)} sahnede oynandı: "
                      + ", ".join(f"{m['ad']} ({m['ilce']})" for m in tiyatro[:6])
                      + " ve diğerleri."},
                {"s": "Çocuk tiyatrosu bileti ne kadar?",
                 "c": "Bilet fiyatı açık veri setinde yer almıyor. Güncel fiyat ve "
                      "kontenjan için İBB Şehir Tiyatroları'nın kendi sitesine bakın."},
                {"s": "Bu liste güncel program mı?",
                 "c": f"Hayır. Veri {yillar} dönemine aittir ve hangi sahnede çocuk oyunu "
                      f"geleneği olduğunu gösterir. Güncel takvim için kurumun sitesine bakın."},
            ],
            "kaynaklar": [
                {"ad": "İBB Açık Veri Portalı — Şehir Tiyatroları Veri Seti",
                 "url": PORTAL + "dataset/sehir-tiyatrolari-veri-seti"},
                {"ad": "İBB Şehir Tiyatroları (güncel program ve bilet)",
                 "url": SEHIR_TIYATROLARI},
            ],
        },
        {
            "slug": "ibb-kutuphaneleri-cocukla",
            "baslik": f"Çocukla Kütüphane: İstanbul'daki {len(kutuphane)} İBB Kütüphanesi",
            "ozet": f"İBB'ye bağlı {len(kutuphane)} halk kütüphanesinin ilçesi, adresi ve "
                    f"çalışma saatleri. Giriş ve üyelik ücretsiz; yağmurlu günün en ucuz "
                    f"planı.",
            "cevap": f"İstanbul'da İBB'ye bağlı {len(kutuphane)} halk kütüphanesi var ve "
                     f"hepsinde giriş ücretsizdir. Kütüphaneler "
                     f"{len({m['ilce'] for m in kutuphane})} ilçeye yayılmış durumda; "
                     f"{sum(1 for m in kutuphane if m.get('saat'))} tanesinin çalışma saati "
                     f"İBB'nin açık veri kaydında yer alıyor.",
            "bolumler": [
                {"baslik": "Neden kütüphane?",
                 "paragraflar": [
                     "Çocukla dışarı çıkmanın maliyeti hızla artıyor: bir oyun alanı, bir "
                     "kafe, iki bilet derken hafta sonu pahalıya geliyor. Halk kütüphanesi "
                     "bunun tersi — kapalı, ısıtılan, sessiz ve tamamen ücretsiz bir mekân.",
                     "İBB kütüphanelerinde giriş ve üyelik için ücret alınmaz. Ödünç kitap "
                     "almak için üyelik gerekir, içeride okumak için gerekmez. Çocuk bölümü "
                     "ve etkinlik takvimi kütüphaneden kütüphaneye değişir. Hangi "
                     "kütüphanede çocuk bölümü olduğu İBB'nin açık veri setinde yer "
                     "almıyor; bu yüzden burada da yazmıyoruz — gitmeden önce aramanız en "
                     "doğrusu, bu sitedeki her kütüphane sayfasında telefon numarası var.",
                 ]},
                {"baslik": "Hangi ilçede kaç kütüphane var?",
                 "paragraflar": ["İBB'nin açık veri kaydına göre dağılım:"],
                 "tablo": {
                     "basliklar": ["İlçe", "Kütüphane sayısı"],
                     "satirlar": [[ad, str(sayi)] for ad, sayi in sorted(
                         [(i, sum(1 for m in kutuphane if m["ilce"] == i))
                          for i in {m["ilce"] for m in kutuphane}],
                         key=lambda t: (-t[1], t[0]))]}},
                {"baslik": "Kütüphaneye çocukla gitmeden önce",
                 "liste": [
                     "Çalışma günü ve saati kütüphaneye göre değişiyor; sayfadaki saat "
                     "bilgisi İBB kaydından geliyor, resmî tatillerde değişebilir.",
                     "Çocuk bölümü olup olmadığı açık veri setinde yer almıyor. Telefonla "
                     "sormak birkaç dakika sürüyor ve boşa yolculuğu önlüyor.",
                     "Ödünç almak isterseniz üyelik için kimlik gerekir.",
                 ]},
            ],
            "sss": [
                {"s": "İBB kütüphaneleri ücretli mi?",
                 "c": "Hayır. İBB halk kütüphanelerinde giriş ve üyelik ücretsizdir."},
                {"s": "İstanbul'da kaç İBB kütüphanesi var?",
                 "c": f"İBB'nin açık veri kaydında {len(kutuphane)} kütüphane bulunuyor "
                      f"({site['veri_tarihi']} itibarıyla)."},
                {"s": "Kütüphaneye kaç yaşındaki çocukla gidilir?",
                 "c": "Yaş sınırı yok; ancak kütüphane sessiz bir ortamdır. Çocuk bölümü "
                      "olan kütüphaneler bebek ve okul öncesi için daha rahattır — hangi "
                      "kütüphanede çocuk bölümü olduğunu telefonla teyit edin."},
            ],
            "kaynaklar": [
                {"ad": "İBB Açık Veri Portalı — İBB Kütüphaneleri Lokasyon, Çalışma Gün ve Saatleri",
                 "url": PORTAL + "dataset/ibb-kutuphaneleri-lokasyon-calisma-gun-ve-saatleri"},
            ],
        },
        {
            "slug": "istanbulun-en-buyuk-parklari",
            "baslik": "İstanbul'un En Büyük Parkları ve Koruları",
            "ozet": f"İBB'nin yeşil alan envanterindeki {binlik(len(yesil))} kaydın en "
                    f"büyükleri: hangi park kaç metrekare, hangi ilçede.",
            "cevap": f"İBB'nin yeşil alan envanterinde {binlik(len(yesil))} park, koru ve "
                     f"mesire alanı kayıtlı; toplam alan "
                     f"{binlik(sum(y['alan_m2'] or 0 for y in yesil))} m². En büyüğü "
                     f"{buyuk_park[0]['ad']} ({buyuk_park[0]['ilce']}, "
                     f"{binlik(buyuk_park[0]['alan_m2'])} m²).",
            "bolumler": [
                {"baslik": "En büyük 25 yeşil alan",
                 "paragraflar": [
                     "Büyüklükler, İBB'nin yayımladığı poligon geometrilerinden hesaplandı. "
                     "Kaynakta bazı parklar birden çok parça olarak kayıtlı; bu parçalar "
                     "birleştirilip toplam alan verildi, yoksa aynı park listede birkaç kez "
                     "ve gerçek boyutunun altında görünürdü.",
                 ],
                 "tablo": {
                     "basliklar": ["Yeşil alan", "İlçe", "Tür", "Büyüklük"],
                     "satirlar": [[y["ad"], y["ilce"], ALT_TUR.get(y["tur"], "Yeşil alan"),
                                   binlik(y["alan_m2"]) + " m²"] for y in buyuk_park]}},
                {"baslik": "Büyük park her zaman iyi park mı?",
                 "paragraflar": [
                     "Değil. Bir kent ormanının 2 km² olması, çocuklu bir aile için yürüyüş "
                     "mesafesinde oyun grubu, tuvalet ya da gölge olduğu anlamına gelmiyor. "
                     "Bu listedeki büyüklük ölçülebilir bir gerçek; mekânın çocuğa "
                     "uygunluğu ise gidip görmeden söylenemez, biz de puan vermiyoruz.",
                     "Mahallenizdeki parkı arıyorsanız ilçe park listelerine bakın: orada "
                     "büyüklüğüne bakılmaksızın İBB kaydındaki her yeşil alan var.",
                 ]},
            ],
            "sss": [
                {"s": "İstanbul'un en büyük parkı hangisi?",
                 "c": f"İBB yeşil alan envanterine göre {buyuk_park[0]['ad']} "
                      f"({buyuk_park[0]['ilce']}), {binlik(buyuk_park[0]['alan_m2'])} m²."},
                {"s": "İstanbul'da kaç park var?",
                 "c": f"İBB'nin park, koru, mesire ve kent ormanı envanterinde "
                      f"{binlik(len(yesil))} kayıt bulunuyor. Bu sayı yalnızca İBB "
                      f"sorumluluğundaki alanları kapsar; ilçe belediyelerinin parkları "
                      f"ayrı kayıtlarda tutulur."},
                {"s": "Park girişleri ücretli mi?",
                 "c": "İBB'nin yeşil alan envanterindeki parklar, korular ve kent ormanları "
                      "halka açıktır ve girişleri ücretsizdir. Otopark, tesis veya büfe "
                      "hizmetleri ücretli olabilir."},
            ],
            "kaynaklar": [
                {"ad": "İBB Açık Veri Portalı — Park, Bahçe ve Yeşil Alan Verileri",
                 "url": PORTAL + "dataset/park-bahce-ve-yesil-alanlar-dairesi-baskanligi-verileri"},
            ],
        },
        {
            "slug": "anadolu-mu-avrupa-mi-yesil-alan",
            "baslik": "Anadolu Yakası mı, Avrupa Yakası mı? İlçe İlçe Yeşil Alan",
            "ozet": "İBB verisiyle iki yakanın karşılaştırması: hangi yakada kaç park var, "
                    "hangi ilçede ne kadar yeşil alan.",
            "cevap": (f"İBB yeşil alan envanterinde Avrupa yakasında "
                      f"{binlik(yaka_ozet['avrupa']['sayi'])} kayıt "
                      f"({binlik(yaka_ozet['avrupa']['alan'])} m²), Anadolu yakasında "
                      f"{binlik(yaka_ozet['anadolu']['sayi'])} kayıt "
                      f"({binlik(yaka_ozet['anadolu']['alan'])} m²) bulunuyor. "
                      f"Avrupa yakası 25, Anadolu yakası 14 ilçeden oluşuyor; bu yüzden "
                      f"toplam yerine ilçe başına bakmak daha anlamlı."),
            "bolumler": [
                {"baslik": "En çok yeşil alanı olan ilçeler",
                 "paragraflar": [
                     "Aşağıdaki tablo, İBB'nin envanterinde kayıtlı alanların ilçe "
                     "toplamlarıdır. Bir uyarı: bu sayı ilçenin toplam yeşil alanı değil, "
                     "İBB sorumluluğundaki alanların toplamıdır — ilçe belediyelerinin "
                     "parkları bu veri setinde yok.",
                 ],
                 "tablo": {
                     "basliklar": ["İlçe", "Yaka", "Kayıt", "Toplam alan"],
                     "satirlar": [[ad, "Anadolu" if ad in ANADOLU else "Avrupa",
                                   str(ilce_sayi[ad]), binlik(alan) + " m²"]
                                  for ad, alan in en_yesil]}},
                {"baslik": "Sayı ile deneyim aynı şey değil",
                 "paragraflar": [
                     "Bir ilçenin toplam yeşil alanı yüksek çıkabilir çünkü sınırları içinde "
                     "tek bir dev kent ormanı vardır; bu, oturduğunuz mahallede yürüme "
                     "mesafesinde park olduğu anlamına gelmez. Kendi mahallenize bakmak için "
                     "ilçe park listelerini kullanın — orada her kaydın büyüklüğü ve konumu var.",
                 ]},
            ],
            "sss": [
                {"s": "Hangi yakada daha çok park var?",
                 "c": f"İBB envanterinde Avrupa yakasında {binlik(yaka_ozet['avrupa']['sayi'])}, "
                      f"Anadolu yakasında {binlik(yaka_ozet['anadolu']['sayi'])} yeşil alan "
                      f"kayıtlı. Avrupa yakasında 25, Anadolu yakasında 14 ilçe bulunduğu "
                      f"için bu fark tek başına bir üstünlük göstergesi değil."},
                {"s": "En çok yeşil alana sahip ilçe hangisi?",
                 "c": f"İBB kaydına göre {en_yesil[0][0]} — {binlik(en_yesil[0][1])} m². "
                      f"Bu yalnızca İBB sorumluluğundaki alanları kapsar."},
            ],
            "kaynaklar": [
                {"ad": "İBB Açık Veri Portalı — Park, Bahçe ve Yeşil Alan Verileri",
                 "url": PORTAL + "dataset/park-bahce-ve-yesil-alanlar-dairesi-baskanligi-verileri"},
            ],
        },
    ]

    sayfalar = [
        {
            "url": "/hakkinda/", "baslik": "Hakkında ve Yöntem",
            "meta": "İstanbulda Çocuk nasıl derleniyor: veri kaynakları, kaynak dosyalardaki "
                    "hataların nasıl onarıldığı ve neden mekânlara puan verilmediği.",
            "bolumler": [
                {"paragraflar": [
                    "İstanbulda Çocuk, İstanbul'da çocuklu ailelerin gidebileceği yerleri "
                    "resmî açık veriden derleyen bağımsız bir rehberdir. Hiçbir kurumu "
                    "temsil etmez, rezervasyon almaz, ücret tahsil etmez.",
                ]},
                {"baslik": "Neden puan yok?",
                 "paragraflar": [
                     "Benzer sitelerin çoğu her mekâna bir puan verir. Bir mekânı gezmeden, "
                     "ölçmeden ona 8,4/10 vermek okuru yanıltır: puan, olmayan bir "
                     "değerlendirmeyi varmış gibi gösterir.",
                     f"Bu sitedeki {len(mekanlar)} kaydın tamamı resmî açık veriden gelir "
                     "ve puanlanmamıştır. Bunun yerine ölçülebilir bilgi yayımlıyoruz: "
                     "alan kaç metrekare, hangi gün ve saatte açık, girişi ücretsiz mi, "
                     "kapalı alan mı, koordinatı ne.",
                 ]},
                {"baslik": "Kaynak dosyalarda bulunan ve onarılan hatalar",
                 "paragraflar": [
                     "Açık veri her zaman temiz gelmiyor. Bulduğumuz ve onardığımız "
                     "sorunlar, ne yaptığımızla birlikte:",
                 ],
                 "liste": [
                     "Bazı parklar poligon parçası olarak ayrı satırlarda kayıtlı "
                     "(“… Parkı/doğu 1”, “/doğu 2” gibi). Birleştirilmeseydi aynı park "
                     "birkaç kez ve gerçek boyutunun altında görünecekti; parçalar "
                     "toplanarak tek kayda indirildi.",
                     "Sosyal tesis dosyasında koordinatların ondalık ayracı düşmüş "
                     "(41057845 gibi). Değerler onarıldı ve İstanbul sınır kutusuna göre "
                     "doğrulandı.",
                     "Müze ve kütüphane veri setlerinde koordinat sütunu yok, yalnız adres "
                     "var. Bu kayıtların konumu OpenStreetMap üzerinden bulundu ve "
                     "bulunanlarda koordinat kaynağı sayfada açıkça yazılıyor; "
                     "bulunamayanlarda koordinat boş bırakıldı.",
                     "Şehir Tiyatroları veri setinde sahnenin ilçesi yok. İlçe, sahne adında "
                     "geçiyorsa oradan, geçmiyorsa koordinatın OpenStreetMap'te ters "
                     "çözümlenmesiyle belirlendi.",
                     "Adres alanlarında ilçe çıkarımı yanıltıcı olabiliyor: “Arnavutköy "
                     "Sosyal Tesisi” Arnavutköy ilçesinde değil, Beşiktaş'ın Arnavutköy "
                     "mahallesinde. Bu yüzden ilçe her zaman adresin ilçe alanından alınır, "
                     "mekânın adından değil.",
                     "Koordinatı kendi ilçesinin ortancasından çok uzağa düşen kayıtlar "
                     "şüpheli olarak işaretlenir ve haritaya konmaz; kaynak veri değiştirilmez.",
                     "İlçe bilgisi OpenStreetMap ters çözümüyle karşılaştırılır. İkisi de "
                     "yanılabiliyor: İBB Taksim Gezi Parkı'nı Şişli yazmış (park Beyoğlu'nda), "
                     "OSM ise Burgazada'daki bir kaydı Fatih sanıyor. Bu yüzden anlaşmazlıkta "
                     "hakem coğrafyadır — kayıt hangi ilçenin kayıt kümesine belirgin biçimde "
                     "daha yakın düşüyorsa o kabul edilir, aksi hâlde İBB'nin değeri korunur.",
                     "Poligonların iç halkaları (park içindeki gölet, bina, yol adası) alandan "
                     "düşülür. Düşülmediğinde 16 kaydın büyüklüğü olduğundan fazla görünüyordu; "
                     "Menekşe Deresi Parkı'nda fark 33.000 m²ydi.",
                     "OpenStreetMap'ten gelen koordinat, mekân adıyla hiçbir ayırt edici sözcük "
                     "paylaşmıyorsa kullanılmaz. Adres tabanlı arama bazen çevredeki başka bir "
                     "yeri döndürüyor (bir kütüphane için yağlama cihazları mağazası gibi); "
                     "yaklaşık konum göstermektense hiç göstermemeyi seçiyoruz.",
                 ]},
                {"baslik": "Hangi mekânın kendi sayfası var?",
                 "paragraflar": [
                     f"İBB müzeleri ({len(muze)}), kütüphaneleri ({len(kutuphane)}), kültür "
                     f"merkezleri ({len(kultur)}), sosyal tesisleri ({len(tesis)}) ve çocuk "
                     f"oyunu sahnelenen tiyatro sahneleri ({len(tiyatro)}) için ayrı sayfa "
                     f"açılır. Yeşil alanlarda eşik 50.000 m²'dir; bu büyüklüğün üzerindeki "
                     f"{len(park)} park, koru ve kent ormanı kendi sayfasını alır.",
                     f"Daha küçük mahalle parkları için ayrı sayfa açmıyoruz: onlar hakkında "
                     f"doğrulanmış olarak söyleyebileceğimiz her şey (ad, tür, büyüklük, "
                     f"konum) ilçe park listelerinde zaten var. Envanterin tamamı — "
                     f"{binlik(len(yesil))} kayıt — o listelerde yer alıyor.",
                 ]},
                {"baslik": "Düzeltme ve iletişim",
                 "paragraflar": [
                     f"Bir bilgi yanlışsa ya da bir mekân kapandıysa {site['eposta']} "
                     "adresine yazın. Düzeltmeleri kaynağıyla birlikte yaparız; kaynağı "
                     "olmayan bir bilgiyi yayımlamayız.",
                 ]},
            ],
        },
        {
            "url": "/kaynaklar/", "baslik": "Veri Kaynakları",
            "meta": "İstanbulda Çocuk'taki her bilginin geldiği resmî veri setleri ve "
                    "bağlantıları.",
            "bolumler": [
                {"paragraflar": [
                    "Sitedeki tüm mekân bilgisi aşağıdaki resmî veri setlerinden derlenmiştir. "
                    f"Son doğrulama tarihi: {site['veri_tarihi']}.",
                ]},
                {"baslik": "İBB Açık Veri Portalı veri setleri",
                 "baglar": [
                     {"ad": "Park, Bahçe ve Yeşil Alan Verileri",
                      "url": PORTAL + "dataset/park-bahce-ve-yesil-alanlar-dairesi-baskanligi-verileri",
                      "not": f"{binlik(len(yesil))} yeşil alan kaydı, poligon geometrisiyle"},
                     {"ad": "İBB Müzeleri Lokasyon, Çalışma Gün ve Saatleri",
                      "url": PORTAL + "dataset/ibb-muzeleri-lokasyon-calisma-gun-ve-saatleri",
                      "not": f"{len(muze)} müze"},
                     {"ad": "İBB Kütüphaneleri Lokasyon, Çalışma Gün ve Saatleri",
                      "url": PORTAL + "dataset/ibb-kutuphaneleri-lokasyon-calisma-gun-ve-saatleri",
                      "not": f"{len(kutuphane)} kütüphane"},
                     {"ad": "Kültür Merkezleri Veri Seti",
                      "url": PORTAL + "dataset/kultur-merkezleri-veri-seti",
                      "not": f"{len(kultur)} kültür merkezi, çocuk birimi bilgisiyle"},
                     {"ad": "Sosyal Tesis Konumları",
                      "url": PORTAL + "dataset/sosyal-tesis-konumlari",
                      "not": f"{len(tesis)} sosyal tesis"},
                     {"ad": "Şehir Tiyatroları Veri Seti",
                      "url": PORTAL + "dataset/sehir-tiyatrolari-veri-seti",
                      "not": f"{binlik(toplam_seans)} çocuk oyunu seansı kaydı ({yillar})"},
                 ]},
                {"baslik": "Yardımcı kaynaklar",
                 "baglar": [
                     {"ad": "OpenStreetMap / Nominatim",
                      "url": "https://www.openstreetmap.org/copyright",
                      "not": "Müze ve kütüphanelerin koordinatları ile tiyatro sahnelerinin "
                             "ilçe bilgisi buradan tamamlandı"},
                     {"ad": "İBB Şehir Tiyatroları — güncel program ve bilet",
                      "url": SEHIR_TIYATROLARI, "not": "Açık veri güncel takvim içermiyor"},
                 ]},
                {"baslik": "Fotoğraflar",
                 "paragraflar": [
                     f"{len(mekanlar)} mekânın {len(fotolar)} tanesinde gerçek fotoğraf var. "
                     f"Stok görsel ya da temsilî fotoğraf kullanmıyoruz: eşleşmeden emin "
                     f"olamadığımız mekân, fotoğraf yerine tür simgesiyle kalıyor.",
                     f"Kaynak dağılımı: Google Haritalar {foto_say['google']}, "
                     f"Wikimedia Commons {foto_say['commons']}, "
                     f"Wikipedia {foto_say['wikipedia']}. Her fotoğrafın altında çekenin adı, "
                     f"lisansı ve kaynak bağlantısı yazılıdır.",
                 ],
                 "baglar": [
                     {"ad": "Google Haritalar kullanım koşulları",
                      "url": "https://www.google.com/intl/tr/help/terms_maps/",
                      "not": "Google Haritalar fotoğrafları, çeken kişinin adıyla birlikte "
                             "ve kaynağına bağlantı verilerek gösteriliyor"},
                     {"ad": "Wikimedia Commons — yeniden kullanım",
                      "url": "https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
                      "not": "Commons görselleri kendi lisanslarıyla, yazar adı belirtilerek kullanılıyor"},
                 ]},
                {"baslik": "Bu sitenin verisi",
                 "paragraflar": [
                     "Derlenmiş veri açık biçimde yayımlanıyor; kullanabilirsiniz.",
                 ],
                 "baglar": [
                     {"ad": "Mekânlar (JSON)", "url": "/veri/mekanlar.json"},
                     {"ad": "Yeşil alan envanteri (JSON)", "url": "/veri/yesil-alanlar.json"},
                 ]},
            ],
        },
        {
            "url": "/gizlilik/", "baslik": "Gizlilik ve Çerezler",
            "meta": "İstanbulda Çocuk hangi verileri işliyor, hangi çerezler kullanılıyor, "
                    "reklam ve ölçümleme nasıl çalışıyor.",
            "bolumler": [
                {"paragraflar": [
                    "Bu site statik sayfalardan oluşur. Üyelik yoktur, form yoktur; "
                    "adınızı, e-postanızı ya da konumunuzu bir sunucuda saklamayız.",
                ]},
                {"baslik": "Konum bilgisi",
                 "paragraflar": [
                     "Harita sayfasındaki “Bana en yakınlar” düğmesine basarsanız tarayıcınız "
                     "konumunuzu ister. Konum yalnızca tarayıcınızın içinde, mesafe "
                     "hesaplamak için kullanılır; hiçbir sunucuya gönderilmez ve saklanmaz. "
                     "Düğmeye basmazsanız konum hiç istenmez.",
                 ]},
                {"baslik": "Reklamlar ve çerezler",
                 "paragraflar": [
                     "Sitede Google AdSense reklamları gösterilir. Google ve iş ortakları, "
                     "reklamları göstermek ve ölçmek için çerez ve benzeri teknolojiler "
                     "kullanabilir; bu yolla tarayıcınızda bir tanımlayıcı saklanabilir ve "
                     "önceki site ziyaretlerinize göre kişiselleştirilmiş reklam "
                     "gösterilebilir.",
                     "Reklam kişiselleştirmesini Google'ın Reklam Ayarları sayfasından "
                     "kapatabilirsiniz. Tarayıcınızın ayarlarından çerezleri tamamen "
                     "engellemeniz de mümkündür; site çerezsiz de çalışır.",
                 ],
                 "baglar": [
                     {"ad": "Google Reklam Ayarları", "url": "https://myadcenter.google.com/"},
                     {"ad": "Google'ın reklam çerezleri hakkındaki açıklaması",
                      "url": "https://policies.google.com/technologies/ads"},
                 ]},
                {"baslik": "Harita ve dış bağlantılar",
                 "paragraflar": [
                     "Harita karoları OpenStreetMap sunucularından, Leaflet kütüphanesi "
                     "cdnjs üzerinden yüklenir; bu isteklerde IP adresiniz ilgili servise "
                     "ulaşır. Google Haritalar bağlantılarına tıkladığınızda Google'ın "
                     "kendi gizlilik politikası geçerli olur.",
                 ]},
                {"baslik": "İletişim",
                 "paragraflar": [
                     f"Gizlilikle ilgili sorularınız için: {site['eposta']}",
                 ]},
            ],
        },
    ]

    (DATA / "rehberler.json").write_text(
        json.dumps(rehberler, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "sayfalar.json").write_text(
        json.dumps(sayfalar, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(rehberler)} rehber, {len(sayfalar)} düz sayfa yazıldı")


if __name__ == "__main__":
    main()
