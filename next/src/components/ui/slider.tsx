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
                bar: "h-full w-1 rounded ",
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
    `relative w-100 h-10 border border-border bg-red-100`,
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
    value = 50,
    min = 0,
    max = 100,
    onValueChange,
    className,
    rounded = false,
    bg = "bg-background",
    fg = "bg-foreground",
    thumb = "none",
    thumbClass = "",
    ...divProps
}: SliderProps) => {
    const [isDragging, setIsDragging] = React.useState(false)
    const ref = React.useRef<HTMLDivElement>(null)
    const tref = React.useRef<HTMLDivElement>(null)
    const percentage = ((value - min) / (max - min)) * 100

    const updateValue = (clientX: number) => {
        const rect = ref.current!.getBoundingClientRect()
        let percent = (clientX - rect.left) / rect?.width
        percent = Math.max(0, Math.min(1, percent))
        const newValue = min + percent * (max - min)
        onValueChange?.(newValue)
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
        console.log("yo")
    }
    const handlePointerMove = (e: React.PointerEvent) => {
        if (isDragging) move(e)
    }

    let clampedPercentage = percentage; 
    if (ref.current && tref.current) {
        const trackWidth = ref.current.offsetWidth;
        const thumbWidth = tref.current.offsetWidth;
        const buffer = 1;

        // const minPerc = (thumbWidth / 2 / trackWidth) * 100; 
        // const maxPerc = 100 - minPerc+ 1;
        // clampedPercentage = Math.min(maxPerc, Math.max(minPerc, percentage));

        const minPerc = ((thumbWidth / 2 - buffer) / trackWidth) * 100;
        const maxPerc = ((trackWidth - thumbWidth / 2 + buffer) / trackWidth) * 100;
        clampedPercentage = Math.min(maxPerc, Math.max(minPerc, percentage));
    }
    return (
        <div
            ref={ref}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
            onPointerMove={handlePointerMove}
            className={cn(sliderCVA({ rounded }), bg, className)}
            {...divProps}
        >
            <div className="w-full h-full relative overflow-hidden rounded-[inherit]">
                <div
                    className={cn(
                        "absolute inset-0 h-full bg-blue-500 duration-150 ease-out pointer-events-none ",
                        isDragging ? 'transition-none' : 'transition-all',
                        fg
                    )}
                    style={{ width: `${percentage}%` }}
                />
            </div>

            <Thumb
                ref={tref}
                type={thumb}
                active={isDragging}
                // style={{ left: `${Math.min(99, Math.max(1, percentage))}%` }}
                style={{ left: `${clampedPercentage}%` }}
                className={cn(thumbClass, "transform -translate-x-1/2")}
            />
        </div>
    )
}



