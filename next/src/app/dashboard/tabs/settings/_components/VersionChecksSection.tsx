"use client"

import React from "react"
import { Delete, Info } from "lucide-react"
import {
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"
import { formatLabel, resolveSchemaNode } from "./shared"
import type { SchemaNode, SettingsObject, SettingsValue } from "./types"

const MAX_SAFE_INTEGER_TEXT = "9007199254740991"
const OPERATORS = [null, "eq", "gt", "gte", "lt", "lte"] as const

type ComparisonOperator = Exclude<(typeof OPERATORS)[number], null>
type ConstraintKind = "version" | "mod"

type ConstraintValue = {
    value: number
    operator: ComparisonOperator | null
}

type VersionChecksSectionProps = {
    sectionKey: string
    node: SchemaNode
    value: SettingsValue | undefined
    rootSchema: SchemaNode
    disabled?: boolean
    onChange: (path: string[], value: SettingsValue | "") => void
}

const OPERATOR_LABELS: Record<ComparisonOperator, string> = {
    eq: "=",
    gt: ">",
    gte: ">=",
    lt: "<",
    lte: "<=",
}

const asSettingsObject = (value: SettingsValue | undefined): SettingsObject | null => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null
    return value as SettingsObject
}

const isComparisonOperator = (value: SettingsValue | undefined): value is ComparisonOperator =>
    value === "eq" || value === "gt" || value === "gte" || value === "lt" || value === "lte"

const readConstraint = (firmwareValue: SettingsObject | null, kind: ConstraintKind): ConstraintValue => {
    const constraint = asSettingsObject(firmwareValue?.[kind])
    const rawValue = constraint?.value
    const rawOperator = constraint?.operator

    return {
        value: typeof rawValue === "number" && Number.isSafeInteger(rawValue) && rawValue >= 0 ? rawValue : 0,
        operator: isComparisonOperator(rawOperator) ? rawOperator : null,
    }
}

const normalizeDigits = (digits: string) => digits.replace(/^0+(?=\d)/, "")

const validateDigits = (digits: string): string | null => {
    if (!digits) return "Enter a value."

    const normalized = normalizeDigits(digits)
    if (
        normalized.length > MAX_SAFE_INTEGER_TEXT.length
        || (normalized.length === MAX_SAFE_INTEGER_TEXT.length && normalized > MAX_SAFE_INTEGER_TEXT)
    ) {
        return `Maximum value is ${Number.MAX_SAFE_INTEGER.toLocaleString()}.`
    }

    return null
}

type NumericKeypadProps = {
    label: string
    value: number
    active: boolean
    disabled?: boolean
    onSave: (value: number) => void
}

const NumericKeypad = ({ label, value, active, disabled, onSave }: NumericKeypadProps) => {
    const [open, setOpen] = React.useState(false)
    const [digits, setDigits] = React.useState(String(value))
    const displayRef = React.useRef<HTMLInputElement | null>(null)
    const error = validateDigits(digits)

    const onOpenChange = (nextOpen: boolean) => {
        if (nextOpen) setDigits(String(value))
        setOpen(nextOpen)
    }

    const appendDigit = React.useCallback((digit: string) => {
        setDigits((current) => {
            const next = current === "0" ? digit : `${current}${digit}`
            return normalizeDigits(next).slice(0, MAX_SAFE_INTEGER_TEXT.length)
        })
    }, [])

    const save = React.useCallback(() => {
        if (validateDigits(digits)) return
        onSave(Number(normalizeDigits(digits)))
        setOpen(false)
    }, [digits, onSave])

    const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return

        if (/^\d$/.test(event.key)) {
            event.preventDefault()
            appendDigit(event.key)
            return
        }

        if (event.key === "Backspace") {
            event.preventDefault()
            setDigits((current) => current.slice(0, -1))
            return
        }

        if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement)) {
            event.preventDefault()
            save()
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogTrigger asChild>
                <Input
                    readOnly
                    disabled={disabled}
                    value={active ? String(value) : "-"}
                    aria-label={`Set ${label}`}
                    aria-haspopup="dialog"
                    className={cn(
                        "h-10 cursor-pointer select-none text-center font-mono tabular-nums",
                        String(value).length > 12 ? "text-xs" : "text-base",
                        !active && "text-muted-foreground"
                    )}
                />
            </DialogTrigger>
            <DialogContent
                className="max-h-[90dvh] overflow-y-auto sm:max-w-sm"
                onKeyDown={onKeyDown}
                onOpenAutoFocus={(event) => {
                    event.preventDefault()
                    window.requestAnimationFrame(() => displayRef.current?.focus())
                }}
            >
                <DialogHeader>
                    <DialogTitle>{label}</DialogTitle>
                    <DialogDescription className="sr-only">
                        Enter a nonnegative whole number.
                    </DialogDescription>
                </DialogHeader>

                <Input
                    ref={displayRef}
                    readOnly
                    value={digits}
                    aria-invalid={Boolean(error)}
                    className="h-14 text-right font-mono text-2xl tabular-nums"
                />

                <div className="grid grid-cols-3 gap-2">
                    {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((digit) => (
                        <Button
                            key={digit}
                            type="button"
                            variant="outline"
                            className="h-14 text-xl"
                            onClick={() => appendDigit(digit)}
                        >
                            {digit}
                        </Button>
                    ))}
                    <Button
                        type="button"
                        variant="outline"
                        className="h-14"
                        onClick={() => setDigits("")}
                    >
                        Clear
                    </Button>
                    <Button
                        type="button"
                        variant="outline"
                        className="h-14 text-xl"
                        onClick={() => appendDigit("0")}
                    >
                        0
                    </Button>
                    <Button
                        type="button"
                        variant="outline"
                        className="h-14"
                        aria-label="Backspace"
                        title="Backspace"
                        onClick={() => setDigits((current) => current.slice(0, -1))}
                    >
                        <Delete />
                    </Button>
                </div>

                <DialogFooter>
                    <DialogClose asChild>
                        <Button type="button" variant="outline">Cancel</Button>
                    </DialogClose>
                    <Button type="button" disabled={Boolean(error)} onClick={save}>Save</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

type ConstraintControlProps = {
    label: string
    constraint: ConstraintValue
    path: string[]
    disabled?: boolean
    onChange: VersionChecksSectionProps["onChange"]
}

const ConstraintControl = ({ label, constraint, path, disabled, onChange }: ConstraintControlProps) => {
    const operatorIndex = OPERATORS.indexOf(constraint.operator)
    const nextOperator = OPERATORS[(operatorIndex + 1) % OPERATORS.length]
    const operatorLabel = constraint.operator ? OPERATOR_LABELS[constraint.operator] : "Off"
    const nextOperatorLabel = nextOperator ? OPERATOR_LABELS[nextOperator] : "Off"

    return (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_3.5rem] gap-2">
            <NumericKeypad
                label={label}
                value={constraint.value}
                active={constraint.operator !== null}
                disabled={disabled}
                onSave={(nextValue) => {
                    onChange([...path, "value"], nextValue)
                    if (constraint.operator === null) {
                        onChange([...path, "operator"], "eq")
                    }
                }}
            />
            <Button
                type="button"
                variant={constraint.operator === null ? "outline" : "secondary"}
                disabled={disabled}
                className="h-10 w-14 px-1 font-mono text-base"
                aria-label={`${label} comparison ${operatorLabel}; next ${nextOperatorLabel}`}
                title={`${label}: ${operatorLabel}`}
                onClick={() => onChange([...path, "operator"], nextOperator)}
            >
                {operatorLabel}
            </Button>
        </div>
    )
}

