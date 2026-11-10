"""Empirical Adversarial Stress Test Suite for Milestone M13 (Challenger 2).

Scope:
1. Telegram Bot Location Integration:
   - Simulate incoming webhook payload with location: {"latitude": 4.6533, "longitude": -74.0628}.
   - Verify proper dispatch to outing research, IntentType.OUTING_RESEARCH, and Spanish Markdown response with map links.
   - Test coordinates variations (Usaquén, Medellín, extreme boundaries, out-of-bounds rejection).
   - Test TelegramLocation attribute and dict access, secret token verification.
2. Spanish NLP Variations:
   - Phrases with accents, varying casing, and sector keywords:
     * "restaurantes en Chapinero", "RESTAURANTES EN CHAPINERO", "restaurantes en chapinero"
     * "lugares para cenar en Usaquén", "lugares para cenar en Usaquen", "CENAR EN USAQUÉN", "dónde cenar en Usaquén"
     * "planes en Parque 93", "PLANES EN PARQUE 93", "qué hacer en Parque 93"
     * "sitios en Zona G", "sitios para comer en Zona G", "buenos restaurantes en Zona G"
   - Diacritics resilience (accents vs non-accents: Usaquén/Usaquen, Bogotá/Bogota, Medellín/Medellin, Chicó/Chico)
   - Canonical sector mapping and ToolRouter Spanish Markdown formatting.
3. Web Dashboard UI and REST Endpoints:
   - GET /api/research/outings?sector=Chapinero
   - GET /api/search/places?location=Usaquén (and unaccented location=Usaquen)
   - GET /api/research/outings?sector=Zona G
   - GET /api/research/outings?sector=Parque 93
   - GET /api/research/outings?latitude=4.6533&longitude=-74.0628
   - Contract compliance (name, address, rating, price_tier, maps_url with universal Google Maps syntax)
   - Graceful fallback for non-existent sectors ([] with HTTP 200)
4. Web Dashboard Static UI Integrity:
   - index.html DOM elements (#outings-widget-card, #outings-sector-select, #outings-search-input, #btn-search-outings, #outings-list)
   - app.js event listeners, loadOutings function, .btn-maps-direct with target="_blank" rel="noopener noreferrer"
   - styles.css styling rules and responsive layout stacking
5. Concurrency & Multithreading Stress:
   - 20 concurrent REST requests to /api/research/outings across sectors
   - 20 concurrent Telegram location webhook updates across distinct users
"""

import concurrent.futures
import math
from pathlib import Path
import re
from typing import Any, Dict, List
import urllib.parse
import pytest
from fastapi.testclient import TestClient

from app.core.intent_parser import IntentParser, IntentType
from app.core.router import ToolRouter
from app.database.connection import DatabaseManager
from app.integrations.mocks import MockWebSearchClient
from app.integrations.telegram_client import TelegramClient, TelegramLocation
from app.services.search_service import SearchService

REPO_ROOT = Path(__file__).resolve().parent.parent


# ==============================================================================
# 1. Telegram Bot Location Integration Tests
# ==============================================================================

