import { cn } from "@/lib/utils";
import { PANEL } from "./shared";


export function SystemHealthPanel({ className }: React.ComponentProps<"div">) {
    return (
        <div className={cn(PANEL, className)}>
            <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                System Health & Status
            </div>
            <div className="w-full flex justify-center"></div>
        </div>
    )
}