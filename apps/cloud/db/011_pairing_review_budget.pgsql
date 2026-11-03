-- Distributed, owner-scoped pairing review rate limit; no IP, code or device secrets.
-- Reusable across Cloud app replicas. Budget saturates instead of overflowing.
CREATE TABLE pairing_review_budget (
  owner_sub text PRIMARY KEY CHECK(length(owner_sub) BETWEEN 1 AND 256),
  window_started_at timestamptz NOT NULL,
  attempts smallint NOT NULL CHECK(attempts BETWEEN 1 AND 11)
);
CREATE INDEX pairing_review_budget_stale ON pairing_review_budget(window_started_at);
