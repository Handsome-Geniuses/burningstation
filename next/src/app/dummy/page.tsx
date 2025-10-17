'use client'

import { Button } from "@/components/ui/button"
import { LoadingGif } from "@/components/ui/loading-gif"
import { flask } from "@/lib/flask"
import React from "react"


type Actions = 'roller' | 'meter' | string



export default () => {
    const [loading, setLoading] = React.useState(false)
    const handleAction = async (action: Actions, kwargs: { [key: string]: any } = {}) => {
        setLoading(true)
        flask.post(`/sim/${action}`, { body: JSON.stringify(kwargs) })
        setLoading(false)
    }
    const BWrap = ({text, action, kwargs={}}:{text?:string, action:string, kwargs?: { [key: string]: any }})=><Button onClick={()=>handleAction(action,kwargs)}>{text??action}</Button>

    return (
        <div className="space-x-2 space-y-2">
            <h1>Pretend Actions for burning station!</h1>

            some io controls
            <br />
            <BWrap action="roller"/>
            <BWrap action="meter"/>
            <BWrap action="emergency" text="tog emergency"/>

            <br />
            ask some questions!
            <br />
            <BWrap action="question" kwargs={{type:0}} text="ask yes no" />
            <BWrap action="question" kwargs={{type:1}} text="ask number" />
            <BWrap action="question" kwargs={{type:2}} text="ask string" />

            <br />
            program
            <br />
            <BWrap action="start"/>
            <BWrap action="stop"/>

            <br />
            robot
            <br />
            <BWrap action="robot power on"/>
            <BWrap action="robot power off"/>
            <BWrap action="robot enable"/>
            <BWrap action="robot disable"/>
            <BWrap action="robot home"/>

            {loading && <LoadingGif variant={'full'} msg="loading" blur={true} className="bg-secondary/20" />}
        </div>
    )
}