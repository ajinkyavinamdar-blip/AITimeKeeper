import urllib.parse
import os
import secrets
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as _pg_pool
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Using DATABASE_URL
DB_URL = os.environ.get('DATABASE_URL')

SEED_ADMIN_EMAIL = 'Ajinkya@CFOLogic.com'
SEED_ADMIN_NAME = 'Ajinkya'

# ── Connection Pool ──────────────────────────────────────────────────────────
# Keeps 2-8 persistent connections open so each request doesn't pay the
# ~100 ms TCP+SSL handshake to Supabase.
_pool = None

def _get_pool():
    global _pool
    if _pool is None and DB_URL:
        url = DB_URL.strip().strip('"').strip("'")
        _pool = _pg_pool.ThreadedConnectionPool(2, 8, url)
    return _pool

def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is not set")
    p = _get_pool()
    if p:
        conn = p.getconn()
        conn.autocommit = False
        return conn
    # Fallback: direct connection
    url = DB_URL.strip().strip('"').strip("'")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn

def release_db_connection(conn):
    """Return a connection to the pool (call instead of conn.close())."""
    p = _get_pool()
    if p and conn:
        try:
            conn.rollback()  # ensure clean state
        except Exception:
            pass
        p.putconn(conn)
    elif conn:
        conn.close()

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id BIGSERIAL PRIMARY KEY,
                timestamp TEXT NOT NULL,
                app_name TEXT,
                window_title TEXT,
                url_or_filename TEXT,
                chrome_profile TEXT,
                client TEXT,
                duration REAL,
                category_id INTEGER,
                user_email TEXT,
                server_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                notes TEXT,
                hourly_rate REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'USD',
                zoho_org_id TEXT DEFAULT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS client_mappings (
                id BIGSERIAL PRIMARY KEY,
                client_id INTEGER REFERENCES clients(id),
                pattern_type TEXT, 
                pattern_value TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                is_focus BOOLEAN DEFAULT FALSE,
                is_distraction BOOLEAN DEFAULT FALSE,
                color TEXT DEFAULT '#808080',
                is_billable BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS category_mappings (
                id BIGSERIAL PRIMARY KEY,
                category_id INTEGER REFERENCES categories(id),
                pattern_type TEXT, 
                pattern_value TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Foreign Key constraint on activities.category_id added separately if needed, 
        # but for simplicity, we keep it as INTEGER in Postgres
        # (It was added as alter table before). Let's formally add it if we can.
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_tokens (
                token TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                manager_id INTEGER REFERENCES users(id),
                is_paused BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Add is_paused column if upgrading from an older schema
        c.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_paused BOOLEAN DEFAULT FALSE
        """)

        # ── Performance indexes ──────────────────────────────────────────────
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_timestamp ON activities(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_user_email ON activities(LOWER(user_email))")
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_server_ts ON activities(server_timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_category ON activities(category_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_activities_ts_user ON activities(timestamp, user_email)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_category_mappings_cat ON category_mappings(category_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_email ON api_tokens(LOWER(user_email))")
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS org_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Insert defaults
        c.execute("INSERT INTO org_settings (key, value) VALUES ('work_hours_goal', '9') ON CONFLICT (key) DO NOTHING")
        c.execute("INSERT INTO org_settings (key, value) VALUES ('default_currency', 'INR') ON CONFLICT (key) DO NOTHING")
        c.execute("INSERT INTO org_settings (key, value) VALUES ('fiscal_year_start', '04') ON CONFLICT (key) DO NOTHING")
        c.execute("INSERT INTO org_settings (key, value) VALUES ('company_name', 'CFOLogic') ON CONFLICT (key) DO NOTHING")

        # Seed admin user
        c.execute("INSERT INTO users (email, name, role) VALUES (%s, %s, 'admin') ON CONFLICT (email) DO NOTHING",
                  (SEED_ADMIN_EMAIL, SEED_ADMIN_NAME))
                  
        # Seed API token
        c.execute("SELECT COUNT(*) FROM api_tokens WHERE LOWER(user_email) = LOWER(%s)", (SEED_ADMIN_EMAIL,))
        if c.fetchone()[0] == 0:
            token = secrets.token_hex(32)
            c.execute("INSERT INTO api_tokens (token, user_email) VALUES (%s, %s)", (token, SEED_ADMIN_EMAIL))

        # ── Category migrations (schema evolution) ──────────────────────────
        import psycopg2.extras

        # Rename Documents → Documentation
        c.execute("UPDATE categories SET name='Documentation' WHERE name='Documents'")

        # Remove Code (reassign activities → Tech Development) and Design (→ null)
        c.execute("""
            UPDATE activities SET category_id=(SELECT id FROM categories WHERE name='Tech Development' LIMIT 1)
            WHERE category_id=(SELECT id FROM categories WHERE name='Code' LIMIT 1)
        """)
        c.execute("DELETE FROM category_mappings WHERE category_id=(SELECT id FROM categories WHERE name='Code' LIMIT 1)")
        c.execute("DELETE FROM categories WHERE name='Code'")

        c.execute("UPDATE activities SET category_id=NULL WHERE category_id=(SELECT id FROM categories WHERE name='Design' LIMIT 1)")
        c.execute("DELETE FROM category_mappings WHERE category_id=(SELECT id FROM categories WHERE name='Design' LIMIT 1)")
        c.execute("DELETE FROM categories WHERE name='Design'")

        # Merge Communication → Collaboration (reassign activities + mappings, then drop)
        c.execute("""
            UPDATE activities SET category_id=(SELECT id FROM categories WHERE name='Collaboration' LIMIT 1)
            WHERE category_id=(SELECT id FROM categories WHERE name='Communication' LIMIT 1)
        """)
        c.execute("""
            UPDATE category_mappings SET category_id=(SELECT id FROM categories WHERE name='Collaboration' LIMIT 1)
            WHERE category_id=(SELECT id FROM categories WHERE name='Communication' LIMIT 1)
        """)
        c.execute("DELETE FROM categories WHERE name='Communication'")

        # ── Seed / refresh categories ─────────────────────────────────────────
        defaults = [
            ('Browsing',         False, True,  '#F59E0B'),  # Distraction — generic web
            ('Admin',            False, False, '#9CA3AF'),  # Neutral — Calendar, Settings
            ('Operations',       True,  False, '#0D9488'),  # Focus — Zoho, Excel, Finance
            ('Documentation',    True,  False, '#0EA5E9'),  # Focus — Word, PDFs, Notes
            ('Tech Development', True,  False, '#4F46E5'),  # Focus — IDE, Terminal, GitHub
            ('Collaboration',    False, False, '#059669'),  # Meetings — Outlook, Teams, Zoom
            ('Social Media',     False, True,  '#D946EF'),  # Distraction — Facebook, Twitter
            ('AI',               True,  False, '#8B5CF6'),  # Focus — Claude, ChatGPT
            ('Research',         True,  False, '#0891B2'),  # Focus — Scholar, Wikipedia, news
            ('Self Improvement', True,  False, '#F97316'),  # Focus — Coursera, Udemy, books
        ]
        psycopg2.extras.execute_batch(
            c,
            "INSERT INTO categories (name, is_focus, is_distraction, color) VALUES (%s, %s, %s, %s) ON CONFLICT (name) DO NOTHING",
            defaults
        )

        # ── Seed default category mappings (URL / app / title patterns) ───────
        c.execute("SELECT COUNT(*) FROM category_mappings")
        if c.fetchone()[0] == 0:
            c.execute("SELECT id, name FROM categories")
            cat_id = {row['name']: row['id'] for row in c.fetchall()}

            url_mappings = [
                # Social Media
                ('Social Media', 'url', 'facebook.com'),
                ('Social Media', 'url', 'instagram.com'),
                ('Social Media', 'url', 'twitter.com'),
                ('Social Media', 'url', 'x.com'),
                ('Social Media', 'url', 'linkedin.com'),
                ('Social Media', 'url', 'youtube.com'),
                ('Social Media', 'url', 'reddit.com'),
                ('Social Media', 'url', 'tiktok.com'),
                ('Social Media', 'url', 'netflix.com'),
                ('Social Media', 'url', 'primevideo.com'),
                # Collaboration / Meetings
                ('Collaboration', 'url', 'teams.microsoft.com'),
                ('Collaboration', 'url', 'zoom.us'),
                ('Collaboration', 'url', 'meet.google.com'),
                ('Collaboration', 'url', 'mail.google.com'),
                ('Collaboration', 'url', 'outlook.live.com'),
                ('Collaboration', 'url', 'outlook.office.com'),
                ('Collaboration', 'app', 'Microsoft Teams'),
                ('Collaboration', 'app', 'Zoom'),
                ('Collaboration', 'app', 'Microsoft Outlook'),
                ('Collaboration', 'app', 'Slack'),
                # Operations / Finance
                ('Operations', 'url', 'zoho.com'),
                ('Operations', 'url', 'books.zoho.com'),
                ('Operations', 'url', 'crm.zoho.com'),
                ('Operations', 'url', 'quickbooks.intuit.com'),
                ('Operations', 'url', 'tallysolutions.com'),
                ('Operations', 'url', 'xero.com'),
                ('Operations', 'app', 'Microsoft Excel'),
                ('Operations', 'app', 'Numbers'),
                # AI Tools
                ('AI', 'url', 'claude.ai'),
                ('AI', 'url', 'chat.openai.com'),
                ('AI', 'url', 'gemini.google.com'),
                ('AI', 'url', 'perplexity.ai'),
                ('AI', 'url', 'notebooklm.google.com'),
                # Tech Development
                ('Tech Development', 'url', 'github.com'),
                ('Tech Development', 'url', 'stackoverflow.com'),
                ('Tech Development', 'url', 'localhost'),
                ('Tech Development', 'url', '127.0.0.1'),
                ('Tech Development', 'app', 'Visual Studio Code'),
                ('Tech Development', 'app', 'Code'),
                ('Tech Development', 'app', 'Terminal'),
                ('Tech Development', 'app', 'iTerm2'),
                ('Tech Development', 'app', 'Xcode'),
                # Research
                ('Research', 'url', 'scholar.google.com'),
                ('Research', 'url', 'wikipedia.org'),
                ('Research', 'url', 'news.google.com'),
                ('Research', 'url', 'medium.com'),
                ('Research', 'url', 'substack.com'),
                # Self Improvement
                ('Self Improvement', 'url', 'coursera.org'),
                ('Self Improvement', 'url', 'udemy.com'),
                ('Self Improvement', 'url', 'linkedin.com/learning'),
                ('Self Improvement', 'url', 'skillshare.com'),
                ('Self Improvement', 'url', 'khanacademy.org'),
                ('Self Improvement', 'url', 'audible.com'),
                # Documentation
                ('Documentation', 'app', 'Microsoft Word'),
                ('Documentation', 'app', 'Pages'),
                ('Documentation', 'app', 'Notion'),
                ('Documentation', 'url', 'notion.so'),
                ('Documentation', 'url', 'docs.google.com'),
                ('Documentation', 'url', 'confluence'),
            ]

            rows = [(cat_id[cn], pt, pv) for cn, pt, pv in url_mappings if cn in cat_id]
            psycopg2.extras.execute_batch(
                c,
                "INSERT INTO category_mappings (category_id, pattern_type, pattern_value) VALUES (%s, %s, %s)",
                rows
            )

        conn.commit()
    except Exception as e:
        print(f"init_db error: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise e
    finally:
        if 'conn' in locals():
            release_db_connection(conn)


def log_activity(activity_data):
    # This remains similar but parameterized using %s
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO activities (timestamp, app_name, window_title, url_or_filename, chrome_profile, client, duration, category_id, user_email)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            activity_data.get('timestamp'),
            activity_data.get('app_name'),
            activity_data.get('window_title'),
            activity_data.get('url_or_filename'),
            activity_data.get('chrome_profile'),
            activity_data.get('client', 'Unassigned'),
            activity_data.get('duration', 0),
            activity_data.get('category_id'),
            activity_data.get('user_email')
        ))
        conn.commit()
    finally:
        release_db_connection(conn)


def get_api_token(user_email):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT token FROM api_tokens WHERE LOWER(user_email) = LOWER(%s)", (user_email,))
        row = c.fetchone()
        return row[0] if row else None
    finally:
        release_db_connection(conn)

def rotate_api_token(user_email):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        token = secrets.token_hex(32)
        c.execute('''
            INSERT INTO api_tokens (token, user_email) VALUES (%s, %s)
            ON CONFLICT(token) DO NOTHING
        ''', (token, user_email))
        c.execute("DELETE FROM api_tokens WHERE LOWER(user_email) = LOWER(%s) AND token != %s", (user_email, token))
        conn.commit()
        return token
    finally:
        release_db_connection(conn)

def get_user_email_by_token(token):
    if not token:
        return None
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_email FROM api_tokens WHERE token = %s", (token,))
        row = c.fetchone()
        return row[0] if row else None
    finally:
        release_db_connection(conn)

def get_todays_activities(date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        query = "SELECT id, timestamp, app_name, window_title, url_or_filename, chrome_profile, client, duration, category_id FROM activities WHERE timestamp >= %s AND timestamp <= %s"
        params = [start_time, end_time]
        
        if user_email:
            query += " AND (LOWER(user_email) = LOWER(%s) OR (user_email IS NULL AND %s = %s))"
            params.extend([user_email, user_email, SEED_ADMIN_EMAIL])
        if app_filter:
            query += " AND app_name ILIKE %s"
            params.append(f"%{app_filter}%")
        if title_filter:
            query += " AND window_title ILIKE %s"
            params.append(f"%{title_filter}%")
        if client_filter:
            query += " AND client = %s"
            params.append(client_filter)
        if category_filter is not None:
            if category_filter == "0" or category_filter == 0:
                query += " AND (category_id IS NULL OR category_id = 0)"
            else:
                query += " AND category_id = %s"
                params.append(category_filter)
            
        query += " ORDER BY timestamp DESC"
        
        c.execute(query, tuple(params))
        rows = c.fetchall()
        return rows
    finally:
        release_db_connection(conn)

def _user_email_clause(user_email, alias='a'):
    if not user_email:
        return '', []
    tbl = f"{alias}." if alias else ''
    sql = f" AND (LOWER({tbl}user_email) = LOWER(%s) OR ({tbl}user_email IS NULL AND %s = %s))"
    return sql, [user_email, user_email, SEED_ADMIN_EMAIL]

def get_summary_stats(date_str=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        ue_sql, ue_params = _user_email_clause(user_email, alias='')

        # Total Duration
        c.execute(f'SELECT COALESCE(SUM(duration), 0) FROM activities WHERE timestamp >= %s AND timestamp <= %s{ue_sql}',
                  [start_time, end_time] + ue_params)
        total_duration = c.fetchone()['coalesce']

        # By App (exclude null/empty app names)
        c.execute(f'''
            SELECT app_name, SUM(duration) as total_time
            FROM activities
            WHERE timestamp >= %s AND timestamp <= %s{ue_sql}
              AND app_name IS NOT NULL AND app_name != ''
            GROUP BY app_name
            ORDER BY total_time DESC
        ''', [start_time, end_time] + ue_params)
        by_app = [dict(row) for row in c.fetchall()]

        # By Client
        c.execute(f'''
            SELECT client, SUM(duration) as total_time
            FROM activities 
            WHERE timestamp >= %s AND timestamp <= %s{ue_sql}
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
            WHERE a.timestamp >= %s AND a.timestamp <= %s{ue_sql_a}
            GROUP BY COALESCE(c.name, 'Uncategorized'), color
            ORDER BY total_time DESC
        ''', [start_time, end_time] + ue_params_a)
        by_category = [dict(row) for row in c.fetchall()]

        return {
            'total_duration': total_duration,
            'by_app': by_app,
            'by_client': by_client,
            'by_category': by_category
        }
    finally:
        release_db_connection(conn)

def get_weekly_summary_stats(date_str=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        
        end_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        start_dt = end_dt - datetime.timedelta(days=6)
        
        start_time = start_dt.strftime('%Y-%m-%d 00:00:00')
        end_time = end_dt.strftime('%Y-%m-%d 23:59:59')

        ue_sql, ue_params = _user_email_clause(user_email, alias='')
        ue_sql_a, ue_params_a = _user_email_clause(user_email, alias='a')

        c.execute(f'SELECT COALESCE(SUM(duration),0) FROM activities WHERE timestamp >= %s AND timestamp <= %s{ue_sql}',
                  [start_time, end_time] + ue_params)
        total_duration = c.fetchone()['coalesce']

        c.execute(f'''
            SELECT app_name, SUM(duration) as total_time
            FROM activities
            WHERE timestamp >= %s AND timestamp <= %s{ue_sql}
              AND app_name IS NOT NULL AND app_name != ''
            GROUP BY app_name ORDER BY total_time DESC
        ''', [start_time, end_time] + ue_params)
        by_app = [dict(row) for row in c.fetchall()]

        c.execute(f'''
            SELECT client, SUM(duration) as total_time
            FROM activities 
            WHERE timestamp >= %s AND timestamp <= %s{ue_sql}
            GROUP BY client ORDER BY total_time DESC
        ''', [start_time, end_time] + ue_params)
        by_client = [dict(row) for row in c.fetchall()]

        c.execute(f'''
            SELECT COALESCE(c.name, 'Uncategorized') as category, SUM(a.duration) as total_time, COALESCE(c.color, '#94a3b8') as color
            FROM activities a
            LEFT JOIN categories c ON a.category_id = c.id
            WHERE a.timestamp >= %s AND a.timestamp <= %s{ue_sql_a}
            GROUP BY COALESCE(c.name, 'Uncategorized'), color ORDER BY total_time DESC
        ''', [start_time, end_time] + ue_params_a)
        by_category = [dict(row) for row in c.fetchall()]

        return {
            'total_duration': total_duration,
            'by_app': by_app,
            'by_client': by_client,
            'by_category': by_category
        }
    finally:
        release_db_connection(conn)

def get_application_stats(app_name, date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        c.execute('''
            SELECT COALESCE(SUM(duration), 0)
            FROM activities 
            WHERE app_name = %s AND timestamp >= %s AND timestamp <= %s
        ''', (app_name, start_time, end_time))
        total_duration = c.fetchone()['coalesce']

        c.execute('''
            SELECT window_title, SUM(duration) as total_time
            FROM activities 
            WHERE app_name = %s AND timestamp >= %s AND timestamp <= %s
            GROUP BY window_title
            ORDER BY total_time DESC
            LIMIT 10
        ''', (app_name, start_time, end_time))
        by_window = [dict(row) for row in c.fetchall()]

        c.execute('''
            SELECT client, SUM(duration) as total_time
            FROM activities 
            WHERE app_name = %s AND timestamp >= %s AND timestamp <= %s
            GROUP BY client
            ORDER BY total_time DESC
        ''', (app_name, start_time, end_time))
        by_client = [dict(row) for row in c.fetchall()]

        return {
            'app_name': app_name,
            'total_duration': total_duration,
            'by_window': by_window,
            'by_client': by_client
        }
    finally:
        release_db_connection(conn)

def get_application_activities(app_name, date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        c.execute('''
            SELECT * FROM activities 
            WHERE app_name = %s AND timestamp >= %s AND timestamp <= %s
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (app_name, start_time, end_time))
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

# --- Client ---
def add_client(name, notes="", zoho_org_id=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO clients (name, notes, zoho_org_id) VALUES (%s, %s, %s)", (name, notes, zoho_org_id or None))
        conn.commit()
        return True, "Client added successfully"
    except psycopg2.IntegrityError:
        conn.rollback()
        return False, "Client name already exists"
    finally:
        release_db_connection(conn)

def get_clients():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT * FROM clients ORDER BY name ASC")
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

def update_client(client_id, name, notes, zoho_org_id=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE clients SET name = %s, notes = %s, zoho_org_id = %s WHERE id = %s",
                  (name, notes, zoho_org_id or None, client_id))
        conn.commit()
        return True, "Client updated successfully"
    except psycopg2.IntegrityError:
        conn.rollback()
        return False, "Client name already exists"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

def get_client_by_zoho_org_id(org_id: str):
    if not org_id:
        return None
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT name FROM clients WHERE zoho_org_id = %s", (str(org_id).strip(),))
        row = c.fetchone()
        return row['name'] if row else None
    finally:
        release_db_connection(conn)

def add_mapping(client_id, pattern_type, pattern_value):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO client_mappings (client_id, pattern_type, pattern_value) VALUES (%s, %s, %s)", 
                  (client_id, pattern_type, pattern_value))
        
        c.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
        client_name = c.fetchone()[0]
        
        if pattern_type == 'url':
            c.execute("UPDATE activities SET client = %s WHERE url_or_filename ILIKE %s AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
        elif pattern_type == 'title':
            c.execute("UPDATE activities SET client = %s WHERE window_title ILIKE %s AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
        elif pattern_type == 'app':
             c.execute("UPDATE activities SET client = %s WHERE app_name ILIKE %s AND (client IS NULL OR client = '' OR client = 'Unassigned')", (client_name, f'%{pattern_value}%'))
             
        conn.commit()
        return True, f"Mapping added and history updated."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

def get_mappings():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT m.id, m.pattern_type, m.pattern_value, c.name as client_name 
            FROM client_mappings m
            JOIN clients c ON m.client_id = c.id
            ORDER BY c.name
        ''')
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

def get_unassigned_summary():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        week_start = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
        c.execute('''
            SELECT 
                app_name, 
                window_title, 
                url_or_filename, 
                COUNT(*) as occurrences,
                SUM(duration) as total_duration
            FROM activities 
            WHERE (client IS NULL OR client = '' OR client = 'Unassigned') 
              AND timestamp >= %s
            GROUP BY app_name, window_title, url_or_filename
            ORDER BY total_duration DESC
            LIMIT 100
        ''', (week_start,))
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

# --- Categories ---
def get_categories():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT * FROM categories ORDER BY name ASC")
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

def get_category_mappings():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT m.id, m.pattern_type, m.pattern_value, c.name as category_name, c.id as category_id 
            FROM category_mappings m
            JOIN categories c ON m.category_id = c.id
            ORDER BY c.name
        ''')
        rows = [dict(row) for row in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

def add_category_mapping(category_id, pattern_type, pattern_value):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO category_mappings (category_id, pattern_type, pattern_value) VALUES (%s, %s, %s)", 
                  (category_id, pattern_type, pattern_value))
        
        if pattern_type == 'url':
            c.execute("UPDATE activities SET category_id = %s WHERE url_or_filename ILIKE %s", (category_id, f'%{pattern_value}%'))
        elif pattern_type == 'title':
            c.execute("UPDATE activities SET category_id = %s WHERE window_title ILIKE %s", (category_id, f'%{pattern_value}%'))
        elif pattern_type == 'app':
             c.execute("UPDATE activities SET category_id = %s WHERE app_name ILIKE %s", (category_id, f'%{pattern_value}%'))
             
        conn.commit()
        return True, "Category mapping added and history updated."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

# --- Analysis ---
def get_work_blocks(date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        c.execute('''
            SELECT * FROM activities 
            WHERE timestamp >= %s AND timestamp <= %s
            ORDER BY timestamp ASC
        ''', (start_time, end_time))
        rows = [dict(row) for row in c.fetchall()]
        
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
                time_gap = (timestamp - current_block['end_time']).total_seconds()
                
                if app == current_block['app_name'] and time_gap < 300:
                    current_block['end_time'] = timestamp + datetime.timedelta(seconds=duration)
                    current_block['duration'] += duration
                    current_block['items'] += 1
                else:
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
            
        result = []
        for b in blocks:
            result.append({
                'start_time': b['start_time'].strftime('%H:%M'),
                'end_time': b['end_time'].strftime('%H:%M'),
                'app_name': b['app_name'],
                'client': b['client'],
                'category_id': b['category_id'],
                'duration_minutes': round(b['duration'] / 60),
                'efficiency': 100 
            })
            
        return result[::-1]
    finally:
        release_db_connection(conn)

def get_overtime_stats(date_str=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        ue_sql, ue_params = _user_email_clause(user_email, alias='')
        c.execute(f'SELECT COALESCE(SUM(duration), 0) FROM activities WHERE timestamp >= %s AND timestamp <= %s{ue_sql}',
                  [start_time, end_time] + ue_params)
        total_duration = c.fetchone()[0]
        
        overtime_duration = max(0, total_duration - 32400)
        
        return {
            'total_duration': total_duration,
            'overtime_duration': overtime_duration,
            'is_overtime': total_duration > 32400
        }
    finally:
        release_db_connection(conn)

def get_user_by_email(email):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        release_db_connection(conn)

def set_user_paused(email: str, paused: bool):
    """Set tracking paused state for a user (used by web UI pause/resume)."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET is_paused = %s WHERE LOWER(email) = LOWER(%s)", (paused, email))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"[set_user_paused] error: {e}")
        return False
    finally:
        release_db_connection(conn)

def get_user_paused(email: str) -> bool:
    """Returns True if the user has paused tracking."""
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT is_paused FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        row = c.fetchone()
        return bool(row['is_paused']) if row else False
    finally:
        release_db_connection(conn)

def get_all_users():
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT u.*, m.name as manager_name, m.email as manager_email
            FROM users u
            LEFT JOIN users m ON u.manager_id = m.id
            ORDER BY u.name ASC
        ''')
        rows = [dict(r) for r in c.fetchall()]
        return rows
    finally:
        release_db_connection(conn)

def upsert_user(email, name, role='member', manager_id=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (email, name, role, manager_id) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(email) DO UPDATE SET 
                name = EXCLUDED.name, 
                role = EXCLUDED.role, 
                manager_id = EXCLUDED.manager_id
        ''', (email, name, role, manager_id))
        conn.commit()
        return True, "User saved successfully"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

