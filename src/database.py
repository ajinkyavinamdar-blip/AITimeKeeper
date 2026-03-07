import sqlite3
import datetime
import os
import secrets

DB_PATH = os.environ.get('DATABASE_PATH') or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'timesheet.db')

# Ensure the data directory exists (important on Render where data/ is gitignored)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

SEED_ADMIN_EMAIL = 'Ajinkya@CFOLogic.com'
SEED_ADMIN_NAME = 'Ajinkya'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            app_name TEXT,
            window_title TEXT,
            url_or_filename TEXT,
            chrome_profile TEXT,
            client TEXT,
            duration REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT,
            hourly_rate REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'USD',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Attempt to add columns to existing clients table if they don't exist
    try:
        c.execute("ALTER TABLE clients ADD COLUMN hourly_rate REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass # Already exists
    try:
        c.execute("ALTER TABLE clients ADD COLUMN currency TEXT DEFAULT 'USD'")
    except sqlite3.OperationalError:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS client_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            pattern_type TEXT, 
            pattern_value TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_focus BOOLEAN DEFAULT 0,
            is_distraction BOOLEAN DEFAULT 0,
            color TEXT DEFAULT '#808080',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS category_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            pattern_type TEXT, 
            pattern_value TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )
    ''')

    # Update activities to include category_id
    try:
        c.execute("ALTER TABLE activities ADD COLUMN category_id INTEGER REFERENCES categories(id)")
    except sqlite3.OperationalError:
        pass

    # Add is_billable to categories
    try:
        c.execute("ALTER TABLE categories ADD COLUMN is_billable INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Add user_email to activities (multi-user support)
    try:
        c.execute("ALTER TABLE activities ADD COLUMN user_email TEXT")
    except sqlite3.OperationalError:
        pass  # Already exists

    # --- API Tokens Table (for desktop agent authentication) ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_tokens (
            token TEXT PRIMARY KEY,
            user_email TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Users Table ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            manager_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Org Settings Table ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS org_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Seed default org settings
    defaults_settings = [
        ('work_hours_goal', '9'),
        ('default_currency', 'INR'),
        ('fiscal_year_start', '04'),
        ('company_name', 'CFOLogic'),
    ]
    for k, v in defaults_settings:
        c.execute("INSERT OR IGNORE INTO org_settings (key, value) VALUES (?, ?)", (k, v))

    # Seed admin user
    c.execute("INSERT OR IGNORE INTO users (email, name, role) VALUES (?, ?, 'admin')",
              (SEED_ADMIN_EMAIL, SEED_ADMIN_NAME))

    # Seed admin API token if none exists
    c.execute("SELECT COUNT(*) FROM api_tokens WHERE user_email = ? COLLATE NOCASE", (SEED_ADMIN_EMAIL,))
    if c.fetchone()[0] == 0:
        token = secrets.token_hex(32)
        c.execute("INSERT INTO api_tokens (token, user_email) VALUES (?, ?)", (token, SEED_ADMIN_EMAIL))

    # Populate Default Categories if empty
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        defaults = [
            ('Code', 1, 0, '#8B5CF6'),   # Purple
            ('Browsing', 0, 1, '#F59E0B'), # Orange
            ('Design', 1, 0, '#EC4899'), # Pink
            ('Admin', 0, 0, '#9CA3AF'),  # Gray
            ('Operations', 1, 0, '#0D9488'), # Teal
            ('Documents', 1, 0, '#0EA5E9'), # Sky Blue (Excel, Word)
            ('Tech Development', 1, 0, '#4F46E5'), # Indigo/Blue
            ('Collaboration', 0, 0, '#059669'), # Emerald/Green
            ('Social Media', 0, 1, '#D946EF'), # Fuchsia
            ('AI', 1, 0, '#8B5CF6') # Violet
        ]
        c.executemany("INSERT INTO categories (name, is_focus, is_distraction, color) VALUES (?, ?, ?, ?)", defaults)

    # --- Migration Logic ---
    # 1. Create Operations if it doesn't exist (above handles defaults, but for existing DBs:)
    c.execute("INSERT OR IGNORE INTO categories (name, is_focus, is_distraction, color) VALUES ('Operations', 1, 0, '#0D9488')")
    c.execute("SELECT id FROM categories WHERE name = 'Operations'")
    ops_id = c.fetchone()[0]
    
    # 2. Get IDs for old categories
    c.execute("SELECT id FROM categories WHERE name IN ('Finance', 'Finance Operations')")
    old_cat_ids = [row[0] for row in c.fetchall()]
    
    if old_cat_ids:
        # 3. Update activities to new Operations ID
        placeholders = ', '.join('?' for _ in old_cat_ids)
        c.execute(f"UPDATE activities SET category_id = ? WHERE category_id IN ({placeholders})", [ops_id] + old_cat_ids)
        
        # 4. Update category_mappings to new Operations ID
        c.execute(f"UPDATE category_mappings SET category_id = ? WHERE category_id IN ({placeholders})", [ops_id] + old_cat_ids)
        
        # 5. Delete old categories
        c.execute(f"DELETE FROM categories WHERE id IN ({placeholders})", old_cat_ids)

    conn.commit()
    conn.close()

def log_activity(activity_data):
    """
    activity_data: dict with keys 'timestamp', 'app_name', 'window_title', 'url_or_filename',
                   'chrome_profile', 'client', 'duration', 'category_id', 'user_email' (optional)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO activities (timestamp, app_name, window_title, url_or_filename, chrome_profile, client, duration, category_id, user_email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        activity_data.get('timestamp'),
        activity_data.get('app_name'),
        activity_data.get('window_title'),
        activity_data.get('url_or_filename'),
        activity_data.get('chrome_profile'),
        activity_data.get('client', 'Unassigned'),
        activity_data.get('duration', 0),
        activity_data.get('category_id'),  # Can be None
        activity_data.get('user_email')    # None for legacy local rows
    ))

    conn.commit()
    conn.close()


# --- API Token Management ---

def get_api_token(user_email):
    """Returns the API token for a user, or None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token FROM api_tokens WHERE user_email = ? COLLATE NOCASE", (user_email,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def rotate_api_token(user_email):
    """Creates or replaces the API token for a user. Returns the new token."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    token = secrets.token_hex(32)
    c.execute('''
        INSERT INTO api_tokens (token, user_email) VALUES (?, ?)
        ON CONFLICT(token) DO NOTHING
    ''', (token, user_email))
    # Remove any old tokens for this user, keep new one
    c.execute("DELETE FROM api_tokens WHERE user_email = ? COLLATE NOCASE AND token != ?", (user_email, token))
    conn.commit()
    conn.close()
    return token


def get_user_email_by_token(token):
    """Validates a Bearer token and returns the associated user_email, or None."""
    if not token:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_email FROM api_tokens WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_todays_activities(date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    query = "SELECT * FROM activities WHERE timestamp >= ? AND timestamp <= ?"
    params = [start_time, end_time]
    
    if user_email:
        query += " AND (user_email = ? COLLATE NOCASE OR (user_email IS NULL AND ? = ?))"
        params.extend([user_email, user_email, SEED_ADMIN_EMAIL])
    if app_filter:
        query += " AND app_name LIKE ?"
        params.append(f"%{app_filter}%")
    if title_filter:
        query += " AND window_title LIKE ?"
        params.append(f"%{title_filter}%")
    if client_filter:
        query += " AND client = ?"
        params.append(client_filter)
    if category_filter is not None:
        if category_filter == "0" or category_filter == 0:
            query += " AND (category_id IS NULL OR category_id = 0)"
        else:
            query += " AND category_id = ?"
            params.append(category_filter)
        
    query += " ORDER BY timestamp DESC"
    
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()
    return rows

def _user_email_clause(user_email, alias='a'):
    """Returns (extra_where_sql, extra_params) for filtering by user_email.
    Legacy rows (user_email IS NULL) are attributed to the seed admin."""
    if not user_email:
        return '', []
    tbl = f"{alias}." if alias else ''
    sql = f" AND ({tbl}user_email = ? COLLATE NOCASE OR ({tbl}user_email IS NULL AND ? = ?))"
    return sql, [user_email, user_email, SEED_ADMIN_EMAIL]


def get_summary_stats(date_str=None, user_email=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"

    ue_sql, ue_params = _user_email_clause(user_email, alias='')

    # Total Duration
    c.execute(f'SELECT SUM(duration) FROM activities WHERE timestamp >= ? AND timestamp <= ?{ue_sql}',
              [start_time, end_time] + ue_params)
    total_duration = c.fetchone()[0] or 0.0

    # By App
    c.execute(f'''
        SELECT app_name, SUM(duration) as total_time
        FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?{ue_sql}
        GROUP BY app_name
        ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params)
    by_app = [dict(row) for row in c.fetchall()]

    # By Client
    c.execute(f'''
        SELECT client, SUM(duration) as total_time
        FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?{ue_sql}
        GROUP BY client
        ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params)
    by_client = [dict(row) for row in c.fetchall()]

    ue_sql_a, ue_params_a = _user_email_clause(user_email, alias='a')
    # By Category
    c.execute(f'''
        SELECT COALESCE(c.name, 'Uncategorized') as category, SUM(a.duration) as total_time, COALESCE(c.color, '#94a3b8') as color
        FROM activities a
        LEFT JOIN categories c ON a.category_id = c.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?{ue_sql_a}
        GROUP BY COALESCE(c.name, 'Uncategorized')
        ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params_a)
    by_category = [dict(row) for row in c.fetchall()]

    conn.close()
    
    return {
        'total_duration': total_duration,
        'by_app': by_app,
        'by_client': by_client,
        'by_category': by_category
    }

