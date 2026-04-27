import psycopg
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
from typing import Optional
from datetime import date
import json

dbcs = secrets.DBCS
VERBOSE = secrets.VERBOSE


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


# ==============================================================================
# Job Insertion
# ==============================================================================
def insert_meter_jobs(
    meter_id: int,
    jobs: list[dict],
    jctl: str = "",
    conn: None | psycopg.Connection = None,
):
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
        values_sql.append("(%s, %s, %s, %s, %s)")
        params.extend(
            [meter_id, job["name"], job["status"], json.dumps(job.get("data", {})), jctl]
        )

    sql = f"""
        INSERT INTO meter_job (meter_id, name, status, data, jctl)
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


# ==============================================================================
# Job Retrieval 
# ==============================================================================
def retrieve_jobs(limit=10, offset=0, conn: None | psycopg.Connection = None,):
    """
    Retrieve meter jobs with pagination.
    Returns list of job rows.
    """
    # sql = """
    #     SELECT *
    #     FROM meter_job
    #     ORDER BY created_at DESC
    #     LIMIT %s OFFSET %s;
    # """
    sql = """
        SELECT
            mj.*,
            m.hostname
            FROM meter_job mj
            JOIN meter m ON mj.meter_id = m.id
            ORDER BY mj.created_at DESC
            LIMIT %s OFFSET %s;
        """
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit, offset))
            return cur.fetchall()

    with psycopg.connect(dbcs, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit, offset))
            return cur.fetchall()

def retrieve_jobs_filtered(
    limit: int = 10,
    date_start: Optional[date | str] = None,
    date_end: Optional[date | str] = None,
    meter_id: Optional[int] = None,
    status: Optional[str] = None,
    conn: None | psycopg.Connection = None,
):
    """
    Retrieve meter jobs with optional filters.

    Args:
        limit: number of entries, sorted by latest created_at first
        date_start: start date for created_at filter
        date_end: end date for created_at filter; if blank, uses date_start
        meter_id: optional meter_id filter
        status: optional status filter ('pass' or 'fail' or others if needed)
        conn: optional existing psycopg connection

    Returns:
        List of rows.
    """

    if date_start and not date_end:
        date_end = date_start

    query = """
        SELECT
            mj.*,
            m.hostname
        FROM meter_job mj
        JOIN meter m ON mj.meter_id = m.id
    """

    where_clauses = []
    params = []

    if date_start:
        where_clauses.append("mj.created_at >= %s")
        params.append(date_start)

    if date_end:
        # Make end-date inclusive for the whole day:
        # created_at < next day
        where_clauses.append("mj.created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_end)

    if meter_id is not None:
        where_clauses.append("mj.meter_id = %s")
        params.append(meter_id)

    if status:
        where_clauses.append("mj.status = %s")
        params.append(status)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += """
        ORDER BY mj.created_at DESC
        LIMIT %s;
    """
    params.append(limit)

    if conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    with psycopg.connect(dbcs, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


# ==============================================================================
# cleanup for testing
# ==============================================================================
def cleanup_test():
    with psycopg.connect(dbcs) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meter_firmware WHERE meter_id IN (SELECT id FROM meter WHERE hostname = %s);",
                ("test-host",),
            )
            cur.execute("DELETE FROM meter WHERE hostname = %s;", ("test-host",))
            conn.commit()


if __name__ == "__main__":
    # fake_jobs = [
    #     {"name": "job1", "status": "pass", "data": {"key1": "value1"}},
    #     {"name": "job2", "status": "fail", "data": {"key2": "value2"}},
    # ]
    import tools.mock

    # meter = SSHMeter("192.168.169.27")
    # insert_sshmeter(meter)
    # insert_meter_jobs(meter.db_id, fake_jobs)


    jobs = retrieve_jobs(limit=10, offset=0)
    for row in jobs: row.pop("jctl", None)
    print(json.dumps(jobs, indent=4, default=str))

