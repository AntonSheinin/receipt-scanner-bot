"""
Category Manager for reading and managing retail taxonomy from JSON file
"""
import json
import os
from typing import Dict, List

class CategoryManager:
    """Manager for category operations using categories.json"""

    def __init__(self, taxonomy_file_path: str = "categories.json"):
        self.taxonomy_file_path = taxonomy_file_path
        self.taxonomy = self._load_taxonomy()
        self._flat_subcategories = self._build_flat_subcategories()

    def _load_taxonomy(self) -> Dict | None:
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
            return None

    def _build_flat_subcategories(self) -> Dict[str, str]:
        """Build flat mapping of subcategory -> category"""
        flat_map = {}
        for category in self.taxonomy.get("categories", []):
            category_code = category.get("code", "other")
            for subcategory in category.get("subcategories", []):
                subcat_code = subcategory.get("code", "miscellaneous")
                flat_map[subcat_code] = category_code
        return flat_map

    def get_all_categories(self) -> List[str]:
        """Get list of all category codes"""
        return [cat.get("code", "other") for cat in self.taxonomy.get("categories", [])]

    def get_all_subcategories(self) -> List[str]:
        """Get list of all subcategory codes"""
        return list(self._flat_subcategories.keys())

    def get_subcategories_for_category(self, category: str) -> List[str]:
        """Get subcategories for a specific category"""
        for cat in self.taxonomy.get("categories", []):
            if cat.get("code") == category:
                return [sub.get("code", "miscellaneous") for sub in cat.get("subcategories", [])]
        return []

    def get_category_from_subcategory(self, subcategory: str) -> str:
        """Get main category from subcategory"""
        return self._flat_subcategories.get(subcategory, "other")

    def get_taxonomy_json_for_llm(self) -> str:
        """Get taxonomy as JSON string for LLM"""
        return json.dumps(self.taxonomy, indent=2)

    def get_categories_list_for_llm(self) -> str:
        """Generate simple categories list for query prompts"""
        return ", ".join(self.get_all_categories())

    def get_subcategories_list_for_llm(self) -> str:
        """Generate simple subcategories list for query prompts"""
        return ", ".join(self.get_all_subcategories())

# Global instance
category_manager = CategoryManager()
