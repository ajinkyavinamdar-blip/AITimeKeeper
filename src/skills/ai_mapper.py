import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai
import os
import json
from ..database import get_categories

class AIMapper:
    def __init__(self):
        # We assume the API key is in the environment
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            self.model = None
            print("Warning: GEMINI_API_KEY not found in environment. AI Mapping will be disabled.")

    def suggest_category(self, app_name, window_title, url_or_filename):
        """
        Uses Gemini to suggest a category from the existing list.
        """
        if not self.model:
            return None, None

        categories = get_categories()
        cat_names = [c['name'] for c in categories]
        
        prompt = f"""
        Given the following activity metadata from a user's computer:
        App: {app_name}
        Title: {window_title}
        URL/Path: {url_or_filename}

        Classify this activity into EXACTLY ONE of the following categories:
        {', '.join(cat_names)}

        If none fit perfectly, pick 'Uncategorized'.
        Return only the category name, nothing else.
        """

        try:
            response = self.model.generate_content(prompt)
            suggestion = response.text.strip()
            
            # Find the matching category object
            for cat in categories:
                if cat['name'].lower() == suggestion.lower():
                    return cat['name'], cat['id']
            
            return "Uncategorized", None
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            return None, None
