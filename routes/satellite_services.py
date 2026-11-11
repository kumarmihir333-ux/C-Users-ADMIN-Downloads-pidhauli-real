import math
from datetime import date, datetime, time, timedelta, timezone

import planetary_computer
import requests
from pystac_client import Client

from app import PLANETARY_COMPUTER_STAC_URL, app


def parse_satellite_geometry(payload):
    if not isinstance(payload, dict):
        raise ValueError('A JSON object is required')
    boundary = payload.get('boundary')
    if not isinstance(boundary, list) or not 3 <= len(boundary) <= 1000:
        raise ValueError('boundary must contain between 3 and 1000 [longitude, latitude] points')

    coordinates = []
    try:
        for point in boundary:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError
            longitude, latitude = (float(value) for value in point)
            if (
                not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
                or not math.isfinite(longitude)
                or not math.isfinite(latitude)
            ):
                raise ValueError
            coordinates.append([longitude, latitude])
    except (TypeError, ValueError):
        raise ValueError('Each boundary point must contain valid longitude and latitude coordinates')

    if len(set(map(tuple, coordinates))) < 3:
        raise ValueError('Boundary must contain at least three distinct points')
    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    signed_area = sum(
        coordinates[index][0] * coordinates[index + 1][1]
        - coordinates[index + 1][0] * coordinates[index][1]
        for index in range(len(coordinates) - 1)
    )
    if abs(signed_area) < 1e-12:
        raise ValueError('Boundary must enclose an area')
    longitudes = [point[0] for point in coordinates]
    latitudes = [point[1] for point in coordinates]
    if max(longitudes) - min(longitudes) > 0.2 or max(latitudes) - min(latitudes) > 0.2:
        raise ValueError('Boundary is too large; satellite lookup is limited to 0.2 degrees in each direction')
    mean_latitude = math.radians(sum(latitudes[:-1]) / (len(latitudes) - 1))
    radius = 6371008.8
    projected = [
        (
            math.radians(longitude) * radius * math.cos(mean_latitude),
            math.radians(latitude) * radius,
        )
        for longitude, latitude in coordinates
    ]
    area_sqm = abs(sum(
        projected[index][0] * projected[index + 1][1]
        - projected[index + 1][0] * projected[index][1]
        for index in range(len(projected) - 1)
    )) / 2
    if area_sqm > 2_000_000:
        raise ValueError('Boundary is too large for a single field analysis (maximum 200 hectares)')
    return {'type': 'Polygon', 'coordinates': [coordinates]}


def find_sentinel_items(geometry, limit):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=180)
    catalog = Client.open(PLANETARY_COMPUTER_STAC_URL, timeout=15)
    search = catalog.search(
        collections=['sentinel-2-l2a'],
        intersects=geometry,
        datetime=f'{start_date.isoformat()}/{end_date.isoformat()}',
        query={'eo:cloud_cover': {'lt': 40}},
        sortby=[{'field': 'properties.datetime', 'direction': 'desc'}],
        max_items=limit,
    )
    return list(search.items())


def build_season_windows(now=None):
    current = now or datetime.now(timezone.utc)
    today = current.date()
    first_date = date(today.year - 1, 3, 1)
    windows = []

    for year in range(first_date.year, today.year + 1):
        definitions = (
            ('Zaid', date(year, 3, 1), date(year, 6, 1)),
            ('Kharif', date(year, 6, 1), date(year, 10, 1)),
            ('Rabi', date(year, 10, 1), date(year + 1, 3, 1)),
        )
        for season, start, end in definitions:
            if end <= first_date or start > today:
                continue
            start = max(start, first_date)
            end = min(end, today + timedelta(days=1))
            label = f'Rabi {year}-{str(year + 1)[-2:]}' if season == 'Rabi' else f'{season} {year}'
            windows.append({
                'season': season,
                'label': label,
                'start': start.isoformat(),
                'end': end.isoformat(),
                'in_progress': end > today,
            })
    return windows


