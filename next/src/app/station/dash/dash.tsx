'use client'
import { Led } from "@/components/ui/indicators"
import { useStoreContext } from "../store"
import { Question } from "../question/question"
import { LoadingGif } from "@/components/ui/loading-gif"

const Roller = ({ active = false }) => {
    const css = `
        size-6 rounded-full 
        bg-[repeating-linear-gradient(45deg,#cccccc,#cccccc_45%,#555555_45%,#555555_55%,#cccccc_55%)] 
        animate-spin [animation-duration:2s] 
        opacity-33
        ${active ? 'opacity-100' : '[animation-play-state:paused]'}
    `
    return (
        <div className="flex gap-0.5 border border-border rounded-full p-1">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className={css} />)}
        </div >
    )
}

const Meter = ({ powered = false, sections = [false, false, false] }) => {
    const imgcss = "size-32";
    const boxcss = `absolute left-[78px] top-[26px] w-[100px] h-[70px] rounded ${powered ? "bg-primary" : "bg-border"}`
    const occupied = sections.every(Boolean)

    const clips = ["[clip-path:inset(0_60%_0_0)]", "[clip-path:inset(0_40%_0_40%)]", "[clip-path:inset(0_0_0_60%)]"]
    return (
        <div className="relative">
            <div className="relative">
                <img src="meter.avif" alt="" className={`size-32 opacity-10`} />
                {clips.map((s,i)=><img key={i}src="meter.avif" alt="" className={`size-32 ${sections[i]?'opacity-100':'opacity-1'} absolute inset-0 ${s}`} />)}
            </div>
        </div>
    )
}

const Detector = ({ state }: { state: boolean[] }) => {
    return (
        <div className="flex gap-1 items-center w-fit">
            {state.map((b, i) => <Led key={i} state={b} />)}
        </div>
    )
}

const MeterSlot = ({ index }: { index: number }) => {
    const { systemState } = useStoreContext()
    const meterDetected = systemState.mds.slice(index * 3, index * 3 + 3).every(Boolean)
    const powered = meterDetected
    const rollersMoving = systemState.rollersMoving[index]
    const mds = systemState.mds.slice(index * 3, index * 3 + 3)
    return (
        <div className="flex flex-col w-fit justice-center items-center">
            <Detector state={systemState.mds.slice(index * 3, index * 3 + 3)} />
            <Meter powered={powered} sections={mds} />
            <Roller active={rollersMoving} />
        </div>
    )
}

const Indicators = () => {
    const { systemState } = useStoreContext()
    return (
        <div className="grid grid-cols-[auto_auto] w-fit items-center gap-2">
            <div className="flex gap-1 items-center w-fit">{systemState.rollersMoving.map((b, i) => <Led key={i} state={b} />)}</div>
            <p>rollers moving</p>

            <div className="flex gap-1 items-center w-fit">{systemState.mds.map((b, i) => <Led key={i} state={b} />)}</div>
            <p>meters detected</p>

            <div className="flex gap-1 items-center w-fit"><Led state={'off'} /></div>
            <p>robot power</p>

            <div className="flex gap-1 items-center w-fit"><Led state={systemState.emergency ? "off" : "neutral"} /></div>
            <p>EMERGENCY</p>
        </div>
    )
}

export const Dash = () => {
    const { systemState } = useStoreContext()
    return (
        <div className="">
            <Indicators />
            <div className="flex border border-border w-fit">
                {Array.from({ length: 3 }).map((_, i) => <MeterSlot key={i} index={i} />)}
            </div>
        </div>
    )
}
