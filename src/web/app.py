from flask import Flask, render_template, jsonify, request, session, redirect, url_for, g
import datetime
import os
from ..database import (
    init_db,
    get_todays_activities, get_summary_stats, get_weekly_summary_stats, get_application_stats, get_application_activities,
    get_clients, add_client, update_client, get_mappings, add_mapping, get_unassigned_summary,
    get_client_users, set_client_users, get_clients_for_user,
    get_categories, get_category_mappings, add_category_mapping,
    get_work_blocks, get_overtime_stats,
    # User management
    get_user_by_email, get_all_users, upsert_user, delete_user,
    get_all_reports, has_reports,
    # Org settings
    get_org_settings, update_org_setting,
    # Category admin
    update_category_full, add_category, update_category_billable,
    # Token management
    get_api_token, rotate_api_token, get_user_email_by_token, log_activity, log_activities_batch,
    # Pause/resume
    set_user_paused, get_user_paused,
    # Agent health
    update_agent_heartbeat, get_all_agent_status, get_user_agent_version,
    SEED_ADMIN_EMAIL
)
from ..db_extensions import (
    get_category_details, get_client_details, assign_activities_bulk, assign_activities_category_bulk, get_aggregated_activities,
    get_summarized_logs, get_score_stats, get_weekly_score_stats, get_timeline_stats, get_weekly_timeline_stats,
    get_monthly_summary_stats, get_monthly_score_stats, get_monthly_timeline_stats,
    get_current_session_info, bulk_update_activities,
    get_team_summary, get_member_detail
)
from ..skills.category_mapper import CategoryMapper
from ..skills.client_mapper import ClientMapper

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_change_in_production')

# Initialise DB schema on startup (critical for Render/gunicorn — main.py is not used)
try:
    init_db()
except Exception as e:
    print(f'[startup] init_db failed: {e}')

# ── Auto-categorisation mappers (lazily reloaded on first ingest call) ──────────
_category_mapper = None
_client_mapper = None

def _get_mappers():
    """Return (category_mapper, client_mapper), re-instantiating to pick up DB rule changes."""
    global _category_mapper, _client_mapper
    if _category_mapper is None:
        _category_mapper = CategoryMapper()
    if _client_mapper is None:
        _client_mapper = ClientMapper()
    return _category_mapper, _client_mapper

def _reload_mappers():
    """Force-reload both mappers so admin rule changes take effect immediately."""
    global _category_mapper, _client_mapper
    _category_mapper = CategoryMapper()
    _client_mapper = ClientMapper()

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    user_name = session.get('user_name')
    if user_id is None:
        g.user = None
    else:
        db_user = get_user_by_email(user_id)
        role = db_user['role'] if db_user else 'member'
        can_see_team = (role == 'admin') or (has_reports(user_id))
        g.user = {
            'id': user_id, 'name': user_name, 'email': user_id,
            'role': role, 'can_see_team': can_see_team
        }

@app.context_processor
def inject_user():
    return dict(user=g.user)

