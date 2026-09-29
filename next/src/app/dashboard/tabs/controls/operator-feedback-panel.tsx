import * as React from "react"

import { Button } from "@/components/ui/button"
import { submitOperatorFeedbackResponse } from "@/lib/ep"
import { cn } from "@/lib/utils"

import type { OperatorFeedbackState } from "../../store/system"

type Props = {
    meterIp: string
    feedback: OperatorFeedbackState
}

const asRecord = (value: unknown): Record<string, unknown> =>
    value && typeof value === "object" && !Array.isArray(value)
        ? value as Record<string, unknown>
        : {}

const asList = (value: unknown): unknown[] => Array.isArray(value) ? value : []
const asText = (value: unknown, fallback = "—") => typeof value === "string" || typeof value === "number" ? String(value) : fallback
const asNumber = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : 0

export function OperatorFeedbackPanel({ meterIp, feedback }: Props) {
    const [sending, setSending] = React.useState(false)
    const [answerSent, setAnswerSent] = React.useState(false)
    const { details } = feedback
    const progress = feedback.total > 0 ? Math.min(100, feedback.current / feedback.total * 100) : 0

    React.useEffect(() => {
        setSending(false)
        setAnswerSent(false)
    }, [feedback.test, feedback.status])

    const sendBrightnessAnswer = async (value: boolean) => {
        setSending(true)
        try {
            await submitOperatorFeedbackResponse(meterIp, feedback.test, value)
            setAnswerSent(true)
        } catch {
            setSending(false)
        }
    }

    return (
        <div className="space-y-4 p-4">
            <div className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold">{feedback.title}</h3>
                    <span className="rounded-full border px-2 py-0.5 text-xs capitalize text-muted-foreground">
                        {feedback.status.replaceAll("_", " ")}
                    </span>
                </div>
                <p className="text-sm text-muted-foreground">{feedback.instruction}</p>
            </div>

            {feedback.total > 0 && (
                <div className="space-y-1">
                    <div className="flex justify-between text-sm"><span>Progress</span><span>{feedback.current} / {feedback.total}</span></div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                        <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
                    </div>
                </div>
            )}

            {feedback.error && <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">{feedback.error}</div>}

            {feedback.test === "card_reader" && <CardReaderDetails details={details} />}
            {feedback.test === "coins" && <CoinDetails details={details} />}
            {feedback.test === "contactless" && <ContactlessDetails details={details} />}
            {feedback.test === "touchscreen" && <TouchscreenDetails details={details} />}
            {feedback.test === "display_brightness" && feedback.status === "awaiting_response" && (
                <div className="rounded-md border p-3 space-y-3">
                    <p className="text-sm">Wait until the screen visibly alternates between dim and bright, then answer.</p>
                    {answerSent ? <p className="text-sm text-muted-foreground">Answer submitted; restoring the display shortly.</p> : (
                        <div className="grid grid-cols-2 gap-2">
                            <Button onClick={() => void sendBrightnessAnswer(true)} disabled={sending}>Yes, changing</Button>
                            <Button variant="destructive" onClick={() => void sendBrightnessAnswer(false)} disabled={sending}>No, not changing</Button>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

function CardReaderDetails({ details }: { details: Record<string, unknown> }) {
    const reads = asList(details.reads).map(asRecord)
    return <div className="space-y-2">
        <p className="text-sm font-medium">Card reads</p>
        {reads.length === 0 ? <p className="text-sm text-muted-foreground">Waiting for a card read.</p> : reads.map((read, index) => {
            const passed = read.classification === "pass"
            const reasons = asList(read.retry_reasons).map(reason => asText(reason)).join("; ")
            return <div key={`${asText(read.read_number)}-${index}`} className={cn("rounded-md border p-2 text-xs", passed ? "border-emerald-500/50" : "border-amber-500/50")}>
                <div className="flex justify-between font-medium"><span>Read {asText(read.read_number)}</span><span>{passed ? "accepted for test" : "try again"}</span></div>
                <div>{asText(read.read_type_name)} · {asText(read.card_type_name)} · hash {asText(read.card_hash_hex)}</div>
                <div>Meter accepted: {read.is_card_accepted === true ? "yes" : "no"}</div>
                {reasons && <div className="mt-1 text-amber-600">{reasons}</div>}
            </div>
        })}
    </div>
}

function CoinDetails({ details }: { details: Record<string, unknown> }) {
    const detections = asRecord(details.detections)
    const cleanup = asRecord(details.cleanup)
    return <div className="space-y-2">
        {cleanup.attempted === true && <p className={cn("rounded-md border p-2 text-sm", cleanup.success === false ? "border-destructive text-destructive" : "text-muted-foreground")}>Clearing coin tallies{cleanup.success === true ? " complete." : "…"}</p>}
        <div className="space-y-2">{Object.entries(detections).map(([name, value]) => {
            const coin = asRecord(value)
            return <div key={name} className="rounded-md border p-2 text-sm">
                <div className="flex justify-between font-medium"><span>{name}</span><span>{asNumber(coin.credited)} / {asNumber(coin.required)}</span></div>
                <div className="text-xs text-muted-foreground">{asText(coin.currency_code)} {asText(coin.value_minor)} · detected {asNumber(coin.detected)} · accepted {asNumber(coin.accepted)} · rejected {asNumber(coin.rejected)}</div>
            </div>
        })}</div>
    </div>
}

function ContactlessDetails({ details }: { details: Record<string, unknown> }) {
    const attempts = asList(details.attempts).map(asRecord)
    return <div className="space-y-2">
        <p className="text-sm">Reader status: <span className="font-medium capitalize">{asText(details.reader_state).replaceAll("_", " ")}</span></p>
        {attempts.map((attempt, index) => <div key={`${asText(attempt.attempt_number)}-${index}`} className="rounded-md border p-2 text-xs">
            Attempt {asText(attempt.attempt_number)}: <span className="font-medium">{asText(attempt.status)}</span>{attempt.card_masked ? ` · ${asText(attempt.card_masked)}` : ""}{attempt.retry_reason ? ` · ${asText(attempt.retry_reason)}` : ""}
        </div>)}
    </div>
}

function TouchscreenDetails({ details }: { details: Record<string, unknown> }) {
    const touches = asList(details.touches).map(asRecord)
    return <div className="space-y-2">
        <p className="text-sm text-muted-foreground">Each numbered marker is a detected touch location.</p>
        <div className="relative aspect-[5/3] overflow-hidden rounded-md border bg-muted/30">
            {touches.map((touch, index) => {
                const x = Math.max(0, Math.min(1, asNumber(touch.physical_x))) * 100
                const y = Math.max(0, Math.min(1, asNumber(touch.physical_y))) * 100
                return <span key={`${asText(touch.number)}-${index}`} className="absolute grid size-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-primary text-xs font-bold text-primary-foreground" style={{ left: `${x}%`, top: `${y}%` }}>{asText(touch.number)}</span>
            })}
        </div>
        {touches.length > 0 && <p className="text-xs text-muted-foreground">Latest: {asText(touches.at(-1)?.x)}, {asText(touches.at(-1)?.y)}</p>}
    </div>
}
