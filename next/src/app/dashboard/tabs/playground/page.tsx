"use client"

import { Button } from "@/components/ui/button"
import { useStoreContext } from "../../store"
import { flask } from "@/lib/flask"


const VirtualEmergency = ({ state }: { state: boolean }) => {
    return (
        <div className="w-full max-w-xs rounded-lg border border-border bg-card p-4 shadow-md">
            <div className="text-lg font-semibold">Motor Emergency</div>
            <div className="text-sm text-muted-foreground">
                Trigger/clear internal motor emergency
            </div>

            <div className="grid grid-cols-2 gap-3 mt-2">
                <Button
                    variant="destructive"
                    disabled={state}
                    onClick={() => flask.handleAction('station', 'emergency', { value: true })}
                >
                    Trigger
                </Button>
                <Button
                    variant="outline"
                    disabled={!state}
                    onClick={() => flask.handleAction('station', 'emergency', { value: false })}
                >
                    Clear
                </Button>
            </div>
        </div>
    )
}
const RandomMeterSim = () => {
    return (
        <div className="w-full max-w-xs rounded-lg border border-border bg-card p-4 shadow-md">
            <div className="text-lg font-semibold">Random Meter</div>
            <div className="text-sm text-muted-foreground">
                Trigger simulated random meter occupancy
            </div>

            <div className="mt-2">
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={() => flask.handleAction('sim', 'meter', { type: 0 })}
                >
                    randomize
                </Button>
            </div>
        </div>
    )
}

export const PlaygroundTab = () => {
    const { systemState } = useStoreContext()

    return (
        <div className="p-4 space-y-1 space-x-1">
            <VirtualEmergency state={systemState.emergency} />
            <RandomMeterSim />
        </div>
    )
}
