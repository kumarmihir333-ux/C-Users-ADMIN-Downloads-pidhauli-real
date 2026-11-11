import os
import secrets
import sqlite3
from datetime import datetime

import requests
from flask import Flask, jsonify, session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR') or os.path.join(BASE_DIR, 'database')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'pidhauli.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'database', 'schema.sql')
PLANETARY_COMPUTER_STAC_URL = 'https://planetarycomputer.microsoft.com/api/stac/v1'

app = Flask(__name__)
secret_key = os.getenv('FLASK_SECRET_KEY')
if os.getenv('APP_ENV') == 'production' and not secret_key:
    raise RuntimeError('FLASK_SECRET_KEY must be configured in production')
app.secret_key = secret_key or secrets.token_urlsafe(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('APP_ENV') == 'production',
)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db_connection()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as fh:
        conn.executescript(fh.read())
    inquiry_columns = {
        row['name'] for row in conn.execute('PRAGMA table_info(inquiries)').fetchall()
    }
    if 'status' not in inquiry_columns:
        conn.execute(
            "ALTER TABLE inquiries ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
    conn.commit()
    conn.close()


def create_admin_from_environment():
    email = os.getenv('ADMIN_EMAIL')
    password = os.getenv('ADMIN_PASSWORD')
    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError('ADMIN_EMAIL and ADMIN_PASSWORD must both be configured')

    from werkzeug.security import generate_password_hash

    email = email.strip().lower()
    full_name = (os.getenv('ADMIN_NAME') or 'Pidhauli Admin').strip()
    if not email or not full_name or len(password) < 12:
        raise RuntimeError(
            'Admin email/name must not be empty and ADMIN_PASSWORD must be at least 12 characters'
        )

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO admin_users (email, password_hash, full_name) VALUES (?, ?, ?)',
            (email, generate_password_hash(password), full_name),
        )
        conn.commit()
    finally:
        conn.close()


def parse_saved_field_id(value):
    try:
        field_id = int(value)
    except (TypeError, ValueError):
        raise ValueError('field id must be a positive integer')
    if field_id < 1:
        raise ValueError('field id must be a positive integer')
    return field_id


def get_owned_field(conn, field_id, user_email):
    return conn.execute(
        'SELECT id, name, boundary_json, area_sqm, created_at, updated_at '
        'FROM farm_fields WHERE id = ? AND user_email = ?',
        (field_id, user_email),
    ).fetchone()


def get_latest_prices():
    query = '''
        SELECT c.id, c.name, c.local_name, c.category, c.icon, c.description,
               p.price_per_qtl, p.change_pct, p.trend_data, m.name AS market_name,
               m.location, m.state, m.latitude, m.longitude
        FROM crops c
        JOIN crop_prices p ON p.crop_id = c.id
        JOIN markets m ON m.id = p.market_id
        WHERE p.id IN (
            SELECT MAX(p2.id)
            FROM crop_prices p2
            GROUP BY p2.crop_id
        )
        ORDER BY c.name ASC
    '''
    conn = get_db_connection()
    rows = conn.execute(query).fetchall()
    conn.close()

    crops = []
    for row in rows:
        crops.append({
            'id': row['id'],
            'name': row['name'],
            'local_name': row['local_name'],
            'category': row['category'],
            'icon': row['icon'],
            'description': row['description'],
            'price': row['price_per_qtl'],
            'change': row['change_pct'],
            'trend': [int(part.strip()) for part in row['trend_data'].split(',') if part.strip()],
            'market': row['market_name'],
            'location': row['location'],
            'state': row['state'],
            'latitude': row['latitude'],
            'longitude': row['longitude'],
        })
    return crops


def get_demand():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM demand_requests ORDER BY id ASC').fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_markets():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM markets ORDER BY id ASC').fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_user_session():
    user_email = session.get('user_email')
    if not user_email:
        return None
    conn = get_db_connection()
    user = conn.execute('SELECT email, full_name FROM users WHERE email = ?', (user_email,)).fetchone()
    conn.close()
    return dict(user) if user else None


def predict_next_price(observations):
    prices = [float(row['price_per_qtl']) for row in observations]
    if len(prices) < 3 or len(set(prices)) < 2 or prices[-1] <= 0:
        return None

    sample_count = len(prices)
    x_mean = (sample_count - 1) / 2
    y_mean = sum(prices) / sample_count
    denominator = sum((index - x_mean) ** 2 for index in range(sample_count))
    slope = sum(
        (index - x_mean) * (price - y_mean)
        for index, price in enumerate(prices)
    ) / denominator
    estimate = max(0, y_mean + slope * (sample_count - x_mean))
    return {
        'estimate_per_qtl': round(estimate),
        'change_pct': round((estimate - prices[-1]) / prices[-1] * 100, 2),
        'samples': sample_count,
    }


