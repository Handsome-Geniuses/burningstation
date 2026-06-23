import { flask } from "./flask"
import { notify } from "./notify"
// flask.handleAction("override", "motor", { value_list: [0, 0, 0] })

export const meterRunProg = async (meterIp?: string, prog?: string, kwargs?: { [key: string]: any }) => {
    if (!meterIp || !prog) return
    const search = new URLSearchParams({ ip: meterIp, prog: prog })
    kwargs = {...kwargs, "program": prog}
    try {
        const res = await flask.handleAction("program", "manual", kwargs)
        const payload = await res.json().catch(() => ({}))
        if (!res.ok) {
            throw new Error(payload?.error ?? `Failed to start ${prog} (${res.status})`)
        }
    } catch (err) {
        const msg = err instanceof Error ? err.message : `Failed to start ${prog}`
        notify.error(msg)
    }
}

export const meterRunBlink = async (meterIp?: string) => meterRunProg(meterIp, "identify")
export const meterRunPrintFw = async (meterIp?: string) => await meterRunProg(meterIp, "printfw")
export const meterRunDummy = async (meterIp?: string) => meterRunProg(meterIp, "dummy")


