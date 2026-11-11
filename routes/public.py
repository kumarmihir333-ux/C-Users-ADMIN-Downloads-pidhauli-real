from flask import jsonify, render_template

from app import app, get_demand, get_latest_prices, get_markets, get_weather


@app.route('/healthz')
def health_check():
    return jsonify({'status': 'ok'})


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/crops')
def api_crops():
    return jsonify(get_latest_prices())


@app.route('/api/demand')
def api_demand():
    return jsonify(get_demand())


@app.route('/api/markets')
def api_markets():
    return jsonify(get_markets())


@app.route('/api/weather')
def api_weather():
    try:
        payload = get_weather()
        return jsonify(payload)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
