"use client"

import * as React from "react"
import { Check, ChevronLeft, CircleHelp, CreditCard, Globe2, Minus, Plus, Printer, Radio, X } from "lucide-react"
import { flask } from "@/lib/flask"
import { FUNCTION_KEYPAD_KEYS, MAIN_KEYPAD_ROWS, OperatorKeypadIcon } from "../dashboard/tabs/controls/operator-keypad-layout"
import type { OperatorFeedbackState, OperatorKeypadState } from "../dashboard/store/system"
import styles from "./virtual-meter.module.css"

type Coin = { id: string; kind: "coin"; country: string; currency: string; value: number; label: string; tone: string }
type Card = { id: string; kind: "card"; brand: string; label: string; nfc: boolean; accepted: boolean }
type Item = Coin | Card
type Snapshot = {
    ip: string; hostname: string; status: string; coins: Coin[]; cards: Card[]
    virtual: { session: string | null; device: string | null; screen_color: string | null; brightness: number; inserted_card: string | null; message: string; printed: number; passive_phase?: string | null }
    job: { current_action?: string; operator_feedback?: OperatorFeedbackState; operator_keypad?: OperatorKeypadState }
}
type Drag = { item: Item; x: number; y: number; phase: "drag" | "consume" | "toss" }
const iconMap = { accept: Check, back: ChevronLeft, cancel: X, down: Minus, globe: Globe2, help: CircleHelp, up: Plus }
function KeyIcon({ icon }: { icon?: OperatorKeypadIcon }) { const Icon = icon && iconMap[icon]; return Icon ? <Icon size={15} /> : null }

function ItemFace({ item }: { item: Item }) {
    if (item.kind === "coin") return <span className={`${styles.coin} ${styles[item.tone]}`}><small>{item.currency}</small><strong>{item.label}</strong><span>✦</span></span>
    return <span className={`${styles.card} ${styles[item.brand]}`}>
        <strong>{item.label}</strong><span className={styles.cardChip}>▥</span>
        <span className={styles.cardNumber}>•••• •••• •••• 0000</span>
        <span className={styles.cardBottom}>TEST CARD {item.nfc ? <Radio size={17} /> : <CreditCard size={17} />}</span>
        <span className={styles.stripe} />
    </span>
}

