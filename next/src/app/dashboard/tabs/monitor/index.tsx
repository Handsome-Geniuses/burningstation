import { Led, LedState } from "@/components/ui/indicators"
import { useStoreContext } from "../../store"

const MotorStateLedMap:Record<number, LedState> = {
    0: 'neutral',
    1: 'on',
    2: 'idle',
    3: 'neutral',
}

const Indicators = () => {
    const { systemState } = useStoreContext()
    return (
        <div className="grid grid-cols-[auto_auto] w-fit items-center gap-2">
            <div className="flex gap-1 items-center w-fit">{systemState.motors.map((v, i) => <Led key={i} state={MotorStateLedMap[v]??'off'} />)}</div>
            <p>roller motors</p>

            <div className="flex gap-1 items-center w-fit">{systemState.mds.map((b, i) => <Led key={i} state={b} />)}</div>
            <p>meters detected</p>

            <div className="flex gap-1 items-center w-fit"><Led state={'off'} /></div>
            <p>robot power</p>

            <div className="flex gap-1 items-center w-fit"><Led state={systemState.emergency ? "off" : "neutral"} /></div>
            <p>EMERGENCY</p>
        </div>
    )
}



export const MonitorTab = ()=>{
    return (
        <div className="p-4">
            <Indicators />
        </div>
    )
}