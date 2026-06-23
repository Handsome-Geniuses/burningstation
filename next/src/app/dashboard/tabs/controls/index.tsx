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
import { MeterState, SystemState } from "../../store/system"
import React from "react"
import { CircleArrowLeft, CircleArrowRight } from "lucide-react"
import { meterRunBlink, meterRunDummy, meterRunPrintFw } from "@/lib/ep"


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
                        className="absolute left-0 h-full flex items-center active:translate-y-0.5"
                        variant="ghost"
                        onPointerDown={handleLeft}
                        disabled={systemState.mode !== "manual"}
                    >
                        <CircleArrowLeft className="size-8 text-primary" />
                    </Button>
                    <Button
                        className="absolute right-0 h-full flex items-center active:translate-y-0.5"
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

export const MeterManager = ({ systemState }: { systemState: SystemState }) => {
    const meters = Object.values(systemState.meters)
    const [frame, setFrame] = React.useState(0)
    const [selectedMeter, setSelectedMeter] = React.useState<MeterState | null>(null)

    React.useEffect(() => {
        const id = window.setInterval(() => {
            setFrame((prev) => (prev + 1) % ascii_meter.length)
        }, 300)

        return () => window.clearInterval(id)
    }, [])

    const onBlink = async () => meterRunBlink(selectedMeter?.ip)
    const onPrintFw = async () => meterRunPrintFw(selectedMeter?.ip)
    const onDummy = async () => meterRunDummy(selectedMeter?.ip)


    return (
        <>
            <AccordionItem key={"meter"} value={'meter'}>
                <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                    Meter Manager
                </AccordionTrigger>
                <AccordionContent asChild className="p-0">
                    <>
                        {meters.length === 0 && (
                            <div className="px-4 py-3 text-sm text-muted-foreground">
                                No connected meters
                            </div>
                        )}

                        <div className="flex flex-wrap gap-2 p-2">
                            {meters.map((meter) => (
                                <button
                                    key={meter.ip}
                                    type="button"
                                    className={cn(
                                        "rounded border bg-accent/10 p-2 text-left",
                                        meter.status != "ready" ? '' : 'bg-accent'
                                    )}
                                    onClick={() => setSelectedMeter(meter)}
                                >
                                    <div className="text-sm font-medium text-center leading-1">{meter.ip.slice(-3)}</div>
                                    <pre className="w-fit min-w-max whitespace-pre font-mono text-[10px] leading-tight tracking-normal text-[#f4a261] [font-variant-ligatures:none] [tab-size:2] md:text-sm">
                                        <code>{ascii_meter[meter.status === "busy" ? frame : 0]}</code>
                                    </pre>
                                    <div className="text-sm font-medium text-center leading-1">{meter.hostname}</div>
                                </button>
                            ))}
                        </div>
                    </>
                </AccordionContent>
            </AccordionItem>

            <Dialog open={selectedMeter != null} onOpenChange={(open) => !open && setSelectedMeter(null)}>
                <DialogContent className="">
                    <DialogHeader className="gap-0">
                        <DialogTitle>{selectedMeter?.hostname ?? "Meter"}</DialogTitle>
                        <DialogDescription>
                            {selectedMeter ? `${selectedMeter.ip} | ${selectedMeter.meter_type || "unknown"}` : ""}
                        </DialogDescription>
                    </DialogHeader>

                    <div className="size-full">
                        {JSON.stringify(selectedMeter?.status)}
                    </div>

                    <DialogFooter>
                        {systemState.playground &&
                            <Button
                                variant="outline"
                                onClick={onDummy}
                            >
                                Dummy
                            </Button>
                        }
                        <Button
                            variant="outline"
                            onClick={onBlink}
                        >
                            Blink
                        </Button>
                        <Button
                            variant="outline"
                            onClick={onPrintFw}
                        >
                            Print
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}

const STORAGE_KEY = "bs-controls-accordion-open-item"
export const ControlsTab = () => {
    const { systemState } = useStoreContext()
    const [openItem, setOpenItem] = React.useState("belt");
    React.useEffect(() => {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            setOpenItem(saved);
        }
    }, []);
    const handleValueChange = (value: string) => {
        console.log(value)
        setOpenItem(value);

        if (value) {
            localStorage.setItem(STORAGE_KEY, value);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    };

    return (
        <div className="p-2 grid grid-cols-[1fr_auto] gap-2 ">
            <div>
                <Accordion
                    type="single"
                    collapsible
                    className={cn(PANEL, "p-0 rounded-lg overflow-hidden")}
                    value={openItem}
                    onValueChange={handleValueChange}
                >
                    <BeltVisualizer systemState={systemState} />
                    <MeterManager systemState={systemState} />
                </Accordion>
            </div>
            <ControlsPanel systemState={systemState} />
        </div>
    )
}
