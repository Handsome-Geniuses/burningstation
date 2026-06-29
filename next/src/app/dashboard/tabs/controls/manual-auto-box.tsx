import { flask } from "@/lib/flask"
import { useStoreContext } from "../../store"
import { useAsyncAction } from "@/hooks/useAsyncAction"
import { Button } from "@/components/ui/button"




export const ManualAutoBox = () => {
    const { systemState } = useStoreContext()
    const isManual = systemState.mode === 'manual'
    const  {running, run} = useAsyncAction()

    const _toggle = async ()=>{
        if (isManual) flask.handleAction('station', 'mode', { value: 'auto' })
        else flask.handleAction('station', 'mode', { value: 'manual' })
    }

    const toggle = run(()=>_toggle())
    return (
        <div className="w-full flex flex-row text-center border border-border rounded-lg shadow-sm">
            <Button 
                variant={"ghost"}
                className={`w-[50%] p-2 rounded-l-lg ${!isManual&&'bg-primary'}`}
                onClick={toggle}
                debounceSeconds={0.3}
                disabled={running}
            >
                auto
            </Button>
            <Button 
                variant={"ghost"}
                className={`w-[50%] p-2 rounded-r-lg ${isManual&&'bg-primary'}`}
                onClick={toggle}
                debounceSeconds={0.3}
                disabled={running}
            >
                manual
            </Button>
        </div>
    )
}