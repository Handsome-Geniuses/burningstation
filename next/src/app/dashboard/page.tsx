'use client'
import { Tabination, TabItem } from "@/components/ui/tabination"
import { StoreProvider, useStoreContext } from "./store"
import { SettingsTab } from "./tabs/settings"
import { Header } from "./header/header"
import React from "react"
import { ControlsTab } from "./tabs/controls"
import { MonitorTab } from "./tabs/monitor"
import { SecretTab } from "./tabs/secret"
import { HistoryTab } from "./tabs/history/page"


const Dashboard = () => {
    const { systemState } = useStoreContext()
    const tabs: TabItem[] = [
        { value: "Controls", content: <ControlsTab /> },
        { value: "Monitor", content: <MonitorTab /> },
        { value: "History", content: <HistoryTab /> },
        { value: "Settings", content: <SettingsTab /> }
    ]
    if (systemState.handsome) tabs.push({ value: "Secret", content: <SecretTab /> })
    return (
        <>
            <Header />
            <Tabination tabs={tabs} />
        </>
    )
}

export default () => {

    return (
        <div className="w-screen h-screen bg-neutral-500 overflow-hidden flex justify-center items-center">
            <div className="bg-background relative w-[1920px] h-[1080px] flex flex-col">
                <StoreProvider>
                    <Dashboard />
                </StoreProvider>
            </div>
        </div>
    )
}