'use client'

import { Button } from "@/components/ui/button"
import { LoadingGif } from "@/components/ui/loading-gif"
import { flask } from "@/lib/flask"
import React from "react"


import { SnapBar } from "@/components/ui/snap-bar"



const SimWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('sim', action, kwargs)}>{text ?? action}</Button>
const OverrideWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('override', action, kwargs)}>{text ?? action}</Button>
const OverrideUpDownWrap = ({ text, dn_action, dn_kwargs = {}, up_action, up_kwargs = {} }: { text?: string, dn_action: string, dn_kwargs?: { [key: string]: any }, up_action: string, up_kwargs?: { [key: string]: any } }) =>
    <Button
        onMouseDown={() => flask.handleAction('override', dn_action, dn_kwargs)}
        onMouseUp={() => flask.handleAction('override', up_action, up_kwargs)}
    >
        {text ?? dn_action}
    </Button>

const OverrideMotorWrap = ({ text, value_list }: { text?: string, value_list: number[] }) =>
    <Button
        onMouseDown={() => flask.handleAction('override', 'motor', { value_list: value_list })}
        onMouseUp={() => flask.handleAction('override', 'motor', { value_list: [0, 0, 0] })}
    >
        {text ?? 'motor'}
    </Button>

const StationWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('station', action, kwargs)}>{text ?? action}</Button>


const LampControls = ()=>{
    return (
        <>
            <div>tower and lamp control</div>
            <div className="flex gap-2">
                <StationWrap action="tower" text="R" kwargs={{ type: 'R' }} />
                <StationWrap action="tower" text="Y" kwargs={{ type: 'Y' }} />
                <StationWrap action="tower" text="G" kwargs={{ type: 'G' }} />
                <StationWrap action="tower" text="BUZ" kwargs={{ type: 'BUZ' }} />
                <StationWrap action="lamp" text="lamp1" kwargs={{ type: 'L1' }} />
                <StationWrap action="lamp" text="lamp2" kwargs={{ type: 'L2' }} />
            </div>
        </>
    )
}

const MotorControls = () => {
    return (
        <>
            <div>Control rollers manually! It forces so careful</div>
            <div className="flex gap-2">
                <OverrideMotorWrap text="off" value_list={[0, 0, 0]} />
                <SnapBar
                    onLeft={() => flask.handleAction('override', 'motor', { value_list: [2, 2, 2] })}
                    onRight={() => flask.handleAction('override', 'motor', { value_list: [1, 1, 1] })}
                    onRelease={() => flask.handleAction('override', 'motor', { value_list: [0, 0, 0] })}
                    text="all"
                />
            </div>
            <div className="flex gap-2">
                {[
                    { text: "L", left: [2, 0, 0], right: [1, 0, 0] },
                    { text: "LM", left: [2, 2, 0], right: [1, 1, 0] },
                    { text: "M", left: [0, 2, 0], right: [0, 1, 0] },
                    { text: "MR", left: [0, 2, 2], right: [0, 1, 1] },
                    { text: "R", left: [0, 0, 2], right: [0, 0, 1] },
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
        </>
    )
}

type Actions = 'roller' | 'meter' | string
export default () => {
    const [loading, setLoading] = React.useState(false)

    return (
        <div className="flex flex-col space-x-2 space-y-2 font-mono m-2 overflow-shown">
            <div>some io controls</div>
            <div className="flex gap-2">
                <SimWrap action="roller" />
                <SimWrap action="emergency" text="tog emergency" />
            </div>

            <LampControls />
            <MotorControls />



            <div>Buttons users will use. Disabled with mock tho</div>
            <div className="flex gap-2">
                <StationWrap action="load" text="load L" kwargs={{ type: 'L' }} />
                <StationWrap action="load" text="load M" kwargs={{ type: 'M' }} />
                <StationWrap action="load" text="load R" kwargs={{ type: 'R' }} />
                <StationWrap action="load" text="load RM" kwargs={{ type: 'RM' }} />
                <StationWrap action="load" text="shift all" kwargs={{ type: 'ALL' }} />
            </div>



            <div>meter move simulation</div>
            <div className="flex gap-2">
                <SimWrap action="meter" kwargs={{ type: 0 }} text="randomize" />
                <SimWrap action="meter" kwargs={{ type: 10 }} text="user loading meter" />
                <SimWrap action="meter" kwargs={{ type: 14 }} text="user unloading meter" />
                <SimWrap action="meter" kwargs={{ type: 15 }} text="user pressed shift ALL" />
            </div>
            <div className="flex gap-2">
                <SimWrap action="meter" kwargs={{ type: 11 }} text="user pressed meter load" />
                <SimWrap action="meter" kwargs={{ type: 12 }} text="user pressed load middle" />
                <SimWrap action="meter" kwargs={{ type: 13 }} text="user pressed load right" />
            </div>


            <div>ask some questions!</div>
            <div className="flex gap-2">
                <SimWrap action="question" kwargs={{ type: 0 }} text="ask yes no" />
                <SimWrap action="question" kwargs={{ type: 1 }} text="ask number" />
                <SimWrap action="question" kwargs={{ type: 2 }} text="ask string" />
            </div>

            {loading && <LoadingGif variant={'full'} msg="loading" blur={true} className="bg-secondary/20" />}
        </div>
    )
}





/**
<OverrideMotorWrap text="+all" value_list={[1, 1, 1]} />
<OverrideMotorWrap text="-all" value_list={[2, 2, 2]} />
<OverrideMotorWrap text="+L" value_list={[1, 0, 0]} />
<OverrideMotorWrap text="+LM" value_list={[1, 1, 0]} />
<OverrideMotorWrap text="+M" value_list={[0, 1, 0]} />
<OverrideMotorWrap text="+MR" value_list={[0, 1, 1]} />
<OverrideMotorWrap text="+R" value_list={[0, 0, 1]} />
<OverrideMotorWrap text="-L" value_list={[2, 0, 0]} />
<OverrideMotorWrap text="-LM" value_list={[2, 2, 0]} />
<OverrideMotorWrap text="-M" value_list={[0, 2, 0]} />
<OverrideMotorWrap text="-MR" value_list={[0, 2, 2]} />
<OverrideMotorWrap text="-R" value_list={[0, 0, 2]} />
 */