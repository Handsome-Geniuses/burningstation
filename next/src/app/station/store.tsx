'use client'
import React from "react"

export interface StoreContextProps {
}
export const StoreContext = React.createContext<StoreContextProps | null>(null)
export interface StoreProviderProps {
    children: React.ReactNode
}

export const StoreProvider = ({ children }: StoreProviderProps) => {
    const [handsome, setIsHandsome] = React.useState(false)



    let flasksse: EventSource | null = null
    React.useEffect(() => {
        setIsHandsome(new URLSearchParams(window.location.search).has('handsome'))

        const flaskconnect = () => {
            if (document.readyState === 'complete') { }
            else window.addEventListener('load', () => { })

            flasksse = new EventSource('http://localhost:8011/api/system/sse')
            flasksse.onmessage = (e) => {
                const data = JSON.parse(e.data)
                const event = data.event
                const payload = data.payload
                if (event == 'keep-alive') return
                console.log(data)
                // if (event=='someevent') 
            }

            flasksse.onerror = () => {
                console.log('Connection lost. Reconnecting...')
                flasksse?.close()

                setTimeout(() => {
                    flaskconnect()
                }, 5000)
            }
        }
        if (flasksse == null) flaskconnect()
        return () => {
            // source?.removeEventListener('meters', sseHandleMeters)
            // source!.onmessage = null
            flasksse?.close()
        }
    }, [])

    return (
        <StoreContext.Provider value={{}}>
            {children}
        </StoreContext.Provider >
    )
}


export const useStoreContext = (): StoreContextProps => {
    const context = React.useContext(StoreContext)
    if (!context) throw new Error('useMenuContext must be used with DataStreamerProvider')
    return context
}
