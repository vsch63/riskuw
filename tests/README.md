# RiskUW — Automated Test Suite

Pytest-based automated test suite covering all functional scenarios.

## Structure

| File | Scenarios | Coverage |
|------|-----------|----------|
| `test_smoke.py` | 10 | Quick sanity — health, login, basic eval, letter |
| `test_auth.py` | 17 | Login, RBAC, token validation |
| `test_underwriting.py` | 18 | STP/Rated/Decline/Refer, ICD-10, validation |
| `test_batch.py` | 8 | Dry run, live run, records, pagination |
| `test_agent_portal.py` | 16 | Dashboard, products, submit, submissions |
| `test_workbench.py` | 11 | Queue, assign, notes, requirements, decision |
| `test_system_config.py` | 15 | Config, letter templates, products, integrations |
| `test_security.py` | 12 | SQL injection, XSS, rate limit, audit, isolation |
| `test_policy.py` | 9 | Policy number format, sequential, duplicate, list |
| `test_analytics.py` | 6 | Dashboard, analytics, reinsurance |
| **Total** | **122** | |

## Installation

```bash
cd /opt/riskuw/tests   # or wherever you save these files
pip install -r requirements_test.txt --break-system-packages
```

## Running Tests

```bash
# Run smoke tests first (30 seconds)
./run_tests.sh --smoke

# Run specific module
./run_tests.sh --auth
./run_tests.sh --uw
./run_tests.sh --agent
./run_tests.sh --security

# Run everything
./run_tests.sh --all

# Generate HTML report
./run_tests.sh --all --html

# Run against a different URL
RISKUW_BASE_URL=http://192.168.1.100:8001 ./run_tests.sh --all
```

## Direct pytest commands

```bash
# Run all tests
python3 -m pytest -v

# Run smoke tests only
python3 -m pytest -m smoke -v

# Run with HTML report
python3 -m pytest --html=report.html --self-contained-html

# Run specific test class
python3 -m pytest test_underwriting.py::TestICD10Integration -v

# Stop on first failure
python3 -m pytest -x -v

# Show 10 slowest tests
python3 -m pytest --durations=10
```

## Default Credentials

| Role | Username | Password |
|------|----------|----------|
| Admin | admin | Admin@1234 |
| Agent | agent001 | Agent@1234 |
| Broker | broker001 | Broker@1234 |

Override with environment variable:
```bash
export RISKUW_BASE_URL=http://your-server:8001
```

## Expected Results

A clean installation with sample data should show:
- **Smoke**: 10/10 pass
- **Auth**: 17/17 pass
- **Underwriting**: 18/18 pass (outcomes vary by product config)
- **Batch**: Some tests skip if no completed jobs exist
- **Workbench**: Some tests skip if no referred cases exist

## Notes

- Tests that create data use timestamped `applicant_ref` values to avoid conflicts
- Workbench and batch tests auto-create test cases if none exist
- Security tests check for vulnerabilities — some may return 400/422 instead of 200
- Run `--smoke` before any demo or client presentation
