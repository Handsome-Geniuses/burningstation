import React from "react"

interface SnapBarProps {
    onLeft?: () => void
    onRight?: () => void
    onRelease?: () => void

    text?: string
    // Customization props
    barClassName?: string           // For the container
    circleClassName?: string        // For the circle
    leftZoneClassName?: string      // For the left section when active
    centerZoneClassName?: string    // For the center section when active
    rightZoneClassName?: string     // For the right section when active
}

export function SnapBar({
    onLeft,
    onRight,
    onRelease,
    text,
    barClassName = "w-26 h-9 bg-gray-700 rounded-lg shadow-md",
    circleClassName = "w-7 h-7 bg-yellow-400 rounded-full shadow-md",
    leftZoneClassName = "bg-gray-600/50",
    centerZoneClassName = "",
    rightZoneClassName = "bg-gray-600/50",
}: SnapBarProps) {
    const barRef = React.useRef<HTMLDivElement>(null);
    const [circlePosition, setCirclePosition] = React.useState<"left" | "right" | "center">("center");

    const handlePointerUp = () => {
        setCirclePosition("center")
        onRelease?.()
        window.removeEventListener("pointerup", handlePointerUp)
    }
    const handlePointerDown = (e: React.PointerEvent) => {
        if (!barRef.current) return
        const rect = barRef.current.getBoundingClientRect()
        const x = e.clientX - rect.left
        const thresholdLeft = rect.width / 3
        const thresholdRight = (rect.width / 3) * 2
        if (x < thresholdLeft) {
            onLeft?.()
            setCirclePosition("left")
        } else if (x > thresholdRight) {
            onRight?.()
            setCirclePosition("right")
        } else {
            setCirclePosition("center")
        }
        window.addEventListener("pointerup", handlePointerUp)

    }

    const left = {
        left: "left-1/6",
        center: "left-1/2",
        right: "left-5/6",
    }[circlePosition]

    return (
        <div
            ref={barRef}
            className={`relative cursor-pointer select-none ${barClassName}`}
            onPointerDown={handlePointerDown}
            onContextMenu={(e) => e.preventDefault()}
        >
            {circlePosition == "left" && <div className={`absolute left-0 top-0 w-1/3 h-full rounded-l ${leftZoneClassName}`}></div>}
            {circlePosition == "center" && <div className={`absolute left-1/3 top-0 w-1/3 h-full ${centerZoneClassName}`}></div>}
            {circlePosition == "right" && <div className={`absolute left-2/3 top-0 w-1/3 h-full rounded-r blur ${rightZoneClassName}`}></div>}

            <div
                className={`z-0 absolute top-1/2 ${left}  transform -translate-y-1/2 -translate-x-1/2 transition-transform transition-all duration-300 ease-in-out ${circleClassName}`}
            />
            {text && <div className="relative z-1 flex items-center justify-center size-full">{text}</div>}
        </div>
    )
}