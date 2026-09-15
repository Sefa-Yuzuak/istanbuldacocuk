/* istanbuldacocuk.com — site içi arama. Dizin derlemede üretilir (/data/ara.json),
   eşleştirme tarayıcıda yapılır; sorgu hiçbir sunucuya gitmez. */
(function () {
  "use strict";
  var form = document.querySelector("form[data-ara]");
  if (!form) return;
  var giris = form.querySelector("input[name=q]");
  var oneri = form.querySelector(".ara-oneri");
  var sonuclar = document.getElementById("ara-sonuclar");
  var sayac = document.getElementById("ara-sayac");
  var dizin = null, istek = null, aktif = -1;

  // build/derle.py'deki arama_anahtari ile aynı sadeleştirme; ikisi birlikte değişmeli.
  // Türkçe harfler toLowerCase'ten ÖNCE çevrilir: "İ".toLowerCase() "i" + U+0307
  // üretir ve "istanbul" ile eşleşmez.
  var TR = { "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g",
             "Ç": "c", "ç": "c", "Ö": "o", "ö": "o", "Ü": "u", "ü": "u",
             "Â": "a", "â": "a", "Î": "i", "î": "i" };
  function sade(s) {
    s = String(s || "").replace(/[İIıŞşĞğÇçÖöÜüÂâÎî]/g, function (h) { return TR[h]; });
    s = s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    return s.replace(/[^a-z0-9]+/g, " ").trim();
  }

  function yukle() {
    if (!istek) {
      istek = fetch("/data/ara.json").then(function (y) { return y.json(); })
        .then(function (v) { dizin = v; return v; })
        .catch(function (e) { istek = null; throw e; });
    }
    return istek;
  }

  // Her parça kayıtta geçmeli. Ad başında geçen 3, kelime başında geçen 2,
  // içeride geçen 1 puan; eşitlikte ada göre.
  function bul(q) {
    var parcalar = sade(q).split(" ").filter(Boolean);
    if (!parcalar.length || !dizin) return [];
    var liste = [];
    dizin.forEach(function (k) {
      var puan = 0;
      for (var i = 0; i < parcalar.length; i++) {
        var yer = k.k.indexOf(parcalar[i]);
        if (yer === -1) return;
        puan += yer === 0 ? 3 : (" " + k.k).indexOf(" " + parcalar[i]) !== -1 ? 2 : 1;
      }
      liste.push({ puan: puan, k: k });
    });
    liste.sort(function (a, b) { return b.puan - a.puan || a.k.a.localeCompare(b.k.a, "tr"); });
    return liste.map(function (x) { return x.k; });
  }

  function ekle(ana, etiket, sinif) {
    var e = document.createElement(etiket);
    if (sinif) e.className = sinif;
    ana.appendChild(e);
    return e;
  }
  function altyazi(k) { return k.t + (k.i ? " · " + k.i : "") + (k.y ? " · " + k.y : ""); }

  // ---- /ara/ sayfası: tam sonuç listesi, yazdıkça yenilenir
  if (sonuclar) {
    var goster = function () {
      var q = giris.value.trim();
      sonuclar.textContent = "";
      if (q.length < 2) { sayac.textContent = "Aramak için en az iki harf yazın."; return; }
      var liste = bul(q);
      sayac.textContent = liste.length
        ? liste.length + " sonuç: “" + q + "”"
        : "“" + q + "” için sonuç yok. Daha kısa yazmayı ya da ilçe adını deneyin.";
      liste.forEach(function (k) {
        var kart = ekle(sonuclar, "article", "kart");
        var bag = ekle(kart, "a", "kart-bag"); bag.href = k.u;
        var ikon = ekle(bag, "span", "kart-ikon"); ikon.setAttribute("aria-hidden", "true"); ikon.textContent = k.n;
        ekle(bag, "span", "kart-ad").textContent = k.a;
        ekle(kart, "p", "kart-alt").textContent = altyazi(k);
      });
    };
    giris.value = new URLSearchParams(location.search).get("q") || "";
    yukle().then(goster, function () { sayac.textContent = "Arama dizini yüklenemedi; sayfayı yenileyin."; });
    giris.addEventListener("input", function () {
      var q = giris.value.trim();
      history.replaceState(null, "", "/ara/" + (q ? "?q=" + encodeURIComponent(q) : ""));
      if (dizin) goster();
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); if (dizin) goster(); });
    return;
  }

  // ---- öneri kutusu (ana sayfa ve listeler)
  function kapat() {
    oneri.hidden = true; oneri.textContent = ""; aktif = -1;
    giris.setAttribute("aria-expanded", "false");
    giris.removeAttribute("aria-activedescendant");
  }
  function sec(i) {
    var ogeler = oneri.children;
    if (!ogeler.length) return;
    if (aktif >= 0) { ogeler[aktif].classList.remove("aktif"); ogeler[aktif].setAttribute("aria-selected", "false"); }
    aktif = (i + ogeler.length) % ogeler.length;
    ogeler[aktif].classList.add("aktif"); ogeler[aktif].setAttribute("aria-selected", "true");
    giris.setAttribute("aria-activedescendant", ogeler[aktif].id);
    ogeler[aktif].scrollIntoView({ block: "nearest" });
  }
  function git(li) { if (li.dataset.u) location.href = li.dataset.u; else form.submit(); }
  function onerileriGoster(q) {
    var liste = bul(q).slice(0, 8);
    kapat();
    if (!liste.length) return;
    liste.forEach(function (k, i) {
      var li = ekle(oneri, "li");
      li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
      li.id = "ara-o" + i; li.dataset.u = k.u;
      ekle(li, "b").textContent = k.a;
      ekle(li, "span").textContent = altyazi(k);
    });
    var hepsi = ekle(oneri, "li", "hepsi");
    hepsi.setAttribute("role", "option"); hepsi.setAttribute("aria-selected", "false");
    hepsi.id = "ara-o" + liste.length; hepsi.textContent = "Tüm sonuçlar →";
    // mousedown: blur'dan önce çalışır, tıklama kaybolmaz.
    Array.prototype.forEach.call(oneri.children, function (li) {
      li.addEventListener("mousedown", function (e) { e.preventDefault(); git(li); });
    });
    oneri.hidden = false;
    giris.setAttribute("aria-expanded", "true");
  }

  giris.addEventListener("focus", function () { yukle().catch(function () {}); });
  giris.addEventListener("input", function () {
    var q = giris.value.trim();
    if (q.length < 2) { kapat(); return; }
    yukle().then(function () { if (giris.value.trim() === q) onerileriGoster(q); }, function () {});
  });
  giris.addEventListener("blur", kapat);
  giris.addEventListener("keydown", function (e) {
    if (oneri.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); sec(aktif + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sec(aktif - 1); }
    else if (e.key === "Escape") { kapat(); }
    else if (e.key === "Enter" && aktif >= 0) { e.preventDefault(); git(oneri.children[aktif]); }
  });
})();
