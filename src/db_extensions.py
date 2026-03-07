from src.database import init_db, DB_PATH, SEED_ADMIN_EMAIL
import sqlite3
import datetime


def _ue_clause(user_email, alias=''):
    """Helper to build user_email WHERE fragment."""
    if not user_email:
        return '', []
    tbl = f"{alias}." if alias else ''
    sql = f" AND ({tbl}user_email = ? COLLATE NOCASE OR ({tbl}user_email IS NULL AND ? = ?))"
    return sql, [user_email, user_email, SEED_ADMIN_EMAIL]

def get_category_details(category_name, date_str=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"

    # Get Category ID first
    if category_name == 'Uncategorized':
        where_clause = "category_id IS NULL"
        params = (start_time, end_time)
    else:
        c.execute("SELECT id FROM categories WHERE name = ?", (category_name,))
        row = c.fetchone()
        if not row:
            conn.close()
            return {}
        cat_id = row['id']
        where_clause = "category_id = ?"
        params = (cat_id, start_time, end_time)

    # Get activities
    c.execute(f'''
        SELECT id, app_name, window_title, url_or_filename, duration, client, timestamp
        FROM activities 
        WHERE {where_clause} AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp DESC
    ''', params)
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Group by App -> Window Title/URL
    grouped = {}
    
    for r in rows:
        app = r['app_name']
        title = r['window_title'] or r['url_or_filename'] or 'No Title'
        
        if app not in grouped:
            grouped[app] = {'total_duration': 0, 'items': {}}
            
        grouped[app]['total_duration'] += r['duration']
        
        if title not in grouped[app]['items']:
            grouped[app]['items'][title] = {'total_duration': 0, 'activities': []}
            
        grouped[app]['items'][title]['total_duration'] += r['duration']
        grouped[app]['items'][title]['activities'].append({
            'id': r['id'],
            'timestamp': r['timestamp'],
            'duration': r['duration'],
            'client': r['client']
        })
        
    return grouped

def get_client_details(client_name, date_str=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"

    # Get activities for the client
    if client_name == 'Unassigned':
        where_clause = "(client IS NULL OR client = 'Unassigned' OR client = '')"
        params = (start_time, end_time)
    else:
        where_clause = "client = ?"
        params = (client_name, start_time, end_time)

    c.execute(f'''
        SELECT id, app_name, window_title, url_or_filename, duration, client, timestamp
        FROM activities 
        WHERE {where_clause} AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp DESC
    ''', params)
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # Group by App -> Window Title/URL
    grouped = {}
    
    for r in rows:
        app = r['app_name']
        title = r['window_title'] or r['url_or_filename'] or 'No Title'
        
        if app not in grouped:
            grouped[app] = {'total_duration': 0, 'items': {}}
            
        grouped[app]['total_duration'] += r['duration']
        
        if title not in grouped[app]['items']:
            grouped[app]['items'][title] = {'total_duration': 0, 'activities': []}
            
        grouped[app]['items'][title]['total_duration'] += r['duration']
        grouped[app]['items'][title]['activities'].append({
            'id': r['id'],
            'timestamp': r['timestamp'],
            'duration': r['duration'],
            'client': r['client']
        })
        
    return grouped

def assign_activities_bulk(activity_ids, client_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # Get Client Name
        c.execute("SELECT name FROM clients WHERE id = ?", (client_id,))
        client_name = c.fetchone()[0]
        
        # Build query
        placeholders = ','.join('?' for _ in activity_ids)
        query = f"UPDATE activities SET client = ? WHERE id IN ({placeholders})"
        args = [client_name] + activity_ids
        
        c.execute(query, args)
        conn.commit()
        return True, f"Updated {c.rowcount} activities"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def assign_activities_category_bulk(activity_ids, category_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        # Build query
        placeholders = ','.join('?' for _ in activity_ids)
        query = f"UPDATE activities SET category_id = ? WHERE id IN ({placeholders})"
        args = [category_id] + activity_ids
        
        c.execute(query, args)
        conn.commit()
        return True, f"Updated {c.rowcount} activities"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def bulk_update_activities(activity_ids, client_id=None, category_id=None):
    if not activity_ids:
        return False, "No activity IDs provided"
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        updates = []
        params = []
        
        if client_id is not None:
            if client_id == "": # Specific case for unassigning
                updates.append("client = 'Unassigned'")
            else:
                c.execute("SELECT name FROM clients WHERE id = ?", (client_id,))
                res = c.fetchone()
                if res:
                    updates.append("client = ?")
                    params.append(res[0])

        if category_id is not None:
            if category_id == "":
                updates.append("category_id = NULL")
            else:
                updates.append("category_id = ?")
                params.append(category_id)
                
        if not updates:
            return True, "No changes to apply"
            
        placeholders = ','.join(['?'] * len(activity_ids))
        query = f"UPDATE activities SET {', '.join(updates)} WHERE id IN ({placeholders})"
        c.execute(query, params + activity_ids)
        conn.commit()
        return True, f"Updated {c.rowcount} activities."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

def get_aggregated_activities(minutes=10, date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    ue_sql, ue_params = _ue_clause(user_email)
    query = f"SELECT * FROM activities WHERE timestamp >= ? AND timestamp <= ?{ue_sql}"
    params = [start_time, end_time] + ue_params
    
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
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    
    if not rows:
        return []
        
    aggregated = []
    current_bucket = None
    bucket_duration = minutes * 60
    
    # Process from newest to oldest (as rows are DESC) or oldest to newest?
    # Better to process ASC timestamps for chronological bucketing, but UI shows DESC.
    # Let's reverse to process ASC, then reverse back.
    rows.reverse()
    
    current_start_time = None
    
    for row in rows:
        ts = datetime.datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        
        if current_start_time is None:
            current_start_time = ts
            # Align to nearest 10 min mark? Optional. Let's just chunk effectively.
            # Aligning makes it cleaner: e.g. 9:00, 9:10.
            minute_floor = (ts.minute // minutes) * minutes
            current_bucket_start = ts.replace(minute=minute_floor, second=0, microsecond=0)
            
            current_bucket = {
                'start_time': current_bucket_start,
                'end_time': current_bucket_start + datetime.timedelta(minutes=minutes),
                'apps': {},
                'titles': {},
                'total_duration': 0,
                'client_counts': {},
                'ids': []
            }
        
        # Check if row belongs in current bucket
        if ts < current_bucket['end_time']:
            # Add to bucket
            app = row['app_name']
            title = row['window_title']
            client = row['client'] or 'Unassigned'
            duration = row['duration']
            
            current_bucket['apps'][app] = current_bucket['apps'].get(app, 0) + duration
            current_bucket['titles'][title] = current_bucket['titles'].get(title, 0) + duration
            current_bucket['client_counts'][client] = current_bucket['client_counts'].get(client, 0) + duration
            current_bucket['total_duration'] += duration
            current_bucket['ids'].append(row['id'])
        else:
            # Finalize current bucket and start new
            aggregated.append(finalize_bucket(current_bucket))
            
            # Start new bucket from this row's timestamp (aligned)
            minute_floor = (ts.minute // minutes) * minutes
            current_bucket_start = ts.replace(minute=minute_floor, second=0, microsecond=0)
            
            current_bucket = {
                'start_time': current_bucket_start,
                'end_time': current_bucket_start + datetime.timedelta(minutes=minutes),
                'apps': {row['app_name']: row['duration']},
                'titles': {row['window_title']: row['duration']},
                'total_duration': row['duration'],
                'client_counts': {(row['client'] or 'Unassigned'): row['duration']},
                'ids': [row['id']]
            }
            
    if current_bucket:
        aggregated.append(finalize_bucket(current_bucket))
        
    return aggregated
def get_summarized_logs(date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    ue_sql, ue_params = _ue_clause(user_email)
    query_where = f"WHERE timestamp >= ? AND timestamp <= ?{ue_sql}"
    params = [start_time, end_time] + ue_params
    
    if app_filter:
        query_where += " AND app_name LIKE ?"
        params.append(f"%{app_filter}%")
    if title_filter:
        query_where += " AND window_title LIKE ?"
        params.append(f"%{title_filter}%")
    if client_filter:
        query_where += " AND client = ?"
        params.append(client_filter)
    if category_filter is not None:
        if category_filter == "0" or category_filter == 0:
            query_where += " AND (category_id IS NULL OR category_id = 0)"
        else:
            query_where += " AND category_id = ?"
            params.append(category_filter)
        
    query = f'''
        SELECT 
            app_name, 
            window_title, 
            category_id, 
            client,
            SUM(duration) as total_duration,
            MAX(timestamp) as last_timestamp,
            GROUP_CONCAT(id) as ids
        FROM activities 
        {query_where}
        GROUP BY app_name, window_title, category_id, client
        ORDER BY total_duration DESC
    '''
    
    c.execute(query, tuple(params))
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    
    # Process GROUP_CONCAT ids into a list
    for r in rows:
        if r['ids']:
            r['ids'] = [int(i) for i in r['ids'].split(',')]
        else:
            r['ids'] = []
            
    return rows

def finalize_bucket(bucket):
    # Find dominant app and title
    dominant_app = max(bucket['apps'].items(), key=lambda x: x[1])[0] if bucket['apps'] else "Unknown"
    dominant_title = max(bucket['titles'].items(), key=lambda x: x[1])[0] if bucket['titles'] else "Unknown"
    dominant_client = max(bucket['client_counts'].items(), key=lambda x: x[1])[0] if bucket['client_counts'] else "Unassigned"
    
    return {
        'timestamp': bucket['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
        'app_name': dominant_app,
        'window_title': dominant_title, # Maybe append " + 5 others"
        'client': dominant_client,
        'duration': bucket['total_duration'], # Total active time in this 10 min window
        'count': len(bucket['ids']),
        'ids': bucket['ids'] # For potential drilldown
    }

def get_score_stats(date_str=None):
    """
    Calculates Focus, Communication, and Break stats.
    Focus: Time in categories with is_focus=1
    Communication: Time in Meeting, Communication, Email
    Breaks: Total Elapsed Time (since start) - Total Active Time
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    # 1. Get all activities for today with category info
    c.execute('''
        SELECT a.duration, c.name as category, c.is_focus 
        FROM activities a
        LEFT JOIN categories c ON a.category_id = c.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?
    ''', (start_time, end_time))
    
    rows = [dict(r) for r in c.fetchall()]
    
    # 2. Get Start Time of first activity
    c.execute("SELECT MIN(timestamp) FROM activities WHERE timestamp >= ? AND timestamp <= ?", (start_time, end_time))
    first_activity_ts = c.fetchone()[0]
    conn.close()
    
    if not rows or not first_activity_ts:
        return {
            'focus': {'time': 0, 'pct': 0},
            'meeting': {'time': 0, 'pct': 0},
            'break': {'time': 0, 'pct': 0},
            'total_elapsed': 0
        }
        
    # Calculate Total Elapsed Time
    start_dt = datetime.datetime.strptime(first_activity_ts, '%Y-%m-%d %H:%M:%S')
    now_dt = datetime.datetime.now()
    total_elapsed = (now_dt - start_dt).total_seconds()
    
    # Calculate Component Times
    focus_time = 0
    meeting_time = 0
    active_time = 0
    
    comm_categories = ['Collaboration']
    
    for r in rows:
        duration = r['duration']
        active_time += duration
        
        # Focus
        if r['is_focus']:
            focus_time += duration
            
        # Meeting/Comm
        cat_name = r['category']
        if cat_name in comm_categories:
            meeting_time += duration
            
    # Break Time
    # If active_time > total_elapsed (due to parallel overlapping logs?), clamp it.
    # Actually, simplistic logger might log parallel. 
    # For now, simplistic break calc:
    break_time = max(0, total_elapsed - active_time)
    
    # Calculate Percentages
    # Denominator: Total Elapsed Time (Total time spent "at work")
    # If total_elapsed is small, avoid div by zero
    denom = max(1, total_elapsed)
    
    return {
        'focus': {'time': int(focus_time), 'pct': round((focus_time / denom) * 100)},
        'meeting': {'time': int(meeting_time), 'pct': round((meeting_time / denom) * 100)},
        'break': {'time': int(break_time), 'pct': round((break_time / denom) * 100)},
        'total_elapsed': int(total_elapsed)
    }

def get_timeline_stats(date_str=None):
    """
    Returns hourly activity for Focus and Communication.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    c.execute('''
        SELECT a.duration, a.timestamp, c.name as category, c.is_focus
        FROM activities a
        LEFT JOIN categories c ON a.category_id = c.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?
        ORDER BY a.timestamp ASC
    ''', (start_time, end_time))
    
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    
    # Range 8 AM to 10 PM
    start_h = 8
    end_h = 22
    
    # Expand if data outside
    if rows:
        first_h = datetime.datetime.strptime(rows[0]['timestamp'], '%Y-%m-%d %H:%M:%S').hour
        last_h = datetime.datetime.strptime(rows[-1]['timestamp'], '%Y-%m-%d %H:%M:%S').hour
        start_h = min(start_h, first_h)
        end_h = max(end_h, last_h)

    hourly_data = {}
    # Use the date from date_str for buckets
    try:
        base_date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    except:
        base_date = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for h in range(start_h, end_h + 1):
        h_str = f"{h:02d}:00"
        label = datetime.time(h % 24).strftime('%I %p').lstrip('0')
        hourly_data[h] = {'hour': label, 'focus': 0, 'comms': 0, 'total': 0}

    comm_categories = ['Collaboration']

    for r in rows:
        dt = datetime.datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S')
        h = dt.hour
        if h not in hourly_data: continue
        
        dur = r['duration']
        if r['is_focus']:
            hourly_data[h]['focus'] += dur
        elif r['category'] in comm_categories:
            hourly_data[h]['comms'] += dur
        hourly_data[h]['total'] += dur

    return [hourly_data[h] for h in sorted(hourly_data.keys())]
def get_current_session_info(date_str=None):
    """
    Finds the start of the current work session.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    start_time = f"{date_str} 00:00:00"
    end_time = f"{date_str} 23:59:59"
    
    c.execute('''
        SELECT timestamp FROM activities 
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
    ''', (start_time, end_time))
    
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return None
        
    # Standard gap is 5 mins
    gap_threshold = datetime.timedelta(minutes=5)
    session_start = rows[0]['timestamp']
    
    for i in range(1, len(rows)):
        prev_ts = datetime.datetime.strptime(rows[i-1]['timestamp'], '%Y-%m-%d %H:%M:%S')
        curr_ts = datetime.datetime.strptime(rows[i]['timestamp'], '%Y-%m-%d %H:%M:%S')
        
        if (curr_ts - prev_ts) > gap_threshold:
            session_start = rows[i]['timestamp']
            
    return session_start
def get_weekly_score_stats(date_str=None):
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    end_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    
    total_focus = 0
    total_meeting = 0
    total_break = 0
    total_elapsed = 0
    
    for i in range(7):
        d_str = (end_dt - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        day_stats = get_score_stats(d_str)
        total_focus += day_stats['focus']['time']
        total_meeting += day_stats['meeting']['time']
        total_break += day_stats['break']['time']
        total_elapsed += day_stats['total_elapsed']
        
    denom = max(1, total_elapsed)
    
    return {
        'focus': {'time': int(total_focus), 'pct': round((total_focus / denom) * 100)},
        'meeting': {'time': int(total_meeting), 'pct': round((total_meeting / denom) * 100)},
        'break': {'time': int(total_break), 'pct': round((total_break / denom) * 100)},
        'total_elapsed': int(total_elapsed)
    }

def get_weekly_timeline_stats(date_str=None):
    """
    Returns daily activity for Focus and Communication for the last 7 days.
    """
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    ref_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    
    result = []
    # Fetch from 6 days ago up to ref_dt (7 days total)
    for i in range(6, -1, -1):
        d_dt = ref_dt - datetime.timedelta(days=i)
        d_str = d_dt.strftime('%Y-%m-%d')
        
        # We need sum by date. We can optimize this or reuse day stats.
        day_timeline = get_timeline_stats(d_str)
        
        total_focus = sum(h['focus'] for h in day_timeline)
        total_comms = sum(h['comms'] for h in day_timeline)
        total_all = sum(h['total'] for h in day_timeline)
        
        result.append({
            'hour': d_dt.strftime('%a'),
            'focus': total_focus,
            'comms': total_comms,
            'total': total_all,
            'date_full': d_str
        })
        
    return result


# --- Team Analytics Functions ---

def get_team_summary(member_emails, start_date, end_date):
    """
    Returns aggregated stats for a list of team member emails.
    Returns:
      {
        'members': [{ email, name, total_time, billable_time, non_billable_time, by_client: [...], by_category: [...] }],
        'by_client': [{ client, total_time, billable_time, non_billable_time, member_breakdown: {email: time} }],
        'by_category': [{ category, color, is_billable, total_time, member_breakdown: {email: time} }],
        'totals': { total_time, billable_time, non_billable_time }
      }
    """
    if not member_emails:
        return {'members': [], 'by_client': [], 'by_category': [], 'totals': {'total_time': 0, 'billable_time': 0, 'non_billable_time': 0}}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    start_time = f"{start_date} 00:00:00"
    end_time = f"{end_date} 23:59:59"

    # The primary user on this device — empty chrome_profile rows belong to them
    primary_email = member_emails[0]

    # Build placeholder string for the full member list
    placeholders = ','.join('?' for _ in member_emails)

    # Pull all activities for these users.
    # Activities with blank/null chrome_profile are attributed to the primary (manager) email
    # since this is a single-device tracker.
    c.execute(f'''
        SELECT
            a.id, a.timestamp, a.app_name, a.window_title, a.url_or_filename,
            CASE
                WHEN a.chrome_profile IS NULL OR TRIM(a.chrome_profile) = ''
                THEN ?
                ELSE a.chrome_profile
            END as chrome_profile,
            a.client, a.duration,
            a.category_id,
            COALESCE(cat.name, 'Uncategorized') as category_name,
            COALESCE(cat.color, '#94a3b8') as category_color,
            COALESCE(cat.is_focus, 0) as is_focus,
            CASE WHEN COALESCE(cat.name, '') IN ('Collaboration', 'Meeting', 'Communication') THEN 1 ELSE 0 END as is_meeting,
            CASE WHEN (a.client IS NOT NULL AND a.client != '' AND a.client != 'Unassigned') THEN 1 ELSE 0 END as is_billable
        FROM activities a
        LEFT JOIN categories cat ON a.category_id = cat.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?
          AND (
              (a.chrome_profile IS NULL OR TRIM(a.chrome_profile) = '')
              OR a.chrome_profile IN ({placeholders})
          )
        ORDER BY a.timestamp DESC
    ''', [primary_email, start_time, end_time] + member_emails)

    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    # --- Aggregate ---
    # Per-member
    member_stats = {email: {
        'total_time': 0, 'billable_time': 0, 'non_billable_time': 0,
        'focus_time': 0, 'meeting_time': 0,
        'by_client': {}, 'by_category': {}
    } for email in member_emails}

    # Cross-team
    client_totals = {}  # client -> {total, billable, non_billable, members: {email: time}}
    category_totals = {}  # cat_name -> {color, is_billable, total, members: {email: time}}
    grand_focus = 0
    grand_meeting = 0

    for r in rows:
        email = r['chrome_profile']
        if email not in member_stats:
            continue
        dur = r['duration'] or 0
        client = r['client'] or 'Unassigned'
        cat = r['category_name']
        billable = bool(r['is_billable'])
        is_focus = bool(r['is_focus'])
        is_meeting = bool(r['is_meeting'])

        # Member totals
        ms = member_stats[email]
        ms['total_time'] += dur
        if billable:
            ms['billable_time'] += dur
        else:
            ms['non_billable_time'] += dur
        if is_focus:
            ms['focus_time'] += dur
            grand_focus += dur
        if is_meeting:
            ms['meeting_time'] += dur
            grand_meeting += dur

        # Member by client
        ms['by_client'][client] = ms['by_client'].get(client, 0) + dur
        # Member by category
        ms['by_category'][cat] = ms['by_category'].get(cat, 0) + dur

        # Cross-team client
        if client not in client_totals:
            client_totals[client] = {'total_time': 0, 'billable_time': 0, 'non_billable_time': 0, 'members': {}}
        client_totals[client]['total_time'] += dur
        if billable:
            client_totals[client]['billable_time'] += dur
        else:
            client_totals[client]['non_billable_time'] += dur
        client_totals[client]['members'][email] = client_totals[client]['members'].get(email, 0) + dur

        # Cross-team category
        if cat not in category_totals:
            category_totals[cat] = {
                'color': r['category_color'], 'is_billable': billable,
                'total_time': 0, 'members': {}
            }
        category_totals[cat]['total_time'] += dur
        category_totals[cat]['members'][email] = category_totals[cat]['members'].get(email, 0) + dur

    # Format
    members_list = sorted([
        {'email': email, 'total_time': d['total_time'], 'billable_time': d['billable_time'],
         'non_billable_time': d['non_billable_time'],
         'by_client': sorted([{'client': k, 'time': v} for k, v in d['by_client'].items()], key=lambda x: -x['time']),
         'by_category': sorted([{'category': k, 'time': v} for k, v in d['by_category'].items()], key=lambda x: -x['time'])}
        for email, d in member_stats.items()
    ], key=lambda x: -x['total_time'])

    by_client = sorted([
        {'client': k, 'total_time': v['total_time'], 'billable_time': v['billable_time'],
         'non_billable_time': v['non_billable_time'], 'member_breakdown': v['members']}
        for k, v in client_totals.items()
    ], key=lambda x: -x['total_time'])

    by_category = sorted([
        {'category': k, 'color': v['color'], 'is_billable': v['is_billable'],
         'total_time': v['total_time'], 'member_breakdown': v['members']}
        for k, v in category_totals.items()
    ], key=lambda x: -x['total_time'])

    grand_total = sum(ms['total_time'] for ms in member_stats.values())
    grand_billable = sum(ms['billable_time'] for ms in member_stats.values())
    denom = max(1, grand_total)

    return {
        'members': members_list,
        'by_client': by_client,
        'by_category': by_category,
        'totals': {
            'total_time': grand_total,
            'billable_time': grand_billable,
            'non_billable_time': grand_total - grand_billable,
            'focus_pct': round((grand_focus / denom) * 100),
            'meeting_pct': round((grand_meeting / denom) * 100),
            'focus_time': int(grand_focus),
            'meeting_time': int(grand_meeting),
        }
    }



def get_member_detail(member_email, start_date, end_date):
    """
    Full drill-down for one team member across a date range.
    Returns client breakdown, category breakdown, app breakdown, and activity log.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    start_time = f"{start_date} 00:00:00"
    end_time = f"{end_date} 23:59:59"

    c.execute('''
        SELECT
            a.id, a.timestamp, a.app_name, a.window_title,
            a.client, a.duration,
            COALESCE(cat.name, 'Uncategorized') as category_name,
            COALESCE(cat.color, '#94a3b8') as category_color,
            CASE WHEN (a.client IS NOT NULL AND a.client != '' AND a.client != 'Unassigned') THEN 1 ELSE 0 END as is_billable
        FROM activities a
        LEFT JOIN categories cat ON a.category_id = cat.id
        WHERE (
            a.chrome_profile = ? COLLATE NOCASE
            OR (a.chrome_profile IS NULL OR TRIM(a.chrome_profile) = '')
        )
          AND a.timestamp >= ? AND a.timestamp <= ?
        ORDER BY a.timestamp DESC
        LIMIT 500
    ''', (member_email, start_time, end_time))

    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    by_client, by_category, by_app = {}, {}, {}
    total_time = 0

    for r in rows:
        dur = r['duration'] or 0
        client = r['client'] or 'Unassigned'
        cat = r['category_name']
        app = r['app_name']
        billable = bool(r['is_billable'])
        total_time += dur

        by_client[client] = {
            'time': by_client.get(client, {}).get('time', 0) + dur,
            'billable': billable
        }
        if cat not in by_category:
            by_category[cat] = {'time': 0, 'color': r['category_color'], 'is_billable': billable}
        by_category[cat]['time'] += dur

        if app not in by_app:
            by_app[app] = 0
        by_app[app] += dur

    return {
        'total_time': total_time,
        'by_client': sorted([{'client': k, 'time': v['time'], 'billable': v['billable']} for k, v in by_client.items()], key=lambda x: -x['time']),
        'by_category': sorted([{'category': k, 'time': v['time'], 'color': v['color'], 'is_billable': v['is_billable']} for k, v in by_category.items()], key=lambda x: -x['time']),
        'by_app': sorted([{'app': k, 'time': v} for k, v in by_app.items()], key=lambda x: -x['time'])[:10],
        'recent_activities': [
            {'timestamp': r['timestamp'], 'app': r['app_name'], 'title': r['window_title'],
             'client': r['client'], 'category': r['category_name'], 'duration': r['duration']}
            for r in rows[:50]
        ]
    }
