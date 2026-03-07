from dataclasses import dataclass
from typing import List, Dict
import datetime

@dataclass
class Session:
    start_time: str
    end_time: str
    app_name: str
    window_title: str
    url_or_filename: str
    duration: float

class ContextMerger:
    def merge_activities(self, raw_activities: List[tuple]) -> List[Session]:
        """
        raw_activities: List of tuples from DB (id, timestamp, app, title, url, profile, duration)
        Returns: List of Session objects
        """
        sessions = []
        if not raw_activities:
            return sessions

        current_session = None

        # Sort by timestamp just in case
        # raw_activities should be sorted by time asc for this to work well
        # But the DB query might return desc. Let's assume we handle sorting before calling this.
        
        for row in raw_activities:
            # Row mapping based on database.py schema:
            # 0: id, 1: timestamp, 2: app_name, 3: window_title, 4: url, 5: profile, 6: duration
            timestamp_str = row[1]
            app_name = row[2]
            title = row[3]
            url = row[4]
            # profile = row[5] # unused for now
            duration = row[6]

            if current_session is None:
                current_session = Session(
                    start_time=timestamp_str,
                    end_time=timestamp_str,
                    app_name=app_name,
                    window_title=title,
                    url_or_filename=url,
                    duration=duration
                )
            else:
                # Check continuity
                # Simple logic: same app, same title (or same URL if browser)
                matches = (
                    app_name == current_session.app_name and
                    (url == current_session.url_or_filename if url else title == current_session.window_title)
                )

                if matches:
                    current_session.duration += duration
                    current_session.end_time = timestamp_str
                else:
                    sessions.append(current_session)
                    current_session = Session(
                        start_time=timestamp_str,
                        end_time=timestamp_str,
                        app_name=app_name,
                        window_title=title,
                        url_or_filename=url,
                        duration=duration
                    )
        
        if current_session:
            sessions.append(current_session)

        return sessions
