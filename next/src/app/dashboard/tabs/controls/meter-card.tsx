import React from "react"

import { cn } from "@/lib/utils"

import { MeterState } from "../../store/system"

const ASCII_METER = [
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
`,
]

const AnimatedMeter = React.memo(({ busy }: { busy: boolean }) => {
    const [frame, setFrame] = React.useState(0)

    React.useEffect(() => {
        if (!busy) {
            setFrame(0)
            return
        }

        const id = window.setInterval(() => {
            setFrame(prev => (prev + 1) % ASCII_METER.length)
        }, 300)

        return () => clearInterval(id)
    }, [busy])

    return (
        <pre className="w-fit min-w-max whitespace-pre font-mono text-[10px] leading-tight tracking-normal text-[#f4a261] [font-variant-ligatures:none] [tab-size:2] md:text-sm">
            <code>{ASCII_METER[frame]}</code>
        </pre>
    )
})

type MeterCardProps = {
    meter: MeterState
    onSelected?: (meter: MeterState) => void
} & React.ComponentProps<"button">

export const MeterCard = ({
    meter,
    onSelected = () => { },
    style = {},
    className,
}: MeterCardProps) => {
    const progress = meter.progress
    const noProgress = (progress?.total ?? 0) <= 1
    const percentage = noProgress || meter.status === "ready"
        ? 100
        : (progress!.current / progress!.total) * 100

    return (
        <button
            type="button"
            className={cn(
                "rounded border px-2 py-2 text-left relative overflow-hidden",
                className
            )}
            onClick={() => onSelected(meter)}
            style={style}
        >
            <div className="relative z-10">
                <div className="text-sm font-medium text-center leading-1">{meter.ip.slice(-3)}</div>
                <AnimatedMeter busy={meter.status === "busy"} />
                <div className="text-sm font-medium text-center leading-1">{meter.hostname}</div>
            </div>

            <div
                className={cn(
                    "absolute inset-x-0 bottom-0 z-1 transition-all duration-500 ease-in-out [animation-duration:1.0s]",
                    meter.status !== "ready" ? "animate-pulse" : "",
                    meter.status === "ready" ? "bg-green-100/50" : "bg-green-300",
                    meter.status === "error" && "bg-destructive/50"
                )}
                style={{ height: `${percentage}%`, minHeight: "2%" }}
            />
        </button>
    )
}
