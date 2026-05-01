"use client"

import React from "react"
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"
import { ChevronDownIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { LoadingGif } from "@/components/ui/loading-gif"
import { Slider } from "@/components/ui/slider"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"

type SettingsValue = string | number | boolean | null | SettingsObject | SettingsValue[]
type SettingsObject = { [key: string]: SettingsValue }

type SchemaNode = {
    $ref?: string
    $defs?: Record<string, SchemaNode>
    type?: string
    title?: string
    description?: string
    minimum?: number
    maximum?: number
    default?: unknown
    properties?: Record<string, SchemaNode>
    items?: SchemaNode
}

type SettingsPayload = {
    values: SettingsObject
    schema: SchemaNode
}

type SettingsTableProps = {
    entries: Array<[string, SchemaNode]>
    currentValue: SettingsObject | null
    path: string[]
    rootSchema: SchemaNode
    disabled?: boolean
    nested?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}

const HIDDEN_SECTIONS = new Set(["handsome"])
const SECTION_ORDER = ["passive", "physical"]
const TABLE_COLUMNS = "grid grid-cols-[1fr_2fr_1fr_2fr] gap-4"
const TABLE_ROW = `${TABLE_COLUMNS} items-start border-t border-border px-4 py-3`
const TABLE_HEADER = `${TABLE_COLUMNS} border-b border-border bg-muted/40 px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground`
const TABLE_TRIGGER_ROW = `${TABLE_COLUMNS} w-full items-start px-4 py-3 text-left`
const TABLE_CELL = "min-w-0"
const TABLE_TEXT_CELL = "min-w-0 space-y-0.5 text-sm text-foreground"
const TABLE_CONTROL_CELL = "min-w-0"

const formatLabel = (value: string) =>
    value
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase())

const resolveSchemaNode = (node: SchemaNode, rootSchema: SchemaNode): SchemaNode => {
    if (!node.$ref) return node

    const match = node.$ref.match(/^#\/\$defs\/(.+)$/)
    if (!match) return node

    return rootSchema.$defs?.[match[1]] ?? node
}

const setValueAtPath = (
    obj: SettingsObject,
    path: string[],
    nextValue: SettingsValue | ""
): SettingsObject => {
    if (path.length === 0) return obj

    const [head, ...tail] = path
    if (tail.length === 0) {
        return { ...obj, [head]: nextValue as SettingsValue }
    }

    const currentChild = obj[head]
    const childObject =
        currentChild && typeof currentChild === "object" && !Array.isArray(currentChild)
            ? (currentChild as SettingsObject)
            : {}

    return {
        ...obj,
        [head]: setValueAtPath(childObject, tail, nextValue),
    }
}

const getDefaultText = (node: SchemaNode) => {
    if (node.default === undefined) return "—"
    if (typeof node.default === "string") return `'${node.default}'`
    return String(node.default)
}

const renderBadge = (value: string) => (
    <span className="inline-flex w-fit rounded-md border border-border bg-muted py-1 px-2 font-mono text-xs text-muted-foreground">
        {value}
    </span>
)

const BooleanRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: {
    fieldKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    path: string[]
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}) => {
    const boolValue = typeof value === "boolean" ? value : Boolean(node.default)

    return (
        <div className={TABLE_ROW}>
            <div className={TABLE_CELL}>
                <div className="font-medium">{fieldKey}</div>
            </div>

            <div className={TABLE_TEXT_CELL}>
                <div>{node.description ?? "No description provided."}</div>
                <div className="flex flex-wrap gap-2">
                    {renderBadge("bool")}
                </div>
            </div>

            <div className={TABLE_CELL}>
                {renderBadge(getDefaultText(node))}
            </div>

            <div className={TABLE_CONTROL_CELL}>
                <div className="inline-flex rounded-full bg-muted p-1">
                    <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onChange(path, false)}
                        className={`
                            rounded-full px-4 py-1.5 text-sm font-medium transition-colors
                            ${!boolValue ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"}
                        `}
                    >
                        False
                    </button>
                    <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onChange(path, true)}
                        className={`
                            rounded-full px-4 py-1.5 text-sm font-medium transition-colors
                            ${boolValue ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"}
                        `}
                    >
                        True
                    </button>
                </div>
            </div>
        </div>
    )
}

const IntegerRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: {
    fieldKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    path: string[]
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}) => {
    const min = node.minimum ?? 0
    const max = node.maximum ?? 100
    const currentValue = typeof value === "number" ? value : Number(node.default ?? min)
    const clampedValue = Math.min(max, Math.max(min, currentValue))

    const setNumberValue = (next: number) => {
        const rounded = Math.round(next)
        onChange(path, Math.min(max, Math.max(min, rounded)))
    }

    return (
        <div className={TABLE_ROW}>
            <div className={TABLE_CELL}>
                <div className="font-medium">{fieldKey}</div>
            </div>

            <div className={TABLE_TEXT_CELL}>
                <div>{node.description ?? "No description provided."}</div>
                <div className="flex flex-wrap gap-2">
                    {renderBadge("integer")}
                    {node.minimum !== undefined && renderBadge(`min ${node.minimum}`)}
                    {node.maximum !== undefined && renderBadge(`max ${node.maximum}`)}
                </div>
            </div>

            <div className={TABLE_CELL}>
                {renderBadge(getDefaultText(node))}
            </div>

            <div className={`${TABLE_CONTROL_CELL} flex items-center gap-3`}>
                <Button
                    type="button"
                    variant="outline"
                    disabled={disabled || clampedValue <= min}
                    className="h-10 w-10 rounded-2xl text-xl shrink-0"
                    onClick={() => setNumberValue(clampedValue - 1)}
                >
                    -
                </Button>

                <div className="relative flex-1 min-w-0">
                    <Slider
                        value={clampedValue}
                        min={min}
                        max={max}
                        onValueChange={setNumberValue}
                        thumb="bar"
                        rounded
                        className={`
                h-10 w-full overflow-hidden rounded-2xl border-2 border-foreground bg-background
                ${disabled ? "pointer-events-none opacity-60" : ""}
            `}
                        fg="bg-foreground/35"
                        thumbClass="bg-foreground"
                    />
                    <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xl font-light text-foreground">
                        {clampedValue}
                    </div>
                </div>

                <Button
                    type="button"
                    variant="outline"
                    disabled={disabled || clampedValue >= max}
                    className="h-10 w-10 rounded-2xl text-xl shrink-0"
                    onClick={() => setNumberValue(clampedValue + 1)}
                >
                    +
                </Button>
            </div>
        </div>
    )
}

const UnsupportedRow = ({
    fieldKey,
    node,
}: {
    fieldKey: string
    node: SchemaNode
}) => (
    <div className={TABLE_ROW}>
        <div className="font-medium">{fieldKey}</div>
        <div className={`${TABLE_CELL} text-sm text-muted-foreground`}>
            {node.description ?? "Unsupported schema node."}
        </div>
        <div className={TABLE_CELL}>{renderBadge("—")}</div>
        <div className={`${TABLE_CONTROL_CELL} text-sm text-muted-foreground`}>
            Unsupported field type: {node.type ?? "unknown"}
        </div>
    </div>
)

