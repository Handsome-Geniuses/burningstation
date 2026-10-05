import * as React from "react"
import { Check, X, Activity } from "lucide-react"
import { useStoreContext } from "../../store"
import { ActivityEntry, failureDetails, formatDuration } from "../../store/activity"
import { cn } from "@/lib/utils"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

const jobNames: Record<string, string> = {
    cycle_all: "Passive job",
    physical_cycle_all: "Physical job",
    operator_cycle_all: "Operator job",
}
const label = (entry: ActivityEntry) => jobNames[entry.name] ?? entry.name.replaceAll("_", " ")

export function StatusPanelContent() {
    const { activity } = useStoreContext()
    const [selected, setSelected] = React.useState<ActivityEntry | null>(null)
    const list = React.useRef<HTMLDivElement>(null)
    const latestId = activity[0]?.id

    React.useEffect(() => {
        list.current?.scrollTo({ top: 0 })
    }, [latestId])

    return (
        <>
            <div ref={list} className="scrollbar-hide h-full min-h-0 overflow-y-auto overscroll-contain" aria-label="Recent station activity">
                {activity.length === 0 ? (
                    <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-muted-foreground">
                        <Activity className="size-6 opacity-60" />
                        <p className="text-sm">No recent activity</p>
                        <p className="text-xs">Completed jobs will appear here.</p>
                    </div>
                ) : activity.map(entry => {
                    const failed = entry.status === "fail"
                    const duration = formatDuration(entry.data?.duration_s)
                    const fresh = entry.receivedAt !== undefined && Date.now() - entry.receivedAt < 800
                    const Icon = failed ? X : Check
                    return (
                        <button
                            key={entry.id}
                            type="button"
                            onClick={() => setSelected(entry)}
                            aria-label={`${entry.hostname}, ${label(entry)}, ${failed ? "failed" : "success"}${duration ? `, ${duration}` : ""}. View overview`}
                            className={cn(
                                "relative flex w-full items-center gap-2 border-b border-border border-l-2 px-3 py-2 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                                failed ? "status-entry-failed border-l-destructive bg-destructive/5 hover:bg-destructive/10" : "border-l-primary bg-primary/5 hover:bg-primary/10",
                                fresh && "status-entry-new"
                            )}
                        >
                            <Icon aria-hidden="true" className={cn("size-4 shrink-0", failed ? "text-destructive" : "text-primary")} />
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm font-medium" title={entry.hostname}>{entry.hostname}</span>
                                <span className="block truncate text-xs text-muted-foreground" title={label(entry)}>{label(entry)}</span>
                            </span>
                            {duration && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{duration}</span>}
                        </button>
                    )
                })}
            </div>
            <Dialog open={selected !== null} onOpenChange={open => { if (!open) setSelected(null) }}>
                {selected && (
                    <DialogContent className="max-h-[80dvh] overflow-y-auto sm:max-w-lg">
                        <DialogHeader>
                            <DialogTitle className="break-words pr-4">{selected.hostname}</DialogTitle>
                            <DialogDescription>{label(selected)}</DialogDescription>
                        </DialogHeader>
                        <div className={cn("flex items-center gap-2 rounded-md border p-3", selected.status === "fail" ? "border-destructive/30 bg-destructive/5" : "border-primary/30 bg-primary/5")}>
                            {selected.status === "fail" ? <X className="size-5 text-destructive" /> : <Check className="size-5 text-primary" />}
                            <span className="font-medium">{selected.status === "fail" ? "Failed" : "Success"}</span>
                            <span className="ml-auto text-sm tabular-nums text-muted-foreground">{formatDuration(selected.data?.duration_s) ?? "Duration unavailable"}</span>
                        </div>
                        {selected.status === "fail" && (
                            <div className="space-y-2 text-sm">
                                <p className="font-medium">What went wrong</p>
                                <ul className="list-disc space-y-2 pl-5 text-muted-foreground">
                                    {failureDetails(selected).map(reason => <li key={reason} className="whitespace-pre-wrap break-words">{reason}</li>)}
                                </ul>
                            </div>
                        )}
                    </DialogContent>
                )}
            </Dialog>
        </>
    )
}
