import { ChevronDownIcon } from "lucide-react"
import { useEffect, useState } from "react"
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import type {
    ObjectRowProps,
    RowRendererProps,
    SchemaNode,
    SettingsObject,
    SettingsTableProps,
    SettingsValue,
} from "./types"
import { cn } from "@/lib/utils"

export const HIDDEN_SECTIONS = new Set(["handsome"])
export const SECTION_ORDER = ["flow", "passive", "physical", "operator", "version_checks", "other"]
export const TABLE_COLUMNS = "grid grid-cols-[1fr_2fr_1fr_2fr] gap-4"
export const TABLE_ROW = `${TABLE_COLUMNS} items-start border-t border-border px-4 py-3`
export const TABLE_HEADER = `${TABLE_COLUMNS} border-b border-border bg-muted/40 px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground`
export const TABLE_TRIGGER_ROW = `${TABLE_COLUMNS} w-full items-start px-4 py-3 text-left bg-muted/40`
export const TABLE_CELL = "min-w-0"
export const TABLE_TEXT_CELL = "min-w-0 space-y-0.5 text-sm text-foreground"
export const TABLE_CONTROL_CELL = "min-w-0"

export const formatLabel = (value: string) =>
    value
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase())

export const resolveSchemaNode = (node: SchemaNode, rootSchema: SchemaNode): SchemaNode => {
    if (!node.$ref) return node

    const match = node.$ref.match(/^#\/\$defs\/(.+)$/)
    if (!match) return node

    return rootSchema.$defs?.[match[1]] ?? node
}

export const setValueAtPath = (
    obj: SettingsObject,
    path: string[],
    nextValue: SettingsValue | ""
): SettingsObject => {
    const update = (current: SettingsValue, remainingPath: string[]): SettingsValue => {
        if (remainingPath.length === 0) return nextValue as SettingsValue

        const [head, ...tail] = remainingPath
        if (Array.isArray(current)) {
            const index = Number(head)
            if (!Number.isInteger(index) || index < 0) return current

            const next = [...current]
            next[index] = update(next[index] ?? null, tail)
            return next
        }

        const currentObject =
            current && typeof current === "object"
                ? current as SettingsObject
                : {}

        return {
            ...currentObject,
            [head]: update(currentObject[head] ?? null, tail),
        }
    }

    return update(obj, path) as SettingsObject
}

export const getDefaultText = (node: SchemaNode) => {
    if (node.default === undefined) return "—"
    if (typeof node.default === "string") return `'${node.default}'`
    return String(node.default)
}

export const renderBadge = (value: string) => (
    <span className="inline-flex w-fit rounded-md border border-border bg-muted py-1 px-2 font-mono text-xs text-muted-foreground">
        {value}
    </span>
)

export const BooleanRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: RowRendererProps) => {
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

            <div className={TABLE_CONTROL_CELL} hidden>
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
            <div className={TABLE_CONTROL_CELL}>
                <button
                    type="button"
                    disabled={disabled}
                    className="inline-flex rounded-full bg-muted p-1"
                    onClick={() => onChange(path, !boolValue)}
                >
                    <p className={cn(
                        "rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
                        !boolValue ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
                    )}>
                        False
                    </p>
                    <p className={cn(
                        "rounded-full px-4 py-1.5 text-sm font-medium transition-colors",
                        boolValue ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
                    )}>
                        True
                    </p>
                </button>
            </div>
        </div>
    )
}

export const IntegerRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: RowRendererProps) => {
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

const validateSettingsArray = (fieldKey: string, parsed: unknown): string | null => {
    if (!Array.isArray(parsed)) return "Value must be a JSON array."
    if (fieldKey !== "back_enter_offsets_mm") return null
    if (parsed.length === 0) return "Provide at least one [x, y] pair."
    for (let index = 0; index < parsed.length; index += 1) {
        const pair = parsed[index]
        if (!Array.isArray(pair) || pair.length !== 2) {
            return `Item ${index + 1} must contain exactly [x, y].`
        }
        const [x, y] = pair
        if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
            return `Item ${index + 1} must contain finite numbers.`
        }
        if (Math.abs(x) >= 12.75) return `Item ${index + 1}: abs(x) must be less than 12.75 mm.`
        if (Math.abs(y) >= 5) return `Item ${index + 1}: abs(y) must be less than 5 mm.`
    }
    return null
}

