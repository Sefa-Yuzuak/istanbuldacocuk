/* İstanbul çocuk mekânları haritası — Leaflet + OpenStreetMap. */
(function () {
  var kap = document.getElementById("harita");
  if (!kap || typeof L === "undefined") return;

  var harita = L.map(kap, { scrollWheelZoom: false }).setView([41.03, 28.98], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları'
  }).addTo(harita);
  harita.on("click", function () { harita.scrollWheelZoom.enable(); });

  var katman = L.layerGroup().addTo(harita);
  var noktalar = [], benim = null;
  var fUcretsiz = document.getElementById("f-ucretsiz"),
      fKapali = document.getElementById("f-kapali"),
      fTur = document.getElementById("f-tur"),
      fYaka = document.getElementById("f-yaka"),
      sayac = document.getElementById("harita-sayac");

  function kacKm(a, b, c, d) {
    var R = 6371, r = Math.PI / 180;
    var x = Math.sin((c - a) * r / 2) ** 2 +
            Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  function ciz() {
    katman.clearLayers();
    var tur = fTur.value, yaka = fYaka.value, n = 0;
    var secili = noktalar.filter(function (p) {
      if (fUcretsiz.checked && !p.uc) return false;
      if (fKapali.checked && !p.kp) return false;
      if (tur && p.k !== tur) return false;
      if (yaka && p.y !== yaka) return false;
      return true;
    });
    if (benim) {
      secili.forEach(function (p) { p._d = kacKm(benim[0], benim[1], p.lat, p.lng); });
      secili.sort(function (a, b) { return a._d - b._d; });
      secili = secili.slice(0, 60);
    }
    secili.forEach(function (p) {
      n++;
      L.marker([p.lat, p.lng], {
        icon: L.divIcon({
          className: "", html: '<div style="font-size:20px;line-height:20px">' + p.n + "</div>",
          iconSize: [22, 22], iconAnchor: [11, 11]
        })
      }).bindPopup(
        '<div class="harita-balon"><b>' + p.a + "</b><span>" + p.t + " · " + p.i +
        (p._d ? " · " + p._d.toFixed(1) + " km" : "") + "</span><br>" +
        '<a href="' + p.u + '">Sayfayı aç →</a></div>'
      ).addTo(katman);
    });
    if (sayac) sayac.textContent = n + " mekân gösteriliyor" + (benim ? " (size en yakınlar)" : "");
  }

  [fUcretsiz, fKapali, fTur, fYaka].forEach(function (e) {
    if (e) e.addEventListener("change", ciz);
  });

  var dugme = document.getElementById("konum");
  if (dugme) dugme.addEventListener("click", function () {
    if (!navigator.geolocation) { dugme.textContent = "Konum desteklenmiyor"; return; }
    dugme.textContent = "Konum alınıyor…";
    navigator.geolocation.getCurrentPosition(function (k) {
      benim = [k.coords.latitude, k.coords.longitude];
      L.circleMarker(benim, { radius: 8, color: "#12506b", fillColor: "#2f9fc7", fillOpacity: .9 })
        .bindPopup("Buradasınız").addTo(harita);
      harita.setView(benim, 13);
      dugme.textContent = "📍 Bana en yakınlar";
      ciz();
    }, function () { dugme.textContent = "Konum alınamadı"; }, { timeout: 10000 });
  });

  fetch("/static/noktalar.json")
    .then(function (y) { return y.json(); })
    .then(function (v) { noktalar = v; ciz(); })
    .catch(function () { if (sayac) sayac.textContent = "Harita verisi yüklenemedi."; });
})();
