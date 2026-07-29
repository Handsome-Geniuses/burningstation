"use client"

import React from "react"
import {
    AlertTriangle,
    ChevronDown,
    ChevronUp,
    Check,
    ClipboardCopy,
    Columns3,
    Download,
    Eye,
    Filter,
    RefreshCw,
    Search,
    ShieldQuestion,
    X,
} from "lucide-react"

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { flask } from "@/lib/flask"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"

type JobStatus = "missing" | "n/a" | "pass" | "fail"

type MeterJob = {
    id: number
    meter_id: number
    name: string
    status: JobStatus
    data: {
        kwargs?: Record<string, unknown>
        results?: Record<string, { status?: string; [key: string]: unknown }>
        [key: string]: unknown
    }
    jctl: string
    created_at: string
    hostname?: string
    work_order?: number | null
}

type QueryFilters = {
    limit: number
    dateStart: string
    dateEnd: string
    statuses: JobStatus[]
}

type CoreColumnKey = "status" | "id" | "hostname" | "meter_id" | "work_order" | "name" | "created_at"
type SortKey = "status" | "id" | "hostname" | "meter_id" | "work_order" | "name" | "created_at" | string
type SortDirection = "asc" | "desc"
type DataSectionKey = "kwargs" | "jctl"
type ExportSectionKey = "results_json"
type DetailTabKey = "results-simple" | "results-json" | "kwargs" | "journalctl"

const coreColumns = [
    { key: "status", label: "Status" },
    { key: "id", label: "Job ID" },
    { key: "hostname", label: "Meter" },
    { key: "meter_id", label: "Meter ID" },
    { key: "work_order", label: "Work Order" },
    { key: "name", label: "Job" },
    { key: "created_at", label: "Finished" },
] as const

const dataSections = [
    { key: "kwargs", label: "kwargs" },
    { key: "jctl", label: "journalctl" },
] as const

const exportSections = [
    { key: "results_json", label: "results json" },
] as const

const jobStatuses: JobStatus[] = ["pass", "fail", "missing", "n/a"]

const defaultCoreColumns = new Set<CoreColumnKey>(["status", "hostname", "work_order", "name", "created_at"])
const defaultDataSections = new Set<DataSectionKey>()
const defaultExportSections = new Set<ExportSectionKey>()

const statusClassName: Record<JobStatus, string> = {
    pass: "bg-green-100 text-green-700 border-green-200",
    fail: "bg-red-100 text-red-700 border-red-200",
    missing: "bg-yellow-100 text-yellow-800 border-yellow-200",
    "n/a": "bg-gray-100 text-gray-700 border-gray-200",
}

const excelStatusStyle: Record<JobStatus, { fill: string; font: string }> = {
    pass: { fill: "FFDCFCE7", font: "FF15803D" },
    fail: { fill: "FFFEE2E2", font: "FFB91C1C" },
    missing: { fill: "FFFEF3C7", font: "FFA16207" },
    "n/a": { fill: "FFF3F4F6", font: "FF374151" },
}

const defaultFilters: QueryFilters = {
    limit: 25,
    dateStart: "",
    dateEnd: "",
    statuses: [...jobStatuses],
}

const todayInputValue = () => new Date().toLocaleDateString("en-CA")

const buildParams = (filters: QueryFilters, offset = 0) => {
    const params = new URLSearchParams()
    params.set("limit", String(filters.limit))
    params.set("offset", String(offset))
    if (filters.dateStart) params.set("date_start", filters.dateStart)
    if (filters.dateEnd) params.set("date_end", filters.dateEnd)
    for (const status of filters.statuses) {
        params.append("status", status)
    }
    return params
}

const retrieveJobHistory = async (filters: QueryFilters, offset = 0) => {
    if (!filters.statuses.length) return []

    const response = await flask.get(`/database/meter_job?${buildParams(filters, offset).toString()}`)

    if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.error ?? `Failed to fetch jobs (${response.status})`)
    }

    return await response.json() as MeterJob[]
}

function downloadBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
}

function downloadFile(content: string, filename: string, mimeType: string) {
    downloadBlob(new Blob([content], { type: mimeType }), filename)
}

