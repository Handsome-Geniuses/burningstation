"use client"

import { Button } from "@/components/ui/button"
import { useStoreContext } from "../../store"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"
import React from "react"
import { useAsyncAction } from "@/hooks/useAsyncAction"



type PGCardProps = {
    label?: string
    desc?: string
} & React.ComponentProps<'div'>
const PGCard = ({
    label,
    desc,
    className,
    children
}: PGCardProps) => {
    return (
        <div className={cn('max-w-xs rounded-lg border border-border bg-card p-4 shadow-md', className)}>
            <div className="text-lg font-semibold leading-none tracking-none">{label}</div>
            <div className="text-sm text-muted-foreground leading-none tracking-none mt-px">{desc}</div>
            <div className="mt-1">
                {children}
            </div>
        </div>
    )
}

const VirtualEmergency = ({ state }: { state: boolean }) => {
    return (
        <PGCard label="Motor Emergency" desc="Trigger/clear internal motor emergency">
            <div className="grid grid-cols-2 gap-3">
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
        </PGCard>
    )
}
const RandomMeterSim = () => {
    const { run, running } = useAsyncAction()
    
    return (
        <PGCard label="Random Meter" desc="Trigger simulated random meter occupancy">
            <div className="grid grid-cols-2 gap-1">
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={run(() => flask.handleAction('sim', 'meter', { type: 2 }))}
                    disabled={running}
                >
                    clear
                </Button>
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={run(() => flask.handleAction('sim', 'meter', { type: 0 }))}
                    disabled={running}
                >
                    randomize
                </Button>
            </div>
        </PGCard>
    )
}

const MeterBayToggleSim = () => {
    const { run, running } = useAsyncAction()
    const { systemState } = useStoreContext()
    const bayStatus = Array.from({ length: 3 }, (_, i) =>
        systemState.mds.slice(i * 3, i * 3 + 3).some(Boolean)
    )
    return (
        <PGCard label="Toggle Bay" desc="toggle bay occupancy">
            <div className="grid grid-cols-3 gap-1">
                {Array.from({ length: 3 }).map((_, index) => (
                    <Button
                        key={index}
                        variant="outline"
                        className={cn(
                            "hover:bg-unset active:translate-y-px transition-all duration-50",
                            bayStatus[index] ? 'bg-accent text-accent-foreground' : ''
                        )}
                        onClick={run(() => flask.handleAction('sim', 'meter', { type: 1, bay: index }))}
                        disabled={running}
                    >
                        bay {index + 1}
                    </Button>
                ))}
            </div>
        </PGCard>
    )
}

const LoadingMeter = () => {
    const { run, running } = useAsyncAction()
    const { systemState } = useStoreContext()
    const bayStatus = Array.from({ length: 3 }, (_, i) =>
        systemState.mds.slice(i * 3, i * 3 + 3).some(Boolean)
    )

    return (
        <PGCard label="Loading Meter" desc="bay1 to be loaded">
            <Button
                variant="outline"
                className="w-full"
                disabled={running || bayStatus[0]}
                onClick={run(() => flask.handleAction('sim', 'meter', { type: 3 }))}
            >
                Loading Meter
            </Button>
        </PGCard>
    )
}

const UnloadingMeter = () => {
    const { run, running } = useAsyncAction()
    const { systemState } = useStoreContext()
    const bayStatus = Array.from({ length: 3 }, (_, i) =>
        systemState.mds.slice(i * 3, i * 3 + 3).some(Boolean)
    )

    const onUnload = run(async () => {
        try {
            const res = await flask.handleAction("sim", "unload_mock_meter")
            const payload = await res.json()

            if (!res.ok) {
                throw new Error(payload?.error ?? `Failed to unload mock meter (${res.status})`)
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to unload mock meter"
            notify.error(msg)
        }
    })

    return (
        <PGCard label="Unloading Meter" desc="remove belt meter and disconnect mock">
            <Button
                variant="outline"
                className="w-full"
                disabled={running || !bayStatus[2]}
                onClick={onUnload}
            >
                Unload Meter
            </Button>
        </PGCard>
    )
}

const AddFakeMeterSim = () => {
    const { run, running } = useAsyncAction()
    const onAdd = run(async () => {
        try {
            const res = await flask.handleAction("sim", "mock_meter")
            const payload = await res.json()

            if (!res.ok) {
                throw new Error(payload?.error ?? `Failed to add fake meter (${res.status})`)
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to add fake meter"
            notify.error(msg)
        }
    })

    const onWipe = run(async () => {
        try {
            const res = await flask.handleAction("sim", "wipe_mock_meters")
            const payload = await res.json()

            if (!res.ok) {
                throw new Error(payload?.error ?? `Failed to wipe fake meters (${res.status})`)
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to wipe fake meters"
            notify.error(msg)
        }
    })

    return (
        <PGCard label="Fake Meter" desc="Add a mock meter to the meter manager">
            <div className="grid grid-cols-2 gap-2">
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={onAdd}
                    disabled={running}
                >
                    add fake meter
                </Button>
                <Button
                    variant="outline"
                    className="w-full"
                    onClick={onWipe}
                    disabled={running}
                >
                    wipe
                </Button>
            </div>
        </PGCard>
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
        <PGCard label="Console Helpers" desc="list meters in console">
            <Button
                variant="outline"
                className="w-full"
                onClick={onLog}
            >
                list meters
            </Button>
        </PGCard>
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
            <MeterBayToggleSim />
            <LoadingMeter/>
            <UnloadingMeter/>
        </div>
    )
}
