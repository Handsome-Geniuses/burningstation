"use client"

import React from "react"

import { flask } from "@/lib/flask"

import type { SchemaNode, SettingsObject, SettingsPayload } from "./_components/types"

const SERVER_SETTINGS_CHANGE_EVENT = "bs-server-settings-change"

export function broadcastServerSettingsChange(values: SettingsObject) {
    if (typeof window === "undefined") return
    window.dispatchEvent(new CustomEvent(SERVER_SETTINGS_CHANGE_EVENT, { detail: values }))
}

async function readServerSettings(): Promise<SettingsPayload> {
    const res = await flask.get("/settings")
    if (!res.ok) throw new Error(`Failed to load server settings (${res.status})`)
    return await res.json() as SettingsPayload
}

export function useServerSettings() {
    const [values, setValues] = React.useState<SettingsObject | null>(null)
    const [schema, setSchema] = React.useState<SchemaNode | null>(null)
    const [loaded, setLoaded] = React.useState(false)
    const [error, setError] = React.useState<string | null>(null)

    const reload = React.useCallback(async () => {
        setError(null)
        try {
            const next = await readServerSettings()
            setValues(next.values)
            setSchema(next.schema)
            return next.values
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : "Failed to load server settings")
            throw reason
        } finally {
            setLoaded(true)
        }
    }, [])

    React.useEffect(() => {
        void reload().catch(() => undefined)
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
        error,
        schema,
        values,
        reload,
    }
}