export default function MockMeterPage() {
    const [ip, setIp] = React.useState("")
    const [snapshot, setSnapshot] = React.useState<Snapshot | null>(null)
    const [error, setError] = React.useState("")
    const [notice, setNotice] = React.useState("")
    const [drag, setDrag] = React.useState<Drag | null>(null)
    const [selected, setSelected] = React.useState<Item | null>(null)
    const [hover, setHover] = React.useState<string | null>(null)
    const [touch, setTouch] = React.useState<{ x: number; y: number } | null>(null)
    const gesture = React.useRef<{ item: Item; x: number; y: number; moved: boolean } | null>(null)
    const animationTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
    const ready = !!snapshot && !error

    React.useEffect(() => {
        const meter = new URLSearchParams(window.location.search).get("meter")
        if (!meter) { setError("Open a meter from the dashboard using its MOCK button."); return }
        setIp(meter)
        const controller = new AbortController()
        let timer: ReturnType<typeof setTimeout>
        const poll = async () => {
            try {
                const response = await flask.get(`/mockmeter/${encodeURIComponent(meter)}`, { signal: controller.signal })
                const data = await response.json()
                if (!response.ok) throw new Error(data.error || "Unable to load mock meter")
                setSnapshot(data)
                setError("")
            } catch (err) {
                if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Connection lost")
            } finally {
                if (!controller.signal.aborted) timer = setTimeout(poll, 350)
            }
        }
        void poll()
        return () => { controller.abort(); clearTimeout(timer) }
    }, [])
    React.useEffect(() => () => { if (animationTimer.current) clearTimeout(animationTimer.current) }, [])

    const interact = async (payload: Record<string, unknown>) => {
        if (!ready) return null
        try {
            const response = await flask.post(`/mockmeter/${encodeURIComponent(ip)}`, {
                body: JSON.stringify({ ...payload, session: snapshot.virtual.session }),
            })
            const data = await response.json()
            if (!response.ok) throw new Error(data.error || "Interaction failed")
            if (data.message) setNotice(data.message)
            return data as { consumed?: boolean; message?: string }
        } catch (err) {
            setNotice(err instanceof Error ? err.message : "Interaction failed")
            return null
        }
    }
    const finishDrop = async (item: Item, target: string | null, x: number, y: number) => {
        setSelected(null)
        setHover(null)
        setDrag({ item, x, y, phase: "drag" })
        const result = target ? await interact({ kind: "drop", target, item: item.id }) : null
        if (animationTimer.current) clearTimeout(animationTimer.current)
        setDrag({ item, x, y, phase: result?.consumed ? "consume" : "toss" })
        animationTimer.current = setTimeout(() => setDrag(null), 550)
    }
    const readerAt = (x: number, y: number) => document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-reader]")?.dataset.reader ?? null
    const pointerDown = (event: React.PointerEvent<HTMLButtonElement>, item: Item) => {
        if (!ready || (drag && drag.phase !== "drag")) return
        event.currentTarget.setPointerCapture(event.pointerId)
        gesture.current = { item, x: event.clientX, y: event.clientY, moved: false }
    }
    const pointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
        const current = gesture.current
        if (!current) return
        if (Math.hypot(event.clientX - current.x, event.clientY - current.y) > 5) current.moved = true
        if (!current.moved) return
        setDrag({ item: current.item, x: event.clientX, y: event.clientY, phase: "drag" })
        setHover(readerAt(event.clientX, event.clientY))
    }
    const pointerUp = (event: React.PointerEvent<HTMLButtonElement>) => {
        const current = gesture.current
        gesture.current = null
        if (!current) return
        if (current.moved) void finishDrop(current.item, readerAt(event.clientX, event.clientY), event.clientX, event.clientY)
        else setSelected(current.item)
    }
    const placeSelectedItem = (event: React.MouseEvent<HTMLButtonElement>, target: string) => {
        if (!selected) return
        const rect = event.currentTarget.getBoundingClientRect()
        void finishDrop(selected, target, rect.left + rect.width / 2, rect.top + rect.height / 2)
    }
    const supply = (items: Item[]) => items.map(item => <button key={item.id} type="button"
        className={`${styles.supplyItem} ${selected?.id === item.id ? styles.selected : ""}`}
        disabled={!ready} aria-label={`Use ${item.kind === "coin" ? `${item.country} ${item.label}` : `${item.label}, ${item.nfc ? "NFC and stripe" : "stripe only"}`}`}
        onPointerDown={event => pointerDown(event, item)} onPointerMove={pointerMove} onPointerUp={pointerUp}
        onPointerCancel={() => { gesture.current = null; setDrag(null); setHover(null) }}
        onClick={event => { if (event.detail === 0) setSelected(item) }}>
        <ItemFace item={item} />
        <span className={styles.itemCaption}>{item.kind === "coin" ? item.country : item.nfc ? "NFC + stripe" : "Stripe only"}</span>
    </button>)
    const state = snapshot?.virtual
    const feedback = snapshot?.job.operator_feedback
    const keypad = snapshot?.job.operator_keypad
    const inserted = snapshot?.cards.find(card => card.id === state?.inserted_card)
    const device = state?.device
    const passiveRunning = snapshot?.job.current_action === "cycle_all"
    const passivePhase = state?.passive_phase
    const canFail = ready && !!state?.session && !!device && snapshot?.status === "busy"
    const showFeedback = feedback?.active || (passiveRunning && feedback?.test.startsWith("passive_"))
    const activeTitle = showFeedback ? feedback?.title : device === "keypad" ? "Keypad test" : "Ready for testing"

    return <main className={styles.page}>
        <header className={styles.header}>
            <div><span className={styles.eyebrow}>BURNING STATION / VIRTUAL LAB</span><h1>Mock meter <span>{snapshot?.hostname ?? ""}</span></h1></div>
            <div className={styles.connection}><span className={ready ? styles.online : styles.offline} />{ready ? `${ip} · US meter` : "Disconnected"}<a href="/dashboard" target="_blank" rel="noreferrer">Dashboard ↗</a></div>
        </header>
        {error && <div className={styles.error} role="alert">{error}</div>}
        {!snapshot && !error && <p className={styles.loading}>Connecting to your mock meter…</p>}
        <div className={styles.workspace}>
            <section className={styles.meterSide} aria-label="Virtual meter">
                <div className={styles.meter}>
                    <div className={styles.meterTop}><span>BS / {snapshot?.hostname ?? "MOCK"}</span><div className={styles.meterActions}><span className={styles.mockBadge}>MOCK</span><button type="button" className={styles.failButton} disabled={!canFail} onClick={() => void interact({ kind: "fail" })} title="Fail the current mock test">FAIL</button></div></div>
                    <button type="button" disabled={!ready} className={styles.screen}
                        aria-label="Touch the meter screen"
                        style={{ background: state?.screen_color || undefined, filter: device === "display_brightness" ? `brightness(${Math.max(0.15, (state?.brightness ?? 99) / 99)})` : undefined }}
                        onClick={event => {
                            if (selected) { const r = event.currentTarget.getBoundingClientRect(); void finishDrop(selected, null, r.left + r.width / 2, r.top + r.height / 2); return }
                            const rect = event.currentTarget.getBoundingClientRect()
                            const x = event.detail === 0 ? 0.5 : (event.clientX - rect.left) / rect.width
                            const y = event.detail === 0 ? 0.5 : (event.clientY - rect.top) / rect.height
                            setTouch({ x, y }); void interact({ kind: "touch", x, y })
                        }}>
                        <span className={styles.screenTop}>UNITED STATES <span>{passiveRunning ? "AUTOMATIC PASSIVE TEST" : device ? "TEST IN PROGRESS" : "DIAGNOSTICS"}</span></span>
                        <span className={styles.screenMain}><strong>{activeTitle}</strong><span>{device === "display_brightness" ? "Testing screen brightness. Confirm on the dashboard." : device === "keypad" ? "Press each highlighted key." : showFeedback ? feedback?.instruction : state?.message ?? "Waiting for meter"}</span></span>
                        <span className={styles.screenBottom}>{showFeedback && feedback && feedback.total > 0 ? `${feedback.current} / ${feedback.total} ${passiveRunning ? "repetitions complete" : ""}` : device === "keypad" ? `${keypad?.current ?? 0} / ${keypad?.total ?? 0} keys` : "Start a test from the dashboard"}</span>
                        {passivePhase && (device === "modem" || device === "call in") && <span className={styles.networkActivity} data-phase={passivePhase}><Radio size={15} />{passivePhase}</span>}
                        {touch && device === "touchscreen" && <span className={styles.touchMarker} style={{ left: `${touch.x * 100}%`, top: `${touch.y * 100}%` }}>+</span>}
                    </button>
                    <div className={styles.readers}>
                        <button type="button" data-reader="coin" data-passive-phase={device === "coin shutter" ? passivePhase : undefined} className={`${styles.reader} ${hover === "coin" ? styles.over : ""}`} disabled={!ready} onClick={e => placeSelectedItem(e, "coin")}><span className={styles.coinSlot} /><strong>COINS</strong><small>{device === "coin shutter" ? `Shutter ${passivePhase}` : "US coins accepted"}</small></button>
                        <button type="button" data-reader="nfc" data-passive-phase={device === "nfc" ? passivePhase : undefined} className={`${styles.reader} ${hover === "nfc" ? styles.over : ""}`} disabled={!ready} onClick={e => placeSelectedItem(e, "nfc")}><Radio size={32} /><strong>TAP CARD</strong><small>{device === "nfc" ? `Reader ${passivePhase}` : "Visa · Mastercard"}</small></button>
                        <button type="button" data-reader="stripe" className={`${styles.reader} ${hover === "stripe" ? styles.over : ""}`} disabled={!ready} onClick={e => placeSelectedItem(e, "stripe")} onDoubleClick={() => void interact({ kind: "remove_card" })}>
                            <span className={styles.cardSlot}>{inserted && <span className={styles.insertedCard}>{inserted.label}</span>}</span><strong>CARD READER</strong><small>{inserted ? "Double-click to remove & read" : "Insert magnetic stripe"}</small>
                        </button>
                    </div>
                    {inserted && <button className={styles.eject} onClick={() => void interact({ kind: "remove_card" })}>Remove {inserted.label} card ↑</button>}
                    <div className={styles.keypad} aria-label="Meter keypad">
                        {[...FUNCTION_KEYPAD_KEYS, ...MAIN_KEYPAD_ROWS.flat()].map(key => {
                            const expected = keypad?.expected_buttons.includes(key.button)
                            const done = (keypad?.counts[key.button] ?? 0) >= (keypad?.required_per_button || Infinity)
                            return <button key={key.button} type="button" title={key.title ?? key.button} aria-label={key.button}
                                style={{ gridColumn: key.colSpan === 2 ? "span 2" : undefined }}
                                className={`${styles.key} ${device === "keypad" && expected ? done ? styles.keyDone : styles.keyExpected : ""}`}
                                disabled={!ready || device !== "keypad"} onClick={() => void interact({ kind: "keypad", button: key.button })}>
                                <KeyIcon icon={key.icon} />{key.label}{device === "keypad" && expected && <small>{keypad?.counts[key.button] ?? 0}/{keypad?.required_per_button}</small>}
                            </button>
                        })}
                    </div>
                    <div className={styles.printer} data-passive-phase={device === "printer" ? passivePhase : undefined}><div><Printer size={17} /><span>LASER PRINTER</span><small>{device === "printer" && passivePhase === "printing" ? "Printing…" : state?.printed ? `${state.printed} printed` : "Ready"}</small></div><span className={styles.printSlot} />{(state?.printed ?? 0) > 0 && <span key={state?.printed} className={styles.receipt}>BURNING STATION<br />{snapshot?.hostname}<br />MOCK METER · US<br />────────────<br />Test information</span>}</div>
                </div>
                <div className={styles.liveNotice} role="status">{passiveRunning ? feedback?.instruction || state?.message : notice || state?.message || "Waiting for connection"}</div>
            </section>
            <aside className={styles.inventory} aria-label="Reusable test items">
                <div className={styles.inventoryHeader}><div><span className={styles.eyebrow}>INFINITE SUPPLY</span><h2>Test items</h2></div><span className={styles.infinity}>∞</span></div>
                <p className={styles.hint}>Drag an item onto a reader, or select it and click a reader. Drop elsewhere to toss it away.</p>
                {selected && <div className={styles.selectionNotice}>{selected.label} selected <button onClick={() => setSelected(null)}>Cancel</button></div>}
                <h3>United States <span>Recognized</span></h3><div className={styles.coins}>{supply(snapshot?.coins.filter(coin => coin.currency === "USD") ?? [])}</div>
                <h3>United Kingdom <span>Unknown to this meter</span></h3><div className={styles.coins}>{supply(snapshot?.coins.filter(coin => coin.currency === "GBP") ?? [])}</div>
                <h3>Around the world <span>10 foreign coins</span></h3><div className={styles.coins}>{supply(snapshot?.coins.filter(coin => !["USD", "GBP"].includes(coin.currency)) ?? [])}</div>
                <h3>Payment cards <span>Visa & Mastercard accepted</span></h3><div className={styles.cards}>{supply(snapshot?.cards ?? [])}</div>
                <p className={styles.hint}>All cards have a magnetic stripe. Only cards marked NFC can be tapped. Items are reusable.</p>
            </aside>
        </div>
        {drag && <div className={styles.dragLayer} style={{ left: drag.x, top: drag.y }}><div className={styles[drag.phase]}><ItemFace item={drag.item} /></div></div>}
    </main>
}
