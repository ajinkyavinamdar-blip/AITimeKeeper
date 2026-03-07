import re
from ..database import get_category_mappings
from .ai_mapper import AIMapper

class CategoryMapper:
    def __init__(self):
        self.mappings = []
        self.ai_mapper = AIMapper()
        self.reload_mappings()

    def reload_mappings(self):
        """Load mappings from the database."""
        try:
            self.mappings = get_category_mappings()
        except Exception as e:
            print(f"Error loading category mappings: {e}")
            self.mappings = []

    def resolve(self, app_name, window_title, url_or_filename):
        """
        Determine category based on activity details and loaded mappings.
        Priority:
        1. URL/Filename match
        2. Window Title match
        3. App Name match
        """
        if not self.mappings:
            return "Admin", None # Default fallback

        # Check URL/Filename mappings
        if url_or_filename:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'url':
                    if mapping['pattern_value'].lower() in url_or_filename.lower():
                        return mapping['category_name'], mapping['category_id']

        # Check Window Title mappings
        if window_title:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'title':
                    if mapping['pattern_value'].lower() in window_title.lower():
                        return mapping['category_name'], mapping['category_id']
        
        # Check App Name mappings
        if app_name:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'app':
                    if mapping['pattern_value'].lower() in app_name.lower():
                        return mapping['category_name'], mapping['category_id']

        # Heuristic Defaults
        app_lower = (app_name or "").lower()
        title_lower = (window_title or "").lower()
        url_lower = (url_or_filename or "").lower()
        
        # Combine title and URL for browser-specific smart detection
        combined_context = f"{title_lower} {url_lower}"
        is_browser = any(b in app_lower for b in ["chrome", "safari", "firefox", "browser", "edge"])

        # 1. Tech Development
        if "code" in app_lower or "studio" in app_lower or "terminal" in app_lower or "iterm" in app_lower:
             return "Tech Development", None
        if is_browser and any(k in combined_context for k in ["github", "stackoverflow", "docs.", "localhost", "127.0.0.1", "console"]):
             return "Tech Development", None

        # 2. Collaboration
        if any(k in app_lower for k in ["zoom", "meet", "teams", "slack", "discord", "outlook", "whatsapp"]):
             return "Collaboration", None
        if is_browser and any(k in combined_context for k in ["slack", "teams.microsoft", "meet.google", "zoom.us", "mail.google", "outlook"]):
             return "Collaboration", None

        # 3. AI
        if any(k in app_lower for k in ["chatgpt", "gemini", "claude", "notebooklm", "perplex"]):
             return "AI", None
        if is_browser and any(k in combined_context for k in ["chat.openai", "gemini.google", "claude.ai"]):
             return "AI", None

        # 4. Social Media & Entertainment
        if any(k in app_lower for k in ["facebook", "linkedin", "instagram", "twitter", "x.com", "pinterest", "reddit", "youtube", "netflix", "prime video", "hulu", "disney+", "twitch", "tiktok"]):
             return "Social Media", None
        if is_browser and any(k in combined_context for k in ["facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com", "reddit.com", "youtube.com", "netflix.com", "primevideo.com", "hulu.com", "disneyplus.com", "twitch.tv", "tiktok.com"]):
             return "Social Media", None

        # 5. Operations
        if any(k in app_lower for k in ["zoho", "quickbooks", "tally", "xero", "excel", "word", "powerpoint", "sheets", "docs"]):
             return "Operations", None
        if is_browser and any(k in combined_context for k in ["zoho.com", "quickbooks.intuit", "tallysolutions", "office.com", "docs.google", "sheets.google"]):
             return "Operations", None

        # 6. Fallback for Browsers
        if is_browser:
             return "Browsing", None

        # 7. AI Fallback (Gemini)
        # Attempt AI mapping if heuristics fail
        ai_suggestion, ai_cat_id = self.ai_mapper.suggest_category(app_name, window_title, url_or_filename)
        if ai_suggestion and ai_suggestion != "Uncategorized":
            return ai_suggestion, ai_cat_id

        return "Uncategorized", None
