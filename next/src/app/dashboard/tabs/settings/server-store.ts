"use client"

import React from "react"

import { flask } from "@/lib/flask"

import type { SettingsObject } from "./_components/types"

const SERVER_SETTINGS_CHANGE_EVENT = "bs-server-settings-change"

export function broadcastServerSettingsChange(values: SettingsObject) {
    if (typeof window === "undefined") return
    window.dispatchEvent(new CustomEvent(SERVER_SETTINGS_CHANGE_EVENT, { detail: values }))
}

async function readServerSettings(): Promise<SettingsObject> {
    const res = await flask.get("/settings/values")
    if (!res.ok) throw new Error(`Failed to load server settings (${res.status})`)
    return await res.json() as SettingsObject
}

export function useServerSettings() {
    const [values, setValues] = React.useState<SettingsObject | null>(null)
    const [loaded, setLoaded] = React.useState(false)

    const reload = React.useCallback(async () => {
        const next = await readServerSettings()
        setValues(next)
        setLoaded(true)
        return next
    }, [])

    React.useEffect(() => {
        void reload()
    }, [reload])

    React.useEffect(() => {
        const handleServerSettingsChange = (event: Event) => {
            const values = (event as CustomEvent<SettingsObject>).detail
            if (values) {
                setValues(values)
                setLoaded(true)
            }
        }

        window.addEventListener(SERVER_SETTINGS_CHANGE_EVENT, handleServerSettingsChange)
        return () => window.removeEventListener(SERVER_SETTINGS_CHANGE_EVENT, handleServerSettingsChange)
    }, [])

    return {
        loaded,
        values,
        reload,
    }
}
