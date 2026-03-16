from src.database import get_db_connection, SEED_ADMIN_EMAIL
import psycopg2
from psycopg2.extras import RealDictCursor
import datetime
import calendar

def _ue_clause(user_email, alias=''):
    if not user_email:
        return '', []
    tbl = f"{alias}." if alias else ''
    sql = f" AND (LOWER({tbl}user_email) = LOWER(%s) OR ({tbl}user_email IS NULL AND %s = %s))"
    return sql, [user_email, user_email, SEED_ADMIN_EMAIL]

def get_category_details(category_name, date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        if category_name == 'Uncategorized':
            where_clause = "category_id IS NULL"
            params = [start_time, end_time]
        else:
            c.execute("SELECT id FROM categories WHERE name = %s", (category_name,))
            row = c.fetchone()
            if not row:
                return {}
            cat_id = row['id']
            where_clause = "category_id = %s"
            params = [cat_id, start_time, end_time]

        c.execute(f'''
            SELECT id, app_name, window_title, url_or_filename, duration, client, timestamp
            FROM activities 
            WHERE {where_clause} AND timestamp >= %s AND timestamp <= %s
            ORDER BY timestamp DESC
        ''', tuple(params))
        
        rows = [dict(r) for r in c.fetchall()]

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
    finally:
        conn.close()

def get_client_details(client_name, date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        if client_name == 'Unassigned':
            where_clause = "(client IS NULL OR client = 'Unassigned' OR client = '')"
            params = [start_time, end_time]
        else:
            where_clause = "client = %s"
            params = [client_name, start_time, end_time]

        c.execute(f'''
            SELECT id, app_name, window_title, url_or_filename, duration, client, timestamp
            FROM activities 
            WHERE {where_clause} AND timestamp >= %s AND timestamp <= %s
            ORDER BY timestamp DESC
        ''', tuple(params))
        
        rows = [dict(r) for r in c.fetchall()]

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
    finally:
        conn.close()

def assign_activities_bulk(activity_ids, client_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
        client_name = c.fetchone()[0]
        
        placeholders = ','.join('%s' for _ in activity_ids)
        query = f"UPDATE activities SET client = %s WHERE id IN ({placeholders})"
        args = [client_name] + activity_ids
        
        c.execute(query, tuple(args))
        conn.commit()
        return True, f"Updated {c.rowcount} activities"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def assign_activities_category_bulk(activity_ids, category_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        placeholders = ','.join('%s' for _ in activity_ids)
        query = f"UPDATE activities SET category_id = %s WHERE id IN ({placeholders})"
        args = [category_id] + activity_ids
        
        c.execute(query, tuple(args))
        conn.commit()
        return True, f"Updated {c.rowcount} activities"
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def bulk_update_activities(activity_ids, client_id=None, category_id=None):
    if not activity_ids:
        return False, "No activity IDs provided"
        
    conn = get_db_connection()
    try:
        c = conn.cursor()
        updates = []
        params = []
        
        if client_id is not None:
            if client_id == "": 
                updates.append("client = 'Unassigned'")
            else:
                c.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
                res = c.fetchone()
                if res:
                    updates.append("client = %s")
                    params.append(res[0])

        if category_id is not None:
            if category_id == "":
                updates.append("category_id = NULL")
            else:
                updates.append("category_id = %s")
                params.append(category_id)
                
        if not updates:
            return True, "No changes to apply"
            
        placeholders = ','.join(['%s'] * len(activity_ids))
        query = f"UPDATE activities SET {', '.join(updates)} WHERE id IN ({placeholders})"
        c.execute(query, tuple(params + activity_ids))
        conn.commit()
        return True, f"Updated {c.rowcount} activities."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def get_aggregated_activities(minutes=10, date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        ue_sql, ue_params = _ue_clause(user_email)
        query = f"SELECT * FROM activities WHERE timestamp >= %s AND timestamp <= %s{ue_sql}"
        params = [start_time, end_time] + ue_params
        
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
        
        rows = [dict(r) for r in c.fetchall()]
        
        if not rows:
            return []
            
        aggregated = []
        current_bucket = None
        bucket_duration = minutes * 60
        
        rows.reverse()
        
        current_start_time = None
        
        for row in rows:
            ts = datetime.datetime.strptime(row['timestamp'][:19], '%Y-%m-%d %H:%M:%S')
            
            if current_start_time is None:
                current_start_time = ts
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
            
            if ts < current_bucket['end_time']:
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
                aggregated.append(finalize_bucket(current_bucket))
                
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
    finally:
        conn.close()

def get_summarized_logs(date_str=None, app_filter=None, title_filter=None, client_filter=None, category_filter=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        ue_sql, ue_params = _ue_clause(user_email)
        query_where = f"WHERE timestamp >= %s AND timestamp <= %s{ue_sql}"
        params = [start_time, end_time] + ue_params
        
        if app_filter:
            query_where += " AND app_name ILIKE %s"
            params.append(f"%{app_filter}%")
        if title_filter:
            query_where += " AND window_title ILIKE %s"
            params.append(f"%{title_filter}%")
        if client_filter:
            query_where += " AND client = %s"
            params.append(client_filter)
        if category_filter is not None:
            if category_filter == "0" or category_filter == 0:
                query_where += " AND (category_id IS NULL OR category_id = 0)"
            else:
                query_where += " AND category_id = %s"
                params.append(category_filter)
            
        query = f'''
            SELECT 
                app_name, 
                window_title, 
                category_id, 
                client,
                SUM(duration) as total_duration,
                MAX(timestamp) as last_timestamp,
                STRING_AGG(id::text, ',') as ids
            FROM activities 
            {query_where}
            GROUP BY app_name, window_title, category_id, client
            ORDER BY total_duration DESC
        '''
        
        c.execute(query, tuple(params))
        
        rows = [dict(r) for r in c.fetchall()]
        
        for r in rows:
            if r['ids']:
                r['ids'] = [int(i) for i in r['ids'].split(',')]
            else:
                r['ids'] = []
                
        return rows
    finally:
        conn.close()

def finalize_bucket(bucket):
    dominant_app = max(bucket['apps'].items(), key=lambda x: x[1])[0] if bucket['apps'] else "Unknown"
    dominant_title = max(bucket['titles'].items(), key=lambda x: x[1])[0] if bucket['titles'] else "Unknown"
    dominant_client = max(bucket['client_counts'].items(), key=lambda x: x[1])[0] if bucket['client_counts'] else "Unassigned"
    
    return {
        'timestamp': bucket['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
        'app_name': dominant_app,
        'window_title': dominant_title, 
        'client': dominant_client,
        'duration': bucket['total_duration'], 
        'count': len(bucket['ids']),
        'ids': bucket['ids'] 
    }

def get_score_stats(date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        c.execute('''
            SELECT a.duration, c.name as category, c.is_focus 
            FROM activities a
            LEFT JOIN categories c ON a.category_id = c.id
            WHERE a.timestamp >= %s AND a.timestamp <= %s
        ''', (start_time, end_time))
        
        rows = [dict(r) for r in c.fetchall()]
        
        c.execute("SELECT MIN(timestamp) FROM activities WHERE timestamp >= %s AND timestamp <= %s", (start_time, end_time))
        first_activity_ts = c.fetchone()['min']
        
        if not rows or not first_activity_ts:
            return {
                'focus': {'time': 0, 'pct': 0},
                'meeting': {'time': 0, 'pct': 0},
                'break': {'time': 0, 'pct': 0},
                'total_elapsed': 0
            }
            
        start_dt = datetime.datetime.strptime(first_activity_ts[:19], '%Y-%m-%d %H:%M:%S')
        now_dt = datetime.datetime.now()
        total_elapsed = (now_dt - start_dt).total_seconds()
        
        focus_time = 0
        meeting_time = 0
        active_time = 0
        
        comm_categories = ['Collaboration']
        
        for r in rows:
            duration = r['duration']
            active_time += duration
            
            if r['is_focus']:
                focus_time += duration
                
            cat_name = r['category']
            if cat_name in comm_categories:
                meeting_time += duration
                
        break_time = max(0, total_elapsed - active_time)
        denom = max(1, total_elapsed)
        
        return {
            'focus': {'time': int(focus_time), 'pct': round((focus_time / denom) * 100)},
            'meeting': {'time': int(meeting_time), 'pct': round((meeting_time / denom) * 100)},
            'break': {'time': int(break_time), 'pct': round((break_time / denom) * 100)},
            'total_elapsed': int(total_elapsed)
        }
    finally:
        conn.close()

def get_timeline_stats(date_str=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"
        
        c.execute('''
            SELECT a.duration, a.timestamp, c.name as category, c.is_focus
            FROM activities a
            LEFT JOIN categories c ON a.category_id = c.id
            WHERE a.timestamp >= %s AND a.timestamp <= %s
            ORDER BY a.timestamp ASC
        ''', (start_time, end_time))
        
        rows = [dict(r) for r in c.fetchall()]
        
        start_h = 8
        end_h = 22
        
        if rows:
            first_h = datetime.datetime.strptime(rows[0]['timestamp'][:19], '%Y-%m-%d %H:%M:%S').hour
            last_h = datetime.datetime.strptime(rows[-1]['timestamp'][:19], '%Y-%m-%d %H:%M:%S').hour
            start_h = min(start_h, first_h)
            end_h = max(end_h, last_h)

        hourly_data = {}

        for h in range(start_h, end_h + 1):
            h_str = f"{h:02d}:00"
            label = datetime.time(h % 24).strftime('%I %p').lstrip('0')
            hourly_data[h] = {'hour': label, 'focus': 0, 'comms': 0, 'total': 0}

        comm_categories = ['Collaboration']

        for r in rows:
            dt = datetime.datetime.strptime(r['timestamp'][:19], '%Y-%m-%d %H:%M:%S')
            h = dt.hour
            if h not in hourly_data: continue
            
            dur = r['duration']
            if r['is_focus']:
                hourly_data[h]['focus'] += dur
            elif r['category'] in comm_categories:
                hourly_data[h]['comms'] += dur
            hourly_data[h]['total'] += dur

        return [hourly_data[h] for h in sorted(hourly_data.keys())]
    finally:
        conn.close()

def get_current_session_info(date_str=None, user_email=None):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)

        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')
        start_time = f"{date_str} 00:00:00"
        end_time = f"{date_str} 23:59:59"

        ue_sql, ue_params = _ue_clause(user_email)
        c.execute(f'''
            SELECT timestamp FROM activities
            WHERE timestamp >= %s AND timestamp <= %s{ue_sql}
            ORDER BY timestamp ASC
        ''', [start_time, end_time] + ue_params)
        
        rows = c.fetchall()
        
        if not rows:
            return None
            
        gap_threshold = datetime.timedelta(minutes=5)
        session_start = rows[0]['timestamp']
        
        for i in range(1, len(rows)):
            prev_ts = datetime.datetime.strptime(rows[i-1]['timestamp'][:19], '%Y-%m-%d %H:%M:%S')
            curr_ts = datetime.datetime.strptime(rows[i]['timestamp'][:19], '%Y-%m-%d %H:%M:%S')
            
            if (curr_ts - prev_ts) > gap_threshold:
                session_start = rows[i]['timestamp']
                
        return session_start
    finally:
        conn.close()

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
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    ref_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    
    result = []
    for i in range(6, -1, -1):
        d_dt = ref_dt - datetime.timedelta(days=i)
        d_str = d_dt.strftime('%Y-%m-%d')
        
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


# ── Monthly aggregation functions ──────────────────────────────────────────────

def get_monthly_summary_stats(date_str=None, user_email=None):
    """Aggregate summary stats for the entire calendar month containing date_str."""
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if not date_str:
            date_str = datetime.datetime.now().strftime('%Y-%m-%d')

        ref_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        year, month = ref_dt.year, ref_dt.month
        last_day = calendar.monthrange(year, month)[1]

        start_time = f'{year}-{month:02d}-01 00:00:00'
        end_time   = f'{year}-{month:02d}-{last_day:02d} 23:59:59'

        ue_sql,   ue_params   = _ue_clause(user_email, alias='')
        ue_sql_a, ue_params_a = _ue_clause(user_email, alias='a')

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
            'by_category': by_category,
        }
    finally:
        conn.close()


def get_monthly_score_stats(date_str=None):
    """Aggregate focus/meeting/break scores for the full calendar month."""
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')

    ref_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    year, month = ref_dt.year, ref_dt.month
    num_days = calendar.monthrange(year, month)[1]

    total_focus = 0
    total_meeting = 0
    total_break = 0
    total_elapsed = 0

    for day in range(1, num_days + 1):
        d_str = f'{year}-{month:02d}-{day:02d}'
        day_stats = get_score_stats(d_str)
        total_focus   += day_stats['focus']['time']
        total_meeting += day_stats['meeting']['time']
        total_break   += day_stats['break']['time']
        total_elapsed += day_stats['total_elapsed']

    denom = max(1, total_elapsed)
    return {
        'focus':   {'time': int(total_focus),   'pct': round((total_focus   / denom) * 100)},
        'meeting': {'time': int(total_meeting), 'pct': round((total_meeting / denom) * 100)},
        'break':   {'time': int(total_break),   'pct': round((total_break   / denom) * 100)},
        'total_elapsed': int(total_elapsed)
    }


def get_monthly_timeline_stats(date_str=None):
    """Return one bar per day for the full calendar month (day-of-month as label)."""
    if not date_str:
        date_str = datetime.datetime.now().strftime('%Y-%m-%d')

    ref_dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    year, month = ref_dt.year, ref_dt.month
    num_days = calendar.monthrange(year, month)[1]

    result = []
    for day in range(1, num_days + 1):
        d_dt  = datetime.datetime(year, month, day)
        d_str = d_dt.strftime('%Y-%m-%d')

        day_timeline = get_timeline_stats(d_str)

        total_focus = sum(h['focus'] for h in day_timeline)
        total_comms = sum(h['comms'] for h in day_timeline)
        total_all   = sum(h['total'] for h in day_timeline)

        result.append({
            'hour':      str(day),       # day-of-month as label
            'focus':     total_focus,
            'comms':     total_comms,
            'total':     total_all,
            'date_full': d_str
        })

    return result


def get_team_summary(member_emails, start_date, end_date):
    if not member_emails:
        return {'members': [], 'by_client': [], 'by_category': [], 'totals': {'total_time': 0, 'billable_time': 0, 'non_billable_time': 0}}

    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)

        start_time = f"{start_date} 00:00:00"
        end_time = f"{end_date} 23:59:59"

        primary_email = member_emails[0]
        placeholders = ','.join('%s' for _ in member_emails)

        c.execute(f'''
            SELECT
                a.id, a.timestamp, a.app_name, a.window_title, a.url_or_filename,
                CASE
                    WHEN a.chrome_profile IS NULL OR TRIM(a.chrome_profile) = ''
                    THEN %s
                    ELSE a.chrome_profile
                END as chrome_profile,
                a.client, a.duration,
                a.category_id,
                COALESCE(cat.name, 'Uncategorized') as category_name,
                COALESCE(cat.color, '#94a3b8') as category_color,
                COALESCE(cat.is_focus, FALSE) as is_focus,
                CASE WHEN COALESCE(cat.name, '') IN ('Collaboration', 'Meeting', 'Communication') THEN 1 ELSE 0 END as is_meeting,
                CASE WHEN (a.client IS NOT NULL AND a.client != '' AND a.client != 'Unassigned') THEN 1 ELSE 0 END as is_billable
            FROM activities a
            LEFT JOIN categories cat ON a.category_id = cat.id
            WHERE a.timestamp >= %s AND a.timestamp <= %s
              AND (
                  (a.chrome_profile IS NULL OR TRIM(a.chrome_profile) = '')
                  OR a.chrome_profile IN ({placeholders})
              )
            ORDER BY a.timestamp DESC
        ''', [primary_email, start_time, end_time] + member_emails)

        rows = [dict(r) for r in c.fetchall()]

        member_stats = {email: {
            'total_time': 0, 'billable_time': 0, 'non_billable_time': 0,
            'focus_time': 0, 'meeting_time': 0,
            'by_client': {}, 'by_category': {}
        } for email in member_emails}

        client_totals = {}  
        category_totals = {}  
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

            ms['by_client'][client] = ms['by_client'].get(client, 0) + dur
            ms['by_category'][cat] = ms['by_category'].get(cat, 0) + dur

            if client not in client_totals:
                client_totals[client] = {'total_time': 0, 'billable_time': 0, 'non_billable_time': 0, 'members': {}}
            client_totals[client]['total_time'] += dur
            if billable:
                client_totals[client]['billable_time'] += dur
            else:
                client_totals[client]['non_billable_time'] += dur
            client_totals[client]['members'][email] = client_totals[client]['members'].get(email, 0) + dur

            if cat not in category_totals:
                category_totals[cat] = {
                    'color': r['category_color'], 'is_billable': billable,
                    'total_time': 0, 'members': {}
                }
            category_totals[cat]['total_time'] += dur
            category_totals[cat]['members'][email] = category_totals[cat]['members'].get(email, 0) + dur

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
    finally:
        conn.close()

def get_member_detail(member_email, start_date, end_date):
    conn = get_db_connection()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        
        start_time = f"{start_date} 00:00:00"
        end_time = f"{end_date} 23:59:59"
        
        c.execute('''
            SELECT a.*, c.name as category_name, c.color as category_color, c.is_focus
            FROM activities a
            LEFT JOIN categories c ON a.category_id = c.id
            WHERE LOWER(a.user_email) = LOWER(%s)
            AND a.timestamp >= %s AND a.timestamp <= %s
            ORDER BY a.timestamp DESC
        ''', (member_email, start_time, end_time))
        
        rows = [dict(r) for r in c.fetchall()]
        
        by_client = {}
        by_category = {}
        by_app = {}
        total_time = 0
        focus_time = 0
        
        for r in rows:
            dur = r['duration'] or 0
            client = r['client'] or 'Unassigned'
            cat = r['category_name'] or 'Uncategorized'
            app = r['app_name']
            
            total_time += dur
            if r['is_focus']: focus_time += dur
            
            by_client[client] = by_client.get(client, 0) + dur
            by_category[cat] = by_category.get(cat, 0) + dur
            by_app[app] = by_app.get(app, 0) + dur
            
        c_list = sorted([{'name': k, 'time': v} for k,v in by_client.items()], key=lambda x: -x['time'])
        cat_list = sorted([{'name': k, 'time': v} for k,v in by_category.items()], key=lambda x: -x['time'])
        app_list = sorted([{'name': k, 'time': v} for k,v in by_app.items()], key=lambda x: -x['time'])
        
        return {
            'email': member_email,
            'total_time': total_time,
            'focus_time': focus_time,
            'by_client': c_list,
            'by_category': cat_list,
            'by_app': app_list,
            'activities': rows[:200]
        }
    finally:
        conn.close()
