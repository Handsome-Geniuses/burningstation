import { cn } from "@/lib/utils";
import { PANEL, PANEL_HEADER } from "./shared";
import { ManualAutoBox } from "./manual-auto-box";
import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import { flask } from "@/lib/flask";
import { BAY_GUESS_BAY_STARTS, SystemState } from "../../store/system";
import { Separator } from "@/components/ui/separator";
import * as React from "react";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { useServerSettings } from "../settings/server-store";

type SectionDividerProps = {
    label: string
    className?: string
}

export const SectionDivider = ({ label, className }: SectionDividerProps) => {
    return (
        <div className={`flex items-center gap-3 ${className ?? ""}`}>
            <Separator className="flex-1" />
            <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">
                {label}
            </span>
            <Separator className="flex-1" />
        </div>
    )
}

function getExactBay1GuessIp(bayGuess: SystemState["bayGuess"]) {
    const bay1Start = BAY_GUESS_BAY_STARTS[1]
    const bay1Guess = bayGuess.slice(bay1Start, bay1Start + 3)
    const [ip] = bay1Guess

    return ip && bay1Guess.every(slot => slot === ip) ? ip : undefined
}

function getExactGuessIpAt(bayGuess: SystemState["bayGuess"], start: number) {
    const guess = bayGuess.slice(start, start + 3)
    const [ip] = guess

    return ip && guess.every(slot => slot === ip) ? ip : undefined
}

function getExactLoadGuessIp(bayGuess: SystemState["bayGuess"]) {
    return getExactGuessIpAt(bayGuess, 0) ?? getExactGuessIpAt(bayGuess, 1)
}

function getBooleanOption(
    settings: Record<string, unknown> | null | undefined,
    sectionKey: string,
    optionKey: string,
    fallback: boolean
) {
    if (!settings) return fallback
    const section = settings[sectionKey]
    if (!section || typeof section !== "object" || Array.isArray(section)) return fallback

    const value = (section as Record<string, unknown>)[optionKey]
    return typeof value === "boolean" ? value : fallback
}

async function loadMeter(systemState: SystemState, meterIp: string) {
    await flask.handleAction('station', 'load', { type: 'L', meter_ip: meterIp })

    if (systemState.mode === "auto") {
        flask.handleAction('program', 'neutral', {
            program: 'start_passive_job',
            meter_ip: meterIp,
        })
    }
}

function startPhysicalJob(meterIp: string) {
    flask.handleAction('program', 'manual', {
        program: 'start_physical_job',
        meter_ip: meterIp,
    })
}

const JobsDivider = ({ isManual }: { isManual: boolean }) => {
    return (
        <div>
            <SectionDivider label="jobs" className="pt-4" />
            <div className="grid grid-cols-2 gap-2 pt-2">
                <Button variant="outline" onClick={() => flask.handleAction('program', 'manual', { program: 'start_passive_job' })} disabled={!isManual}>
                    passive
                </Button>
                <Button variant="outline" onClick={() => flask.handleAction('program', 'manual', { program: 'start_physical_job' })} disabled={!isManual}>
                    physical
                </Button>
            </div>
        </div>
    )
}

const RobotDivider = ({ isManual }: { isManual: boolean }) => {
    const robotShutDown = async () => {
        notify.info("[test] shut down")
        flask.handleAction('station', 'robot', { "wdyw": "home" })
    }
    const robotSafeHome = async () => {
        notify.info("[test] robot safe home")
        flask.handleAction('station', 'robot', { "wdyw": "home" })
    }
    return (
        <div>
            <SectionDivider label="robot tools" className="pt-4" />
            <div className="grid grid-cols-2 gap-2 pt-2">
                <Button onClick={robotShutDown} variant="outline" disabled={!isManual}>
                    shut down
                </Button>
                <Button onClick={robotSafeHome} variant="outline" disabled={!isManual} >
                    safe home
                </Button>
            </div>
        </div>
    )
}