def delete_user(user_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM api_tokens WHERE user_email = (SELECT email FROM users WHERE id = %s)", (user_id,))
        c.execute("UPDATE users SET manager_id = NULL WHERE manager_id = %s", (user_id,))
        c.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return True, "User deleted successfully"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

def get_org_settings():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT key, value FROM org_settings")
        d = {row[0]: row[1] for row in c.fetchall()}
        return d
    finally:
        release_db_connection(conn)

def update_org_setting(key, value):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO org_settings (key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value", (key, value))
        conn.commit()
    finally:
        release_db_connection(conn)

# Org reporting helpers
def get_all_reports(manager_email):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(%s)", (manager_email,))
        row = c.fetchone()
        if not row:
            return []
            
        manager_id = row['id']
        reports = []
        
        c.execute('''
            WITH RECURSIVE subordinates AS (
                SELECT id, email, name, manager_id FROM users WHERE manager_id = %s
                UNION
                SELECT u.id, u.email, u.name, u.manager_id 
                FROM users u
                INNER JOIN subordinates s ON s.id = u.manager_id
            )
            SELECT email, name FROM subordinates
        ''', (manager_id,))
        
        for r in c.fetchall():
            reports.append({'email': r['email'], 'name': r['name']})
            
        return reports
    finally:
        release_db_connection(conn)

def has_reports(manager_email):
    return len(get_all_reports(manager_email)) > 0


def update_category_full(cat_id, name=None, is_focus=None, is_distraction=None, color=None, is_billable=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        fields = []
        vars_list = []
        if name is not None:
            fields.append("name = %s")
            vars_list.append(name)
        if is_focus is not None:
            fields.append("is_focus = %s")
            vars_list.append(is_focus)
        if is_distraction is not None:
            fields.append("is_distraction = %s")
            vars_list.append(is_distraction)
        if color is not None:
            fields.append("color = %s")
            vars_list.append(color)
        if is_billable is not None:
            fields.append("is_billable = %s")
            vars_list.append(is_billable)
            
        if fields:
            vars_list.append(cat_id)
            query = f"UPDATE categories SET {', '.join(fields)} WHERE id = %s"
            c.execute(query, tuple(vars_list))
            conn.commit()
            return True, "Category updated successfully"
        return False, "No fields to update"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)

def add_category(name, is_focus=False, is_distraction=False, color='#808080', is_billable=True):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO categories (name, is_focus, is_distraction, color, is_billable) 
            VALUES (%s, %s, %s, %s, %s)
        ''', (name, is_focus, is_distraction, color, is_billable))
        conn.commit()
        return True, "Category added successfully"
    except psycopg2.IntegrityError:
        conn.rollback()
        return False, "Category already exists"
    finally:
        release_db_connection(conn)

def update_category_billable(cat_id, is_billable):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE categories SET is_billable = %s WHERE id = %s", (is_billable, cat_id))
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        release_db_connection(conn)