class TestTelegramLocationIntegration:
    """Verifies incoming Telegram location share payloads and routing."""

    def test_telegram_location_share_chapinero_dispatch_and_markdown(self, test_client: TestClient):
        """Simulate incoming location payload (4.6533, -74.0628) near Chapinero/Zona G."""
        payload = {
            "update_id": 88001,
            "message": {
                "message_id": 501,
                "chat": {"id": 998811},
                "from": {"id": 998811, "first_name": "Samuel"},
                "location": {
                    "latitude": 4.6533,
                    "longitude": -74.0628,
                },
                "date": 1731175200,
            },
        }

        response = test_client.post("/api/webhook/telegram", json=payload)
        assert response.status_code == 200, f"Webhook failed: {response.text}"
        data = response.json()
        assert data.get("ok") is True
        assert data.get("status") == "ok"
        assert data.get("intent") == "outing_research"

        reply_text = data.get("response", "")
        # Must return rich Spanish Markdown
        assert "Recomendaciones" in reply_text or "recomendaciones" in reply_text
        assert "Google Maps" in reply_text
        # Must include at least one valid Google Maps URL
        assert "https://www.google.com/maps/search/?api=1&query=" in reply_text
        # Near coordinates (4.6533, -74.0628) are authentic Bogotá places like Criterión, El Chato, or Andrés D.C.
        found_bogota_place = any(p in reply_text for p in ["Criterión", "El Chato", "Andrés D.C."])
        assert found_bogota_place, f"Expected Bogotá venue in response: {reply_text}"

    def test_telegram_location_share_usaquen_coordinates(self, test_client: TestClient):
        """Simulate location in Usaquén (4.6961, -74.0305)."""
        payload = {
            "update_id": 88002,
            "message": {
                "message_id": 502,
                "chat": {"id": 998812},
                "from": {"id": 998812, "first_name": "Samuel"},
                "location": {
                    "latitude": 4.6961,
                    "longitude": -74.0305,
                },
                "date": 1731175201,
            },
        }

        response = test_client.post("/api/webhook/telegram", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("intent") == "outing_research"
        reply_text = data.get("response", "")
        assert "Abasto" in reply_text
        assert "https://www.google.com/maps/search/?api=1&query=" in reply_text

    def test_telegram_location_share_medellin_coordinates(self, test_client: TestClient):
        """Simulate location in El Poblado, Medellín (6.2088, -75.5683)."""
        payload = {
            "update_id": 88003,
            "message": {
                "message_id": 503,
                "chat": {"id": 998813},
                "from": {"id": 998813, "first_name": "Samuel"},
                "location": {
                    "latitude": 6.2088,
                    "longitude": -75.5683,
                },
                "date": 1731175202,
            },
        }

        response = test_client.post("/api/webhook/telegram", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("intent") == "outing_research"
        reply_text = data.get("response", "")
        assert "Carmen Medellín" in reply_text
        assert "https://www.google.com/maps/search/?api=1&query=" in reply_text

    def test_telegram_location_with_live_period_and_extra_fields(self, test_client: TestClient):
        """Telegram live location payloads include extra fields like live_period and heading."""
        payload = {
            "update_id": 88004,
            "message": {
                "message_id": 504,
                "chat": {"id": 998814},
                "from": {"id": 998814, "first_name": "Samuel"},
                "location": {
                    "latitude": 4.6765,
                    "longitude": -74.0483,
                    "live_period": 3600,
                    "heading": 180,
                    "horizontal_accuracy": 5.0,
                },
            },
        }

        response = test_client.post("/api/webhook/telegram", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True
        assert "Parque 93" in data.get("response", "") or "Cervecería" in data.get("response", "")

    def test_telegram_location_out_of_bounds_rejection(self, test_client: TestClient):
        """Out of bounds GPS coordinates return friendly error without 500 crash."""
        bad_coords = [
            (90.5, -74.0),
            (-90.5, -74.0),
            (4.65, 180.5),
            (4.65, -180.5),
        ]
        for idx, (lat, lon) in enumerate(bad_coords):
            payload = {
                "update_id": 88100 + idx,
                "message": {
                    "message_id": 600 + idx,
                    "chat": {"id": 998820 + idx},
                    "location": {"latitude": lat, "longitude": lon},
                },
            }
            response = test_client.post("/api/webhook/telegram", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "error"
            assert "rango válido" in data.get("error", "").lower() or "valid range" in data.get("error", "").lower()

    def test_telegram_location_class_dict_and_attr_access(self):
        """Verify TelegramLocation subclasses dict and exposes both attributes and item getters."""
        loc = TelegramLocation(latitude=4.6533, longitude=-74.0628, live_period=1800)
        assert loc["latitude"] == 4.6533
        assert loc["longitude"] == -74.0628
        assert loc["live_period"] == 1800
        assert loc.latitude == 4.6533
        assert loc.longitude == -74.0628
        assert loc.live_period == 1800

    def test_telegram_webhook_secret_token_verification(self, test_client: TestClient, monkeypatch):
        """Secret token header enforcement."""
        monkeypatch.setenv("TELEGRAM_SECRET_TOKEN", "super_secret_webhook_key_xyz")
        from app.integrations.telegram_client import TelegramClient
        test_client.app.state.telegram = TelegramClient(secret_token="super_secret_webhook_key_xyz")

        payload = {
            "update_id": 88099,
            "message": {
                "message_id": 599,
                "chat": {"id": 11111},
                "location": {"latitude": 4.6533, "longitude": -74.0628},
            },
        }

        # 1. Invalid secret -> 403 Forbidden
        bad_resp = test_client.post(
            "/api/webhook/telegram",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_key"},
        )
        assert bad_resp.status_code == 403

        # 2. Valid secret -> 200 OK
        good_resp = test_client.post(
            "/api/webhook/telegram",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_webhook_key_xyz"},
        )
        assert good_resp.status_code == 200


# ==============================================================================
# 2. Spanish NLP Variations & Sector Extraction Tests
# ==============================================================================

class TestSpanishNLPVariations:
    """Verifies intent parsing and sector recognition across accents, casing, and phrasing."""

    @pytest.fixture
    def parser(self) -> IntentParser:
        return IntentParser()

    def test_nlp_restaurantes_en_chapinero_variations(self, parser: IntentParser):
        variations = [
            "restaurantes en Chapinero",
            "RESTAURANTES EN CHAPINERO",
            "restaurantes en chapinero",
            "buscar restaurantes en Chapinero",
            "buenos restaurantes en Chapinero",
            "sitios para comer en Chapinero",
        ]
        for phrase in variations:
            res = parser.parse(phrase)
            assert res.intent == IntentType.OUTING_RESEARCH, f"Failed on: {phrase}"
            assert res.slots.get("location") == "Chapinero", f"Failed location on: {phrase}"

    def test_nlp_lugares_para_cenar_en_usaquen_variations(self, parser: IntentParser):
        variations = [
            "lugares para cenar en Usaquén",
            "lugares para cenar en Usaquen",
            "LUGARES PARA CENAR EN USAQUÉN",
            "cenar en Usaquén",
            "cenar en Usaquen",
            "dónde cenar en Usaquén",
            "donde cenar en Usaquen",
            "sitios para cenar en Usaquén",
            "recomiéndame dónde cenar en Usaquén",
        ]
        for phrase in variations:
            res = parser.parse(phrase)
            assert res.intent == IntentType.OUTING_RESEARCH, f"Failed on: {phrase}"
            assert res.slots.get("location") == "Usaquén", f"Failed location on: {phrase}"

    def test_nlp_planes_en_parque_93_variations(self, parser: IntentParser):
        variations = [
            "planes en Parque 93",
            "PLANES EN PARQUE 93",
            "planes en parque 93",
            "qué hacer en Parque 93",
            "que hacer en Parque 93",
            "actividades en Parque 93",
            "buscar planes en Parque 93",
        ]
        for phrase in variations:
            res = parser.parse(phrase)
            assert res.intent == IntentType.OUTING_RESEARCH, f"Failed on: {phrase}"
            assert res.slots.get("location") == "Parque 93", f"Failed location on: {phrase}"

    def test_nlp_sitios_en_zona_g_variations(self, parser: IntentParser):
        variations = [
            "sitios en Zona G",
            "SITIOS EN ZONA G",
            "sitios para comer en Zona G",
            "buenos restaurantes en Zona G",
            "lugares en Zona G",
            "restaurantes en Zona G",
        ]
        for phrase in variations:
            res = parser.parse(phrase)
            assert res.intent == IntentType.OUTING_RESEARCH, f"Failed on: {phrase}"
            assert res.slots.get("location") == "Zona G", f"Failed location on: {phrase}"

    def test_nlp_comprehensive_colombian_sectors(self, parser: IntentParser):
        """Verify diacritics normalization across major Colombian sectors."""
        sector_test_cases = [
            ("cenar en La Candelaria", "La Candelaria"),
            ("restaurantes en candelaria", "La Candelaria"),
            ("comer en El Poblado", "El Poblado"),
            ("sitios en poblado", "El Poblado"),
            ("dónde almorzar en Laureles", "La Laureles" if "La Laureles" == "Laureles" else "Laureles"),
            ("restaurantes en Chicó", "Chicó"),
            ("restaurantes en chico", "Chicó"),
            ("planes en Santa Bárbara", "Santa Bárbara"),
            ("planes en santa barbara", "Santa Bárbara"),
            ("sitios para cenar en La Macarena", "La Macarena"),
            ("restaurantes en macarena", "La Macarena"),
            ("bares en Zona T", "Zona T"),
        ]
        for phrase, expected_sector in sector_test_cases:
            res = parser.parse(phrase)
            assert res.intent == IntentType.OUTING_RESEARCH, f"Failed on: {phrase}"
            assert res.slots.get("location") == expected_sector, f"Expected {expected_sector} for '{phrase}', got {res.slots.get('location')}"

    def test_toolrouter_dispatch_spanish_markdown_formatting(self):
        """Verify ToolRouter formats Spanish Markdown with venue emojis and Google Maps links."""
        search_svc = SearchService(MockWebSearchClient())
        router = ToolRouter(search_service=search_svc)

        parser = IntentParser()
        intent_res = parser.parse("restaurantes en Chapinero")
        output = router.dispatch("user_samuel", intent_res)

        assert "Recomendaciones" in output or "recomendaciones" in output
        assert "El Chato" in output or "Andrés D.C." in output
        assert "🗺️ [Ver en Google Maps](https://www.google.com/maps/search/?api=1&query=" in output
        assert "⭐" in output
        assert "💰" in output


# ==============================================================================
# 3. Web Dashboard REST Endpoints & Recommendation Contract Tests
# ==============================================================================

class TestWebDashboardAndRESTEndpoints:
    """Verifies REST endpoints /api/research/outings and /api/search/places."""

    def test_get_research_outings_sector_chapinero(self, test_client: TestClient):
        """GET /api/research/outings?sector=Chapinero."""
        response = test_client.get("/api/research/outings?sector=Chapinero")
        assert response.status_code == 200
        places = response.json()
        assert isinstance(places, list)
        assert len(places) >= 1
        place_names = [p["name"] for p in places]
        assert "El Chato" in place_names or "Andrés D.C." in place_names

        # Contract checks
        for p in places:
            assert "name" in p
            assert "address" in p
            assert "rating" in p
            assert "price_tier" in p
            assert "maps_url" in p
            assert p["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")

    def test_get_search_places_location_usaquen(self, test_client: TestClient):
        """GET /api/search/places?location=Usaquén (with accent)."""
        response = test_client.get("/api/search/places?location=Usaquén")
        assert response.status_code == 200
        places = response.json()
        assert len(places) >= 1
        place_names = [p["name"] for p in places]
        assert "Abasto" in place_names

    def test_get_search_places_location_usaquen_unaccented(self, test_client: TestClient):
        """GET /api/search/places?location=Usaquen (without accent)."""
        response = test_client.get("/api/search/places?location=Usaquen")
        assert response.status_code == 200
        places = response.json()
        assert len(places) >= 1
        place_names = [p["name"] for p in places]
        assert "Abasto" in place_names

    def test_get_research_outings_sector_zona_g(self, test_client: TestClient):
        """GET /api/research/outings?sector=Zona G."""
        response = test_client.get("/api/research/outings?sector=Zona G")
        assert response.status_code == 200
        places = response.json()
        assert any(p["name"] == "Criterión" for p in places)

    def test_get_research_outings_sector_parque_93(self, test_client: TestClient):
        """GET /api/research/outings?sector=Parque 93."""
        response = test_client.get("/api/research/outings?sector=Parque 93")
        assert response.status_code == 200
        places = response.json()
        assert any("Parque 93" in p["name"] or "Cervecería" in p["name"] for p in places)

    def test_get_research_outings_by_coordinates(self, test_client: TestClient):
        """GET /api/research/outings?latitude=4.6533&longitude=-74.0628."""
        response = test_client.get("/api/research/outings?latitude=4.6533&longitude=-74.0628")
        assert response.status_code == 200
        places = response.json()
        assert isinstance(places, list)
        assert len(places) >= 1
        for p in places:
            assert p["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")

    def test_maps_url_syntax_and_percent_encoding(self, test_client: TestClient):
        """Validate URL syntax and strict percent encoding of maps_url."""
        response = test_client.get("/api/research/outings?sector=Chapinero")
        assert response.status_code == 200
        places = response.json()
        for p in places:
            url = p["maps_url"]
            assert " " not in url, f"maps_url contains unencoded whitespace: {url}"
            parsed = urllib.parse.urlparse(url)
            assert parsed.scheme == "https"
            assert parsed.netloc == "www.google.com"
            assert parsed.path == "/maps/search/"
            qs = urllib.parse.parse_qs(parsed.query)
            assert "api" in qs and qs["api"] == ["1"]
            assert "query" in qs
            assert len(qs["query"][0]) > 0

    def test_unknown_sector_clean_empty_list_fallback(self, test_client: TestClient):
        """Unknown sector query returns empty list [] without uncaught exception."""
        response = test_client.get("/api/research/outings?sector=SectorTotalmenteInexistente999")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


# ==============================================================================
# 4. Web Dashboard Static UI Assets Integrity Tests
# ==============================================================================

class TestWebDashboardStaticUIAssets:
    """Verifies static HTML, JavaScript, and CSS elements for geo-outings."""

    def test_index_html_outings_dom_structure(self):
        html_path = REPO_ROOT / "app" / "static" / "index.html"
        assert html_path.exists(), "app/static/index.html missing"
        content = html_path.read_text(encoding="utf-8")

        # Mandatory UI elements
        assert 'id="outings-widget-card"' in content
        assert 'id="outings-sector-select"' in content
        assert 'id="outings-search-input"' in content
        assert 'id="btn-search-outings"' in content
        assert 'id="outings-list"' in content
        assert 'id="outings-count-badge"' in content

        # Colombian sectors in dropdown
        for sector in ["Chapinero", "Usaquén", "Parque 93", "Zona G", "La Candelaria", "El Poblado", "Laureles"]:
            assert f'value="{sector}"' in content or f'>{sector}<' in content, f"Missing sector option: {sector}"

    def test_app_js_outings_event_listeners_and_rendering(self):
        js_path = REPO_ROOT / "app" / "static" / "js" / "app.js"
        assert js_path.exists(), "app/static/js/app.js missing"
        content = js_path.read_text(encoding="utf-8")

        assert "loadOutings" in content
        assert "outings-sector-select" in content
        assert "outings-search-input" in content
        assert "btn-search-outings" in content
        assert "/api/research/outings" in content
        # Check map button opens in new tab securely
        assert 'target="_blank"' in content
        assert 'rel="noopener noreferrer"' in content
        assert "btn-maps-direct" in content

    def test_styles_css_outings_rules(self):
        css_path = REPO_ROOT / "app" / "static" / "css" / "styles.css"
        assert css_path.exists(), "app/static/css/styles.css missing"
        content = css_path.read_text(encoding="utf-8")

        assert ".outings-filter-bar" in content
        assert ".outings-filter-row" in content
        assert ".outings-col-sector" in content
        assert ".outings-col-search" in content
        assert ".btn-maps-direct" in content


# ==============================================================================
# 5. Concurrency & Multithreading Stress Tests
# ==============================================================================

class TestConcurrencyAndMultithreading:
    """Verifies thread safety under concurrent requests."""

    def test_concurrent_rest_outings_queries(self, test_client: TestClient):
        """20 concurrent queries across sectors return valid responses without race conditions."""
        sectors = ["Chapinero", "Usaquén", "Zona G", "Parque 93", "La Candelaria"] * 4

        def fetch_sector(sec: str) -> Dict[str, Any]:
            resp = test_client.get(f"/api/research/outings?sector={sec}")
            return {"status": resp.status_code, "count": len(resp.json()), "sector": sec}

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_sector, s) for s in sectors]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20
        for r in results:
            assert r["status"] == 200
            assert r["count"] >= 1, f"Empty result for sector {r['sector']}"

    def test_concurrent_telegram_location_shares(self, test_client: TestClient):
        """20 concurrent Telegram location shares for distinct users."""
        def send_location(i: int) -> int:
            payload = {
                "update_id": 99000 + i,
                "message": {
                    "message_id": 1000 + i,
                    "chat": {"id": 800000 + i},
                    "from": {"id": 800000 + i, "first_name": f"User_{i}"},
                    "location": {"latitude": 4.6533, "longitude": -74.0628},
                },
            }
            resp = test_client.post("/api/webhook/telegram", json=payload)
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(send_location, i) for i in range(20)]
            statuses = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(statuses) == 20
        assert all(s == 200 for s in statuses)
