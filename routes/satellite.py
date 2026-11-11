import planetary_computer

from flask import jsonify, request

from app import app
from routes.satellite_services import (
    add_weather_context, build_season_windows, compute_ndvi_statistics,
    find_seasonal_scenes, find_sentinel_items, parse_satellite_geometry,
)


@app.route('/api/satellite/observations', methods=['POST'])
def api_satellite_observations():
    payload = request.get_json(silent=True)
    try:
        geometry = parse_satellite_geometry(payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        items = find_sentinel_items(geometry, limit=1)
        item = items[0] if items else None
        if item is None:
            return jsonify({
                'available': False,
                'collection': 'sentinel-2-l2a',
                'message': 'No Sentinel-2 scenes under 40% cloud cover were found for this boundary in the last 180 days.',
            })

        signed_item = planetary_computer.sign(item)
        preview = next(
            (
                signed_item.assets[key].href
                for key in ('rendered_preview', 'thumbnail', 'visual')
                if key in signed_item.assets
            ),
            None,
        )
        return jsonify({
            'available': True,
            'collection': 'sentinel-2-l2a',
            'item_id': item.id,
            'acquired_at': item.datetime.isoformat() if item.datetime else None,
            'cloud_cover_pct': item.properties.get('eo:cloud_cover'),
            'preview_url': preview,
            'message': 'Scene metadata is available. This checks imagery coverage only; it does not calculate crop health.',
        })
    except Exception:
        app.logger.exception('Planetary Computer Sentinel-2 search failed')
        return jsonify({'error': 'Satellite catalog lookup failed. Please try again later.'}), 502


@app.route('/api/satellite/ndvi', methods=['POST'])
def api_satellite_ndvi():
    try:
        geometry = parse_satellite_geometry(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        items = find_sentinel_items(geometry, limit=6)
        observations = []
        previews = []
        for item in items:
            statistics = compute_ndvi_statistics(item, geometry)
            observations.append({
                'item_id': item.id,
                'acquired_at': item.datetime.isoformat() if item.datetime else None,
                'cloud_cover_pct': item.properties.get('eo:cloud_cover'),
                **statistics,
            })
            if not previews:
                signed_item = planetary_computer.sign(item)
                previews = [
                    signed_item.assets[key].href
                    for key in ('rendered_preview', 'thumbnail', 'visual')
                    if key in signed_item.assets
                ][:1]

        observations.sort(key=lambda result: result['acquired_at'] or '')
        return jsonify({
            'available': bool(observations),
            'collection': 'sentinel-2-l2a',
            'observations': observations,
            'preview_url': previews[0] if previews else None,
            'message': (
                'NDVI is calculated from Sentinel-2 B08 (near-infrared) and B04 (red) reflectance. '
                'SCL cloud, shadow, water and invalid pixels are excluded. NDVI describes greenness; '
                'it does not identify crop type, diagnose crop health or estimate yield.'
            ) if observations else (
                'No Sentinel-2 scenes under 40% cloud cover were found for this boundary in the last 180 days.'
            ),
        })
    except Exception:
        app.logger.exception('Planetary Computer Sentinel-2 NDVI processing failed')
        return jsonify({'error': 'Sentinel-2 NDVI processing failed. Please try again later.'}), 502


@app.route('/api/satellite/seasonal', methods=['POST'])
def api_satellite_seasonal():
    try:
        geometry = parse_satellite_geometry(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        windows = build_season_windows()
        scenes_by_season = find_seasonal_scenes(geometry, windows)
        observations = []
        unavailable = []
        latest_item = max(
            (
                item
                for _, items in scenes_by_season
                for item in items
                if item.datetime
            ),
            key=lambda item: item.datetime,
            default=None,
        )
        for window, items in scenes_by_season:
            if not items:
                unavailable.append({
                    'season': window['label'],
                    'reason': 'No scene under 40% cloud cover was found for this season.',
                })
                continue

            last_error = None
            for item in items:
                try:
                    statistics = compute_ndvi_statistics(
                        item,
                        geometry,
                        include_pixels=latest_item is not None and item.id == latest_item.id,
                    )
                except ValueError as exc:
                    last_error = str(exc)
                    continue
                observations.append({
                    'season': window['season'],
                    'label': window['label'],
                    'in_progress': window['in_progress'],
                    'item_id': item.id,
                    'acquired_at': item.datetime.isoformat() if item.datetime else None,
                    'cloud_cover_pct': item.properties.get('eo:cloud_cover'),
                    **statistics,
                })
            if not any(observation['label'] == window['label'] for observation in observations):
                unavailable.append({
                    'season': window['label'],
                    'reason': last_error or 'No usable pixels found.',
                })

        observations.sort(key=lambda result: result['acquired_at'] or '')
        season_summaries = []
        for window in windows:
            season_observations = [
                observation for observation in observations
                if observation['label'] == window['label']
            ]
            if not season_observations:
                continue
            season_summaries.append({
                'season': window['season'],
                'label': window['label'],
                'in_progress': window['in_progress'],
                'mean_ndvi': round(
                    sum(item['mean_ndvi'] for item in season_observations)
                    / len(season_observations),
                    3,
                ),
                'samples': len(season_observations),
                'coverage_pct': round(
                    sum(item['coverage_pct'] for item in season_observations)
                    / len(season_observations),
                    1,
                ),
            })
        previous_by_season = {}
        comparisons = []
        for summary in season_summaries:
            prior = previous_by_season.get(summary['season'])
            if prior:
                comparisons.append({
                    'season': summary['season'],
                    'previous_label': prior['label'],
                    'current_label': summary['label'],
                    'previous_mean_ndvi': prior['mean_ndvi'],
                    'current_mean_ndvi': summary['mean_ndvi'],
                    'change': round(summary['mean_ndvi'] - prior['mean_ndvi'], 3),
                })
            previous_by_season[summary['season']] = summary

        preview = None
        if observations:
            selected = next(
                item
                for window, items in scenes_by_season
                for item in items
                if item.id == observations[-1]['item_id']
            )
            signed_item = planetary_computer.sign(selected)
            preview = next(
                (
                    signed_item.assets[key].href
                    for key in ('rendered_preview', 'thumbnail', 'visual')
                    if key in signed_item.assets
                ),
                None,
            )

        weather_context = None
        weather_error = None
        if observations:
            try:
                weather_context = add_weather_context(observations, geometry)
            except Exception:
                app.logger.exception('Open-Meteo historical weather context failed')
                weather_error = 'Historical weather context could not be loaded.'

        map_observation = next(
            (item for item in reversed(observations) if item.get('ndvi_pixels_available')),
            None,
        )
        return jsonify({
            'available': bool(observations),
            'observations': observations,
            'season_summaries': season_summaries,
            'comparisons': comparisons,
            'unavailable_seasons': unavailable,
            'weather_context': weather_context,
            'weather_error': weather_error,
            'ndvi_map': map_observation.get('ndvi_pixels', []) if map_observation else [],
            'ndvi_map_available': bool(map_observation and map_observation.get('ndvi_pixels')),
            'ndvi_map_scene': map_observation.get('label') if map_observation else None,
            'preview_url': preview,
            'message': (
                'Up to two clear satellite snapshots are sampled across each season; the season mean averages those snapshots. '
                'NDVI describes greenness; it does not identify crop type, diagnose crop health or estimate yield.'
            ) if observations else (
                'No usable Sentinel-2 scenes were found for these seasons and this boundary.'
            ),
        })
    except Exception:
        app.logger.exception('Planetary Computer seasonal NDVI comparison failed')
        return jsonify({'error': 'Seasonal satellite comparison failed. Please try again later.'}), 502
