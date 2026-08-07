-- V032 — drop legacy duplicate tables that no code writes or reads.
--
--   * product    — superseded by `products` (the live product catalog the
--                  CRUD router and single-benefit evaluation read). The UW
--                  engine previously read this empty table, silently
--                  disabling product age/face eligibility checks; that
--                  reader now targets `products` (see uw_engine.py).
--   * batch_job  — superseded by `batch_jobs` (17 read/write sites).
--
-- Both tables are empty, have no triggers/views/FKs, and are not referenced
-- by any backend code. Confirmed before this migration was written.

DROP TABLE IF EXISTS public.batch_job;
DROP TABLE IF EXISTS public.product;
