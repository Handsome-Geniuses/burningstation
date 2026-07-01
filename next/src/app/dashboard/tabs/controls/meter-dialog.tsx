import { Button } from "@/components/ui/button"
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { useAsyncAction } from "@/hooks/useAsyncAction"
import { cn } from "@/lib/utils"
import {
    meterRunBlinkUntil,
    meterRunDummy,
    meterRunPassive,
    meterRunPrintFw,
    meterStopBlink,
    meterStopPassive,
    meterStopPhysical,
} from "@/lib/ep"

import { MeterState, SystemState } from "../../store/system"

const BAY_GUESS_LABELS: Record<string, string> = {
    "111000000000000": "__bay0",
    "011100000000000": "_bay0",
    "001110000000000": "bay0",
    "000111000000000": "bay0_",
    "000011100000000": "bay0_1",
    "000001110000000": "_bay1",
    "000000111000000": "bay1",
    "000000011100000": "bay1_",
    "000000001110000": "bay1_2",
    "000000000111000": "_bay2",
    "000000000011100": "bay2",
    "000000000001110": "bay2_",
    "000000000000111": "bay2__",
}

function getBayGuessLabel(bayGuess: SystemState["bayGuess"], meterIp?: string) {
    if (!meterIp) return undefined

    const key = bayGuess.map(ip => ip === meterIp ? "1" : "0").join("")
    return BAY_GUESS_LABELS[key]
}

type MeterDialogProps = {
    systemState: SystemState
    selectedMeter: MeterState | null
    onSelectedMeterChange: (meter: MeterState | null) => void
}

export const MeterDialog = ({
    systemState,
    selectedMeter,
    onSelectedMeterChange,
}: MeterDialogProps) => {
    const meters = Object.values(systemState.meters)
    const meter = meters.find(m => m.ip === selectedMeter?.ip)
    const { run, running } = useAsyncAction()
    const isMeterReady = meter?.status === "ready"
    const isPassiveRunning = meter?.current_action === "cycle_all"
    const isPhysicalRunning = meter?.current_action === "physical_cycle_all"
    const isBlinking = meter?.current_action === "blinking"

    const handleDialogOpenChange = (open: boolean) => {
        if (open) return
        if (isBlinking) void meterStopBlink(meter?.ip)
        onSelectedMeterChange(null)
    }

    const bayGuessLabel = getBayGuessLabel(systemState.bayGuess, meter?.ip)
    const meterInfo = meter?.ip.concat(
        meter?.meter_type ? ` | ${meter?.meter_type}` : " | ms-n/a",
        bayGuessLabel ? ` | ${bayGuessLabel}` : "",
    )
    const meterStatus = meter?.status.concat(
        meter?.current_action ? ` -- ${meter?.current_action}` : "",
        meter?.current_action && meter?.progress && meter.progress.total !== 0 ? ` -- ${meter.progress.current} / ${meter.progress.total}` : ""
    )

    return (
        <Dialog open={meter != undefined} onOpenChange={handleDialogOpenChange}>
            <DialogContent className="w-fit m-0 p-0 space-y-0 space-x-0 [&>button]:hidden gap-0">
                <DialogHeader className="gap-0 border-b p-4">
                    <DialogTitle>{meter?.hostname ?? "Meter"}</DialogTitle>
                    <div className="text-muted-foreground text-sm">
                        <div className="leading-none tracking-none">{meterInfo}</div>
                        <div className="leading-none tracking-none">{meterStatus}</div>
                    </div>
                </DialogHeader>

                <div className="min-w-80 p-4 grid grid-cols-3 gap-2">
                    {systemState.playground &&
                        <Button
                            variant="outline"
                            onClick={run(() => meterRunDummy(meter?.ip))}
                            disabled={running}
                        >
                            Dummy
                        </Button>
                    }

                    <Button
                        variant="outline"
                        onClick={run(() => meterRunPassive(meter?.ip))}
                        disabled={running || systemState.mode !== "manual" || !isMeterReady}
                    >
                        run passive
                    </Button>
                </div>

                <DialogFooter className="border-t p-4">
                    {systemState.playground && isPassiveRunning &&
                        <Button
                            variant="destructive"
                            onClick={run(() => meterStopPassive(meter?.ip))}
                            disabled={running}
                        >
                            passive
                        </Button>
                    }
                    {systemState.playground && isPhysicalRunning &&
                        <Button
                            variant="destructive"
                            onClick={run(() => meterStopPhysical(meter?.ip))}
                            disabled={running}
                        >
                            physical
                        </Button>
                    }
                    <Button
                        variant={isBlinking ? "destructive" : "outline"}
                        className={cn("border border-border", isBlinking && "animate-pulse [animation-duration:0.5s]")}
                        onClick={run(() => isBlinking ? meterStopBlink(meter?.ip) : meterRunBlinkUntil(meter?.ip, 60))}
                        disabled={running || (!isMeterReady && !isBlinking)}
                    >
                        Blink
                    </Button>
                    <Button
                        variant="outline"
                        onClick={run(() => meterRunPrintFw(meter?.ip))}
                        disabled={running || !isMeterReady}
                    >
                        Print
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
