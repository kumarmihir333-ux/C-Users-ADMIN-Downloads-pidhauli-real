      const map = L.map('map', { center: dairyCenter, zoom: 16, zoomControl: true, scrollWheelZoom: true });

        const layers = {
          satellite: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: 'Tiles © Esri'
          }),
          streets: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
          })
        };
        layers.satellite.addTo(map);

        markets.forEach((market) => {
          const marker = L.marker([market.latitude, market.longitude]).addTo(map);
          marker.bindPopup(`<strong>${market.name}</strong><br>${market.location}, ${market.state}`);
        });

        const dairyMarker = L.marker(dairyCenter, {
          icon: L.divIcon({ className: '', html: '<span class="dairy-marker"></span>', iconSize: [28, 28], iconAnchor: [14, 14] })
        }).addTo(map).bindPopup('<strong>Sudha milk dairy pidhauli</strong><br>Pidhauli, Begusarai, Bihar<br>25.5302806, 85.9195789');
        dairyMarker.openPopup();

        document.querySelectorAll('[data-layer]').forEach((button) => {
          button.addEventListener('click', () => {
            document.querySelectorAll('[data-layer]').forEach((btn) => btn.classList.toggle('active', btn === button));
            Object.values(layers).forEach((layer) => map.removeLayer(layer));
            layers[button.dataset.layer].addTo(map);
          });
        });

        const locateButton = document.querySelector('#locateDevice');
        const mapStatus = document.querySelector('#mapStatus');
        let locationWatchId = null;
        let deviceMarker = null;
        let accuracyCircle = null;
        let hasLocationFix = false;

        const formatAccuracy = (accuracy) => accuracy >= 1000
          ? `±${(accuracy / 1000).toFixed(1)} km`
          : `±${Math.round(accuracy)} m`;

        const stopLocationTracking = () => {
          if (locationWatchId !== null) {
            navigator.geolocation.clearWatch(locationWatchId);
            locationWatchId = null;
          }
          locateButton.textContent = '◎ Use my device location';
        };

        const showLocationError = (error) => {
          const messages = {
            1: 'Location permission was denied. Allow location access in your browser and try again.',
            2: 'The device could not determine a location. Check device location services and try again.',
            3: 'Location lookup timed out. Check your connection or device location settings and try again.'
          };
          stopLocationTracking();
          mapStatus.textContent = messages[error.code] || 'Could not get device location.';
        };

        locateButton.addEventListener('click', () => {
          if (!navigator.geolocation) {
            mapStatus.textContent = 'Geolocation is unavailable in this browser.';
            return;
          }

          if (locationWatchId !== null) {
            stopLocationTracking();
            mapStatus.textContent = 'Device location tracking stopped.';
            return;
          }

          hasLocationFix = false;
          locateButton.textContent = 'Finding device…';
          mapStatus.textContent = 'Requesting a fresh position from your browser. Allow location access if prompted.';
          locationWatchId = navigator.geolocation.watchPosition((position) => {
            const { latitude, longitude, accuracy } = position.coords;
            const here = [latitude, longitude];

            if (!deviceMarker) {
              deviceMarker = L.marker(here, {
                icon: L.divIcon({
                  className: '',
                  html: '<span class="device-marker"></span>',
                  iconSize: [20, 20],
                  iconAnchor: [10, 10]
                })
              }).addTo(map);
              deviceMarker.bindPopup('Your device');
            } else {
              deviceMarker.setLatLng(here);
            }

            if (!accuracyCircle) {
              accuracyCircle = L.circle(here, {
                radius: accuracy,
                className: 'device-accuracy',
                color: '#ff9a84',
                weight: 1,
                fillColor: '#ff9a84',
                fillOpacity: 0.12
              }).addTo(map);
            } else {
              accuracyCircle.setLatLng(here);
              accuracyCircle.setRadius(accuracy);
            }

            const accuracyLabel = formatAccuracy(accuracy);
            deviceMarker.setPopupContent(
              `<strong>Your device</strong><br>${latitude.toFixed(5)}, ${longitude.toFixed(5)}<br>Reported accuracy: ${accuracyLabel}`
            );
            if (!hasLocationFix) {
              map.setView(here, 16);
              hasLocationFix = true;
              locateButton.textContent = '■ Stop device tracking';
            } else {
              map.panTo(here);
            }
            mapStatus.textContent = accuracy > 200
              ? `Device position updated · reported accuracy ${accuracyLabel}. A large circle means the position is approximate.`
              : `Device position updated · reported accuracy ${accuracyLabel}.`;
          }, showLocationError, {
            enableHighAccuracy: true,
            maximumAge: 0,
            timeout: 30000
          });
        });

        window.addEventListener('pagehide', () => {
          if (locationWatchId !== null) navigator.geolocation.clearWatch(locationWatchId);
        }, { once: true });

  
