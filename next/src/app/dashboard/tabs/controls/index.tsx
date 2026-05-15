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
export const BeltVisualizer = () => {
    return (
        <AccordionItem key={"belt"} value={'belt'}>
            <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                Belt Visualizer
            </AccordionTrigger>
            <AccordionContent asChild className="p-0">
                <div className="w-full flex justify-center">
                    <MeterSlots classname="" />
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

    const onBlink = async () => {
        if (!selectedMeter) return

        try {
            const search = new URLSearchParams({
                ip: selectedMeter.ip,
                prog: "identify",
            })
            const res = await flask.get(`/testing?${search.toString()}`)
            const payload = await res.json().catch(() => ({}))

            if (!res.ok) {
                throw new Error(payload?.error ?? `Failed to start identify (${res.status})`)
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to start identify"
            notify.error(msg)
        }
    }

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
                                    className="rounded border bg-accent p-2 text-left"
                                    onClick={() => setSelectedMeter(meter)}
                                >
                                    <div className="text-sm font-medium text-center leading-1">{meter.ip.slice(-3)}</div>
                                    <pre className="w-fit min-w-max whitespace-pre font-mono text-[10px] leading-tight tracking-normal text-[#f4a261] [font-variant-ligatures:none] [tab-size:2] md:text-sm">
                                        <code>{ascii_meter[frame]}</code>
                                    </pre>
                                    <div className="text-sm font-medium text-center leading-1">{meter.hostname}</div>
                                </button>
                            ))}
                        </div>
                    </>
                </AccordionContent>
            </AccordionItem>

            <Dialog open={selectedMeter != null} onOpenChange={(open) => !open && setSelectedMeter(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{selectedMeter?.hostname ?? "Meter"}</DialogTitle>
                        <DialogDescription>
                            {selectedMeter ? `${selectedMeter.ip} | ${selectedMeter.meter_type || "unknown"}` : ""}
                        </DialogDescription>
                    </DialogHeader>

                    <DialogFooter>
                        <Button onClick={onBlink}>
                            Blink
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}

export const ControlsTab = () => {
    const { systemState } = useStoreContext()

    return (
        <div className="p-2 grid grid-cols-[1fr_auto] gap-2 ">
            <div>
                <Accordion type="single" collapsible className={cn(PANEL, "p-0 rounded-lg overflow-hidden")}>
                    <BeltVisualizer />
                    <MeterManager systemState={systemState} />
                </Accordion>
            </div>
            <ControlsPanel systemState={systemState} />
        </div>
    )
}