function escapeCsvValue(value: unknown) {
    if (value === null || value === undefined) return ""

    const str = Array.isArray(value)
        ? value.join("; ")
        : typeof value === "object"
            ? JSON.stringify(value)
            : String(value)

    if (/[",\n]/.test(str)) return `"${str.replace(/"/g, '""')}"`
    return str
}

function resultsObject(results: MeterJob["data"]["results"] | undefined) {
    return Object.fromEntries(
        Object.entries(results ?? {})
    )
}

function simpleResultsObject(results: MeterJob["data"]["results"] | undefined) {
    return Object.fromEntries(
        Object.entries(results ?? {}).map(([key, result]) => [
            key,
            result?.status ?? "n/a",
        ])
    )
}

function exportColumnKey(key: CoreColumnKey) {
    if (key === "id") return "job_id"
    return key === "created_at" ? "finished" : key
}

function projectRowsForJson(
    rows: MeterJob[],
    visibleCoreColumns: Set<CoreColumnKey>,
    visibleExportSections: Set<ExportSectionKey>,
    visibleDataSections: Set<DataSectionKey>
) {
    return buildExportRows(rows, visibleCoreColumns, visibleExportSections, visibleDataSections)
}

function convertToCsv(
    rows: MeterJob[],
    visibleCoreColumns: Set<CoreColumnKey>,
    visibleExportSections: Set<ExportSectionKey>,
    visibleDataSections: Set<DataSectionKey>
) {
    if (!rows.length) return ""

    const normalizedRows = buildExportRows(rows, visibleCoreColumns, visibleExportSections, visibleDataSections)
    const headers = getExportHeaders(normalizedRows)

    const csvRows = normalizedRows.map((row) =>
        headers.map((header) => escapeCsvValue(row[header as keyof typeof row])).join(",")
    )

    return [headers.join(","), ...csvRows].join("\n")
}

function buildExportRows(
    rows: MeterJob[],
    visibleCoreColumns: Set<CoreColumnKey>,
    visibleExportSections: Set<ExportSectionKey>,
    visibleDataSections: Set<DataSectionKey>
) {
    return rows.map((row) => {
        const normalized: Record<string, unknown> = {}

        for (const column of coreColumns) {
            if (visibleCoreColumns.has(column.key)) {
                normalized[exportColumnKey(column.key)] = column.key === "created_at"
                    ? formatExportDateTime(row.created_at)
                    : row[column.key] ?? ""
            }
        }

        normalized.results_simple = simpleResultsObject(row.data?.results)

        if (visibleExportSections.has("results_json")) {
            normalized.results_json = resultsObject(row.data?.results)
        }

        if (visibleDataSections.has("kwargs")) {
            normalized.kwargs = row.data?.kwargs ?? {}
        }

        if (visibleDataSections.has("jctl")) {
            normalized.journalctl = row.jctl ?? ""
        }

        return normalized
    })
}

function getExportHeaders(rows: Record<string, unknown>[]) {
    const allHeaders = Array.from(new Set(rows.flatMap((row) => Object.keys(row))))
    const preferredOrder: string[] = coreColumns.map((column) => exportColumnKey(column.key))

    return [
        ...preferredOrder.filter((header) => allHeaders.includes(header)),
        "results_simple",
        ...exportSections
            .map((section) => section.key)
            .filter((header) => allHeaders.includes(header)),
        ...dataSections
            .map((section) => section.key === "jctl" ? "journalctl" : section.key)
            .filter((header) => allHeaders.includes(header)),
        ...allHeaders
            .filter((header) => (
                !preferredOrder.includes(header) &&
                header !== "results_simple" &&
                !exportSections.some((section) => section.key === header) &&
                !dataSections.some((section) => (section.key === "jctl" ? "journalctl" : section.key) === header)
            ))
            .sort(),
    ].filter((header) => allHeaders.includes(header))
}

async function exportToExcel(
    rows: MeterJob[],
    visibleCoreColumns: Set<CoreColumnKey>,
    visibleExportSections: Set<ExportSectionKey>,
    visibleDataSections: Set<DataSectionKey>,
    filename: string
) {
    const ExcelJS = await import("exceljs")
    const workbook = new ExcelJS.Workbook()
    const worksheet = workbook.addWorksheet("meter_job", {
        views: [{ state: "frozen", ySplit: 1, showGridLines: false }],
    })
    const exportRows = buildExportRows(rows, visibleCoreColumns, visibleExportSections, visibleDataSections)
    const headers = getExportHeaders(exportRows)

    const wideExportColumns = new Set(["finished", "name", "results_simple", "results_json", "kwargs", "journalctl"])
    const detailExportColumns = new Set(["results_simple", "results_json", "kwargs", "journalctl"])

    worksheet.columns = headers.map((header) => ({
        header,
        key: header,
        width: header === "status" ? 12 : wideExportColumns.has(header) ? 32 : Math.max(12, header.length + 4),
    }))

    worksheet.getRow(1).font = { bold: true, color: { argb: "FFFFFFFF" } }
    worksheet.getRow(1).fill = {
        type: "pattern",
        pattern: "solid",
        fgColor: { argb: "FF1F2937" },
    }
    worksheet.getRow(1).alignment = { vertical: "middle" }
    worksheet.autoFilter = {
        from: { row: 1, column: 1 },
        to: { row: 1, column: Math.max(headers.length, 1) },
    }

    for (const row of exportRows) {
        worksheet.addRow(Object.fromEntries(
            headers.map((header) => {
                const value = row[header]
                return [
                    header,
                    value && typeof value === "object" ? JSON.stringify(value, null, 2) : value,
                ]
            })
        ))
    }

    const lastDataRow = exportRows.length + 1
    const lastDataColumn = headers.length
    const tableBorder = { style: "medium" as const, color: { argb: "FF6B7280" } }
    const detailColumnBorder = { style: "medium" as const, color: { argb: "FF9CA3AF" } }
    const innerBorder = { style: "thin" as const, color: { argb: "FFE5E7EB" } }

    worksheet.eachRow((row, rowNumber) => {
        const rowFill = rowNumber > 1 && rowNumber % 2 === 0 ? "FFF3F4F6" : "FFFFFFFF"

        row.eachCell((cell, columnNumber) => {
            const columnKey = worksheet.getColumn(cell.col).key
            const statusStyle = columnKey === "status"
                ? excelStatusStyle[String(cell.value) as JobStatus]
                : null
            const isObjectColumn = rowNumber > 1 && (
                String(columnKey ?? "").includes("results") ||
                columnKey === "kwargs" ||
                columnKey === "journalctl"
            )
            const isDetailColumn = detailExportColumns.has(String(columnKey ?? ""))

            cell.alignment = {
                vertical: "top",
                horizontal: statusStyle ? "center" : isObjectColumn ? "fill" : undefined,
                wrapText: false,
            }
            cell.border = {
                top: rowNumber === 1 ? tableBorder : innerBorder,
                right: columnNumber === lastDataColumn ? tableBorder : isDetailColumn ? detailColumnBorder : innerBorder,
                bottom: rowNumber === lastDataRow ? tableBorder : innerBorder,
                left: columnNumber === 1 ? tableBorder : isDetailColumn ? detailColumnBorder : innerBorder,
            }

            if (rowNumber > 1) {
                cell.fill = {
                    type: "pattern",
                    pattern: "solid",
                    fgColor: { argb: rowFill },
                }
            }

            if (rowNumber > 1 && statusStyle) {
                cell.fill = {
                    type: "pattern",
                    pattern: "solid",
                    fgColor: { argb: statusStyle.fill },
                }
                cell.font = {
                    bold: true,
                    color: { argb: statusStyle.font },
                }
            }
        })
    })

    const buffer = await workbook.xlsx.writeBuffer()
    downloadBlob(
        new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
        filename
    )
}

function buildFilename(filters: QueryFilters, ext: "json" | "csv" | "xlsx") {
    const parts = [`limit-${filters.limit}`]
    if (filters.dateStart) parts.push(`start-${filters.dateStart}`)
    if (filters.dateEnd) parts.push(`end-${filters.dateEnd}`)
    if (filters.statuses.length) parts.push(`status-${filters.statuses.join("-")}`)
    return `meter_job_${parts.join("_")}.${ext}`
}

function formatDate(value: string) {
    if (!value) return ""
    return new Date(value).toLocaleString("en-US", {
        month: "2-digit",
        day: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
    })
}

function formatExportDateTime(value: string) {
    if (!value) return ""
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value

    const pad = (part: number) => String(part).padStart(2, "0")

    return [
        pad(date.getMonth() + 1),
        pad(date.getDate()),
        date.getFullYear(),
    ].join("/") + " " + [
        pad(date.getHours()),
        pad(date.getMinutes()),
        pad(date.getSeconds()),
    ].join(":")
}

function getJobValue(job: MeterJob, key: SortKey) {
    if (key in job) return job[key as keyof MeterJob]
    return job.data?.results?.[key]?.status ?? ""
}

function getSearchText(job: MeterJob) {
    return [
        job.id,
        job.meter_id,
        job.work_order,
        job.hostname,
        job.name,
        job.status,
        job.created_at,
        JSON.stringify(job.data ?? {}),
        job.jctl,
    ].join(" ").toLowerCase()
}

function copyText(text: string, label: string) {
    navigator.clipboard.writeText(text)
    notify.info(`${label} copied`)
}

function JsonBlock({ value }: { value: unknown }) {
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)

    return (
        <section className="flex h-full min-h-0 flex-col">
            <pre className="min-h-0 max-w-full flex-1 overflow-auto rounded-md border bg-muted/40 p-2 text-xs leading-relaxed">
                {text || "No data"}
            </pre>
        </section>
    )
}

function ResultsSummary({ results }: { results?: MeterJob["data"]["results"] }) {
    const entries = Object.entries(results ?? {})

    return (
        <section className="flex h-full min-h-0 flex-col">
            <div className="min-h-0 flex-1 overflow-auto rounded-md border bg-muted/40 p-3 text-sm">
                {entries.length ? (
                    <div className="space-y-1">
                        {entries.map(([key, result]) => (
                            <p key={key} className="flex items-center gap-2">
                                <span className="min-w-36 font-medium">{key}</span>
                                <StatusPill status={(result?.status ?? "n/a") as JobStatus} />
                            </p>
                        ))}
                    </div>
                ) : (
                    <p className="text-muted-foreground">No results</p>
                )}
            </div>
        </section>
    )
}

function StatusPill({ status }: { status: JobStatus }) {
    return (
        <span
            className={cn(
                "inline-flex min-w-10 justify-center rounded border px-2 py-0.5 text-xs font-medium",
                statusClassName[status]
            )}
            title={status}
            aria-label={status}
        >
            <StatusIcon status={status} />
        </span>
    )
}

function StatusIcon({ status, className }: { status: JobStatus; className?: string }) {
    switch (status) {
        case "pass":
            return <Check className={cn("size-4", className)} />
        case "fail":
            return <X className={cn("size-4", className)} />
        case "missing":
            return <AlertTriangle className={cn("size-4", className)} />
        case "n/a":
            return <ShieldQuestion className={cn("size-4", className)} />
    }
}

function ToggleChip({
    active,
    label,
    ariaLabel,
    onClick,
}: {
    active: boolean
    label: React.ReactNode
    ariaLabel?: string
    onClick: () => void
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={ariaLabel}
            title={ariaLabel}
            className={cn(
                "inline-flex items-center justify-center rounded border px-2 py-1 text-xs",
                active
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-muted-foreground"
            )}
        >
            {label}
        </button>
    )
}

export default function Page() {
    const maxDate = React.useMemo(() => todayInputValue(), [])
    const [draftFilters, setDraftFilters] = React.useState<QueryFilters>(defaultFilters)
    const [activeFilters, setActiveFilters] = React.useState<QueryFilters>(defaultFilters)
    const [jobs, setJobs] = React.useState<MeterJob[]>([])
    const [loading, setLoading] = React.useState(false)
    const [exporting, setExporting] = React.useState<"json" | "csv" | "xlsx" | null>(null)
    const [error, setError] = React.useState("")
    const [search, setSearch] = React.useState("")
    const [sortKey, setSortKey] = React.useState<SortKey>("created_at")
    const [sortDirection, setSortDirection] = React.useState<SortDirection>("desc")
    const [visibleCoreColumns, setVisibleCoreColumns] = React.useState<Set<CoreColumnKey>>(new Set(defaultCoreColumns))
    const [visibleDataSections, setVisibleDataSections] = React.useState<Set<DataSectionKey>>(new Set(defaultDataSections))
    const [visibleExportSections, setVisibleExportSections] = React.useState<Set<ExportSectionKey>>(new Set(defaultExportSections))
    const [selectedJob, setSelectedJob] = React.useState<MeterJob | null>(null)
    const [detailTab, setDetailTab] = React.useState<DetailTabKey>("results-simple")
    const [hasQueried, setHasQueried] = React.useState(false)

    const hasMore = jobs.length > 0 && jobs.length % activeFilters.limit === 0

    React.useEffect(() => {
        if (detailTab === "results-json" && !visibleExportSections.has("results_json")) setDetailTab("results-simple")
        if (detailTab === "kwargs" && !visibleDataSections.has("kwargs")) setDetailTab("results-simple")
        if (detailTab === "journalctl" && !visibleDataSections.has("jctl")) setDetailTab("results-simple")
    }, [detailTab, visibleDataSections, visibleExportSections])

    const fetchJobs = React.useCallback(async (filters: QueryFilters, offset = 0) => {
        setLoading(true)
        setError("")

        try {
            const rows = await retrieveJobHistory(filters, offset)
            setJobs((current) => offset === 0 ? rows : [...current, ...rows])
        } catch (err) {
            const msg = err instanceof Error ? err.message : "Failed to fetch jobs"
            setError(msg)
            notify.error(msg)
        } finally {
            setLoading(false)
        }
    }, [])

    const filteredJobs = React.useMemo(() => {
        const query = search.trim().toLowerCase()
        const searched = query ? jobs.filter((job) => getSearchText(job).includes(query)) : jobs

        return [...searched].sort((a, b) => {
            const aValue = getJobValue(a, sortKey)
            const bValue = getJobValue(b, sortKey)

            if (sortKey === "created_at") {
                const diff = new Date(String(aValue)).getTime() - new Date(String(bValue)).getTime()
                return sortDirection === "asc" ? diff : -diff
            }

            if (typeof aValue === "number" && typeof bValue === "number") {
                return sortDirection === "asc" ? aValue - bValue : bValue - aValue
            }

            const diff = String(aValue ?? "").localeCompare(String(bValue ?? ""), undefined, { numeric: true })
            return sortDirection === "asc" ? diff : -diff
        })
    }, [jobs, search, sortDirection, sortKey])

    const handleSort = (key: SortKey) => {
        if (sortKey === key) {
            setSortDirection((current) => current === "asc" ? "desc" : "asc")
            return
        }

        setSortKey(key)
        setSortDirection(key === "created_at" ? "desc" : "asc")
    }

    const setDateStart = (dateStart: string) => {
        setDraftFilters((current) => ({
            ...current,
            dateStart,
            dateEnd: !current.dateEnd && dateStart
                ? dateStart
                : current.dateEnd && dateStart && dateStart > current.dateEnd
                ? dateStart
                : current.dateEnd,
        }))
    }

    const setDateEnd = (dateEnd: string) => {
        setDraftFilters((current) => ({
            ...current,
            dateStart: !current.dateStart && dateEnd
                ? dateEnd
                : current.dateStart && dateEnd && dateEnd < current.dateStart
                ? dateEnd
                : current.dateStart,
            dateEnd,
        }))
    }

    const applyFilters = () => {
        const filters = { ...draftFilters }
        setActiveFilters(filters)
        setHasQueried(true)
        fetchJobs(filters, 0)
    }

    const resetFilters = () => {
        setDraftFilters(defaultFilters)
        setActiveFilters(defaultFilters)
        setSearch("")
        setJobs([])
        setHasQueried(false)
    }

    const loadMore = () => fetchJobs(activeFilters, jobs.length)

    const exportRows = async (ext: "json" | "csv" | "xlsx") => {
        setExporting(ext)
        setError("")

        try {
            const rows = filteredJobs
            if (ext === "xlsx") {
                await exportToExcel(rows, visibleCoreColumns, visibleExportSections, visibleDataSections, buildFilename(activeFilters, ext))
                return
            }

            const content = ext === "json"
                ? JSON.stringify(projectRowsForJson(rows, visibleCoreColumns, visibleExportSections, visibleDataSections), null, 2)
                : convertToCsv(rows, visibleCoreColumns, visibleExportSections, visibleDataSections)
            downloadFile(
                content,
                buildFilename(activeFilters, ext),
                ext === "json" ? "application/json" : "text/csv;charset=utf-8;"
            )
        } catch (err) {
            const msg = err instanceof Error ? err.message : `Failed to export ${ext.toUpperCase()}`
            setError(msg)
            notify.error(msg)
        } finally {
            setExporting(null)
        }
    }

    const toggleCoreColumn = (column: CoreColumnKey) => {
        setVisibleCoreColumns((current) => {
            const next = new Set(current)
            if (next.has(column)) next.delete(column)
            else next.add(column)
            return next
        })
    }

    const toggleDataSection = (section: DataSectionKey) => {
        setVisibleDataSections((current) => {
            const next = new Set(current)
            if (next.has(section)) next.delete(section)
            else next.add(section)
            return next
        })
    }

    const toggleExportSection = (section: ExportSectionKey) => {
        setVisibleExportSections((current) => {
            const next = new Set(current)
            if (next.has(section)) next.delete(section)
            else next.add(section)
            return next
        })
    }

    const toggleStatusFilter = (status: JobStatus) => {
        setDraftFilters((current) => {
            const selected = current.statuses.includes(status)
                ? current.statuses.filter((item) => item !== status)
                : [...current.statuses, status]

            return { ...current, statuses: selected }
        })
    }

    const renderSortIcon = (key: SortKey) => {
        if (sortKey !== key) return null
        return sortDirection === "asc" ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />
    }

    const renderCoreCell = (job: MeterJob, key: CoreColumnKey) => {
        switch (key) {
            case "status":
                return <StatusPill status={job.status} />
            case "id":
                return job.id
            case "hostname":
                return job.hostname ?? ""
            case "meter_id":
                return job.meter_id
            case "work_order":
                return job.work_order ?? ""
            case "name":
                return job.name
            case "created_at":
                return formatDate(job.created_at)
        }
    }

    const copySelectedDetail = () => {
        if (!selectedJob) return

        switch (detailTab) {
            case "results-simple":
                copyText(JSON.stringify(simpleResultsObject(selectedJob.data?.results), null, 2), "results simple")
                return
            case "results-json":
                copyText(JSON.stringify(resultsObject(selectedJob.data?.results), null, 2), "results")
                return
            case "kwargs":
                copyText(JSON.stringify(selectedJob.data?.kwargs ?? {}, null, 2), "kwargs")
                return
            case "journalctl":
                copyText(selectedJob.jctl ?? "", "journalctl")
        }
    }

    return (
        <main className="h-screen overflow-y-auto bg-background p-4 text-foreground md:p-6">
            <div className="flex w-full flex-col gap-4">
                <header className="flex flex-col gap-3 border-b pb-4 md:flex-row md:items-end md:justify-between">
                    <div>
                        <h1 className="text-2xl font-semibold tracking-normal">Meter Job DB Viewer</h1>
                        <p className="text-sm text-muted-foreground">
                            {jobs.length} loaded, {filteredJobs.length} shown
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <Button variant="outline" onClick={() => fetchJobs(activeFilters, 0)} disabled={loading || !hasQueried}>
                            <RefreshCw className={cn(loading && "animate-spin")} />
                            Refresh
                        </Button>
                        <Button variant="outline" onClick={() => exportRows("json")} disabled={!!exporting || !hasQueried}>
                            <Download />
                            {exporting === "json" ? "Exporting" : "JSON"}
                        </Button>
                        <Button variant="outline" onClick={() => exportRows("csv")} disabled={!!exporting || !hasQueried}>
                            <Download />
                            {exporting === "csv" ? "Exporting" : "CSV"}
                        </Button>
                        <Button variant="outline" onClick={() => exportRows("xlsx")} disabled={!!exporting || !hasQueried}>
                            <Download />
                            {exporting === "xlsx" ? "Exporting" : "Excel"}
                        </Button>
                    </div>
                </header>

                <div className="flex min-w-0 flex-col gap-4">
                    <section className="rounded-md border bg-card p-3">
                        <div className="flex flex-col gap-4">
                            <section className="flex flex-wrap items-end gap-3">
                                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                                    <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                                        <Filter className="size-4" />
                                        Filters
                                    </div>
                                    <div className="flex gap-2">
                                        <Button size="sm" onClick={applyFilters} disabled={loading}>
                                            <Filter />
                                            Apply
                                        </Button>
                                        <Button variant="outline" size="icon" onClick={resetFilters} aria-label="Reset filters">
                                            <X />
                                        </Button>
                                    </div>
                                </div>
                                <label className="space-y-1">
                                    <span className="text-xs font-medium text-muted-foreground">Start</span>
                                    <Input
                                        type="date"
                                        max={maxDate}
                                        value={draftFilters.dateStart}
                                        onChange={(event) => setDateStart(event.target.value)}
                                    />
                                </label>
                                <label className="space-y-1">
                                    <span className="text-xs font-medium text-muted-foreground">End</span>
                                    <Input
                                        type="date"
                                        max={maxDate}
                                        value={draftFilters.dateEnd}
                                        onChange={(event) => setDateEnd(event.target.value)}
                                    />
                                </label>
                                <label className="space-y-1 md:w-[140px]">
                                    <span className="text-xs font-medium text-muted-foreground">Fetch Size</span>
                                    <select
                                        value={draftFilters.limit}
                                        onChange={(event) => setDraftFilters((current) => ({ ...current, limit: Number(event.target.value) }))}
                                        className="border-input h-9 w-full appearance-none rounded-md border bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
                                    >
                                        {[10, 25, 50, 100, 250, 500, 1000].map((limit) => (
                                            <option key={limit} value={limit}>{limit}</option>
                                        ))}
                                    </select>
                                </label>
                                <label className="min-w-80 flex-1 space-y-1">
                                    <span className="text-xs font-medium text-muted-foreground">Search loaded rows</span>
                                    <div className="relative">
                                        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                                        <Input
                                            className="pl-9"
                                            value={search}
                                            placeholder="hostname, job, JSON, logs..."
                                            onChange={(event) => setSearch(event.target.value)}
                                        />
                                    </div>
                                </label>
                            </section>

                            <section className="grid gap-3 border-t pt-3 xl:grid-cols-3">
                                <div className="rounded-md border p-2">
                                    <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                                        <Filter className="size-4" />
                                        Status
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {jobStatuses.map((status) => (
                                            <ToggleChip
                                                key={status}
                                                active={draftFilters.statuses.includes(status)}
                                                label={status}
                                                ariaLabel={status}
                                                onClick={() => toggleStatusFilter(status)}
                                            />
                                        ))}
                                    </div>
                                </div>

                                <div className="rounded-md border p-2">
                                    <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                                        <Columns3 className="size-4" />
                                        Core columns
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {coreColumns.map((column) => (
                                            <ToggleChip
                                                key={column.key}
                                                active={visibleCoreColumns.has(column.key)}
                                                label={column.label}
                                                onClick={() => toggleCoreColumn(column.key)}
                                            />
                                        ))}
                                    </div>
                                </div>

                                <div className="rounded-md border p-2">
                                    <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                                        <Columns3 className="size-4" />
                                        Export/detail sections
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {exportSections.map((section) => (
                                            <ToggleChip
                                                key={section.key}
                                                active={visibleExportSections.has(section.key)}
                                                label={section.label}
                                                onClick={() => toggleExportSection(section.key)}
                                            />
                                        ))}
                                        {dataSections.map((section) => (
                                            <ToggleChip
                                                key={section.key}
                                                active={visibleDataSections.has(section.key)}
                                                label={section.label}
                                                onClick={() => toggleDataSection(section.key)}
                                            />
                                        ))}
                                    </div>
                                </div>
                            </section>
                        </div>
                    </section>

                    <div className="flex min-w-0 flex-col gap-4">
                        {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

                        <section className="overflow-x-auto rounded-md border">
                            <table className="w-full min-w-[920px] border-collapse text-sm">
                                <thead className="sticky top-0 z-10 bg-muted">
                                    <tr>
                                        {coreColumns.filter((column) => visibleCoreColumns.has(column.key)).map((column) => (
                                            <th key={column.key} className="border-b px-3 py-2 text-left font-medium">
                                                <button
                                                    type="button"
                                                    className="inline-flex items-center gap-1"
                                                    onClick={() => handleSort(column.key)}
                                                >
                                                    {column.label}
                                                    {renderSortIcon(column.key)}
                                                </button>
                                            </th>
                                        ))}
                                        <th className="border-b px-3 py-2 text-right font-medium">Details</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredJobs.map((job) => (
                                        <tr key={job.id} className="border-b hover:bg-muted/50">
                                            {coreColumns.filter((column) => visibleCoreColumns.has(column.key)).map((column) => (
                                                <td
                                                    key={`${job.id}-${column.key}`}
                                                    className={cn(
                                                        "px-3 py-2",
                                                        column.key === "id" || column.key === "meter_id" || column.key === "work_order" ? "tabular-nums" : "",
                                                        column.key === "created_at" ? "whitespace-nowrap" : ""
                                                    )}
                                                >
                                                    {renderCoreCell(job, column.key)}
                                                </td>
                                            ))}
                                            <td className="px-3 py-2 text-right">
                                                <Button variant="ghost" size="icon" onClick={() => setSelectedJob(job)} aria-label={`View job ${job.id}`}>
                                                    <Eye />
                                                </Button>
                                            </td>
                                        </tr>
                                    ))}
                                    {!filteredJobs.length && (
                                        <tr>
                                            <td colSpan={visibleCoreColumns.size + 1} className="px-3 py-10 text-center text-muted-foreground">
                                                {loading ? "Loading jobs..." : hasQueried ? "No rows match the current view" : "Apply filters to load rows"}
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </section>

                        <footer className="flex items-center justify-between gap-3 pb-6">
                            <p className="text-xs text-muted-foreground">
                                Server filters define the loaded result set. Search, sorting, and columns affect loaded rows only.
                            </p>
                            <Button onClick={loadMore} disabled={loading || !hasMore || !hasQueried} variant="outline">
                                {loading ? "Loading" : !hasQueried ? "Apply filters first" : hasMore ? "Load more" : "No more rows"}
                            </Button>
                        </footer>
                    </div>
                </div>
            </div>

            <Dialog open={!!selectedJob} onOpenChange={(open) => !open && setSelectedJob(null)}>
                <DialogContent className="grid h-[85vh] min-w-[85vw] grid-rows-[auto_minmax(0,1fr)_auto] gap-2 overflow-hidden p-6">
                    {selectedJob && (
                        <>
                            <DialogHeader className="gap-1 space-y-0">
                                <DialogTitle className="flex flex-wrap items-center gap-2 leading-tight">
                                    Job {selectedJob.id}
                                    <StatusPill status={selectedJob.status} />
                                </DialogTitle>
                                <DialogDescription className="text-xs">
                                    {selectedJob.hostname ?? `meter ${selectedJob.meter_id}`}
                                    {visibleCoreColumns.has("work_order") && selectedJob.work_order != null ? ` - WO${selectedJob.work_order}` : ""}
                                    {" - "}
                                    {selectedJob.name} - {formatDate(selectedJob.created_at)}
                                </DialogDescription>
                            </DialogHeader>
                            <Tabs
                                value={detailTab}
                                onValueChange={(value) => setDetailTab(value as DetailTabKey)}
                                className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-1 overflow-hidden"
                            >
                                <div className="flex items-center gap-2">
                                    <TabsList className="flex h-8 flex-1 flex-wrap justify-start">
                                        <TabsTrigger value="results-simple">results simple</TabsTrigger>
                                        {visibleExportSections.has("results_json") && (
                                            <TabsTrigger value="results-json">results json</TabsTrigger>
                                        )}
                                        {visibleDataSections.has("kwargs") && (
                                            <TabsTrigger value="kwargs">kwargs</TabsTrigger>
                                        )}
                                        {visibleDataSections.has("jctl") && (
                                            <TabsTrigger value="journalctl">journalctl</TabsTrigger>
                                        )}
                                    </TabsList>
                                    <Button variant="outline" size="icon" onClick={copySelectedDetail} aria-label={`Copy ${detailTab}`}>
                                        <ClipboardCopy />
                                    </Button>
                                </div>
                                <TabsContent value="results-simple" className="h-full min-h-0 overflow-hidden">
                                    <ResultsSummary results={selectedJob.data?.results} />
                                </TabsContent>
                                {visibleExportSections.has("results_json") && (
                                    <TabsContent value="results-json" className="h-full min-h-0 overflow-hidden">
                                        <JsonBlock
                                            value={resultsObject(selectedJob.data?.results)}
                                        />
                                    </TabsContent>
                                )}
                                {visibleDataSections.has("kwargs") && (
                                    <TabsContent value="kwargs" className="h-full min-h-0 overflow-hidden">
                                        <JsonBlock value={selectedJob.data?.kwargs ?? {}} />
                                    </TabsContent>
                                )}
                                {visibleDataSections.has("jctl") && (
                                    <TabsContent value="journalctl" className="h-full min-h-0 overflow-hidden">
                                        <JsonBlock value={selectedJob.jctl ?? ""} />
                                    </TabsContent>
                                )}
                            </Tabs>
                            <DialogFooter className="gap-0 pt-0">
                                <DialogClose asChild>
                                    <Button variant="secondary">Close</Button>
                                </DialogClose>
                            </DialogFooter>
                        </>
                    )}
                </DialogContent>
            </Dialog>
        </main>
    )
}
