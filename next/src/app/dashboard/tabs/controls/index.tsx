import { MeterSlots } from "./meter-slots"

export const ControlsTab = ()=>{
    return (
        <div className="grid grid-cols-[25%_50%_25%] flex-1">
            <div></div>
            <MeterSlots classname="mt-auto border border-border p-1 border-b-0"/>
            <div></div>
        </div>
    )
}