def build_user_insights(user_email):
    conn = get_db_connection()
    watched = conn.execute(
        '''
        SELECT c.id, c.name, c.category, p.price_per_qtl, p.change_pct,
               m.name AS market_name
        FROM watchlist w
        JOIN crops c ON c.id = w.crop_id
        LEFT JOIN crop_prices p ON p.id = (
            SELECT p2.id FROM crop_prices p2
            WHERE p2.crop_id = c.id ORDER BY p2.id DESC LIMIT 1
        )
        LEFT JOIN markets m ON m.id = p.market_id
        WHERE w.user_email = ?
        ORDER BY c.name COLLATE NOCASE
        ''',
        (user_email,),
    ).fetchall()
    inquiries_count = conn.execute(
        'SELECT COUNT(*) AS total FROM inquiries WHERE user_email = ?',
        (user_email,),
    ).fetchone()['total']
    demand = conn.execute(
        'SELECT crop_name, quantity, place, delivery, quality FROM demand_requests'
    ).fetchall()

    watched_ids = [row['id'] for row in watched]
    histories = {}
    if watched_ids:
        placeholders = ','.join('?' for _ in watched_ids)
        history_rows = conn.execute(
            f'''
            SELECT crop_id, price_per_qtl
            FROM crop_prices
            WHERE crop_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            ''',
            watched_ids,
        ).fetchall()
        for row in history_rows:
            histories.setdefault(row['crop_id'], []).append(row)
    conn.close()

    insights = []
    changes = []
    demand_by_crop = {}
    for row in demand:
        crop_name = row['crop_name'].split('·', 1)[0].strip().casefold()
        demand_by_crop.setdefault(crop_name, []).append(dict(row))

    for crop in watched:
        name = crop['name']
        if crop['change_pct'] is not None:
            changes.append(float(crop['change_pct']))
        for request_row in demand_by_crop.get(name.casefold(), []):
            insights.append({
                'type': 'demand',
                'crop': name,
                'title': 'Buyer demand matches your watchlist',
                'detail': (
                    f"{request_row['quantity']} wanted in {request_row['place']} · "
                    f"{request_row['delivery']} · {request_row['quality']}"
                ),
            })

        forecast = predict_next_price(histories.get(crop['id'], []))
        if forecast:
            direction = 'up' if forecast['change_pct'] > 0 else (
                'down' if forecast['change_pct'] < 0 else 'flat'
            )
            insights.append({
                'type': 'forecast',
                'crop': name,
                'title': f"Model estimate: ₹{forecast['estimate_per_qtl']:,}/qtl next",
                'detail': (
                    f"Linear trend from {forecast['samples']} recorded prices; "
                    f"{forecast['change_pct']:+.1f}% vs. latest observation. "
                    'Experimental estimate, not a guarantee.'
                ),
                'direction': direction,
            })
        elif crop['change_pct'] is not None:
            move = float(crop['change_pct'])
            insights.append({
                'type': 'market',
                'crop': name,
                'title': f"Recent reported move: {move:+.1f}%",
                'detail': (
                    f"Latest indicative price at {crop['market_name'] or 'the recorded market'}. "
                    'More recorded prices are needed for a trend estimate.'
                ),
                'direction': 'up' if move > 0 else ('down' if move < 0 else 'flat'),
            })

    average_change = round(sum(changes) / len(changes), 2) if changes else None
    model_data_count = sum(
        len(histories.get(crop['id'], [])) >= 3
        and len({row['price_per_qtl'] for row in histories.get(crop['id'], [])}) >= 2
        for crop in watched
    )
    return {
        'watchlist_count': len(watched),
        'inquiries_count': inquiries_count,
        'average_change_pct': average_change,
        'modelled_crops': model_data_count,
        'insights': insights,
        'data_note': (
            'Trend estimates appear only for watched crops with at least three distinct recorded price observations.'
            if model_data_count
            else 'Not enough recorded price history for an ML estimate yet. Three or more distinct observations are needed.'
        ),
    }


def get_admin_session():
    admin_email = session.get('admin_email')
    if not admin_email:
        return None
    conn = get_db_connection()
    admin = conn.execute('SELECT email, full_name FROM admin_users WHERE email = ?', (admin_email,)).fetchone()
    conn.close()
    return dict(admin) if admin else None


