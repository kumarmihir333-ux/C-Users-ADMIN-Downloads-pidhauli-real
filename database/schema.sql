PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    state TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    market_type TEXT NOT NULL DEFAULT 'APMC'
);

CREATE TABLE IF NOT EXISTS crops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    local_name TEXT,
    category TEXT NOT NULL,
    icon TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS crop_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_id INTEGER NOT NULL,
    market_id INTEGER NOT NULL,
    price_per_qtl INTEGER NOT NULL,
    change_pct REAL NOT NULL,
    trend_data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (crop_id) REFERENCES crops(id),
    FOREIGN KEY (market_id) REFERENCES markets(id)
);

CREATE TABLE IF NOT EXISTS demand_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name TEXT NOT NULL,
    detail TEXT NOT NULL,
    quantity TEXT NOT NULL,
    place TEXT NOT NULL,
    delivery TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    crop_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_email, crop_id),
    FOREIGN KEY (crop_id) REFERENCES crops(id)
);

CREATE TABLE IF NOT EXISTS farm_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    name TEXT NOT NULL,
    boundary_json TEXT NOT NULL,
    area_sqm REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_email, name),
    FOREIGN KEY (user_email) REFERENCES users(email) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS satellite_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (field_id) REFERENCES farm_fields(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT,
    crop_name TEXT NOT NULL,
    buyer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    quantity TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'closed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_import_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    imported_rows INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO markets (id, name, location, state, latitude, longitude, market_type) VALUES
    (1, 'Begusarai APMC', 'Teghra', 'Bihar', 25.5253, 85.9081, 'APMC'),
    (2, 'Barauni Market', 'Barauni', 'Bihar', 25.4636, 85.9963, 'Market Yard'),
    (3, 'Samastipur APMC', 'Samastipur', 'Bihar', 25.8575, 85.7783, 'APMC');

INSERT OR IGNORE INTO crops (id, name, local_name, category, icon, description) VALUES
    (1, 'Wheat', 'गेहूँ', 'Grain', '✳', 'Milling wheat from Bihar grain markets'),
    (2, 'Maize', 'मक्का', 'Grain', '✺', 'Feed-grade maize for poultry and feed mills'),
    (3, 'Potato', 'आलू', 'Vegetable', '◉', 'Fresh potato lots traded through local mandis'),
    (4, 'Mustard', 'सरसों', 'Grain', '✣', 'Mustard seed and oilseed movement'),
    (5, 'Lentil', 'मसूर', 'Pulse', '❋', 'Bulk pulse supply for wholesale trade');

INSERT OR IGNORE INTO crop_prices (id, crop_id, market_id, price_per_qtl, change_pct, trend_data, created_at) VALUES
    (1, 1, 1, 2425, 1.2, '10,15,12,23,20,28,33', '2026-11-11 01:00:00'),
    (2, 2, 2, 2180, 0.7, '13,12,18,17,22,20,29', '2026-11-11 01:00:00'),
    (3, 3, 1, 1450, -0.4, '28,27,21,24,16,19,17', '2026-11-11 01:00:00'),
    (4, 4, 2, 5675, 1.8, '11,12,14,20,19,25,32', '2026-11-11 01:00:00'),
    (5, 5, 3, 6480, 0.3, '17,16,18,19,18,22,24', '2026-11-11 01:00:00');

INSERT OR IGNORE INTO demand_requests (id, crop_name, detail, quantity, place, delivery, quality) VALUES
    (1, 'Maize · Feed grade', 'Moisture below 14% · Cleaned', '100 MT', 'Bihar', 'Within 30 days', 'Feed grade'),
    (2, 'Turmeric · High curcumin', 'Finger turmeric · Lab report requested', '25 MT', 'India', 'As agreed', 'High curcumin'),
    (3, 'Wheat · Milling', 'FAQ quality · Bulk supply', '50 MT', 'Eastern India', 'Next harvest', 'Milling grade');
