import traceback
from lib.meter.ssh_meter import SSHMeter
from lib.automation.tests import PROGRAM_REGISTRY
from lib.automation.shared_state import SharedState
from lib.meter.lifecycle import session_for, MeterInterrupted
from lib.automation.recovery import run_subtest, await_meter

def run_test_job(
    meter: SSHMeter,
    program_name: str,
    automation_kwargs: dict,
    shared: SharedState,
    log: bool = True,
    verbose: bool = False,
):
    """Dispatch existing subtests with shared interruption handling.

    The supervisor is the only continuous journal reader. Full cycles apply
    run_subtest per stage; this function supplies the same wrapper for a single
    requested test. It never imports or starts the retired listener/monitors.
    """
    if automation_kwargs.pop("monitors", None):
        shared.log("Ignoring retired monitors option; subtests validate their own results", console=True)
    session = session_for(meter)
    if session is not None:
        with session.condition:
            session.subscribers.add(shared)
        shared.log(f"Continuous journal session={session.id}; path={session.supervisor.log_path if session.supervisor else None}")
        if session.supervisor:
            shared.extras["meter_session"] = {"id": session.id, "journal_path": session.supervisor.log_path,
                                               "start_cursor": session.supervisor.cursor}
    try:
        if program_name not in PROGRAM_REGISTRY:
            raise ValueError(f"Unknown test: {program_name!r}")
        test_func = PROGRAM_REGISTRY[program_name]
        if program_name in {"cycle_all", "all tests", "physical_cycle_all", "operator_cycle_all"}:
            test_func(meter, shared=shared, **automation_kwargs)
        else:
            uses_robot = (program_name.startswith("test_robot") or program_name == "robot_display_brightness"
                          or automation_kwargs.get("payment_type") == "robot_contactless")
            pose_epoch = session.epoch if session is not None else None

            def prepare_attempt(attempt):
                nonlocal pose_epoch
                if uses_robot and (attempt or (session is not None and pose_epoch != shared.attempt_epoch)):
                    from lib.robot.robot_client import RobotClient
                    from lib.automation.tests.physical_cycle_all import run_and_retrieve_charuco
                    meter.set_brightness(15)
                    automation_kwargs["charuco_frame"] = run_and_retrieve_charuco(RobotClient(), meter, shared, 30)
                    pose_epoch = shared.attempt_epoch

            run_subtest(meter, shared, program_name,
                        lambda: test_func(meter, shared=shared, **automation_kwargs),
                        robot=uses_robot, prepare=prepare_attempt)
        await_meter(meter, shared)

    except MeterInterrupted as exc:
        shared.extras["meter_disruption"] = str(exc)
        if shared.current_device:
            shared.device_results[shared.current_device] = "interrupted"
        shared.last_error = str(exc)
        shared.stop_event.set()
        shared.log(str(exc), console=True)
    except Exception as exc:
        shared.log(f"Error running test {program_name!r} on {meter.host}: {type(exc).__name__}: {exc}", console=True)
        for line in traceback.format_exc().splitlines():
            shared.log(line, console=True)
        
        shared.last_error = str(exc)
        shared.stop_event.set()

    finally:
        if shared.abort_event.is_set() and getattr(meter, "is_mock", False):
            virtual = getattr(meter, "virtual_meter", None)
            if virtual is not None:
                virtual.finish(False)
        if session is not None:
            with session.condition:
                session.subscribers.discard(shared)
            if session.supervisor:
                shared.extras["meter_session"]["end_cursor"] = session.supervisor.cursor
        # This runs before jobs.job_done() can switch completed cycle groups to
        # results mode. clear_banner_text() does not change the current UI mode,
        # so cleanup also remains safe if that ordering changes in the future.
        try:
            meter.clear_banner_text()
        except Exception as exc:
            shared.log(
                f"Unable to clear the completed test banner on {meter.host}: {exc}",
                console=True,
            )