const VERSION_GRID = "grid grid-cols-1 gap-3 sm:grid-cols-[minmax(9rem,1.2fr)_minmax(10rem,1fr)_minmax(10rem,1fr)] sm:items-center"

export const VersionChecksSection = ({
    sectionKey,
    node,
    value,
    rootSchema,
    disabled,
    onChange,
}: VersionChecksSectionProps) => {
    const resolved = resolveSchemaNode(node, rootSchema)
    const currentValue = asSettingsObject(value)

    return (
        <AccordionItem
            value={sectionKey}
            className="overflow-hidden rounded-xl border border-border bg-card shadow-md"
        >
            <AccordionTrigger className="px-4 py-4 hover:no-underline">
                <div className="text-left">
                    <div className="text-lg font-semibold leading-none tracking-none">
                        Version Checks
                    </div>
                    <div className="pt-1 text-sm leading-none tracking-none text-muted-foreground">
                        {node.description ?? "Configure firmware version and MOD requirements."}
                    </div>
                </div>
            </AccordionTrigger>
            <AccordionContent className="p-0">
                <div className="m-1 overflow-hidden rounded-lg border border-border">
                    <div className={cn(VERSION_GRID, "hidden bg-muted/40 px-4 py-3 text-xs font-semibold uppercase text-muted-foreground sm:grid")}>
                        <div>Firmware</div>
                        <div>Version</div>
                        <div>MOD</div>
                    </div>

                    {Object.entries(resolved.properties ?? {}).map(([firmwareKey, rawNode]) => {
                        const firmwareNode = resolveSchemaNode(rawNode, rootSchema)
                        const firmwareValue = asSettingsObject(currentValue?.[firmwareKey])
                        const version = readConstraint(firmwareValue, "version")
                        const mod = readConstraint(firmwareValue, "mod")
                        const firmwareLabel = rawNode.title ?? formatLabel(firmwareKey)
                        const description = rawNode.description ?? firmwareNode.description ?? firmwareLabel
                        const firmwarePath = [sectionKey, firmwareKey]

                        return (
                            <div key={firmwareKey} className={cn(VERSION_GRID, "border-t border-border px-4 py-3 first:border-t-0 sm:first:border-t")}>
                                <div className="flex min-w-0 items-center gap-2">
                                    <span className="min-w-0 font-medium break-words">{firmwareLabel}</span>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="size-8 shrink-0 text-muted-foreground"
                                        aria-label={`Show description for ${firmwareLabel}`}
                                        title={`About ${firmwareLabel}`}
                                        onClick={() => notify.info(description)}
                                    >
                                        <Info />
                                    </Button>
                                </div>

                                <div className="min-w-0">
                                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground sm:hidden">Version</div>
                                    <ConstraintControl
                                        label={`${description} version`}
                                        constraint={version}
                                        path={[...firmwarePath, "version"]}
                                        disabled={disabled}
                                        onChange={onChange}
                                    />
                                </div>

                                <div className="min-w-0">
                                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground sm:hidden">MOD</div>
                                    <ConstraintControl
                                        label={`${description} MOD`}
                                        constraint={mod}
                                        path={[...firmwarePath, "mod"]}
                                        disabled={disabled}
                                        onChange={onChange}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            </AccordionContent>
        </AccordionItem>
    )
}
