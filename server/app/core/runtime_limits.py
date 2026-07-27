"""Shared actor time limits and their distributed lease invariants."""

PIPELINE_ACTOR_TIME_LIMIT_MS = 1_800_000
PUBLISH_ACTOR_TIME_LIMIT_MS = 900_000

# A lease must outlive its actor. The extra minute covers broker and cleanup overhead.
PIPELINE_SEMAPHORE_LEASE_SECONDS = PIPELINE_ACTOR_TIME_LIMIT_MS // 1000 + 60
PUBLISH_SEMAPHORE_LEASE_SECONDS = PUBLISH_ACTOR_TIME_LIMIT_MS // 1000 + 60
