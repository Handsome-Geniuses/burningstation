import { flask } from "./flask"
import { notify } from "./notify"
// flask.handleAction("override", "motor", { value_list: [0, 0, 0] })

type ProgramKwargs = Record<string, unknown>

export const meterRunProg = async (meterIp?: string, prog?: string, kwargs?: ProgramKwargs) => {
    return meterRunProgramAction("manual", meterIp, prog, kwargs)
}

export const meterRunNeutralProg = async (meterIp?: string, prog?: string, kwargs?: ProgramKwargs) => {
    return meterRunProgramAction("neutral", meterIp, prog, kwargs)
}

const meterRunProgramAction = async (action: "manual" | "neutral", meterIp?: string, prog?: string, kwargs?: ProgramKwargs) => {
    if (!meterIp || !prog) return
    kwargs = { ...kwargs, program: prog, meter_ip: meterIp }
    try {
        const res = await flask.handleAction("program", action, kwargs)
        const payload = await res.json().catch(() => ({}))
        if (!res.ok) {
            throw new Error(payload?.error ?? `Failed to start ${prog} (${res.status})`)
        }
    } catch (err) {
        const msg = err instanceof Error ? err.message : `Failed to start ${prog}`
        notify.error(msg)
    }
}

export const meterRunBlink = async (meterIp?: string) => meterRunNeutralProg(meterIp, "identify")
export const meterRunBlinkUntil = async (meterIp?: string, maxDuration = 3) => meterRunNeutralProg(meterIp, "identify_until", { max_duration: maxDuration })
export const meterStopBlink = async (meterIp?: string) => meterRunNeutralProg(meterIp, "identify_stop")
export const meterRunPassive = async (meterIp?: string) => meterRunProg(meterIp, "start_passive_job")
export const meterStopPassive = async (meterIp?: string) => meterRunProg(meterIp, "stop_passive_job")
export const meterStopPhysical = async (meterIp?: string) => meterRunProg(meterIp, "stop_physical_job")
export const meterRunPrintFw = async (meterIp?: string) => await meterRunNeutralProg(meterIp, "printfw")
export const meterRunDummy = async (meterIp?: string) => meterRunNeutralProg(meterIp, "dummy")
