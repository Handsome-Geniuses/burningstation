import psycopg
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
import json

dbcs = secrets.DBCS
VERBOSE = secrets.VERBOSE

# ==============================================================================
# Job Insertion
# ==============================================================================
def insert_meter_jobs(meter_id: int, jobs: list[dict], conn=None):
    """
    Bulk insert meter jobs (no upsert).
    Each job dict must contain: name, status, data.
    Returns list of inserted rows.
    """
    if not jobs:
        return []

    values_sql = []
    params = []

    for job in jobs:
        values_sql.append("(%s, %s, %s, %s)")
        params.extend(
            [meter_id, job["name"], job["status"], json.dumps(job.get("data", {}))]
        )

    sql = f"""
        INSERT INTO meter_job (meter_id, name, status, data)
        VALUES {", ".join(values_sql)}
        RETURNING *;
    """

    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    with psycopg.connect(dbcs) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def cleanup_test():
    with psycopg.connect(dbcs) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meter_firmware WHERE meter_id IN (SELECT id FROM meter WHERE hostname = %s);",
                ("test-host",),
            )
            cur.execute("DELETE FROM meter WHERE hostname = %s;", ("test-host",))
            conn.commit()

# ==============================================================================
# Meter Insertion
# ==============================================================================
def insert_meter(
    hostname: str,
    system_version: int = -1,
    subsystem_version: int = -1,
    meter_type: str = "",
    modules: dict | None = None,
    conn: None | psycopg.Connection = None,
):
    """
    Insert or update a meter in the 'meter' table.
    Upsert on hostname.
    Updates last_updated ALWAYS.
    """
    if modules is None:
        modules = {}

    columns = ["hostname", "meter_type", "modules"]
    placeholders = ["%s", "%s", "%s"]
    values = [hostname, meter_type, psycopg.types.json.Json(modules)]

    if system_version != -1:
        columns.append("system_version")
        placeholders.append("%s")
        values.append(system_version)

    if subsystem_version != -1:
        columns.append("subsystem_version")
        placeholders.append("%s")
        values.append(subsystem_version)

    # Build SET clause for update (exclude hostname because it's the PK)
    set_clause = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in columns if col != "hostname"
    )
    set_clause += ", last_updated = LOCALTIMESTAMP"

    sql = f"""
        INSERT INTO meter ({', '.join(columns)}, last_updated)
        VALUES ({', '.join(placeholders)}, LOCALTIMESTAMP)
        ON CONFLICT (hostname) DO UPDATE
        SET {set_clause}
        RETURNING *;
    """

    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(values))
            return cur.fetchone()

    with psycopg.connect(dbcs) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(values))
            return cur.fetchone()
        
def insert_sshmeter(meter: SSHMeter):
    """
    Insert meter and its firmwares into the database.
    Returns a tuple of (meter_row, [firmware_rows]).
    """
    hn = meter.hostname
    modules = meter.module_info
    svs = meter.system_versions
    system_version = svs.get("system_version", -1)
    subsystem_version = svs.get("system_sub_version", -1)
    meter_type = meter.meter_type

    # print(modules)
    with psycopg.connect(dbcs) as conn:
        res = insert_meter(
            hn, system_version, subsystem_version, meter_type, modules, conn=conn
        )
    
    meter.db_id = res[0]  # meter row id
    return res


if __name__ == "__main__":
    fake_jobs = [
        {"name": "job1", "status": "pass", "data": {"key1": "value1"}},
        {"name": "job2", "status": "fail", "data": {"key2": "value2"}},
    ]
    import tools.mock
    meter = SSHMeter("192.168.137.180")
    insert_sshmeter(meter)
    insert_meter_jobs(meter.db_id, fake_jobs)
