"use client"

import { Button } from "@/components/ui/button"
import { useStoreContext } from "../../store"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"


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

const AddFakeMeterSim = () => {
    const onAdd = async () => {
        try {
            const res = await flask.handleAction("sim", "mock_meter")
            const payload = await res.json()

            if (!res.ok) {
                throw new Error(payload?.error ?? `Failed to add fake meter (${res.status})`)
            }

            notify.success(`Added fake meter ${payload.ip}`)
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to add fake meter"
            notify.error(msg)
        }
    }

    return (
        <div className="w-full max-w-xs rounded-lg border border-border bg-card p-4 shadow-md">
            <div className="text-lg font-semibold">Fake Meter</div>
            <div className="text-sm text-muted-foreground">
                Add a mock meter to the meter manager
            </div>

            <div className="mt-2">
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={onAdd}
                >
                    add fake meter
                </Button>
            </div>
        </div>
    )
}

const LogMeters = () => {
    const onLog = async () => {
        try {
            const res = await flask.handleAction("sim", "list_meters")
            if (!res.ok) {
                throw new Error(`Failed to fetch meters (${res.status})`)
            }

            console.log("meters", await res.json())
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to log meters"
            notify.error(msg)
        }
    }

    return (
        <div className="w-full max-w-xs rounded-lg border border-border bg-card p-4 shadow-md">
            <div className="text-lg font-semibold">Console Helpers</div>
            <div className="text-sm text-muted-foreground">
                list meters in console
            </div>

            <div className="mt-2">
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={onLog}
                >
                    list meters
                </Button>
            </div>
        </div>
    )
}

export const PlaygroundTab = () => {
    const { systemState } = useStoreContext()

    return (
        // <div className="p-4 flex flex-wrap gap-2 items-start">
        // <div className="p-4 space-y-1 space-x-1">
        // <div className="p-4 flex flex-wrap gap-3 items-start content-start overflow-scroll">
        // <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 overflow-scroll p-4">
        // <div className="grid grid-cols-[repeat(3,max-content)] items-start gap-2 overflow-auto p-4">
        // <div className="grid grid-cols-[repeat(3,max-content)] auto-rows-max items-start gap-2 overflow-auto p-4">
        <div className="grid grid-cols-[1fr_1fr_1fr] content-start gap-2 overflow-auto p-4">
            <VirtualEmergency state={systemState.emergency} />
            <RandomMeterSim />
            <AddFakeMeterSim />
            <LogMeters />
        </div>
    )
}
