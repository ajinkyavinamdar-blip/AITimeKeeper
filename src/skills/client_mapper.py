import re
from ..database import get_mappings, get_client_by_zoho_org_id, get_clients

# Zoho URL patterns — org ID appears right after /app/ in the path
# e.g. https://books.zoho.in/app/738291234#/dashboard
#      https://invoice.zoho.com/app/123456789/
# Covers all Zoho products across all regional TLDs (.com, .in, .eu, .com.au, .jp)
_ZOHO_PRODUCTS = ('books', 'invoice', 'expense', 'payroll', 'people',
                  'inventory', 'subscriptions', 'practice', 'billing',
                  'crm', 'sign')
_ZOHO_TLDS = ('.zoho.com', '.zoho.in', '.zoho.eu', '.zoho.com.au', '.zoho.jp')
ZOHO_DOMAINS = tuple(f'{p}{t}' for p in _ZOHO_PRODUCTS for t in _ZOHO_TLDS)
ZOHO_ORG_RE = re.compile(r'/app/(\d{6,})', re.IGNORECASE)
# Some Zoho URLs put the org ID as a query param: ?organization_id=60000553962
ZOHO_ORG_QUERY_RE = re.compile(r'organization_id=(\d{6,})', re.IGNORECASE)


def extract_zoho_org_id(url: str):
    """Extract Zoho organisation ID from any Zoho product URL, or return None."""
    if not url:
        return None
    url_lower = url.lower()
    if not any(d in url_lower for d in ZOHO_DOMAINS):
        return None
    # Try /app/<orgid> path style first
    m = ZOHO_ORG_RE.search(url)
    if m:
        return m.group(1)
    # Try ?organization_id=<orgid> query param style
    m = ZOHO_ORG_QUERY_RE.search(url)
    return m.group(1) if m else None


def _is_zoho_url(url: str):
    """Check if URL belongs to any Zoho product."""
    if not url:
        return False
    url_lower = url.lower()
    return any(d in url_lower for d in ZOHO_DOMAINS)


# File extensions that indicate document/spreadsheet work
_DOC_EXTENSIONS = ('.xlsx', '.xls', '.xlsm', '.docx', '.doc', '.csv', '.pdf', '.pptx', '.ppt')
_DOC_EXT_RE = re.compile(r'\.(?:xlsx?|xlsm|docx?|csv|pdf|pptx?)(?:\s|$|\]|\))', re.IGNORECASE)

def _normalize(text):
    """Lowercase and strip common separators for fuzzy matching."""
    return re.sub(r'[_\-.\s]+', ' ', text.lower()).strip()

def _fuzzy_contains(haystack, needle, threshold=0.8):
    """Check if needle appears in haystack with fuzzy tolerance.
    Uses simple token overlap: if >= threshold of needle tokens are in haystack, it's a match.
    """
    needle_tokens = _normalize(needle).split()
    haystack_norm = _normalize(haystack)
    if not needle_tokens:
        return False
    # Exact substring match first (fast path)
    if _normalize(needle) in haystack_norm:
        return True
    # Token overlap for multi-word client names
    if len(needle_tokens) == 1:
        # Single word: require it as a standalone word in the haystack
        return bool(re.search(r'\b' + re.escape(needle_tokens[0]) + r'\b', haystack_norm))
    matched = sum(1 for t in needle_tokens if t in haystack_norm)
    return (matched / len(needle_tokens)) >= threshold


class ClientMapper:
    def __init__(self):
        self.mappings = []
        self._clients = []  # cached client list for fuzzy matching
        self.reload_mappings()

    def reload_mappings(self):
        """Load mappings and client list from the database."""
        try:
            self.mappings = get_mappings()
        except Exception as e:
            print(f"Error loading client mappings: {e}")
            self.mappings = []
        try:
            self._clients = get_clients()
        except Exception:
            self._clients = []

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

        # 1. URL/Filename pattern match (only if mappings exist)
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

        # 4. Zoho window title matching — when on a Zoho page but no org ID in URL,
        #    try to match client names from the window title (e.g. "... - Botspace - Microsoft Edge")
        if url_or_filename and _is_zoho_url(url_or_filename) and window_title:
            for client in sorted(self._clients, key=lambda c: len(c['name']), reverse=True):
                if len(client['name']) >= 3 and _fuzzy_contains(window_title, client['name']):
                    return client['name']

        # 5. Fuzzy filename matching for Excel/Word/PDF documents
        #    If the window title or filename looks like a document, try to match
        #    client names from the clients table against the text.
        for text in (window_title, url_or_filename):
            if text and _DOC_EXT_RE.search(text):
                # Sort clients by name length (longest first) to prefer more specific matches
                for client in sorted(self._clients, key=lambda c: len(c['name']), reverse=True):
                    if len(client['name']) >= 3 and _fuzzy_contains(text, client['name']):
                        return client['name']

        # Legacy: "2026_Audit_[ClientName]" filename pattern
        for text in (window_title, url_or_filename):
            if text:
                match = re.search(r'2026_Audit_(\w+)', text, re.IGNORECASE)
                if match:
                    return match.group(1)

        return None

    def get_client(self, filename: str) -> str:
        return self.resolve(None, None, filename) or "Unassigned"
