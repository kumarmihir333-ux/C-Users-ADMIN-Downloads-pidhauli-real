import json
import sqlite3

from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from app import (
    app, build_user_insights, get_db_connection, get_owned_field, get_user_session,
    get_weather, parse_float, parse_required_text,
)
from routes.satellite_services import parse_satellite_geometry


@app.route('/api/me')
def api_me():
    user = get_user_session()
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({'logged_in': True, 'user': user})


@app.route('/api/login', methods=['POST'])
def api_login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    password = payload.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        conn.close()
        return jsonify({'error': 'Invalid email or password'}), 401

    session['user_email'] = user['email']
    session['user_name'] = user['full_name']
    conn.close()
    return jsonify({'ok': True, 'user': {'email': user['email'], 'full_name': user['full_name']}})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/watchlist', methods=['GET', 'POST', 'DELETE'])
def watchlist():
    user = get_user_session()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    conn = get_db_connection()
    if request.method == 'GET':
        rows = conn.execute(
            'SELECT crop_id FROM watchlist WHERE user_email = ?', (user['email'],)
        ).fetchall()
        conn.close()
        return jsonify({'items': [row['crop_id'] for row in rows]})

    payload = request.get_json(silent=True) or {}
    crop_id = payload.get('crop_id')
    if crop_id is None:
        conn.close()
        return jsonify({'error': 'crop_id is required'}), 400
    try:
        crop_id = int(crop_id)
        if crop_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'error': 'crop_id must be a positive integer'}), 400

    try:
        if request.method == 'DELETE':
            conn.execute(
                'DELETE FROM watchlist WHERE user_email = ? AND crop_id = ?',
                (user['email'], crop_id),
            )
            conn.commit()
            conn.close()
            return jsonify({'ok': True, 'crop_id': crop_id})
        conn.execute(
            'INSERT OR IGNORE INTO watchlist (user_email, crop_id) VALUES (?, ?)',
            (user['email'], crop_id),
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'crop_id': crop_id})
    except sqlite3.Error as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 500


@app.route('/api/insights')
def api_user_insights():
    user = get_user_session()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify(build_user_insights(user['email']))


@app.route('/api/fields', methods=['GET', 'POST'])
def api_fields():
    user = get_user_session()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    conn = get_db_connection()
    if request.method == 'GET':
        rows = conn.execute(
            '''
            SELECT f.id, f.name, f.boundary_json, f.area_sqm, f.created_at, f.updated_at,
                   (SELECT COUNT(*) FROM satellite_analyses a WHERE a.field_id = f.id) AS analysis_count,
                   (SELECT a.created_at FROM satellite_analyses a WHERE a.field_id = f.id ORDER BY a.id DESC LIMIT 1) AS last_analysis_at
            FROM farm_fields f
            WHERE f.user_email = ?
            ORDER BY f.updated_at DESC, f.id DESC
            ''',
            (user['email'],),
        ).fetchall()
        conn.close()
        return jsonify([{
            **dict(row),
            'boundary': json.loads(row['boundary_json']),
        } for row in rows])

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        conn.close()
        return jsonify({'error': 'A JSON object is required'}), 400
    try:
        name = parse_required_text(payload, 'name', 80)
        geometry = parse_satellite_geometry(payload)
        area_sqm = parse_float(payload, 'area_sqm', 0)
        boundary = geometry['coordinates'][0][:-1]
        boundary_json = json.dumps(boundary, separators=(',', ':'))
        conn.execute(
            'INSERT INTO farm_fields (user_email, name, boundary_json, area_sqm) VALUES (?, ?, ?, ?)',
            (user['email'], name, boundary_json, area_sqm),
        )
        conn.commit()
        row = conn.execute(
            'SELECT id, name, boundary_json, area_sqm, created_at, updated_at '
            'FROM farm_fields WHERE user_email = ? AND name = ?',
            (user['email'], name),
        ).fetchone()
        conn.close()
        return jsonify({
            'ok': True,
            'id': row['id'],
            'name': row['name'],
            'boundary': json.loads(row['boundary_json']),
            'area_sqm': row['area_sqm'],
        }), 201
    except ValueError as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Could not save this field'}), 409


