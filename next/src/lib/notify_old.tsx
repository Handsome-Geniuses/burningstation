import { InfoIcon, CircleXIcon, CircleAlertIcon, CircleCheckIcon } from "lucide-react"
import { toast } from "sonner"

// const Msg = (msg:string)=> <p className="text-xl">{msg}</p>
const msgStyle = "ml-2.5 text-lg w-full "
const iconStyle = "text-[1.8em] rounded-full border-0"
const wrapStyle = "!min-w-100"

const message = (msg: string) => {
    toast.message(() => (
        <p className={msgStyle} > {msg} </p>
    ))
}
const warn = (msg: string) => {
    toast.message(() => (
        <p className={`${msgStyle} text-[#f3c562]`}> {msg} </p>
    ), { className: wrapStyle, icon: <CircleAlertIcon className={`${iconStyle} bg-[#f3c562] text-background`} /> })
}
const error = (msg: string) => {
    toast.message(() => (
        <p className={`${msgStyle} text-destructive`}> {msg} </p>
    ), { className: wrapStyle, icon: <CircleXIcon className={`${iconStyle} bg-destructive text-background`} /> })
}
const info = (msg: string) => {
    toast.message(() => (
        <p className={`${msgStyle} text-foreground`}> {msg} </p>
    ), { className: wrapStyle, icon: <InfoIcon className={`${iconStyle} bg-foreground text-background`} /> })
}
const success = (msg: string) => {
    toast.message(() => (
        <p className={`${msgStyle} text-primary`}> {msg} </p>
    ), { className: wrapStyle, icon: <CircleCheckIcon className={`${iconStyle} bg-primary text-background`} /> })
}
export type NotifyType = 'info' | 'warn' | 'error' | 'success'
const NTMap: { [K in NotifyType]: typeof info } = {
    'info': info,
    'success': success,
    'error': error,
    'warn': warn
}
const notice = (nt: NotifyType, msg: string) => (NTMap[nt] ?? NTMap.info)(msg)

export const notify = {
    message, warn, error, info, success, notice
}