const BACK_ENTER_OFFSET_PRESETS = [
    { label: "Left", offset: [-10, 0] },
    { label: "Centered", offset: [0, 0] },
    { label: "Right", offset: [10, 0] },
] as const

type BackEnterOffsetPresetLabel = (typeof BACK_ENTER_OFFSET_PRESETS)[number]["label"]

const isBackEnterOffset = (value: unknown, [expectedX, expectedY]: readonly [number, number]) =>
    Array.isArray(value)
    && value.length === 2
    && value[0] === expectedX
    && value[1] === expectedY

export const BackEnterOffsetsRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: RowRendererProps) => {
    const currentOffsets = Array.isArray(value) ? value : []
    const selectedPresets = BACK_ENTER_OFFSET_PRESETS.filter(({ offset }) =>
        currentOffsets.some((currentOffset) => isBackEnterOffset(currentOffset, offset)),
    )
    const selectedLabels = new Set(selectedPresets.map(({ label }) => label))
    const hasUnsupportedOffsets = currentOffsets.some(
        (currentOffset) => !BACK_ENTER_OFFSET_PRESETS.some(({ offset }) => isBackEnterOffset(currentOffset, offset)),
    )

    const togglePreset = (label: BackEnterOffsetPresetLabel) => {
        const isSelected = selectedLabels.has(label)
        if (isSelected && selectedPresets.length <= 1) return

        const nextSelectedLabels = new Set(selectedLabels)
        if (isSelected) {
            nextSelectedLabels.delete(label)
        } else {
            nextSelectedLabels.add(label)
        }

        // Build from the canonical preset order so the physical test always
        // receives a predictable list, regardless of toggle order.
        const nextOffsets = BACK_ENTER_OFFSET_PRESETS
            .filter(({ label: presetLabel }) => nextSelectedLabels.has(presetLabel))
            .map(({ offset }) => [...offset])
        onChange(path, nextOffsets)
    }

    return (
        <div className={TABLE_ROW}>
            <div className={TABLE_CELL}>
                <div className="font-medium">{fieldKey}</div>
            </div>
            <div className={TABLE_TEXT_CELL}>
                <div>{node.description ?? "Choose the robot BACK/ENTER press positions."}</div>
                <div className="flex flex-wrap gap-2">
                    {renderBadge("preset offsets")}
                    {renderBadge("choose at least one")}
                </div>
            </div>
            <div className={TABLE_CELL}>{renderBadge(JSON.stringify(node.default ?? [[0, 0]]))}</div>
            <div className={TABLE_CONTROL_CELL}>
                <div className="grid grid-cols-3 gap-2">
                    {BACK_ENTER_OFFSET_PRESETS.map(({ label, offset }) => {
                        const isSelected = selectedLabels.has(label)
                        const isLastSelected = isSelected && selectedPresets.length <= 1
                        return (
                            <Button
                                key={label}
                                type="button"
                                variant={isSelected ? "default" : "outline"}
                                disabled={disabled || isLastSelected}
                                aria-pressed={isSelected}
                                onClick={() => togglePreset(label)}
                                className="h-auto min-h-14 flex-col gap-0.5 rounded-xl px-2 py-2 text-sm"
                            >
                                <span>{label}</span>
                                <span className="font-mono text-xs opacity-80">[{offset[0]}, {offset[1]}]</span>
                            </Button>
                        )
                    })}
                </div>
                {hasUnsupportedOffsets && (
                    <div className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                        Select a preset to replace the unsupported saved offset values.
                    </div>
                )}
            </div>
        </div>
    )
}

