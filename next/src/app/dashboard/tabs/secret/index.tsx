import { SnapBar } from "@/components/ui/snap-bar"
import { Indicators } from "../monitor"
import { MeterSlots } from "../controls/meter-slots"
import { flask } from "@/lib/flask"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { useStoreContext } from "../../store"
import React from "react"
import { useDebounce } from "@/hooks/useDebounce"

const TowerLampControls = () => {
    const { systemState } = useStoreContext()
    const [value1, setValue1] = React.useState(systemState.lamp[2])
    const [value2, setValue2] = React.useState(systemState.lamp[3])
    const timeoutRef = React.useRef<NodeJS.Timeout | null>(null)

    const dbdc1 = useDebounce((v) => flask.handleAction('station', 'lamp', { type: 'L1', dc: Math.floor(v) }), 100)
    const dbdc2 = useDebounce((v) => flask.handleAction('station', 'lamp', { type: 'L2', dc: Math.floor(v) }), 100)

    const updateDC1 = (v: number) => {
        setValue1(v)
        dbdc1(v)
    }
    const updateDC2 = (v: number) => {
        setValue2(v)
        dbdc2(v)
    }

    return (
        <div className="flex flex-col items-center justify-center">
            <div>Tower Lamp Controls</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {['R', 'Y', 'G', 'BUZ'].map((type, i) => (
                    <Button
                        key={i}
                        onClick={() => flask.handleAction('station', 'tower', { type: type })}
                    >
                        {type}
                    </Button>
                ))}
                {['L1', 'L2'].map((type, i) => (
                    <Button
                        key={i}
                        onClick={() => flask.handleAction('station', 'lamp', { type: type, state: !systemState.lamp[i] })}
                    >
                        {type}
                    </Button>
                ))}
            </div>
            <Slider
                className="h-8 w-60 mt-1"
                value={value1}
                onValueChange={updateDC1}
                min={0}
                max={100}
                thumb={"ball"}
            />
            <Slider
                className="h-8 w-60 mt-4"
                value={value2}
                onValueChange={updateDC2}
                min={0}
                max={100}
                thumb={"ball"}
            />
        </div>
    )
}

const MeterLoadControls = () => {
    return (
        <div className="flex flex-col items-center justify-center">
            <div>Meter Load Controls</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {['L', 'M', 'R', 'ALL'].map((s, i) => (
                    <Button
                        key={s}
                        onClick={() => flask.handleAction('station', 'load', { type: s })}
                    >
                        load {s}
                    </Button>
                ))}
                <Button onClick={() => flask.handleAction('station', 'load', { type: 'ML' })}>M to L</Button>
                <Button onClick={() => flask.handleAction('station', 'load', { type: 'RM' })}>R to M</Button>
            </div>

        </div>
    )

}

const MotorControls = () => {
    return (
        <div className="flex flex-col items-center justify-center">
            <div>Motor Control OVERRIDE</div>
            <div className="grid grid-cols-3 gap-1 p-1">
                {[
                    { text: "L", left: [2, 0, 0], right: [1, 0, 0] },
                    { text: "M", left: [0, 2, 0], right: [0, 1, 0] },
                    { text: "R", left: [0, 0, 2], right: [0, 0, 1] },
                    { text: "LM", left: [2, 2, 0], right: [1, 1, 0] },
                    { text: "all", left: [2, 2, 2], right: [1, 1, 1] },
                    { text: "MR", left: [0, 2, 2], right: [0, 1, 1] },
                ].map(({ text, left, right }) => (
                    <SnapBar
                        key={text}
                        text={text}
                        onLeft={() => flask.handleAction('override', 'motor', { value_list: left })}
                        onRight={() => flask.handleAction('override', 'motor', { value_list: right })}
                        onRelease={() => flask.handleAction('override', 'motor', { value_list: [0, 0, 0] })}
                    />
                ))}
            </div>
        </div>
    )
}

export const SecretTab = () => {
    return (
        // <div className="flex flex-col gap-4 flex-1">
        //     <TowerLampControls />
        //     <MeterLoadControls />

        //     <div className="items-end h-full p-2 flex justify-center gap-4">
        //         <MeterSlots classname="border border-border p-1" />
        //         <MotorControls />
        //     </div>
        // </div>
        <div className="flex items-center justify-around">
            <div className="bg-muted/70 gap-2 p-4 flex flex-col items-center">
                <Indicators />
                <MeterSlots classname="border border-border p-1" />
            </div>
            <div className="bg-muted/70 gap-2 p-4 flex flex-col items-center">
                <TowerLampControls />
                <MeterLoadControls />
                <MotorControls />
            </div>
        </div>
    )
}