def require_role(*roles):
    """Returns a redirect response if the current user lacks one of the given roles, else None."""
    if g.user is None:
        return redirect(url_for('login'))
    if g.user.get('role') not in roles:
        return redirect(url_for('dashboard'))
    return None

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        email = request.form['email']
        name = request.form.get('name')
        
        # Resolve name from users table, then fallback to email prefix
        db_user = get_user_by_email(email)
        if db_user:
            name = db_user['name']
        elif not name and '@' in email:
            name_part = email.split('@')[0]
            name = name_part.split('.')[0].title()
            
        session.clear()
        session['user_id'] = email
        session['user_name'] = name
        return redirect(url_for('dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.before_request
def require_login():
    if request.endpoint and 'static' in request.endpoint:
        return
    if request.endpoint in ('login', 'api_status', 'api_control', 'api_ingest', 'api_agent_provision'):
        return
    if g.user is None and request.endpoint != 'login':
        return redirect(url_for('login'))


# --- Routes ---

@app.route('/')
def dashboard():
    return render_template('dashboard.html', active_page='dashboard')

@app.route('/activities')
def activities_page():
    return render_template('activities.html', active_page='activities')

@app.route('/summary')
def summary():
    return render_template('summary.html', active_page='summary')

@app.route('/clients')
def clients_page():
    guard = require_role('admin')
    if guard: return guard
    return render_template('clients.html', active_page='clients')

@app.route('/admin')
def admin_page():
    guard = require_role('admin')
    if guard: return guard
    return render_template('admin.html', active_page='admin')

@app.route('/team')
def team_page():
    if g.user is None:
        return redirect(url_for('login'))
    if not g.user.get('can_see_team'):
        return redirect(url_for('dashboard'))
    return render_template('team.html', active_page='team')

# --- API ---

@app.route('/api/users/list')
def api_users_list():
    """Returns all users for the admin member-filter dropdown."""
    if not g.user or not g.user.get('can_see_team'):
        return jsonify([])  # non-admins get empty list
    users = get_all_users()
    return jsonify([{'email': u['email'], 'name': u['name']} for u in users])

@app.route('/api/dashboard')
def api_dashboard():
    """Combined endpoint — returns all dashboard data in one request."""
    import concurrent.futures
    date_str = request.args.get('date')
    view = request.args.get('view', 'day')
    user_email = g.user['email'] if g.user else None
    session_user = session.get('user_id')

    def _summary():
        if view == 'month':
            return get_monthly_summary_stats(date_str, user_email=user_email)
        elif view == 'week':
            return get_weekly_summary_stats(date_str, user_email=user_email)
        return get_summary_stats(date_str, user_email=user_email)

    def _scores():
        if view == 'month':
            return get_monthly_score_stats(date_str, user_email=user_email)
        elif view == 'week':
            return get_weekly_score_stats(date_str, user_email=user_email)
        return get_score_stats(date_str, user_email=user_email)

    def _timeline():
        if view == 'month':
            return get_monthly_timeline_stats(date_str, user_email=user_email)
        elif view == 'week':
            return get_weekly_timeline_stats(date_str, user_email=user_email)
        return get_timeline_stats(date_str, user_email=user_email)

    def _work_stats():
        activities = get_todays_activities(date_str, user_email=user_email)
        start_time = activities[-1][1] if activities else None
        overtime = get_overtime_stats(date_str, user_email=user_email)
        return {
            'active': bool(start_time),
            'start_time': start_time,
            'total_duration': overtime['total_duration'],
            'overtime_duration': overtime['overtime_duration'],
            'is_overtime': overtime['is_overtime']
        }

    def _work_blocks():
        try:
            return get_work_blocks(date_str=date_str, user_email=user_email)
        except Exception:
            return []

    def _status():
        ss = get_current_session_info(date_str, user_email=session_user)
        status = 'unknown'
        if session_user:
            if get_user_paused(session_user):
                status = 'paused'
            else:
                from psycopg2.extras import RealDictCursor as _RDC
                from ..database import get_db_connection as _gdc, release_db_connection as _rdc
                try:
                    cn = _gdc()
                    try:
                        cr = cn.cursor(cursor_factory=_RDC)
                        two_min = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
                        cr.execute('SELECT COUNT(*) as cnt FROM activities WHERE LOWER(user_email) = LOWER(%s) AND server_timestamp >= %s', (session_user, two_min))
                        r = cr.fetchone()
                        status = 'running' if r and r['cnt'] > 0 else 'stopped'
                    finally:
                        _rdc(cn)
                except Exception:
                    status = 'unknown'
        return {
            'status': status,
            'session_start': ss,
            'server_time': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        }

    def _activities():
        return get_aggregated_activities(minutes=10, date_str=date_str, user_email=user_email)

    def _focus_stats():
        rows = get_todays_activities(date_str, user_email=user_email)
        cats = {c['id']: c for c in get_categories()}
        total_time = focus_time = 0
        for row in rows:
            duration = row[7]
            total_time += duration
            cat = cats.get(row[8])
            if cat and cat['is_focus']:
                focus_time += duration
        quality = (focus_time / total_time * 100) if total_time > 0 else 0
        return {
            'quality_score': round(quality, 1),
            'focus_time': focus_time,
            'interruptions': len(rows) // 10,
            'categories': {c['name']: {'color': c['color']} for c in cats.values()}
        }

    # Run all queries in parallel threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        f_summary = pool.submit(_summary)
        f_scores = pool.submit(_scores)
        f_timeline = pool.submit(_timeline)
        f_work_stats = pool.submit(_work_stats)
        f_blocks = pool.submit(_work_blocks)
        f_status = pool.submit(_status)
        f_activities = pool.submit(_activities)
        f_focus = pool.submit(_focus_stats)

    return jsonify({
        'summary': f_summary.result(),
        'scores': f_scores.result(),
        'timeline': f_timeline.result(),
        'work_stats': f_work_stats.result(),
        'work_blocks': f_blocks.result(),
        'status': f_status.result(),
        'activities': f_activities.result(),
        'focus_stats': f_focus.result(),
    })


@app.route('/api/activities')
def api_activities():
    date_str = request.args.get('date')
    is_aggregated = request.args.get('aggregated') == 'true'
    is_summarized = request.args.get('summarized') == 'true'
    member_filter = request.args.get('member')  # team view filter

    # Resolve effective user_email for filtering
    # Admins/managers: ?member=email shows that user, ?member=all shows everyone
    current_email = g.user['email'] if g.user else None
    if member_filter and g.user and g.user.get('can_see_team'):
        effective_email = None if member_filter == 'all' else member_filter
    else:
        effective_email = current_email

    # New Filters
    app_filter = request.args.get('app')
    title_filter = request.args.get('title')
    client_filter = request.args.get('client')
    category_filter = request.args.get('category')
    
    if is_aggregated:
        rows = get_aggregated_activities(
            minutes=10, 
            date_str=date_str,
            app_filter=app_filter,
            title_filter=title_filter,
            client_filter=client_filter,
            category_filter=category_filter,
            user_email=effective_email
        )
        return jsonify(rows)
    elif is_summarized:
        rows = get_summarized_logs(
            date_str=date_str,
            app_filter=app_filter,
            title_filter=title_filter,
            client_filter=client_filter,
            category_filter=category_filter,
            user_email=effective_email
        )
        return jsonify(rows)
    else:
        rows = get_todays_activities(
            date_str=date_str,
            app_filter=app_filter,
            title_filter=title_filter,
            client_filter=client_filter,
            category_filter=category_filter,
            user_email=effective_email
        )
        return jsonify([{
            'timestamp': row[1],
            'app_name': row[2],
            'window_title': row[3],
            'url': row[4],
            'url_or_filename': row[4],
            'profile': row[5],
            'client': row[6],
            'duration': row[7],
            'category_id': row[8],
            'id': row[0]
        } for row in rows])

@app.route('/api/activities/bulk_update', methods=['POST'])
def api_bulk_update():
    data = request.json
    activity_ids = data.get('activity_ids', [])
    client_id = data.get('client_id')
    category_id = data.get('category_id')
    
    if not activity_ids:
        return jsonify({'error': 'Missing activity_ids'}), 400
        
    success, msg = bulk_update_activities(activity_ids, client_id, category_id)
    
    if success:
        return jsonify({'status': 'success', 'message': msg})
    else:
        return jsonify({'error': msg}), 500

@app.route('/api/summary')
def api_summary():
    date_str = request.args.get('date')
    view = request.args.get('view')
    user_email = g.user['email'] if g.user else None
    if view == 'month':
        stats = get_monthly_summary_stats(date_str, user_email=user_email)
    elif view == 'week':
        stats = get_weekly_summary_stats(date_str, user_email=user_email)
    else:
        stats = get_summary_stats(date_str, user_email=user_email)
    return jsonify(stats)

@app.route('/api/focus_stats')
def api_focus_stats():
    # In a real app, we'd query the DB for "Focus" vs "Distraction" time today
    # For now, let's calculate it from get_todays_activities or a specialized query
    # We will compute it on the fly for simplicity
    rows = get_todays_activities()
    
    total_time = 0
    focus_time = 0
    distraction_time = 0
    interruptions = 0
    
    # We need to look up category types. 
    # Valid optimization: Join in SQL. 
    # For MVP: Fetch all categories and map in python.
    cats = {c['id']: c for c in get_categories()}
    
    last_type = None
    
    for row in rows:
        duration = row[7]
        cat_id = row[8]
        
        total_time += duration
        
        cat = cats.get(cat_id)
        is_focus = cat['is_focus'] if cat else False
        is_distraction = cat['is_distraction'] if cat else False
        
        current_type = 'neutral'
        if is_focus: 
            focus_time += duration
            current_type = 'focus'
        elif is_distraction: 
            distraction_time += duration
            current_type = 'distraction'
            
        # interruptions (very rough approx given descending order list, need chronological)
        # rows are DESC.
        
    # Quality Score: Focus / (Focus + Distraction + Neutral)
    quality = (focus_time / total_time * 100) if total_time > 0 else 0
    
    return jsonify({
        'quality_score': round(quality, 1),
        'focus_time': focus_time,
        'interruptions': random_mock_interruptions(rows), # Placeholder or implement smarter calc
        'categories': {c['name']: {'color': c['color']} for c in cats.values()}
    })

def random_mock_interruptions(rows):
    # Just a placeholder to show data on UI if logic isn't perfect yet
    return len(rows) // 10 

@app.route('/api/categories', methods=['GET', 'POST'])
def api_categories():
    if request.method == 'POST':
         # Map category
         data = request.json
         add_category_mapping(data['category_id'], data['pattern_type'], data['pattern_value'])
         return jsonify({'status': 'success'})
         
    return jsonify([dict(c) for c in get_categories()])

@app.route('/api/category_details/<category_name>')
def api_category_details(category_name):
    date_str = request.args.get('date')
    # Retrieve hierarchical data
    data = get_category_details(category_name, date_str)
    return jsonify(data)

@app.route('/api/client_details/<client_name>')
def api_client_details(client_name):
    date_str = request.args.get('date')
    # Retrieve hierarchical data
    data = get_client_details(client_name, date_str)
    return jsonify(data)

@app.route('/api/activities/assign_bulk', methods=['POST'])
def api_assign_bulk():
    data = request.json
    activity_ids = data.get('activity_ids', [])
    client_id = data.get('client_id')
    
    if not activity_ids or not client_id:
        return jsonify({'error': 'Missing activity_ids or client_id'}), 400
        
    success, msg = assign_activities_bulk(activity_ids, client_id)
    
    if success:
        return jsonify({'status': 'success', 'message': msg})
    else:
        return jsonify({'error': msg}), 500

@app.route('/api/activities/assign_category_bulk', methods=['POST'])
def api_assign_category_bulk():
    data = request.json
    activity_ids = data.get('activity_ids', [])
    category_id = data.get('category_id')
    
    if not activity_ids or not category_id:
        return jsonify({'error': 'Missing activity_ids or category_id'}), 400
        
    success, msg = assign_activities_category_bulk(activity_ids, category_id)
    
    if success:
        return jsonify({'status': 'success', 'message': msg})
    else:
        return jsonify({'error': msg}), 500

@app.route('/api/scores')
def api_scores():
    date_str = request.args.get('date')
    view = request.args.get('view')
    user_email = g.user['email'] if g.user else None
    if view == 'month':
        stats = get_monthly_score_stats(date_str, user_email=user_email)
    elif view == 'week':
        stats = get_weekly_score_stats(date_str, user_email=user_email)
    else:
        stats = get_score_stats(date_str, user_email=user_email)
    return jsonify(stats)

@app.route('/api/timeline')
def api_timeline():
    date_str = request.args.get('date')
    view = request.args.get('view')
    user_email = g.user['email'] if g.user else None
    if view == 'month':
        stats = get_monthly_timeline_stats(date_str, user_email=user_email)
    elif view == 'week':
        stats = get_weekly_timeline_stats(date_str, user_email=user_email)
    else:
        stats = get_timeline_stats(date_str, user_email=user_email)
    return jsonify(stats)

@app.route('/api/work_stats')
def api_work_stats():
    date_str = request.args.get('date')
    user_email = g.user['email'] if g.user else None
    activities = get_todays_activities(date_str, user_email=user_email)
    start_time = activities[-1][1] if activities else None
    
    overtime = get_overtime_stats(date_str, user_email=user_email)
    
    return jsonify({
        'active': bool(start_time),
        'start_time': start_time,
        'total_duration': overtime['total_duration'],
        'overtime_duration': overtime['overtime_duration'],
        'is_overtime': overtime['is_overtime']
    })

@app.route('/api/work_blocks')
def api_work_blocks():
    date_str = request.args.get('date')
    user_email = g.user['email'] if g.user else None
    try:
        blocks = get_work_blocks(date_str=date_str, user_email=user_email)
        return jsonify(blocks)
    except Exception as e:
        print(f"Error getting work blocks: {e}")
        return jsonify([]), 500

@app.route('/application/<app_name>')
def application_details(app_name):
    # Decode app name if needed, but Flask handles URL decoding usually
    return render_template('application.html', app_name=app_name, active_page='dashboard')

@app.route('/api/application/<app_name>')
def api_application_details(app_name):
    stats = get_application_stats(app_name)
    activities = get_application_activities(app_name)
    
    # Convert activities to list of dicts
    activity_list = []
    for row in activities:
        activity_list.append({
            'timestamp': row['timestamp'],
            'window_title': row['window_title'],
            'client': row['client'],
            'duration': row['duration']
        })
        
    return jsonify({
        'stats': stats,
        'activities': activity_list
    })

# --- Client Management API ---

@app.route('/api/clients', methods=['GET', 'POST'])
def api_clients():
    if request.method == 'POST':
        # Only admins may add/edit clients
        if not g.user or g.user.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin access required'}), 403
        data = request.json
        name = data.get('name')
        notes = data.get('notes', '')
        zoho_org_id = data.get('zoho_org_id', '').strip() or None
        client_id = data.get('id')
        
        if client_id:
            success, msg = update_client(client_id, name, notes, zoho_org_id)
        else:
            success, msg = add_client(name, notes, zoho_org_id)
            
        if success:
            return jsonify({'status': 'success', 'message': msg})
        else:
            return jsonify({'status': 'error', 'message': msg}), 400
            
    # GET — admins see all clients; regular users see only their assigned clients
    if g.user and g.user.get('role') == 'admin':
        clients = get_clients()
    else:
        user_email = g.user['email'] if g.user else None
        clients = get_clients_for_user(user_email) if user_email else []
        if not clients:
            # Fallback: if no clients assigned yet, show all (graceful migration)
            clients = get_clients()
    return jsonify([dict(c) for c in clients])

@app.route('/api/mappings', methods=['GET', 'POST'])
def api_mappings():
    if request.method == 'POST':
        data = request.json
        client_id = data.get('client_id')
        pattern_type = data.get('pattern_type')
        pattern_value = data.get('pattern_value')
        
        success, msg = add_mapping(client_id, pattern_type, pattern_value)
        if success:
             return jsonify({'status': 'success', 'message': msg})
        else:
             return jsonify({'status': 'error', 'message': msg}), 400

    mappings = get_mappings()
    return jsonify([dict(m) for m in mappings])

@app.route('/api/client_users/<int:client_id>', methods=['GET', 'PUT'])
def api_client_users(client_id):
    if not g.user or g.user.get('role') != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    if request.method == 'PUT':
        user_ids = request.json.get('user_ids', [])
        set_client_users(client_id, user_ids)
        return jsonify({'status': 'success'})
    return jsonify(get_client_users(client_id))

@app.route('/api/unassigned')
def api_unassigned():
    # Only admins see all unassigned; regular users see only their own
    if g.user and g.user.get('role') == 'admin':
        rows = get_unassigned_summary(user_email=None)
    else:
        user_email = g.user['email'] if g.user else None
        rows = get_unassigned_summary(user_email=user_email)
    return jsonify([dict(r) for r in rows])

# Global agent reference (hacky but effective for this scale)
agent_ref = None

@app.route('/api/status')
def api_status():
    date_str = request.args.get('date')
    user_email = session.get('user_id')
    session_start = get_current_session_info(date_str, user_email=user_email)

    # Determine tracking status:
    # 1. If a local agent_ref is available, use its status
    # 2. Otherwise: check DB paused flag first, then detect from recent log activity
    status = 'unknown'
    if agent_ref:
        status = agent_ref.get_status()
    else:
        if user_email:
            # Check if user has manually paused via the web UI
            if get_user_paused(user_email):
                status = 'paused'
            else:
                from psycopg2.extras import RealDictCursor
                from ..database import get_db_connection, release_db_connection
                try:
                    conn = get_db_connection()
                    try:
                        c = conn.cursor(cursor_factory=RealDictCursor)
                        two_min_ago = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M:%S')
                        c.execute('''
                            SELECT COUNT(*) as cnt FROM activities
                            WHERE LOWER(user_email) = LOWER(%s) AND server_timestamp >= %s
                        ''', (user_email, two_min_ago))
                        row = c.fetchone()
                        status = 'running' if row and row['cnt'] > 0 else 'stopped'
                    finally:
                        release_db_connection(conn)
                except Exception as e:
                    print(f'[status] error checking recent logs: {e}')
                    status = 'unknown'

    return jsonify({
        'status': status,
        'session_start': session_start,
        'server_time': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')  # ISO UTC
    })

@app.route('/api/control/<action>', methods=['POST'])
def api_control(action):
    # Support both session-based (web UI) and token-based (desktop agent) auth
    user_email = session.get('user_id')
    if not user_email:
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.removeprefix('Bearer ').strip()
        if token:
            user_email = get_user_email_by_token(token)

    if not user_email:
        return jsonify({'error': 'Not authenticated'}), 401

    if agent_ref:
        # Local mode — control the in-process agent directly
        if action in ('pause', 'break_start'):
            agent_ref.pause()
            return jsonify({'status': 'paused' if action == 'pause' else 'break'})
        elif action in ('resume', 'break_end'):
            agent_ref.resume()
            return jsonify({'status': 'running'})
    else:
        # Cloud mode — persist pause state in DB; desktop agent polls /api/agent/poll
        if action in ('pause', 'break_start'):
            set_user_paused(user_email, True)
            return jsonify({'status': 'paused', 'message': 'Tracking paused — desktop agent will stop within 30 s'})
        elif action in ('resume', 'break_end'):
            set_user_paused(user_email, False)
            return jsonify({'status': 'running', 'message': 'Tracking resumed'})

    return jsonify({'error': 'Invalid action'}), 400


@app.route('/api/agent/poll')
def api_agent_poll():
    """Desktop agent polls this to check whether it should pause/resume.
    Auth: Authorization: Bearer <api_token>
    Returns: { "paused": true/false }
    """
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.removeprefix('Bearer ').strip()
    user_email = get_user_email_by_token(token)
    if not user_email:
        return jsonify({'error': 'Invalid or missing API token'}), 401
    paused = get_user_paused(user_email)
    return jsonify({'paused': paused})

# ============================================================
# --- Agent Health (Admin Diagnostics) ---
# ============================================================

@app.route('/api/admin/agent-health')
def api_admin_agent_health():
    """Returns agent connection status for all users (admin only)."""
    if not g.user or g.user.get('email', '').lower() != SEED_ADMIN_EMAIL.lower():
        return jsonify({'error': 'Admin access required'}), 403
    return jsonify(get_all_agent_status())


# ============================================================
# --- Ingest API (Desktop Agent → Central Backend) ---
# ============================================================

@app.route('/api/ingest', methods=['POST'])
def api_ingest():
    """Receives activity log batches from desktop agents.
    Auth: Authorization: Bearer <api_token>
    Body: { "logs": [ { timestamp, app_name, window_title, url_or_filename,
                         chrome_profile, client, duration, category_id } ] }
    """
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.removeprefix('Bearer ').strip()
    user_email = get_user_email_by_token(token)
    if not user_email:
        return jsonify({'error': 'Invalid or missing API token'}), 401

    data = request.json or {}
    logs = data.get('logs', [])
    if not isinstance(logs, list):
        return jsonify({'error': 'logs must be a list'}), 400

    cat_mapper, cli_mapper = _get_mappers()

    # ── Resolve client + category for each row (in-memory, no DB) ─────────
    for entry in logs:
        try:
            app_name     = entry.get('app_name', '')
            window_title = entry.get('window_title', '')
            url          = entry.get('url_or_filename', '')

            # Client resolution (Zoho Org ID → pattern rules → existing value)
            if not entry.get('client') or entry.get('client') == 'Unassigned':
                try:
                    resolved_client = cli_mapper.resolve(app_name, window_title, url)
                    if resolved_client:
                        entry['client'] = resolved_client
                except Exception as ce:
                    print(f'[ingest] client_mapper error: {ce}')

            # Category resolution (rules → heuristics → AI fallback)
            if not entry.get('category_id'):
                try:
                    _, cat_id = cat_mapper.resolve(app_name, window_title, url)
                    if cat_id:
                        entry['category_id'] = cat_id
                except Exception as ce:
                    print(f'[ingest] category_mapper error: {ce}')

            entry['user_email'] = user_email
        except Exception as e:
            print(f"[ingest] Entry resolution error: {e}")

    # ── Batch insert all rows in a single DB transaction ──────────────────
    try:
        accepted = log_activities_batch(logs)
    except Exception as e:
        # Fallback: try one-by-one if batch fails
        print(f"[ingest] Batch insert failed ({e}), falling back to row-by-row")
        accepted = 0
        for entry in logs:
            try:
                log_activity(entry)
                accepted += 1
            except Exception as row_err:
                print(f"[ingest] Row insert failed: {row_err}")

    # Update heartbeat (and agent version if provided) so admin can monitor
    agent_version = data.get('agent_version')
    if accepted > 0:
        try:
            update_agent_heartbeat(user_email, agent_version=agent_version)
        except Exception as hb_err:
            print(f"[ingest] Heartbeat update failed: {hb_err}")

    return jsonify({'accepted': accepted})


@app.route('/api/agent/provision', methods=['POST'])
def api_agent_provision():
    """Called by the desktop agent on first run to obtain an API token.
    The user must already exist in the users table (added by admin).
    Body: { "email": "user@company.com" }
    Returns: { "token": "...", "email": "..." }
    """
    data = request.json or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'email is required'}), 400

    user = get_user_by_email(email)
    if not user:
        return jsonify({'error': 'Email not registered. Ask your admin to add you first.'}), 403

    token = get_api_token(email)
    if not token:
        token = rotate_api_token(email)

    return jsonify({'token': token, 'email': email})