const OPERATOR_COIN_PRESETS = [
    { key: "us_penny", group: "US coins", label: "Penny", currency: "USD", value: "1¢", defaultQuantity: 5 },
    { key: "us_nickel", group: "US coins", label: "Nickel", currency: "USD", value: "5¢", defaultQuantity: 5 },
    { key: "us_dime", group: "US coins", label: "Dime", currency: "USD", value: "10¢", defaultQuantity: 5 },
    { key: "us_quarter", group: "US coins", label: "Quarter", currency: "USD", value: "25¢", defaultQuantity: 5 },
    { key: "us_dollar_coin", group: "US coins", label: "Dollar coin", currency: "USD", value: "$1", defaultQuantity: 5 },
    { key: "uk_1p", group: "UK coins", label: "1p", currency: "GBP", value: "1p", defaultQuantity: 0 },
    { key: "uk_2p", group: "UK coins", label: "2p", currency: "GBP", value: "2p", defaultQuantity: 0 },
    { key: "uk_5p", group: "UK coins", label: "5p", currency: "GBP", value: "5p", defaultQuantity: 0 },
    { key: "uk_10p", group: "UK coins", label: "10p", currency: "GBP", value: "10p", defaultQuantity: 0 },
    { key: "uk_20p", group: "UK coins", label: "20p", currency: "GBP", value: "20p", defaultQuantity: 0 },
    { key: "uk_50p", group: "UK coins", label: "50p", currency: "GBP", value: "50p", defaultQuantity: 0 },
    { key: "uk_1_pound", group: "UK coins", label: "£1", currency: "GBP", value: "£1", defaultQuantity: 0 },
    { key: "uk_2_pounds", group: "UK coins", label: "£2", currency: "GBP", value: "£2", defaultQuantity: 0 },
] as const

type OperatorCoinKey = (typeof OPERATOR_COIN_PRESETS)[number]["key"]

const OPERATOR_COIN_GROUPS = ["US coins", "UK coins"] as const

const asSettingsObject = (value: SettingsValue | undefined): SettingsObject => (
    value && typeof value === "object" && !Array.isArray(value)
        ? value as SettingsObject
        : {}
)

export const CoinRequirementsRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: RowRendererProps) => {
    const quantities = asSettingsObject(value)
    const quantityFor = (key: OperatorCoinKey, fallback: number) => {
        const quantity = quantities[key]
        return typeof quantity === "number" ? Math.min(10, Math.max(0, quantity)) : fallback
    }
    const selectedQuantity = OPERATOR_COIN_PRESETS.reduce(
        (total, { key, defaultQuantity }) => total + quantityFor(key, defaultQuantity),
        0,
    )

    const setQuantity = (key: OperatorCoinKey, nextQuantity: number) => {
        onChange(path, {
            ...quantities,
            [key]: Math.min(10, Math.max(0, nextQuantity)),
        })
    }

    return (
        <div className={TABLE_ROW}>
            <div className={TABLE_CELL}>
                <div className="font-medium">{fieldKey}</div>
            </div>
            <div className={TABLE_TEXT_CELL}>
                <div>{node.description ?? "Choose the quantity required for each coin denomination."}</div>
                <div className="flex flex-wrap gap-2">
                    {renderBadge("quantity 0–10")}
                    {renderBadge("region-aware")}
                </div>
            </div>
            <div className={TABLE_CELL}>{renderBadge("US: 5 each · UK: 0")}</div>
            <div className={TABLE_CONTROL_CELL}>
                <Accordion type="single" collapsible>
                    <AccordionItem value={path.join(".")} className="rounded-lg border border-border px-3">
                        <AccordionTrigger className="py-3 text-sm hover:no-underline">
                            Configure quantities ({selectedQuantity} coin{selectedQuantity === 1 ? "" : "s"})
                        </AccordionTrigger>
                        <AccordionContent className="space-y-4 pb-3">
                            {OPERATOR_COIN_GROUPS.map((group) => (
                                <div key={group} className="space-y-2">
                                    <div className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                                        {group}
                                    </div>
                                    {OPERATOR_COIN_PRESETS.filter((coin) => coin.group === group).map((coin) => {
                                        const quantity = quantityFor(coin.key, coin.defaultQuantity)
                                        return (
                                            <div key={coin.key} className="flex items-center gap-2 rounded-md bg-muted/50 px-2 py-1.5">
                                                <div className="min-w-0 flex-1 text-sm">
                                                    <div className="font-medium">{coin.label}</div>
                                                    <div className="text-xs text-muted-foreground">{coin.currency} · {coin.value}</div>
                                                </div>
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    disabled={disabled || quantity === 0}
                                                    className="h-9 w-9 shrink-0 rounded-lg text-lg"
                                                    onClick={() => setQuantity(coin.key, quantity - 1)}
                                                >
                                                    -
                                                </Button>
                                                <span className="w-7 text-center font-mono text-base" aria-label={`${coin.label} quantity`}>
                                                    {quantity}
                                                </span>
                                                <Button
                                                    type="button"
                                                    variant="outline"
                                                    disabled={disabled || quantity === 10}
                                                    className="h-9 w-9 shrink-0 rounded-lg text-lg"
                                                    onClick={() => setQuantity(coin.key, quantity + 1)}
                                                >
                                                    +
                                                </Button>
                                            </div>
                                        )
                                    })}
                                </div>
                            ))}
                        </AccordionContent>
                    </AccordionItem>
                </Accordion>
            </div>
        </div>
    )
}

