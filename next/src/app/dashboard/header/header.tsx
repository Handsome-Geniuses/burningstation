'use client'
import { useCountdown } from "@/hooks/useCountdown"
import NumberFlow, { NumberFlowGroup } from "@number-flow/react"
import React from "react"
import { useStoreContext } from "../store"
import { notify } from "@/lib/notify"


const Clock = () => {
    const [hh, setHH] = React.useState(0)
    const [mm, setMM] = React.useState(0)
    const [ss, setSS] = React.useState(0)
    React.useEffect(() => {
        const tick = () => {
            const now = new Date()
            const hh = String(now.getHours()).padStart(2, '0')
            const mm = String(now.getMinutes()).padStart(2, '0')
            const ss = String(now.getSeconds()).padStart(2, '0')
            setHH(now.getHours())
            setMM(now.getMinutes())
            setSS(now.getSeconds())
        }
        tick()
        const timer = setInterval(tick, 1000)
        return () => clearInterval(timer)
    }, [])
    return (
        <div>
            <NumberFlowGroup>
                <NumberFlow value={hh} format={{ minimumIntegerDigits: 2 }} />
                <NumberFlow
                    prefix=":"
                    value={mm}
                    digits={{ 1: { max: 5 } }}
                    format={{ minimumIntegerDigits: 2 }}
                />
                <NumberFlow
                    prefix=":"
                    value={ss}
                    digits={{ 1: { max: 5 } }}
                    format={{ minimumIntegerDigits: 2 }}
                />
            </NumberFlowGroup>
        </div>
    )
}

export const Header = () => {
    const [clickCount, setClickCount] = React.useState(0)
    const [seconds, setSeconds] = useCountdown(() => { setClickCount(0) })
    const { systemState, systemDispatch } = useStoreContext()


    // seconds window to click 10 times
    const handleSecretClick = () => {
        if (clickCount === 0) setSeconds(5)
        const newCount = clickCount + 1
        setClickCount(newCount)
        if (newCount === 10) {
            setClickCount(0)
            setSeconds(-1)
            const isHandsome = systemState.handsome
            notify.info(`${isHandsome ? 'Goodbye' : 'Hello'} handsome.`)
            systemDispatch({ type: 'set', key: 'handsome', value: !isHandsome })
            systemDispatch({ type: 'set', key: 'currentTab', value: undefined })
        }
    }

    return (
        <div className={`
            h-10 w-full border-b-1 border-border grid grid-cols-[10%_auto_10%] items-stretch relative
            ${systemState.emergency||systemState.running?'text-primary-foreground':''}
        `}>
            {systemState.emergency && <div className="absolute inset-0 bg-destructive/90 pointer-events-none z-0 animate-[pulse_0.5s_ease-in-out_infinite]" />}
            {!systemState.emergency && systemState.running && <div className="absolute inset-0 bg-primary/90 pointer-events-none z-0 animate-[pulse_0.5s_ease-in-out_infinite]" />}

            <div className="border border-border flex items-center justify-center z-1" onClick={handleSecretClick}></div>
            <div className="border border-border flex items-center justify-center z-1">
                {systemState.emergency?'EMERGENCY':(systemState.running?'RUNNING':systemState.currentTab)}
            </div>
            <div className="border border-border flex flex-col items-center justify-center text-xs font-mono z-1">
                <Clock />
            </div>
        </div>
    )
}