# ============================================================

@app.route('/api/me/token', methods=['GET'])
def api_my_token():
    """Returns the current user's API token. Creates one if missing."""
    if not g.user:
        return jsonify({'error': 'Not logged in'}), 401
    token = get_api_token(g.user['email'])
    if not token:
        token = rotate_api_token(g.user['email'])
    return jsonify({'token': token, 'email': g.user['email']})


@app.route('/api/me/token/rotate', methods=['POST'])
def api_rotate_token():
    """Generates a new API token for the current user."""
    if not g.user:
        return jsonify({'error': 'Not logged in'}), 401
    token = rotate_api_token(g.user['email'])
    return jsonify({'token': token, 'email': g.user['email']})


@app.route('/api/me/agent-version')
def api_my_agent_version():
    """Returns the current user's installed agent version and heartbeat info."""
    if not g.user:
        return jsonify({'error': 'Not logged in'}), 401
    info = get_user_agent_version(g.user['email'])
    return jsonify(info)


def start_server(agent=None):
    global agent_ref
    agent_ref = agent
    port = int(__import__('os').environ.get('PORT', 5001))
    # Disable reloader to avoid main thread issues
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


# ============================================================
# --- Admin API ---
# ============================================================

@app.route('/api/admin/users', methods=['GET', 'POST'])
def api_admin_users():
    guard = require_role('admin')
    if guard: return guard

    if request.method == 'POST':
        data = request.json
        email = data.get('email', '').strip()
        name = data.get('name', '').strip()
        role = data.get('role', 'member')
        manager_id = data.get('manager_id') or None
        if not email or not name:
            return jsonify({'error': 'email and name are required'}), 400
        success, msg = upsert_user(email, name, role, manager_id)
        if success:
            return jsonify({'status': 'success', 'message': msg})
        return jsonify({'error': msg}), 400

    users = get_all_users()
    return jsonify(users)

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def api_admin_delete_user(user_id):
    guard = require_role('admin')
    if guard: return guard
    success, msg = delete_user(user_id)
    if success:
        return jsonify({'status': 'success', 'message': msg})
    return jsonify({'error': msg}), 400