export const ArrayRow = ({
    fieldKey,
    node,
    value,
    path,
    disabled,
    onChange,
}: RowRendererProps) => {
    const arrayValue = Array.isArray(value) ? value : (Array.isArray(node.default) ? node.default : [])
    const serialized = JSON.stringify(arrayValue)
    const [text, setText] = useState(serialized)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        setText(serialized)
        setError(null)
    }, [serialized])

    const update = (nextText: string) => {
        setText(nextText)
        try {
            const parsed: unknown = JSON.parse(nextText)
            const validationError = validateSettingsArray(fieldKey, parsed)
            setError(validationError)
            if (!validationError) onChange(path, parsed as SettingsValue[])
        } catch {
            setError("Enter valid JSON, for example [[-5,0],[0,0],[5,0]].")
        }
    }

    return (
        <div className={TABLE_ROW}>
            <div className={TABLE_CELL}>
                <div className="font-medium">{fieldKey}</div>
            </div>
            <div className={TABLE_TEXT_CELL}>
                <div>{node.description ?? "Ordered JSON array setting."}</div>
                <div className="flex flex-wrap gap-2">{renderBadge("array")}</div>
            </div>
            <div className={TABLE_CELL}>{renderBadge(JSON.stringify(node.default ?? []))}</div>
            <div className={TABLE_CONTROL_CELL}>
                <textarea
                    disabled={disabled}
                    value={text}
                    rows={3}
                    spellCheck={false}
                    onChange={(event) => update(event.target.value)}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
                    aria-invalid={Boolean(error)}
                />
                {error && <div className="mt-1 text-xs text-destructive">{error}</div>}
            </div>
        </div>
    )
}

export const UnsupportedRow = ({
    fieldKey,
    node,
}: Pick<RowRendererProps, "fieldKey" | "node">) => (
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

type SettingsTableComponent = (props: SettingsTableProps) => React.JSX.Element

let settingsTableImpl: SettingsTableComponent | null = null

export const registerSettingsTable = (component: SettingsTableComponent) => {
    settingsTableImpl = component
}

const RenderSettingsTable = (props: SettingsTableProps) => {
    if (!settingsTableImpl) {
        throw new Error("SettingsTable is not registered")
    }

    return settingsTableImpl(props)
}

export const ObjectRow = ({
    fieldKey,
    node,
    value,
    path,
    rootSchema,
    disabled,
    onChange,
}: ObjectRowProps) => {
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
                        <RenderSettingsTable
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
