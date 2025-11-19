import { Led } from "@/components/ui/indicators";
import { useStoreContext } from "../../store";
import { SystemState } from "../../store/system";
import { MeterSvg } from "@/components/ui/meter";
import { cn } from "@/lib/utils";
import Image from 'next/image';

const Roller = ({ state = 0 }) => {

    const css = `
        size-6 rounded-full 
        bg-[repeating-linear-gradient(45deg,#cccccc,#cccccc_45%,#555555_45%,#555555_55%,#cccccc_55%)] 
        animate-spin [animation-duration:2s] 
        opacity-33
        ${state == 1 || state == 2 ? 'opacity-100' : '[animation-play-state:paused]'}
        ${state == 2 ? '[animation-direction:reverse]' : ''}
    `
    return (
        <div className="flex gap-0.5 border border-border rounded-full p-1">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className={css} />)}
        </div >
    )
}

const Meter = ({ powered = false, sections = [false, false, false] }) => {
    const occupied = sections.every(Boolean)
    const stops = [40, 60]
    const webkitMask = `linear-gradient(to right, ${[0, 1, 2].map(i => {
        const start = i === 0 ? 0 : stops[i - 1];
        const end = i === 2 ? 100 : stops[i];
        return `${sections[i] ? 'black' : 'transparent'} ${start}%, ${sections[i] ? 'black' : 'transparent'} ${end}%`;
    }).join(', ')
        })`
    const meterCssBase = "size-32 scale-x-140"
    return (
        <div className="relative z-1">
            <div className="relative">
                <MeterSvg className={cn(meterCssBase, "opacity-10")} />
                <MeterSvg
                    className={cn(meterCssBase, "absolute inset-0")}
                    style={{
                        WebkitMask: webkitMask,
                        WebkitMaskRepeat: 'no-repeat',
                        WebkitMaskSize: '100% 100%',
                    }}
                    baseColor="fill-border"
                    meterColor="fill-background"
                    screenColor={occupied ? 'fill-primary' : 'fill-border'}
                />
            </div>
        </div>
    )
}


const Detector = ({ state }: { state: boolean[] }) => {
    return (
        <div className="flex gap-1 items-center w-fit z-2">
            {state.map((b, i) => <Led key={i} state={b} />)}
        </div>
    )
}

const MeterSlot = ({ index, systemState }: { index: number, systemState: SystemState }) => {
    const meterDetected = systemState.mds.slice(index * 3, index * 3 + 3).every(Boolean)
    const powered = meterDetected
    const mds = systemState.mds.slice(index * 3, index * 3 + 3)
    return (
        <div className="flex flex-col w-fit justice-center items-center">
            <Detector state={systemState.mds.slice(index * 3, index * 3 + 3)} />
            <Meter powered={powered} sections={mds} />
            {/* <Roller moving={systemState.rollersMoving[index]} reverse={systemState.rollersReverse[index]}/> */}
            <Roller state={systemState.motors[index]} />
        </div>
    )
}

const Lamp = ({ systemState }: { systemState: SystemState }) => {
    const back = systemState.lamp[0]
    const front = systemState.lamp[1]
    const isOn = back || front
    const light = `blur-3xl absolute top-0 left-1/2 -translate-x-1/2 w-40 h-[105%] bg-gradient-to-b from-yellow-200/80 to-yellow-100/10 [clip-path:polygon(30%_10px,70%_10px,100%_100%,0%_100%)]`;
    const lamp = `z-3 absolute left-1/2 -translate-x-1/2 top-0 w-20 h-2 rounded-b-2xl border-border border-2 border-t-0 bg-yellow-200/20 ${isOn ? 'bg-yellow-200/50' : ''} ${back && front ? 'bg-yellow-300/50' : ''}`;
    return (
        <>

            {back && 
                <div 
                    className={cn(light,"z-0")}
                    style={{WebkitMask: `linear-gradient(to bottom, black ${systemState.lamp[2]}%, transparent ${systemState.lamp[2]}%)`}}
            />}
            {front && 
                <div 
                    className={cn(light,"z-2")}
                    style={{WebkitMask: `linear-gradient(to bottom, black ${systemState.lamp[3]}%, transparent ${systemState.lamp[3]}%)`}}
            />}

            <div className={lamp} />
        </>
    )
}

export const MeterSlots = ({ classname = '', ...props }) => {
    const { systemState } = useStoreContext()
    return (
        <div className={`flex w-fit ${classname} relative pt-3`} {...props}>
            <Lamp systemState={systemState} />
            {Array.from({ length: 3 }).map((_, i) => <MeterSlot key={i} index={i} systemState={systemState} />)}
        </div>
    )
}