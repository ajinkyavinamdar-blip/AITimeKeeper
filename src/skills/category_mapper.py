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

        # ── Heuristic fallbacks (run when no DB rule matched) ─────────────────
        app_lower = (app_name or "").lower()
        title_lower = (window_title or "").lower()
        url_lower = (url_or_filename or "").lower()
        combined = f"{title_lower} {url_lower}"
        is_browser = any(b in app_lower for b in ["chrome", "safari", "firefox", "browser", "edge"])

        # 1. AI tools
        if any(k in app_lower for k in ["chatgpt", "gemini", "claude", "notebooklm", "perplex"]):
            return "AI", None
        if is_browser and any(k in combined for k in ["chat.openai", "gemini.google", "claude.ai", "perplexity.ai", "notebooklm"]):
            return "AI", None

        # 2. Social Media & Entertainment (URL-first — almost all are browser-only)
        if is_browser and any(k in combined for k in [
            "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
            "youtube.com", "reddit.com", "tiktok.com", "netflix.com", "primevideo.com",
            "hulu.com", "disneyplus.com", "twitch.tv", "pinterest.com",
        ]):
            return "Social Media", None
        if any(k in app_lower for k in ["facebook", "instagram", "twitter", "youtube", "netflix", "twitch"]):
            return "Social Media", None

        # 3. Collaboration / Meetings
        if any(k in app_lower for k in ["zoom", "teams", "slack", "outlook", "discord", "whatsapp", "webex"]):
            return "Collaboration", None
        if is_browser and any(k in combined for k in [
            "teams.microsoft", "zoom.us", "meet.google", "mail.google",
            "outlook.live", "outlook.office", "slack.com",
        ]):
            return "Collaboration", None

        # 4. Operations / Finance
        if any(k in app_lower for k in ["zoho", "quickbooks", "tally", "xero", "excel", "numbers"]):
            return "Operations", None
        if is_browser and any(k in combined for k in [
            "zoho.com", "quickbooks.intuit", "tallysolutions", "xero.com",
            "sheets.google", "office.com/excel",
        ]):
            return "Operations", None

        # 5. Research
        if is_browser and any(k in combined for k in [
            "scholar.google", "wikipedia.org", "medium.com", "substack.com",
            "news.google", "arxiv.org", "pubmed",
        ]):
            return "Research", None

        # 6. Self Improvement
        if is_browser and any(k in combined for k in [
            "coursera.org", "udemy.com", "linkedin.com/learning",
            "skillshare.com", "khanacademy.org", "audible.com",
        ]):
            return "Self Improvement", None

        # 7. Tech Development
        if any(k in app_lower for k in ["code", "studio", "terminal", "iterm", "xcode", "cursor", "windsurf"]):
            return "Tech Development", None
        if is_browser and any(k in combined for k in ["github.com", "stackoverflow.com", "localhost", "127.0.0.1"]):
            return "Tech Development", None

        # 8. Documentation
        if any(k in app_lower for k in ["word", "pages", "notion", "obsidian", "bear", "typora"]):
            return "Documentation", None
        if is_browser and any(k in combined for k in ["notion.so", "docs.google.com", "confluence"]):
            return "Documentation", None

        # 9. Generic browser fallback
        if is_browser:
            return "Browsing", None

        # 10. AI fallback (Gemini) for anything not matched by heuristics
        ai_suggestion, ai_cat_id = self.ai_mapper.suggest_category(app_name, window_title, url_or_filename)
        if ai_suggestion and ai_suggestion != "Uncategorized":
            return ai_suggestion, ai_cat_id

        return "Uncategorized", None
