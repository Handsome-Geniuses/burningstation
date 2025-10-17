'use client'
import React from "react"
import { Action, initialSystemState, reducer, SystemState } from "./system"
import { notify } from "@/lib/notify"
import { defaultQuestionProps, Question, QuestionProps } from "./question/question"
import { LoadingGif } from "@/components/ui/loading-gif"

export interface StoreContextProps {
    systemState: SystemState
    systemDispatch: React.Dispatch<Action>
    connected: boolean
    handsome: boolean
}
export const StoreContext = React.createContext<StoreContextProps | null>(null)
export interface StoreProviderProps {
    children: React.ReactNode
}

export const StoreProvider = ({ children }: StoreProviderProps) => {
    const [handsome, setIsHandsome] = React.useState(false)
    const [connected, setConnected] = React.useState(false)
    const [systemState, systemDispatch] = React.useReducer(reducer, initialSystemState)

    // const [question, setQuestion] = React.useState({ open: false, title: undefined, msg: undefined })
    const [question, setQuestion] = React.useState<QuestionProps | undefined>(undefined)
    React.useEffect(()=>{
        if (systemState.emergency) notify.error("EMERGENCY TRIGGERED!")
    },[systemState.emergency])

    const onState = (payload: any) => {
        const { key, value } = payload
        if (typeof key !== 'string' || !(key in initialSystemState)) return
        const typedKey = key as (keyof typeof initialSystemState)

        // runtime type check
        if (typeof value !== typeof initialSystemState[typedKey]) {
            notify.warn(`>[bad state] ${key} : ${value} `)
            return
        }

        systemDispatch({ type: 'set', key: typedKey, value: value })
    }

    const onQuestion = (payload: any) => {
        const { title, msg, qtype, id, src, response, confirm, cancel } = payload

        if (response == undefined) setQuestion({ title, msg, qtype, src, id, confirm, cancel })
        else setQuestion(undefined)
    }

    let flasksse: EventSource | null = null
    React.useEffect(() => {
        setIsHandsome(new URLSearchParams(window.location.search).has('handsome'))

        const flaskconnect = () => {
            flasksse = new EventSource('http://localhost:8011/api/system/sse')
            flasksse.onopen = (e) => {
                console.log("connection established")
                setConnected(true)
            }
            flasksse.onmessage = (e) => {
                const data = JSON.parse(e.data)
                const event = data.event
                const payload = data.payload
                console.log(data)
                if (event == 'keep-alive') return
                else if (event == 'state') onState(payload)
                else if (event == 'question') onQuestion(payload)
            }

            flasksse.onerror = () => {
                console.log('Connection lost. Reconnecting...')
                // notify.error("server connection issue")
                setConnected(false)
                flasksse?.close()

                setTimeout(() => {
                    flaskconnect()
                }, 5000)
            }
        }
        if (flasksse == null) flaskconnect()
        return () => {
            flasksse?.close()
        }
    }, [])

    return (
        <StoreContext.Provider value={{ systemState, systemDispatch, handsome, connected }}>
            {!connected && <LoadingGif variant={"fill"} msg="System Offline..." blur/>}
            {children}
            <Question open={question != undefined} {...question} />
        </StoreContext.Provider >
    )
}


export const useStoreContext = (): StoreContextProps => {
    const context = React.useContext(StoreContext)
    if (!context) throw new Error('useMenuContext must be used with DataStreamerProvider')
    return context
}
