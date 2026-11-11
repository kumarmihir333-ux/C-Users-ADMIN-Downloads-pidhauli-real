      const describeGreennessChange = (change) => {
          if (Math.abs(change) < 0.015) return 'about the same';
          const degree = Math.abs(change) < 0.05 ? 'slightly' : (
            Math.abs(change) < 0.1 ? 'noticeably' : 'much'
          );
          return `${degree} ${change > 0 ? 'greener' : 'less green'}`;
        };

        const ndviColor = (value) => {
          if (value < 0.1) return '#9b6248';
          if (value < 0.25) return '#d1a85d';
          if (value < 0.4) return '#acc56d';
          return '#4e9a50';
        };

        const renderSeasonalResults = (data, options = {}) => {
          state.latestSeasonalResult = data;
          saveFieldAnalysis.disabled = !state.user || !data.available;
          satelliteTitle.textContent = data.available
            ? `Seasonal NDVI snapshots · ${data.observations.length} dates`
            : 'No suitable seasonal scenes found';

          const summaries = (data.comparisons || []).map((comparison) =>
            `${comparison.season}: ${describeGreennessChange(comparison.change)} than ${comparison.previous_label} (${comparison.change >= 0 ? '+' : ''}${comparison.change.toFixed(3)} NDVI).`
          );
          (data.season_summaries || []).forEach((summary) => {
            summaries.push(
              `${summary.label}: average greenness ${summary.mean_ndvi} across ${summary.samples} clear date${summary.samples === 1 ? '' : 's'}; ${summary.coverage_pct}% of field pixels usable on average.`
            );
          });
          const qualityWarnings = (data.observations || [])
            .filter((item) => item.quality === 'low')
            .map((item) => `Low usable coverage for ${item.label} (${item.coverage_pct}% of field pixels).`);
          satelliteDetails.textContent = [
            data.message,
            ...summaries,
            ...qualityWarnings,
            data.weather_context || '',
            data.weather_error || '',
            'Sentinel-2 pixels are about 10 m; field-edge pixels may include neighboring land.'
          ].filter(Boolean).join(' ');

          ndviChart.replaceChildren();
          ndviLegend.replaceChildren();
          const observations = data.observations || [];
          if (observations.length) {
            const chartWidth = Math.max(360, observations.length * 82);
            const xFor = (index) => observations.length === 1
              ? chartWidth / 2
              : 36 + index * (chartWidth - 72) / (observations.length - 1);
            const yFor = (value) => 112 - ((value + 1) / 2) * 92;
            ndviChart.setAttribute('viewBox', `0 0 ${chartWidth} 142`);
            ndviChart.setAttribute('preserveAspectRatio', 'none');

            [-1, 0, 0.5, 1].forEach((value) => {
              const y = yFor(value);
              const guide = document.createElementNS('http://www.w3.org/2000/svg', 'line');
              guide.setAttribute('x1', '34');
              guide.setAttribute('x2', String(chartWidth - 28));
              guide.setAttribute('y1', String(y));
              guide.setAttribute('y2', String(y));
              guide.setAttribute('class', 'ndvi-guide');
              ndviChart.append(guide);
              const axisLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
              axisLabel.setAttribute('x', '0');
              axisLabel.setAttribute('y', String(y + 3));
              axisLabel.textContent = value.toFixed(1);
              axisLabel.setAttribute('class', 'ndvi-axis');
              ndviChart.append(axisLabel);
            });

            const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
            line.setAttribute('points', observations.map((item, index) =>
              `${xFor(index)},${yFor(item.mean_ndvi)}`
            ).join(' '));
            line.setAttribute('class', 'ndvi-line');
            ndviChart.append(line);

            observations.forEach((item, index) => {
              const x = xFor(index);
              const y = yFor(item.mean_ndvi);
              const point = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
              point.setAttribute('cx', String(x));
              point.setAttribute('cy', String(y));
              point.setAttribute('r', '4');
              point.setAttribute('class', 'ndvi-point');
              const tooltip = document.createElementNS('http://www.w3.org/2000/svg', 'title');
              tooltip.textContent = `${item.label} · mean NDVI ${item.mean_ndvi}`;
              point.append(tooltip);
              ndviChart.append(point);

              const dateLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
              dateLabel.setAttribute('x', String(x));
              dateLabel.setAttribute('y', '134');
              dateLabel.setAttribute('text-anchor', 'middle');
              dateLabel.setAttribute('class', 'ndvi-axis');
              dateLabel.textContent = item.acquired_at
                ? new Date(item.acquired_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
                : item.label;
              ndviChart.append(dateLabel);

              const rainText = item.rainfall_14d_mm === undefined || item.rainfall_14d_mm === null
                ? 'rainfall unavailable'
                : `${item.rainfall_14d_mm} mm rain / 14 days`;
              const tempText = item.mean_temp_14d_c === undefined || item.mean_temp_14d_c === null
                ? ''
                : ` · avg ${item.mean_temp_14d_c}°C`;
              const summary = document.createElement('span');
              summary.textContent = `${item.label}${item.in_progress ? ' (in progress)' : ''} · ${dateLabel.textContent}: greenness ${item.mean_ndvi} (median ${item.median_ndvi}); ${item.coverage_pct}% of field pixels usable (${item.quality}); ${item.cloud_cover_pct ?? '—'}% scene cloud; ${rainText}${tempText}.`;
              ndviLegend.append(summary);
            });
            ndviChart.hidden = false;
          } else {
            ndviChart.hidden = true;
          }

          if (data.preview_url) {
            satellitePreview.href = data.preview_url;
            satellitePreview.hidden = false;
          } else {
            satellitePreview.hidden = true;
          }

          clearNdviMap();
          if (options.showMap !== false && data.ndvi_map_available && data.ndvi_map?.length) {
            const features = data.ndvi_map.map((pixel) => ({
              type: 'Feature',
              properties: { ndvi: pixel.value },
              geometry: { type: 'Polygon', coordinates: [pixel.coordinates] }
            }));
            ndviPixelLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
              style: (feature) => ({
                color: '#253629',
                weight: 0.35,
                fillColor: ndviColor(feature.properties.ndvi),
                fillOpacity: 0.78
              })
            }).addTo(map);
            ndviPixelLegend = L.control({ position: 'bottomright' });
            ndviPixelLegend.onAdd = () => {
              const legend = L.DomUtil.create('div', 'ndvi-map-legend');
              legend.innerHTML = '<strong>Field greenness · NDVI</strong><span><i class="ndvi-low"></i>Low</span><span><i class="ndvi-mid"></i>Some</span><span><i class="ndvi-high"></i>Higher</span>';
              L.DomEvent.disableClickPropagation(legend);
              return legend;
            };
            ndviPixelLegend.addTo(map);
          }
        };

        const loadFieldHistory = async (fieldId) => {
          const response = await fetch(`/api/fields/${fieldId}/analyses`);
          const entries = await response.json();
          if (!response.ok) throw new Error(entries.error || 'Unable to load field history');
          savedAnalysisHistory.replaceChildren();
          if (!entries.length) {
            savedAnalysisHistory.textContent = 'No saved analyses for this field yet.';
            return;
          }
          const heading = document.createElement('strong');
          heading.textContent = 'Saved analysis history';
          savedAnalysisHistory.append(heading);
          entries.forEach((entry) => {
            const button = document.createElement('button');
            const when = new Date(`${entry.created_at.replace(' ', 'T')}Z`).toLocaleString('en-IN');
            const firstComparison = entry.result.comparisons?.[0];
            button.textContent = firstComparison
              ? `${when} · ${firstComparison.season} ${firstComparison.change >= 0 ? '+' : ''}${firstComparison.change.toFixed(3)}`
              : `${when} · ${entry.result.observations.length} observations`;
            button.type = 'button';
            button.addEventListener('click', () => {
              renderSeasonalResults(entry.result, { showMap: false });
              satelliteTitle.textContent = `Saved analysis · ${when}`;
            });
            savedAnalysisHistory.append(button);
          });
        };

        savedFieldSelect.addEventListener('change', () => {
          loadSavedFieldButton.disabled = !savedFieldSelect.value;
        });

        loadSavedFieldButton.addEventListener('click', async () => {
          const field = state.savedFields.find((item) => String(item.id) === savedFieldSelect.value);
          if (!field) return;
          try {
            clearMeasurement();
            state.currentFieldId = field.id;
            document.querySelector('#fieldName').value = field.name;
            savedFieldSelect.value = String(field.id);
            boundaryPoints = field.boundary.map(([longitude, latitude]) => L.latLng(latitude, longitude));
            renderBoundaryHandles();
            map.fitBounds(measuredBoundary.getBounds(), { padding: [30, 30], maxZoom: 19 });
            measureInstructions.textContent = `Loaded “${field.name}” · edit boundary if needed, then compare seasons.`;
            fieldSaveStatus.textContent = `${field.name} loaded. New analysis will be added to its history.`;
            satelliteResult.hidden = false;
            satelliteTitle.textContent = `Saved field · ${field.name}`;
            satelliteDetails.textContent = 'Drawn boundary loaded. Run a fresh seasonal comparison to update its history.';
            await loadFieldHistory(field.id);
          } catch (error) {
            toast(error.message);
          }
        });

        saveFieldAnalysis.addEventListener('click', async () => {
          if (!state.user || !state.latestSeasonalResult?.available) {
            toast('Sign in and run a seasonal analysis before saving.');
            return;
          }
          saveFieldAnalysis.disabled = true;
          try {
            let fieldId = state.currentFieldId;
            if (!fieldId) {
              const name = document.querySelector('#fieldName').value.trim();
              if (!name) throw new Error('Enter a field name before saving.');
              const response = await fetch('/api/fields', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  name,
                  area_sqm: Number(document.querySelector('#areaSqm').textContent.replaceAll(',', '')),
                  boundary: boundaryPoints.map((point) => [point.lng, point.lat])
                })
              });
              const data = await response.json();
              if (!response.ok) throw new Error(data.error || 'Could not save field');
              fieldId = data.id;
              state.currentFieldId = fieldId;
            }
            const response = await fetch(`/api/fields/${fieldId}/analyses`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                result: state.latestSeasonalResult,
                area_sqm: Number(document.querySelector('#areaSqm').textContent.replaceAll(',', '')),
                boundary: boundaryPoints.map((point) => [point.lng, point.lat])
              })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Could not save analysis');
            fieldSaveStatus.textContent = 'Field and analysis saved privately to your account.';
            await loadSavedFields();
            savedFieldSelect.value = String(fieldId);
            loadSavedFieldButton.disabled = false;
            await loadFieldHistory(fieldId);
          } catch (error) {
            fieldSaveStatus.textContent = error.message;
          } finally {
            saveFieldAnalysis.disabled = !state.user || !state.latestSeasonalResult?.available;
          }
        });

        checkSatellite.addEventListener('click', async () => {
          checkSatellite.disabled = true;
          checkSatellite.textContent = 'Comparing…';
          state.latestSeasonalResult = null;
          saveFieldAnalysis.disabled = true;
          satelliteResult.hidden = false;
          satellitePreview.hidden = true;
          ndviChart.hidden = true;
          ndviChart.replaceChildren();
          ndviLegend.replaceChildren();
          clearNdviMap();
          satelliteTitle.textContent = 'Comparing agricultural seasons…';
          satelliteDetails.textContent = 'Processing multiple clear dates per season, checking pixel coverage, and fetching nearby rainfall context.';
          try {
            const response = await fetch('/api/satellite/seasonal', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                boundary: boundaryPoints.map((point) => [point.lng, point.lat])
              })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Satellite search failed');
            renderSeasonalResults(data);
          } catch (error) {
            satelliteTitle.textContent = 'Satellite lookup unavailable';
            satelliteDetails.textContent = error.message;
          } finally {
            checkSatellite.disabled = false;
            checkSatellite.textContent = 'Compare seasons';
          }
        });

  
