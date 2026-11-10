"""Outing, leisure, and dining research service."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.integrations.mocks import MockWebSearchClient

logger = logging.getLogger(__name__)


def _normalize_text(text: Optional[str]) -> str:
    """Normalize text removing diacritics and lowercasing."""
    if not text:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower().strip()


COLOMBIA_BBOX = {
    "min_lat": -4.3,
    "max_lat": 13.5,
    "min_lon": -81.8,
    "max_lon": -66.8,
}


def validate_coordinates(coordinates: Tuple[float, float]) -> None:
    """Validate latitude in [-90, 90] and longitude in [-180, 180]."""
    lat, lon = coordinates
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(
            f"Coordinates ({lat}, {lon}) out of valid range: lat in [-90, 90], lon in [-180, 180]."
        )


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
    "colombian": [
        "colombian", "colombiana", "criolla", "bandeja paisa",
        "ajiaco", "parrilla", "asado", "típica", "tipica"
    ],
}

ACTIVITY_PATTERNS = {
    "outdoor": ["outdoor", "park", "walk", "promenade", "hiking", "waterfront", "beach"],
    "cultural": ["museum", "gallery", "art", "theater", "sculpture", "history"],
    "dining": ["restaurant", "dinner", "lunch", "breakfast", "brunch", "eat", "food"],
    "cafe": ["coffee", "cafe", "work with wifi", "wifi"],
}

COLOMBIAN_SECTORS = [
    "chapinero",
    "usaquén",
    "usaquen",
    "parque 93",
    "zona g",
    "zona t",
    "la candelaria",
    "candelaria",
    "el poblado",
    "poblado",
    "laureles",
    "bogotá",
    "bogota",
    "medellín",
    "medellin",
    "cartagena",
    "cali",
    "la macarena",
    "macarena",
    "chicó",
    "chico",
    "santa bárbara",
    "santa barbara",
]

CANONICAL_SECTORS = {
    "chapinero": "Chapinero",
    "usaquen": "Usaquén",
    "usaquén": "Usaquén",
    "parque 93": "Parque 93",
    "zona g": "Zona G",
    "zona t": "Zona T",
    "la candelaria": "La Candelaria",
    "candelaria": "La Candelaria",
    "el poblado": "El Poblado",
    "poblado": "El Poblado",
    "laureles": "Laureles",
    "bogota": "Bogotá",
    "bogotá": "Bogotá",
    "medellin": "Medellín",
    "medellín": "Medellín",
    "cartagena": "Cartagena",
    "cali": "Cali",
    "la macarena": "La Macarena",
    "macarena": "La Macarena",
    "chico": "Chicó",
    "chicó": "Chicó",
    "santa barbara": "Santa Bárbara",
    "santa bárbara": "Santa Bárbara",
}

LOCATION_KEYWORDS = [
    "downtown",
    "midtown",
    "seattle",
    "brooklyn",
    "capitol hill",
    "waterfront",
    "bellevue",
    "manhattan",
    "ballard",
] + COLOMBIAN_SECTORS

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
        has_outdoor_kws = (
            "outdoor seating" in text_lower
            or "patio" in text_lower
            or ("outdoor" in text_lower and ("restaurant" in text_lower or extracted["cuisine"]))
        )
        if has_outdoor_kws:
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
        norm_text = _normalize_text(text_lower)
        for loc in LOCATION_KEYWORDS:
            norm_loc = _normalize_text(loc)
            if re.search(r"\b" + re.escape(norm_loc) + r"\b", norm_text):
                extracted["location"] = CANONICAL_SECTORS.get(norm_loc, loc.title())
                break

        # 5. Budget extraction
        for tier, keywords in BUDGET_PATTERNS.items():
            if any(kw in text_lower for kw in keywords):
                extracted["budget"] = tier
                break

        return extracted

    @staticmethod
    def generate_maps_url(name: str, address: str) -> str:
        """Construct universal Google Maps navigation URL."""
        query = f"{name}, {address}" if address else name
        encoded = urllib.parse.quote_plus(query)
        return f"https://www.google.com/maps/search/?api=1&query={encoded}"

    def _search_nominatim(
        self,
        query: str,
        location: Optional[str] = None,
        coordinates: Optional[Tuple[float, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Query OpenStreetMap Nominatim API with User-Agent and strict timeout."""
        # Under pytest or hermetic test mode, do not execute external HTTP calls
        if "PYTEST_CURRENT_TEST" in os.environ:
            return []

        search_q = f"{query} {location}" if location else query
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "SamuelAzueroPersonalAssistant/1.0 (contact: samuel@example.com)"}
        params: Dict[str, Any] = {
            "q": search_q,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
        }
        if coordinates:
            lat, lon = coordinates
            params["viewbox"] = f"{lon-0.05},{lat+0.05},{lon+0.05},{lat-0.05}"
            params["bounded"] = 1

        try:
            with httpx.Client(timeout=3.0, headers=headers) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for item in data:
                        name = item.get("name") or item.get("display_name", "").split(",")[0]
                        address = item.get("display_name", "")
                        lat = float(item.get("lat", 0.0))
                        lon = float(item.get("lon", 0.0))
                        results.append({
                            "name": name,
                            "category": item.get("type", "venue"),
                            "cuisine": item.get("category", "dining"),
                            "rating": 4.7,
                            "price_tier": "$$",
                            "address": address,
                            "location": location or "Bogotá",
                            "sector": location or "Bogotá",
                            "latitude": lat,
                            "longitude": lon,
                            "description": f"Lugar identificado vía OpenStreetMap en {location or 'Bogotá'}.",
                            "amenities": ["información vía OSM"],
                            "maps_url": self.generate_maps_url(name, address),
                        })
                    return results
        except Exception as e:
            logger.debug("Nominatim live query failed or timed out: %s", e)
        return []

    def search_outings(
        self,
        user_id: str,
        query: str,
        location: Optional[str] = None,
        coordinates: Optional[Tuple[float, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Search outings matching user query, sector, or GPS coordinates."""
        if coordinates:
            validate_coordinates(coordinates)

        params = self.extract_parameters(query)
        effective_location = location or params["location"]

        # 1. Try Nominatim live search if not in offline test mode
        live_results = self._search_nominatim(query, location=effective_location, coordinates=coordinates)
        if live_results:
            return live_results

        # 2. Hybrid fallback to local client (MockWebSearchClient)
        results = self.search_client.search(
            query=query,
            location=effective_location,
            category=params["activity"] if params["activity"] != "dining" else params["cuisine"],
            budget=params["budget"],
            coordinates=coordinates,
        )

        # Filter by amenity if specified
        if "wifi" in params.get("amenities", []):
            wifi_matches = [r for r in results if "wifi" in r.get("amenities", [])]
            if wifi_matches:
                results = wifi_matches

        # Ensure maps_url is populated on every returned item
        for r in results:
            if "maps_url" not in r or not r["maps_url"]:
                r["maps_url"] = self.generate_maps_url(r.get("name", ""), r.get("address", ""))

        return results

    def format_recommendations_markdown(self, recommendations: List[Dict[str, Any]]) -> str:
        """Format recommendations as conversational Markdown with maps links."""
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
            maps_url = place.get("maps_url") or self.generate_maps_url(name, address)

            lines.append(f"{i}. **{name}** ({rating} ⭐ | {price})")
            if address:
                lines.append(f"   📍 {address}")
            if desc:
                lines.append(f"   _{desc}_")
            if amenities:
                lines.append(f"   ✨ Features: {amenities}")
            if maps_url:
                lines.append(f"   🗺️ [Ver en Google Maps]({maps_url})")
            lines.append("")

        return "\n".join(lines).strip()
