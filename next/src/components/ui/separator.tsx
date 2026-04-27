// /components/ui/separator.tsx
import * as React from "react"

export function Separator({
    className = "",
    orientation = "horizontal",
}: {
    className?: string
    orientation?: "horizontal" | "vertical"
}) {
    return (
        <div
            role="separator"
            aria-orientation={orientation}
            className={[
                "shrink-0 bg-border",
                orientation === "horizontal"
                    ? "h-[1px] w-full"
                    : "h-full w-[1px]",
                className,
            ].join(" ")}
        />
    )
}