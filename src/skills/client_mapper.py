import re
from ..database import get_mappings

class ClientMapper:
    def __init__(self):
        self.mappings = []
        self.reload_mappings()

    def reload_mappings(self):
        """Load mappings from the database."""
        try:
            self.mappings = get_mappings()
        except Exception as e:
            print(f"Error loading client mappings: {e}")
            self.mappings = []

    def resolve(self, app_name, window_title, url_or_filename):
        """
        Determine client based on activity details and loaded mappings.
        Priority:
        1. URL/Filename match
        2. Window Title match
        3. App Name match
        """
        if not self.mappings:
            return None

        # Check URL/Filename mappings
        if url_or_filename:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'url':
                    if mapping['pattern_value'].lower() in url_or_filename.lower():
                        return mapping['client_name']

        # Check Window Title mappings
        if window_title:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'title':
                    if mapping['pattern_value'].lower() in window_title.lower():
                        return mapping['client_name']
        
        # Check App Name mappings
        if app_name:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'app':
                    if mapping['pattern_value'].lower() in app_name.lower():
                        return mapping['client_name']

        # Legacy Regex Fallback (if kept for specific hardcoded logic)
        # "2026_Audit_[ClientName]" -> ClientName
        if window_title:
             match = re.search(r'2026_Audit_(\w+)', window_title, re.IGNORECASE)
             if match:
                 return match.group(1)
        if url_or_filename:
             match = re.search(r'2026_Audit_(\w+)', url_or_filename, re.IGNORECASE)
             if match:
                 return match.group(1)

        return None

    def get_client(self, filename: str) -> str:
        # Deprecated adapter for backward compatibility if needed, 
        # but we will update agent.py to use resolve()
        return self.resolve(None, None, filename) or "Unassigned"

