-- V033 — force the seed-created super admin to rotate its password on first
-- login. V001a_seed_admin.sql bakes a fixed password hash into the migration
-- (same hash on every install); instead of trying to rotate that hash in a
-- migration that may already be applied, flag the account so the API tells
-- the client (password_change_required) and the next successful password set
-- clears the flag (auth.py reset-password / reset-password-confirm).

ALTER TABLE public.uw_user
    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- The account seeded by V001a_seed_admin.sql must rotate on first login.
UPDATE public.uw_user
   SET must_change_password = TRUE
 WHERE username = 'chakravarthi';
