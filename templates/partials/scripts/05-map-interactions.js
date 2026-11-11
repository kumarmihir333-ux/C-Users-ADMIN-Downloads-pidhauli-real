      const mapContainer = map.getContainer();
        if (window.PointerEvent) {
          let activePointerId = null;
          let lastTracePixel = null;
          let mapDraggingWasEnabled = false;

          mapContainer.addEventListener('pointerdown', (event) => {
            if (!drawingBoundary || event.button !== 0 || event.target.closest('.leaflet-control')) return;
            event.preventDefault();
            event.stopPropagation();
            activePointerId = event.pointerId;
            lastTracePixel = { x: event.clientX, y: event.clientY };
            mapDraggingWasEnabled = map.dragging.enabled();
            map.dragging.disable();
            mapContainer.setPointerCapture(activePointerId);
            boundaryPoints.push(map.mouseEventToLatLng(event));
            draftBoundaryLine = L.polyline(boundaryPoints, {
              color: '#c5df7a',
              weight: 2,
              dashArray: '6 5'
            }).addTo(map);
          }, true);

          mapContainer.addEventListener('pointermove', (event) => {
            if (activePointerId !== event.pointerId || !drawingBoundary) return;
            const dx = event.clientX - lastTracePixel.x;
            const dy = event.clientY - lastTracePixel.y;
            if (dx * dx + dy * dy < 16) return;
            lastTracePixel = { x: event.clientX, y: event.clientY };
            boundaryPoints.push(map.mouseEventToLatLng(event));
            if (draftBoundaryLine) draftBoundaryLine.setLatLngs(boundaryPoints);
            undoMeasure.disabled = false;
            clearMeasure.disabled = false;
            measureInstructions.textContent = `${boundaryPoints.length} boundary points traced · release to finish tracing, then add any missing corners.`;
          }, true);

          const endBoundaryTrace = (event) => {
            if (activePointerId !== event.pointerId) return;
            if (drawingBoundary) {
              const dx = event.clientX - lastTracePixel.x;
              const dy = event.clientY - lastTracePixel.y;
              if (dx * dx + dy * dy >= 4) {
                boundaryPoints.push(map.mouseEventToLatLng(event));
              }
              updateBoundaryDraft();
            }
            const pointerId = activePointerId;
            activePointerId = null;
            lastTracePixel = null;
            if (mapContainer.hasPointerCapture(pointerId)) {
              mapContainer.releasePointerCapture(pointerId);
            }
            if (mapDraggingWasEnabled) map.dragging.enable();
          };

          mapContainer.addEventListener('pointerup', endBoundaryTrace, true);
          mapContainer.addEventListener('pointercancel', endBoundaryTrace, true);
        } else {
          map.on('click', (event) => {
            if (!drawingBoundary) return;
            boundaryPoints.push(event.latlng);
            updateBoundaryDraft();
          });
        }

        document.querySelector('#mapStatus').textContent = 'Pinned location: Sudha milk dairy pidhauli · select “Use my device location” to switch to your live device position.';
        document.querySelector('#mapStatusFooter').textContent = 'Sudha Milk Dairy · 25.5302806, 85.9195789';
      }

      loadData();
    
