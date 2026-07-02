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

    return (
        <AccordionItem key="meter" value="meter">
            <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                Meter Manager
            </AccordionTrigger>
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
