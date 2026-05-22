import re, shutil, sys

filepath = "/opt/riskuw/backend/routers/premium_formula.py"

# Backup first
shutil.copy(filepath, filepath + ".bak")
print(f"Backup created: {filepath}.bak")

with open(filepath, "r") as f:
    content = f.read()

# ── Fix 3: Replace SELECT s.* in get_formula steps query ──────────────────────
old = '''            SELECT s.*, r.name AS scale_name
            FROM premium_formula_step s
            LEFT JOIN uw_rate_scale r ON r.id = s.scale_id
            WHERE s.formula_id = %s::uuid
            ORDER BY s.seq_no'''

new = '''            SELECT s.id, s.formula_id, s.seq_no, s.description,
                   s.operator, s.factor::float AS factor,
                   s.parameter_type,
                   s.user_value::float AS user_value,
                   s.user_label, s.scale_id,
                   r.name AS scale_name
            FROM premium_formula_step s
            LEFT JOIN uw_rate_scale r ON r.id = s.scale_id
            WHERE s.formula_id = %s::uuid
            ORDER BY s.seq_no'''

if old in content:
    content = content.replace(old, new)
    print("✅ Fix 3 applied: steps query now casts factor and user_value to float")
else:
    print("⚠️  Fix 3 pattern not found — already applied or file differs")
    print("    Check the file manually around get_formula()")

with open(filepath, "w") as f:
    f.write(content)

print("Done. Now run: docker cp then docker restart riskuw_fastapi")