def get_admin_dashboard():
    conn = get_db_connection()
    summary = {
        'crops': conn.execute('SELECT COUNT(*) AS total FROM crops').fetchone()['total'],
        'markets': conn.execute('SELECT COUNT(*) AS total FROM markets').fetchone()['total'],
        'inquiries': conn.execute('SELECT COUNT(*) AS total FROM inquiries').fetchone()['total'],
        'watchlist': conn.execute('SELECT COUNT(*) AS total FROM watchlist').fetchone()['total'],
    }
    inquiries = conn.execute(
        'SELECT id, crop_name, buyer_name, phone, quantity, message, status, created_at FROM inquiries ORDER BY id DESC LIMIT 10'
    ).fetchall()
    crops = conn.execute(
        '''
        SELECT c.id, c.name, c.local_name, c.category, p.price_per_qtl, p.change_pct, m.name AS market_name
        FROM crops c
        JOIN crop_prices p ON p.crop_id = c.id
        JOIN markets m ON m.id = p.market_id
        WHERE p.id IN (SELECT MAX(p2.id) FROM crop_prices p2 GROUP BY p2.crop_id)
        ORDER BY c.name ASC
        LIMIT 20
        '''
    ).fetchall()
    import_jobs = conn.execute(
        'SELECT id, filename, imported_rows, status, created_at FROM price_import_jobs ORDER BY id DESC LIMIT 10'
    ).fetchall()
    conn.close()
    return {
        'summary': summary,
        'inquiries': [dict(row) for row in inquiries],
        'crops': [dict(row) for row in crops],
        'import_jobs': [dict(row) for row in import_jobs],
    }


def admin_required():
    if not get_admin_session():
        return jsonify({'error': 'Authentication required'}), 401
    return None


def parse_required_text(payload, field, max_length=200):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} is required')
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f'{field} must be {max_length} characters or fewer')
    return value


def parse_optional_text(payload, field, default='', max_length=500):
    value = payload.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f'{field} must be text')
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f'{field} must be {max_length} characters or fewer')
    return value


def parse_float(payload, field, minimum=None):
    value = payload.get(field)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be a number')
    if parsed != parsed or parsed in (float('inf'), float('-inf')):
        raise ValueError(f'{field} must be a finite number')
    if minimum is not None and parsed < minimum:
        raise ValueError(f'{field} must be at least {minimum}')
    return parsed


def get_weather():
    api_key = os.getenv('OPENWEATHER_API_KEY')
    if not api_key:
        return {
            'current': {
                'temp': 29,
                'description': 'Clear sky',
                'humidity': 58,
                'windSpeed': 11,
                'iconCode': 800,
                'time': int(datetime.now().timestamp())
            },
            'forecast': [
                {'date': '2026-11-11', 'max': 31, 'min': 20, 'description': 'Clear', 'iconCode': 800},
                {'date': '2026-11-12', 'max': 30, 'min': 20, 'description': 'Sunny', 'iconCode': 801},
                {'date': '2026-11-13', 'max': 31, 'min': 21, 'description': 'Warm', 'iconCode': 800},
                {'date': '2026-11-14', 'max': 32, 'min': 21, 'description': 'Partly cloudy', 'iconCode': 801},
                {'date': '2026-11-15', 'max': 33, 'min': 22, 'description': 'Bright', 'iconCode': 800},
            ]
        }

    lat = 25.5253
    lon = 85.9081
    url = (
        f'https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&exclude=minutely,hourly,alerts&units=metric&appid={api_key}'
    )
    response = requests.get(url, timeout=15)
    if response.status_code != 200:
        raise RuntimeError('Unable to fetch weather data')
    payload = response.json()
    current = payload.get('current', {})
    daily = payload.get('daily', [])[:5]

    return {
        'current': {
            'temp': round(current.get('temp', 0)),
            'description': current.get('weather', [{}])[0].get('description', 'Unknown'),
            'humidity': current.get('humidity', 0),
            'windSpeed': round(current.get('wind_speed', 0)),
            'iconCode': current.get('weather', [{}])[0].get('id', 800),
            'time': current.get('dt', int(datetime.now().timestamp())),
        },
        'forecast': [
            {
                'date': datetime.utcfromtimestamp(day.get('dt', 0)).strftime('%Y-%m-%d'),
                'max': round(day.get('temp', {}).get('max', 0)),
                'min': round(day.get('temp', {}).get('min', 0)),
                'description': day.get('weather', [{}])[0].get('description', 'Unknown'),
                'iconCode': day.get('weather', [{}])[0].get('id', 800),
            }
            for day in daily
        ]
    }


if __name__ == '__main__':
    import sys
    sys.modules.setdefault('app', sys.modules[__name__])

import routes.public
import routes.admin
import routes.accounts
import routes.satellite


if __name__ == '__main__':
    init_db()
    create_admin_from_environment()
    app.run(debug=os.getenv('APP_ENV') != 'production', host='0.0.0.0', port=5000)
