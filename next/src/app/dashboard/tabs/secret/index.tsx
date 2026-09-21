import { SnapBar } from "@/components/ui/snap-bar"
import { Indicators } from "../monitor"
import { MeterSlots } from "../controls/meter-slots"
import { flask } from "@/lib/flask"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { useStoreContext } from "@/app/dashboard/store"
import { hasHardwareCapability } from "@/app/dashboard/store/system"
import React from "react"
import { useDebounce } from "@/hooks/useDebounce"
import { Pinout } from "./Pinout"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog"
import { Loader2, Network } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"

type DeviceIpAddress = {
    interface?: string
    family?: string
    address: string
    source?: string
}

type DeviceIpPayload = {
    hostname?: string
    request_host?: string | null
    addresses?: DeviceIpAddress[]
}

const TowerLampControls = () => {
    const { systemState } = useStoreContext()
    const [value1, setValue1] = React.useState(systemState.lamp[2])
    const [value2, setValue2] = React.useState(systemState.lamp[3])
    const timeoutRef = React.useRef<NodeJS.Timeout | null>(null)

    const dbdc1 = useDebounce((v) => flask.handleAction('station', 'lamp', { type: 'L1', dc: Math.floor(v) }), 100)
    const dbdc2 = useDebounce((v) => flask.handleAction('station', 'lamp', { type: 'L2', dc: Math.floor(v) }), 100)

    const updateDC1 = (v: number) => {
        setValue1(v)
        dbdc1(v)
    }
    const updateDC2 = (v: number) => {
        setValue2(v)
        dbdc2(v)
    }

    return (
        <div className="flex flex-col items-center justify-center">
            <div>Tower Lamp Controls</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {['R', 'Y', 'G', 'BUZ'].map((type, i) => (
                    <Button
                        key={i}
                        onClick={() => flask.handleAction('station', 'tower', { type: type })}
                    >
                        {type}
                    </Button>
                ))}
                {['L1', 'L2'].map((type, i) => (
                    <Button
                        key={i}
                        onClick={() => flask.handleAction('station', 'lamp', { type: type, state: !systemState.lamp[i] })}
                    >
                        {type}
                    </Button>
                ))}
            </div>
            <Slider
                className="h-8 w-60 mt-1"
                value={value1}
                onValueChange={updateDC1}
                min={0}
                max={100}
                thumb={"ball"}
            />
            <Slider
                className="h-8 w-60 mt-4"
                value={value2}
                onValueChange={updateDC2}
                min={0}
                max={100}
                thumb={"ball"}
            />
        </div>
    )
}

const MeterLoadControls = () => {
    return (
        <div className="flex flex-col items-center justify-center">
            <div>Meter Load Controls</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {['L', 'M', 'R', 'ALL'].map((s, i) => (
                    <Button
                        key={s}
                        onClick={() => flask.handleAction('station', 'load', { type: s })}
                    >
                        load {s}
                    </Button>
                ))}
                <Button onClick={() => flask.handleAction('station', 'load', { type: 'ML' })}>M to L</Button>
                <Button onClick={() => flask.handleAction('station', 'load', { type: 'RM' })}>R to M</Button>
            </div>

        </div>
    )

}

const MotorControls = () => {
    return (
        <div className="flex flex-col items-center justify-center">
            <div>Motor Control OVERRIDE</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {[
                    { text: "L", left: [2, 0, 0], right: [1, 0, 0] },
                    { text: "M", left: [0, 2, 0], right: [0, 1, 0] },
                    { text: "R", left: [0, 0, 2], right: [0, 0, 1] },
                    { text: "LM", left: [2, 2, 0], right: [1, 1, 0] },
                    { text: "all", left: [2, 2, 2], right: [1, 1, 1] },
                    { text: "MR", left: [0, 2, 2], right: [0, 1, 1] },
                ].map(({ text, left, right }) => (
                    <SnapBar
                        key={text}
                        text={text}
                        onLeft={() => flask.handleAction('override', 'motor', { value_list: left })}
                        onRight={() => flask.handleAction('override', 'motor', { value_list: right })}
                        onRelease={() => flask.handleAction('override', 'motor', { value_list: [0, 0, 0] })}
                    />
                ))}
            </div>
        </div>
    )
}

const ManualAutoBox = () => {
    const { systemState } = useStoreContext()
    const isManual = systemState.mode === 'manual'
    const autoAvailable = hasHardwareCapability(systemState, "auto_mode")
    return (
        <div className="flex flex-col w-full gap-1">
            <div className="w-full flex items-center gap-2 justify-end">
                <Label htmlFor="mode">{systemState.mode}</Label>
                <Switch
                    id="mode"
                    checked={!isManual}
                    onCheckedChange={(checked) => flask.handleAction('station', 'mode', { value: checked ? 'auto' : 'manual' })}
                    disabled={!autoAvailable}
                />
            </div>
            {
                isManual &&
                <div className="w-full flex flex-col gap-1">
                    <Button onClick={() => flask.handleAction('program', 'manual', { program: 'setup_custom_display' })}>
                        Load Custom Display
                    </Button>
                    <Button onClick={() => flask.handleAction('program', 'manual', { program: 'start_passive_job' })}>
                        Start Passive Job
                    </Button>
                    <Button onClick={() => flask.handleAction('program', 'manual', { program: 'start_physical_job' })}>
                        Start Physical Job
                    </Button>
                    <Button onClick={() => flask.handleAction('program', 'manual', { program: 'hello' })}>
                        hello
                    </Button>
                </div>
            }
        </div>
    )
}

