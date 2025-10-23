import { flask } from "@/lib/flask"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog"
import React from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { notify } from "@/lib/notify"



type QuestionTypes = "boolean" | "string" | "number"
export interface QuestionProps {
    title?: string
    msg?: string
    id?: string
    src?: string
    qtype?: QuestionTypes
    confirm?: string
    cancel?: string
}
export const defaultQuestionProps: QuestionProps = {
    title: "Question",
    msg: "Yes or no",
    id: undefined,
    src: undefined,
    qtype: "boolean",
    confirm: "yes",
    cancel: "no"

}

const QSrc = ({ src }: { src: string | undefined }) => {
    return src && (
        <div className="flex items-center justify-center">
            <img src={src} alt="" className="h-32 object-contain" />
        </div>
    )
}

const handleConfirm = async (value: any) => {
    const res = await flask.post('/question/response', { body: JSON.stringify({ value: value }) })
    if (res.ok) {
        notify.info(`responded: ${value}`)
    }
    else {
        notify.info(`bad response: ${value}`)
    }
}
const QBoolean = ({ confirm, cancel }: { confirm: string, cancel: string }) => {
    return (
        <div className="grid grid-cols-[auto_auto] gap-2">
            <Button variant="default" onClick={() => handleConfirm(true)}>{confirm}</Button>
            <Button variant="destructive" onClick={() => handleConfirm(false)}>{cancel}</Button>
        </div>
    )
}
const QNumber = ({ confirm = "confirm" }: { confirm?: string }) => {
    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>)=>{
        e.preventDefault()
        const value = Number((new FormData(e.currentTarget)).get("value"))
        if (!value) notify.warn("not valid input")
        else handleConfirm(value)
    }
    return (
        <form onSubmit={handleSubmit}>
            <div className="w-full">
                <Input type="number" name="value"/>
                <Button>{confirm}</Button>
            </div>
        </form>
    )
}
const QString = ({ confirm = "confirm" }: { confirm?: string }) => {
    const handleSubmit = (e: React.FormEvent<HTMLFormElement>)=>{
        e.preventDefault()
        const value = (new FormData(e.currentTarget)).get("value")
        if (!value) notify.warn("not valid input")
        else handleConfirm(value)
    }
    return (
        <form onSubmit={handleSubmit}>
            <div className="w-full">
                <Input type="text" name="value"/>
                <Button>{confirm}</Button>
            </div>
        </form>
    )
}

// export const Question = ({ title = "Question", msg = "Yes or no", ...props }: { title?: string, msg?: string } & React.ComponentProps<typeof Dialog>) => {
export const Question = ({ ...baseprops }: QuestionProps & React.ComponentProps<typeof Dialog>) => {
    const props = { ...defaultQuestionProps, ...baseprops };
    const { title, msg, id, src, qtype, confirm, cancel, ...diagprops } = props

    return (
        <Dialog {...diagprops}>
            <DialogContent className="[&>button]:hidden">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>{msg}</DialogDescription>
                </DialogHeader>
                {/* {
                    <div className="flex items-center justify-center">
                        <img src="running-cat.gif" alt="" className="h-32 object-contain" />
                    </div>
                } */}
                <QSrc src={src} />
                {qtype == "string" && <QString confirm={confirm} />}
                {qtype == "number" && <QNumber confirm={confirm} />}
                {qtype == "boolean" && <QBoolean confirm={confirm!} cancel={cancel!} />}
            </DialogContent>
        </Dialog>
    )
}