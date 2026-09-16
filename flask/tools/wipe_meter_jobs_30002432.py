from lib.database import delete_meter_jobs_for_meter_identifier


METER_IDENTIFIER = "30002432"


def wipe_meter_jobs_30002432() -> int:
    return delete_meter_jobs_for_meter_identifier(METER_IDENTIFIER)


if __name__ == "__main__":
    # Usage: PYTHONPATH=. python wipe_meter_jobs_30002432.py
    count = wipe_meter_jobs_30002432()
    print(f"Deleted {count} meter_job rows for meter identifier {METER_IDENTIFIER}.")
