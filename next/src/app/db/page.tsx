"use client"

import { useState } from "react"
import { flask } from "@/lib/flask"

type MeterJob = {
    id: number
    meter_id: number
    name: string
    status: "missing" | "n/a" | "pass" | "fail"
    data: Record<string, unknown>
    jctl: string
    created_at: string
    hostname?: string
}

const retrieveJobHistory = async ({
    limit,
    dateStart,
    dateEnd,
    meterId,
    status,
}: {
    limit: number
    dateStart: string
    dateEnd: string
    meterId: string
    status: string
}) => {
    const params = new URLSearchParams()

    params.set("limit", String(limit))

    if (dateStart) params.set("date_start", dateStart)
    if (dateEnd) params.set("date_end", dateEnd)
    if (meterId) params.set("meter_id", meterId)
    if (status) params.set("status", status)

    const response = await flask.get(`/database/meter_job?${params.toString()}`)
    const data = await response.json()
    return data as MeterJob[]
}

function downloadFile(content: string, filename: string, mimeType: string) {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)

    const a = document.createElement("a")
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()

    URL.revokeObjectURL(url)
}

function flattenObject(
    obj: Record<string, unknown>,
    prefix = ""
): Record<string, unknown> {
    const result: Record<string, unknown> = {}

    for (const [key, value] of Object.entries(obj)) {
        const newKey = prefix ? `${prefix}.${key}` : key

        if (
            value !== null &&
            typeof value === "object" &&
            !Array.isArray(value)
        ) {
            Object.assign(
                result,
                flattenObject(value as Record<string, unknown>, newKey)
            )
        } else {
            result[newKey] = value
        }
    }

    return result
}

function escapeCsvValue(value: unknown) {
    if (value === null || value === undefined) return ""

    let str: string

    if (Array.isArray(value)) {
        str = value.join("; ")
    } else if (typeof value === "object") {
        str = JSON.stringify(value)
    } else {
        str = String(value)
    }

    if (/[",\n]/.test(str)) {
        return `"${str.replace(/"/g, '""')}"`
    }

    return str
}

function convertToCsv(rows: MeterJob[]) {
    if (!rows.length) return ""

    type CsvRow = Record<string, unknown>

    const normalizedRows: CsvRow[] = rows.map((row) => {
        const flatData = flattenObject(row.data ?? {}, "data")

        return {
            id: row.id,
            meter_id: row.meter_id,
            hostname: row.hostname ?? "",
            name: row.name,
            status: row.status,
            created_at: row.created_at,
            ...flatData,
            jctl: row.jctl,
        }
    })

    const allHeaders = Array.from(
        new Set(normalizedRows.flatMap((row) => Object.keys(row)))
    )

    const preferredOrder = [
        "id",
        "meter_id",
        "hostname",
        "name",
        "status",
        "created_at",
    ]

    const headers = [
        ...preferredOrder.filter((h) => allHeaders.includes(h)),
        ...allHeaders
            .filter((h) => !preferredOrder.includes(h) && h !== "jctl")
            .sort(),
        "jctl",
    ].filter((h) => allHeaders.includes(h))

    const csvRows = normalizedRows.map((row) =>
        headers.map((header) => escapeCsvValue(row[header])).join(",")
    )

    return [headers.join(","), ...csvRows].join("\n")
}

function buildFilename({
    limit,
    dateStart,
    dateEnd,
    meterId,
    status,
    ext,
}: {
    limit: number
    dateStart: string
    dateEnd: string
    meterId: string
    status: string
    ext: "json" | "csv"
}) {
    const parts = [`limit-${limit}`]

    if (dateStart) parts.push(`start-${dateStart}`)
    if (dateEnd) parts.push(`end-${dateEnd}`)
    if (meterId) parts.push(`meter-${meterId}`)
    if (status) parts.push(`status-${status}`)

    return `meter_job_${parts.join("_")}.${ext}`
}

export default function Page() {
    const [limit, setLimit] = useState(100)
    const [dateStart, setDateStart] = useState("")
    const [dateEnd, setDateEnd] = useState("")
    const [meterId, setMeterId] = useState("")
    const [status, setStatus] = useState("")
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState("")

    const handleDownloadJson = async () => {
        try {
            setLoading(true)
            setError("")

            const data = await retrieveJobHistory({
                limit,
                dateStart,
                dateEnd,
                meterId,
                status,
            })

            downloadFile(
                JSON.stringify(data, null, 2),
                buildFilename({
                    limit,
                    dateStart,
                    dateEnd,
                    meterId,
                    status,
                    ext: "json",
                }),
                "application/json"
            )
        } catch (err) {
            console.error(err)
            setError("Failed to download JSON.")
        } finally {
            setLoading(false)
        }
    }

    const handleDownloadCsv = async () => {
        try {
            setLoading(true)
            setError("")

            const data = await retrieveJobHistory({
                limit,
                dateStart,
                dateEnd,
                meterId,
                status,
            })

            const csv = convertToCsv(data)

            downloadFile(
                csv,
                buildFilename({
                    limit,
                    dateStart,
                    dateEnd,
                    meterId,
                    status,
                    ext: "csv",
                }),
                "text/csv;charset=utf-8;"
            )
        } catch (err) {
            console.error(err)
            setError("Failed to download CSV.")
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="max-w-md space-y-4 p-6">
            <h1 className="text-xl font-semibold">Download DB Logs</h1>

            <div className="space-y-3">
                <label className="block">
                    <div className="mb-1 text-sm">Limit</div>
                    <input
                        type="number"
                        min={1}
                        value={limit}
                        onChange={(e) => setLimit(Number(e.target.value))}
                        className="w-full rounded border px-3 py-2"
                    />
                </label>

                <label className="block">
                    <div className="mb-1 text-sm">Date Start</div>
                    <input
                        type="date"
                        value={dateStart}
                        onChange={(e) => setDateStart(e.target.value)}
                        className="w-full rounded border px-3 py-2"
                    />
                </label>

                <label className="block">
                    <div className="mb-1 text-sm">Date End</div>
                    <input
                        type="date"
                        value={dateEnd}
                        onChange={(e) => setDateEnd(e.target.value)}
                        className="w-full rounded border px-3 py-2"
                    />
                </label>

                <label className="block">
                    <div className="mb-1 text-sm">Meter ID</div>
                    <input
                        type="number"
                        min={1}
                        value={meterId}
                        onChange={(e) => setMeterId(e.target.value)}
                        className="w-full rounded border px-3 py-2"
                        placeholder="optional"
                    />
                </label>

                <label className="block">
                    <div className="mb-1 text-sm">Status</div>
                    <select
                        value={status}
                        onChange={(e) => setStatus(e.target.value)}
                        className="w-full rounded border px-3 py-2"
                    >
                        <option value="">All</option>
                        <option value="missing">missing</option>
                        <option value="n/a">n/a</option>
                        <option value="pass">pass</option>
                        <option value="fail">fail</option>
                    </select>
                </label>
            </div>

            <div className="flex gap-2">
                <button
                    onClick={handleDownloadJson}
                    disabled={loading}
                    className="rounded bg-black px-4 py-2 text-white disabled:opacity-50"
                >
                    Download as JSON
                </button>

                <button
                    onClick={handleDownloadCsv}
                    disabled={loading}
                    className="rounded bg-gray-700 px-4 py-2 text-white disabled:opacity-50"
                >
                    Download as CSV
                </button>
            </div>

            {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
    )
}