@app.route('/api/admin/settings', methods=['GET', 'POST'])
def api_admin_settings():
    guard = require_role('admin')
    if guard: return guard
    if request.method == 'POST':
        data = request.json
        for key, value in data.items():
            update_org_setting(key, str(value))
        return jsonify({'status': 'success'})
    return jsonify(get_org_settings())

@app.route('/api/admin/categories', methods=['GET', 'POST'])
def api_admin_categories():
    guard = require_role('admin')
    if guard: return guard
    if request.method == 'POST':
        data = request.json
        action = data.get('action', 'update')
        if action == 'add':
            success, msg = add_category(
                data.get('name', ''),
                is_focus=data.get('is_focus', False),
                is_distraction=data.get('is_distraction', False),
                color=data.get('color', '#808080'),
                is_billable=data.get('is_billable', True)
            )
        else:
            cat_id = data.get('id')
            if not cat_id:
                return jsonify({'error': 'id required'}), 400
            success, msg = update_category_full(
                cat_id,
                name=data.get('name'),
                is_focus=data.get('is_focus'),
                is_distraction=data.get('is_distraction'),
                color=data.get('color'),
                is_billable=data.get('is_billable')
            )
        if success:
            return jsonify({'status': 'success', 'message': msg})
        return jsonify({'error': msg}), 400
    return jsonify([dict(c) for c in get_categories()])

