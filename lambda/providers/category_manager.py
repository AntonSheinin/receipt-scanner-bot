"""
    Category Manager for reading and managing categories/subcategories taxonomy
"""

import json
import os
from pathlib import Path


class CategoryManager:
    """Manager for category operations using categories.json"""

    def __init__(self, taxonomy_file_path: str = "utils/categories.json"):
        self.taxonomy_file_path = taxonomy_file_path
        self.taxonomy = self._load_taxonomy()
        self._flat_subcategories = self._build_flat_subcategories()

    def _load_taxonomy(self) -> dict:
        """Load taxonomy from JSON file."""
        try:
            # Resolve file path relative to this file
            taxonomy_path = Path(__file__).resolve().parents[2] / self.taxonomy_file_path

            # Fallback to current working directory if not found
            if not taxonomy_path.exists():
                taxonomy_path = Path(self.taxonomy_file_path).resolve()

            with taxonomy_path.open("r", encoding="utf-8") as f:
                return json.load(f)

        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to load taxonomy from {taxonomy_path}") from e

    def _build_flat_subcategories(self) -> dict[str, str]:
        """Build flat mapping of subcategory -> category"""
        return {sub["code"]: category["code"] for category in self.taxonomy["categories"] for sub in category["subcategories"]}

    def get_all_categories(self) -> list[str]:
        """Get list of all category codes"""
        return [cat["code"] for cat in self.taxonomy["categories"]]

    def get_all_subcategories(self) -> list[str]:
        """Get list of all subcategory codes"""
        return list(self._flat_subcategories.keys())

    def get_subcategories_for_category(self, category: str) -> list[str]:
        """Get subcategories for a specific category"""
        return [sub["code"] for cat in self.taxonomy["categories"] if cat["code"] == category for sub in cat["subcategories"]]

    def get_category_from_subcategory(self, subcategory: str) -> str:
        """Get main category from subcategory"""
        return self._flat_subcategories.get(subcategory, "other")

    def get_taxonomy_json_for_llm(self) -> str:
        """Get taxonomy as JSON string for LLM"""
        return json.dumps(self.taxonomy, indent=2)

    def get_category_hebrew_name(self, category_code: str) -> str | None:
        """Get Hebrew name for category from taxonomy"""
        return next(cat["hebrew_name"] for cat in self.taxonomy["categories"] if cat["code"] == category_code)

# Global instance
category_manager = CategoryManager()
