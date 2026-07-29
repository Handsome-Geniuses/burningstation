import { useStoreContext } from "../../store"
import { ControlsPanel } from "./controls-panel"
import { cn } from "@/lib/utils"
import { PANEL } from "./shared"
import { Accordion } from "@/components/ui/accordion"

import { MeterState } from "../../store/system"

import React from "react"
import { MeterDialog } from "./meter-dialog"
import { MeterManager } from "./meter-manager"
import { StationVisualizer } from "./station-visualizer"

const STORAGE_KEY = "bs-controls-accordion-open-items"
export const ControlsTab = () => {
    const { systemState } = useStoreContext()
    const [openItems, setOpenItems] = React.useState<string[]>(["belt", "meter"]);
    const [selectedMeter, setSelectedMeter] = React.useState<MeterState | null>(null)

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
                    <StationVisualizer systemState={systemState} onMeterSelected={setSelectedMeter} />
                    <MeterManager systemState={systemState} onMeterSelected={setSelectedMeter} />
                </Accordion>
                <MeterDialog
                    systemState={systemState}
                    selectedMeter={selectedMeter}
                    onSelectedMeterChange={setSelectedMeter}
                />
            </div>
            <ControlsPanel systemState={systemState} />
        </div>
    )
}