const DeviceIpDialog = () => {
    const [open, setOpen] = React.useState(false)
    const [payload, setPayload] = React.useState<DeviceIpPayload | null>(null)
    const [loading, setLoading] = React.useState(false)
    const [error, setError] = React.useState<string | null>(null)

    const loadDeviceIps = React.useCallback(async () => {
        setLoading(true)
        setError(null)

        try {
            const res = await flask.get("/device/ip-addresses")
            const data = await res.json().catch(() => null) as DeviceIpPayload | null

            if (!res.ok) {
                throw new Error(`Could not load device IP addresses (${res.status})`)
            }

            setPayload(data ?? { addresses: [] })
        } catch (err) {
            setPayload(null)
            setError(err instanceof Error ? err.message : "Could not load device IP addresses")
        } finally {
            setLoading(false)
        }
    }, [])

    const onOpenChange = (value: boolean) => {
        setOpen(value)
        if (value) void loadDeviceIps()
    }

    const addresses = payload?.addresses ?? []

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogTrigger asChild>
                <Button variant="outline" className="w-full justify-start">
                    <Network />
                    Device IPs
                </Button>
            </DialogTrigger>
            <DialogContent className="max-h-100 overflow-hidden p-0 sm:max-w-md">
                <ScrollArea
                    className="min-h-0 max-h-100 w-full"
                    viewportClassName="max-h-100 overscroll-contain"
                    scrollBarClassName="w-4 border-l-0 p-0.5 [&>div]:bg-muted-foreground/70 [&>div:hover]:bg-foreground"
                >
                    <div className="grid gap-4 p-6 pr-12">
                        <DialogHeader>
                            <DialogTitle>Device IP Addresses</DialogTitle>
                            <DialogDescription className="h-0 w-0 hidden" />
                        </DialogHeader>
                        <div className="grid gap-3">
                            {payload?.hostname && (
                                <div className="grid gap-1 text-sm">
                                    <div className="text-muted-foreground">Hostname</div>
                                    <div className="font-mono break-all">{payload.hostname}</div>
                                </div>
                            )}
                            {payload?.request_host && (
                                <div className="grid gap-1 text-sm">
                                    <div className="text-muted-foreground">Request host</div>
                                    <div className="font-mono break-all">{payload.request_host}</div>
                                </div>
                            )}
                            {loading && (
                                <div className="flex items-center gap-2 text-muted-foreground">
                                    <Loader2 className="animate-spin" />
                                    Loading
                                </div>
                            )}
                            {error && <div className="text-destructive">{error}</div>}
                            {!loading && !error && addresses.length === 0 && (
                                <div className="text-muted-foreground">No device IP addresses found.</div>
                            )}
                            {!loading && !error && addresses.map((entry, i) => {
                                const meta = [entry.interface, entry.source, entry.family].filter(Boolean).join(" / ")

                                return (
                                    <div key={`${entry.address}-${i}`} className="rounded-md border bg-muted/40 px-3 py-2">
                                        {meta && <div className="text-xs text-muted-foreground">{meta}</div>}
                                        <div className="font-mono text-lg break-all">{entry.address}</div>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </ScrollArea>
            </DialogContent>
        </Dialog>
    )
}
// onClick={() => flask.handleAction('station', 'lamp', { type: type, state: !systemState.lamp[i] })}

export const SecretTab = () => {
    const { systemState } = useStoreContext()
    const beltAvailable = hasHardwareCapability(systemState, "belt")
    const motorAvailable = hasHardwareCapability(systemState, "motor_control")
    const towerAvailable = hasHardwareCapability(systemState, "tower")
    const lampAvailable = hasHardwareCapability(systemState, "lamp")

    return (
        <div className="flex items-center justify-around">
            <Pinout />
            <div className="bg-muted/70 gap-2 p-4 flex flex-col items-center">
                <div className="flex justify-between w-full">
                    <div className="border-4 border-border p-1"><Indicators /></div>
                    <div className="flex flex-col items-center gap-2">
                        <ManualAutoBox />
                        <DeviceIpDialog />
                    </div>
                </div>
                {beltAvailable && <MeterSlots classname="border border-border p-1" />}
            </div>
            <div className="bg-muted/70 gap-2 p-4 flex flex-col items-center">
                {(towerAvailable || lampAvailable) && <TowerLampControls />}
                {beltAvailable && <MeterLoadControls />}
                {motorAvailable && <MotorControls />}
            </div>
        </div>
    )
}
