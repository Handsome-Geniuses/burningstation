
import { useStoreContext } from "../../store"
import { ControlsPanel } from "./controls-panel"
import { SystemHealthPanel } from "./system-health-panel"
import { SystemVisualizerPanel } from "./system-visualizer-panel"



export const ControlsTab = () => {
    const { systemState } = useStoreContext()

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
            <div className="lg:col-span-2 flex flex-col gap-4">
                <SystemHealthPanel className="h-[42%]"/>
                <SystemVisualizerPanel/>
            </div>
            <ControlsPanel systemState={systemState}/>
            
        </div>
    )
}