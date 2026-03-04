import { ManualAutoBox } from "./manual-auto-box"
import { MeterSlots } from "./meter-slots"

export const ControlsTab = () => {
    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
            <div className="lg:col-span-2 flex flex-col gap-4">
                <div className="rounded-lg shadow-md border border-border h-[42%]">
                    <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                        System Health & Status
                    </div>
                </div>
                <div className="rounded-lg shadow-md border border-border h-[58%]">
                    <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                        System Visualizer
                    </div>
                    <div className="w-full flex justify-center">
                        <MeterSlots classname=""/>
                    </div>
                </div>
            </div>
            <div className="rounded-lg shadow-md border border-border">
                <div className="rounded-t-lg border border-border text-center p-2 bg-secondary">
                    Control Panel
                </div>
                <div>
                    <ManualAutoBox/>
                </div>
            </div>
        </div>
    )
    return (
        // <div className="flex flex-col flex-1">
        //     <div className="mt-auto w-full flex justify-center">
        //         <MeterSlots classname="border border-border p-1 border-b-0"/>
        //     </div>
        // </div>


        
        <div className="grid grid-cols-1 lg:grid-cols-3">
            <div className="lg:col-span-2 flex flex-col">

                <div className="bg-white rounded-lg shadow-md border border-slate-200 overflow-hidden">
                    <div className="bg-slate-700 text-white px-4 py-2 text-center font-semibold">
                        System Health & Status
                    </div>
                    <div className="p-6 min-h-[120px]">
                    </div>
                </div>

                <div className="bg-white rounded-lg shadow-md border border-slate-200 overflow-hidden flex-1">
                    <div className="bg-slate-700 text-white px-4 py-2 text-center font-semibold">
                        System Visualizer
                    </div>
                    <div className="p-6 flex justify-center items-center min-h-[300px]">
                    </div>
                </div>

            </div>

            <div className="lg:col-span-1">

                <div className="bg-white rounded-lg shadow-md border border-slate-200 overflow-hidden h-full">
                    <div className="bg-slate-700 text-white px-4 py-2 text-center font-semibold">
                        Control & Override Panel
                    </div>
                    <div className="p-6">
                    </div>
                </div>

            </div>

        </div>
    )
}