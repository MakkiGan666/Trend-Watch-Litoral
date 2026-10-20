(() => {
  const container = document.getElementById('misiones-map');
  if (!container) return;
  const status = document.getElementById('map-status');
  if (!window.L) {
    status.textContent = 'No pudimos cargar el mapa. Podés consultar las noticias desde las tarjetas de Localidades.';
    return;
  }
  // Puntos de referencia del mapa territorial existente, sin métricas de muestra.
  const coordinates = {
    capital: [-27.36, -55.90], obera: [-27.49, -55.12],
    iguazu: [-25.60, -54.57], eldorado: [-26.40, -54.62],
    sanignacio: [-27.25, -55.53], cainguas: [-27.20, -54.99],
    libertador: [-26.90, -54.96], apostoles: [-27.91, -55.75],
    belgrano: [-25.95, -53.95], montecarlo: [-26.57, -54.74],
    candelaria: [-27.46, -55.74], sanpedro: [-26.62, -54.11],
    sanjavier: [-27.87, -55.13], concepcion: [-27.99, -55.52],
    '25mayo': [-27.38, -54.74], leandro: [-27.60, -55.32],
    guarani: [-27.30, -54.20]
  };
  const map = L.map(container, { scrollWheelZoom: false });
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    // OSM necesita la referencia del sitio; enviar solo el origen, sin rutas privadas.
    referrerPolicy: 'strict-origin-when-cross-origin',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);
  tiles.on('tileerror', () => {
    status.textContent = 'Algunas partes del mapa no pudieron cargarse. Los puntos y las tarjetas de Localidades permiten consultar las noticias.';
  });
  const markers = [];
  document.querySelectorAll('#localidades .locality-card').forEach(card => {
    const slug = new URL(card.href).pathname.split('/').filter(Boolean).pop();
    if (!coordinates[slug]) return;
    const name = card.querySelector('small').textContent;
    const popup = document.createElement('div');
    const heading = document.createElement('strong');
    heading.textContent = name;
    const link = document.createElement('a');
    link.href = card.href;
    link.textContent = 'Ver noticias →';
    popup.append(heading, document.createElement('br'), link);
    const marker = L.circleMarker(coordinates[slug], {
      radius: 7, color: '#051f20', weight: 2, fillColor: '#235347', fillOpacity: .95
    }).addTo(map).bindPopup(popup).bindTooltip(name, { direction: 'top' });
    marker.on('click', () => {
      markers.forEach(item => item.setStyle({ radius: 7, fillColor: '#235347' }));
      marker.setStyle({ radius: 10, fillColor: '#8eb69b' });
      document.getElementById('map-selection-title').textContent = name;
      status.textContent = 'Consultá las publicaciones asociadas a este departamento.';
      const newsLink = document.getElementById('map-news-link');
      newsLink.href = card.href;
      newsLink.hidden = false;
    });
    markers.push(marker);
  });
  map.fitBounds(Object.values(coordinates), { padding: [24, 24] });
  status.textContent = 'Seleccioná uno de los 17 puntos para ver el departamento y acceder a sus noticias.';
  if ('ResizeObserver' in window) {
    new ResizeObserver(() => map.invalidateSize()).observe(container);
  }
})();
