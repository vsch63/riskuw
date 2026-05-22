-- Runs on every startup to ensure admin credentials are always valid
UPDATE uw_user 
SET hashed_password = '$2b$12$JUwmWJ1gb0G9bf6zWqIbduT/w04r77B9lEilIYiUnPEdfh0At2YIe',
    is_active = true,
    is_deleted = false
WHERE username IN ('admin', 'chakravarthi', 'manager');
