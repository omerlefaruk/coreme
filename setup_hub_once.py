from pathlib import Path
from pgserver import get_server
import os

pgdata = Path(r"C:\Users\Rau\Desktop\coreme\.tmp-pg")
server = get_server(pgdata)
dsn = server.get_uri(database="postgres")
print(f"DSN={dsn}")
print(f"postmaster={server.get_postmaster_info()}")

# Keep env for hub libs
os.environ["COREME_HUB_DSN"] = dsn
os.environ["COREME_HUB_DATA"] = r"C:\Users\Rau\Desktop\coreme\coreme-hub-data"
os.environ["COREME_HUB_OPS_TOKEN"] = "local-ops-token"

from coreme_hub.db import migrate
from coreme_hub.store import register_tree, list_schedules, create_schedule, validate_schedule_template
from coreme_hub.db import connect

print("migrating...")
migrate(dsn)
print("migrated ok")

data_dir = Path(r"C:\Users\Rau\Desktop\coreme\coreme-hub-data")
source = Path(r"C:\Users\Rau\Desktop\coreme\releases\koala-popup-0.1.0")
# register
from coreme_hub.store import register_tree
with connect(dsn) as conn:
    row = register_tree(conn, data_dir=data_dir, source=source)
    conn.commit()
    print(f"registered name={row['name']} version={row['version']} hash={row['content_hash']}")

# validate + create schedule
with connect(dsn) as conn:
    validate_schedule_template(conn, data_dir=data_dir, release_name="koala-popup", release_version="0.1.0", inputs={"query":"koala","message":"a"})
    print("template validated")
    try:
        row = create_schedule(conn, name="koala-every-1min", release_name="koala-popup", release_version="0.1.0", inputs={"query":"koala","message":"a"}, secret_names=[], required_tags=[], lease_seconds=900, interval_seconds=60, daily_utc=None)
        conn.commit()
        print(f"schedule created name={row['name']} interval={row['interval_seconds']} next_run={row['next_run_at']} enabled={row['enabled']}")
    except Exception as e:
        print(f"create failed: {e}")
        # try list existing
        from coreme_hub.store import list_schedules
        with connect(dsn) as conn2:
            rows = list_schedules(conn2)
            for r in rows:
                print(f"existing schedule {r}")

with connect(dsn) as conn:
    rows = list_schedules(conn)
    print(f"total schedules={len(rows)}")
    for r in rows:
        print(r)

# Keep server alive a moment to ensure commit
print("DONE - server held open for hub. DSN still valid in this process only.")
# Note: server will stop when this script exits if cleanup_mode=stop, but we printed DSN for external use.
# To keep server alive for hub serve, we need to keep this process running.
# For now we exit and let pgserver handle next invocation.
