"""
job_queue.py — RiskUW background worker
Consumes jobs from Redis queue and processes notifications / async tasks.
Auto-installs redis if missing.
"""
import os, sys, json, time, logging, smtplib, ssl, subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(levelname)s %(message)s"
)
log = logging.getLogger("job_queue")

# ── Auto-install redis if missing ─────────────────────────────────────────────
try:
    import redis
except ImportError:
    log.info("redis module not found — installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "redis", "-q"])
    import redis
    log.info("redis installed OK")

# ── DB helper for notification_log updates ────────────────────────────────────
def get_db_conn():
    try:
        import psycopg2
        return psycopg2.connect(os.environ.get("DATABASE_URL", ""))
    except Exception as e:
        log.warning(f"DB connect failed: {e}")
        return None

def log_notification(event, recipient, status, error_code=None, error_msg=None):
    conn = get_db_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_log (event, recipient, status, error_code, error_msg, sent_at)
            VALUES (%s, %s, %s, %s, %s, now())
        """, (event, recipient, status, error_code, error_msg))
        conn.commit()
        cur.close()
    except Exception as e:
        log.warning(f"notification_log write failed: {e}")
    finally:
        conn.close()

# ── Email sender ──────────────────────────────────────────────────────────────
def send_email(job: dict):
    host     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port     = int(os.environ.get("SMTP_PORT", 587))
    user     = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    frm      = os.environ.get("SMTP_FROM", user)
    to       = job.get("to", "")
    subject  = job.get("subject", "RiskUW Notification")
    body     = job.get("body", "")
    event    = job.get("event", "DECISION_EMAIL")

    if not to:
        log.warning("send_email: no recipient — skipping")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = frm
        msg["To"]      = to
        msg.attach(MIMEText(body, "html"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(user, password)
            s.sendmail(frm, to, msg.as_string())

        log.info(f"✅ Email sent  to={to}  subject={subject}")
        log_notification(event, to, "SENT")

    except Exception as e:
        log.error(f"❌ Email failed to={to}: {e}")
        log_notification(event, to, "FAILED", "NOTIF_SEND_FAILED", str(e)[:500])

# ── Job dispatcher ────────────────────────────────────────────────────────────
def process_job(job: dict):
    jtype = job.get("type")
    log.info(f"Job received: type={jtype}")

    if jtype == "send_email":
        send_email(job)
    elif jtype == "ping":
        log.info("Pong — worker is alive")
    else:
        log.warning(f"Unknown job type: {jtype!r} — skipping")

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    log.info(f"RiskUW worker starting | Redis={redis_url}")

    # Retry Redis connection on startup (wait for redis container)
    r = None
    for attempt in range(10):
        try:
            r = redis.from_url(redis_url, decode_responses=True, socket_timeout=5)
            r.ping()
            log.info("✅ Connected to Redis")
            break
        except Exception as e:
            log.warning(f"Redis not ready (attempt {attempt+1}/10): {e} — retrying in 3s")
            time.sleep(3)

    if not r:
        log.error("❌ Could not connect to Redis after 10 attempts — exiting")
        sys.exit(1)

    log.info("Worker ready — listening on queue: riskuw:jobs")

    while True:
        try:
            item = r.blpop("riskuw:jobs", timeout=10)
            if item:
                _, raw = item
                try:
                    job = json.loads(raw)
                    process_job(job)
                except json.JSONDecodeError as e:
                    log.error(f"Invalid JSON in job: {e} | raw={raw[:200]}")
        except redis.exceptions.ConnectionError as e:
            log.error(f"Redis connection lost: {e} — reconnecting in 5s")
            time.sleep(5)
            try:
                r = redis.from_url(redis_url, decode_responses=True, socket_timeout=5)
            except Exception:
                pass
        except KeyboardInterrupt:
            log.info("Worker stopped")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