const MeterMiddlePhysical = ({
    physicalCheck,
    systemState,
}: {
    physicalCheck: boolean
    systemState: SystemState
}) => {
    const [metersReady, setMetersReady] = React.useState<string[]>([])
    const [meterIndex, setMeterIndex] = React.useState<number | null>(null)
    const middleMeterIp = meterIndex === null ? undefined : metersReady[meterIndex]
    const isManual = systemState.mode == "manual"
    const isPhysicalRunning = Object.values(systemState.meters).some(
        meter => meter.current_action === "physical_cycle_all"
    )
    const isReadyForPhysical = isManual && systemState.mds[3] && systemState.mds[4] && systemState.mds[5] && !isPhysicalRunning

    const blinkMeter = (meter_ip: string) => {
        flask.handleAction('program', 'neutral', { program: 'identify_until', meter_ip })
    }

    const stopBlinkMeter = (meter_ip?: string) => {
        if (!meter_ip) return
        return flask.handleAction('program', 'neutral', { program: 'identify_stop', meter_ip })
    }

    const stopMiddleMeterDialog = async () => {
        await stopBlinkMeter(middleMeterIp)
        setMeterIndex(null)
        setMetersReady([])
    }

    const handleMiddleNo = async () => {
        if (meterIndex === null) return
        await stopBlinkMeter(middleMeterIp)
        const nextIndex = meterIndex + 1
        const nextMeterIp = metersReady[nextIndex]

        if (!nextMeterIp) {
            notify.info("Nothing to run physical?")
            return stopMiddleMeterDialog()
        }

        setMeterIndex(nextIndex)
        blinkMeter(nextMeterIp)
    }

    const handleMiddleYes = async () => {
        if (!middleMeterIp) return

        notify.success("Middle found")
        await stopBlinkMeter(middleMeterIp)
        startPhysicalJob(middleMeterIp)

        setMeterIndex(null)
        setMetersReady([])
    }

    const handleClick1 = () => {
        if (isPhysicalRunning) return notify.info("Physical already running")

        const mds = systemState.mds

        // check if the middle three is on
        if (!mds[3] || !mds[4] || !mds[5])
            return notify.error("Middle bay not occupied!")

        // search for meters that are in "ready" state. assume [0]th is oldest
        const meters = Object.values(systemState.meters).filter(
            meter => meter.status === "ready"
        )
        if (!meters.length) return notify.info("No ready meters found")

        const bay1GuessIp = getExactBay1GuessIp(systemState.bayGuess)

        if (!physicalCheck && bay1GuessIp && meters.some(meter => meter.ip === bay1GuessIp)) {
            startPhysicalJob(bay1GuessIp)
            return
        }

        const prioritizedMeters = bay1GuessIp && meters.some(meter => meter.ip === bay1GuessIp)
            ? [
                ...meters.filter(meter => meter.ip === bay1GuessIp),
                ...meters.filter(meter => meter.ip !== bay1GuessIp),
            ]
            : meters

        // loop thru and blink, asking the user if the blinking one is in the middle
        // blinking should persist until an action is done.
        // while blinking, meter should also go into busy state i think. 
        // open a dialog with question, is the blinking meter in the middle? yes, no, cancel
        // if cancel can stop
        // if no, go to next meter
        // if no more meter, treat like stop
        // if yes, move to next step
        setMetersReady(prioritizedMeters.map(meter => meter.ip))
        setMeterIndex(0)
        blinkMeter(prioritizedMeters[0].ip)
    }

    return (
        <>
            <Button
                onClick={handleClick1}
                variant="outline"
                disabled={!isManual || isPhysicalRunning}
                className={cn(
                    "text-xs",
                    isReadyForPhysical && "animate-pulse border-primary bg-orange-500/40 hover:bg-orange-500/60 text-primary [animation-duration:0.5s]"
                )}
            >
                Physical
            </Button>
            <Dialog open={meterIndex !== null} onOpenChange={(open) => { if (!open) void stopMiddleMeterDialog() }}>
                <DialogContent className="w-fit">
                    <DialogHeader>
                        <DialogTitle>blinking in middle?</DialogTitle>
                        <DialogDescription>
                            {/* {middleMeter ? `${middleMeter.hostname} (${middleMeter.ip})` : ""} */}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={stopMiddleMeterDialog}>Cancel</Button>
                        <Button variant="outline" onClick={handleMiddleNo} debounceSeconds={1}>No</Button>
                        <Button type="button" onClick={() => { void handleMiddleYes() }}>Yes</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}

export function LoadMeter({
    loadCheck,
    systemState,
}: {
    loadCheck: boolean
    systemState: SystemState
} & React.ComponentProps<"div">) {
    const [metersReady, setMetersReady] = React.useState<string[]>([])
    const [meterIndex, setMeterIndex] = React.useState<number | null>(null)
    const mds = systemState.mds
    const isReadyToLoad = (mds[0] || mds[1]) && !mds[2]
    const loadingMeterIp = meterIndex === null ? undefined : metersReady[meterIndex]

    const blinkMeter = (meter_ip: string) => {
        flask.handleAction('program', 'neutral', { program: 'identify_until', meter_ip })
    }

    const stopBlinkMeter = (meter_ip?: string) => {
        if (!meter_ip) return
        return flask.handleAction('program', 'neutral', { program: 'identify_stop', meter_ip })
    }

    const stopLoadMeterDialog = async () => {
        await stopBlinkMeter(loadingMeterIp)
        setMeterIndex(null)
        setMetersReady([])
    }

    const handleLoadNo = async () => {
        if (meterIndex === null) return
        await stopBlinkMeter(loadingMeterIp)
        const nextIndex = meterIndex + 1
        const nextMeterIp = metersReady[nextIndex]

        if (!nextMeterIp) {
            notify.info("Nothing to load?")
            return stopLoadMeterDialog()
        }

        setMeterIndex(nextIndex)
        blinkMeter(nextMeterIp)
    }

    const handleLoadYes = async () => {
        if (!loadingMeterIp) return

        await stopBlinkMeter(loadingMeterIp)
        await loadMeter(systemState, loadingMeterIp)

        setMeterIndex(null)
        setMetersReady([])
    }

    const handleClick = () => {
        if (!isReadyToLoad) {
            notify.info("nothing to load")
            return
        }

        const meters = Object.values(systemState.meters)
            .filter(meter => meter.status === "ready")
            .reverse()

        if (!meters.length) return notify.info("No ready meters found")

        const loadGuessIp = getExactLoadGuessIp(systemState.bayGuess)
        if (!loadCheck && loadGuessIp && meters.some(meter => meter.ip === loadGuessIp)) {
            void loadMeter(systemState, loadGuessIp)
            return
        }

        setMetersReady(meters.map(meter => meter.ip))
        setMeterIndex(0)
        blinkMeter(meters[0].ip)
    }

    return (
        <>
            <Button
                variant="outline"
                className={cn(
                    "text-xs",
                    isReadyToLoad && "animate-pulse border-primary bg-orange-500/40 hover:bg-orange-500/60 text-primary [animation-duration:0.5s] transition-all"
                )}
                onClick={handleClick}
                disabled={false}
            >
                Load Meter
            </Button>
            <Dialog open={meterIndex !== null} onOpenChange={(open) => { if (!open) void stopLoadMeterDialog() }}>
                <DialogContent className="w-fit">
                    <DialogHeader>
                        <DialogTitle>blinking to load?</DialogTitle>
                        <DialogDescription />
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={stopLoadMeterDialog}>Cancel</Button>
                        <Button variant="outline" onClick={handleLoadNo} debounceSeconds={1}>No</Button>
                        <Button type="button" onClick={() => { void handleLoadYes() }}>Yes</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}

export function ControlsPanel({ systemState, className }: { systemState: SystemState } & React.ComponentProps<"div">) {
    const isManual = systemState.mode == "manual"
    const { values: serverSettings } = useServerSettings()
    const loadCheck = getBooleanOption(serverSettings, "flow", "load_check", true)
    const physicalCheck = getBooleanOption(serverSettings, "flow", "physical_check", true)

    return (
        <div className={cn(PANEL, className)}>
            <div className={PANEL_HEADER}>
                Control Panel
            </div>
            <div className="flex flex-col p-4">
                <SectionDivider label="MODE selector" />
                <ManualAutoBox />

                {/* <JobsDivider isManual={isManual} /> */}
                <RobotDivider isManual={isManual} />

                <SectionDivider label="programs" className="pt-4" />
                <div className="grid grid-cols-2 gap-2 pt-2">
                    <MeterMiddlePhysical physicalCheck={physicalCheck} systemState={systemState} />
                    <LoadMeter loadCheck={loadCheck} systemState={systemState} />
                </div>
            </div>
        </div>
    )
}
