import { useStoreContext } from "../../store"
import { ControlsPanel } from "./controls-panel"
import { cn } from "@/lib/utils"
import { PANEL, PANEL_HEADER } from "./shared"
import { Accordion, AccordionContent, AccordionItem } from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"

import { MeterSlots } from "./meter-slots"
import { AccordionTrigger } from "@radix-ui/react-accordion"
import { MeterInfo, MeterState, SystemState } from "../../store/system"
import React from "react"
import { CircleArrowLeft, CircleArrowRight } from "lucide-react"
import { meterRunBlinkUntil, meterRunDummy, meterRunPassive, meterRunPrintFw, meterStopBlink, meterStopPassive, meterStopPhysical } from "@/lib/ep"
// import { useALoading } from "@/hooks/useALoading"
import { useAsyncAction } from "@/hooks/useAsyncAction"


const ascii_meter = [
    `\
  ─┬─
┌──┴──┐
│ ╔══╗│
│ ╚══╝│
│  ┌┐ │
└──┬──┘
 ──┴──
`,
    `\
  ─┬─
┌──┴──┐
│╔══╗ │
│╚══╝ │
│ ┌┐  │
└──┬──┘
 ──┴──
`
]

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


export const BeltVisualizer = ({ systemState }: { systemState: SystemState }) => {
    const handlePointerUp = () => {
        flask.handleAction("override", "motor", { value_list: [0, 0, 0] })
        window.removeEventListener("pointerup", handlePointerUp)
    }
    const handlePointerDown = () => {
        window.addEventListener('pointerup', handlePointerUp)
    }
    const handleLeft = () => {
        flask.handleAction("override", "motor", { value_list: [2, 2, 2] })
        handlePointerDown()
    }
    const handleRight = () => {
        flask.handleAction("override", "motor", { value_list: [1, 1, 1] })
        handlePointerDown()
    }
    return (
        <AccordionItem key={"belt"} value={'belt'}>
            <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                Belt Visualizer
            </AccordionTrigger>
            <AccordionContent asChild className="p-0">
                <div className="relative w-full flex justify-center">
                    <MeterSlots classname="" />
                    <Button
                        className="absolute left-0 h-full flex items-center active:translate-y-0.5 hover:bg-unset active:bg-primary/10 z-1"
                        variant="ghost"
                        onPointerDown={handleLeft}
                        disabled={systemState.mode !== "manual"}
                    >
                        <CircleArrowLeft className="size-8 text-primary" />
                    </Button>
                    <Button
                        className="absolute right-0 h-full flex items-center active:translate-y-0.5 hover:bg-unset active:bg-primary/10 z-1"
                        variant="ghost"
                        onPointerDown={handleRight}
                        disabled={systemState.mode !== "manual"}
                    >
                        <CircleArrowRight className="size-8 text-primary" />
                    </Button>
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}


const AnimatedMeter = React.memo(
    ({ busy }: { busy: boolean }) => {
        const [frame, setFrame] = React.useState(0)

        React.useEffect(() => {
            if (!busy) {
                setFrame(0)
                return
            }

            const id = window.setInterval(() => {
                setFrame(prev => (prev + 1) % ascii_meter.length)
            }, 300)

            return () => clearInterval(id)
        }, [busy])

        return (
            <pre className="w-fit min-w-max whitespace-pre font-mono text-[10px] leading-tight tracking-normal text-[#f4a261] [font-variant-ligatures:none] [tab-size:2] md:text-sm">
                <code>{ascii_meter[frame]}</code>
            </pre>
        )
    }
)

type MeterProps = {
    meter: MeterState,
    onSelected: (meter: MeterState) => void
} & React.ComponentProps<'button'>
const Meter = ({
    meter,
    onSelected
}: MeterProps) => {
    const progress = meter.progress;
    const noProgress = (progress?.total ?? 0) <= 1;
    const percentage = noProgress || meter.status=="ready"
        ? 100
        : (progress!.current / progress!.total) * 100;

    return (
        <button
            key={meter.ip}
            type="button"
            className={cn(
                "rounded border p-2 text-left relative overflow-hidden",
            )}
            onClick={() => onSelected(meter)}
        >

            <div className="relative z-10">
                <div className="text-sm font-medium text-center leading-1">{meter.ip.slice(-3)}</div>
                <AnimatedMeter busy={meter.status === "busy"} />
                <div className="text-sm font-medium text-center leading-1">{meter.hostname}</div>
            </div>

            <div
                className={cn(
                    "absolute inset-x-0 bottom-0 z-1 transition-all duration-500 ease-in-out [animation-duration:1.0s]",
                    meter.status !== "ready" ? 'animate-pulse' : '',
                    meter.status === "ready"
                        ? "bg-green-100/50"
                        : noProgress
                            ? "bg-green-300"
                            : "bg-green-300",
                    meter.status === "error" && "bg-destructive/50"
                )}
                style={{ height: `${percentage}%`, minHeight: '2%' }}
            />
        </button>
    )
}



export const MeterManager = ({ systemState }: { systemState: SystemState }) => {
    const meters = Object.values(systemState.meters)
    const [selectedMeter, setSelectedMeter] = React.useState<MeterState | null>(null)
    const meter = meters.find(m => m.hostname === selectedMeter?.hostname);
    const { run, running } = useAsyncAction()
    const isMeterReady = meter?.status === "ready"
    const isPassiveRunning = meter?.current_action === "cycle_all"
    const isPhysicalRunning = meter?.current_action === "physical_cycle_all"
    const isBlinking = meter?.current_action === "blinking"

    // React.useEffect(()=>{
    //     console.log(systemState.mds)
    //     console.log(systemState.bayGuess)
    // },[systemState.mds])

    const handleDialogOpenChange = (open: boolean) => {
        if (open) return
        if (isBlinking) void meterStopBlink(meter?.ip)
        setSelectedMeter(null)
    }

    const bayGuessLabel = getBayGuessLabel(systemState.bayGuess, meter?.ip)
    let meterInfo = meter?.ip.concat(
        meter?.meter_type ? ` | ${meter?.meter_type}` : ' | ms-n/a',
        bayGuessLabel ? ` | ${bayGuessLabel}` : '',
    )
    let meterStatus = meter?.status.concat(
        meter?.current_action ? ` -- ${meter?.current_action}` : '',
        meter?.current_action && meter?.progress && meter.progress.total !== 0 ? ` -- ${meter.progress.current} / ${meter.progress.total}` : ''
    )

    return (
        <>
            <AccordionItem key={"meter"} value={'meter'}>
                <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                    Meter Manager
                </AccordionTrigger>
                <AccordionContent asChild className="p-0">
                    <div className="min-h-43 flex items-center">
                        {meters.length === 0 && (
                            <div className="px-4 py-3 text-sm text-muted-foreground self-start">
                                No connected meters
                            </div>
                        )}

                        <div className="flex flex-wrap items-center gap-2 p-2">
                            {meters.map((meter, index) => (
                                <Meter
                                    key={meter.ip}
                                    meter={meter}
                                    onSelected={setSelectedMeter}
                                // onClick={() => setSelectedMeter(meter)}
                                />
                            ))}
                        </div>
                    </div>
                </AccordionContent>
            </AccordionItem>

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
                            className={cn("border border-border", isBlinking&&'animate-pulse [animation-duration:0.5s]')}
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
        </>
    )
}

const STORAGE_KEY = "bs-controls-accordion-open-items"
export const ControlsTab = () => {
    const { systemState } = useStoreContext()
    const [openItem, setOpenItem] = React.useState("belt");
    const [openItems, setOpenItems] = React.useState<string[]>(["belt", "meter"]);

    React.useEffect(() => {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            try {
                setOpenItems(JSON.parse(saved));
            } catch {
            }
        }
    }, []);

    const handleValueChange = (value: string[]) => {
        setOpenItems(value);

        if (value.length > 0) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    };

    return (
        <div className="p-2 grid grid-cols-[1fr_auto] gap-2 ">
            <div>
                <Accordion type="multiple" className={cn(PANEL, "p-0 rounded-lg overflow-hidden")} value={openItems} onValueChange={handleValueChange}>
                    <BeltVisualizer systemState={systemState} />
                    <MeterManager systemState={systemState} />
                </Accordion>
            </div>
            <ControlsPanel systemState={systemState} />
        </div>
    )
}
