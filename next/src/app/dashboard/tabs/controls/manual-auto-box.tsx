import { flask } from "@/lib/flask"
import { useStoreContext } from "../../store"




export const ManualAutoBox = () => {
    const { systemState } = useStoreContext()
    const isManual = systemState.mode === 'manual'
    return (
        <div className="w-full flex flex-row text-center border border-border rounded-lg shadow-sm m-2">
            <div 
                className={`w-[50%] p-2 rounded-l-lg ${!isManual&&'bg-primary'}`}
                onClick={()=>isManual&&flask.handleAction('station', 'mode', { value: 'auto' })}
            >
                auto
            </div>
            <div 
                className={`w-[50%] p-2 rounded-r-lg ${isManual&&'bg-primary'}`}
                onClick={()=>!isManual&&flask.handleAction('station', 'mode', { value: 'manual' })}
            >
                manual
            </div>
        </div>
    )
}