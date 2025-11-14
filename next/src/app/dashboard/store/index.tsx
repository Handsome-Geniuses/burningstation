'use client'
import React, { useRef, useEffect, useState, useReducer } from "react"
import { Action, initialSystemState, reducer, SystemState } from "./system"
import { notify } from "@/lib/notify"
import { Question, QuestionProps } from "./question"
import { LoadingGif } from "@/components/ui/loading-gif"
import { useCountdown } from "@/hooks/useCountdown"

export interface StoreContextProps {
    systemState: SystemState
    systemDispatch: React.Dispatch<Action>
}
export const StoreContext = React.createContext<StoreContextProps | null>(null)

export interface StoreProviderProps {
    children: React.ReactNode
}

export const StoreProvider = ({ children }: StoreProviderProps) => {
    const [systemState, systemDispatch] = useReducer(reducer, initialSystemState)
    const [question, setQuestion] = useState<QuestionProps | undefined>(undefined)

    // Countdown to reconnect
    const [countdown, setCountdown] = useCountdown(flaskconnect) // flaskconnect defined later

    // Ref to hold EventSource
    const flasksse = useRef<EventSource | null>(null)

    // Notify on emergency
    useEffect(() => {
        if (systemState.emergency) notify.error("EMERGENCY TRIGGERED!")
    }, [systemState.emergency])

    // trigger event for state changes from the server
    const onState = (payload: any) => {
        const { key, value } = payload
        if (typeof key !== 'string' || !(key in initialSystemState)) return
        const typedKey = key as keyof typeof initialSystemState

        if (typeof value !== typeof initialSystemState[typedKey]) {
            notify.warn(`>[bad state] ${key} : ${value} `)
            return
        }

        systemDispatch({ type: 'set', key: typedKey, value })
    }

    // trigger event for question!
    const onQuestion = (payload: any) => {
        const { title, msg, qtype, id, src, response, confirm, cancel } = payload
        if (response == undefined) setQuestion({ title, msg, qtype, src, id, confirm, cancel })
        else setQuestion(undefined)
    }
    const onNotify = (payload: any) => {
        const {msg, ntype} = payload
        notify.notice(ntype,msg)
    }

    function flaskconnect() {
        if (flasksse.current) flasksse.current.close()
        setCountdown(-1)
        flasksse.current = new EventSource(`http://${window.location.hostname}:8011/api/system/sse`)
        flasksse.current.onopen = () => {
            console.log("connection established")
            systemDispatch({ type: 'set', key: 'connected', value: true })
        }
        flasksse.current.onmessage = (e) => {
            const data = JSON.parse(e.data)
            const { event, payload } = data
            console.log(data)
            if (event === 'keep-alive') return
            else if (event === 'state') onState(payload)
            else if (event === 'question') onQuestion(payload)
            else if (event === 'notify') onNotify(payload)
        }
        flasksse.current.onerror = () => {
            console.log('Connection lost. Reconnecting...')
            systemDispatch({ type: 'set', key: 'connected', value: false })
            flasksse.current?.close()
            flasksse.current = null
            setCountdown(9)
        }
    }

    // Initial setup
    useEffect(() => {
        systemDispatch({ type: 'set', key: 'handsome', value: new URLSearchParams(window.location.search).has('handsome') })
        flaskconnect()
        return () => { flasksse.current?.close() }
    }, [])

    return (
        <StoreContext.Provider value={{ systemState, systemDispatch }}>
            {!systemState.connected &&
                <LoadingGif
                    variant="fill"
                    msg={countdown > 0 ? `Reconnecting in ${countdown}` : 'Reconnecting ...'}
                    blur
                    onClick={() => (countdown > 0) && flaskconnect()}
                />
            }
            {children}
            {question != undefined && <Question open={question != undefined} {...question} />}
        </StoreContext.Provider>
    )
}

export const useStoreContext = (): StoreContextProps => {
    const context = React.useContext(StoreContext)
    if (!context) throw new Error('useStoreContext must be used with StoreProvider')
    return context
}
