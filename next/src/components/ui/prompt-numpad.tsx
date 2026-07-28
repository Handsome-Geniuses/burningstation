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

type PromptNumpadProps = React.ComponentProps<typeof Dialog> & {
    title?: string
    description?: string
    value?: number
    onChange?: (value: number | undefined) => void
    onSubmit?: (value: number | undefined) => void
    onCancel?: () => void
}

const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "c", "0", "b"]

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

    const handleKey = (key: string) => {
        if (key === "c") {
            updateDraft("")
            return
        }

        if (key === "b") {
            updateDraft(draft.slice(0, -1))
            return
        }

        updateDraft(`${draft}${key}`)
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
                            key={key}
                            type="button"
                            variant="outline"
                            className={cn(
                                "h-12 text-lg font-semibold uppercase",
                                key === "c" && "text-destructive hover:text-destructive",
                            )}
                            aria-label={key === "c" ? "Clear" : key === "b" ? "Back" : key}
                            onClick={() => handleKey(key)}
                        >
                            {key}
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
