"""Separate GOIA collection worker; disabled unless explicitly enabled."""

from __future__ import annotations

import json
import os
import time

from iat.goia.collector import (
    GOIACollectionError,
    extract_commercial_json_ld,
    fetch_allowed_document,
)
from iat.goia.repository import (
    claim_collection_job,
    complete_collection_job,
    fail_collection_job,
    init_goia_tables,
    store_review_candidates,
)


def collection_enabled() -> bool:
    return os.getenv("IAT_GOIA_COLLECTION_ENABLED", "false").strip().lower() == "true"


def process_one_job() -> dict:
    job = claim_collection_job()
    if job is None:
        return {"status": "idle"}
    try:
        document = fetch_allowed_document(job["url"])
        candidates = extract_commercial_json_ld(document)
        candidate_ids = store_review_candidates(
            job_id=job["job_id"],
            provider_id=job["provider_id"],
            candidates=candidates,
        )
        complete_collection_job(
            job["job_id"],
            result={
                "source_url": document.url,
                "source_sha256": document.sha256,
                "candidate_count": len(candidates),
                "candidate_ids": candidate_ids,
                "publication_status": "review_required",
            },
        )
        return {
            "status": "completed",
            "job_id": job["job_id"],
            "candidate_count": len(candidates),
            "publication_status": "review_required",
        }
    except GOIACollectionError as exc:
        fail_collection_job(job["job_id"], error_code=str(exc))
        return {"status": "failed", "job_id": job["job_id"], "error_code": str(exc)}


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
