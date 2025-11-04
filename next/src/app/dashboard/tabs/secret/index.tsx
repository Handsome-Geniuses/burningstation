import { SnapBar } from "@/components/ui/snap-bar"
import { MeterSlots } from "../controls/meter-slots"
import { flask } from "@/lib/flask"
import { Button } from "@/components/ui/button"

const TowerLampControls = () => {
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
                        onClick={() => flask.handleAction('station', 'lamp', { type: type })}
                    >
                        {type}
                    </Button>
                ))}
            </div>
        </div>
    )
}

const MotorControls = () => {
    return (
        <div className="flex flex-col items-center justify-center">
            <div>Motor Control</div>
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
        <div className="flex flex-col gap-4 flex-1">
            <TowerLampControls />

            <div className="items-end h-full p-2 flex justify-center gap-4">
                <MeterSlots classname="border border-border p-1" />
                <MotorControls />
            </div>

        </div>
    )
}