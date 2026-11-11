import csv
import io
import sqlite3

from flask import jsonify, render_template, request, session
from werkzeug.security import check_password_hash

from app import (
    admin_required, app, get_admin_dashboard, get_admin_session, get_db_connection,
    parse_float, parse_optional_text, parse_required_text,
)


@app.route('/admin')
def admin_page():
    return render_template('admin.html')


@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    password = payload.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400

    conn = get_db_connection()
    admin = conn.execute('SELECT * FROM admin_users WHERE email = ?', (email,)).fetchone()
    if not admin or not check_password_hash(admin['password_hash'], password):
        conn.close()
        return jsonify({'error': 'Invalid admin credentials'}), 401

    session['admin_email'] = admin['email']
    session['admin_name'] = admin['full_name']
    conn.close()
    return jsonify({'ok': True, 'user': {'email': admin['email'], 'full_name': admin['full_name']}})


@app.route('/api/admin/logout', methods=['POST'])
def api_admin_logout():
    session.pop('admin_email', None)
    session.pop('admin_name', None)
    return jsonify({'ok': True})


@app.route('/api/admin/me')
def api_admin_me():
    admin = get_admin_session()
    if not admin:
        return jsonify({'logged_in': False})
    return jsonify({'logged_in': True, 'user': admin})


@app.route('/api/admin/dashboard')
def api_admin_dashboard():
    auth_error = admin_required()
    if auth_error:
        return auth_error
    return jsonify(get_admin_dashboard())


@app.route('/api/admin/inquiries')
def api_admin_inquiries():
    auth_error = admin_required()
    if auth_error:
        return auth_error
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT id, user_email, crop_name, buyer_name, phone, quantity, message, status, created_at '
        'FROM inquiries ORDER BY id DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/admin/inquiries/<int:inquiry_id>', methods=['PATCH'])
def api_admin_update_inquiry(inquiry_id):
    auth_error = admin_required()
    if auth_error:
        return auth_error
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'A JSON object is required'}), 400
    status = payload.get('status')
    if status not in {'pending', 'approved', 'rejected', 'closed'}:
        return jsonify({'error': 'status must be pending, approved, rejected, or closed'}), 400
    conn = get_db_connection()
    cursor = conn.execute(
        'UPDATE inquiries SET status = ? WHERE id = ?', (status, inquiry_id)
    )
    conn.commit()
    conn.close()
    if cursor.rowcount == 0:
        return jsonify({'error': 'Inquiry not found'}), 404
    return jsonify({'ok': True, 'id': inquiry_id, 'status': status})


@app.route('/api/admin/crops', methods=['GET', 'POST'])
def api_admin_crops():
    auth_error = admin_required()
    if auth_error:
        return auth_error

    conn = get_db_connection()
    if request.method == 'GET':
        rows = conn.execute(
            '''
            SELECT c.id, c.name, c.local_name, c.category, c.icon, c.description,
                   p.price_per_qtl, p.change_pct, p.trend_data, p.market_id,
                   m.name AS market_name
            FROM crops c
            LEFT JOIN crop_prices p ON p.id = (
                SELECT p2.id FROM crop_prices p2
                WHERE p2.crop_id = c.id ORDER BY p2.id DESC LIMIT 1
            )
            LEFT JOIN markets m ON m.id = p.market_id
            ORDER BY c.name COLLATE NOCASE
            '''
        ).fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        conn.close()
        return jsonify({'error': 'A JSON object is required'}), 400
    try:
        name = parse_required_text(payload, 'name')
        category = parse_required_text(payload, 'category', 80)
        local_name = parse_optional_text(payload, 'local_name', max_length=200)
        icon = parse_optional_text(payload, 'icon', '✳', 20) or '✳'
        description = parse_optional_text(payload, 'description')
        conn.execute(
            'INSERT INTO crops (name, local_name, category, icon, description) VALUES (?, ?, ?, ?, ?)',
            (name, local_name, category, icon, description),
        )
        crop_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if payload.get('price_per_qtl') not in (None, ''):
            price = parse_float(payload, 'price_per_qtl', 0)
            change_pct = parse_float(payload, 'change_pct', -100)
            try:
                market_id = int(payload.get('market_id'))
            except (TypeError, ValueError):
                raise ValueError('market_id must be a valid market id')
            market = conn.execute('SELECT id FROM markets WHERE id = ?', (market_id,)).fetchone()
            if not market:
                raise ValueError('market_id does not exist')
            trend = payload.get('trend_data') or '10,12,14,16,18,20,22'
            if not isinstance(trend, str) or len(trend) > 200:
                raise ValueError('trend_data must be a comma-separated string of at most 200 characters')
            conn.execute(
                'INSERT INTO crop_prices (crop_id, market_id, price_per_qtl, change_pct, trend_data) '
                'VALUES (?, ?, ?, ?, ?)',
                (crop_id, market_id, round(price), change_pct, trend),
            )
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': crop_id}), 201
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Could not create crop because related data is invalid'}), 409


