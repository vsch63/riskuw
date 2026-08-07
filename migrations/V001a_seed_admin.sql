-- Seed super_admin user (chakravarthi)
-- Password: Admin@1234  —  change after first production login
DO $$
DECLARE
  v_tenant_id UUID := 'bdf62338-1db0-416b-8eaa-d22cb60378c2';
  v_user_id   UUID := gen_random_uuid();
BEGIN
  INSERT INTO uw_user (
      id, username, email, hashed_password, full_name,
      role, is_active, is_deleted, tenant_id,
      created_by, updated_by, version
  ) VALUES (
      v_user_id,
      'chakravarthi',
      'chakravarthi@riskuw.com',
      '$2b$12$slxEricTJF/0Zv32YPtLHOHLfjTUnasEpYmwxB2CZdCBZJgIiGGD.',
      'Chakravarthi',
      'super_admin',
      true, false,
      v_tenant_id,
      'system', 'system', 1
  ) ON CONFLICT DO NOTHING;
END $$;
