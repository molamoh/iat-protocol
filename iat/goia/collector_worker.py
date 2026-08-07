"""Separate GOIA collection worker; disabled unless explicitly enabled."""

from __future__ import annotations

import json
import os
import socket
import time

from iat.goia.collector import (
    GOIACollectionError,
    extract_commercial_json_ld,
    extract_native_catalog_candidates,
    extract_partner_hints,
    extract_provider_manifest,
    extract_sitemap_urls,
    fetch_allowed_document,
)
from iat.goia.repository import (
    GOIARepositoryError,
    claim_collection_job,
    complete_collection_job,
    enqueue_sitemap_pages,
    fail_collection_job,
    init_goia_tables,
    prepare_partner_proposals,
    record_worker_heartbeat,
    recover_stale_collection_jobs,
    record_provider_manifest_verification,
    refresh_partnership_opportunities,
    refresh_opportunity_prospect_links,
    refresh_partner_permissions,
    schedule_due_quarantine_retries,
    seed_due_catalog_sources,
    store_review_candidates,
    upsert_partner_hints,
)
from iat.goia.autonomous_review import autonomously_review_candidate
from iat.goia.prospecting import refresh_public_prospects


def collection_enabled() -> bool:
    return os.getenv("IAT_GOIA_COLLECTION_ENABLED", "false").strip().lower() == "true"


def worker_id() -> str:
    configured = os.getenv("IAT_GOIA_WORKER_ID", "").strip()
    return (configured or f"collector:{socket.gethostname()}")[:160]