@app.route('/api/fields/<int:field_id>/analyses', methods=['GET', 'POST'])
def api_field_analyses(field_id):
    user = get_user_session()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    conn = get_db_connection()
    field = get_owned_field(conn, field_id, user['email'])
    if not field:
        conn.close()
        return jsonify({'error': 'Field not found'}), 404

    if request.method == 'GET':
        rows = conn.execute(
            'SELECT id, result_json, created_at FROM satellite_analyses '
            'WHERE field_id = ? ORDER BY id DESC LIMIT 30',
            (field_id,),
        ).fetchall()
        conn.close()
        return jsonify([{
            'id': row['id'],
            'created_at': row['created_at'],
            'result': json.loads(row['result_json']),
        } for row in rows])

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('result'), dict):
        conn.close()
        return jsonify({'error': 'A result object is required'}), 400
    try:
        geometry = parse_satellite_geometry(payload)
        area_sqm = parse_float(payload, 'area_sqm', 0)
    except ValueError as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 400
    result = payload['result']
    if not isinstance(result.get('observations'), list) or not result['observations']:
        conn.close()
        return jsonify({'error': 'Result must contain satellite observations'}), 400
    observations = []
    for observation in result['observations']:
        if not isinstance(observation, dict):
            conn.close()
            return jsonify({'error': 'Each observation must be an object'}), 400
        observations.append({
            key: value for key, value in observation.items()
            if not key.startswith('ndvi_pixels')
        })
    saved_result = {
        'available': bool(result.get('available')),
        'observations': observations,
        'comparisons': result.get('comparisons', []),
        'unavailable_seasons': result.get('unavailable_seasons', []),
        'season_summaries': result.get('season_summaries', []),
        'weather_context': result.get('weather_context'),
        'boundary': geometry['coordinates'][0][:-1],
        'message': result.get('message', ''),
    }
    try:
        result_json = json.dumps(saved_result, separators=(',', ':'), allow_nan=False)
        if len(result_json) > 200_000:
            raise ValueError('Analysis result is too large to save')
        cursor = conn.execute(
            'INSERT INTO satellite_analyses (field_id, result_json) VALUES (?, ?)',
            (field_id, result_json),
        )
        conn.execute(
            'UPDATE farm_fields SET boundary_json = ?, area_sqm = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (json.dumps(geometry['coordinates'][0][:-1], separators=(',', ':')), area_sqm, field_id),
        )
        conn.commit()
        analysis_id = cursor.lastrowid
        conn.close()
        return jsonify({'ok': True, 'id': analysis_id}), 201
    except (TypeError, ValueError) as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.Error:
        conn.rollback()
        conn.close()
        raise


@app.route('/api/inquiries', methods=['POST'])
def api_inquiries():
    payload = request.get_json(silent=True) or {}
    crop_name = (payload.get('crop_name') or '').strip()
    buyer_name = (payload.get('buyer_name') or '').strip()
    phone = (payload.get('phone') or '').strip()
    quantity = (payload.get('quantity') or '').strip()
    message = (payload.get('message') or '').strip()

    if not crop_name or not buyer_name or not phone or not quantity:
        return jsonify({'error': 'crop_name, buyer_name, phone and quantity are required'}), 400

    user = get_user_session()
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO inquiries (user_email, crop_name, buyer_name, phone, quantity, message) VALUES (?, ?, ?, ?, ?, ?)',
        (user['email'] if user else None, crop_name, buyer_name, phone, quantity, message),
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/register', methods=['POST'])
def api_register():
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    full_name = (payload.get('full_name') or '').strip()
    password = payload.get('password') or ''

    if not email or not full_name or not password:
        return jsonify({'error': 'email, full_name and password are required'}), 400

    password_hash = generate_password_hash(password)
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (email, password_hash, full_name) VALUES (?, ?, ?)',
            (email, password_hash, full_name),
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'A user with this email already exists'}), 409
