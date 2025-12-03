import { MeterSlots } from "./meter-slots"

export const ControlsTab = ()=>{
    return (
        <div className="flex flex-col flex-1">
            <div className="mt-auto w-full flex justify-center">
                <MeterSlots classname="border border-border p-1 border-b-0"/>
            </div>
        </div>
        // <div className="grid grid-cols-[25%_50%_25%] flex-1">
        //     <div></div>
        //     <MeterSlots classname="mt-auto border border-border p-1 border-b-0 w-full bg-red-100"/>
        //     <div></div>
        // </div>
    )
}