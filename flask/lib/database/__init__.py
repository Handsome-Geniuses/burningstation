import psycopg
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
dbcs = secrets.DBCS
VERBOSE = secrets.VERBOSE

def insert_meter(hostname: str, system_version: int = -1, subsystem_version: int = -1, conn:None|psycopg.Connection=None):
    """
    Insert a meter into the 'meter' table.
    If a meter with the same hostname exists, update the provided columns and last_updated.
    Returns the inserted/updated row as a tuple.
    """
    # Build columns, placeholders, and values dynamically
    columns = ["hostname"]
    placeholders = ["%s"]
    values = [hostname]

    if system_version != -1:
        columns.append("system_version")
        placeholders.append("%s")
        values.append(system_version)

    if subsystem_version != -1:
        columns.append("subsystem_version")
        placeholders.append("%s")
        values.append(subsystem_version)

    # Build the ON CONFLICT SET clause (exclude hostname) and always update last_updated
    set_clause = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in columns if col != "hostname"
    )
    if set_clause:
        set_clause += ", "
    set_clause += "last_updated = LOCALTIMESTAMP"

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
            row = cur.fetchone()
            return row
    else:
        with psycopg.connect(dbcs) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(values))
                row = cur.fetchone()
                return row


def insert_meter_fws(meterId: int, firmwares: list[dict] | dict, conn:None|psycopg.Connection=None):
    """
    Insert multiple firmware records for a given meterId into 'meter_firmware'.
    If a record with the same (meter_id, name) exists, update version, modfunc, fullid, and last_updated.
    Returns the inserted/updated rows as a list of tuples.
    """
    if isinstance(firmwares, dict):
        firmwares = [
            {
                "name": name,
                "version": data["fw"],
                "modfunc": data["mod_func"],
                "fullid": data["full_id"],
            }
            for name, data in firmwares.items()
        ]

    if not firmwares:
        return []

    # Build the VALUES placeholders and parameters
    values_sql = []
    params = []
    for fw in firmwares:
        values_sql.append("(%s, %s, %s, %s, %s, LOCALTIMESTAMP)")
        params.extend([meterId, fw["name"], fw["version"], fw["modfunc"], fw["fullid"]])

    sql = f"""
        INSERT INTO meter_firmware (meter_id, name, version, modfunc, fullid, last_updated)
        VALUES {', '.join(values_sql)}
        ON CONFLICT (meter_id, name) DO UPDATE
        SET version = EXCLUDED.version,
            modfunc = EXCLUDED.modfunc,
            fullid = EXCLUDED.fullid,
            last_updated = LOCALTIMESTAMP
        RETURNING *;
    """
    if conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return rows
    else:
        with psycopg.connect(dbcs) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                return rows

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

    with psycopg.connect(dbcs) as conn:
        res_meter = insert_meter(hn, system_version, subsystem_version, conn=conn)
        meter_id = res_meter[0]
        res_meter_fws = insert_meter_fws(meter_id, modules, conn=conn)
        return res_meter, res_meter_fws




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
    client = SSHMeter("192.168.137.42")
    client.connect()
    insert_sshmeter(client)
    client.close()