@app.route('/api/admin/crops/<int:crop_id>', methods=['PUT', 'DELETE'])
def api_admin_crop(crop_id):
    auth_error = admin_required()
    if auth_error:
        return auth_error

    conn = get_db_connection()
    crop = conn.execute('SELECT id FROM crops WHERE id = ?', (crop_id,)).fetchone()
    if not crop:
        conn.close()
        return jsonify({'error': 'Crop not found'}), 404

    if request.method == 'DELETE':
        references = conn.execute(
            'SELECT (SELECT COUNT(*) FROM crop_prices WHERE crop_id = ?) + '
            '(SELECT COUNT(*) FROM watchlist WHERE crop_id = ?) AS total',
            (crop_id, crop_id),
        ).fetchone()['total']
        if references:
            conn.close()
            return jsonify({'error': 'Crop has price history or watchlist entries and cannot be deleted'}), 409
        conn.execute('DELETE FROM crops WHERE id = ?', (crop_id,))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        conn.close()
        return jsonify({'error': 'A JSON object is required'}), 400
    try:
        name = parse_required_text(payload, 'name')
        category = parse_required_text(payload, 'category', 80)
        local_name = parse_optional_text(payload, 'local_name', max_length=200)
        icon = parse_optional_text(payload, 'icon', '✳', 20) or '✳'
        description = parse_optional_text(payload, 'description')
        conn.execute(
            'UPDATE crops SET name = ?, local_name = ?, category = ?, icon = ?, description = ? WHERE id = ?',
            (name, local_name, category, icon, description, crop_id),
        )

        if payload.get('price_per_qtl') not in (None, ''):
            price = parse_float(payload, 'price_per_qtl', 0)
            change_pct = parse_float(payload, 'change_pct', -100)
            try:
                market_id = int(payload.get('market_id'))
            except (TypeError, ValueError):
                raise ValueError('market_id must be a valid market id')
            market = conn.execute('SELECT id FROM markets WHERE id = ?', (market_id,)).fetchone()
            if not market:
                raise ValueError('market_id does not exist')
            latest = conn.execute(
                'SELECT price_per_qtl, change_pct, market_id, trend_data FROM crop_prices '
                'WHERE crop_id = ? ORDER BY id DESC LIMIT 1',
                (crop_id,),
            ).fetchone()
            trend = payload.get('trend_data') or (
                latest['trend_data'] if latest else '10,12,14,16,18,20,22'
            )
            if not isinstance(trend, str) or len(trend) > 200:
                raise ValueError('trend_data must be a comma-separated string of at most 200 characters')
            rounded_price = round(price)
            if (
                latest is None
                or latest['price_per_qtl'] != rounded_price
                or latest['change_pct'] != change_pct
                or latest['market_id'] != market_id
                or ('trend_data' in payload and latest['trend_data'] != trend)
            ):
                conn.execute(
                    'INSERT INTO crop_prices (crop_id, market_id, price_per_qtl, change_pct, trend_data) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (crop_id, market_id, rounded_price, change_pct, trend),
                )
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': crop_id})
    except ValueError as exc:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({'error': 'Could not update crop because related data is invalid'}), 409


@app.route('/api/admin/markets', methods=['GET', 'POST'])
def api_admin_markets():
    auth_error = admin_required()
    if auth_error:
        return auth_error

    conn = get_db_connection()
    if request.method == 'GET':
        rows = conn.execute('SELECT * FROM markets ORDER BY name COLLATE NOCASE').fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        conn.close()
        return jsonify({'error': 'A JSON object is required'}), 400
    try:
        name = parse_required_text(payload, 'name')
        location = parse_required_text(payload, 'location')
        state_name = parse_required_text(payload, 'state', 100)
        latitude = parse_float(payload, 'latitude', -90)
        longitude = parse_float(payload, 'longitude', -180)
        if latitude > 90 or longitude > 180:
            raise ValueError('latitude must be between -90 and 90 and longitude between -180 and 180')
        market_type = parse_optional_text(payload, 'market_type', 'APMC', 80) or 'APMC'
        conn.execute(
            'INSERT INTO markets (name, location, state, latitude, longitude, market_type) VALUES (?, ?, ?, ?, ?, ?)',
            (name, location, state_name, latitude, longitude, market_type),
        )
        market_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': market_id}), 201
    except ValueError as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Could not create market'}), 409


