"""Outing, leisure, and dining research service."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from app.integrations.mocks import MockWebSearchClient


CUISINE_PATTERNS = {
    "italian": ["italian", "pasta", "pizza", "trattoria", "osteria"],
    "sushi": ["sushi", "japanese", "ramen", "sashimi", "omakase"],
    "mexican": ["mexican", "tacos", "burritos", "taqueria"],
    "coffee": ["coffee", "cafe", "espresso", "latte", "roasters"],
    "american": ["american", "burger", "grill", "steak", "diner"],
    "french": ["french", "bistro", "pastry"],
    "chinese": ["chinese", "dim sum", "noodles", "dumplings"],
    "indian": ["indian", "curry", "tandoori"],
    "thai": ["thai", "pad thai"],
}

ACTIVITY_PATTERNS = {
    "outdoor": ["outdoor", "park", "walk", "promenade", "hiking", "waterfront", "beach"],
    "cultural": ["museum", "gallery", "art", "theater", "sculpture", "history"],
    "dining": ["restaurant", "dinner", "lunch", "breakfast", "brunch", "eat", "food"],
    "cafe": ["coffee", "cafe", "work with wifi", "wifi"],
}

LOCATION_KEYWORDS = [
    "downtown",
    "seattle",
    "brooklyn",
    "capitol hill",
    "waterfront",
    "bellevue",
    "manhattan",
    "ballard",
]

BUDGET_PATTERNS = {
    "$": ["cheap", "inexpensive", "budget", "$"],
    "$$": ["moderate", "reasonable", "$$"],
    "$$$": ["upscale", "nice", "$$$"],
    "$$$$": ["fine dining", "luxury", "expensive", "omakase", "$$$$"],
}


class SearchService:
    """Service providing structured leisure, dining, and outing recommendations."""

    def __init__(self, search_client: Optional[MockWebSearchClient] = None) -> None:
        self.search_client = search_client or MockWebSearchClient()

    def extract_parameters(self, text: str) -> Dict[str, Any]:
        """Extract cuisine, activity, location, and budget constraints from text."""
        text_lower = text.lower()
        extracted: Dict[str, Any] = {
            "cuisine": None,
            "activity": "dining",
            "location": None,
            "budget": None,
            "amenities": [],
        }

        # 1. Cuisine extraction
        for cuisine, keywords in CUISINE_PATTERNS.items():
            if any(re.search(r"\b" + re.escape(kw) + r"\b", text_lower) for kw in keywords):
                extracted["cuisine"] = cuisine.capitalize()
                break

        # 2. Amenity extraction
        if "wifi" in text_lower:
            extracted["amenities"].append("wifi")
        if "outdoor seating" in text_lower or "patio" in text_lower or ("outdoor" in text_lower and ("restaurant" in text_lower or extracted["cuisine"])):
            extracted["amenities"].append("outdoor seating")

        # 3. Activity extraction
        dining_kws = ["restaurant", "restaurants", "dinner", "lunch", "breakfast", "brunch", "eat", "food"]
        if extracted["cuisine"] or any(re.search(r"\b" + re.escape(dkw) + r"\b", text_lower) for dkw in dining_kws):
            extracted["activity"] = "dining"
        else:
            for act in ["outdoor", "cultural", "cafe"]:
                keywords = ACTIVITY_PATTERNS[act]
                if any(re.search(r"\b" + re.escape(kw) + r"\b", text_lower) for kw in keywords):
                    extracted["activity"] = act
                    break

        # 4. Location extraction
        for loc in LOCATION_KEYWORDS:
            if re.search(r"\b" + re.escape(loc) + r"\b", text_lower):
                extracted["location"] = loc.title()
                break

        # 5. Budget extraction
        for tier, keywords in BUDGET_PATTERNS.items():
            if any(kw in text_lower for kw in keywords):
                extracted["budget"] = tier
                break

        return extracted

    def search_outings(
        self,
        user_id: str,
        query: str,
        location: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search outings matching user query and location."""
        params = self.extract_parameters(query)
        effective_location = location or params["location"]

        results = self.search_client.search(
            query=query,
            location=effective_location,
            category=params["activity"] if params["activity"] != "dining" else params["cuisine"],
            budget=params["budget"],
        )

        # Filter by amenity if specified
        if "wifi" in params.get("amenities", []):
            wifi_matches = [r for r in results if "wifi" in r.get("amenities", [])]
            if wifi_matches:
                results = wifi_matches

        return results

    def format_recommendations_markdown(self, recommendations: List[Dict[str, Any]]) -> str:
        """Format recommendations as conversational Markdown."""
        if not recommendations:
            return "No places found matching your criteria. Try widening your location or search terms."

        lines = ["Here are top curated recommendations for you:\n"]
        for i, place in enumerate(recommendations, 1):
            name = place.get("name", "Unknown")
            rating = place.get("rating", 4.5)
            price = place.get("price_tier", "$$")
            address = place.get("address", "")
            desc = place.get("description", "")
            amenities = ", ".join(place.get("amenities", []))

            lines.append(f"{i}. **{name}** ({rating} ⭐ | {price})")
            if address:
                lines.append(f"   📍 {address}")
            if desc:
                lines.append(f"   _{desc}_")
            if amenities:
                lines.append(f"   ✨ Features: {amenities}")
            lines.append("")

        return "\n".join(lines).strip()
