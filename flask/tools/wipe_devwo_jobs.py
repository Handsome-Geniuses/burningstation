from lib.database import delete_meter_jobs_for_work_order


DEV_WORK_ORDER = 999999999


def wipe_devwo_jobs() -> int:
    return delete_meter_jobs_for_work_order(DEV_WORK_ORDER)


if __name__ == "__main__":
    # Usage: PYTHONPATH=. python wipe_devwo_jobs.py
    count = wipe_devwo_jobs()
    print(f"Deleted {count} meter_job rows for work_order {DEV_WORK_ORDER}.")
