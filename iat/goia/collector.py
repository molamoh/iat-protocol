"""Fail-closed Web collection primitives for GOIA."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from pydantic import ValidationError

from iat.security.network import UnsafeNetworkTarget, validate_public_runtime_url
from iat.goia.contracts import MerchantProviderManifest, NativeCatalogDocument


GOIA_USER_AGENT = "GOIABot/0.1 (+https://iat-protocol-latest.onrender.com/.well-known/goia.json)"
MAX_DOCUMENT_BYTES = 1_000_000
MAX_SITEMAP_URLS = 1_000
MAX_JSON_LD_SCRIPTS = 100
MAX_PARTNER_HINTS = 500
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/json",
    "application/ld+json",
    "text/plain",
}


class GOIACollectionError(ValueError):
    pass


@dataclass(frozen=True)
class CollectedDocument:
    url: str
    content_type: str
    body: bytes
    sha256: str


def configured_collection_hosts() -> set[str]:
    return {
        item.strip().lower().rstrip(".")
        for item in os.getenv("IAT_GOIA_COLLECTION_HOSTS", "").split(",")
        if item.strip()
    }


def validate_collection_url(url: str, *, allowed_hosts: set[str] | None = None) -> dict:
    hosts = configured_collection_hosts() if allowed_hosts is None else allowed_hosts
    if not hosts:
        raise GOIACollectionError("collection_hosts_not_configured")
    parsed = urlparse(str(url or "").strip())
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if hostname not in hosts:
        raise GOIACollectionError("collection_host_not_allowed")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise GOIACollectionError("collection_url_components_not_allowed")
    try:
        target = validate_public_runtime_url(url)
    except UnsafeNetworkTarget as exc:
        raise GOIACollectionError(str(exc)) from exc
    return target


def _read_bounded(response: requests.Response, *, maximum: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > maximum:
                raise GOIACollectionError("document_too_large")
        except ValueError as exc:
            raise GOIACollectionError("invalid_content_length") from exc
    body = bytearray()
    for chunk in response.iter_content(chunk_size=16_384):
        body.extend(chunk)
        if len(body) > maximum:
            raise GOIACollectionError("document_too_large")
    return bytes(body)


def _connected_peer_ip(response: requests.Response) -> str:
    explicit = getattr(response, "peer_ip", None)
    if explicit:
        return str(explicit)
    try:
        return str(response.raw._connection.sock.getpeername()[0])
    except (AttributeError, IndexError, TypeError) as exc:
        raise GOIACollectionError("connected_peer_unavailable") from exc


def _validate_connected_peer(response: requests.Response, target: dict) -> None:
    peer = _connected_peer_ip(response)
    try:
        address = ipaddress.ip_address(peer)
    except ValueError as exc:
        raise GOIACollectionError("connected_peer_invalid") from exc
    if not address.is_global:
        raise GOIACollectionError("connected_peer_must_be_public")
    if peer not in set(target.get("resolved_addresses") or []):
        raise GOIACollectionError("connected_peer_resolution_mismatch")


def fetch_document(
    url: str,
    *,
    session=requests,
    allowed_hosts: set[str] | None = None,
    maximum_bytes: int = MAX_DOCUMENT_BYTES,
) -> CollectedDocument:
    target = validate_collection_url(url, allowed_hosts=allowed_hosts)
    response = session.get(
        url,
        headers={"User-Agent": GOIA_USER_AGENT, "Accept": ", ".join(sorted(ALLOWED_CONTENT_TYPES))},
        timeout=(5, 15),
        allow_redirects=False,
        stream=True,
    )
    _validate_connected_peer(response, target)
    if 300 <= response.status_code < 400:
        raise GOIACollectionError("redirect_not_followed")
    if response.status_code != 200:
        raise GOIACollectionError(f"unexpected_http_status_{response.status_code}")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise GOIACollectionError("unsupported_content_type")
    body = _read_bounded(response, maximum=maximum_bytes)
    return CollectedDocument(
        url=url,
        content_type=content_type,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
    )


def robots_allows(
    url: str,
    *,
    session=requests,
    allowed_hosts: set[str] | None = None,
) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        document = fetch_document(
            robots_url,
            session=session,
            allowed_hosts=allowed_hosts,
            maximum_bytes=500_000,
        )
    except GOIACollectionError:
        return False
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.parse(document.body.decode("utf-8", errors="strict").splitlines())
    except UnicodeDecodeError:
        return False
    return parser.can_fetch(GOIA_USER_AGENT, url)


def fetch_allowed_document(
    url: str,
    *,
    session=requests,
    allowed_hosts: set[str] | None = None,
) -> CollectedDocument:
    validate_collection_url(url, allowed_hosts=allowed_hosts)
    if not robots_allows(url, session=session, allowed_hosts=allowed_hosts):
        raise GOIACollectionError("robots_disallowed_or_unavailable")
    return fetch_document(url, session=session, allowed_hosts=allowed_hosts)


def extract_sitemap_urls(
    document: CollectedDocument,
    *,
    allowed_hosts: set[str] | None = None,
) -> list[str]:
    lowered = document.body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise GOIACollectionError("unsafe_xml_declaration")
    try:
        root = ElementTree.fromstring(document.body)
    except ElementTree.ParseError as exc:
        raise GOIACollectionError("invalid_sitemap_xml") from exc
    urls: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "loc" or not element.text:
            continue
        candidate = urljoin(document.url, element.text.strip())
        validate_collection_url(candidate, allowed_hosts=allowed_hosts)
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return urls


def _json_ld_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _json_ld_nodes(item)
    elif isinstance(value, dict):
        graph = value.get("@graph")
        if graph is not None:
            yield from _json_ld_nodes(graph)
        yield value


def _prospect_url(value: object) -> tuple[str, str] | None:
    raw = str(value or "").strip()
    if not raw or len(raw) > 2_000:
        return None
    parsed = urlparse(raw)
    hostname = str(parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    return raw, hostname


def extract_partner_hints(document: CollectedDocument) -> list[dict]:
    """Extract merchant evidence without fetching or trusting discovered domains."""
    if document.content_type not in {"text/html", "application/xhtml+xml"}:
        raise GOIACollectionError("html_document_required")
    soup = BeautifulSoup(document.body, "html.parser")
    hints: dict[tuple[str, str], dict] = {}
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts[:MAX_JSON_LD_SCRIPTS]:
        raw = script.string or script.get_text()
        if not raw or len(raw.encode("utf-8")) > 250_000:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for node in _json_ld_nodes(payload):
            node_type = node.get("@type")
            types = {node_type} if isinstance(node_type, str) else set(node_type or [])
            commercial_types = types & {"Product", "SoftwareApplication", "Service"}
            if not commercial_types:
                continue
            offers = node.get("offers")
            offer_items = offers if isinstance(offers, list) else [offers]
            for offer in offer_items:
                if not isinstance(offer, dict):
                    continue
                seller = offer.get("seller")
                seller = seller if isinstance(seller, dict) else {}
                candidate = _prospect_url(seller.get("url")) or _prospect_url(offer.get("url"))
                if candidate is None:
                    continue
                url, domain = candidate
                name = str(seller.get("name") or "").strip()[:300]
                currency = str(offer.get("priceCurrency") or "").strip().upper()[:3]
                evidence_type = "schema_offer_seller" if seller.get("url") else "schema_offer_url"
                key = (domain, evidence_type)
                hints[key] = {
                    "domain": domain,
                    "name": name,
                    "url": url,
                    "source_url": document.url,
                    "source_sha256": document.sha256,
                    "evidence_type": evidence_type,
                    "kinds": sorted(commercial_types),
                    "currencies": [currency] if len(currency) == 3 else [],
                    "network_access_performed": False,
                    "outreach_authorized": False,
                }
                if len(hints) >= MAX_PARTNER_HINTS:
                    return list(hints.values())
    return list(hints.values())


def extract_commercial_json_ld(document: CollectedDocument) -> list[dict]:
    if document.content_type not in {"text/html", "application/xhtml+xml"}:
        raise GOIACollectionError("html_document_required")
    soup = BeautifulSoup(document.body, "html.parser")
    extracted: list[dict] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts[:MAX_JSON_LD_SCRIPTS]:
        raw = script.string or script.get_text()
        if not raw or len(raw.encode("utf-8")) > 250_000:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for node in _json_ld_nodes(payload):
            node_type = node.get("@type")
            types = {node_type} if isinstance(node_type, str) else set(node_type or [])
            if types & {"Product", "SoftwareApplication", "Service"}:
                extracted.append(
                    {
                        "source_url": document.url,
                        "source_sha256": document.sha256,
                        "schema_types": sorted(types),
                        "name": str(node.get("name") or "")[:500],
                        "url": str(node.get("url") or document.url)[:2_000],
                        "offers": node.get("offers"),
                        "extraction_method": "json_ld",
                        "review_required": True,
                    }
                )
    return extracted[:500]


def extract_native_catalog_candidates(
    document: CollectedDocument,
    *,
    provider_id: str,
    now: int,
) -> list[dict]:
    if document.content_type not in {"application/json", "application/ld+json"}:
        raise GOIACollectionError("native_catalog_json_required")
    try:
        payload = json.loads(document.body)
        catalog = NativeCatalogDocument.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise GOIACollectionError("invalid_native_catalog") from exc
    if catalog.provider_id != provider_id:
        raise GOIACollectionError("native_catalog_provider_mismatch")
    if catalog.generated_at > now + 300:
        raise GOIACollectionError("native_catalog_generated_in_future")
    if catalog.expires_at <= now:
        raise GOIACollectionError("native_catalog_expired")
    source_host = str(urlparse(document.url).hostname or "").lower()
    candidates = []
    schema_type = {
        "software": "SoftwareApplication",
        "api": "SoftwareApplication",
        "hosting": "Service",
        "digital_service": "Service",
    }
    availability = {
        "available": "https://schema.org/InStock",
        "limited": "https://schema.org/LimitedAvailability",
        "unavailable": "https://schema.org/OutOfStock",
    }
    for offer in catalog.offers:
        canonical_url = str(offer.canonical_url)
        if str(urlparse(canonical_url).hostname or "").lower() != source_host:
            raise GOIACollectionError("native_catalog_offer_domain_mismatch")
        candidates.append(
            {
                "source_url": document.url,
                "source_sha256": document.sha256,
                "schema_types": [schema_type[offer.kind]],
                "goia_kind": offer.kind,
                "goia_offer_id": offer.offer_id,
                "name": offer.title,
                "url": canonical_url,
                "offers": {
                    "@type": "Offer",
                    "price": offer.total_price,
                    "priceCurrency": offer.currency,
                    "availability": availability[offer.availability],
                },
                "extraction_method": "partner_catalog",
                "catalog_generated_at": catalog.generated_at,
                "catalog_expires_at": catalog.expires_at,
                "review_required": True,
            }
        )
    return candidates


def extract_provider_manifest(
    document: CollectedDocument,
    *,
    provider_id: str,
) -> MerchantProviderManifest:
    if document.content_type not in {"application/json", "application/ld+json"}:
        raise GOIACollectionError("provider_manifest_json_required")
    try:
        payload = json.loads(document.body)
        manifest = MerchantProviderManifest.model_validate(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise GOIACollectionError("invalid_provider_manifest") from exc
    if manifest.provider_id != provider_id:
        raise GOIACollectionError("provider_manifest_provider_mismatch")
    source_host = str(urlparse(document.url).hostname or "").lower().rstrip(".")
    website_host = str(manifest.website.host or "").lower().rstrip(".")
    if source_host != website_host:
        raise GOIACollectionError("provider_manifest_domain_mismatch")
    if str(manifest.partnership_discovery.manifest_url) != document.url:
        raise GOIACollectionError("provider_manifest_source_mismatch")
    return manifest
