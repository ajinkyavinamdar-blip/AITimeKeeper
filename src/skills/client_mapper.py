import re
from ..database import get_mappings, get_client_by_zoho_org_id

# Zoho Books URL patterns — org ID appears right after /app/ in the path
# e.g. https://books.zoho.in/app/738291234#/dashboard
#      https://books.zoho.com/app/123456789/
ZOHO_BOOK_DOMAINS = ('books.zoho.in', 'books.zoho.com', 'books.zoho.eu',
                     'books.zoho.com.au', 'books.zoho.jp')
ZOHO_ORG_RE = re.compile(r'/app/(\d{6,})', re.IGNORECASE)


def extract_zoho_org_id(url: str):
    """Extract Zoho Books organisation ID from a URL, or return None."""
    if not url:
        return None
    url_lower = url.lower()
    if not any(d in url_lower for d in ZOHO_BOOK_DOMAINS):
        return None
    m = ZOHO_ORG_RE.search(url)
    return m.group(1) if m else None


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
        0. Zoho Org ID (highest — precise org-level match)
        1. URL/Filename pattern match
        2. Window Title match
        3. App Name match
        """
        # 0. Zoho Org ID — most precise, always checked first
        org_id = extract_zoho_org_id(url_or_filename or '')
        if org_id:
            client = get_client_by_zoho_org_id(org_id)
            if client:
                return client

        if not self.mappings:
            return None

        # 1. URL/Filename pattern match
        if url_or_filename:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'url':
                    if mapping['pattern_value'].lower() in url_or_filename.lower():
                        return mapping['client_name']

        # 2. Window Title match
        if window_title:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'title':
                    if mapping['pattern_value'].lower() in window_title.lower():
                        return mapping['client_name']

        # 3. App Name match
        if app_name:
            for mapping in self.mappings:
                if mapping['pattern_type'] == 'app':
                    if mapping['pattern_value'].lower() in app_name.lower():
                        return mapping['client_name']

        # Legacy: "2026_Audit_[ClientName]" filename pattern
        for text in (window_title, url_or_filename):
            if text:
                match = re.search(r'2026_Audit_(\w+)', text, re.IGNORECASE)
                if match:
                    return match.group(1)

        return None

    def get_client(self, filename: str) -> str:
        return self.resolve(None, None, filename) or "Unassigned"