@app.route('/api/admin/markets/<int:market_id>', methods=['PUT', 'DELETE'])
def api_admin_market(market_id):
    auth_error = admin_required()
    if auth_error:
        return auth_error
    conn = get_db_connection()
    market = conn.execute('SELECT id FROM markets WHERE id = ?', (market_id,)).fetchone()
    if not market:
        conn.close()
        return jsonify({'error': 'Market not found'}), 404

    if request.method == 'DELETE':
        references = conn.execute(
            'SELECT COUNT(*) AS total FROM crop_prices WHERE market_id = ?', (market_id,)
        ).fetchone()['total']
        if references:
            conn.close()
            return jsonify({'error': 'Market has price records and cannot be deleted'}), 409
        conn.execute('DELETE FROM markets WHERE id = ?', (market_id,))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        conn.close()
        return jsonify({'error': 'A JSON object is required'}), 400
    try:
        name = parse_required_text(payload, 'name')
        location = parse_required_text(payload, 'location')
        state_name = parse_required_text(payload, 'state', 100)
        latitude = parse_float(payload, 'latitude', -90)
        longitude = parse_float(payload, 'longitude', -180)
        if latitude > 90 or longitude > 180:
            raise ValueError('latitude must be between -90 and 90 and longitude between -180 and 180')
        market_type = parse_optional_text(payload, 'market_type', 'APMC', 80) or 'APMC'
        conn.execute(
            'UPDATE markets SET name = ?, location = ?, state = ?, latitude = ?, longitude = ?, market_type = ? WHERE id = ?',
            (name, location, state_name, latitude, longitude, market_type, market_id),
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': market_id})
    except ValueError as exc:
        conn.close()
        return jsonify({'error': str(exc)}), 400
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Could not update market'}), 409


@app.route('/api/admin/import-prices', methods=['POST'])
def api_admin_import_prices():
    auth_error = admin_required()
    if auth_error:
        return auth_error

    uploaded = request.files.get('file')
    if not uploaded:
        return jsonify({'error': 'CSV file is required'}), 400

    text = uploaded.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    required_fields = {'crop_name', 'market_name', 'price_per_qtl'}
    if not reader.fieldnames or not required_fields.issubset(set([field.strip() for field in reader.fieldnames])):
        return jsonify({'error': 'CSV must include crop_name, market_name, and price_per_qtl columns'}), 400

    imported_rows = 0
    conn = get_db_connection()
    for row in reader:
        if not row or not (row.get('crop_name') or '').strip():
            continue

        crop_name = (row.get('crop_name') or '').strip()
        market_name = (row.get('market_name') or '').strip() or 'Begusarai APMC'
        location = (row.get('location') or '').strip() or 'Teghra'
        state = (row.get('state') or '').strip() or 'Bihar'
        local_name = (row.get('local_name') or '').strip() or crop_name
        category = (row.get('category') or 'Grain').strip() or 'Grain'
        icon = (row.get('icon') or '✳').strip() or '✳'
        description = (row.get('description') or f'{crop_name} imported from CSV').strip() or f'{crop_name} imported from CSV'
        price = row.get('price_per_qtl') or 0
        change_pct = row.get('change_pct') or 0
        trend_data = (row.get('trend_data') or '10,12,14,16,18,20,22').strip() or '10,12,14,16,18,20,22'

        market = conn.execute('SELECT id FROM markets WHERE LOWER(name) = LOWER(?)', (market_name,)).fetchone()
        if not market:
            conn.execute(
                'INSERT INTO markets (name, location, state, latitude, longitude, market_type) VALUES (?, ?, ?, 25.5253, 85.9081, "APMC")',
                (market_name, location, state),
            )
            market = conn.execute('SELECT id FROM markets WHERE name = ?', (market_name,)).fetchone()

        crop = conn.execute('SELECT id FROM crops WHERE LOWER(name) = LOWER(?)', (crop_name,)).fetchone()
        if not crop:
            conn.execute(
                'INSERT INTO crops (name, local_name, category, icon, description) VALUES (?, ?, ?, ?, ?)',
                (crop_name, local_name, category, icon, description),
            )
            crop = conn.execute('SELECT id FROM crops WHERE name = ?', (crop_name,)).fetchone()

        conn.execute(
            'INSERT INTO crop_prices (crop_id, market_id, price_per_qtl, change_pct, trend_data) VALUES (?, ?, ?, ?, ?)',
            (crop['id'], market['id'], int(float(price)), float(change_pct), trend_data),
        )
        imported_rows += 1

    conn.execute(
        'INSERT INTO price_import_jobs (filename, imported_rows, status) VALUES (?, ?, ?)',
        (uploaded.filename, imported_rows, 'completed'),
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'imported_rows': imported_rows, 'filename': uploaded.filename})
