import { ComponentProps } from "react"
import { AccordionContent, AccordionItem } from "@/components/ui/accordion"
import { AccordionTrigger } from "@radix-ui/react-accordion"

import { flask } from "@/lib/flask"
import { cn } from "@/lib/utils"

import { MeterState, SystemState } from "../../store/system"
import { PANEL_HEADER } from "./shared"
import { MeterCard } from "./meter-card"
import ToothedFrame, { ToothedFrameDirection as Direction } from "./tooth-frame"


export function WarehouseDolly({ className = "" }) {
    return (
        <svg
            viewBox="34 -65 72 175"
            className={cn("w-24 h-24", className)}
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-label="Dolly"
        >
            <path
                d="M55 -60 V85 H100"
                stroke="currentColor"
                strokeWidth="8"
                strokeLinecap="round"
                strokeLinejoin="round"
            />

            <path
                d="M55 -60 H40"
                stroke="currentColor"
                strokeWidth="8"
                strokeLinecap="round"
            />

            <circle cx="62" cy="97" r="10" fill="currentColor" />
            <circle cx="92" cy="97" r="10" fill="currentColor" />
        </svg>
    );
}


const motorDirectionMap: Record<0 | 1 | 2 | 3, Direction> = {
    0: "off",
    1: "cw",
    2: "ccw",
    3: "off",
}

const MDS_TO_BAY_GUESS_INDEX = [2, 3, 4, 6, 7, 8, 10, 11, 12]

function getBayGuessCenterIndex(bayGuess: SystemState["bayGuess"], meterIp: string) {
    const indexes = bayGuess
        .map((ip, index) => ip === meterIp ? index : null)
        .filter((index): index is number => index !== null)

    if (indexes.length === 0) return null

    return indexes.reduce((sum, index) => sum + index, 0) / indexes.length
}

function isMysterySensorTrigger(systemState: SystemState, bayGuessIndex: number) {
    const mdsIndex = MDS_TO_BAY_GUESS_INDEX.indexOf(bayGuessIndex)
    if (mdsIndex === -1) return false

    return systemState.mds[mdsIndex] && !systemState.bayGuess[bayGuessIndex]
}

function Roller({
    direction = "off",
    animationDuration = 2,
    onPointerDown,
}: {
    direction?: "cw" | "ccw" | "off"
    animationDuration?: number
} & ComponentProps<"div">) {
    return (
        <div
            className={cn(
                "size-4 rounded-full opacity-33",
                "bg-[repeating-linear-gradient(45deg,#cccccc,#cccccc_45%,#555555_45%,#555555_55%,#cccccc_55%)]",
                "animate-spin",
                onPointerDown && "cursor-pointer",
                `[animation-duration:${animationDuration}s]`,
                direction === "cw" || direction === "ccw" ? "opacity-100" : "[animation-play-state:paused]",
                direction === "ccw" ? "[animation-direction:reverse]" : ""
            )}
            onPointerDown={onPointerDown}
        />
    )
}

type MovingBeltProps = {
    direction?: "cw" | "ccw" | "off"
    onL?: () => void
    onR?: () => void
}

function MovingBelt({
    direction = "off",
    onL = () => { },
    onR = () => { },
}: MovingBeltProps) {
    const hz = 0.3

    return (
        <ToothedFrame
            innerWidth={273}
            innerHeight={38}
            outerThickness={20}
            toothSpacingFromInner={4}
            teethThickness={20}
            toothWidth={14}
            toothGap={7}
            toothSpeed={hz}
            direction={direction}
            outerBorderWidth={8}
            outerFill="#18181b"
            outerStroke="#3f3f46"
            teethFill="#71717a"
            innerFill="#71717a"
            className={cn(direction == "off" ? "opacity-70" : "", "transition-all duration-300 ease-in-out")}
            contentClassName="text-white font-semibold"
            style={{ margin: 0 }}
        >
            <div className="size-full flex items-center justify-center gap-[6px]">
                <Roller direction={direction} animationDuration={hz * 10} onPointerDown={onL} />
                {Array.from({ length: 5 }).map((_, index) => (
                    <Roller key={index} direction={direction} animationDuration={hz * 10} />
                ))}
                <Roller direction={direction} animationDuration={hz * 10} onPointerDown={onR} />
            </div>
        </ToothedFrame>
    )
}

const SideBelt = ({
    onL = () => { },
    onR = () => { },
}: {
    onL?: () => void
    onR?: () => void
}) => {
    return (
        <ToothedFrame
            innerWidth={72}
            innerHeight={38}
            outerThickness={20}
            toothSpacingFromInner={4}
            teethThickness={20}
            toothWidth={14}
            toothGap={7}
            outerBorderWidth={8}
            outerFill="#18181b"
            outerStroke="#3f3f46"
            teethFill="#71717a"
            innerFill="#71717a"
            className="opacity-70"
            contentClassName="text-white font-semibold"
            style={{ margin: 0 }}
        >
            <div className="size-full flex items-center justify-center gap-[2px]">
                <Roller onPointerDown={onL} />
                <Roller onPointerDown={onR} />
            </div>
        </ToothedFrame>
    )
}

