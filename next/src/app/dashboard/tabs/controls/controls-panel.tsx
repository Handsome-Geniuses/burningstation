import { cn } from "@/lib/utils";
import { PANEL, PANEL_HEADER } from "./shared";
import { ManualAutoBox } from "./manual-auto-box";
import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import { flask } from "@/lib/flask";
import { SystemState } from "../../store/system";
import { Separator } from "@/components/ui/separator";

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


const JobsDivider = ({ isManual }: { isManual: boolean }) => {
    return (
        <div>
            <SectionDivider label="jobs" className="pt-4" />
            <div className="grid grid-cols-2 gap-2 pt-2">
                <Button variant="outline" onClick={() => flask.handleAction('program', 'manual', { program: 'start_passive_job' })} disabled={!isManual}>
                    passive
                </Button>
                <Button variant="outline" onClick={() => flask.handleAction('program', 'manual', { program: 'start_physical_job' })} disabled={!isManual}>
                    physical
                </Button>
            </div>
        </div>
    )
}

const RobotDivider = ({ isManual }: { isManual: boolean }) => {
    const robotShutDown = async () => {
        notify.info("[test] shut down")
        flask.handleAction('station', 'robot', { "wdyw": "home" })
    }
    const robotSafeHome = async () => {
        notify.info("[test] robot safe home")
        flask.handleAction('station', 'robot', { "wdyw": "home" })
    }
    return (
        <div>
            <SectionDivider label="robot tools" className="pt-4" />
            <div className="grid grid-cols-2 gap-2 pt-2">
                <Button onClick={robotShutDown} variant="outline" disabled={!isManual}>
                    shut down
                </Button>
                <Button onClick={robotSafeHome} variant="outline" disabled={!isManual} >
                    safe home
                </Button>
            </div>
        </div>
    )
}

export function ControlsPanel({ systemState, className }: { systemState: SystemState } & React.ComponentProps<"div">) {
    return (
        <div className={cn(PANEL, className)}>
            <div className={PANEL_HEADER}>
                Control Panel
            </div>
            <div className="flex flex-col p-4">
                <SectionDivider label="MODE selector" />
                <ManualAutoBox />

                <JobsDivider isManual={systemState.mode == "manual"} />
                <RobotDivider isManual={systemState.mode == "manual"} />
            </div>
        </div>
    )
}