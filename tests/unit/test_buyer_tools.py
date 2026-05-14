"""Broad coverage for the remaining buyer-action and primitive tools."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import (
    category,
    compare,
    disputes,
    intel,
    messaging,
    offer,
    product,
    purchase_handoff,
    purchases,
    ratings,
    seller,
    watching,
)


@pytest.mark.asyncio
async def test_get_offer(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/X",
        json={"id": "X", "name": "n", "sellingMode": {"price": {"amount": "5"}}},
    )
    mcp = FastMCP(name="t")
    offer.register(mcp, tool_context)
    tool = await mcp.get_tool("get_offer")
    result = await tool.fn(offer_id="X")
    assert result.offer_id == "X"


@pytest.mark.asyncio
async def test_list_categories_and_parameters(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/categories",
        json={"categories": [{"id": "1", "name": "Książki", "leaf": True}]},
    )
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/categories/1/parameters",
        json={"parameters": [{"id": "p", "name": "Marka", "type": "STRING"}]},
    )
    mcp = FastMCP(name="t")
    category.register(mcp, tool_context)
    cats = await (await mcp.get_tool("list_categories")).fn()
    assert cats[0].category_id == "1"
    params = await (await mcp.get_tool("get_category_parameters")).fn(category_id="1")
    assert params.parameters[0].parameter_id == "p"


@pytest.mark.asyncio
async def test_get_product_and_listings(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/products/PR",
        json={"id": "PR", "name": "Foo"},
    )
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {
                "regular": [{"id": "1", "name": "n", "sellingMode": {"price": {"amount": "5"}}}]
            }
        },
    )
    httpx_mock.add_response(
        url=re.compile(r".*sale/products.*"),
        json={"products": [{"id": "PR", "name": "Foo"}]},
    )
    mcp = FastMCP(name="t")
    product.register(mcp, tool_context)
    prod = await (await mcp.get_tool("get_product")).fn(product_id="PR")
    assert prod.product_id == "PR"
    offers = await (await mcp.get_tool("list_offers_for_product")).fn(product_id="PR")
    assert offers[0].offer_id == "1"
    search_result = await (await mcp.get_tool("search_products")).fn(phrase="Foo")
    assert search_result.products[0].product_id == "PR"


@pytest.mark.asyncio
async def test_search_products_requires_input(tool_context) -> None:
    mcp = FastMCP(name="t")
    product.register(mcp, tool_context)
    tool = await mcp.get_tool("search_products")
    with pytest.raises(ValueError):
        await tool.fn()


@pytest.mark.asyncio
async def test_seller_lookup(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/U",
        json={"id": "U", "login": "L", "ratings": {"average": 4.0, "count": 100}},
    )
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={"items": {"regular": []}},
    )
    mcp = FastMCP(name="t")
    seller.register(mcp, tool_context)
    s = await (await mcp.get_tool("get_seller")).fn(seller_id="U")
    assert s.login == "L"
    listings = await (await mcp.get_tool("list_seller_offers")).fn(seller_id="U")
    assert listings == []


@pytest.mark.asyncio
async def test_watching_lifecycle(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/watchlist",
        json={
            "watchedOffers": [{"id": "1", "name": "n", "sellingMode": {"price": {"amount": "5"}}}]
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.allegro.pl.allegrosandbox.pl/watchlist",
        json={"offer": {"id": "1"}},
    )
    httpx_mock.add_response(
        method="DELETE",
        url="https://api.allegro.pl.allegrosandbox.pl/watchlist/1",
    )
    mcp = FastMCP(name="t")
    watching.register(mcp, tool_context)
    listed = await (await mcp.get_tool("list_watched")).fn()
    assert listed[0].offer_id == "1"
    watched = await (await mcp.get_tool("watch_offer")).fn(offer_id="1")
    assert watched.watched is True
    unwatched = await (await mcp.get_tool("unwatch_offer")).fn(offer_id="1")
    assert unwatched.watched is False


@pytest.mark.asyncio
async def test_messaging(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/messaging/threads",
        json={"threads": [{"id": "T1", "interlocutor": {"id": "u", "login": "u"}}]},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.allegro.pl.allegrosandbox.pl/messaging/threads/T1/messages",
        json={"id": "M", "text": "hi", "author": {"id": "me"}, "createdAt": "2024-01-01T00:00:00Z"},
    )
    mcp = FastMCP(name="t")
    messaging.register(mcp, tool_context)
    threads = await (await mcp.get_tool("list_messages")).fn()
    assert threads[0].thread_id == "T1"
    msg = await (await mcp.get_tool("send_message")).fn(thread_id="T1", body="hi")
    assert msg.body == "hi"


@pytest.mark.asyncio
async def test_messaging_thread_detail(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/messaging/threads/T2/messages",
        json={
            "thread": {"id": "T2", "interlocutor": {"id": "u", "login": "u"}},
            "messages": [
                {
                    "id": "M1",
                    "text": "hello",
                    "author": {"id": "u"},
                    "createdAt": "2024-01-01T00:00:00Z",
                },
            ],
        },
    )
    mcp = FastMCP(name="t")
    messaging.register(mcp, tool_context)
    result = await (await mcp.get_tool("list_messages")).fn(thread_id="T2")
    assert result[0].messages[0].body == "hello"


@pytest.mark.asyncio
async def test_purchases(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*order/checkout-forms.*"),
        json={
            "checkoutForms": [
                {
                    "id": "O1",
                    "status": "BOUGHT",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "lineItems": [
                        {
                            "offer": {"id": "X", "name": "x"},
                            "price": {"amount": "10", "currency": "PLN"},
                            "quantity": 1,
                        }
                    ],
                    "summary": {"totalToPay": {"amount": "10", "currency": "PLN"}},
                    "seller": {"id": "S", "login": "L"},
                    "delivery": {
                        "address": {"city": "Warszawa", "zipCode": "00-001"},
                        "method": {"name": "Kurier"},
                    },
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/order/checkout-forms/O1",
        json={
            "id": "O1",
            "status": "BOUGHT",
            "createdAt": "2024-01-01T00:00:00Z",
            "lineItems": [],
            "summary": {"totalToPay": {"amount": "5"}},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/me",
        json={"id": "1", "login": "me"},
    )
    mcp = FastMCP(name="t")
    purchases.register(mcp, tool_context)
    listed = await (await mcp.get_tool("list_purchases")).fn(period_days=30)
    assert listed[0].order_id == "O1"
    one = await (await mcp.get_tool("get_purchase")).fn(order_id="O1")
    assert one.order_id == "O1"
    account = await (await mcp.get_tool("get_my_account")).fn()
    assert account.login == "me"


@pytest.mark.asyncio
async def test_ratings(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/user-ratings",
        json={"id": "R", "order": {"id": "O"}, "rating": 5},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/user-ratings.*"),
        json={"ratings": [{"id": "R", "order": {"id": "O"}, "rating": 5}]},
    )
    mcp = FastMCP(name="t")
    ratings.register(mcp, tool_context)
    submitted = await (await mcp.get_tool("submit_rating")).fn(order_id="O", rating=5)
    assert submitted.rating == 5
    listed = await (await mcp.get_tool("list_my_ratings")).fn(limit=10)
    assert listed[0].rating_id == "R"


@pytest.mark.asyncio
async def test_disputes(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/disputes",
        json={
            "disputes": [
                {
                    "id": "D",
                    "order": {"id": "O"},
                    "status": "OPEN",
                    "subject": {"id": "NOT_RECEIVED"},
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/disputes/D",
        json={
            "id": "D",
            "order": {"id": "O"},
            "status": "OPEN",
            "subject": {"id": "NOT_RECEIVED"},
            "createdAt": "2024-01-01T00:00:00Z",
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/disputes/D/messages",
        json={
            "messages": [
                {
                    "id": "M1",
                    "author": {"role": "BUYER"},
                    "text": "hi",
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            ]
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/disputes",
        json={
            "id": "D2",
            "order": {"id": "O"},
            "status": "OPEN",
            "subject": {"id": "NOT_RECEIVED"},
            "createdAt": "2024-01-01T00:00:00Z",
        },
    )
    mcp = FastMCP(name="t")
    disputes.register(mcp, tool_context)
    listed = await (await mcp.get_tool("list_disputes")).fn()
    assert listed[0].dispute_id == "D"
    detail = await (await mcp.get_tool("get_dispute")).fn(dispute_id="D")
    assert detail.messages[0].body == "hi"
    opened = await (await mcp.get_tool("open_dispute")).fn(
        order_id="O",
        reason="NOT_RECEIVED",
        description="Item never arrived after the promised window expired.",
    )
    assert opened.dispute_id == "D2"


@pytest.mark.asyncio
async def test_pickup_points(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*order/pickup-points.*"),
        json={
            "pickupPoints": [
                {
                    "id": "PP1",
                    "provider": "INPOST",
                    "name": "Locker A",
                    "address": {"street": "Main 1", "zipCode": "00-001", "city": "Warszawa"},
                    "location": {"latitude": 52.2, "longitude": 21.0},
                    "distance": 0.5,
                }
            ]
        },
    )
    mcp = FastMCP(name="t")
    purchase_handoff.register(mcp, tool_context)
    points = await (await mcp.get_tool("find_pickup_points")).fn(postal_code="00-001", radius_km=3)
    assert points[0].point_id == "PP1"


@pytest.mark.asyncio
async def test_compute_total_cost_with_quote(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/Z",
        json={
            "id": "Z",
            "name": "n",
            "sellingMode": {"price": {"amount": "100", "currency": "PLN"}},
            "delivery": {"options": []},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/product-offers/Z/delivery-methods.*"),
        json={
            "deliveryMethods": [
                {"id": "kurier", "price": {"amount": "12.99", "currency": "PLN"}},
            ]
        },
    )
    mcp = FastMCP(name="t")
    compare.register(mcp, tool_context)
    landed = await (await mcp.get_tool("compute_total_cost")).fn(
        offer_id="Z", postal_code="00-001", quantity=2
    )
    assert landed.total.amount == pytest.approx(212.99)
    assert landed.delivery_method == "kurier"


@pytest.mark.asyncio
async def test_find_lower_price(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/REF",
        json={
            "id": "REF",
            "name": "Ref",
            "sellingMode": {"price": {"amount": "200"}},
            "seller": {"id": "S0"},
            "product": {"id": "P"},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/users/S0",
        json={"id": "S0", "login": "ref", "ratings": {"average": 5.0, "count": 100}},
        is_reusable=True,
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {
                "regular": [
                    {
                        "id": "C1",
                        "name": "Cheap",
                        "sellingMode": {"price": {"amount": "180"}},
                        "seller": {"id": "S1"},
                        "product": {"id": "P"},
                    },
                ]
            }
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/users/S1",
        json={"id": "S1", "login": "alt", "ratings": {"average": 4.8, "count": 80}},
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    cheaper = await (await mcp.get_tool("find_lower_price")).fn(reference_offer_id="REF")
    assert cheaper[0].offer_id == "C1"
