import psycopg

from lib.utils import secrets


def wipe_dummy_jobs() -> int:
    with psycopg.connect(secrets.DBCS) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meter_job WHERE lower(name) = lower(%s);",
                ("dummy",),
            )
            return cur.rowcount


if __name__ == "__main__":
    count = wipe_dummy_jobs()
    print(f"Deleted {count} dummy meter_job rows.")
