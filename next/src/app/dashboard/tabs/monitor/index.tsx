import { Led, LedState } from "@/components/ui/indicators"
import { useStoreContext } from "../../store"
import React from "react"

const MotorStateLedMap:Record<number, LedState> = {
    0: 'neutral',
    1: 'on',
    2: 'idle',
    3: 'neutral',
}

const lampBg = (state:number|boolean, dc:number)=>{
    if (!state) return 'bg-[rgb(105,105,105,0.15)]'
    const intensity = dc>20?(dc/100).toFixed(1):0.2
    return `bg-[rgba(255,255,0,${intensity})]`
}
const LampIndicator = ({lamp}:{lamp:[number, number, number, number]})=>{
    return (
        <div className="flex gap-1 items-center w-fit">
            <Led state="neutral" className={lampBg(lamp[0],lamp[2])} />
            <Led state="neutral" className={lampBg(lamp[1],lamp[3])} />
        </div>
    )
}

export const Indicators = () => {
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

            <div className="flex gap-1 items-center w-fit">{systemState.tower.map((b, i) => <Led key={i} state={b} />)}</div>
            <p>tower rgb buz</p>

            {/* <div className="flex gap-1 items-center w-fit">{systemState.lamp.slice(0,2).map((b, i) => <Led key={i} state={b} />)}</div> */}
            <LampIndicator lamp={systemState.lamp}/>
            <p>lamp</p>
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