import { Button } from "@/components/ui/button"
import { useAsyncAction } from "@/hooks/useAsyncAction"
import { meterMockOperatorKeypadPress } from "@/lib/ep"
import { cn } from "@/lib/utils"
import { Check, ChevronDown, ChevronLeft, ChevronUp, CircleHelp, Globe2, Minus, Plus, Undo2, X } from "lucide-react"

import { OperatorKeypadState } from "../../store/system"
import {
    FUNCTION_KEYPAD_KEYS,
    MAIN_KEYPAD_ROWS,
    OPERATOR_KEYPAD_LAYOUT_BUTTONS,
    OperatorKeypadIcon,
    OperatorKeypadKey,
} from "./operator-keypad-layout"

type OperatorKeypadPanelProps = {
    meterIp: string
    keypadState?: OperatorKeypadState
    mock: boolean
    running: boolean
}

const iconClassName = "size-4"

function KeyIcon({ icon }: { icon?: OperatorKeypadIcon }) {
    if (icon === "accept") return <Check className={iconClassName} />
    if (icon === "back") return <ChevronLeft className={iconClassName} />
    if (icon === "cancel") return <X className={iconClassName} />
    if (icon === "down") return <Minus className={iconClassName} />
    if (icon === "globe") return <Globe2 className={iconClassName} />
    if (icon === "help") return <CircleHelp className={iconClassName} />
    if (icon === "up") return <Plus className={iconClassName} />
    return null
}

function formatCount(count: number, required: number) {
    return required > 0 ? `${count} / ${required}` : `${count}`
}

function KeypadCell({
    keySpec,
    keypadState,
    expected,
    mock,
    running,
    onPress,
}: {
    keySpec: OperatorKeypadKey
    keypadState?: OperatorKeypadState
    expected: Set<string>
    mock: boolean
    running: boolean
    onPress: (button: string) => void
}) {
    const required = keypadState?.required_per_button ?? 0
    const count = keypadState?.counts[keySpec.button] ?? 0
    const isExpected = expected.has(keySpec.button)
    const isComplete = isExpected && required > 0 && count >= required
    const isLatest = keypadState?.latest_button === keySpec.button
    const canPress = mock && running && isExpected

    return (
        <Button
            type="button"
            variant="outline"
            title={keySpec.title ?? keySpec.button}
            className={cn(
                "relative min-w-0 flex-col gap-0 px-0 pb-0 text-center leading-none transition-colors",
                "border-border bg-background text-foreground shadow-none h-8",
                keySpec.colSpan === 2 && "col-span-2",
                keySpec.tone === "utility" && "border-blue-300 bg-blue-50 text-blue-950 hover:bg-blue-100",
                keySpec.tone === "danger" && "border-red-300 bg-red-50 text-red-950 hover:bg-red-100",
                keySpec.tone === "confirm" && "border-emerald-300 bg-emerald-50 text-emerald-950 hover:bg-emerald-100",
                !isExpected && "opacity-35",
                isComplete && "border-emerald-500 bg-emerald-100 text-emerald-950",
                isLatest && "ring-2 ring-amber-400 ring-offset-2 ring-offset-background",
                !canPress && "cursor-default"
            )}
            aria-disabled={!canPress}
            onClick={() => {
                if (canPress) onPress(keySpec.button)
            }}
        >
            <span className="flex min-h-0 items-center justify-center gap-0 text-xs font-semibold uppercase leading-none">
                <KeyIcon icon={keySpec.icon} />
                <span className="truncate">{keySpec.label}</span>
            </span>
            <span className="text-[11px] font-medium leading-none text-muted-foreground">
                {formatCount(count, required)}
            </span>
        </Button>
    )
}

export function OperatorKeypadPanel({
    meterIp,
    keypadState,
    mock,
    running,
}: OperatorKeypadPanelProps) {
    const { run, running: pressing } = useAsyncAction()
    const expected = new Set(keypadState?.expected_buttons ?? [])
    const current = keypadState?.current ?? 0
    const total = keypadState?.total ?? 0
    const counts = keypadState?.counts ?? {}
    const fallbackButtons = [
        ...new Set([
            ...Object.keys(counts),
            ...(keypadState?.expected_buttons ?? []),
        ]),
    ].filter((button) => !OPERATOR_KEYPAD_LAYOUT_BUTTONS.has(button))

    const handlePress = (button: string) => {
        if (pressing) return
        void run(() => meterMockOperatorKeypadPress(meterIp, button))()
    }

    return (
        <div className="bg-muted/20 px-[15%] my-2">
            <div className="mb-3 flex items-center justify-between gap-4 hidden">
                <div>
                    <div className="text-sm font-semibold leading-tight">operator keypad</div>
                    <div className="text-xs text-muted-foreground">{current} / {total}</div>
                </div>
                <div className={cn(
                    "rounded-md border px-2 py-1 text-xs font-medium",
                    total > 0 && current >= total
                        ? "border-emerald-500 bg-emerald-50 text-emerald-900"
                        : "border-border bg-background text-muted-foreground"
                )}>
                    {total > 0 && current >= total ? "complete" : running ? "running" : "idle"}
                </div>
            </div>

            <div className="grid gap-1">
                <div className="grid grid-cols-6 gap-1">
                    {FUNCTION_KEYPAD_KEYS.map((keySpec) => (
                        <KeypadCell
                            key={keySpec.button}
                            keySpec={keySpec}
                            keypadState={keypadState}
                            expected={expected}
                            mock={mock}
                            running={running}
                            onPress={handlePress}
                        />
                    ))}
                </div>

                <div className="grid grid-cols-6 gap-1">
                    {MAIN_KEYPAD_ROWS.flat().map((keySpec) => (
                        <KeypadCell
                            key={keySpec.button}
                            keySpec={keySpec}
                            keypadState={keypadState}
                            expected={expected}
                            mock={mock}
                            running={running}
                            onPress={handlePress}
                        />
                    ))}
                </div>
            </div>

            {fallbackButtons.length > 0 &&
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {fallbackButtons.map((button) => {
                        const count = counts[button] ?? 0
                        const required = keypadState?.required_per_button ?? 0
                        const isLatest = keypadState?.latest_button === button
                        return (
                            <button
                                key={button}
                                type="button"
                                className={cn(
                                    "rounded-md border border-border bg-background px-2 py-1 font-medium",
                                    isLatest && "ring-2 ring-amber-400 ring-offset-2 ring-offset-background",
                                    (!mock || !running) && "cursor-default"
                                )}
                                aria-disabled={!mock || !running}
                                onClick={() => {
                                    if (mock && running) handlePress(button)
                                }}
                            >
                                {button}: {formatCount(count, required)}
                            </button>
                        )
                    })}
                </div>
            }
        </div>
    )
}
