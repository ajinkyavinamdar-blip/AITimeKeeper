import re
from ..database import get_category_mappings, get_categories
from .ai_mapper import AIMapper

class CategoryMapper:
    def __init__(self):
        self.mappings = []
        self._cat_name_to_id = {}   # cache: category name → id
        self.ai_mapper = AIMapper()
        self.reload_mappings()

    def reload_mappings(self):
        """Load mappings from the database."""
        try:
            self.mappings = get_category_mappings()
        except Exception as e:
            print(f"Error loading category mappings: {e}")
            self.mappings = []
        # Build name→id lookup from categories table
        try:
            for cat in get_categories():
                self._cat_name_to_id[cat['name']] = cat['id']
        except Exception:
            pass

    def _resolve_id(self, category_name):
        """Return the category_id for a given name, or None."""
        return self._cat_name_to_id.get(category_name)

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
        # These return (category_name, category_id) — the id is looked up from
        # the categories table so the ingest endpoint actually assigns it.
        app_lower = (app_name or "").lower()
        title_lower = (window_title or "").lower()
        url_lower = (url_or_filename or "").lower()
        combined = f"{title_lower} {url_lower}"
        is_browser = any(b in app_lower for b in ["chrome", "safari", "firefox", "browser", "edge"])

        def _h(name):
            """Return (name, id) for a heuristic match."""
            return name, self._resolve_id(name)

        # 1. AI tools
        if any(k in app_lower for k in ["chatgpt", "gemini", "claude", "notebooklm", "perplex", "copilot"]):
            return _h("AI")
        if is_browser and any(k in combined for k in [
            "chat.openai", "gemini.google", "claude.ai", "perplexity.ai",
            "notebooklm", "copilot.microsoft", "deepseek",
        ]):
            return _h("AI")

        # 2. Social Media & Entertainment
        if is_browser and any(k in combined for k in [
            "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
            "youtube.com", "reddit.com", "tiktok.com", "netflix.com", "primevideo.com",
            "hulu.com", "disneyplus.com", "twitch.tv", "pinterest.com", "snapchat.com",
        ]):
            return _h("Social Media")
        if any(k in app_lower for k in ["facebook", "instagram", "twitter", "youtube", "netflix", "twitch"]):
            return _h("Social Media")

        # 3. Collaboration / Meetings
        if any(k in app_lower for k in ["zoom", "teams", "slack", "outlook", "discord", "whatsapp", "webex", "lark"]):
            return _h("Collaboration")
        if is_browser and any(k in combined for k in [
            "teams.microsoft", "zoom.us", "meet.google", "mail.google",
            "outlook.live", "outlook.office", "slack.com", "calendly.com",
        ]):
            return _h("Collaboration")

        # 4. Operations / Finance / Accounting
        if any(k in app_lower for k in [
            "zoho", "quickbooks", "tally", "xero", "excel", "numbers",
            "freshbooks", "sage", "myob", "taxpower",
        ]):
            return _h("Operations")
        if is_browser and any(k in combined for k in [
            # Zoho (global + India)
            "zoho.com", "zoho.in",
            # Accounting / ERP
            "quickbooks.intuit", "tallysolutions", "tallyprime.com", "xero.com",
            "sheets.google", "office.com/excel", "freshbooks.com",
            "sage.com", "myob.com", "wave.com", "freeagent.com",
            "kashoo.com", "zetran.com", "dext.com", "hubdoc.com",
            "netsuite.com", "sap.com", "oracle.com/financials",
            "workday.com", "busy.in",
            # Expense / AP-AR
            "bill.com", "melio.com", "ramp.com", "brex.com",
            "expensify.com", "concur.com",
            "happay.com", "fyle.in", "zaggle.in",
            # Payroll — global + India
            "gusto.com", "rippling.com", "adp.com", "paychex.com",
            "paylocity.com", "paycom.com",
            "greythr.com", "keka.com", "darwinbox.com", "sumhr.com",
            # Tax — India
            "gst.gov.in", "incometax.gov.in", "mca.gov.in",
            "tdscpc.gov.in", "traces.gov.in", "einvoice.gst.gov.in",
            "cleartax.in", "taxbuddy.com", "winman.in", "saral.pro",
            "tdsman.com", "mastersindia.co",
            # Tax — Global
            "irs.gov", "hmrc.gov.uk",
            "taxjar.com", "avalara.com", "vertex.com",
            "caseware.com", "wolterskluwer.com",
            "thomsonreuters.com/tax", "cch.com",
            # Practice Management
            "karbon.com", "canopy.com", "jetpackworkflow.com",
            "practiceics.com", "taxdome.com",
            "ignitionapp.com", "proposify.com",
            # Payments — global + India
            "stripe.com/dashboard", "paypal.com/merchant",
            "gocardless.com", "razorpay.com",
            "paytm.com", "phonepe.com", "cashfree.com", "instamojo.com",
            # Indian banking
            "onlinesbi.sbi", "hdfcbank.com", "icicibank.com",
            "axisbank.com", "kotak.com", "yesbank.in", "idfcfirstbank.com",
        ]):
            return _h("Operations")

        # 5. Research
        if is_browser and any(k in combined for k in [
            "scholar.google", "wikipedia.org", "medium.com", "substack.com",
            "news.google", "arxiv.org", "pubmed", "ssrn.com",
        ]):
            return _h("Research")

        # 6. Self Improvement
        if is_browser and any(k in combined for k in [
            "coursera.org", "udemy.com", "linkedin.com/learning",
            "skillshare.com", "khanacademy.org", "audible.com",
            "pluralsight.com", "edx.org", "masterclass.com",
        ]):
            return _h("Self Improvement")

        # 7. Tech Development
        if any(k in app_lower for k in ["code", "studio", "terminal", "iterm", "xcode", "cursor", "windsurf"]):
            return _h("Tech Development")
        if is_browser and any(k in combined for k in ["github.com", "stackoverflow.com", "localhost", "127.0.0.1"]):
            return _h("Tech Development")

        # 8. Documentation
        if any(k in app_lower for k in ["word", "pages", "notion", "obsidian", "bear", "typora"]):
            return _h("Documentation")
        if is_browser and any(k in combined for k in ["notion.so", "docs.google.com", "confluence"]):
            return _h("Documentation")

        # 9. Generic browser fallback
        if is_browser:
            return _h("Browsing")

        # 10. AI fallback (Gemini) for anything not matched by heuristics
        ai_suggestion, ai_cat_id = self.ai_mapper.suggest_category(app_name, window_title, url_or_filename)
        if ai_suggestion and ai_suggestion != "Uncategorized":
            return ai_suggestion, ai_cat_id or self._resolve_id(ai_suggestion)

        return "Uncategorized", None
