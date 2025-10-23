import { Led } from "@/components/ui/indicators";
import { useStoreContext } from "../../store";
import { SystemState } from "../../store/system";

import Image from 'next/image';


// const Roller = ({ moving = false, reverse= false}) => {
//     const css = `
//         size-6 rounded-full 
//         bg-[repeating-linear-gradient(45deg,#cccccc,#cccccc_45%,#555555_45%,#555555_55%,#cccccc_55%)] 
//         animate-spin [animation-duration:2s] 
//         opacity-33
//         ${moving ? 'opacity-100' : '[animation-play-state:paused]'}
//         ${reverse ? '[animation-direction:reverse]' : ''}
//     `
//     return (
//         <div className="flex gap-0.5 border border-border rounded-full p-1">
//             {Array.from({ length: 6 }).map((_, i) => <div key={i} className={css} />)}
//         </div >
//     )
// }

const Roller = ({state=0}) => {

    const css = `
        size-6 rounded-full 
        bg-[repeating-linear-gradient(45deg,#cccccc,#cccccc_45%,#555555_45%,#555555_55%,#cccccc_55%)] 
        animate-spin [animation-duration:2s] 
        opacity-33
        ${state==1 || state==2 ? 'opacity-100' : '[animation-play-state:paused]'}
        ${state==2 ? '[animation-direction:reverse]' : ''}
    `
    return (
        <div className="flex gap-0.5 border border-border rounded-full p-1">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className={css} />)}
        </div >
    )
}

const Meter = ({ powered = false, sections = [false, false, false] }) => {
    const imgcss = "size-32";
    const boxcss = `absolute left-[78px] top-[25px] w-[100px] h-[70px] rounded ${powered ? "bg-primary" : "bg-border"}`
    const occupied = sections.every(Boolean)

    const clips = ["[clip-path:inset(0_60%_0_0)]", "[clip-path:inset(0_40%_0_40%)]", "[clip-path:inset(0_0_0_60%)]"]
    return (
        <div className="relative">
            <div className="relative">
                {/* <img src="meter.avif" alt="" className={`size-32 opacity-10`} /> */}
                <Image src="/meter.avif" alt="" width={64} height={64} className="!size-32 opacity-10"/>
                {clips.map((s, i) => (
                    // <img key={i} src="meter.avif" alt="" className={`size-32 ${sections[i] ? 'opacity-100' : 'opacity-0'} absolute inset-0 ${s}`} />
                    <Image key={i} src="/meter.avif" alt="" width={64} height={64} className={`!size-32 opacity-10 ${sections[i] ? 'opacity-100' : 'opacity-0'} absolute inset-0 ${s}`}/>
                ))}
                {occupied && <div className={boxcss}/>}
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

const MeterSlot = ({ index, systemState }: { index: number, systemState:SystemState }) => {
    const meterDetected = systemState.mds.slice(index * 3, index * 3 + 3).every(Boolean)
    const powered = meterDetected
    const mds = systemState.mds.slice(index * 3, index * 3 + 3)
    return (
        <div className="flex flex-col w-fit justice-center items-center">
            <Detector state={systemState.mds.slice(index * 3, index * 3 + 3)} />
            <Meter powered={powered} sections={mds} />
            {/* <Roller moving={systemState.rollersMoving[index]} reverse={systemState.rollersReverse[index]}/> */}
            <Roller state={systemState.motors[index]}/>
        </div>
    )
}

export const MeterSlots = ({classname='', ...props}) => {
    const { systemState } = useStoreContext()
    return (
        <div className={`flex w-fit ${classname}`} {...props}>
            {Array.from({ length: 3 }).map((_, i) => <MeterSlot key={i} index={i} systemState={systemState}/>)}
        </div>
    )
}