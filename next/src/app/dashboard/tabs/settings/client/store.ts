"use client"

import React from "react"

import type { SchemaNode, SettingsObject, SettingsValue } from "../_components/types"
import {
    CLIENT_SETTINGS_DEFAULTS,
    CLIENT_SETTINGS_SCHEMA,
    clientSettingsDefaultsObject,
    type ClientSettings,
} from "./schema"

const CLIENT_SETTINGS_STORAGE_KEY = "bs-cockpit-settings"
const CLIENT_SETTINGS_CHANGE_EVENT = "bs-cockpit-settings-change"

function isObject(value: unknown): value is SettingsObject {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function cloneDefaults() {
    return structuredClone(CLIENT_SETTINGS_DEFAULTS) as ClientSettings
}

function sanitizeValue(node: SchemaNode | undefined, value: unknown, fallback: SettingsValue): SettingsValue {
    if (!node) return fallback

    if (node.type === "boolean") {
        return typeof value === "boolean" ? value : fallback
    }

    if (node.type === "integer") {
        const min = node.minimum ?? Number.MIN_SAFE_INTEGER
        const max = node.maximum ?? Number.MAX_SAFE_INTEGER
        const fallbackNumber = typeof fallback === "number" ? fallback : Number(node.default ?? min)
        const next = typeof value === "number" && Number.isFinite(value) ? Math.round(value) : fallbackNumber
        return Math.min(max, Math.max(min, next))
    }

    if (node.type === "object" || node.properties) {
        const fallbackObject = isObject(fallback) ? fallback : {}
        const valueObject = isObject(value) ? value : {}

        return Object.fromEntries(
            Object.entries(node.properties ?? {}).map(([key, childNode]) => [
                key,
                sanitizeValue(childNode, valueObject[key], fallbackObject[key]),
            ])
        )
    }

    return fallback
}

function sanitizeClientSettings(value: unknown): ClientSettings {
    return sanitizeValue(
        CLIENT_SETTINGS_SCHEMA,
        value,
        clientSettingsDefaultsObject
    ) as unknown as ClientSettings
}

function readStoredClientSettings(): ClientSettings {
    if (typeof window === "undefined") return cloneDefaults()

    const raw = window.localStorage.getItem(CLIENT_SETTINGS_STORAGE_KEY)
    if (!raw) return cloneDefaults()

    try {
        return sanitizeClientSettings(JSON.parse(raw))
    } catch {
        return cloneDefaults()
    }
}

function writeStoredClientSettings(settings: ClientSettings) {
    window.localStorage.setItem(CLIENT_SETTINGS_STORAGE_KEY, JSON.stringify(settings))
    window.dispatchEvent(new CustomEvent(CLIENT_SETTINGS_CHANGE_EVENT))
}

export function useClientSettings() {
    const [values, setValues] = React.useState<ClientSettings>(() => cloneDefaults())
    const [loaded, setLoaded] = React.useState(false)

    const reload = React.useCallback(() => {
        const next = readStoredClientSettings()
        setValues(next)
        setLoaded(true)
        return next
    }, [])

    React.useEffect(() => {
        reload()
    }, [reload])

    React.useEffect(() => {
        const handleClientSettingsChange = () => {
            reload()
        }

        const handleStorageChange = (event: StorageEvent) => {
            if (event.key === CLIENT_SETTINGS_STORAGE_KEY) reload()
        }

        window.addEventListener(CLIENT_SETTINGS_CHANGE_EVENT, handleClientSettingsChange)
        window.addEventListener("storage", handleStorageChange)

        return () => {
            window.removeEventListener(CLIENT_SETTINGS_CHANGE_EVENT, handleClientSettingsChange)
            window.removeEventListener("storage", handleStorageChange)
        }
    }, [reload])

    const save = React.useCallback((settings: ClientSettings | SettingsObject) => {
        const sanitized = sanitizeClientSettings(settings)
        writeStoredClientSettings(sanitized)
        setValues(sanitized)
        return sanitized
    }, [])

    const reset = React.useCallback(() => {
        return save(cloneDefaults())
    }, [save])

    return {
        loaded,
        schema: CLIENT_SETTINGS_SCHEMA,
        values: values as unknown as SettingsObject,
        save,
        reload,
        reset,
    }
}
