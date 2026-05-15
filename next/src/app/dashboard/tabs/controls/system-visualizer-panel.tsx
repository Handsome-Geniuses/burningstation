import { cn } from "@/lib/utils";
import { PANEL, PanelHeader } from "./shared";
import { MeterSlots } from "./meter-slots";
import { Accordion, AccordionContent, AccordionItem } from "@/components/ui/accordion";
import { AccordionTrigger } from "@radix-ui/react-accordion";

export function SystemVisualizerPanel({ className }: React.ComponentProps<"div">) {
    return (

        // <div className={cn(PANEL, className)}>
        //     <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
        //         System Visualizer
        //     </div>
        //     <div className="w-full flex justify-center">
        //         <MeterSlots classname="" />
        //     </div>
        // </div>
        <Accordion type="single" collapsible className={cn(PANEL, "p-0",className)}>
            <AccordionItem key={"visualizer"} value={'visualizer'}>
                <AccordionTrigger asChild>
                    <PanelHeader text="System Visualizer"/>
                </AccordionTrigger>
                <AccordionContent asChild className="p-0">
                    <div className="w-full flex justify-center">
                        <MeterSlots classname="" />
                    </div>
                </AccordionContent>
            </AccordionItem>
        </Accordion>
    )
}