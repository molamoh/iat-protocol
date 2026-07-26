"""Separate GOIA collection worker; disabled unless explicitly enabled."""

from __future__ import annotations

import json
import os
import time

from iat.goia.collector import (
    GOIACollectionError,
    extract_commercial_json_ld,
    extract_native_catalog_candidates,
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
    recover_stale_collection_jobs,
    schedule_due_quarantine_retries,
    seed_due_catalog_sources,
    store_review_candidates,
)
from iat.goia.autonomous_review import autonomously_review_candidate


def collection_enabled() -> bool:
    return os.getenv("IAT_GOIA_COLLECTION_ENABLED", "false").strip().lower() == "true"


def process_one_job() -> dict:
    recovery = recover_stale_collection_jobs()
    retries = schedule_due_quarantine_retries()
    source_discovery = seed_due_catalog_sources()
    job = claim_collection_job()
    if job is None:
        return {
            "status": "idle",
            "recovery": recovery,
            "quarantine_retries": retries,
            "source_discovery": source_discovery,
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
            }
        if job.get("job_type") == "catalog_json":
            candidates = extract_native_catalog_candidates(
                document,
                provider_id=job["provider_id"],
                now=int(time.time()),
            )
        else:
            candidates = extract_commercial_json_ld(document)
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
            "recovery": recovery,
            "quarantine_retries": retries,
            "source_discovery": source_discovery,
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
        }


def main() -> int:
    if not collection_enabled():
        print(json.dumps({"status": "disabled", "reason": "explicit_enable_required"}))
        return 0
    init_goia_tables()
    interval = max(5, min(int(os.getenv("IAT_GOIA_WORKER_INTERVAL_SECONDS", "30")), 300))
    while True:
        result = process_one_job()
        print(json.dumps(result, sort_keys=True))
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
