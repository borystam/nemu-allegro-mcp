"""Parsing helpers."""

from __future__ import annotations

from allegro_mcp.tools._parsers import (
    parse_category,
    parse_category_parameters,
    parse_offer,
    parse_offer_summary,
    parse_product,
    parse_product_search,
    parse_search_result,
    parse_seller,
)


def test_parse_offer_summary_extracts_essentials() -> None:
    summary = parse_offer_summary(
        {
            "id": "12345",
            "name": "Test Offer",
            "sellingMode": {"price": {"amount": "99.50", "currency": "PLN"}},
            "seller": {"id": "1", "login": "seller", "kind": "BUSINESS"},
            "delivery": {"free": True, "smart": False},
            "stock": {"available": 3},
            "product": {"id": "p1"},
            "category": {"id": "c1"},
            "images": [{"url": "https://img/1.jpg"}],
        }
    )
    assert summary.offer_id == "12345"
    assert summary.price.amount == 99.5
    assert summary.price.currency == "PLN"
    assert summary.seller_login == "seller"
    assert summary.free_delivery is True
    assert summary.product_id == "p1"
    assert summary.image_url == "https://img/1.jpg"


def test_parse_search_result_handles_promoted() -> None:
    result = parse_search_result(
        {
            "items": {
                "regular": [{"id": "1", "name": "n", "sellingMode": {"price": {"amount": "1"}}}],
                "promoted": [{"id": "2", "name": "p", "sellingMode": {"price": {"amount": "2"}}}],
            },
            "filters": [
                {
                    "id": "fid",
                    "name": "fname",
                    "values": [{"value": "v1", "name": "vn"}],
                }
            ],
            "totalCount": 99,
        },
        offset=10,
        limit=20,
    )
    assert result.total_count == 99
    assert result.offers[0].offer_id == "1"
    assert result.promoted_offers[0].offer_id == "2"
    assert result.filters[0].id == "fid"
    assert result.offset == 10
    assert result.limit == 20


def test_parse_offer_uses_categories_and_images() -> None:
    offer = parse_offer(
        {
            "id": "o1",
            "name": "Offer",
            "sellingMode": {"price": {"amount": "200", "currency": "PLN"}},
            "seller": {"id": "s", "login": "L", "kind": "BUSINESS"},
            "category": {"id": "10"},
            "product": {"id": "p"},
            "images": [{"url": "a"}, {"url": "b"}],
            "categoryPath": [{"name": "A"}, {"name": "B"}],
            "stock": {"available": 7, "unit": "UNIT"},
            "parameters": [],
            "delivery": {"free": True, "options": []},
        }
    )
    assert offer.category_path == ["A", "B"]
    assert offer.image_urls == ["a", "b"]
    assert offer.quantity_available == 7
    assert offer.delivery is not None
    assert offer.delivery.free_delivery is True


def test_parse_product_extracts_ean_list() -> None:
    product = parse_product(
        {
            "id": "p1",
            "name": "x",
            "category": {"id": "c"},
            "ean": ["123", 456],
            "images": ["a", {"url": "b"}],
        }
    )
    assert product.ean == ["123", "456"]
    assert product.image_urls == ["a", "b"]


def test_parse_product_search_preserves_phrase() -> None:
    result = parse_product_search({"products": [{"id": "1", "name": "x"}]}, phrase="ph")
    assert result.products[0].product_id == "1"
    assert result.query_phrase == "ph"


def test_parse_category_marks_leaf_explicitly() -> None:
    cat = parse_category({"id": "c", "name": "Książki", "leaf": True})
    assert cat.leaf is True
    assert cat.name == "Książki"
    assert cat.name_pl == "Książki"


def test_parse_category_falls_back_to_children_absence() -> None:
    cat = parse_category({"id": "c", "name": "n"})
    assert cat.leaf is True


def test_parse_category_parameters_preserves_unit() -> None:
    params = parse_category_parameters(
        {
            "parameters": [
                {
                    "id": "p1",
                    "name": "Rozmiar",
                    "nameEn": "Size",
                    "type": "INTEGER",
                    "required": True,
                    "unit": "mm",
                }
            ]
        },
        category_id="c1",
    )
    assert params.parameters[0].name == "Size"
    assert params.parameters[0].name_pl == "Rozmiar"
    assert params.parameters[0].unit == "mm"


def test_parse_seller_extracts_ratings() -> None:
    seller = parse_seller(
        {
            "id": "s",
            "login": "L",
            "kind": "BUSINESS",
            "company": {"name": "Co Ltd"},
            "ratings": {
                "average": 4.7,
                "count": 250,
                "positivePercentage": 99.2,
            },
            "superSeller": True,
        }
    )
    assert seller.is_business is True
    assert seller.ratings is not None
    assert seller.ratings.average_score == 4.7
    assert seller.ratings.super_seller is True