def find_seasonal_scenes(geometry, windows):
    catalog = Client.open(PLANETARY_COMPUTER_STAC_URL, timeout=15)
    scenes = []
    for window in windows:
        final_day = date.fromisoformat(window['end']) - timedelta(days=1)
        search = catalog.search(
            collections=['sentinel-2-l2a'],
            intersects=geometry,
            datetime=f"{window['start']}/{final_day.isoformat()}",
            query={'eo:cloud_cover': {'lt': 40}},
            sortby=[{'field': 'properties.datetime', 'direction': 'desc'}],
            max_items=40,
        )
        candidates = sorted(
            search.items(),
            key=lambda item: item.datetime or datetime.min.replace(tzinfo=timezone.utc),
        )
        start = date.fromisoformat(window['start'])
        end = date.fromisoformat(window['end'])
        duration = max(1, (end - start).days)
        selected = []
        for fraction in (1 / 3, 2 / 3):
            target = datetime.combine(
                start + timedelta(days=round(duration * fraction)),
                time.min,
                tzinfo=timezone.utc,
            )
            options = [
                item for item in candidates
                if item not in selected
                and all(abs((item.datetime - prior.datetime).days) >= 21 for prior in selected)
            ]
            if options:
                selected.append(min(
                    options,
                    key=lambda item: (
                        abs((item.datetime or target) - target),
                        item.properties.get('eo:cloud_cover', 100),
                    ),
                ))
        scenes.append((window, selected))
    return scenes


def compute_ndvi_statistics(item, geometry, include_pixels=False):
    import numpy as np
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.mask import mask
    from rasterio.warp import Resampling, reproject, transform_geom

    signed_item = planetary_computer.sign(item)
    required_assets = ('B04', 'B08', 'SCL')
    if any(key not in signed_item.assets for key in required_assets):
        raise ValueError(f'Sentinel-2 scene {item.id} is missing required analysis bands')

    with rasterio.open(signed_item.assets['B04'].href) as red_source, \
            rasterio.open(signed_item.assets['B08'].href) as nir_source, \
            rasterio.open(signed_item.assets['SCL'].href) as scl_source:
        if red_source.crs != nir_source.crs:
            raise ValueError(f'Sentinel-2 scene {item.id} red and near-infrared grids do not match')
        projected_geometry = transform_geom('EPSG:4326', red_source.crs, geometry)
        red, transform = mask(red_source, [projected_geometry], crop=True, filled=True, nodata=0)
        nir, nir_transform = mask(nir_source, [projected_geometry], crop=True, filled=True, nodata=0)
        if red.shape != nir.shape or transform != nir_transform:
            raise ValueError(f'Sentinel-2 scene {item.id} red and near-infrared pixel grids do not align')

        scene_class = np.zeros(red.shape[1:], dtype=np.uint8)
        reproject(
            source=rasterio.band(scl_source, 1),
            destination=scene_class,
            src_transform=scl_source.transform,
            src_crs=scl_source.crs,
            src_nodata=scl_source.nodata,
            dst_transform=transform,
            dst_crs=red_source.crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )
        inside_boundary = geometry_mask(
            [projected_geometry],
            out_shape=red.shape[1:],
            transform=transform,
            invert=True,
        )
        red_pixels = red[0].astype(np.float32)
        nir_pixels = nir[0].astype(np.float32)
        denominator = nir_pixels + red_pixels
        valid = (
            inside_boundary
            & np.isin(scene_class, (4, 5))
            & (red_pixels > 0)
            & (nir_pixels > 0)
            & (denominator > 0)
        )
        valid_count = int(np.count_nonzero(valid))
        if valid_count < 4:
            raise ValueError(
                f'Sentinel-2 scene {item.id} has fewer than four clear land pixels inside the drawn boundary'
            )
        ndvi = (nir_pixels[valid] - red_pixels[valid]) / denominator[valid]
        field_count = int(np.count_nonzero(inside_boundary))
        statistics = {
            'mean_ndvi': round(float(np.mean(ndvi)), 3),
            'median_ndvi': round(float(np.median(ndvi)), 3),
            'green_pixels_pct': round(float(np.count_nonzero(ndvi >= 0.3) / valid_count * 100), 1),
            'valid_pixels': valid_count,
            'field_pixels': field_count,
            'coverage_pct': round(valid_count / field_count * 100, 1) if field_count else 0,
        }
        coverage = statistics['coverage_pct']
        statistics['quality'] = 'good' if coverage >= 70 else ('partial' if coverage >= 40 else 'low')
        if include_pixels:
            row_indices, column_indices = np.where(valid)
            statistics['ndvi_pixels_available'] = len(row_indices) <= 2000
            if statistics['ndvi_pixels_available']:
                from rasterio.transform import xy
                from rasterio.warp import transform as transform_coordinates

                pixel_coordinates = []
                for row_index, column_index in zip(row_indices.tolist(), column_indices.tolist()):
                    corners = [
                        xy(transform, row_index, column_index, offset='ul'),
                        xy(transform, row_index, column_index, offset='ur'),
                        xy(transform, row_index, column_index, offset='lr'),
                        xy(transform, row_index, column_index, offset='ll'),
                    ]
                    pixel_coordinates.extend(corners + [corners[0]])
                geographic_x, geographic_y = transform_coordinates(
                    red_source.crs,
                    'EPSG:4326',
                    [point[0] for point in pixel_coordinates],
                    [point[1] for point in pixel_coordinates],
                )
                ndvi_values = ndvi.tolist()
                statistics['ndvi_pixels'] = [
                    {
                        'coordinates': [
                            [round(geographic_x[offset + corner], 7), round(geographic_y[offset + corner], 7)]
                            for corner in range(5)
                        ],
                        'value': round(float(ndvi_values[index]), 3),
                    }
                    for index, offset in enumerate(range(0, len(geographic_x), 5))
                ]
        return statistics


