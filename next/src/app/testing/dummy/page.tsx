'use client'

import { Button } from "@/components/ui/button"
import { LoadingGif } from "@/components/ui/loading-gif"
import { flask } from "@/lib/flask"
import React from "react"


type Actions = 'roller' | 'meter' | string



export default () => {
    const [loading, setLoading] = React.useState(false)
    const SimWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('sim', action, kwargs)}>{text ?? action}</Button>
    const OverrideWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('override', action, kwargs)}>{text ?? action}</Button>
    const OverrideUpDownWrap = ({ text, dn_action, dn_kwargs = {} , up_action, up_kwargs = {} }: { text?: string, dn_action: string, dn_kwargs?: { [key: string]: any }, up_action: string, up_kwargs?: { [key: string]: any } }) => 
        <Button 
            onMouseDown={() => flask.handleAction('override', dn_action, dn_kwargs)}
            onMouseUp={() => flask.handleAction('override', up_action, up_kwargs)}
        >
            {text ?? dn_action}
        </Button>
        
    const OverrideMotorWrap = ({ text, value_list }: { text?: string, value_list:number[]}) => 
        <Button 
            onMouseDown={() => flask.handleAction('override', 'motor', { value_list: value_list })}
            onMouseUp={() => flask.handleAction('override', 'motor', { value_list: [0,0,0] })}
        >
            {text ?? 'motor'}
        </Button>

    const StationWrap = ({ text, action, kwargs = {} }: { text?: string, action: string, kwargs?: { [key: string]: any } }) => <Button onClick={() => flask.handleAction('station',action, kwargs)}>{text ?? action}</Button>

    return (
        <div className="space-x-2 space-y-2 font-mono">
            <h1>Pretend Actions for burning station!</h1>

            some io controls
            <br />
            <SimWrap action="roller" />
            <SimWrap action="emergency" text="tog emergency" />

            <br />
            Control rollers manually! It forces so careful
            <br />
            <OverrideMotorWrap text="off" value_list={[0,0,0]}/>
            <OverrideMotorWrap text="+all" value_list={[1,1,1]}/>
            <OverrideMotorWrap text="-all" value_list={[2,2,2]}/>

            <br />
            <OverrideMotorWrap text="+L" value_list={[1,0,0]}/>
            <OverrideMotorWrap text="+LM" value_list={[1,1,0]}/>
            <OverrideMotorWrap text="+M" value_list={[0,1,0]}/>
            <OverrideMotorWrap text="+MR" value_list={[0,1,1]}/>
            <OverrideMotorWrap text="+R" value_list={[0,0,1]}/>
            <br />

            <OverrideMotorWrap text="-L" value_list={[2,0,0]}/>
            <OverrideMotorWrap text="-LM" value_list={[2,2,0]}/>
            <OverrideMotorWrap text="-M" value_list={[0,2,0]}/>
            <OverrideMotorWrap text="-MR" value_list={[0,2,2]}/>
            <OverrideMotorWrap text="-R" value_list={[0,0,2]}/>

            <br />
            Buttons users will use. Disabled with mock tho
            <br />
            <StationWrap action="load" text="load L" kwargs={{type:'L'}}/>
            <StationWrap action="load" text="load M" kwargs={{type:'M'}}/>
            <StationWrap action="load" text="load R" kwargs={{type:'R'}}/>
            <StationWrap action="load" text="load RM" kwargs={{type:'RM'}}/>
            <StationWrap action="load" text="shift all" kwargs={{type:'ALL'}}/>


            <br />
            ask some questions!
            <br />
            <SimWrap action="question" kwargs={{ type: 0 }} text="ask yes no" />
            <SimWrap action="question" kwargs={{ type: 1 }} text="ask number" />
            <SimWrap action="question" kwargs={{ type: 2 }} text="ask string" />

            <br />
            <br />
            <br />
            meter move simulation
            <br />
            <SimWrap action="meter" kwargs={{ type: 0 }} text="randomize" />
            <SimWrap action="meter" kwargs={{ type: 10 }} text="user loading meter" />
            <SimWrap action="meter" kwargs={{ type: 14 }} text="user unloading meter" />
            <SimWrap action="meter" kwargs={{ type: 15 }} text="user pressed shift ALL" />
            <br />
            <SimWrap action="meter" kwargs={{ type: 11 }} text="user pressed meter load" />
            <SimWrap action="meter" kwargs={{ type: 12 }} text="user pressed load middle" />
            <SimWrap action="meter" kwargs={{ type: 13 }} text="user pressed load right" />


            <br />
            program
            <br />
            <SimWrap action="run" kwargs={{ type: 0 }} text="run L passive test" />
            <SimWrap action="run" kwargs={{ type: 1 }} text="run M active test" />

            <br />
            robot
            <br />
            <SimWrap action="robot power on" />
            <SimWrap action="robot power off" />
            <SimWrap action="robot enable" />
            <SimWrap action="robot disable" />
            <SimWrap action="robot home" />

            {loading && <LoadingGif variant={'full'} msg="loading" blur={true} className="bg-secondary/20" />}
        </div>
    )
}


