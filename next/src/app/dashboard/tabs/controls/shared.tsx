import { cn } from "@/lib/utils"
import React from "react"

export const PANEL = `rounded-lg shadow-md border border-border text-sm`
export const PANEL_HEADER = "rounded-t-lg border border-border text-center p-2 bg-secondary"

export const PanelHeader = ({ text, className, ...props }: { text: string, className?: string } & React.ComponentProps<"div">) => {
    return (
        <div className={cn(PANEL_HEADER, className)} {...props}>
            {text}
        </div>
    )
}