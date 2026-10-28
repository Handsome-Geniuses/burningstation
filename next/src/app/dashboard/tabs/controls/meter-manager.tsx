import { useRef, useState } from "react"
import { Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { flask } from "@/lib/flask"
import { AccordionContent, AccordionItem } from "@/components/ui/accordion"
import { AccordionTrigger } from "@radix-ui/react-accordion"

import { cn } from "@/lib/utils"

import { MeterState, SystemState } from "../../store/system"
import { MeterCard } from "./meter-card"
import { PANEL_HEADER } from "./shared"

type MeterManagerProps = {
    systemState: SystemState
    onMeterSelected?: (meter: MeterState) => void
}

export const MeterManager = ({
    systemState,
    onMeterSelected = () => { },
}: MeterManagerProps) => {
    const meters = Object.values(systemState.meters)
    const [wiping, setWiping] = useState(false)
    const wipePending = useRef(false)

    const wipeMeters = async () => {
        if (wipePending.current) return
        wipePending.current = true
        setWiping(true)
        try {
            const response = await flask.post("meters/wipe")
            if (!response.ok) throw new Error("Unable to wipe meters")
            const result = await response.json() as { removed: string[]; preserved: string[] }
            toast.success(`Removed ${result.removed.length} meter(s); kept ${result.preserved.length} connected busy meter(s).`)
        } catch {
            toast.error("Unable to wipe meters. Please try again.")
        } finally {
            wipePending.current = false
            setWiping(false)
        }
    }

    return (
        <AccordionItem key="meter" value="meter">
            <div className="relative">
                <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                    Meter Manager
                </AccordionTrigger>
                <button
                    type="button"
                    aria-label="Wipe meters"
                    title="Wipe unreachable and idle meters; keep connected busy meters"
                    disabled={wiping}
                    aria-busy={wiping}
                    onClick={(event) => {
                        event.stopPropagation()
                        void wipeMeters()
                    }}
                    className="absolute inset-y-0 left-0 flex min-w-4 items-center justify-center px-4 hover:bg-black/5 focus-visible:outline-2 focus-visible:outline-ring focus-visible:-outline-offset-2 disabled:opacity-50"
                >
                    {wiping ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                </button>
            </div>
            <AccordionContent asChild className="p-0">
                <div className="min-h-3 flex items-center">
                    {meters.length === 0 && (
                        <div className="px-4 py-3 text-sm text-muted-foreground self-start">
                            No connected meters
                        </div>
                    )}

                    <div className="flex flex-wrap items-center gap-2 p-2">
                        {meters.map((meter) => (
                            <MeterCard
                                key={meter.ip}
                                meter={meter}
                                onSelected={onMeterSelected}
                            />
                        ))}
                    </div>
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}