def process_one_job() -> dict:
    recovery = recover_stale_collection_jobs()
    retries = schedule_due_quarantine_retries()
    source_discovery = seed_due_catalog_sources()
    partnership_intelligence = refresh_partnership_opportunities()
    partnership_permissions = refresh_partner_permissions()
    partnership_links = refresh_opportunity_prospect_links()
    partnership_proposals = prepare_partner_proposals()
    public_prospects = refresh_public_prospects()
    job = claim_collection_job()
    if job is None:
        return {
            "status": "idle",
            "recovery": recovery,
            "quarantine_retries": retries,
            "source_discovery": source_discovery,
            "partnership_intelligence": partnership_intelligence,
            "partnership_permissions": partnership_permissions,
            "partnership_links": partnership_links,
            "partnership_proposals": partnership_proposals,
            "public_prospects": public_prospects,
        }
    try:
        document = fetch_allowed_document(job["url"])
        if job.get("job_type") == "sitemap":
            urls = extract_sitemap_urls(document)
            pages = enqueue_sitemap_pages(sitemap_job=job, urls=urls)
            complete_collection_job(
                job["job_id"],
                result={
                    "source_url": document.url,
                    "source_sha256": document.sha256,
                    "discovered_url_count": len(urls),
                    "page_jobs": pages,
                    "publication_status": "discovery_only",
                },
            )
            return {
                "status": "completed",
                "job_id": job["job_id"],
                "job_type": "sitemap",
                "discovered_url_count": len(urls),
                "page_jobs_created": pages["created_count"],
                "recovery": recovery,
                "quarantine_retries": retries,
                "source_discovery": source_discovery,
                "partnership_intelligence": partnership_intelligence,
                "partnership_permissions": partnership_permissions,
                "partnership_proposals": partnership_proposals,
                "public_prospects": public_prospects,
            }
        if job.get("job_type") == "provider_manifest":
            manifest = extract_provider_manifest(
                document,
                provider_id=job["provider_id"],
            )
            verification = record_provider_manifest_verification(
                provider_id=job["provider_id"],
                manifest=manifest,
                source_url=document.url,
                source_sha256=document.sha256,
            )
            permissions = refresh_partner_permissions()
            complete_collection_job(
                job["job_id"],
                result={
                    "source_url": document.url,
                    "source_sha256": document.sha256,
                    "verification": verification,
                    "partnership_permissions": permissions,
                    "publication_status": "verification_only",
                },
            )
            return {
                "status": "completed",
                "job_id": job["job_id"],
                "job_type": "provider_manifest",
                "verification": verification,
                "partnership_permissions": permissions,
                "publication_status": "verification_only",
                "outreach_triggered": False,
                "partnership_proposals": partnership_proposals,
                "public_prospects": public_prospects,
            }
        if job.get("job_type") == "catalog_json":
            candidates = extract_native_catalog_candidates(
                document,
                provider_id=job["provider_id"],
                now=int(time.time()),
            )
        else:
            candidates = extract_commercial_json_ld(document)
        partner_result = {"stored_count": 0, "outreach_triggered": False}
        if job.get("job_type") not in {"catalog_json", "sitemap"}:
            partner_result = upsert_partner_hints(extract_partner_hints(document))
            refresh_opportunity_prospect_links()
        candidate_ids = store_review_candidates(
            job_id=job["job_id"],
            provider_id=job["provider_id"],
            candidates=candidates,
        )
        decisions = [
            autonomously_review_candidate(candidate_id)
            for candidate_id in candidate_ids
        ]
        approved_count = sum(item["status"] == "approved" for item in decisions)
        quarantined_count = sum(item["status"] == "quarantined" for item in decisions)
        complete_collection_job(
            job["job_id"],
            result={
                "source_url": document.url,
                "source_sha256": document.sha256,
                "candidate_count": len(candidates),
                "candidate_ids": candidate_ids,
                "approved_count": approved_count,
                "quarantined_count": quarantined_count,
                "publication_status": "autonomously_reviewed",
                "review_policy": "goia_autonomous_review_v1",
                "partner_prospects": partner_result,
            },
        )
        return {
            "status": "completed",
            "job_id": job["job_id"],
            "job_type": job.get("job_type") or "page",
            "candidate_count": len(candidates),
            "approved_count": approved_count,
            "quarantined_count": quarantined_count,
            "publication_status": "autonomously_reviewed",
            "partner_prospect_count": partner_result["stored_count"],
            "recovery": recovery,
            "quarantine_retries": retries,
            "source_discovery": source_discovery,
            "partnership_intelligence": partnership_intelligence,
            "partnership_permissions": partnership_permissions,
            "partnership_proposals": partnership_proposals,
            "public_prospects": public_prospects,
        }
    except (GOIACollectionError, GOIARepositoryError) as exc:
        fail_collection_job(job["job_id"], error_code=str(exc))
        return {
            "status": "failed",
            "job_id": job["job_id"],
            "error_code": str(exc),
            "recovery": recovery,
            "quarantine_retries": retries,
            "source_discovery": source_discovery,
            "partnership_intelligence": partnership_intelligence,
            "partnership_permissions": partnership_permissions,
            "partnership_proposals": partnership_proposals,
        }


def main() -> int:
    if not collection_enabled():
        print(json.dumps({"status": "disabled", "reason": "explicit_enable_required"}))
        return 0
    init_goia_tables()
    interval = max(5, min(int(os.getenv("IAT_GOIA_WORKER_INTERVAL_SECONDS", "30")), 300))
    identity = worker_id()
    started_at = int(time.time())
    cycle_count = 0
    record_worker_heartbeat(
        worker_id=identity,
        worker_type="collector",
        status="starting",
        cycle_count=cycle_count,
        started_at=started_at,
    )
    while True:
        cycle_count += 1
        try:
            result = process_one_job()
            heartbeat_status = {
                "idle": "idle",
                "failed": "degraded",
            }.get(result.get("status"), "working")
            record_worker_heartbeat(
                worker_id=identity,
                worker_type="collector",
                status=heartbeat_status,
                cycle_count=cycle_count,
                result=result,
                error_code=result.get("error_code"),
                started_at=started_at,
            )
        except Exception as exc:
            result = {
                "status": "degraded",
                "error_code": f"worker_cycle_error:{type(exc).__name__}",
            }
            record_worker_heartbeat(
                worker_id=identity,
                worker_type="collector",
                status="degraded",
                cycle_count=cycle_count,
                result=result,
                error_code=result["error_code"],
                started_at=started_at,
            )
        print(json.dumps(result, sort_keys=True))
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
