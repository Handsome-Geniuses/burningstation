import { ManualAutoBox } from "./manual-auto-box"
import { MeterSlots } from "./meter-slots"
// import { Separator } from "@/components/ui/separator"
import { Separator } from "@/components/ui/separator"
import { Button } from "@/components/ui/button"
import { useStoreContext } from "../../store"
import { notify } from "@/lib/notify"
import { flask } from "@/lib/flask"

type SectionDividerProps = {
    label: string
    className?: string
}

export const SectionDivider = ({ label, className }: SectionDividerProps) => {
    return (
        <div className={`flex items-center gap-3 ${className ?? ""}`}>
            <Separator className="flex-1" />
            <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">
                {label}
            </span>
            <Separator className="flex-1" />
        </div>
    )
}

export const ControlsTab = () => {
    const { systemState } = useStoreContext()

    const robotShutDown = async ()=>{
        notify.info("[test] shut down")
        flask.handleAction('station', 'robot', {"wdyw":"home"})
    }
    const robotSafeHome = async ()=>{
        notify.info("[test] robot safe home")
        flask.handleAction('station', 'robot', {"wdyw":"home"})
    }

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
            <div className="lg:col-span-2 flex flex-col gap-4">
                <div className="rounded-lg shadow-md border border-border h-[42%]">
                    <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                        System Health & Status
                    </div>
                    <div className="w-full flex justify-center"></div>
                </div>

                <div className="rounded-lg shadow-md border border-border h-[58%]">
                    <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                        System Visualizer
                    </div>
                    <div className="w-full flex justify-center">
                        <MeterSlots classname="" />
                    </div>
                </div>
            </div>

            <div className="rounded-lg shadow-md border border-border">
                <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                    Control Panel
                </div>
                <div className="flex flex-col p-4">
                    <SectionDivider label="MODE selector" />
                    <ManualAutoBox />

                    <SectionDivider label="robot tools" className="pt-4" />
                    <div className="grid grid-cols-2 gap-2 pt-2">
                        <Button onClick={robotShutDown} variant="outline" disabled={systemState.mode!='manual'}>
                            shut down
                        </Button>
                        <Button onClick={robotSafeHome} variant="outline" disabled={systemState.mode!='manual'} >
                            safe home
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    )
}