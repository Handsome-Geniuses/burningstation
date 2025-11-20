'use client'
import { cn } from "@/lib/utils";
import { cva, VariantProps } from "class-variance-authority";
import React from "react"


type SliderThumbType = "ball" | "bar" | "none"
export const thumbCVA = cva(
    "bg-primary absolute top-1/2 -translate-y-1/2 pointer-events-none",
    {
        variants: {
            type: {
                ball: "h-[140%] aspect-square rounded-full",
                bar: "h-[110%] w-1 rounded-full",
                none: "hidden display-none"
            },
            active: {
                true: "scale-110 shadow-md",
                false: "scale-100",
            },
        },
        defaultVariants: {
            type: "ball",
            active: false,
        },
    }
);

interface ThumbProps extends VariantProps<typeof thumbCVA>, React.HTMLAttributes<HTMLDivElement> {
    type?: SliderThumbType;
    active?: boolean;
    style?: React.CSSProperties;
}

const Thumb = React.forwardRef<HTMLDivElement, ThumbProps>(
    ({ type, active, className, style }, ref) => (
        <div
            ref={ref}
            className={cn(thumbCVA({ type, active }), className)}
            style={style}
        />
    )
);


const sliderCVA = cva(
    `relative w-40 h-8 border border-border bg-red-100`,
    {
        variants: {
            rounded: {
                true: 'rounded',
                false: ''
            },
        },
        defaultVariants: {
            rounded: true
        }
    }
)
interface SliderProps extends VariantProps<typeof sliderCVA>, React.HTMLAttributes<HTMLDivElement> {
    value?: number
    min?: number
    max?: number
    onValueChange?: (value: number) => void

    rounded?: boolean
    bg?: string
    fg?: string
    thumb?: SliderThumbType
    thumbClass?: string
}

export const Slider = ({
    value,
    min = 0,
    max = 100,
    onValueChange,
    className,
    rounded,
    bg = "bg-background",
    fg = "bg-foreground",
    thumb = "none",
    thumbClass = "",
    ...divProps
}: SliderProps) => {
    const [_value, _setValue] = React.useState(Math.floor(max / 2))
    const [isDragging, setIsDragging] = React.useState(false)
    const ref = React.useRef<HTMLDivElement>(null)
    const tref = React.useRef<HTMLDivElement>(null)

    const currentValue = value == null ? _value : value
    const currentHandle = onValueChange == null ? _setValue : onValueChange
    const percentage = ((currentValue - min) / (max - min)) * 100

    const updateValue = (clientX: number) => {
        const rect = ref.current!.getBoundingClientRect()
        let percent = (clientX - rect.left) / rect?.width
        percent = Math.max(0, Math.min(1, percent))
        const newValue = min + percent * (max - min)
        // onValueChange?.(newValue)
        currentHandle(newValue)
    }
    const move = (e: React.PointerEvent) => updateValue(e.clientX)
    const handlePointerDown = (e: React.PointerEvent) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        updateValue(e.clientX)
        setTimeout(() => { setIsDragging(true) }, 50)

    }
    const handlePointerUp = (e: React.PointerEvent) => {
        e.currentTarget.releasePointerCapture(e.pointerId)
        updateValue(e.clientX)
        setIsDragging(false)
    }
    const handlePointerMove = (e: React.PointerEvent) => {
        if (isDragging) move(e)
    }

    let clampedPercentage = percentage;
    let clampedHeight;
    if (ref.current && tref.current) {
        const trackWidth = ref.current.offsetWidth
        const trackHeight = ref.current.offsetHeight
        const W = trackWidth
        const H = trackHeight
        const thumbWidth = thumb == "ball"
            ? Math.floor(tref.current.offsetWidth / 1.75)
            : Math.floor(tref.current.offsetWidth - 4)
        const minPerc = ((thumbWidth / 2) / trackWidth) * 100
        const maxPerc = ((trackWidth - thumbWidth / 2) / trackWidth) * 100
        clampedPercentage = Math.min(maxPerc, Math.max(minPerc, percentage))


        const cs = getComputedStyle(ref.current)
        const br = Math.floor(Math.min(parseFloat(cs.borderRadius), W / 2, H /2))
        
        const x = (clampedPercentage / 100) * W;
        let topLimit = 0;
        if (x < br) {
            // left rounded corner
            topLimit = br - Math.sqrt(br ** 2 - (br - x) ** 2);
        } else if (x > W - br) {
            // right rounded corner
            const dx = x - (W - br);
            topLimit = br - Math.sqrt(br ** 2 - dx ** 2);
        } else {
            topLimit = 0;
        }

        const height = (H - topLimit*2)*1.1;
        clampedHeight = Math.floor(height)

    }

    return (
        <div
            ref={ref}
            className={cn(sliderCVA({ rounded }), bg, className, "touch-none")}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onPointerMove={handlePointerMove}
            onContextMenu={e => e.preventDefault()}
            {...divProps}
        >
            <div className="w-full h-full relative overflow-hidden rounded-[inherit] p-2">
                <div
                    className={cn(
                        "absolute inset-0 h-full bg-blue-500 duration-150 ease-out pointer-events-none ",
                        isDragging ? 'transition-none' : 'transition-all',
                        fg
                    )}
                    style={{ width: `${clampedPercentage}%` }}
                />
            </div>
            {
                thumb == "ball" &&
                <Thumb
                    ref={tref}
                    type={thumb}
                    active={isDragging}
                    style={{ left: `${clampedPercentage}%`}}
                    className={cn(thumbClass, "transform -translate-x-1/2")}
                />
            }
            {
                thumb == "bar" &&
                <Thumb
                    ref={tref}
                    type={thumb}
                    active={isDragging}
                    style={{ left: `${clampedPercentage}%`, height: `${clampedHeight}px`}}
                    className={cn(thumbClass, "transform -translate-x-1/2")}
                />
            }
        </div>
    )
}