const ObjectRow = ({
    fieldKey,
    node,
    value,
    path,
    rootSchema,
    disabled,
    onChange,
}: {
    fieldKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    path: string[]
    rootSchema: SchemaNode
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}) => {
    const childValue =
        value && typeof value === "object" && !Array.isArray(value)
            ? (value as SettingsObject)
            : null

    return (
        <div className="border-t border-border">
            <Accordion type="single" collapsible>
                <AccordionItem value={path.join(".")} className="border-b-0">
                    <AccordionTrigger className="group px-0 py-0 hover:no-underline [&>svg]:hidden">
                        <div className={TABLE_TRIGGER_ROW}>
                            <div className={TABLE_CELL}>
                                <div className="font-medium">{fieldKey}</div>
                            </div>
                            <div className={TABLE_TEXT_CELL}>
                                <div>{node.description ?? "Nested settings section."}</div>
                                <div className="flex flex-wrap gap-2">
                                    {renderBadge("object")}
                                </div>
                            </div>
                            <div className={TABLE_CELL}>{renderBadge("—")}</div>
                            <div className={`${TABLE_CONTROL_CELL} flex items-center justify-between gap-3 text-sm text-muted-foreground`}>
                                <span>Expand controls</span>
                                <ChevronDownIcon className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
                            </div>
                        </div>
                    </AccordionTrigger>
                    <AccordionContent className="pb-0">
                        <SettingsTable
                            entries={Object.entries(node.properties ?? {})}
                            currentValue={childValue}
                            path={path}
                            rootSchema={rootSchema}
                            disabled={disabled}
                            nested
                            onChange={onChange}
                        />
                    </AccordionContent>
                </AccordionItem>
            </Accordion>
        </div>
    )
}

const SettingsTable = ({
    entries,
    currentValue,
    path,
    rootSchema,
    disabled,
    nested = false,
    onChange,
}: SettingsTableProps) => {
    return (
        <div className={`overflow-hidden border border-border ${nested ? "bg-background/70" : "rounded-lg bg-card"}`}>
            {!nested && (
                <div className={TABLE_HEADER}>
                    <div>Name</div>
                    <div>Description</div>
                    <div>Default</div>
                    <div>Control</div>
                </div>
            )}

            <div>
                {entries.map(([fieldKey, rawNode]) => {
                    const node = resolveSchemaNode(rawNode, rootSchema)
                    const value = currentValue?.[fieldKey]
                    const nextPath = [...path, fieldKey]

                    if (node.type === "object" || node.properties) {
                        return (
                            <ObjectRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                rootSchema={rootSchema}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    if (node.type === "integer") {
                        return (
                            <IntegerRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    if (node.type === "boolean") {
                        return (
                            <BooleanRow
                                key={nextPath.join(".")}
                                fieldKey={fieldKey}
                                node={node}
                                value={value}
                                path={nextPath}
                                disabled={disabled}
                                onChange={onChange}
                            />
                        )
                    }

                    return <UnsupportedRow key={nextPath.join(".")} fieldKey={fieldKey} node={node} />
                })}
            </div>
        </div>
    )
}

const SectionCard = ({
    sectionKey,
    node,
    value,
    rootSchema,
    disabled,
    onChange,
}: {
    sectionKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    rootSchema: SchemaNode
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}) => {
    const resolved = resolveSchemaNode(node, rootSchema)
    const sectionValue =
        value && typeof value === "object" && !Array.isArray(value)
            ? (value as SettingsObject)
            : null

    return (
        <AccordionItem
            value={sectionKey}
            className="overflow-hidden rounded-xl border border-border bg-card shadow-md"
        >
            <AccordionTrigger className="px-4 py-4 hover:no-underline">
                <div className="text-left">
                    <div className="text-lg font-semibold">{resolved.title ?? formatLabel(sectionKey)}</div>
                    <div className="pt-1 text-sm text-muted-foreground">
                        {resolved.description ?? `Configure ${formatLabel(sectionKey).toLowerCase()} settings.`}
                    </div>
                </div>
            </AccordionTrigger>
            <AccordionContent className="p-0">
                <div className="p-1 pt-0">
                    <SettingsTable
                        entries={Object.entries(resolved.properties ?? {})}
                        currentValue={sectionValue}
                        path={[sectionKey]}
                        rootSchema={rootSchema}
                        disabled={disabled}
                        onChange={onChange}
                    />
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}

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
        <form onSubmit={onSave} ref={formRef} className="select-none flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-4 bg-background">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                    <div className="text-lg font-semibold">Settings</div>
                    <div className="pt-1 text-sm text-muted-foreground">
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

            <Accordion type="multiple" className="flex flex-col gap-4">
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