@app.route('/api/admin/categories/<int:cat_id>/billable', methods=['POST'])
def api_admin_category_billable(cat_id):
    guard = require_role('admin')
    if guard: return guard
    data = request.json
    is_billable = data.get('is_billable', True)
    success, msg = update_category_billable(cat_id, is_billable)
    if success:
        return jsonify({'status': 'success'})
    return jsonify({'error': msg}), 400


# ============================================================
# --- Team API ---
# ============================================================

def _get_date_range():
    """Parse start/end from query params, default to current week Mon–today."""
    start = request.args.get('start')
    end = request.args.get('end')
    today = datetime.date.today()
    if not end:
        end = today.strftime('%Y-%m-%d')
    if not start:
        monday = today - datetime.timedelta(days=today.weekday())
        start = monday.strftime('%Y-%m-%d')
    return start, end

@app.route('/api/team/summary')
def api_team_summary():
    if g.user is None or not g.user.get('can_see_team'):
        return jsonify({'error': 'Unauthorized'}), 403

    start, end = _get_date_range()
    email = g.user['email']

    if g.user.get('role') == 'admin':
        # Admin sees ALL users
        all_users = get_all_users()
        member_name_map = {u['email']: u['name'] for u in all_users}
        member_emails = [u['email'] for u in all_users]
    else:
        # Manager sees transitive reports + self
        reports = get_all_reports(email)
        member_name_map = {r['email']: r['name'] for r in reports}
        manager_name = g.user.get('name') or email.split('@')[0].title()
        member_name_map[email] = manager_name
        member_emails = [email] + [r['email'] for r in reports if r['email'].lower() != email.lower()]

    data = get_team_summary(member_emails, start, end)

    # Enrich members with names
    for m in data['members']:
        m['name'] = member_name_map.get(m['email'], m['email'].split('@')[0].title())

    data['date_range'] = {'start': start, 'end': end}
    return jsonify(data)

@app.route('/api/team/member/<path:member_email>')
def api_team_member_detail(member_email):
    if g.user is None or not g.user.get('can_see_team'):
        return jsonify({'error': 'Unauthorized'}), 403

    # Validate the requested member is self or a report of the requesting manager
    requester_email = g.user['email']
    if member_email.lower() != requester_email.lower() and g.user.get('role') != 'admin':
        reports = get_all_reports(requester_email)
        report_emails = {r['email'].lower() for r in reports}
        if member_email.lower() not in report_emails:
            return jsonify({'error': 'Unauthorized'}), 403

    start, end = _get_date_range()
    data = get_member_detail(member_email, start, end)
    # Managers see aggregated data only — never raw activity logs
    data.pop('activities', None)
    return jsonify(data)
