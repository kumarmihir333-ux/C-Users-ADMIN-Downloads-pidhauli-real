      let drawingBoundary = false;
        let boundaryPoints = [];
        let boundaryPointLayers = [];
        let draftBoundaryLine = null;
        let measuredBoundary = null;
        const startMeasure = document.querySelector('#startMeasure');
        const undoMeasure = document.querySelector('#undoMeasure');
        const finishMeasure = document.querySelector('#finishMeasure');
        const clearMeasure = document.querySelector('#clearMeasure');
        const checkSatellite = document.querySelector('#checkSatellite');
        const measureInstructions = document.querySelector('#measureInstructions');
        const measureResult = document.querySelector('#measureResult');
        const satelliteResult = document.querySelector('#satelliteResult');
        const satelliteTitle = document.querySelector('#satelliteTitle');
        const satelliteDetails = document.querySelector('#satelliteDetails');
        const satellitePreview = document.querySelector('#satellitePreview');
        const ndviChart = document.querySelector('#ndviChart');
        const ndviLegend = document.querySelector('#ndviLegend');
        const saveFieldAnalysis = document.querySelector('#saveFieldAnalysis');
        const savedFieldSelect = document.querySelector('#savedFieldSelect');
        const loadSavedFieldButton = document.querySelector('#loadSavedField');
        const fieldSaveStatus = document.querySelector('#fieldSaveStatus');
        const savedAnalysisHistory = document.querySelector('#savedAnalysisHistory');
        let ndviPixelLayer = null;
        let ndviPixelLegend = null;

        const clearNdviMap = () => {
          if (ndviPixelLayer) {
            map.removeLayer(ndviPixelLayer);
            ndviPixelLayer = null;
          }
          if (ndviPixelLegend) {
            map.removeControl(ndviPixelLegend);
            ndviPixelLegend = null;
          }
        };

        const clearDraftBoundary = () => {
          boundaryPointLayers.forEach((layer) => map.removeLayer(layer));
          boundaryPointLayers = [];
          if (draftBoundaryLine) {
            map.removeLayer(draftBoundaryLine);
            draftBoundaryLine = null;
          }
        };

        const clearMeasurement = () => {
          drawingBoundary = false;
          boundaryPoints = [];
          state.currentFieldId = null;
          document.querySelector('#fieldName').value = '';
          savedFieldSelect.value = '';
          savedAnalysisHistory.replaceChildren();
          clearDraftBoundary();
          if (measuredBoundary) {
            map.removeLayer(measuredBoundary);
            measuredBoundary = null;
          }
          measureResult.hidden = true;
          satelliteResult.hidden = true;
          satellitePreview.hidden = true;
          ndviChart.hidden = true;
          ndviChart.replaceChildren();
          ndviLegend.replaceChildren();
          clearNdviMap();
          state.latestSeasonalResult = null;
          saveFieldAnalysis.disabled = true;
          checkSatellite.disabled = true;
          checkSatellite.textContent = 'Compare seasons';
          measureInstructions.textContent = 'Start measuring, then click corners or press and drag along the field edge.';
          startMeasure.textContent = '＋ Measure land';
          undoMeasure.disabled = true;
          finishMeasure.disabled = true;
          clearMeasure.disabled = true;
          map.getContainer().style.cursor = '';
        };

        const updateBoundaryDraft = () => {
          clearDraftBoundary();
          const markerStride = Math.max(1, Math.ceil(boundaryPoints.length / 40));
          boundaryPoints.forEach((point, index) => {
            if (index % markerStride !== 0 && index !== boundaryPoints.length - 1) return;
            const marker = L.circleMarker(point, {
              radius: 5,
              color: '#15231b',
              weight: 2,
              fillColor: '#c5df7a',
              fillOpacity: 1
            }).addTo(map);
            marker.bindTooltip(`Boundary point ${index + 1}`);
            boundaryPointLayers.push(marker);
          });
          if (boundaryPoints.length > 1) {
            draftBoundaryLine = L.polyline(boundaryPoints, {
              color: '#c5df7a',
              weight: 2,
              dashArray: '6 5'
            }).addTo(map);
          }
          undoMeasure.disabled = boundaryPoints.length === 0;
          finishMeasure.disabled = boundaryPoints.length < 3;
          clearMeasure.disabled = false;
          measureInstructions.textContent = boundaryPoints.length < 3
            ? `${boundaryPoints.length} point${boundaryPoints.length === 1 ? '' : 's'} placed · add at least ${3 - boundaryPoints.length} more.`
            : `${boundaryPoints.length} points placed · finish when the boundary is complete.`;
        };

        const calculateBoundaryArea = () => {
          const semiMajorAxis = 6378137;
          const flattening = 1 / 298.257223563;
          const eccentricitySquared = flattening * (2 - flattening);
          const eccentricity = Math.sqrt(eccentricitySquared);
          const meridianArea = (latitude) => {
            const sine = Math.sin(latitude);
            const denominator = 1 - eccentricitySquared * sine * sine;
            const atanhArgument = eccentricity * sine;
            const atanh = 0.5 * Math.log((1 + atanhArgument) / (1 - atanhArgument));
            return semiMajorAxis ** 2 * (1 - eccentricitySquared) / 2 * (
              sine / denominator + atanh / eccentricity
            );
          };
          let ellipsoidArea = 0;
          let perimeter = 0;
          for (let index = 0; index < boundaryPoints.length; index += 1) {
            const current = boundaryPoints[index];
            const next = boundaryPoints[(index + 1) % boundaryPoints.length];
            const currentLatitude = current.lat * Math.PI / 180;
            const nextLatitude = next.lat * Math.PI / 180;
            let longitudeDifference = (next.lng - current.lng) * Math.PI / 180;
            if (longitudeDifference > Math.PI) longitudeDifference -= 2 * Math.PI;
            if (longitudeDifference < -Math.PI) longitudeDifference += 2 * Math.PI;

            const intervals = 8;
            const step = (nextLatitude - currentLatitude) / intervals;
            let meanMeridianArea = meridianArea(currentLatitude) + meridianArea(nextLatitude);
            for (let sample = 1; sample < intervals; sample += 1) {
              const weight = sample % 2 === 0 ? 2 : 4;
              meanMeridianArea += weight * meridianArea(currentLatitude + sample * step);
            }
            meanMeridianArea /= 3 * intervals;
            ellipsoidArea += longitudeDifference * meanMeridianArea;
            perimeter += map.distance(current, next);
          }
          const squareMeters = Math.abs(ellipsoidArea);
          document.querySelector('#areaAcres').textContent =
            (squareMeters / 4046.8564224).toLocaleString('en-IN', { maximumFractionDigits: 2 });
          document.querySelector('#areaHectares').textContent =
            (squareMeters / 10000).toLocaleString('en-IN', { maximumFractionDigits: 4 });
          document.querySelector('#areaSqm').textContent =
            Math.round(squareMeters).toLocaleString('en-IN');
          document.querySelector('#measureNote').textContent =
            `Boundary ${Math.round(perimeter).toLocaleString('en-IN')} m · WGS84 ellipsoid estimate. Trace every bend closely; this is not a legal survey.`;
          measureResult.hidden = false;
        };

        const renderBoundaryHandles = () => {
          if (measuredBoundary) map.removeLayer(measuredBoundary);
          boundaryPointLayers.forEach((layer) => map.removeLayer(layer));
          boundaryPointLayers = [];
          measuredBoundary = L.polygon(boundaryPoints, {
            color: '#c5df7a',
            weight: 2,
            fillColor: '#c5df7a',
            fillOpacity: 0.18
          }).addTo(map);
          boundaryPoints.forEach((point, index) => {
            const handle = L.marker(point, {
              draggable: true,
              icon: L.divIcon({
                className: '',
                html: '<span class="measure-handle"></span>',
                iconSize: [14, 14],
                iconAnchor: [7, 7]
              })
            }).addTo(map);
            handle.on('drag', (event) => {
              boundaryPoints[index] = event.target.getLatLng();
              measuredBoundary.setLatLngs(boundaryPoints);
              calculateBoundaryArea();
              clearNdviMap();
              state.latestSeasonalResult = null;
              saveFieldAnalysis.disabled = true;
            });
            boundaryPointLayers.push(handle);
          });
          calculateBoundaryArea();
          clearMeasure.disabled = false;
          checkSatellite.disabled = false;
          startMeasure.textContent = '＋ Measure again';
          undoMeasure.disabled = true;
          finishMeasure.disabled = true;
          map.getContainer().style.cursor = '';
          measureInstructions.textContent = 'Drag the green corner handles to refine the boundary; area updates as you adjust.';
        };

        startMeasure.addEventListener('click', () => {
          clearMeasurement();
          drawingBoundary = true;
          if (map.getZoom() < 18) map.setZoom(18);
          startMeasure.textContent = 'Drawing boundary…';
          map.getContainer().style.cursor = 'crosshair';
          mapStatus.textContent = 'Click each corner of the land boundary; zoom and pan as needed.';
          measureInstructions.textContent = 'Click the field edge point by point, or press and drag to trace it. Add points along every bend.';
        });

        undoMeasure.addEventListener('click', () => {
          if (!drawingBoundary || boundaryPoints.length === 0) return;
          boundaryPoints.pop();
          updateBoundaryDraft();
        });

        clearMeasure.addEventListener('click', () => {
          clearMeasurement();
          mapStatus.textContent = 'Land measurement cleared.';
        });

        finishMeasure.addEventListener('click', () => {
          if (!drawingBoundary || boundaryPoints.length < 3) return;
          drawingBoundary = false;
          clearDraftBoundary();
          renderBoundaryHandles();
          mapStatus.textContent = 'Land area estimated · drag green corner handles to refine.';
        });

  