def add_weather_context(observations, geometry):
    if not observations:
        return None

    india_timezone = timezone(timedelta(hours=5, minutes=30))
    local_dates = [
        datetime.fromisoformat(item['acquired_at']).astimezone(india_timezone).date()
        for item in observations
        if item.get('acquired_at')
    ]
    if not local_dates:
        return None
    points = geometry['coordinates'][0][:-1]
    latitude = sum(point[1] for point in points) / len(points)
    longitude = sum(point[0] for point in points) / len(points)
    start_date = min(local_dates) - timedelta(days=13)
    end_date = max(local_dates)
    response = requests.get(
        'https://archive-api.open-meteo.com/v1/archive',
        params={
            'latitude': latitude,
            'longitude': longitude,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'daily': 'precipitation_sum,temperature_2m_max,temperature_2m_min',
            'timezone': 'Asia/Kolkata',
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f'Open-Meteo archive returned HTTP {response.status_code}')
    payload = response.json()
    daily = payload.get('daily')
    if not isinstance(daily, dict) or not isinstance(daily.get('time'), list):
        raise RuntimeError('Open-Meteo archive response did not contain daily weather data')
    weather_by_day = {
        day: {
            'rain': rainfall,
            'max': maximum,
            'min': minimum,
        }
        for day, rainfall, maximum, minimum in zip(
            daily['time'],
            daily.get('precipitation_sum', []),
            daily.get('temperature_2m_max', []),
            daily.get('temperature_2m_min', []),
        )
    }

    for observation in observations:
        if not observation.get('acquired_at'):
            continue
        scene_day = datetime.fromisoformat(
            observation['acquired_at']
        ).astimezone(india_timezone).date()
        days = [
            weather_by_day.get((scene_day - timedelta(days=offset)).isoformat())
            for offset in range(13, -1, -1)
        ]
        available_days = [day for day in days if day and day['rain'] is not None]
        temperatures = [
            (day['max'] + day['min']) / 2
            for day in days
            if day and day['max'] is not None and day['min'] is not None
        ]
        observation['rainfall_14d_mm'] = round(
            sum(day['rain'] for day in available_days), 1
        ) if available_days else None
        observation['mean_temp_14d_c'] = round(
            sum(temperatures) / len(temperatures), 1
        ) if temperatures else None
        observation['weather_days'] = len(available_days)
    return 'Historical rainfall and temperature from Open-Meteo for the 14 days through each satellite scene date.'
