"""
    Category Manager for reading and managing categories/subcategories taxonomy
"""

import json
import os
from typing import Dict, List


class CategoryManager:
    """Manager for category operations using categories.json"""

    def __init__(self, taxonomy_file_path: str = "utils/categories.json"):
        self.taxonomy_file_path = taxonomy_file_path
        self.taxonomy = self._load_taxonomy()
        self._flat_subcategories = self._build_flat_subcategories()

    def _load_taxonomy(self) -> Dict:
        """Load taxonomy from JSON file"""
        try:
            # Try to load from the lambda directory first
            current_dir = os.path.dirname(os.path.abspath(__file__))
            taxonomy_path = os.path.join(current_dir, "..", "..", self.taxonomy_file_path)

            # If not found, try current directory
            if not os.path.exists(taxonomy_path):
                taxonomy_path = self.taxonomy_file_path

            with open(taxonomy_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError("Failed to load taxonomy") from e

    def _build_flat_subcategories(self) -> Dict[str, str]:
        """Build flat mapping of subcategory -> category"""
        flat_map = {}
        for category in self.taxonomy["categories"]:
            category_code = category["code"]
            for subcategory in category["subcategories"]:
                subcat_code = subcategory["code"]
                flat_map[subcat_code] = category_code
        return flat_map

    def get_all_categories(self) -> List[str]:
        """Get list of all category codes"""
        return [cat["code"] for cat in self.taxonomy["categories"]]

    def get_all_subcategories(self) -> List[str]:
        """Get list of all subcategory codes"""
        return list(self._flat_subcategories.keys())

    def get_subcategories_for_category(self, category: str) -> List[str]:
        """Get subcategories for a specific category"""
        for cat in self.taxonomy["categories"]:
            if cat["code"] == category:
                return [sub["code"] for sub in cat["subcategories"]]
        return []

    def get_category_from_subcategory(self, subcategory: str) -> str:
        """Get main category from subcategory"""
        return self._flat_subcategories.get(subcategory, "other")

    def get_taxonomy_json_for_llm(self) -> str:
        """Get taxonomy as JSON string for LLM"""
        return json.dumps(self.taxonomy, indent=2)

    def _get_category_hebrew_name(self, category_code: str) -> str | None:
        """Get Hebrew name for category from taxonomy"""
        return next(cat["hebrew_name"] for cat in self.taxonomy["categories"] if cat["code"] == category_code)

# Global instance
category_manager = CategoryManager()