type BayGuessStripProps = {
    systemState: SystemState
}

function BayGuessStrip({
    systemState,
}: BayGuessStripProps) {
    return (
        <div className="grid grid-cols-15 w-full gap-px z-1">
            {Array.from({ length: 15 }).map((_, index) => (
                <div
                    key={index}
                    className={cn(
                        "border border-border py-0.5 text-center rounded-full transition-all duration-300 ease-in-out",
                        systemState.bayGuess[index]
                            ? "bg-blue-300"
                            : isMysterySensorTrigger(systemState, index)
                                ? "bg-red-300"
                                : "bg-muted"
                    )}
                />
            ))}
        </div>
    )
}

type StationVisualizerProps = {
    systemState: SystemState
    onMeterSelected?: (meter: MeterState) => void
}

export function StationVisualizer({
    systemState,
    onMeterSelected = () => { },
}: StationVisualizerProps) {
    const canLoadFromLeft = systemState.mds[0] && !systemState.mds[2]
    const canUnloadFromRight = !systemState.mds[6] && systemState.mds[8]

    const handlePointerUp = () => {
        flask.handleAction("override", "motor", { value_list: [0, 0, 0] })
        window.removeEventListener("pointerup", handlePointerUp)
    }

    const handlePointerDown = () => {
        window.addEventListener("pointerup", handlePointerUp)
    }

    const moveMotors = (value_list: number[]) => {
        if (systemState.mode !== "manual") return
        flask.handleAction("override", "motor", { value_list })
        handlePointerDown()
    }

    return (
        <AccordionItem key="station" value="station">
            <AccordionTrigger className={cn(PANEL_HEADER, "w-full rounded-none")}>
                Station Visualizer
            </AccordionTrigger>
            <AccordionContent asChild className="p-0">
                <div className="relative w-full flex justify-center">

                    {/* SIDE DOLLY'S FOR FUN */}
                    <div className={cn(
                        "absolute bottom-7.5 text-[#f4a261] transition-all duration-300 ease-in-out ",
                        canLoadFromLeft ? "-left-5 animate-pulse [animation-duration:0.5s]" : "-left-14 opacity-50"
                    )}>
                        <WarehouseDolly className="w-20 h-35" />
                    </div>

                    <div className={cn(
                        "absolute bottom-7.5 text-[#f4a261] transition-all duration-300 ease-in-out -scale-x-100",
                        canUnloadFromRight ? "-right-5 animate-pulse [animation-duration:0.5s]" : "-right-14 opacity-50"
                    )}>
                        <WarehouseDolly className="w-20 h-35" />
                    </div>


                    <div className="relative w-150 flex flex-col size-full items-center">
                        {/* VERTICAL SEPARATOR */}
                        {[1, 5, 9, 13].map((index) => (
                            <div
                                key={index}
                                className="pointer-events-none absolute top-0 bottom-0 z-0 w-[2px] opacity-15"
                                style={{
                                    left: `${((index + 0.5) / 15) * 100}%`,
                                    backgroundImage:
                                        "repeating-linear-gradient(to bottom, rgba(0,0,0,1) 0 10px, transparent 10px 18px)",
                                }}
                            />
                        ))}

                        {/* setting the height */}
                        <div className="w-full h-38" />

                        {/* METER PLACEMENT */}
                        {Object.values(systemState.meters).map((meter) => {
                            const centerIndex = getBayGuessCenterIndex(systemState.bayGuess, meter.ip)
                            if (centerIndex === null) return null

                            return (
                                <div
                                    key={meter.ip}
                                    className="z-1 absolute top-0 w-fit h-38 -translate-x-1/2 transition-[left] duration-300 ease-in-out flex justify-center items-end"
                                    style={{ left: `${((centerIndex + 0.5) / 15) * 100}%` }}
                                >
                                    <MeterCard
                                        className="px-6 z-1"
                                        meter={meter}
                                        onSelected={onMeterSelected}
                                    />
                                </div>
                            )
                        })}
                        <BayGuessStrip systemState={systemState} />
                        <div className="flex">
                            <SideBelt onL={() => moveMotors([2, 2, 2])} />
                            <MovingBelt direction={motorDirectionMap[systemState.motors[0]]} onL={() => moveMotors([2, 0, 0])} onR={() => moveMotors([1, 0, 0])} />
                            <MovingBelt direction={motorDirectionMap[systemState.motors[1]]} onL={() => moveMotors([0, 2, 0])} onR={() => moveMotors([0, 1, 0])} />
                            <MovingBelt direction={motorDirectionMap[systemState.motors[2]]} onL={() => moveMotors([0, 0, 2])} onR={() => moveMotors([0, 0, 1])} />
                            <SideBelt onR={() => moveMotors([1, 1, 1])} />
                        </div>
                        <BayGuessStrip systemState={systemState} />
                    </div>
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}
