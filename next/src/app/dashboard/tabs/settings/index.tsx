"use client"

import React from "react"
import { Accordion } from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { LoadingGif } from "@/components/ui/loading-gif"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"
import { SectionCard } from "./_components/SectionCard"
import {
    HIDDEN_SECTIONS,
    SECTION_ORDER,
    setValueAtPath,
} from "./_components/shared"
import type { SchemaNode, SettingsObject, SettingsPayload, SettingsValue } from "./_components/types"

export const SettingsTab = () => {
    const formRef = React.useRef<HTMLFormElement | null>(null)
    const [schema, setSchema] = React.useState<SchemaNode | null>(null)
    const [values, setValues] = React.useState<SettingsObject | null>(null)
    const [draft, setDraft] = React.useState<SettingsObject | null>(null)
    const [loading, setLoading] = React.useState(true)
    const [reloading, setReloading] = React.useState(false)
    const [saving, setSaving] = React.useState(false)
    const [error, setError] = React.useState<string | null>(null)

    const fetchSettings = React.useCallback(async (showLoadingState = true) => {
        if (showLoadingState) setLoading(true)
        setReloading(!showLoadingState)
        setError(null)

        try {
            const res = await flask.get("/settings")
            if (!res.ok) throw new Error(`Failed to load settings (${res.status})`)

            const payload = (await res.json()) as SettingsPayload
            setSchema(payload.schema)
            setValues(payload.values)
            setDraft(payload.values)
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to load settings"
            setError(msg)
            notify.error(msg)
        } finally {
            setLoading(false)
            setReloading(false)
        }
    }, [])

    React.useEffect(() => {
        fetchSettings()
    }, [fetchSettings])

    const topLevelEntries = React.useMemo(() => {
        if (!schema?.properties) return []

        return Object.entries(schema.properties)
            .filter(([key]) => !HIDDEN_SECTIONS.has(key))
            .sort(([a], [b]) => {
                const ia = SECTION_ORDER.indexOf(a)
                const ib = SECTION_ORDER.indexOf(b)
                if (ia === -1 && ib === -1) return a.localeCompare(b)
                if (ia === -1) return 1
                if (ib === -1) return -1
                return ia - ib
            })
    }, [schema])

    const isDirty = React.useMemo(() => {
        if (!values || !draft) return false
        return JSON.stringify(values) !== JSON.stringify(draft)
    }, [draft, values])

    const onFieldChange = React.useCallback((path: string[], value: SettingsValue | "") => {
        setDraft((current) => (current ? setValueAtPath(current, path, value) : current))
    }, [])

    const onReset = () => {
        if (!values) return
        setDraft(values)
        setError(null)
    }

    const onReload = async () => {
        await fetchSettings(false)
    }

    const onSave = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (!draft || !formRef.current) return

        if (!formRef.current.reportValidity()) {
            notify.warn("Please fix invalid settings values before saving.")
            return
        }

        setSaving(true)
        setError(null)

        try {
            const saveRes = await flask.post("/settings", { body: JSON.stringify(draft) })
            if (!saveRes.ok) {
                let message = `Failed to save settings (${saveRes.status})`
                try {
                    const payload = await saveRes.json()
                    if (typeof payload?.error === "string") message = payload.error
                } catch { }
                throw new Error(message)
            }

            await fetchSettings(false)
            notify.success("Settings saved.")
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to save settings"
            setError(msg)
            notify.error(msg)
        } finally {
            setSaving(false)
        }
    }

    if (loading) {
        return (
            <div className="relative h-full min-h-80">
                <LoadingGif variant="fit" size="sm" msg="Loading settings..." />
            </div>
        )
    }

    if (!schema || !draft) {
        return (
            <div className="flex h-full items-center justify-center p-6">
                <div className="rounded-lg border border-border bg-card p-6 text-center shadow-md">
                    <div className="text-lg font-semibold">Settings unavailable</div>
                    <div className="pt-2 text-sm text-muted-foreground">
                        {error ?? "Could not load settings payload from the backend."}
                    </div>
                    <Button className="mt-4" onClick={() => fetchSettings()}>
                        Retry
                    </Button>
                </div>
            </div>
        )
    }

    return (
        <form onSubmit={onSave} ref={formRef} className="select-none flex h-full min-h-0 flex-col gap-4 overflow-y-auto bg-background pb-4">
            <div className="px-4 py-2 sticky top-0 inset-0 z-10 bg-background flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between shadow">
                <div className="flex flex-col gap-0 space-y-0">
                    <div className="text-lg font-semibold leading-6 z-20">Settings</div>
                    <div className="pt-0 text-sm text-muted-foreground leading-4">
                        {saving ? "Saving..." : reloading ? "Reloading..." : isDirty ? "Unsaved changes" : "Up to date"}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <Button type="button" variant="outline" onClick={onReset} disabled={!isDirty || saving || reloading}>
                        Reset
                    </Button>
                    <Button type="button" variant="outline" onClick={onReload} disabled={saving || reloading}>
                        Reload
                    </Button>
                    <Button type="submit" disabled={!isDirty || saving || reloading}>
                        Save
                    </Button>
                </div>
            </div>
            {error && (
                <div className="bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                </div>
            )}

            <Accordion type="multiple" className="flex flex-col gap-4 px-4">
                {topLevelEntries.map(([sectionKey, sectionNode]) => (
                    <SectionCard
                        key={sectionKey}
                        sectionKey={sectionKey}
                        node={sectionNode}
                        value={draft[sectionKey]}
                        rootSchema={schema}
                        disabled={saving || reloading}
                        onChange={onFieldChange}
                    />
                ))}
            </Accordion>

            {topLevelEntries.length === 0 && (
                <div className="pt-2 text-sm text-muted-foreground">
                    No supported settings sections were returned by the backend schema.
                </div>
            )}
        </form>
    )
}
