import { ChevronDownIcon } from "lucide-react"
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
export const SECTION_ORDER = ["passive", "physical"]
export const TABLE_COLUMNS = "grid grid-cols-[1fr_2fr_1fr_2fr] gap-4"
export const TABLE_ROW = `${TABLE_COLUMNS} items-start border-t border-border px-4 py-3`
export const TABLE_HEADER = `${TABLE_COLUMNS} border-b border-border bg-muted/40 px-4 py-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground`
export const TABLE_TRIGGER_ROW = `${TABLE_COLUMNS} w-full items-start px-4 py-3 text-left`
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
