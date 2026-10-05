export interface ActivityEntry {
    id: string
    kind: string
    created_at: string
    hostname: string
    name: string
    status: string
    data?: {
        duration_s?: number | null
        failure_reason?: string
        last_error?: string
        results?: Record<string, { status?: string; error?: string }>
        device_meta?: Record<string, { error?: string }>
    }
    receivedAt?: number
}

export function failureDetails(entry: ActivityEntry): string[] {
    const data = entry.data
    const reasons = new Set<string>()
    for (const reason of [data?.failure_reason, data?.last_error]) {
        if (reason && reason !== "failed") reasons.add(reason)
    }
    for (const [name, result] of Object.entries(data?.results ?? {})) {
        if (result.status !== "fail") continue
        const error = result.error || data?.device_meta?.[name]?.error
        reasons.add(`${name.replaceAll("_", " ")}: ${error || "check failed"}`)
    }
    for (const [name, meta] of Object.entries(data?.device_meta ?? {})) {
        if (meta.error && data?.results?.[name]?.status !== "fail") {
            reasons.add(`${name.replaceAll("_", " ")}: ${meta.error}`)
        }
    }
    return reasons.size ? [...reasons] : ["The job failed without a recorded explanation."]
}

export function formatDuration(seconds?: number | null): string | null {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return null
    if (seconds < 60) return `${Math.round(seconds * 10) / 10}s`
    const rounded = Math.round(seconds)
    return `${Math.floor(rounded / 60)}m ${rounded % 60}s`
}
