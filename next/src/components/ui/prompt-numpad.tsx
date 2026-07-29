"use client"

import * as React from "react"

import { Button } from "@/components/ui/button"
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { ChevronLeft, Eraser } from "lucide-react"

type PromptNumpadProps = React.ComponentProps<typeof Dialog> & {
    title?: string
    description?: string
    value?: number
    onChange?: (value: number | undefined) => void
    onSubmit?: (value: number | undefined) => void
    onCancel?: () => void
}

type NumpadKey = {
    id: string
    label: string
    action: "digit" | "clear" | "back"
    value?: string
    content: React.ReactNode
    destructive?: boolean
}

const keys: NumpadKey[] = [
    { id: "1", label: "1", action: "digit", value: "1", content: "1" },
    { id: "2", label: "2", action: "digit", value: "2", content: "2" },
    { id: "3", label: "3", action: "digit", value: "3", content: "3" },
    { id: "4", label: "4", action: "digit", value: "4", content: "4" },
    { id: "5", label: "5", action: "digit", value: "5", content: "5" },
    { id: "6", label: "6", action: "digit", value: "6", content: "6" },
    { id: "7", label: "7", action: "digit", value: "7", content: "7" },
    { id: "8", label: "8", action: "digit", value: "8", content: "8" },
    { id: "9", label: "9", action: "digit", value: "9", content: "9" },
    { id: "clear", label: "Clear", action: "clear", content: <Eraser className="size-5" />, destructive: true },
    { id: "0", label: "0", action: "digit", value: "0", content: "0" },
    { id: "back", label: "Back", action: "back", content: <ChevronLeft className="size-5" /> },
]

const toDraftValue = (value?: number) => value === undefined ? "" : String(value)

export const PromptNumpad = ({
    title = "Enter Number",
    description = "Use the numpad to enter number",
    value = undefined,
    onChange = () => {},
    onSubmit = () => {},
    onCancel = () => {},
    onOpenChange = () => {},
    ...props
}: PromptNumpadProps) => {
    const [draft, setDraft] = React.useState(toDraftValue(value))
    const closeActionRef = React.useRef<"cancel" | "submit" | null>(null)
    const wasOpenRef = React.useRef(false)

    React.useEffect(() => {
        if (props.open && !wasOpenRef.current) {
            setDraft(toDraftValue(value))
        }

        wasOpenRef.current = Boolean(props.open)
    }, [props.open, value])

    const updateDraft = (next: string) => {
        setDraft(next)
        onChange(next ? Number(next) : undefined)
    }

    const handleKey = (key: NumpadKey) => {
        if (key.action === "clear") {
            updateDraft("")
            return
        }

        if (key.action === "back") {
            updateDraft(draft.slice(0, -1))
            return
        }

        updateDraft(`${draft}${key.value}`)
    }

    const handleCancel = () => {
        closeActionRef.current = "cancel"
        setDraft(toDraftValue(value))
        onCancel()
    }

    const handleSubmit = () => {
        closeActionRef.current = "submit"
        onSubmit(draft ? Number(draft) : undefined)
    }

    const handleOpenChange = (open: boolean) => {
        if (!open && !closeActionRef.current) {
            setDraft(toDraftValue(value))
            onCancel()
        }

        closeActionRef.current = null
        onOpenChange(open)
    }

    return (
        <Dialog onOpenChange={handleOpenChange} {...props}>
            <DialogContent showCloseButton={false} className="max-w-xs gap-4">
                <DialogHeader className="items-center text-center">
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>{description}</DialogDescription>
                </DialogHeader>

                <Input
                    value={draft}
                    readOnly
                    tabIndex={-1}
                    inputMode="none"
                    aria-label="Numpad value"
                    className="h-12 cursor-default select-none text-center !text-3xl font-semibold caret-transparent"
                    onMouseDown={(event) => event.preventDefault()}
                    onSelect={(event) => event.currentTarget.setSelectionRange(event.currentTarget.value.length, event.currentTarget.value.length)}
                />

                <div className="grid grid-cols-3 gap-2">
                    {keys.map((key) => (
                        <Button
                            key={key.id}
                            type="button"
                            variant="outline"
                            className={cn(
                                "h-12 text-lg font-semibold uppercase",
                                key.destructive && "text-destructive hover:text-destructive",
                            )}
                            aria-label={key.label}
                            onClick={() => handleKey(key)}
                        >
                            {key.content}
                        </Button>
                    ))}
                </div>

                <DialogFooter className="grid grid-cols-2 gap-2 sm:grid-cols-2 sm:justify-stretch">
                    <DialogClose asChild>
                        <Button type="button" variant="outline" onClick={handleCancel}>
                            Cancel
                        </Button>
                    </DialogClose>
                    <DialogClose asChild>
                        <Button type="button" onClick={handleSubmit}>
                            Submit
                        </Button>
                    </DialogClose>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
