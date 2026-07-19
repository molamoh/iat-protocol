from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any, Callable

from iat.platform.gateway import sanitize_public_value
from iat.platform.models import utc_now_iso


Provider = Callable[[], Any]


def _stable_id(prefix: str, value: Any) -> str:
    normalized = str(value or "unknown").strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _unwrap(value: Any, *keys: str) -> Any:
    current = value

    for key in keys:
        if not isinstance(current, dict):
            return current

        if key not in current:
            return current

        current = current[key]

    return current


def _collection(value: Any, *preferred_keys: str) -> list[dict[str, Any]]:
    current = value

    if isinstance(current, dict):
        for key in preferred_keys:
            candidate = current.get(key)

            if candidate is not None:
                current = candidate
                break

    if isinstance(current, dict):
        result: list[dict[str, Any]] = []

        for item_key, item_value in current.items():
            if isinstance(item_value, dict):
                normalized = dict(item_value)
                normalized.setdefault("_collection_key", item_key)
                result.append(normalized)

        return result

    if isinstance(current, Iterable) and not isinstance(
        current,
        (str, bytes, bytearray),
    ):
        return [
            dict(item)
            for item in current
            if isinstance(item, dict)
        ]

    return []


class ProtocolGraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}

    def add_node(
        self,
        node_id: str,
        node_type: str,
        *,
        label: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        existing = self.nodes.get(node_id, {})

        merged_metadata = dict(existing.get("metadata") or {})
        merged_metadata.update(metadata or {})

        node = {
            "id": node_id,
            "type": node_type,
            "label": label or existing.get("label") or node_id,
            "status": status or existing.get("status") or "unknown",
            "metadata": merged_metadata,
        }

        self.nodes[node_id] = sanitize_public_value(node)
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        edge_key = f"{source}|{relation}|{target}"
        edge_id = _stable_id("edge", edge_key)

        existing = self.edges.get(edge_id, {})
        merged_metadata = dict(existing.get("metadata") or {})
        merged_metadata.update(metadata or {})

        edge = {
            "id": edge_id,
            "source": source,
            "target": target,
            "relation": relation,
            "status": status or existing.get("status") or "active",
            "metadata": merged_metadata,
        }

        self.edges[edge_id] = sanitize_public_value(edge)
        return edge_id

    def result(self) -> dict[str, Any]:
        nodes = sorted(
            self.nodes.values(),
            key=lambda item: (item["type"], item["id"]),
        )
        edges = sorted(
            self.edges.values(),
            key=lambda item: (
                item["source"],
                item["relation"],
                item["target"],
            ),
        )

        node_types: dict[str, int] = {}
        edge_relations: dict[str, int] = {}

        for node in nodes:
            node_type = str(node.get("type") or "unknown")
            node_types[node_type] = node_types.get(node_type, 0) + 1

        for edge in edges:
            relation = str(edge.get("relation") or "unknown")
            edge_relations[relation] = edge_relations.get(relation, 0) + 1

        return {
            "status": "online",
            "graph_version": "iat_protocol_graph_v1",
            "generated_at": utc_now_iso(),
            "directed": True,
            "read_only": True,
            "authority": "iat_foundation",
            "summary": {
                "nodes": len(nodes),
                "edges": len(edges),
                "node_types": node_types,
                "edge_relations": edge_relations,
            },
            "nodes": nodes,
            "edges": edges,
        }


def _safe_provider(provider: Provider | None) -> Any:
    if provider is None:
        return None

    try:
        return provider()
    except Exception:
        return None


def build_protocol_graph(
    *,
    marketplace_provider: Provider | None = None,
    orders_provider: Provider | None = None,
    agents_provider: Provider | None = None,
    foundation_agents_provider: Provider | None = None,
    workers_provider: Provider | None = None,
    settlements_provider: Provider | None = None,
    events_provider: Provider | None = None,
) -> dict[str, Any]:
    builder = ProtocolGraphBuilder()

    foundation_id = builder.add_node(
        "foundation:iat",
        "foundation",
        label="IAT Foundation",
        status="online",
        metadata={
            "authority": True,
            "buyer_facing": True,
            "supplier_control": True,
        },
    )

    marketplace_id = builder.add_node(
        "marketplace:iat",
        "marketplace",
        label="IAT Marketplace",
        status="online",
    )

    builder.add_edge(
        foundation_id,
        marketplace_id,
        "governs",
    )

    marketplace_data = _safe_provider(marketplace_provider)
    listings = _collection(
        marketplace_data,
        "marketplace",
        "listings",
    )

    for index, listing in enumerate(listings):
        service = listing.get("service") or "unknown"
        agent_identity = (
            listing.get("agent_id")
            or listing.get("seller_agent_id")
            or listing.get("id")
            or listing.get("wallet")
            or listing.get("seller_wallet")
            or f"{service}:{listing.get('source')}:{index}"
        )

        agent_id = _stable_id("seller_agent", agent_identity)

        builder.add_node(
            agent_id,
            "seller_agent",
            label=str(
                listing.get("agent_name")
                or listing.get("name")
                or agent_identity
            ),
            status=str(listing.get("status") or "unknown"),
            metadata={
                "service": service,
                "source": listing.get("source"),
                "reputation": listing.get("reputation"),
                "score": listing.get("score"),
                "routing_status": listing.get("routing_status"),
                "trust_tier": listing.get("trust_tier"),
            },
        )

        service_id = _stable_id("service", service)

        builder.add_node(
            service_id,
            "service",
            label=str(service),
            status="available",
        )

        builder.add_edge(
            marketplace_id,
            service_id,
            "publishes",
        )
        builder.add_edge(
            agent_id,
            service_id,
            "provides",
        )
        builder.add_edge(
            foundation_id,
            agent_id,
            "controls_supplier",
        )

    agents_data = _safe_provider(agents_provider)
    agents = _collection(agents_data, "agents")

    for index, agent in enumerate(agents):
        identity = (
            agent.get("agent_id")
            or agent.get("id")
            or agent.get("wallet")
            or agent.get("_collection_key")
            or f"agent:{index}"
        )

        node_type = (
            "foundation_agent"
            if agent.get("is_foundation")
            or agent.get("agent_type") == "foundation"
            or agent.get("role") == "foundation"
            else "agent"
        )

        node_id = _stable_id(node_type, identity)

        builder.add_node(
            node_id,
            node_type,
            label=str(agent.get("name") or identity),
            status=str(agent.get("status") or "unknown"),
            metadata={
                "service": agent.get("service"),
                "role": agent.get("role"),
                "source": agent.get("source"),
            },
        )

        builder.add_edge(
            foundation_id,
            node_id,
            "governs",
        )

    foundation_agents_data = _safe_provider(
        foundation_agents_provider
    )
    foundation_agents = _collection(
        foundation_agents_data,
        "foundation_agents",
        "agents",
    )

    for index, agent in enumerate(foundation_agents):
        identity = (
            agent.get("agent_id")
            or agent.get("id")
            or agent.get("_collection_key")
            or f"foundation-agent:{index}"
        )

        node_id = _stable_id("foundation_agent", identity)

        builder.add_node(
            node_id,
            "foundation_agent",
            label=str(agent.get("name") or identity),
            status=str(agent.get("status") or "unknown"),
            metadata={
                "role": agent.get("role"),
                "capabilities": agent.get("capabilities"),
                "specialties": agent.get("specialties"),
            },
        )

        builder.add_edge(
            foundation_id,
            node_id,
            "operates",
        )

    orders_data = _safe_provider(orders_provider)
    orders = _collection(orders_data, "orders")

    order_nodes: dict[str, str] = {}

    for index, order in enumerate(orders):
        order_identity = (
            order.get("order_id")
            or order.get("id")
            or order.get("_collection_key")
            or f"order:{index}"
        )

        order_id = _stable_id("order", order_identity)
        order_nodes[str(order_identity)] = order_id

        buyer_identity = (
            order.get("buyer_wallet")
            or order.get("buyer_id")
            or order.get("buyer")
            or "anonymous"
        )
        buyer_id = _stable_id("buyer", buyer_identity)

        builder.add_node(
            buyer_id,
            "buyer",
            label="Buyer",
            status="active",
            metadata={
                "identity_protected": True,
            },
        )

        builder.add_node(
            order_id,
            "order",
            label=str(order_identity),
            status=str(order.get("status") or "unknown"),
            metadata={
                "service": order.get("service"),
                "price": order.get("price"),
                "created_at": order.get("created_at"),
                "updated_at": order.get("updated_at"),
                "execution_mode": order.get("execution_mode"),
            },
        )

        builder.add_edge(
            buyer_id,
            foundation_id,
            "requests_through",
        )
        builder.add_edge(
            foundation_id,
            order_id,
            "controls_order",
        )

        seller_identity = (
            order.get("seller_agent_id")
            or order.get("seller_id")
            or order.get("seller_wallet")
        )

        if seller_identity:
            seller_id = _stable_id(
                "seller_agent",
                seller_identity,
            )

            builder.add_node(
                seller_id,
                "seller_agent",
                label=str(seller_identity),
                status="unknown",
                metadata={
                    "wallet": order.get("seller_wallet"),
                    "source": order.get("seller_source"),
                },
            )

            builder.add_edge(
                order_id,
                seller_id,
                "assigned_supplier",
            )
            builder.add_edge(
                foundation_id,
                seller_id,
                "controls_supplier",
            )

        service = order.get("service")

        if service:
            service_id = _stable_id("service", service)

            builder.add_node(
                service_id,
                "service",
                label=str(service),
                status="available",
            )

            builder.add_edge(
                order_id,
                service_id,
                "requests_service",
            )

    workers_data = _safe_provider(workers_provider)
    workers = _collection(workers_data, "workers")

    for index, worker in enumerate(workers):
        identity = (
            worker.get("worker_id")
            or worker.get("id")
            or worker.get("_collection_key")
            or f"worker:{index}"
        )
        worker_id = _stable_id("worker", identity)

        builder.add_node(
            worker_id,
            "worker",
            label=str(worker.get("worker_name") or identity),
            status=str(
                worker.get("worker_status")
                or worker.get("status")
                or "unknown"
            ),
            metadata={
                "hostname": worker.get("hostname"),
                "capabilities": worker.get("capabilities"),
                "current_action_id": worker.get("current_action_id"),
                "last_heartbeat": worker.get("last_heartbeat"),
            },
        )

        builder.add_edge(
            foundation_id,
            worker_id,
            "supervises_runtime",
        )

    settlements_data = _safe_provider(settlements_provider)
    settlements = _collection(
        settlements_data,
        "settlements",
    )

    for index, settlement in enumerate(settlements):
        identity = (
            settlement.get("settlement_id")
            or settlement.get("id")
            or settlement.get("_collection_key")
            or f"settlement:{index}"
        )
        settlement_id = _stable_id("settlement", identity)

        builder.add_node(
            settlement_id,
            "settlement",
            label=str(identity),
            status=str(settlement.get("status") or "unknown"),
            metadata={
                "order_id": settlement.get("order_id"),
                "gross_amount_iat": settlement.get(
                    "gross_amount_iat"
                ),
                "tx_signature": settlement.get("tx_signature"),
            },
        )

        builder.add_edge(
            foundation_id,
            settlement_id,
            "authorizes_settlement",
        )

        linked_order = settlement.get("order_id")

        if linked_order:
            order_id = order_nodes.get(str(linked_order))

            if order_id is None:
                order_id = _stable_id("order", linked_order)
                builder.add_node(
                    order_id,
                    "order",
                    label=str(linked_order),
                    status="unknown",
                )

            builder.add_edge(
                order_id,
                settlement_id,
                "settles_through",
            )

    events_data = _safe_provider(events_provider)
    events = _collection(
        events_data,
        "recent_events",
        "events",
    )

    for index, event in enumerate(events):
        identity = (
            event.get("event_id")
            or event.get("id")
            or event.get("_collection_key")
            or f"event:{index}"
        )
        event_id = _stable_id("runtime_event", identity)

        builder.add_node(
            event_id,
            "runtime_event",
            label=str(event.get("event_type") or identity),
            status=str(event.get("status") or "recorded"),
            metadata={
                "event_type": event.get("event_type"),
                "action_id": event.get("action_id"),
                "worker_id": event.get("worker_id"),
                "created_at": event.get("created_at"),
            },
        )

        builder.add_edge(
            foundation_id,
            event_id,
            "observes",
        )

        worker_identity = event.get("worker_id")

        if worker_identity:
            worker_id = _stable_id("worker", worker_identity)

            builder.add_node(
                worker_id,
                "worker",
                label=str(worker_identity),
                status="unknown",
            )

            builder.add_edge(
                worker_id,
                event_id,
                "emits",
            )

        order_identity = event.get("order_id")

        if order_identity:
            order_id = order_nodes.get(str(order_identity))

            if order_id is None:
                order_id = _stable_id("order", order_identity)
                builder.add_node(
                    order_id,
                    "order",
                    label=str(order_identity),
                    status="unknown",
                )

            builder.add_edge(
                event_id,
                order_id,
                "relates_to_order",
            )

        settlement_identity = event.get("settlement_id")

        if settlement_identity:
            settlement_id = _stable_id(
                "settlement",
                settlement_identity,
            )

            builder.add_node(
                settlement_id,
                "settlement",
                label=str(settlement_identity),
                status="unknown",
            )

            builder.add_edge(
                event_id,
                settlement_id,
                "relates_to_settlement",
            )

    return builder.result()
