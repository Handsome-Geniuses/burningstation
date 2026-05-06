import { cn } from "@/lib/utils";
import { PANEL } from "./shared";
import { MeterSlots } from "./meter-slots";

export function SystemVisualizerPanel({ className }: React.ComponentProps<"div">) {
    return (
        <div className={cn(PANEL, className)}>
            <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                System Visualizer
            </div>
            <div className="w-full flex justify-center">
                <MeterSlots classname="" />
            </div>
        </div>
    )
}