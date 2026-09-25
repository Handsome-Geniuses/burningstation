import * as React from "react"
import { RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { MeterState } from "../../store/system"
import type { SchemaNode, SettingsObject } from "../settings/_components/types"
import {
    evaluateVersionChecks,
    MeterVersionCheckRow,
    Operator,
    VersionCheckStatus,
} from "./version-checks"


const STATUS_DETAILS: Record<VersionCheckStatus, { label: string, className: string }> = {
    good: {
        label: "Good",
        className: "border-emerald-400 bg-emerald-100 text-emerald-950 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-100",
    },
    bad: {
        label: "Bad",
        className: "border-red-400 bg-red-100 text-red-950 dark:border-red-700 dark:bg-red-950 dark:text-red-100",
    },
    missing: {
        label: "Missing",
        className: "border-amber-400 bg-amber-100 text-amber-950 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100",
    },
    extra: {
        label: "Extra",
        className: "border-blue-400 bg-blue-100 text-blue-950 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-100",
    },
}

const OPERATOR_LABELS: Record<Operator, string> = {
    eq: "=",
    gt: ">",
    gte: ">=",
    lt: "<",
    lte: "<=",
}

const TABLE_COLUMNS = "grid-cols-[minmax(10rem,1fr)_4.5rem_4.5rem_1px_1.75rem_4.5rem_1.75rem_4.5rem]"

function displayNumber(value: number | null) {
    return value?.toString() ?? ""
}

function numberSize(value: string) {
    return value.length > 10 && "text-[9px]"
}

function VersionRow({ row }: { row: MeterVersionCheckRow }) {
    const status = STATUS_DETAILS[row.status]
    const version = displayNumber(row.version)
    const mod = displayNumber(row.mod)
    const settingVersion = displayNumber(row.settingVersion)
    const settingMod = displayNumber(row.settingMod)
    const versionOperator = row.versionOperator ? OPERATOR_LABELS[row.versionOperator] : ""
    const modOperator = row.modOperator ? OPERATOR_LABELS[row.modOperator] : ""

    return (
        <div
            className={cn(
                "grid min-h-11 items-stretch border-b px-3 text-sm last:border-b-0",
                TABLE_COLUMNS,
                status.className,
            )}
            aria-label={`${row.name}: ${status.label}`}
        >
            <div className="flex min-w-0 items-center break-words py-2 pr-3 font-medium leading-tight">
                {row.name}
                <span className="sr-only">, {status.label}</span>
            </div>
            <div className={cn(
                "flex min-w-0 items-center justify-center font-mono tabular-nums",
                numberSize(version),
            )}>
                {version}
            </div>
            <div className={cn(
                "flex min-w-0 items-center justify-center font-mono tabular-nums",
                numberSize(mod),
            )}>
                {mod}
            </div>
            <div className="my-2 bg-current opacity-20" aria-hidden="true" />
            <div
                className="flex min-w-0 items-center justify-end font-mono font-semibold tabular-nums"
                title="Version operation"
            >
                {versionOperator}
            </div>
            <div className={cn(
                "flex min-w-0 items-center justify-center font-mono tabular-nums",
                numberSize(settingVersion),
            )}>
                {settingVersion}
            </div>
            <div
                className="flex min-w-0 items-center justify-end font-mono font-semibold tabular-nums"
                title="MOD operation"
            >
                {modOperator}
            </div>
            <div className={cn(
                "flex min-w-0 items-center justify-center font-mono tabular-nums",
                numberSize(settingMod),
            )}>
                {settingMod}
            </div>
        </div>
    )
}

type VersionChecksPanelProps = {
    meter: MeterState
    settings: SettingsObject | null
    schema: SchemaNode | null
    settingsLoaded: boolean
    settingsError: string | null
    onReloadSettings: () => Promise<SettingsObject>
}

export function VersionChecksPanel({
    meter,
    settings,
    schema,
    settingsLoaded,
    settingsError,
    onReloadSettings,
}: VersionChecksPanelProps) {
    const rows = React.useMemo(
        () => settings && schema ? evaluateVersionChecks(meter, settings, schema) : [],
        [meter, schema, settings],
    )
    const loading = !settingsLoaded
    const error = settingsError ?? (settingsLoaded && (!settings || !schema)
        ? "Version check settings are unavailable"
        : null)

    return (
        <div className="p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="Version check status legend">
                {(Object.keys(STATUS_DETAILS) as VersionCheckStatus[]).map((key) => (
                    <span
                        key={key}
                        className={cn(
                            "inline-flex h-7 items-center rounded-full border px-3 text-xs font-semibold",
                            STATUS_DETAILS[key].className,
                        )}
                    >
                        {STATUS_DETAILS[key].label}
                    </span>
                ))}
            </div>

            <div className="overflow-x-auto rounded-md border border-border">
                <div className="min-w-[44rem]">
                    <div className={cn(
                        "grid items-stretch border-b border-border bg-muted/60 px-3 text-xs font-semibold uppercase text-muted-foreground",
                        TABLE_COLUMNS,
                    )}>
                        <div className="py-2">Module</div>
                        <div className="py-2 text-center normal-case">mVER</div>
                        <div className="py-2 text-center normal-case">mMOD</div>
                        <div className="bg-border" aria-hidden="true" />
                        <div aria-label="Version operation" />
                        <div className="py-2 text-center normal-case">sVER</div>
                        <div aria-label="MOD operation" />
                        <div className="py-2 text-center normal-case">sMOD</div>
                    </div>

                    {loading && (
                        <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
                            <RefreshCw className="size-4 animate-spin" />
                            Loading version checks
                        </div>
                    )}

                    {!loading && error && (
                        <div className="flex min-h-32 flex-col items-center justify-center gap-3 p-4 text-center">
                            <p className="text-sm text-destructive">{error}</p>
                            <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => void onReloadSettings().catch(() => undefined)}
                            >
                                <RefreshCw />
                                Retry
                            </Button>
                        </div>
                    )}

                    {!loading && !error && rows.length === 0 && (
                        <div className="flex min-h-32 items-center justify-center p-4 text-sm text-muted-foreground">
                            No version information is available.
                        </div>
                    )}

                    {!loading && !error && rows.map((row) => (
                        <VersionRow key={`${row.status}:${row.key}`} row={row} />
                    ))}
                </div>
            </div>
        </div>
    )
}