def get_weekly_summary_stats(date_str=None, user_email=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    end_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    start_dt = end_dt - datetime.timedelta(days=6)
    
    start_time = start_dt.strftime('%Y-%m-%d 00:00:00')
    end_time = end_dt.strftime('%Y-%m-%d 23:59:59')

    ue_sql, ue_params = _user_email_clause(user_email, alias='')
    ue_sql_a, ue_params_a = _user_email_clause(user_email, alias='a')

    c.execute(f'SELECT SUM(duration) FROM activities WHERE timestamp >= ? AND timestamp <= ?{ue_sql}',
              [start_time, end_time] + ue_params)
    total_duration = c.fetchone()[0] or 0.0

    c.execute(f'''
        SELECT app_name, SUM(duration) as total_time
        FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?{ue_sql}
        GROUP BY app_name ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params)
    by_app = [dict(row) for row in c.fetchall()]

    c.execute(f'''
        SELECT client, SUM(duration) as total_time
        FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?{ue_sql}
        GROUP BY client ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params)
    by_client = [dict(row) for row in c.fetchall()]

    c.execute(f'''
        SELECT COALESCE(c.name, 'Uncategorized') as category, SUM(a.duration) as total_time, COALESCE(c.color, '#94a3b8') as color
        FROM activities a
        LEFT JOIN categories c ON a.category_id = c.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?{ue_sql_a}
        GROUP BY COALESCE(c.name, 'Uncategorized') ORDER BY total_time DESC
    ''', [start_time, end_time] + ue_params_a)
    by_category = [dict(row) for row in c.fetchall()]

    conn.close()
    return {
        'total_duration': total_duration,
        'by_app': by_app,
        'by_client': by_client,
        'by_category': by_category
    }

def get_application_stats(app_name, date_str=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"

    # Total duration for this app
    c.execute('''
        SELECT SUM(duration) 
        FROM activities 
        WHERE app_name = ? AND timestamp >= ? AND timestamp <= ?
    ''', (app_name, start_time, end_time))
    total_duration = c.fetchone()[0] or 0.0

    # Top usage by Window Title
    c.execute('''
        SELECT window_title, SUM(duration) as total_time
        FROM activities 
        WHERE app_name = ? AND timestamp >= ? AND timestamp <= ?
        GROUP BY window_title
        ORDER BY total_time DESC
        LIMIT 10
    ''', (app_name, start_time, end_time))
    by_window = [dict(row) for row in c.fetchall()]

    # Top Clients for this app
    c.execute('''
        SELECT client, SUM(duration) as total_time
        FROM activities 
        WHERE app_name = ? AND timestamp >= ? AND timestamp <= ?
        GROUP BY client
        ORDER BY total_time DESC
    ''', (app_name, start_time, end_time))
    by_client = [dict(row) for row in c.fetchall()]

    conn.close()

    return {
        'app_name': app_name,
        'total_duration': total_duration,
        'by_window': by_window,
        'by_client': by_client
    }

def get_application_activities(app_name, date_str=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    c.execute('''
        SELECT * FROM activities 
        WHERE app_name = ? AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp DESC
        LIMIT 100
    ''', (app_name, start_time, end_time))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

# --- Client Management Functions ---

def add_client(name, notes=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO clients (name, notes) VALUES (?, ?)", (name, notes))
        conn.commit()
        return True, "Client added successfully"
    except sqlite3.IntegrityError:
        return False, "Client name already exists"
    finally:
        conn.close()

def get_clients():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM clients ORDER BY name ASC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def update_client(client_id, name, notes):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("UPDATE clients SET name = ?, notes = ? WHERE id = ?", (name, notes, client_id))
        conn.commit()
        return True, "Client updated successfully"
    except sqlite3.IntegrityError:
        return False, "Client name already exists"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def add_mapping(client_id, pattern_type, pattern_value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # Check if mapping already exists to avoid duplicates if needed, 
        # but unique key is not strictly enforced on pattern_value alone as multiple clients
        # might theoretically have similar patterns (though unlikely in practice).
        # Implementing basic insert.
        c.execute("INSERT INTO client_mappings (client_id, pattern_type, pattern_value) VALUES (?, ?, ?)", 
                  (client_id, pattern_type, pattern_value))
        
        # Get client name for bulk update
        c.execute("SELECT name FROM clients WHERE id = ?", (client_id,))
        client_name = c.fetchone()[0]
        
        # Apply mapping retroactively
        if pattern_type == 'url':
            c.execute("UPDATE activities SET client = ? WHERE url_or_filename LIKE ? AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
        elif pattern_type == 'title':
            c.execute("UPDATE activities SET client = ? WHERE window_title LIKE ? AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
        elif pattern_type == 'app':
             c.execute("UPDATE activities SET client = ? WHERE app_name LIKE ? AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
             
        conn.commit()
        return True, f"Mapping added and history updated for {c.rowcount} entries."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def get_mappings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT m.id, m.pattern_type, m.pattern_value, c.name as client_name 
        FROM client_mappings m
        JOIN clients c ON m.client_id = c.id
        ORDER BY c.name
    ''')
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_unassigned_summary():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Analyze only last 7 days to keep it relevant
    week_start = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
    
    # Group by URL/Title where client is Unassigned
    # We group by specific combinations of App + Title + URL to be precise
    c.execute('''
        SELECT 
            app_name, 
            window_title, 
            url_or_filename, 
            COUNT(*) as occurrences,
            SUM(duration) as total_duration
        FROM activities 
        WHERE (client IS NULL OR client = '' OR client = 'Unassigned') 
          AND timestamp >= ?
        GROUP BY app_name, window_title, url_or_filename
        ORDER BY total_duration DESC
        LIMIT 100
    ''', (week_start,))
    
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

# --- Category Management Functions ---

def get_categories():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM categories ORDER BY name ASC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_category_mappings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT m.id, m.pattern_type, m.pattern_value, c.name as category_name, c.id as category_id 
        FROM category_mappings m
        JOIN categories c ON m.category_id = c.id
        ORDER BY c.name
    ''')
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def add_category_mapping(category_id, pattern_type, pattern_value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO category_mappings (category_id, pattern_type, pattern_value) VALUES (?, ?, ?)", 
                  (category_id, pattern_type, pattern_value))
        
        # Retroactive Update
        if pattern_type == 'url':
            c.execute("UPDATE activities SET category_id = ? WHERE url_or_filename LIKE ?", (category_id, f'%{pattern_value}%'))
        elif pattern_type == 'title':
            c.execute("UPDATE activities SET category_id = ? WHERE window_title LIKE ?", (category_id, f'%{pattern_value}%'))
        elif pattern_type == 'app':
             c.execute("UPDATE activities SET category_id = ? WHERE app_name LIKE ?", (category_id, f'%{pattern_value}%'))
             
        conn.commit()
        return True, "Category mapping added and history updated."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()
# --- Analysis Functions ---

def get_work_blocks(date_str=None):
    """
    Groups consecutive activities into blocks based on app_name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    c.execute('''
        SELECT * FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
    ''', (start_time, end_time))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    
    if not rows:
        return []
        
    blocks = []
    current_block = None
    
    for row in rows:
        app = row['app_name']
        timestamp = datetime.datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        duration = row['duration']
        client = row['client'] or 'Unassigned'
        cat_id = row['category_id']
        
        if current_block is None:
            current_block = {
                'start_time': timestamp,
                'end_time': timestamp + datetime.timedelta(seconds=duration),
                'app_name': app,
                'client': client,
                'category_id': cat_id,
                'duration': duration,
                'items': 1
            }
        else:
            # Check if same app and within reasonable time gap (e.g. 5 mins)
            time_gap = (timestamp - current_block['end_time']).total_seconds()
            
            if app == current_block['app_name'] and time_gap < 300:
                # Extend block
                current_block['end_time'] = timestamp + datetime.timedelta(seconds=duration)
                current_block['duration'] += duration
                current_block['items'] += 1
            else:
                # Close block and start new
                blocks.append(current_block)
                current_block = {
                    'start_time': timestamp,
                    'end_time': timestamp + datetime.timedelta(seconds=duration),
                    'app_name': app,
                    'client': client,
                    'category_id': cat_id,
                    'duration': duration,
                    'items': 1
                }
    
    if current_block:
        blocks.append(current_block)
        
    # Format for JSON
    result = []
    for b in blocks:
        # Filter very short blocks (e.g. < 1 min) unless solitary? 
        # For now keep all to be accurate, maybe filter in UI.
        result.append({
            'start_time': b['start_time'].strftime('%H:%M'),
            'end_time': b['end_time'].strftime('%H:%M'),
            'app_name': b['app_name'],
            'client': b['client'],
            'category_id': b['category_id'],
            'duration_minutes': round(b['duration'] / 60),
            'efficiency': 100 # Placeholder
        })
        
    # Return reverse chronological
    return result[::-1]

def get_overtime_stats(date_str=None, user_email=None):
    """
    Calculates time worked after 18:30 (6:30 PM).
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"

    ue_sql, ue_params = _user_email_clause(user_email, alias='')
    c.execute(f'SELECT SUM(duration) FROM activities WHERE timestamp >= ? AND timestamp <= ?{ue_sql}',
              [start_time, end_time] + ue_params)
    total_duration = c.fetchone()[0] or 0.0
    
    overtime_duration = max(0, total_duration - 32400)
    conn.close()
    
    return {
        'total_duration': total_duration,
        'overtime_duration': overtime_duration,
        'is_overtime': total_duration > 32400
    }


# --- User Management Functions ---

def get_user_by_email(email):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT u.*, m.name as manager_name, m.email as manager_email
        FROM users u
        LEFT JOIN users m ON u.manager_id = m.id
        ORDER BY u.name ASC
    ''')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def upsert_user(email, name, role='member', manager_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO users (email, name, role, manager_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                name = excluded.name,
                role = excluded.role,
                manager_id = excluded.manager_id
        ''', (email, name, role, manager_id))
        conn.commit()
        return True, "User saved successfully"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # Don't allow deleting the seed admin
        c.execute("SELECT email FROM users WHERE id = ?", (user_id,))
        row = c.fetchone()
        if row and row[0].lower() == SEED_ADMIN_EMAIL.lower():
            return False, "Cannot delete the system admin"
        c.execute("UPDATE users SET manager_id = NULL WHERE manager_id = ?", (user_id,))
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True, "User deleted"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def get_direct_reports(manager_email):
    """Returns list of user dicts who directly report to manager_email."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (manager_email,))
    row = c.fetchone()
    if not row:
        conn.close()
        return []
    manager_id = row['id']
    c.execute("SELECT * FROM users WHERE manager_id = ? ORDER BY name ASC", (manager_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_all_reports(manager_email):
    """Returns all users (direct + indirect) who report up to manager_email."""
    all_reports = []
    queue = get_direct_reports(manager_email)
    visited_emails = set()
    while queue:
        user = queue.pop(0)
        if user['email'] in visited_emails:
            continue
        visited_emails.add(user['email'])
        all_reports.append(user)
        queue.extend(get_direct_reports(user['email']))
    return all_reports

def has_reports(email):
    """Returns True if user has at least one direct report."""
    return len(get_direct_reports(email)) > 0


# --- Org Settings Functions ---

def get_org_settings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT key, value FROM org_settings")
    result = {r['key']: r['value'] for r in c.fetchall()}
    conn.close()
    return result

def update_org_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT OR REPLACE INTO org_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


# --- Category Billable Toggle ---

def update_category_billable(category_id, is_billable):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("UPDATE categories SET is_billable = ? WHERE id = ?", (1 if is_billable else 0, category_id))
        conn.commit()
        return True, "Updated"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def update_category_full(category_id, name=None, is_focus=None, is_distraction=None, color=None, is_billable=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        updates, params = [], []
        if name is not None: updates.append("name = ?"); params.append(name)
        if is_focus is not None: updates.append("is_focus = ?"); params.append(int(is_focus))
        if is_distraction is not None: updates.append("is_distraction = ?"); params.append(int(is_distraction))
        if color is not None: updates.append("color = ?"); params.append(color)
        if is_billable is not None: updates.append("is_billable = ?"); params.append(int(is_billable))
        if not updates:
            return True, "No changes"
        params.append(category_id)
        c.execute(f"UPDATE categories SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return True, "Category updated"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def add_category(name, is_focus=False, is_distraction=False, color='#808080', is_billable=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO categories (name, is_focus, is_distraction, color, is_billable) VALUES (?, ?, ?, ?, ?)",
                  (name, int(is_focus), int(is_distraction), color, int(is_billable)))
        conn.commit()
        return True, "Category added"
    except sqlite3.IntegrityError:
        return False, "Category already exists"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()
